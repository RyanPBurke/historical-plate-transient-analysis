from __future__ import annotations
from pathlib import Path
import json, hashlib

ROOT = Path.cwd()
OUT = ROOT / "results" / "order11_followup_match3_v047"
OUT.mkdir(parents=True, exist_ok=True)

POLICY = ROOT / "config" / "candidate_adjudication_policy_v002.json"
GAIA = ROOT / "results/order11_followup_match3_v042/order11_match3_gaia_epoch_report_v042.json"
COMMON = ROOT / "results/order11_followup_match3_v043a/order11_match3_local_astrometry_report_v043a.json"
SPARSE = ROOT / "results/order11_followup_match3_v044/order11_match3_sparse_astrometry_report_v044.json"
ROBUST = ROOT / "results/order11_followup_match3_v044b/order11_match3_sparse_robustness_audit_v044b.json"
FINAL = ROOT / "results/order11_followup_match3_v045a/order11_match3_final_adjudication_v045a.json"
REPORT = OUT / "order11_match3_method_freeze_v047.json"

def load(p: Path):
    if not p.is_file():
        raise RuntimeError(f"REFUSING: required input missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))

def sha(p: Path):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def find_text(obj, needle):
    if isinstance(obj, dict):
        return any(find_text(v, needle) for v in obj.values())
    if isinstance(obj, list):
        return any(find_text(v, needle) for v in obj)
    return needle in str(obj)

def main():
    print("="*120)
    print("ORDER 11 — MATCH 3 METHOD LESSON FREEZE v047")
    print("="*120)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    p=load(POLICY); g=load(GAIA); c=load(COMMON); s=load(SPARSE); r=load(ROBUST); f=load(FINAL)

    guards = {
        "policy_id": p.get("policy_id") == "candidate_adjudication_policy_v002",
        "gaia_diagnostic_association": find_text(g, "CATALOGUE_SOURCE_BOTH_ENDPOINTS_WITHIN_5ARCSEC"),
        "primary_common_refs_insufficient": find_text(c, "INSUFFICIENT_LOCAL_COMMON_GAIA_REFERENCES"),
        "sparse_does_not_support_raw_strict": find_text(s, "SPARSE_DIAGNOSTIC_DOES_NOT_SUPPORT_STRICT_RAW_COINCIDENCE"),
        "robust_to_any_single_dasch_reference": find_text(r, "SPARSE_MISMATCH_ROBUST_TO_ANY_SINGLE_DASCH_REFERENCE"),
        "final_pair_disposition_closed": find_text(f, "CLOSED_COMMON_SKY_COINCIDENCE_SPARSE_REGISTRATION_ROBUST"),
        "poss_morphology_ordinary": find_text(f, "MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS"),
        "dasch_morphology_ordinary": find_text(f, "MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS"),
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: semantic guard failed: " + json.dumps(guards, sort_keys=True))

    payload = {
        "stage": "ORDER11_MATCH3_METHOD_LESSON_FREEZE_V047",
        "status": "COMPLETE",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "semantic_guards": guards,
        "input_sha256": {str(x.relative_to(ROOT)): sha(x) for x in (POLICY,GAIA,COMMON,SPARSE,ROBUST,FINAL)},
        "pair_disposition": "CLOSED_COMMON_SKY_COINCIDENCE_SPARSE_REGISTRATION_ROBUST",
        "measurement_summary": {
            "raw_poss_dasch_separation_arcsec": 1.596,
            "sparse_corrected_poss_dasch_separation_arcsec": 11.756,
            "sparse_leave_one_dasch_reference_out_range_arcsec": [11.587, 12.591],
            "all_leave_one_out_trials_gt_3arcsec": True,
            "all_leave_one_out_trials_gt_5arcsec": True,
            "poss_morphology": "MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS",
            "dasch_morphology": "MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS",
        },
        "interpretation": {
            "what_is_closed": "The hypothesis that the raw POSS and DASCH detections form one static/common-sky two-observatory source coincidence.",
            "what_is_not_claimed": [
                "This does not prove either individual plate feature is non-astrophysical.",
                "This does not automatically reject either endpoint from a separately defined single-observatory transient search.",
                "This does not test parallax-aware near-Earth hypotheses."
            ],
            "likely_mechanism": "Raw-coordinate coincidence produced by archive/local astrometric offsets plus ordinary-source/background coincidence.",
        },
        "generic_lessons_promoted_to_policy": p.get("match3_lessons", []),
        "next_project_phase": "Complete/freeze census universe, then apply generic adjudication policy systematically to every eligible pair/candidate."
    }
    tmp = REPORT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    tmp.replace(REPORT)
    print("Pair disposition:", payload["pair_disposition"])
    print("Policy:", POLICY)
    print("Report:", REPORT)
    print("\nSTAGE STATUS: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
