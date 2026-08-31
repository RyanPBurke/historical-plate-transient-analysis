#!/usr/bin/env python3
"""
Repair transient automation bootstrap v0.0.1a.

NON-DESTRUCTIVE with respect to science/results:
- no network access
- no science pixels read
- no detector rerun
- no candidate state mutation
- only repairs automation package bootstrap files
"""

from pathlib import Path
import py_compile
import sys

ROOT = Path.cwd()
AUTO = ROOT / "automation"
INIT = AUTO / "__init__.py"

def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION BOOTSTRAP REPAIR v0.0.1a")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.")
    print("No candidate state is changed.\n")

    if not AUTO.is_dir():
        print(f"FAIL: automation directory not found: {AUTO}")
        return 2

    # Repair the known bootstrap escaping defect exactly.
    INIT.write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    print(f"Repaired: {INIT.relative_to(ROOT)}")

    # Validate every Python module in the automation package.
    failures = []
    py_files = sorted(AUTO.rglob("*.py"))
    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\nAUTOMATION PACKAGE COMPILE STATUS: FAIL")
        return 3

    print("\nAUTOMATION PACKAGE COMPILE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-baseline')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner plan')
    print()
    print("No science was executed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
