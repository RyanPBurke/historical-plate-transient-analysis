from __future__ import annotations

"""Repair v028cj to validate red and blue POSS-I scan dimensions separately."""

from pathlib import Path
from datetime import datetime, timezone
import ast
import shutil


ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "acquire_survivor_poss_references_v028cj.py"

OLD = '''    fw = int(hhh.get("XPIXELS", 14000))
    fh = int(hhh.get("YPIXELS", 13999))
    if (fw, fh) != (14000, 13999):
        raise RuntimeError(f"REFUSING: unexpected DSS dimensions for {region}: {fw}x{fh}")
'''

NEW = '''    if "XPIXELS" not in hhh or "YPIXELS" not in hhh:
        raise RuntimeError(f"REFUSING: physical scan dimensions missing for {region}")
    fw = int(hhh["XPIXELS"])
    fh = int(hhh["YPIXELS"])
    expected = (23040, 23040) if region.startswith("XO") else (14000, 13999)
    if (fw, fh) != expected:
        raise RuntimeError(
            f"REFUSING: unexpected DSS dimensions for {region}: "
            f"{fw}x{fh}; expected {expected[0]}x{expected[1]}"
        )
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION REPAIR v0.3.8b — BAND-SPECIFIC POSS SCAN DIMENSIONS")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")

    if not STAGE.is_file():
        raise RuntimeError(f"Missing installed stage: {STAGE}")

    text = STAGE.read_text(encoding="utf-8-sig")
    if NEW in text:
        raise RuntimeError("REFUSING: v038b repair is already present")
    if text.count(OLD) != 1:
        raise RuntimeError("REFUSING: expected v028cj dimension guard was not found exactly once")

    repaired = text.replace(OLD, NEW, 1)
    ast.parse(repaired, filename=str(STAGE))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = (
        ROOT / "automation" / "backups" /
        f"pre_v038b_poss_dimensions_{stamp}"
    )
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    STAGE.write_text(repaired, encoding="utf-8")

    print(f"Patched stage: {STAGE}")
    print("Allowed physical formats:")
    print("  XE (POSS-I E/red): 14000 x 13999")
    print("  XO (POSS-I O/blue): 23040 x 23040")
    print(f"Backup: {backup}")
    print("\nREPAIR STATUS: PASS")


if __name__ == "__main__":
    main()
