from pathlib import Path
from datetime import datetime, timezone
import hashlib, shutil, py_compile

ROOT=Path.cwd()
TARGET=ROOT/"tools"/"audit_wide_census_gaia_reference_coverage_v065.py"
PAYLOAD=ROOT/"tools"/"_audit_wide_census_gaia_reference_coverage_v065_fix1.payload.py"
EXPECTED_ORIGINAL="db94f5a7bd677c9666581ce0abf6cd027839bf28a760021a9a7cdd404eb2a24a"
EXPECTED_FIXED="213416fcb26406a1c14986ebf4d7de7482a5853e3dc7ecce0f5d46c8bf3bc6b2"

def nsha(p):
    t=p.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n")
    return hashlib.sha256(t.encode()).hexdigest()

def main():
    print("="*124)
    print("v065 GAIA REFERENCE COVERAGE AUDIT — NUMERICAL CENTER-GUARD FIX 1")
    print("="*124)
    print("NO NETWORK. NO GAIA ROWS. NO PIXELS. NO REGISTRATION. NO CANDIDATE MUTATION.\n")
    if not TARGET.is_file(): raise RuntimeError(f"Missing target: {TARGET}")
    if not PAYLOAD.is_file(): raise RuntimeError(f"Missing payload: {PAYLOAD}")
    cur=nsha(TARGET)
    print("Installed v065 normalized SHA256:",cur)
    if cur==EXPECTED_FIXED:
        print("Source guard: ALREADY FIXED")
        print("REPAIR STATUS: PASS")
        return
    if cur!=EXPECTED_ORIGINAL:
        raise RuntimeError("REFUSING: installed v065 source differs from expected original. Current normalized SHA="+cur)
    py_compile.compile(str(PAYLOAD),doraise=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=ROOT/"tools"/f"audit_wide_census_gaia_reference_coverage_v065.pre_fix1_{stamp}.py"
    shutil.copy2(TARGET,backup)
    TARGET.write_text(PAYLOAD.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n"),encoding="utf-8",newline="\n")
    py_compile.compile(str(TARGET),doraise=True)
    got=nsha(TARGET)
    if got!=EXPECTED_FIXED: raise RuntimeError("Installed fixed hash mismatch: "+got)
    print("Source guard: PASS")
    print("Backup:",backup)
    print("Fixed v065 normalized SHA256:",got)
    print("Science thresholds changed: NO")
    print("Transport geometry changed: NO")
    print("Only numerical equality guard changed: YES")
    print("REPAIR STATUS: PASS")

if __name__=="__main__":
    main()
