#!/usr/bin/env python3
from __future__ import annotations

import ast
import py_compile
import re
import shutil
from pathlib import Path

ROOT = Path.cwd()
AUTO = ROOT / "automation"
STAGE = AUTO / "stages" / "query_science25_analogue_catalog_provenance_v028bq.py"
RUNNER = AUTO / "runner.py"
INIT = AUTO / "__init__.py"
BACKUP = AUTO / "backups" / "pre_v022b_repair"

SCIENCE_RESOLUTION_LINES = [
    "",
    "    # Resolve science #25 through the authoritative frozen native-candidate table.",
    "    # The v028ar science object intentionally does not guarantee RA/Dec fields.",
    "    native_rows = read_csv_file(NATIVE)",
    '    s25_tile_id = str(science[25].get("tile_id", ""))',
    '    s25_candidate_index = i(science[25].get("candidate_index"))',
    "",
    "    s25_native_matches = [",
    "        r for r in native_rows",
    '        if str(r.get("tile_id", "")) == s25_tile_id',
    '        and i(r.get("candidate_index")) == s25_candidate_index',
    "    ]",
    "    if len(s25_native_matches) != 1:",
    "        print(",
    '            f"FAIL science #25 native identity resolution: "',
    '            f"tile={s25_tile_id!r} candidate_index={s25_candidate_index!r} "',
    '            f"matches={len(s25_native_matches)}"',
    "        )",
    "        return 3",
    "",
    "    s25_native = s25_native_matches[0]",
    '    s25_ra = f(s25_native.get("ra_deg"))',
    '    s25_dec = f(s25_native.get("dec_deg"))',
    "    if s25_ra is None or s25_dec is None:",
    '        print("FAIL science #25 native row lacks valid ra_deg/dec_deg")',
    "        return 3",
    "",
    "    print(",
    '        f"Science #25 native identity resolved: "',
    '        f"{s25_tile_id}::{s25_candidate_index} "',
    '        f"RA={s25_ra:.9f} Dec={s25_dec:.9f}"',
    "    )",
    "",
]
SCIENCE_RESOLUTION = "\n".join(SCIENCE_RESOLUTION_LINES)

READCSV_LINES = [
    "",
    "def read_csv_file(path):",
    '    with path.open("r", encoding="utf-8-sig", newline="") as fh:',
    "        return list(csv.DictReader(fh))",
    "",
]
READCSV_FUNC = "\n".join(READCSV_LINES)


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.2.3b — v028bq SCIENCE #25 COORDINATE PROVENANCE")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
    print("No scientific outputs or candidate state are changed by this repair.\n")

    if not STAGE.is_file():
        print(f"FAIL missing stage: {STAGE}")
        return 2

    text = STAGE.read_text(encoding="utf-8")

    BACKUP.mkdir(parents=True, exist_ok=True)
    backup = BACKUP / STAGE.name
    if not backup.exists():
        shutil.copy2(STAGE, backup)
    if RUNNER.is_file() and not (BACKUP / "runner.py").exists():
        shutil.copy2(RUNNER, BACKUP / "runner.py")
    if INIT.is_file() and not (BACKUP / "__init__.py").exists():
        shutil.copy2(INIT, BACKUP / "__init__.py")

    # Add authoritative native-candidate input.
    native_decl = 'NATIVE = BASE / "order01_dasch_native_candidates.csv"'
    if native_decl not in text:
        marker = 'BO = BASE / "order01_dasch_science25_direct_shape_neighbourhood_v028bo.json"\n'
        if marker not in text:
            print("FAIL could not find BO constant insertion marker")
            return 3
        text = text.replace(marker, marker + native_decl + "\n", 1)
        print("Patched: added NATIVE candidate-table input")
    else:
        print("Patched: NATIVE candidate-table input already present")

    # Add CSV reader helper.
    if "def read_csv_file(path):" not in text:
        marker = "\ndef f(v, default=None):\n"
        if marker not in text:
            print("FAIL could not find f() helper insertion marker")
            return 3
        text = text.replace(marker, READCSV_FUNC + marker, 1)
        print("Patched: added read_csv_file() helper")
    else:
        print("Patched: read_csv_file() helper already present")

    # Hard-require native input.
    old_loop = "for p in (AR_JSON, BJ, BO):"
    new_loop = "for p in (AR_JSON, BJ, BO, NATIVE):"
    if old_loop in text:
        text = text.replace(old_loop, new_loop, 1)
        print("Patched: added NATIVE to input existence guard")
    elif new_loop in text:
        print("Patched: NATIVE already present in input guard")
    else:
        print("FAIL could not identify v028bq input existence guard")
        return 3

    # Insert science identity resolution after existing science #25 guard.
    if "Science #25 native identity resolved:" not in text:
        marker = (
            '    if 25 not in science:\n'
            '        print("FAIL science #25 missing")\n'
            '        return 3\n'
        )
        if marker not in text:
            print("FAIL could not find science #25 guard insertion marker")
            return 3
        text = text.replace(marker, marker + SCIENCE_RESOLUTION, 1)
        print("Patched: added exact native identity -> coordinate resolution")
    else:
        print("Patched: science #25 native coordinate resolution already present")

    # Replace invalid direct access.
    old_ra = '"ra_deg": float(science[25]["ra_deg"])'
    old_dec = '"dec_deg": float(science[25]["dec_deg"])'
    if old_ra in text:
        text = text.replace(old_ra, '"ra_deg": s25_ra', 1)
    if old_dec in text:
        text = text.replace(old_dec, '"dec_deg": s25_dec', 1)

    if 'science[25]["ra_deg"]' in text or 'science[25]["dec_deg"]' in text:
        print("FAIL invalid direct v028ar science coordinate access remains")
        return 4
    if '"ra_deg": s25_ra' not in text or '"dec_deg": s25_dec' not in text:
        print("FAIL science25 target block was not successfully patched")
        return 4
    print("Patched: science25 query target now uses native s25_ra/s25_dec")

    STAGE.write_text(text, encoding="utf-8")

    try:
        ast.parse(text)
        py_compile.compile(str(STAGE), doraise=True)
    except Exception as exc:
        print(f"FAIL repaired stage syntax/compile: {type(exc).__name__}: {exc}")
        return 5

    print("Repaired v028bq stage compile: PASS")

    if RUNNER.is_file():
        r = RUNNER.read_text(encoding="utf-8")
        r = re.sub(
            r"Transient automation v[0-9.]+ - Order01 registry status",
            "Transient automation v0.2.4 - Order01 registry status",
            r,
            count=1,
        )
        RUNNER.write_text(r, encoding="utf-8")
    INIT.write_text('__version__ = "0.2.4"\n', encoding="utf-8")

    failures = []
    py_files = sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\nREPAIR STATUS: FAIL")
        return 6

    try:
        import sys
        sys.path.insert(0, str(ROOT))
        import automation.registry_order01 as reg

        target = next(
            s for s in reg.ORDER01_STAGES
            if getattr(s, "stage_id", None)
            == "dasch_science25_analogue_catalog_provenance_v028bq"
        )
        if not getattr(target, "network_access"):
            raise RuntimeError("v028bq network_access is not True")
        print("\nRegistry import/network-gate regression: PASS (network_access=True)")
    except Exception as exc:
        print(f"\nRegistry import regression: FAIL: {type(exc).__name__}: {exc}")
        return 7

    print("\nREPAIR STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_analogue_catalog_provenance_v028bq'
    )
    print("\nDo not rerun v022 or v022a after this repair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
