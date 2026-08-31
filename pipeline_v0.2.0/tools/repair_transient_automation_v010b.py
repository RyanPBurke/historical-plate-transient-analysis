#!/usr/bin/env python3
from pathlib import Path
import py_compile
import ast

ROOT = Path.cwd()
AUTO = ROOT / "automation"
INIT = AUTO / "__init__.py"
RUNNER = AUTO / "runner.py"
REGISTRY = AUTO / "registry_order01.py"
STAGE = AUTO / "stages" / "execute_platephot_full_queue_v028be.py"

def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.1.0b — PACKAGE INIT FINALIZATION")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("No science/result artifact is modified.")
    print("No candidate state is changed.\n")

    for p in (RUNNER, REGISTRY, STAGE):
        if not p.is_file():
            print(f"FAIL missing required v0.1.0 file: {p}")
            return 2

    # Fix the only observed failure: literal backslash-n in package init.
    INIT.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    print("Repaired: automation\\__init__.py")

    runner = RUNNER.read_text(encoding="utf-8")
    registry = REGISTRY.read_text(encoding="utf-8")

    checks = [
        (
            "v028be registry entry",
            'stage_id="dasch_platephot_full_queue_v028be"' in registry,
        ),
        (
            "run-until-blocked command function",
            "def cmd_run_until_blocked(" in runner,
        ),
        (
            "run-until-blocked parser registration",
            'sub.add_parser("run-until-blocked")' in runner,
        ),
        (
            "checkpointed progress handling",
            "IN_PROGRESS_CHECKPOINTED" in runner,
        ),
        (
            "v0.1.0 status banner",
            "Transient automation v0.1.0 - Order01 registry status" in runner,
        ),
    ]

    print("\nStructural checks:")
    all_structural = True
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        all_structural = all_structural and ok

    if not all_structural:
        print("\nAUTOMATION REPAIR STATUS: FAIL")
        print("One or more v0.1.0 patches did not survive the previous installer.")
        return 3

    # Parse the two patched structural modules explicitly.
    try:
        ast.parse(runner)
        print("  [PASS] runner AST parse")
        ast.parse(registry)
        print("  [PASS] registry AST parse")
    except SyntaxError as exc:
        print(f"  [FAIL] AST parse: {exc}")
        return 4

    failures = []
    py_files = sorted(
        p for p in AUTO.rglob("*.py")
        if "backups" not in p.parts
    )

    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\nAUTOMATION REPAIR STATUS: FAIL")
        return 5

    print("\nAUTOMATION REPAIR STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print("    expected: v028be selected, then REFUSED without --allow-network")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network')
    print("\nNo science or network work was performed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
