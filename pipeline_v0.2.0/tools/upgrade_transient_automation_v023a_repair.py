#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
import py_compile
import re
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
AUTO = ROOT / "automation"
STAGE = AUTO / "stages" / "inventory_science25_analogue_exposures_v028br.py"
RUNNER = AUTO / "runner.py"
INIT = AUTO / "__init__.py"
BACKUP = AUTO / "backups" / "pre_v023a_repair"

NONNEG_HELPER = '''
def nonneg_i(v, default=None):
    value = i(v, default=None)
    if value is None or value < 0:
        return default
    return value
'''


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.2.5a — QUERYEXPS MASKED EXPOSURE IDENTITY")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
    print("No scientific outputs or candidate state are changed by this repair.\\n")

    if not STAGE.is_file():
        print(f"FAIL missing stage: {STAGE}")
        return 2

    text = STAGE.read_text(encoding="utf-8")

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (STAGE, RUNNER, INIT):
        if p.is_file():
            dst = BACKUP / p.name
            if not dst.exists():
                shutil.copy2(p, dst)

    if "def nonneg_i(v, default=None):" not in text:
        marker = "\\ndef s(v):\\n"
        if marker not in text:
            print("FAIL could not locate s() insertion marker")
            return 3
        text = text.replace(marker, "\\n" + NONNEG_HELPER.strip() + "\\n" + marker, 1)
        print("Patched: added nonneg_i() for DR7 nonnegative-or-masked integer fields")
    else:
        print("Patched: nonneg_i() already present")

    replacements = {
        '    platenum = i(first(row, "platenum", "plateNum", "plate_num"))':
            '    platenum = nonneg_i(first(row, "platenum", "plateNum", "plate_num"))',
        '    mosnum = i(first(row, "mosnum", "mosNum", "mosaicNum"))':
            '    mosnum = nonneg_i(first(row, "mosnum", "mosNum", "mosaicNum"))',
        '    solnum = i(first(row, "solnum", "solNum", "solutionNumber"))':
            '    solnum = nonneg_i(first(row, "solnum", "solNum", "solutionNumber"))',
        '    expnum = i(first(row, "expnum", "expNum", "exposureNum"))':
            '    expnum = nonneg_i(first(row, "expnum", "expNum", "exposureNum"))',
        '    nsol_apass = i(first(row, "nSolutionsApass", "n_solutions_apass"), 0) or 0':
            '    nsol_apass = nonneg_i(first(row, "nSolutionsApass", "n_solutions_apass"), 0) or 0',
        '    nsol_atlas = i(first(row, "nSolutionsAtlas", "n_solutions_atlas"), 0) or 0':
            '    nsol_atlas = nonneg_i(first(row, "nSolutionsAtlas", "n_solutions_atlas"), 0) or 0',
    }

    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
            print(f"Patched: {old.strip()} -> nonnegative-aware form")
        elif new in text:
            print(f"Patched: already present: {new.strip()}")
        else:
            print(f"FAIL expected normalize_exposure line not found: {old.strip()}")
            return 3

    old_identity = '''    has_imaging = mosnum is not None and solnum is not None
    apass_cal = bool(rid_apass) or nsol_apass > 0
    atlas_cal = bool(rid_atlas) or nsol_atlas > 0

    pid = plate_id(series, platenum)
    if has_imaging:
        identity = f"{series}:{platenum}:{mosnum}:{solnum}"
    else:
        identity = f"{series}:{platenum}:log:{expnum}"
'''

    new_identity = '''    has_imaging = mosnum is not None and solnum is not None
    apass_cal = bool(rid_apass) or nsol_apass > 0
    atlas_cal = bool(rid_atlas) or nsol_atlas > 0

    if series is None or platenum is None:
        raise RuntimeError(
            f"queryexps row lacks valid plate identity: "
            f"series={series!r} platenum={platenum!r}"
        )

    pid = plate_id(series, platenum)

    # Official DR7 exposure identity:
    #   imaging: series + platenum + mosnum + solnum
    #   logbook-only: series + platenum + expnum
    # Raw API masked integer fields may serialize using negative sentinels,
    # which nonneg_i() has converted to None above.
    if has_imaging:
        identity = f"{series}:{platenum}:mos:{mosnum}:sol:{solnum}"
        identity_kind = "IMAGING_WCS"
    elif expnum is not None:
        identity = f"{series}:{platenum}:log:{expnum}"
        identity_kind = "LOGBOOK_ONLY"
    else:
        raise RuntimeError(
            f"{target}: queryexps row has neither a valid imaging identity "
            f"nor a valid logbook exposure identity for plate {pid}; "
            f"raw mosnum={first(row, 'mosnum', 'mosNum', 'mosaicNum')!r} "
            f"solnum={first(row, 'solnum', 'solNum', 'solutionNumber')!r} "
            f"expnum={first(row, 'expnum', 'expNum', 'exposureNum')!r}"
        )
'''

    if old_identity in text:
        text = text.replace(old_identity, new_identity, 1)
        print("Patched: exposure identity now follows official DR7 imaging/logbook forms")
    elif 'identity_kind = "IMAGING_WCS"' in text:
        print("Patched: official DR7 exposure identity block already present")
    else:
        print("FAIL could not locate old exposure identity block")
        return 3

    old_return = '        "exposure_identity": identity,\\n        "has_imaging": has_imaging,'
    new_return = (
        '        "exposure_identity": identity,\\n'
        '        "exposure_identity_kind": identity_kind,\\n'
        '        "has_imaging": has_imaging,'
    )
    if old_return in text:
        text = text.replace(old_return, new_return, 1)
        print("Patched: output records exposure_identity_kind")
    elif '"exposure_identity_kind": identity_kind' in text:
        print("Patched: exposure_identity_kind already recorded")
    else:
        print("FAIL could not locate normalized return identity fields")
        return 3

    STAGE.write_text(text, encoding="utf-8")

    try:
        ast.parse(text)
        py_compile.compile(str(STAGE), doraise=True)
    except Exception as exc:
        print(f"FAIL repaired stage syntax/compile: {type(exc).__name__}: {exc}")
        return 4

    print("Repaired v028br stage compile: PASS")

    try:
        spec = importlib.util.spec_from_file_location("v028br_repair_test", STAGE)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot import repaired v028br")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)

        imaging = mod.normalize_exposure(
            {
                "series": "ai",
                "platenum": "43437",
                "mosnum": "0",
                "solnum": "1",
                "expnum": "-1",
                "nSolutionsApass": "1",
                "nSolutionsAtlas": "0",
            },
            "synthetic",
        )
        if not imaging["has_imaging"]:
            raise RuntimeError("synthetic imaging row not recognized as imaging")
        if imaging["exposure_identity"] != "ai:43437:mos:0:sol:1":
            raise RuntimeError(f"bad imaging identity {imaging['exposure_identity']!r}")
        if imaging["expnum"] is not None:
            raise RuntimeError("masked synthetic expnum=-1 was not normalized to None")

        logonly = mod.normalize_exposure(
            {
                "series": "ab",
                "platenum": "129",
                "mosnum": "-1",
                "solnum": "-1",
                "expnum": "2",
                "nSolutionsApass": "-1",
                "nSolutionsAtlas": "-1",
            },
            "synthetic",
        )
        if logonly["has_imaging"]:
            raise RuntimeError("masked mosnum/solnum=-1 incorrectly recognized as imaging")
        if logonly["exposure_identity"] != "ab:129:log:2":
            raise RuntimeError(f"bad logbook identity {logonly['exposure_identity']!r}")
        if logonly["n_solutions_apass"] != 0 or logonly["n_solutions_atlas"] != 0:
            raise RuntimeError("masked nSolutions sentinel did not normalize to zero")

        print(
            "Synthetic identity regressions: PASS "
            "(masked -1 -> None; imaging/logbook identities distinct)"
        )
    except Exception as exc:
        print(f"FAIL synthetic identity regression: {type(exc).__name__}: {exc}")
        return 5

    if RUNNER.is_file():
        runner = RUNNER.read_text(encoding="utf-8")
        runner = re.sub(
            r"Transient automation v[0-9.]+ - Order01 registry status",
            "Transient automation v0.2.6 - Order01 registry status",
            runner,
            count=1,
        )
        RUNNER.write_text(runner, encoding="utf-8")
    INIT.write_text('__version__ = "0.2.6"\\n', encoding="utf-8")

    failures = []
    py_files = sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
    print(f"\\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\\nREPAIR STATUS: FAIL")
        return 6

    try:
        sys.path.insert(0, str(ROOT))
        import automation.registry_order01 as regmod

        target = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_science25_analogue_exposure_inventory_v028br"
        )
        if getattr(target, "network_access", None) is not True:
            raise RuntimeError("v028br network_access is not True")
        print("\\nRegistry import regression: PASS (network_access=True)")
    except Exception as exc:
        print(f"\\nRegistry import regression: FAIL: {type(exc).__name__}: {exc}")
        return 7

    print("\\nREPAIR STATUS: PASS")
    print("\\nNext commands:")
    print(r'  & ".\\.venv\\Scripts\\python.exe" -m automation.runner status')
    print(r'  & ".\\.venv\\Scripts\\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\\.venv\\Scripts\\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_analogue_exposure_inventory_v028br'
    )
    print(
        "\\nThe cached science25 queryexps response will be reused if present; "
        "remaining target queries will be fetched as needed."
    )
    print("\\nDo not rerun upgrade_transient_automation_v023.py after this repair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
