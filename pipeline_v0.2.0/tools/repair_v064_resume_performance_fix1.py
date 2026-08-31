from pathlib import Path
from datetime import datetime, timezone
import hashlib
import py_compile
import shutil

ROOT=Path.cwd()
TARGET=ROOT/"tools"/"run_wide_census_gaia_acquisition_v064.py"
PAYLOAD=ROOT/"tools"/"_run_wide_census_gaia_acquisition_v064_fix1.payload.py"

EXPECTED_ORIGINAL="8f3cbacc926461d91bb5693898f831d54e05d88e48d65482b836c1e417b4d70a"
EXPECTED_FIXED="b3c8da9ad93da4bf10e9e49586c4328b6f0c97223e1091e902a0c1d6e28c0682"

def normalized_bytes(p):
    t=p.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n")
    return t.encode("utf-8")

def nsha(p):
    return hashlib.sha256(normalized_bytes(p)).hexdigest()

def main():
    print("="*124)
    print("v064 GAIA ACQUISITION — RESUME PERFORMANCE FIX 1")
    print("="*124)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO GAIA QUERIES. NO CACHE DELETION. NO CANDIDATE STATE MUTATION.\n")

    if not TARGET.is_file(): raise RuntimeError(f"Missing target: {TARGET}")
    if not PAYLOAD.is_file(): raise RuntimeError(f"Missing payload: {PAYLOAD}")

    current=nsha(TARGET)
    print("Installed worker normalized SHA256:",current)

    if current==EXPECTED_FIXED:
        print("Source guard: ALREADY FIXED")
        print("REPAIR STATUS: PASS")
        return 0
    if current!=EXPECTED_ORIGINAL:
        raise RuntimeError(
            "REFUSING: installed v064 worker differs from both the original "
            f"and fix1. Current normalized SHA={current}"
        )

    py_compile.compile(str(PAYLOAD),doraise=True)

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=ROOT/"tools"/f"run_wide_census_gaia_acquisition_v064.pre_fix1_{stamp}.py"
    shutil.copy2(TARGET,backup)

    TARGET.write_text(
        PAYLOAD.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n"),
        encoding="utf-8",newline="\n"
    )
    py_compile.compile(str(TARGET),doraise=True)

    installed=nsha(TARGET)
    if installed!=EXPECTED_FIXED:
        raise RuntimeError(f"Installed fix hash mismatch: {installed}")

    print("Source guard: PASS")
    print("Backup:",backup)
    print("Fixed worker normalized SHA256:",installed)
    print("Existing Gaia cache touched: NO")
    print("Existing v064 state/results deleted: NO")
    print("Science/transport semantics changed: NO")
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(r'  & ".\.venv\Scripts\python.exe" ".\tools\run_wide_census_gaia_acquisition_v064.py"')
    return 0

if __name__=="__main__":
    raise SystemExit(main())
