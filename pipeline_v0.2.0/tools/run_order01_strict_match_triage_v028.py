from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import math

ROOT = Path.cwd()
RESULT = ROOT / "results" / "order01_native_full_v028"

REPORT = RESULT / "order01_whole_pair_report.json"
MATCHES = RESULT / "order01_raw_coincidences.csv"
OUT_CSV = RESULT / "order01_strict_match_triage_v028.csv"
OUT_JSON = RESULT / "order01_strict_match_triage_v028.json"

EXPECTED_ORDER = 1
EXPECTED_OVERLAP_S = 3480.0
EXPECTED_RAW10 = 476
EXPECTED_STRICT3 = 38
EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"

# Candidate match CSV field aliases, deliberately schema-tolerant but not semantic-tolerant.
ALIASES = {
    "sep": ["separation_arcsec", "sep_arcsec", "angular_separation_arcsec", "separation"],
    "strict": ["strict_le_3arcsec", "strict", "le_3arcsec"],
    "p_tile": ["poss_tile_id", "p_tile_id", "poss_tile", "tile_id_poss"],
    "d_tile": ["dasch_tile_id", "d_tile_id", "dasch_tile", "tile_id_dasch"],
    "p_idx": ["poss_candidate_index", "p_candidate_index", "poss_index", "candidate_index_poss"],
    "d_idx": ["dasch_candidate_index", "d_candidate_index", "dasch_index", "candidate_index_dasch"],
    "p_ra": ["poss_ra_deg", "p_ra_deg", "ra_deg_poss"],
    "p_dec": ["poss_dec_deg", "p_dec_deg", "dec_deg_poss"],
    "d_ra": ["dasch_ra_deg", "d_ra_deg", "ra_deg_dasch"],
    "d_dec": ["dasch_dec_deg", "d_dec_deg", "dec_deg_dasch"],
    "p_snr": ["poss_snr", "p_snr", "snr_poss"],
    "d_snr": ["dasch_snr", "d_snr", "snr_dasch"],
    "p_pol": ["poss_polarity", "p_polarity", "polarity_poss"],
    "d_pol": ["dasch_polarity", "d_polarity", "polarity_dasch"],
}


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def truthy(v) -> bool:
    s = str(v).strip().lower()
    return s in {"true", "1", "yes", "y", "t"}


def resolve(fields, key, required=True):
    lower = {str(f).strip().lower(): f for f in fields}
    hits = [lower[a.lower()] for a in ALIASES[key] if a.lower() in lower]
    if len(hits) == 1:
        return hits[0]
    if required:
        raise RuntimeError(
            f"REFUSING: could not uniquely resolve field {key!r}; "
            f"aliases={ALIASES[key]!r}; fields={fields!r}; hits={hits!r}"
        )
    return None


def fnum(row, field):
    if field is None:
        return None
    s = str(row.get(field, "")).strip()
    return float(s) if s else None


def inum(row, field):
    if field is None:
        return None
    s = str(row.get(field, "")).strip()
    return int(float(s)) if s else None


def main():
    print("=" * 108)
    print("ORDER 01 — STRICT RAW-MATCH TRIAGE v028")
    print("=" * 108)
    print("Completed-product analysis only: no detector, no image pixels, no catalogue/network query.")
    print()

    for p in (REPORT, MATCHES):
        if not p.is_file():
            raise RuntimeError(f"Missing completed Order-1 product: {p}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    rows = read_csv(MATCHES)
    if not rows:
        raise RuntimeError("REFUSING: raw coincidence CSV is empty")

    # Guard the completed science product, not the known cosmetic console label.
    guards = {
        "report_status": report.get("status") == "COMPLETE",
        "canonical_order": int(report.get("canonical_order", -1)) == EXPECTED_ORDER,
        "poss_id": report.get("poss_exposure_id") == "POSS-I:413:E:rec297",
        "poss_region": report.get("poss_region") == "XE296",
        "poss_plate": report.get("poss_plate_id") == "06S2",
        "dasch_plate": str(report.get("dasch_plate_id", "")).lower() == "ai43437",
        "overlap": abs(float(report.get("actual_overlap_s", -1)) - EXPECTED_OVERLAP_S) < 1e-6,
        "detector_sha": report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method_sha": report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "raw10_report": int(report.get("raw_le_10arcsec", -1)) == EXPECTED_RAW10,
        "strict3_report": int(report.get("raw_le_3arcsec", -1)) == EXPECTED_STRICT3,
        "raw_csv_rows": len(rows) == EXPECTED_RAW10,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed Order-1 report guard failure: " + repr(guards))

    fields = list(rows[0].keys())
    mapping = {
        "sep": resolve(fields, "sep"),
        "strict": resolve(fields, "strict"),
        "p_tile": resolve(fields, "p_tile"),
        "d_tile": resolve(fields, "d_tile"),
        "p_idx": resolve(fields, "p_idx"),
        "d_idx": resolve(fields, "d_idx"),
        "p_ra": resolve(fields, "p_ra", required=False),
        "p_dec": resolve(fields, "p_dec", required=False),
        "d_ra": resolve(fields, "d_ra", required=False),
        "d_dec": resolve(fields, "d_dec", required=False),
        "p_snr": resolve(fields, "p_snr"),
        "d_snr": resolve(fields, "d_snr"),
        "p_pol": resolve(fields, "p_pol"),
        "d_pol": resolve(fields, "d_pol"),
    }

    strict = [
        r for r in rows
        if truthy(r[mapping["strict"]]) or float(r[mapping["sep"]]) <= 3.0
    ]
    if len(strict) != EXPECTED_STRICT3:
        raise RuntimeError(
            f"REFUSING: strict CSV reconstruction gave {len(strict)}, expected {EXPECTED_STRICT3}"
        )

    # Sort deterministically by separation, then physical candidate identities.
    strict.sort(
        key=lambda r: (
            float(r[mapping["sep"]]),
            str(r[mapping["p_tile"]]),
            int(float(r[mapping["p_idx"]])),
            str(r[mapping["d_tile"]]),
            int(float(r[mapping["d_idx"]])),
        )
    )

    out_rows = []
    p_keys = []
    d_keys = []
    same_pol = 0
    opposite_pol = 0

    for rank, r in enumerate(strict, 1):
        pkey = f"{r[mapping['p_tile']]}::{int(float(r[mapping['p_idx']]))}"
        dkey = f"{r[mapping['d_tile']]}::{int(float(r[mapping['d_idx']]))}"
        p_keys.append(pkey)
        d_keys.append(dkey)

        pp = int(float(r[mapping["p_pol"]]))
        dp = int(float(r[mapping["d_pol"]]))
        same = pp == dp
        same_pol += int(same)
        opposite_pol += int(not same)

        out_rows.append({
            "strict_rank": rank,
            "separation_arcsec": float(r[mapping["sep"]]),
            "same_polarity": same,
            "poss_candidate_key": pkey,
            "dasch_candidate_key": dkey,
            "poss_tile_id": r[mapping["p_tile"]],
            "poss_candidate_index": int(float(r[mapping["p_idx"]])),
            "poss_ra_deg": fnum(r, mapping["p_ra"]),
            "poss_dec_deg": fnum(r, mapping["p_dec"]),
            "poss_snr": float(r[mapping["p_snr"]]),
            "poss_polarity": pp,
            "dasch_tile_id": r[mapping["d_tile"]],
            "dasch_candidate_index": int(float(r[mapping["d_idx"]])),
            "dasch_ra_deg": fnum(r, mapping["d_ra"]),
            "dasch_dec_deg": fnum(r, mapping["d_dec"]),
            "dasch_snr": float(r[mapping["d_snr"]]),
            "dasch_polarity": dp,
        })

    unique_p = len(set(p_keys))
    unique_d = len(set(d_keys))

    # Under a locally uniform 2-D separation null, area <= r scales as r^2.
    n10 = len(rows)
    p3_given_10 = (3.0 / 10.0) ** 2
    exp3 = n10 * p3_given_10
    sd3 = math.sqrt(n10 * p3_given_10 * (1.0 - p3_given_10))
    z3 = (len(strict) - exp3) / sd3 if sd3 > 0 else None

    fieldnames = list(out_rows[0].keys())
    tmp_csv = OUT_CSV.with_suffix(OUT_CSV.suffix + ".tmp")
    with tmp_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    tmp_csv.replace(OUT_CSV)

    result = {
        "status": "COMPLETE",
        "analysis_kind": "order01_strict_raw_match_triage_v028",
        "guards": guards,
        "input": {
            "whole_pair_report": str(REPORT),
            "whole_pair_report_sha256": sha_file(REPORT),
            "raw_coincidences_csv": str(MATCHES),
            "raw_coincidences_sha256": sha_file(MATCHES),
            "resolved_schema": mapping,
        },
        "counts": {
            "raw_le_10arcsec": n10,
            "strict_le_3arcsec": len(strict),
            "same_polarity_strict": same_pol,
            "opposite_polarity_strict": opposite_pol,
            "unique_poss_candidates_in_strict": unique_p,
            "unique_dasch_candidates_in_strict": unique_d,
        },
        "conditional_radial_null": {
            "model": "uniform_2d_area conditional on observed <=10 arcsec associations",
            "p_le_3_given_le_10": p3_given_10,
            "expected_le_3": exp3,
            "observed_le_3": len(strict),
            "binomial_sd": sd3,
            "z_approx": z3,
            "interpretation": (
                "Diagnostic population-level control only. No positive excess is claimed "
                "from the strict raw-association count."
            ),
        },
        "strict_rows": out_rows,
        "output_csv": str(OUT_CSV),
        "known_reporting_defect": {
            "science_effect": "none identified",
            "detail": (
                "The completed Order-1 worker retained cosmetic Order-61 wording in its "
                "terminal closeout. Report identity/output paths are guarded here as Order 1. "
                "Do not rerun science merely to repair terminal text."
            ),
        },
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "catalogue_query_performed": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Run static-source rejection on the frozen 38 strict associations using "
            "the already established Order-61 Gaia-first policy, then PS1 only on Gaia-clean survivors."
        ),
    }

    tmp_json = OUT_JSON.with_suffix(OUT_JSON.suffix + ".tmp")
    tmp_json.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp_json.replace(OUT_JSON)

    print("Completed Order-1 product guards: PASS")
    print(f"Resolved match schema: {mapping}")
    print()
    print(f"Raw <=10\":                 {n10}")
    print(f"Strict <=3\":               {len(strict)}")
    print(f"Same-polarity strict:       {same_pol}")
    print(f"Opposite-polarity strict:   {opposite_pol}")
    print(f"Unique POSS candidates:     {unique_p}/{len(strict)}")
    print(f"Unique DASCH candidates:    {unique_d}/{len(strict)}")
    print()
    print("Conditional radial null (given <=10\"):")
    print(f"  expected <=3\": {exp3:.3f}")
    print(f"  observed <=3\": {len(strict)}")
    print(f"  approximate z: {z3:+.3f}")
    print()
    print("Closest strict associations:")
    for r in out_rows[:20]:
        sign = "same" if r["same_polarity"] else "opposite"
        print(
            f"  #{r['strict_rank']:02d} {r['separation_arcsec']:.4f}\" "
            f"{sign:8s} | POSS SNR={r['poss_snr']:.2f} pol={r['poss_polarity']:+d} "
            f"| DASCH SNR={r['dasch_snr']:.2f} pol={r['dasch_polarity']:+d}"
        )

    print()
    print("=" * 108)
    print("ORDER 01 STRICT RAW-MATCH TRIAGE COMPLETE")
    print("=" * 108)
    print("CSV:", OUT_CSV)
    print("JSON:", OUT_JSON)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No external catalogue was queried.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
