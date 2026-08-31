from pathlib import Path
from datetime import datetime, timezone
import hashlib, shutil, py_compile

ROOT=Path.cwd()
TARGET=ROOT/"tools"/"run_wide_census_gaia_supplemental_acquisition_v066.py"
PAYLOAD=ROOT/"tools"/"_run_wide_census_gaia_supplemental_acquisition_v066_workers4.payload.py"
EXPECTED_ORIGINAL="b64f5c59d2b433dbc108b3e085ddb8bbc1f2d37648e17c581a630950373441d6"
EXPECTED_FIXED="66b41f6dfcef2db8ba5ffc70490e1b809aa04233a6eaa0c003f0b12403518275"

def nsha(p):
    t=p.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n")
    return hashlib.sha256(t.encode()).hexdigest()

def main():
    print("="*128)
    print("v066 SUPPLEMENTAL GAIA ACQUISITION — 4-WORKER TRANSPORT CEILING PATCH")
    print("="*128)
    print("NO NETWORK. NO GAIA QUERIES. NO CACHE DELETION. NO REGISTRATION.\n")
    if not TARGET.is_file(): raise RuntimeError(f"Missing target: {TARGET}")
    if not PAYLOAD.is_file(): raise RuntimeError(f"Missing payload: {PAYLOAD}")
    cur=nsha(TARGET)
    print("Installed v066 normalized SHA256:",cur)
    if cur==EXPECTED_FIXED:
        print("Source guard: ALREADY PATCHED")
        print("PATCH STATUS: PASS")
        return
    if cur!=EXPECTED_ORIGINAL:
        raise RuntimeError(f"REFUSING unexpected installed v066 SHA: {cur}")
    py_compile.compile(str(PAYLOAD),doraise=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=ROOT/"tools"/f"run_wide_census_gaia_supplemental_acquisition_v066.pre_workers4_{stamp}.py"
    shutil.copy2(TARGET,backup)
    TARGET.write_text(PAYLOAD.read_text(encoding="utf-8"),encoding="utf-8",newline="\n")
    py_compile.compile(str(TARGET),doraise=True)
    got=nsha(TARGET)
    if got!=EXPECTED_FIXED: raise RuntimeError(f"Patched SHA mismatch: {got}")
    print("Source guard: PASS")
    print("Backup:",backup)
    print("Patched SHA256:",got)
    print("Default workers: 2 (unchanged)")
    print("Maximum workers: 4")
    print("Global request-start spacing: 0.75 s (unchanged)")
    print("Science/query geometry changed: NO")
    print("PATCH STATUS: PASS")

if __name__=="__main__":
    main()
