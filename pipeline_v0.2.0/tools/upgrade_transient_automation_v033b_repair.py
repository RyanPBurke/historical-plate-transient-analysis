from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "acquire_order74_poss_identity_v028ce.py"
WRONG = 'INVENTORY = ROOT / "results" / "order74_native_preflight_v028" / "order74_disposition_queue_advance_v028cd.json"'
RIGHT = 'INVENTORY = ROOT / "results" / "order55_native_preflight_v028" / "order55_disposition_queue_advance_v028cd.json"'


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.3.3b — ORDER-74 ADVANCED-QUEUE INPUT PATH")
    print("=" * 112)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    if not STAGE.is_file():
        raise RuntimeError(f"Missing installed Order-74 stage: {STAGE}")
    text = STAGE.read_text(encoding="utf-8")
    if RIGHT in text and WRONG not in text:
        ast.parse(text, filename=str(STAGE))
        print("Correct queue input path already installed.")
        print("REPAIR STATUS: PASS (NO CHANGE REQUIRED)")
        return
    if text.count(WRONG) != 1:
        raise RuntimeError(f"REFUSING: expected exactly one incorrect input path; found {text.count(WRONG)}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v033b_order74_path_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    patched = text.replace(WRONG, RIGHT, 1)
    ast.parse(patched, filename=str(STAGE))
    STAGE.write_text(patched, encoding="utf-8", newline="\n")
    print(f"Patched stage: {STAGE}")
    print(f"Correct input: results/order55_native_preflight_v028/order55_disposition_queue_advance_v028cd.json")
    print(f"Backup: {backup}")
    print("\nREPAIR STATUS: PASS")


if __name__ == "__main__":
    main()
