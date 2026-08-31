from pathlib import Path
from datetime import datetime, timezone
import hashlib, shutil, py_compile

ROOT=Path.cwd()
TARGET=ROOT/"tools"/"run_wide_census_gaia_supplemental_acquisition_v066.py"
PAYLOAD=ROOT/"tools"/"_run_wide_census_gaia_supplemental_acquisition_v066_workers8.payload.py"
EXPECTED_CURRENT="66b41f6dfcef2db8ba5ffc70490e1b809aa04233a6eaa0c003f0b12403518275"
EXPECTED_FIXED="8b4a036eb18514ed2c0e4fd30089a1e3a78aa49a362953fb3e40396da1b28704"

def nsha(p):
    t=p.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n")
    return hashlib.sha256(t.encode()).hexdigest()

def main():
    print("="*128)
    print("v066 SUPPLEMENTAL GAIA ACQUISITION — 8-WORKER TRANSPORT CEILING PATCH")
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
    if cur!=EXPECTED_CURRENT:
        raise RuntimeError(
            "REFUSING: installed v066 is not the expected 4-worker-patched source. "
            f"Current normalized SHA={cur}"
        )
    py_compile.compile(str(PAYLOAD),doraise=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=ROOT/"tools"/f"run_wide_census_gaia_supplemental_acquisition_v066.pre_workers8_{stamp}.py"
    shutil.copy2(TARGET,backup)
    TARGET.write_text(PAYLOAD.read_text(encoding="utf-8"),encoding="utf-8",newline="\n")
    py_compile.compile(str(TARGET),doraise=True)
    got=nsha(TARGET)
    if got!=EXPECTED_FIXED: raise RuntimeError(f"Patched SHA mismatch: {got}")
    print("Source guard: PASS")
    print("Backup:",backup)
    print("Patched SHA256:",got)
    print("Default workers: 2 (unchanged)")
    print("Maximum workers: 8")
    print("Global request-start spacing: 0.75 s (unchanged)")
    print("Retries / MAXREC / cache / disk guard changed: NO")
    print("Science/query geometry changed: NO")
    print("PATCH STATUS: PASS")

if __name__=="__main__":
    main()
