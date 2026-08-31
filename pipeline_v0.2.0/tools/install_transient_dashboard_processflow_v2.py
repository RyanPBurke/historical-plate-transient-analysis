from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "transient_dashboard.py"
PAYLOAD = ROOT / "tools" / "_transient_dashboard_processflow_v2.payload.py"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def main():
    print("=" * 116)
    print("TRANSIENT DASHBOARD — PROCESS-FLOW UI v2 INSTALLER")
    print("=" * 116)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO RESULT/CANDIDATE/AUTOMATION STATE MUTATION.\n")

    if not PAYLOAD.is_file():
        raise RuntimeError(f"Missing payload: {PAYLOAD}")
    py_compile.compile(str(PAYLOAD), doraise=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if TARGET.is_file():
        backup_dir = ROOT / "dashboard_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"transient_dashboard_pre_processflow_v2_{stamp}.py"
        shutil.copy2(TARGET, backup)
        print("Existing dashboard SHA256:", sha(TARGET))
        print("Backup:", backup)

    TARGET.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    py_compile.compile(str(TARGET), doraise=True)

    print("\nInstalled:", TARGET)
    print("New dashboard SHA256:", sha(TARGET))
    print("Syntax compile: PASS")
    print("Science/result state touched: NO")
    print("\nINSTALL STATUS: PASS")
    print("\nRestart the dashboard process to load v2:")
    print(r'  & ".\.venv\Scripts\python.exe" ".\transient_dashboard.py"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
