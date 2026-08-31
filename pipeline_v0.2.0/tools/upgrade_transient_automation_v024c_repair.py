#!/usr/bin/env python3
from __future__ import annotations

import ast
import py_compile
import re
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
AUTO = ROOT / "automation"
INIT = AUTO / "__init__.py"
RUNNER = AUTO / "runner.py"
REGISTRY = AUTO / "registry_order01.py"
BR = AUTO / "stages" / "inventory_science25_analogue_exposures_v028br.py"
BS = AUTO / "stages" / "plan_matched_recurrence_v028bs.py"
BACKUP = AUTO / "backups" / "pre_v024c_bootstrap_repair"

EXPECTED_VERSION = "0.2.9"
EXPECTED_BANNER = "Transient automation v0.2.9 - Order01 registry status"


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.2.8c — PACKAGE BOOTSTRAP / __init__.py")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
    print("No scientific outputs or candidate state are changed.")
    print("This repairs the literal \\\\n written into automation/__init__.py.\n")

    for p in (INIT, RUNNER, REGISTRY, BR, BS):
        if not p.is_file():
            print(f"FAIL missing required file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (INIT, RUNNER, REGISTRY, BR, BS):
        dst = BACKUP / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    # The previous installer wrote the characters backslash+n into the file.
    # Write a real newline byte here, not an escaped textual sequence.
    INIT.write_bytes(f'__version__ = "{EXPECTED_VERSION}"\n'.encode("utf-8"))
    print(f"Rewrote {INIT.relative_to(ROOT)} with a real newline")

    # Ensure runner banner is also at the intended version. The previous repair
    # normally updated this before failing, but make this repair idempotent.
    runner = RUNNER.read_text(encoding="utf-8")
    runner2, n = re.subn(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        EXPECTED_BANNER,
        runner,
        count=1,
    )
    if n != 1:
        print("FAIL could not locate runner status banner")
        return 3
    RUNNER.write_text(runner2, encoding="utf-8")
    print(f"Runner banner normalized to: {EXPECTED_BANNER}")

    # Validate that the substantive v024b stage fixes survived the earlier
    # installer failure. Do not silently proceed if they did not.
    br_text = BR.read_text(encoding="utf-8")
    br_requirements = [
        'first(row, "expdate", "obsDate", "obs_date")',
        'first(row, "edgedist", "edgeDistance", "edge_distance")',
        'first(row, "centerdist", "centerDistance", "center_distance")',
        'first(row, "ra", "raDeg", "ra_deg")',
        'first(row, "dec", "decDeg", "dec_deg")',
        'raw queryexps schema OK',
        'metadata completeness (imaging)',
    ]
    missing_br = [x for x in br_requirements if x not in br_text]
    if missing_br:
        print("FAIL corrected v028br raw-schema repair is not fully present:")
        for x in missing_br:
            print(f"  missing marker: {x}")
        return 4
    print("v028br raw-schema repair presence check: PASS")

    bs_text = BS.read_text(encoding="utf-8")
    bs_requirements = [
        'raw DASCH queryexps `expdate` field',
        'from daschlab.timeutil import dasch_time_as_isot',
        'from astropy.time import Time',
        'Raw expdate examples for diagnosis',
    ]
    missing_bs = [x for x in bs_requirements if x not in bs_text]
    if missing_bs:
        print("FAIL corrected v028bs date-parser repair is not fully present:")
        for x in missing_bs:
            print(f"  missing marker: {x}")
        return 4
    print("v028bs expdate parser repair presence check: PASS")

    # Parse/compile every active Python file.
    failures = []
    py_files = sorted(
        p for p in AUTO.rglob("*.py")
        if "backups" not in p.parts
    )
    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            source = p.read_text(encoding="utf-8")
            ast.parse(source)
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {type(exc).__name__}: {exc}")

    if failures:
        print("\nREPAIR STATUS: FAIL")
        return 5

    # Critical runtime import regression: this is exactly what was broken.
    try:
        sys.path.insert(0, str(ROOT))
        import automation
        import automation.registry_order01 as regmod

        if getattr(automation, "__version__", None) != EXPECTED_VERSION:
            raise RuntimeError(
                f"automation.__version__={getattr(automation, '__version__', None)!r}"
            )

        br_contract = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_science25_analogue_exposure_inventory_v028br"
        )
        bs_contract = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_matched_recurrence_plan_v028bs"
        )
        bt_contract = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_matched_recurrence_phase1_v028bt"
        )

        if getattr(br_contract, "network_access", None) is not True:
            raise RuntimeError("v028br network_access contract changed")
        if getattr(bs_contract, "network_access", False) is not False:
            raise RuntimeError("v028bs unexpectedly requires network")
        if getattr(bt_contract, "network_access", None) is not True:
            raise RuntimeError("v028bt network_access contract changed")

        print(
            "\nRuntime package/registry import regression: PASS "
            f"(automation.__version__={automation.__version__})"
        )
    except Exception as exc:
        print(
            f"\nRuntime package/registry import regression: FAIL: "
            f"{type(exc).__name__}: {exc}"
        )
        return 6

    # Report expected stale-product state. Do not recreate or modify science outputs.
    base = ROOT / "results" / "order01_native_full_v028"
    br_json = base / "order01_dasch_science25_analogue_exposure_inventory_v028br.json"
    bs_json = base / "order01_dasch_matched_recurrence_plan_v028bs.json"
    print("\nExpected rebuild state:")
    print(
        "  v028br primary product: "
        + ("PRESENT" if br_json.is_file() else "MISSING (expected; will rebuild from cache)")
    )
    print(
        "  v028bs primary product: "
        + ("PRESENT" if bs_json.is_file() else "MISSING (expected; waits for rebuilt v028br)")
    )

    print("\nREPAIR STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_analogue_exposure_inventory_v028br'
    )
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_matched_recurrence_plan_v028bs'
    )
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_matched_recurrence_phase1_v028bt'
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
