from __future__ import annotations

from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import statistics

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

PS1_TRIAGE = BASE / "order01_ps1_static_triage_v028.csv"
MORPH_SUMMARY = (
    BASE / "order01_matched_peer_morphology_v028"
    / "order01_matched_peer_candidate_summary_v028.csv"
)
MORPH_ENDPOINT = (
    BASE / "order01_matched_peer_morphology_v028"
    / "order01_matched_peer_endpoint_metrics_v028.csv"
)
INJECTION_REPORT = BASE / "order01_injection_recovery_report_v028.json"

STAGE1_REPORT = BASE / "order01_platephot_stage1_report_v028c.json"
STAGE1_DETAIL = BASE / "order01_platephot_stage1_detail_v028c.csv"
STAGE2_REPORT = BASE / "order01_platephot_stage2_report_v028c.json"
STAGE2_DETAIL = BASE / "order01_platephot_stage2_detail_new_v028c.csv"
STAGE3_REPORT = BASE / "order01_platephot_stage3_report_v028c.json"
STAGE3_DETAIL = BASE / "order01_platephot_stage3_detail_new_v028c.csv"

OUT_CSV = BASE / "order01_post1024_adjudication_v028c.csv"
OUT_JSON = BASE / "order01_post1024_adjudication_v028c.json"
OUT_MD = BASE / "ORDER01_POST1024_ADJUDICATION_V028C.md"

EXPECTED_INPUT_RANKS = [5, 6, 8, 10, 12, 24, 25, 26, 29, 30, 36]
EXPECTED_STAGE1_RECURRENT = [6, 8]
EXPECTED_STAGE2_RECURRENT = [12, 36]
EXPECTED_STAGE3_RECURRENT = [5]
EXPECTED_ACTIVE_AFTER_1024 = [10, 24, 25, 26, 29, 30]

FIELDS = [
    "strict_rank",
    "final_disposition",
    "recurrence_stage_reached",
    "cumulative_plates_examined",
    "plates_with_source_within_3arcsec",
    "plates_with_source_within_5arcsec",
    "pair_separation_arcsec",
    "poss_snr",
    "dasch_snr",
    "poss_polarity",
    "dasch_polarity",
    "same_polarity",
    "gaia_class",
    "ps1_class",
    "morphology_status",
    "poss_morph_extreme_continuous_count",
    "dasch_morph_extreme_continuous_count",
    "poss_morph_count_hi_count",
    "dasch_morph_count_hi_count",
    "poss_injection_observed_snr",
    "dasch_injection_observed_snr",
    "poss_max_matching_polarity_snr_at_90pct_recovery",
    "dasch_max_matching_polarity_snr_at_90pct_recovery",
    "poss_observed_ge_all_tested_90pct_recovery_thresholds",
    "dasch_observed_ge_all_tested_90pct_recovery_thresholds",
    "close5_reference_group_count",
    "close5_distinct_reference_count",
    "closest_historical_sep_arcsec",
    "closest_historical_plate_id",
    "closest_historical_refcat",
    "closest_historical_ref_number",
    "closest_reference_total_detections_in_sample",
    "closest_reference_close5_detections_in_sample",
    "closest_reference_median_sep_arcsec",
    "isolated_close_match_context",
    "interpretive_label",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def as_bool(v):
    return str(v).strip().lower() in {"1", "true", "yes", "y", "t"}


def as_int(v):
    if v is None or str(v).strip() == "":
        return None
    return int(float(v))


def as_float(v):
    if v is None or str(v).strip() == "":
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def endpoint_key(row):
    return int(row["strict_rank"]), str(row["archive"]).upper()


def rank_summary_map(report, key):
    return {
        int(r["strict_rank"]): r
        for r in report[key]
    }


def max_90_threshold(endpoint_summary):
    vals = []
    by_width = endpoint_summary["matching_polarity_recovery_by_width"]
    for width in ("1.0", "2.0", "3.0"):
        if width not in by_width:
            raise RuntimeError(
                f"missing fixed injection width {width} for "
                f"rank {endpoint_summary['strict_rank']} "
                f"{endpoint_summary['archive']}"
            )
        v = by_width[width].get("snr_at_90pct_recovery")
        if v is not None:
            vals.append(float(v))
    if not vals:
        return None
    return max(vals)


def recurrence_context(rank, all_detail, plates_examined):
    rr = [
        r for r in all_detail
        if int(r["strict_rank"]) == rank
        and int(r["rank_sample_order"]) <= plates_examined
    ]
    close = [
        r for r in rr
        if float(r["sep_target_arcsec"]) <= 5.0
    ]

    if not close:
        return {
            "group_count": 0,
            "distinct_reference_count": 0,
            "closest": None,
            "context": "ZERO_WITHIN_5ARCSEC_IN_REACHED_SAMPLE",
        }

    groups = Counter(
        (str(r["refcat"]), str(r["ref_number"]))
        for r in close
    )
    closest = min(
        close,
        key=lambda r: (
            float(r["sep_target_arcsec"]),
            int(r["rank_sample_order"]),
            str(r["plate_id"]),
        ),
    )
    key = (str(closest["refcat"]), str(closest["ref_number"]))

    same_ref = [
        r for r in rr
        if (str(r["refcat"]), str(r["ref_number"])) == key
    ]
    seps = [
        float(r["sep_target_arcsec"])
        for r in same_ref
        if math.isfinite(float(r["sep_target_arcsec"]))
    ]
    close_same = [x for x in seps if x <= 5.0]

    if len(close) == 1 and len(same_ref) > 1:
        context = (
            "SINGLE_CLOSE_HIT_FROM_REFERENCE_USUALLY_FARTHER_AWAY"
        )
    elif len(close) == 1:
        context = "SINGLE_CLOSE_HIT_SPARSE_REFERENCE_HISTORY"
    elif len(groups) == 1:
        context = "MULTIPLE_CLOSE_HITS_SAME_REFERENCE_OBJECT"
    else:
        context = "MULTIPLE_CLOSE_HITS_MULTIPLE_REFERENCE_OBJECTS"

    return {
        "group_count": len(close),
        "distinct_reference_count": len(groups),
        "closest": {
            "plate_id": closest["plate_id"],
            "sep_arcsec": float(closest["sep_target_arcsec"]),
            "refcat": closest["refcat"],
            "ref_number": closest["ref_number"],
            "total_same_ref_detections": len(same_ref),
            "close5_same_ref_detections": len(close_same),
            "median_same_ref_sep_arcsec":
                statistics.median(seps) if seps else None,
        },
        "context": context,
    }


def main():
    print("=" * 104)
    print("ORDER 01 — POST-1024 BRANCH-A ADJUDICATION FREEZE v028c")
    print("=" * 104)
    print(
        "Joins completed static-catalogue, morphology, injection/recovery, and "
        "blind historical-recurrence evidence. No network, no pixels, no detector."
    )
    print()

    required = [
        PS1_TRIAGE,
        MORPH_SUMMARY,
        MORPH_ENDPOINT,
        INJECTION_REPORT,
        STAGE1_REPORT,
        STAGE1_DETAIL,
        STAGE2_REPORT,
        STAGE2_DETAIL,
        STAGE3_REPORT,
        STAGE3_DETAIL,
    ]
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage file: {p}")

    ps1 = read_csv(PS1_TRIAGE)
    morph_sum = read_csv(MORPH_SUMMARY)
    morph_ep = read_csv(MORPH_ENDPOINT)
    inj = json.loads(INJECTION_REPORT.read_text(encoding="utf-8"))
    s1 = json.loads(STAGE1_REPORT.read_text(encoding="utf-8"))
    s2 = json.loads(STAGE2_REPORT.read_text(encoding="utf-8"))
    s3 = json.loads(STAGE3_REPORT.read_text(encoding="utf-8"))

    guards = {
        "injection_complete": inj.get("status") == "COMPLETE",
        "injection_ranks":
            [int(x) for x in inj.get("survivor_ranks", [])]
            == EXPECTED_INPUT_RANKS,
        "stage1_complete": s1.get("status") == "COMPLETE",
        "stage1_recurrent":
            [int(x) for x in s1.get("stage1_recurrent_ranks_5arcsec", [])]
            == EXPECTED_STAGE1_RECURRENT,
        "stage2_complete": s2.get("status") == "COMPLETE",
        "stage2_recurrent":
            [int(x) for x in s2.get("stage2_recurrent_ranks_5arcsec", [])]
            == EXPECTED_STAGE2_RECURRENT,
        "stage3_complete": s3.get("status") == "COMPLETE",
        "stage3_recurrent":
            [int(x) for x in s3.get("stage3_recurrent_ranks_5arcsec", [])]
            == EXPECTED_STAGE3_RECURRENT,
        "stage3_active":
            [int(x) for x in s3.get("stage3_clean_ranks_5arcsec", [])]
            == EXPECTED_ACTIVE_AFTER_1024,
        "stage3_no_detector": s3.get("detector_rerun") is False,
        "stage3_no_pixels": s3.get("science_image_pixels_read") is False,
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    ps1_by_rank = {
        int(r["strict_rank"]): r
        for r in ps1
        if int(r["strict_rank"]) in EXPECTED_INPUT_RANKS
    }
    morph_sum_by_rank = {
        int(r["strict_rank"]): r
        for r in morph_sum
    }
    morph_ep_by_key = {
        endpoint_key(r): r
        for r in morph_ep
    }
    inj_by_key = {
        (int(e["strict_rank"]), str(e["archive"]).upper()): e
        for e in inj["endpoint_summaries"]
    }

    for rank in EXPECTED_INPUT_RANKS:
        if rank not in ps1_by_rank:
            raise RuntimeError(f"rank {rank} missing from PS1 triage")
        if rank not in morph_sum_by_rank:
            raise RuntimeError(f"rank {rank} missing from morphology summary")
        for archive in ("POSS", "DASCH"):
            if (rank, archive) not in morph_ep_by_key:
                raise RuntimeError(
                    f"rank {rank} {archive} missing morphology endpoint"
                )
            if (rank, archive) not in inj_by_key:
                raise RuntimeError(
                    f"rank {rank} {archive} missing injection endpoint"
                )

    s1_by_rank = rank_summary_map(s1, "rank_summaries")
    s2_by_rank = rank_summary_map(
        s2, "active_rank_summaries_cumulative_256"
    )
    s3_by_rank = rank_summary_map(
        s3, "active_rank_summaries_cumulative_1024"
    )

    detail = (
        read_csv(STAGE1_DETAIL)
        + read_csv(STAGE2_DETAIL)
        + read_csv(STAGE3_DETAIL)
    )

    rows = []
    recurrence_audit = {}

    for rank in EXPECTED_INPUT_RANKS:
        p = ps1_by_rank[rank]
        ms = morph_sum_by_rank[rank]
        me_p = morph_ep_by_key[(rank, "POSS")]
        me_d = morph_ep_by_key[(rank, "DASCH")]
        ie_p = inj_by_key[(rank, "POSS")]
        ie_d = inj_by_key[(rank, "DASCH")]

        if rank in EXPECTED_STAGE1_RECURRENT:
            rs = s1_by_rank[rank]
            plates_examined = 64
            final = "RECURRENT_STATIC_AUDIT_STAGE1_64"
            stage = "STAGE1_64"
        elif rank in EXPECTED_STAGE2_RECURRENT:
            rs = s2_by_rank[rank]
            plates_examined = 256
            final = "RECURRENT_STATIC_AUDIT_STAGE2_256"
            stage = "STAGE2_256"
        else:
            rs = s3_by_rank[rank]
            plates_examined = 1024
            stage = "STAGE3_1024"
            if rank in EXPECTED_STAGE3_RECURRENT:
                final = "RECURRENT_STATIC_AUDIT_STAGE3_1024"
            else:
                final = "ACTIVE_UNRESOLVED_BRANCH_A_AFTER_1024"

        rc = recurrence_context(rank, detail, plates_examined)
        recurrence_audit[str(rank)] = rc

        p90 = max_90_threshold(ie_p)
        d90 = max_90_threshold(ie_d)
        p_obs = float(ie_p["observed_candidate_snr"])
        d_obs = float(ie_d["observed_candidate_snr"])

        closest = rc["closest"]

        if final.startswith("RECURRENT_STATIC"):
            label = (
                "Meets prospectively fixed historical recurrence gate; "
                "retain for audit, not active Branch-A survivor."
            )
        elif rc["group_count"] == 0:
            label = (
                "Catalogue-clean unresolved Branch-A survivor with zero "
                f"historical <=5\" matches in {plates_examined} blind plates."
            )
        else:
            label = (
                "Catalogue-clean unresolved Branch-A survivor; fixed recurrence "
                "gate not met. Isolated historical close match retained as "
                "diagnostic context only."
            )

        rows.append({
            "strict_rank": rank,
            "final_disposition": final,
            "recurrence_stage_reached": stage,
            "cumulative_plates_examined": plates_examined,
            "plates_with_source_within_3arcsec":
                int(rs["plates_with_source_within_3arcsec"]),
            "plates_with_source_within_5arcsec":
                int(rs["plates_with_source_within_5arcsec"]),
            "pair_separation_arcsec":
                float(p["pair_separation_arcsec"]),
            "poss_snr": float(p["poss_snr"]),
            "dasch_snr": float(p["dasch_snr"]),
            "poss_polarity": int(float(p["poss_polarity"])),
            "dasch_polarity": int(float(p["dasch_polarity"])),
            "same_polarity": as_bool(p["same_polarity"]),
            "gaia_class": p["gaia_class"],
            "ps1_class": p["ps1_class"],
            "morphology_status": ms["pair_morphology_status"],
            "poss_morph_extreme_continuous_count":
                as_int(
                    ms[
                        "poss_matched_peer_extreme_continuous_metric_count"
                    ]
                ),
            "dasch_morph_extreme_continuous_count":
                as_int(
                    ms[
                        "dasch_matched_peer_extreme_continuous_metric_count"
                    ]
                ),
            "poss_morph_count_hi_count":
                as_int(
                    ms[
                        "poss_matched_peer_count_metric_ge95_count"
                    ]
                ),
            "dasch_morph_count_hi_count":
                as_int(
                    ms[
                        "dasch_matched_peer_count_metric_ge95_count"
                    ]
                ),
            "poss_injection_observed_snr": p_obs,
            "dasch_injection_observed_snr": d_obs,
            "poss_max_matching_polarity_snr_at_90pct_recovery": p90,
            "dasch_max_matching_polarity_snr_at_90pct_recovery": d90,
            "poss_observed_ge_all_tested_90pct_recovery_thresholds":
                None if p90 is None else p_obs >= p90,
            "dasch_observed_ge_all_tested_90pct_recovery_thresholds":
                None if d90 is None else d_obs >= d90,
            "close5_reference_group_count": rc["group_count"],
            "close5_distinct_reference_count":
                rc["distinct_reference_count"],
            "closest_historical_sep_arcsec":
                None if closest is None else closest["sep_arcsec"],
            "closest_historical_plate_id":
                None if closest is None else closest["plate_id"],
            "closest_historical_refcat":
                None if closest is None else closest["refcat"],
            "closest_historical_ref_number":
                None if closest is None else closest["ref_number"],
            "closest_reference_total_detections_in_sample":
                None
                if closest is None
                else closest["total_same_ref_detections"],
            "closest_reference_close5_detections_in_sample":
                None
                if closest is None
                else closest["close5_same_ref_detections"],
            "closest_reference_median_sep_arcsec":
                None
                if closest is None
                else closest["median_same_ref_sep_arcsec"],
            "isolated_close_match_context": rc["context"],
            "interpretive_label": label,
        })

    write_csv(OUT_CSV, rows, FIELDS)

    active = [
        r for r in rows
        if r["final_disposition"]
        == "ACTIVE_UNRESOLVED_BRANCH_A_AFTER_1024"
    ]
    recurrent = [
        r for r in rows
        if r["final_disposition"].startswith("RECURRENT_STATIC")
    ]

    report = {
        "status": "COMPLETE",
        "analysis_kind":
            "order01_post1024_branch_a_adjudication_v028c",
        "guards": guards,
        "input_sha256": {
            str(p): sha256_file(p)
            for p in required
        },
        "input_ranks": EXPECTED_INPUT_RANKS,
        "recurrent_audit_ranks": [
            int(r["strict_rank"]) for r in recurrent
        ],
        "active_unresolved_branch_a_ranks": [
            int(r["strict_rank"]) for r in active
        ],
        "recurrence_audit": recurrence_audit,
        "interpretation_policy": {
            "5arcsec_recurrence_gate":
                ">=2 distinct physical Harvard plates",
            "isolated_single_close_match_is_not_recurrence": True,
            "local_density_expected_counts_are_contextual_not_formal_significance":
                True,
            "morphology_extreme_is_diagnostic_not_automatic_veto": True,
            "injection_recovery_is_sensitivity_context_not_candidate_promotion":
                True,
            "candidate_promoted_to_confirmed_transient": False,
        },
        "no_external_query": True,
        "no_science_pixels_read": True,
        "detector_rerun": False,
        "no_candidate_deleted": True,
        "outputs": {
            "csv": str(OUT_CSV),
            "markdown": str(OUT_MD),
        },
        "next_stage": (
            "Freeze these six as unresolved Branch-A Order-1 survivors and "
            "return to the prospective <=5-minute denominator. Candidate-specific "
            "registration/physical/Branch-C work remains optional follow-up and "
            "must not alter the prospective cohort detector thresholds."
        ),
    }

    write_json(OUT_JSON, report)

    lines = [
        "# Order 01 post-1024 Branch-A adjudication — v028c",
        "",
        "No detector was rerun. No external catalogue was queried. "
        "No science image pixel was read.",
        "",
        "## Cohort disposition",
        "",
        f"- Input Gaia+PS1-clean ranks: `{EXPECTED_INPUT_RANKS}`",
        f"- Recurrence-audit ranks: `{report['recurrent_audit_ranks']}`",
        f"- Active unresolved Branch-A survivors: "
        f"`{report['active_unresolved_branch_a_ranks']}`",
        "",
        "The fixed recurrence gate remains >=2 distinct physical Harvard plates "
        "within 5 arcsec. A single close historical detection is retained as "
        "diagnostic context only.",
        "",
        "## Active survivors",
        "",
        "| rank | sep | P/D SNR | morphology | <=5in1024 | recurrence context |",
        "|---:|---:|---:|---|---:|---|",
    ]

    for r in active:
        lines.append(
            f"| {r['strict_rank']} "
            f"| {r['pair_separation_arcsec']:.3f}\" "
            f"| {r['poss_snr']:.2f}/{r['dasch_snr']:.2f} "
            f"| {r['morphology_status']} "
            f"| {r['plates_with_source_within_5arcsec']} "
            f"| {r['isolated_close_match_context']} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "These are unresolved cross-observatory candidates, not confirmed "
        "transients. The approximate local-density expected-match totals are "
        "retained only as context and are not converted into formal significance.",
        "",
        "Candidate-specific physical or parallax-aware modelling is deliberately "
        "separated from this prospective Branch-A adjudication.",
        "",
    ]

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("Completed-stage guards: PASS")
    print(
        "Recurrent/static audit ranks:",
        report["recurrent_audit_ranks"],
    )
    print(
        "Active unresolved Branch-A ranks:",
        report["active_unresolved_branch_a_ranks"],
    )
    print()
    print("Active survivor summary:")
    for r in active:
        print(
            f"  strict #{int(r['strict_rank']):02d}: "
            f"sep={float(r['pair_separation_arcsec']):.3f}\" "
            f"P/D SNR={float(r['poss_snr']):.2f}/{float(r['dasch_snr']):.2f} "
            f"morph={r['morphology_status']} "
            f"hist<=5\"={int(r['plates_with_source_within_5arcsec'])}/1024 "
            f"context={r['isolated_close_match_context']}"
        )
    print()
    print("Outputs:")
    print(" ", OUT_JSON)
    print(" ", OUT_CSV)
    print(" ", OUT_MD)
    print()
    print("No external query was made.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")


if __name__ == "__main__":
    main()
