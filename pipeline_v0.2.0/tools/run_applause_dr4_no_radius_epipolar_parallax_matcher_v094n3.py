#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse,csv,io,sys

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/"tools"/"run_applause_dr4_no_radius_epipolar_parallax_matcher_v094n.py"

EXPECTED_CONTRACT_SHA="f4c3e6260bf8139ab7ac370e2f9f5a28d46353685dd17f1d07ead516dfb1b643"
OLD='pf=["candidate_hash","class","calibration_tier","pair_id","source_id_a","source_id_b","gaia_id_a","gaia_id_b","ra_a","dec_a","ra_b","dec_b","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec","geocentric_distance_km"]'
NEW='pf=["candidate_hash","class","calibration_tier","pair_id","source_id_a","source_id_b","gaia_id_a","gaia_id_b","ra_a","dec_a","ra_b","dec_b","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec","geocentric_distance_km","distance_bin","disparity_bin"]'

def patched_text():
    if not ORIGINAL.is_file():
        raise SystemExit(f"Missing frozen v094n runner: {ORIGINAL}")
    s=ORIGINAL.read_text(encoding="utf-8")
    if s.count(OLD)!=1:
        raise SystemExit(f"Expected exactly one v094n private-field schema occurrence, found {s.count(OLD)}")
    if f'EXPECTED="{EXPECTED_CONTRACT_SHA}"' not in s:
        raise SystemExit("Frozen v094n contract constant not found in original runner")
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

def load_namespace(s):
    # Execute definitions only, preserving the original frozen runner's __file__,
    # so ROOT resolves exactly as it did at prospective freeze.
    ns={"__name__":"v094n3_definition_check","__file__":str(ORIGINAL)}
    exec(compile(s,str(ORIGINAL),"exec"),ns,ns)
    return ns

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()

    s=patched_text()
    serialization_self_test()
    ns=load_namespace(s)

    if Path(ns["ROOT"]).resolve()!=ROOT.resolve():
        raise SystemExit(f"ROOT-preservation self-test failed: {ns['ROOT']} != {ROOT}")
    if str(ns["CONTRACT"].resolve()) != str((ROOT/"research"/"prospective_freezes"/"applause_dr4_no_radius_epipolar_parallax_matcher_contract_v094n.json").resolve()):
        raise SystemExit("Contract-path preservation self-test failed")
    if ns["EXPECTED"]!=EXPECTED_CONTRACT_SHA:
        raise SystemExit("Frozen scientific contract constant changed")

    if a.self_test:
        print("v094n3 serialization + original-ROOT preservation self-test PASS")
        return 0

    print(f"v094n3 executing patched frozen source in-memory with __file__ preserved as: {ORIGINAL}")
    # Run the exact patched frozen source as __main__. The only text change is the
    # two private CSV field names; __file__ remains ORIGINAL, so ROOT is unchanged.
    run_ns={"__name__":"__main__","__file__":str(ORIGINAL)}
    exec(compile(s,str(ORIGINAL),"exec"),run_ns,run_ns)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
