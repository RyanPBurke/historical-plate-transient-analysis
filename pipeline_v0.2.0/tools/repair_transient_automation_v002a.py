#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
VERIFIER = AUTO / "verifier.py"
BACKUP = AUTO / "backups" / "pre_v002a"

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION METADATA REPAIR v0.0.2a")
    print("="*112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.")
    print("No science/result artifact is modified.")
    print("No candidate state is changed.\n")

    for p in (REGISTRY, VERIFIER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, VERIFIER):
        dst = BACKUP / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    reg = REGISTRY.read_text(encoding="utf-8")
    old = (
        '    StageContract(\n'
        '        stage_id="order01_closure_v028ag",\n'
        '        title="Final POSS endpoint disposition + two-observatory closure",\n'
        '        produces=("results/order01_native_full_v028/order01_candidate24_final_disposition_and_closure_v028ag.json",),\n'
        '        notes="Frozen authoritative closure artifact.",\n'
        '    ),'
    )
    new = (
        '    StageContract(\n'
        '        stage_id="order01_closure_v028ag",\n'
        '        title="Final POSS endpoint disposition + two-observatory closure",\n'
        '        produces=("results/order01_native_full_v028/order01_candidate24_final_disposition_and_closure_v028ag.json",),\n'
        '        candidate_state_mutation=True,\n'
        '        notes="Frozen authoritative closure artifact; historical stage intentionally mutated disposition state.",\n'
        '    ),'
    )
    if old not in reg:
        print("FAIL: expected v028ag registry block not found; refusing broad text edit.")
        return 3
    reg = reg.replace(old, new, 1)
    REGISTRY.write_text(reg, encoding="utf-8")
    print("Updated registry: v028ag candidate_state_mutation=True")

    ver = VERIFIER.read_text(encoding="utf-8")
    old_alias = '    "non_science_pixels_read": ("non_science_pixels_read", "control_pixels_read"),'
    new_alias = (
        '    "non_science_pixels_read": (\n'
        '        "non_science_pixels_read",\n'
        '        "non_science_control_pixels_read",\n'
        '        "control_pixels_read",\n'
        '    ),'
    )
    if old_alias not in ver:
        print("FAIL: expected verifier alias line not found; refusing broad text edit.")
        return 3
    ver = ver.replace(old_alias, new_alias, 1)
    VERIFIER.write_text(ver, encoding="utf-8")
    print("Updated verifier: recognises non_science_control_pixels_read")

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
        print("\nAUTOMATION METADATA REPAIR STATUS: FAIL")
        return 4

    print("\nAUTOMATION METADATA REPAIR STATUS: PASS")
    print(f"Backup: {BACKUP.relative_to(ROOT)}")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-all')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print("\nNo science was executed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
