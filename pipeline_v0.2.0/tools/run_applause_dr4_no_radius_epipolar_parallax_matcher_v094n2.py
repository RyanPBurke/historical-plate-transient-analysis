#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse,csv,io,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/"tools"/"run_applause_dr4_no_radius_epipolar_parallax_matcher_v094n.py"

OLD='pf=["candidate_hash","class","calibration_tier","pair_id","source_id_a","source_id_b","gaia_id_a","gaia_id_b","ra_a","dec_a","ra_b","dec_b","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec","geocentric_distance_km"]'
NEW='pf=["candidate_hash","class","calibration_tier","pair_id","source_id_a","source_id_b","gaia_id_a","gaia_id_b","ra_a","dec_a","ra_b","dec_b","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec","geocentric_distance_km","distance_bin","disparity_bin"]'

def patched_text():
    if not ORIGINAL.is_file():
        raise SystemExit(f"Missing frozen v094n runner: {ORIGINAL}")
    s=ORIGINAL.read_text(encoding="utf-8")
    if s.count(OLD)!=1:
        raise SystemExit(f"Expected exactly one v094n private-field schema occurrence, found {s.count(OLD)}")
    # Operational serialization repair only.
    return s.replace(OLD,NEW,1)

def serialization_self_test():
    rec={"candidate_hash":"x","class":"PHYSICAL_PARALLAX_GEOMETRY","calibration_tier":"CALIBRATED_LOCAL25",
         "signed_disparity_arcsec":3.0,"cross_track_arcsec":0.5,"closure_arcsec":0.4,
         "distance_bin":"0P01_TO_0P1AU","disparity_bin":"2_TO_5ARCSEC"}
    pf=["candidate_hash","class","calibration_tier","pair_id","source_id_a","source_id_b","gaia_id_a","gaia_id_b",
        "ra_a","dec_a","ra_b","dec_b","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec",
        "geocentric_distance_km","distance_bin","disparity_bin"]
    private={**rec,"pair_id":"1|2","source_id_a":1,"source_id_b":2,"gaia_id_a":3,"gaia_id_b":4,
             "ra_a":1.0,"dec_a":2.0,"ra_b":1.1,"dec_b":2.1,"geocentric_distance_km":100000.0}
    csv.DictWriter(io.StringIO(),fieldnames=pf).writerow(private)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()

    s=patched_text()
    serialization_self_test()
    compile(s,"<v094n2_patched_runtime>","exec")

    if a.self_test:
        print("v094n2 serialization repair self-test PASS")
        return 0

    work=ROOT/"work"/"applause_dr4_no_radius_epipolar_parallax_matcher_v094n2_runtime"
    work.mkdir(parents=True,exist_ok=True)
    runtime=work/"run_applause_dr4_no_radius_epipolar_parallax_matcher_v094n2_runtime.py"
    runtime.write_text(s,encoding="utf-8")
    print("v094n2 runtime serialization patch prepared from frozen v094n runner")
    return subprocess.run([sys.executable,str(runtime)]).returncode

if __name__=="__main__":
    raise SystemExit(main())
