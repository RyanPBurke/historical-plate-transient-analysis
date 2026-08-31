from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json

ROOT = Path.cwd()

POLICY_V001 = ROOT / "config" / "candidate_adjudication_policy_v001.json"
POLICY_V002 = ROOT / "config" / "candidate_adjudication_policy_v002.json"

V052 = ROOT / "results" / "wide_census_exact_footprint_v052.json"
V053 = ROOT / "results" / "wide_census_detector_execution_plan_v053.json"
V053_QUEUE = ROOT / "results" / "wide_census_detector_execution_queue_v053.csv"
V054 = ROOT / "results" / "wide_census_heavy_preflight_v054.json"
V054_ENDPOINTS = ROOT / "results" / "wide_census_detector_endpoint_plan_v054.csv"
V054_PAIRS = ROOT / "results" / "wide_census_detector_pair_plan_v054.json"
V054_TILES = ROOT / "results" / "wide_census_detector_tile_plan_v054.csv"

# IMPORTANT: This prospective freeze deliberately does not read any v056
# detector output or candidate outcome file.
FORBIDDEN_V056 = [
    ROOT / "results" / "wide_census_detector_execution_v056.json",
    ROOT / "results" / "wide_census_detector_candidates_v056.csv",
    ROOT / "results" / "wide_census_pair_raw_match_summary_v056.csv",
    ROOT / "results" / "wide_census_pair_raw_matches_v056.csv",
]

FREEZE_DIR = ROOT / "research" / "prospective_freezes"
CONTRACT = FREEZE_DIR / "wide_census_postdetector_adjudication_contract_v001.json"
REPORT = ROOT / "results" / "wide_census_postdetector_adjudication_freeze_v057.json"

EXPECTED_POLICY_V001_SHA = "a42be953f8162520de83f3b9d4e7e8f9cf2935d9a78b7b743de267107bea3af5"
EXPECTED_POLICY_V002_SHA = "eb8512724b2ef23b3ee88e5ffcfab8088144c984f0b75adb7b68e87198cb4cbd"

EXPECTED_V052_TRUE_OVERLAP = 33
EXPECTED_V052_HOLDS = 41
EXPECTED_V052_NO_OVERLAP = 8
EXPECTED_V053_OPPS = 33
EXPECTED_V054_ENDPOINTS = 53
EXPECTED_V054_TILES = 6293


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    print("=" * 132)
    print("WIDE CENSUS — PROSPECTIVE POST-DETECTOR ADJUDICATION FREEZE v057")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO v056 OUTCOMES. NO CANDIDATE STATE MUTATION.\n")

    required = [
        POLICY_V001, POLICY_V002, V052, V053, V053_QUEUE, V054,
        V054_ENDPOINTS, V054_PAIRS, V054_TILES,
    ]
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing prerequisite {p}")

    if sha(POLICY_V001) != EXPECTED_POLICY_V001_SHA:
        raise RuntimeError("REFUSING: candidate_adjudication_policy_v001 SHA changed")
    if sha(POLICY_V002) != EXPECTED_POLICY_V002_SHA:
        raise RuntimeError("REFUSING: candidate_adjudication_policy_v002 SHA changed")

    p1 = load(POLICY_V001)
    p2 = load(POLICY_V002)
    if p1.get("policy_id") != "candidate_adjudication_policy_v001":
        raise RuntimeError("REFUSING: v001 policy id mismatch")
    if p2.get("policy_id") != "candidate_adjudication_policy_v002":
        raise RuntimeError("REFUSING: v002 policy id mismatch")

    v052 = load(V052)
    counts = v052.get("classification_counts") or {}
    if int(counts.get("TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST", -1)) != EXPECTED_V052_TRUE_OVERLAP:
        raise RuntimeError("REFUSING: v052 robust-overlap count changed")
    if int(v052.get("hold_count", -1)) != EXPECTED_V052_HOLDS:
        raise RuntimeError("REFUSING: v052 hold count changed")
    if int(counts.get("NO_TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST", -1)) != EXPECTED_V052_NO_OVERLAP:
        raise RuntimeError("REFUSING: v052 no-overlap count changed")

    v053 = load(V053)
    if int(v053.get("detector_execution_eligible_count", -1)) != EXPECTED_V053_OPPS:
        raise RuntimeError("REFUSING: v053 opportunity count changed")
    q053 = read_csv(V053_QUEUE)
    if len(q053) != EXPECTED_V053_OPPS:
        raise RuntimeError("REFUSING: v053 queue row count changed")

    v054 = load(V054)
    endpoints = read_csv(V054_ENDPOINTS)
    pair_plan = load(V054_PAIRS)
    tiles = read_csv(V054_TILES)
    if int(v054.get("opportunity_count", -1)) != EXPECTED_V053_OPPS:
        raise RuntimeError("REFUSING: v054 opportunity count changed")
    if int(v054.get("endpoint_count", -1)) != EXPECTED_V054_ENDPOINTS or len(endpoints) != EXPECTED_V054_ENDPOINTS:
        raise RuntimeError("REFUSING: v054 endpoint count changed")
    if int(v054.get("unique_tile_count", -1)) != EXPECTED_V054_TILES or len(tiles) != EXPECTED_V054_TILES:
        raise RuntimeError("REFUSING: v054 tile count changed")
    if len(pair_plan.get("pairs") or []) != EXPECTED_V053_OPPS:
        raise RuntimeError("REFUSING: v054 pair-plan count changed")

    frozen_at = datetime.now(timezone.utc).isoformat()

    contract = {
        "contract_id": "wide_census_postdetector_adjudication_contract_v001",
        "status": "FROZEN_PROSPECTIVE_BEFORE_V056_OUTCOME",
        "frozen_at_utc": frozen_at,
        "purpose": (
            "Operationalise candidate_adjudication_policy_v002 over the full robust "
            "wide-census detector subset before inspecting the completed v056 raw-match outcome."
        ),
        "prospective_guard": {
            "v056_outcome_files_read_by_this_freeze": False,
            "forbidden_outcome_paths": [
                str(p.relative_to(ROOT)).replace("\\", "/") for p in FORBIDDEN_V056
            ],
            "threshold_retuning_after_v056": False,
            "candidate_specific_rule_changes_after_v056": False,
        },
        "source_policies": {
            "candidate_adjudication_policy_v001": {
                "path": str(POLICY_V001.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha(POLICY_V001),
                "role": "pre-Match3-outcome operational details and windows",
            },
            "candidate_adjudication_policy_v002": {
                "path": str(POLICY_V002.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha(POLICY_V002),
                "role": "post-validation generic governing policy",
            },
        },
        "frozen_universe": {
            "v052_true_overlap_opportunities": 33,
            "v052_geometry_holds_separate_unresolved_branch": 41,
            "v052_robust_no_spatial_overlap": 8,
            "v053_detector_opportunities": 33,
            "v054_unique_detector_endpoints": 53,
            "v054_native_tiles": 6293,
            "scope_boundary": (
                "This contract governs raw coincidences from the 33 robust true-footprint "
                "opportunities only. The 41 geometry holds remain unresolved and are not negatives."
            ),
        },
        "frozen_input_sha256": {
            "v052_exact_footprint": sha(V052),
            "v053_detector_plan": sha(V053),
            "v053_detector_queue": sha(V053_QUEUE),
            "v054_heavy_preflight": sha(V054),
            "v054_endpoint_plan": sha(V054_ENDPOINTS),
            "v054_pair_plan": sha(V054_PAIRS),
            "v054_tile_plan": sha(V054_TILES),
        },
        "raw_candidate_inventory": {
            "source_after_completion": "results/wide_census_pair_raw_matches_v056.csv",
            "include_every_row_at_or_below_arcsec": 10.0,
            "strict_flag_arcsec": 3.0,
            "pre_adjudication_exclusions": [],
            "do_not_filter_on": [
                "SNR", "polarity", "morphology", "catalogue proximity",
                "pair family", "candidate density", "whether another raw match shares an endpoint",
            ],
            "stable_processing_order": [
                "pair_index ascending",
                "endpoint_a tile_id lexicographic",
                "endpoint_a candidate_index ascending",
                "endpoint_b tile_id lexicographic",
                "endpoint_b candidate_index ascending",
            ],
            "raw_separation_must_not_determine_processing_inclusion": True,
            "raw_coordinate_coincidence_is_not_source_identity": True,
        },
        "detector_coverage_rule": {
            "zero_robust_sigma_state": "UNINFORMATIVE_ZERO_ROBUST_SIGMA",
            "pair_state_if_common_footprint_touches_uninformative_tile": "INCOMPLETE_UNINFORMATIVE_TILE_HOLD",
            "absence_of_raw_matches_on_affected_pair_is_scientifically_negative": False,
            "raw_matches_in_valid_covered_regions_are_still_adjudicated": True,
            "transport_or_execution_failure_is_scientific_negative": False,
        },
        "population_background_control": {
            "required": True,
            "purpose": "Contextualise pair/raw-match counts; never reject an individual candidate by population null alone.",
            "method": "deterministic_tangent_plane_shift_of_endpoint_b_candidate_coordinates",
            "shift_rings_arcsec": [60.0, 120.0],
            "directions_unit_xy": [
                [1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [0.0, -1.0],
                [0.7071067811865476, 0.7071067811865476],
                [-0.7071067811865476, 0.7071067811865476],
                [0.7071067811865476, -0.7071067811865476],
                [-0.7071067811865476, -0.7071067811865476],
            ],
            "control_count_per_pair_when_geometry_allows": 16,
            "match_gates_arcsec": [3.0, 10.0],
            "footprint_rule": (
                "After shifting, retain only shifted coordinates lying inside the same exact "
                "v054 common-sky polygon; report the valid shifted denominator for each control."
            ),
            "no_candidate_outcome_used_to_choose_shifts": True,
        },
        "epoch_aware_static_catalogue": {
            "catalogue": "Gaia DR3",
            "target_epoch": "physical exposure-overlap midpoint",
            "ordinary_query_cone_arcsec": 120.0,
            "high_proper_motion_rescue_cone_arcsec": 900.0,
            "high_proper_motion_rescue_min_masyr": 1700.0,
            "proper_motion": (
                "Propagate Gaia rows to target epoch with apply_space_motion only when pmra/pmdec "
                "and reference epoch are available; retain rows lacking PM with explicit incompleteness caveat."
            ),
            "parallax": (
                "Record parallax and maximum annual angular amplitude but do not fold it into "
                "the ordinary-source positional gate; parallax-aware near-Earth search is separate."
            ),
            "diagnostic_endpoint_gate_arcsec": 5.0,
            "strict_endpoint_gate_arcsec": 3.0,
            "catalogue_absence_is_transience": False,
            "catalogue_association_alone_closes_pair": False,
            "identified_target_source_excluded_from_reference_fit": True,
        },
        "primary_astrometry": {
            "target_independent": True,
            "model": "translation_only_median",
            "reference_windows_arcmin": [5.0, 10.0, 20.0, 30.0],
            "window_choice": "smallest window meeting minimum common-reference count",
            "minimum_common_same_Gaia_references": 5,
            "reference_acquisition_arcsec": 15.0,
            "science_exclusion_arcsec": 30.0,
            "reference_matching": "reciprocal-nearest candidate_to_epoch_propagated_Gaia",
            "reference_clipping": False,
            "higher_order_fit": False,
            "strict_registered_match_arcsec": 3.0,
            "diagnostic_catalogue_arcsec": 5.0,
        },
        "sparse_fallback": {
            "trigger": "primary common-reference solution has fewer than 5 references at 30 arcmin",
            "confidence": "DIAGNOSTIC_ONLY",
            "model": "independent_per_archive_translation_only_median_against_epoch_propagated_Gaia",
            "minimum_independent_references_per_archive": 3,
            "maximum_window_arcmin": 30.0,
            "reference_acquisition_arcsec": 15.0,
            "science_exclusion_arcsec": 30.0,
            "reference_clipping": False,
            "higher_order_fit": False,
            "mismatch_pair_closure_requires": (
                "leave-one-reference-out robustness on sparse side(s), with every trial "
                "remaining outside the strict 3 arcsec gate; also report the 5 arcsec result"
            ),
            "sparse_solution_must_not_be_reported_as_primary_confidence": True,
        },
        "morphology": {
            "role": "contextual_only",
            "same_tile": True,
            "same_polarity": True,
            "preferred_snr_ratio": [0.75, 1.25],
            "fallback_snr_ratio": [0.5, 1.5],
            "fallback_trigger_minimum_controls": 12,
            "maximum_controls": 32,
            "science_target_exclusion_pixels": 32.0,
            "patch_radius_pixels": 10,
            "robust_outlier_abs_z": 3.5,
            "metrics": [
                "sigma_major_px", "sigma_minor_px", "ellipticity",
                "centroid_offset_px", "concentration_f3_f8", "peak_to_flux5",
            ],
            "compact_morphology_proves_transience": False,
            "ordinary_morphology_alone_closes_pair": False,
        },
        "recurrence_and_sensitivity": {
            "required_for_unexplained_common_sky_survivors": True,
            "comparison_exposure_priority": (
                "nearest adequate preceding and subsequent same-field exposures from the "
                "same observing system; independent archives may add corroboration"
            ),
            "negative_evidence_requires": [
                "adequate local background/noise characterization",
                "local candidate-coordinate SNR or forced measurement",
                "nearby comparison-star recovery",
                "equivalent-source injection/recovery or empirically equivalent completeness test",
                "plate/scan provenance and usable-region status",
            ],
            "non_detection_without_sensitivity_is_negative": False,
            "copies_or_scans_same_physical_plate_are_independent_recurrence": False,
        },
        "pair_disposition_logic": {
            "raw_match_only": "UNRESOLVED_REQUIRES_FURTHER_EVIDENCE",
            "persistent_source": (
                "CLOSED_PERSISTENT_SOURCE_EXPLANATION only when the same epoch-aware source "
                "is supported consistently after applicable target-independent registration; "
                "raw catalogue proximity alone is insufficient."
            ),
            "primary_registration_mismatch": (
                "CLOSED_RAW_COINCIDENCE_NOT_SUPPORTED_AFTER_REGISTRATION when a valid primary "
                "common-reference solution moves the pair outside the strict 3 arcsec gate."
            ),
            "sparse_registration_mismatch": (
                "CLOSED_COMMON_SKY_COINCIDENCE_SPARSE_REGISTRATION_ROBUST only when the sparse "
                "fallback prerequisites and leave-one-reference-out mismatch robustness are met."
            ),
            "surviving_registered_common_sky_match": "SURVIVES_TO_SENSITIVITY_QUALIFIED_RECURRENCE",
            "insufficient_evidence": "UNRESOLVED_REQUIRES_FURTHER_EVIDENCE",
            "uninformative_detector_coverage": (
                "Does not erase a positive raw match, but prevents interpreting absence of "
                "matches as complete negative coverage for the affected pair."
            ),
        },
        "state_and_review": {
            "preserve_frozen_measurements": True,
            "do_not_delete_closed_candidates": True,
            "pair_closure_does_not_close_individual_endpoints": True,
            "manual_review_only_after_mechanical_explanations_exhausted": True,
            "manual_review_cannot_change_frozen_thresholds": True,
            "parallax_aware_search_is_separate_hypothesis_branch": True,
        },
        "batch_order": [
            "freeze_v056_raw_inventory_without_pruning",
            "record_detector_coverage_holds",
            "deterministic_shifted_coordinate_population_background",
            "epoch_aware_Gaia_static_source_association",
            "target_independent_primary_registration",
            "predeclared_sparse_fallback_only_if_primary_insufficient",
            "deterministic_local_morphology_controls",
            "sensitivity_qualified_recurrence_and_injection_recovery_for_survivors",
            "manual_review_of_terminal_survivors_or_ambiguities_only",
            "separate_parallax_aware_branch_if_still_motivated",
        ],
    }

    write_json(CONTRACT, contract)
    contract_sha = sha(CONTRACT)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_postdetector_adjudication_freeze_v057",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "v056_outcome_read": False,
        },
        "contract_path": str(CONTRACT.relative_to(ROOT)).replace("\\", "/"),
        "contract_sha256": contract_sha,
        "frozen_at_utc": frozen_at,
        "interpretation": (
            "The post-detector adjudication logic is frozen before reading completed v056 "
            "candidate outcomes. Later automation may implement this contract but may not "
            "change its thresholds or candidate-inclusion rules in response to v056 results."
        ),
    }
    write_json(REPORT, report)

    print("Prospective contract:", CONTRACT)
    print("Contract SHA256:", contract_sha)
    print("v056 outcome files read: 0")
    print("SCIENCE PIXELS READ: 0")
    print("DETECTOR RUNS: 0")
    print("CANDIDATE STATE MUTATIONS: 0")
    print("\nFREEZE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
