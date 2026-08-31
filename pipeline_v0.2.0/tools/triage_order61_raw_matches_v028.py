from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import json
import math
import statistics

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

REPORT = BASE / "order61_whole_pair_report.json"
MATCHES = BASE / "order61_raw_coincidences.csv"

OUT_JSON = BASE / "order61_raw_match_triage.json"
OUT_STRICT = BASE / "order61_strict_match_triage.csv"
OUT_RADIAL = BASE / "order61_radial_area_null.csv"
OUT_TILES = BASE / "order61_strict_tile_concentration.csv"

EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa"
    "0fd0fee864a81d954f74fe4a5f5af25e7"
)

EXPECTED_METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd30"
    "02be90297e55bb0e0dcdd9dea1d0c4c1"
)

EXPECTED_POLICY_SHA = (
    "44fc3453c3291a7cbe72894d781729a3"
    "0943ad540aa169b2c0897b446c5c8ec7"
)

STRICT_FIELDS = [
    "strict_rank",
    "separation_arcsec",
    "poss_tile_id",
    "poss_candidate_index",
    "dasch_tile_id",
    "dasch_candidate_index",
    "poss_ra_deg",
    "poss_dec_deg",
    "dasch_ra_deg",
    "dasch_dec_deg",
    "east_offset_arcsec",
    "north_offset_arcsec",
    "poss_snr",
    "dasch_snr",
    "min_snr",
    "poss_polarity",
    "dasch_polarity",
    "same_polarity",
    "poss_endpoint_raw_degree",
    "dasch_endpoint_raw_degree",
    "poss_endpoint_strict_degree",
    "dasch_endpoint_strict_degree",
    "raw_endpoint_unique",
    "strict_endpoint_unique",
]

RADIAL_FIELDS = [
    "radius_arcsec",
    "observed_count",
    "conditional_area_expected_count",
    "conditional_area_expected_fraction",
    "binomial_sd",
    "z_vs_conditional_area_null",
]

TILE_FIELDS = [
    "archive",
    "tile_id",
    "strict_match_count",
]


def as_bool(v) -> bool:
    return str(v).strip().lower() in {
        "1", "true", "t", "yes", "y"
    }


def read_matches():
    out = []
    with MATCHES.open(
        newline="",
        encoding="utf-8-sig",
    ) as f:
        for row in csv.DictReader(f):
            out.append({
                "match_index":
                    int(row["match_index"]),
                "separation_arcsec":
                    float(row["separation_arcsec"]),
                "strict_le_3arcsec":
                    as_bool(
                        row["strict_le_3arcsec"]
                    ),
                "poss_tile_id":
                    row["poss_tile_id"],
                "poss_candidate_index":
                    int(
                        row["poss_candidate_index"]
                    ),
                "poss_ra_deg":
                    float(row["poss_ra_deg"]),
                "poss_dec_deg":
                    float(row["poss_dec_deg"]),
                "poss_snr":
                    float(row["poss_snr"]),
                "poss_polarity":
                    int(row["poss_polarity"]),
                "dasch_tile_id":
                    row["dasch_tile_id"],
                "dasch_candidate_index":
                    int(
                        row["dasch_candidate_index"]
                    ),
                "dasch_ra_deg":
                    float(row["dasch_ra_deg"]),
                "dasch_dec_deg":
                    float(row["dasch_dec_deg"]),
                "dasch_snr":
                    float(row["dasch_snr"]),
                "dasch_polarity":
                    int(row["dasch_polarity"]),
            })
    return out


def write_csv(path, rows, fieldnames):
    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)

    tmp.replace(path)


def robust_summary(vals):
    vals = [
        float(x)
        for x in vals
        if math.isfinite(float(x))
    ]

    if not vals:
        return {
            "n": 0,
            "median": None,
            "mad": None,
            "robust_sigma": None,
            "mean": None,
            "stdev": None,
        }

    med = statistics.median(vals)

    mad = statistics.median(
        abs(x - med)
        for x in vals
    )

    return {
        "n":
            len(vals),
        "median":
            med,
        "mad":
            mad,
        "robust_sigma":
            1.4826 * mad,
        "mean":
            statistics.fmean(vals),
        "stdev":
            (
                statistics.stdev(vals)
                if len(vals) > 1
                else 0.0
            ),
    }


def endpoint_keys(row):
    pk = (
        row["poss_tile_id"],
        row["poss_candidate_index"],
    )

    dk = (
        row["dasch_tile_id"],
        row["dasch_candidate_index"],
    )

    return pk, dk


def main():
    print(
        "=" * 84
    )
    print(
        "ORDER 61 — RAW COINCIDENCE TRIAGE"
    )
    print(
        "=" * 84
    )
    print(
        "Read-only with respect to detector and pixels."
    )
    print(
        "No external catalogue query is performed."
    )
    print()

    if not REPORT.is_file():
        raise RuntimeError(
            f"Missing report: {REPORT}"
        )

    if not MATCHES.is_file():
        raise RuntimeError(
            f"Missing raw-match CSV: {MATCHES}"
        )

    report = json.loads(
        REPORT.read_text(
            encoding="utf-8"
        )
    )

    guards = {
        "detector_sha":
            report.get(
                "detector_sha256"
            )
            == EXPECTED_DETECTOR_SHA,

        "method_sha":
            report.get(
                "method_sha256"
            )
            == EXPECTED_METHOD_SHA,

        "policy_sha":
            report.get(
                "policy_sha256"
            )
            == EXPECTED_POLICY_SHA,

        "report_status":
            report.get(
                "status"
            )
            == "COMPLETE",

        "canonical_order":
            int(
                report.get(
                    "canonical_order",
                    -1,
                )
            )
            == 61,
    }

    if not all(
        guards.values()
    ):
        raise RuntimeError(
            "REFUSING: report guard failure: "
            + json.dumps(
                guards,
                sort_keys=True,
            )
        )

    rows = read_matches()

    expected_raw = int(
        report["raw_le_10arcsec"]
    )

    expected_strict = int(
        report["raw_le_3arcsec"]
    )

    strict = [
        r
        for r in rows
        if r["strict_le_3arcsec"]
    ]

    if len(rows) != expected_raw:
        raise RuntimeError(
            "REFUSING: raw-match count "
            f"{len(rows)} != report "
            f"{expected_raw}"
        )

    if len(strict) != expected_strict:
        raise RuntimeError(
            "REFUSING: strict-match count "
            f"{len(strict)} != report "
            f"{expected_strict}"
        )

    # --------------------------------------------------------
    # Conditional radial-area null.
    #
    # This is deliberately modest:
    # conditional on the observed set of <=10" pairs,
    # a spatially uniform unrelated-pair population has
    # P(R <= r | R <= 10") = (r / 10)^2.
    #
    # It is NOT a complete chance-coincidence model because
    # source density, clustering, astrometric errors, and
    # plate systematics are not modeled here.
    # --------------------------------------------------------

    radii = [
        0.5,
        1.0,
        2.0,
        3.0,
        5.0,
        7.5,
        10.0,
    ]

    radial_rows = []

    n = len(rows)

    for radius in radii:
        obs = sum(
            r["separation_arcsec"]
            <= radius
            for r in rows
        )

        p = (
            radius / 10.0
        ) ** 2

        expected = (
            n * p
        )

        sd = math.sqrt(
            n
            * p
            * (
                1.0 - p
            )
        )

        z = (
            (
                obs - expected
            ) / sd
            if sd > 0
            else 0.0
        )

        radial_rows.append({
            "radius_arcsec":
                radius,
            "observed_count":
                obs,
            "conditional_area_expected_count":
                expected,
            "conditional_area_expected_fraction":
                p,
            "binomial_sd":
                sd,
            "z_vs_conditional_area_null":
                z,
        })

    # --------------------------------------------------------
    # Endpoint multiplicity / uniqueness.
    # --------------------------------------------------------

    raw_p_degree = Counter()
    raw_d_degree = Counter()

    strict_p_degree = Counter()
    strict_d_degree = Counter()

    for r in rows:
        pk, dk = endpoint_keys(r)
        raw_p_degree[pk] += 1
        raw_d_degree[dk] += 1

    for r in strict:
        pk, dk = endpoint_keys(r)
        strict_p_degree[pk] += 1
        strict_d_degree[dk] += 1

    # --------------------------------------------------------
    # Position-vector diagnostics for strict pairs.
    # --------------------------------------------------------

    strict_rows = []

    for r in strict:
        p = SkyCoord(
            r["poss_ra_deg"] * u.deg,
            r["poss_dec_deg"] * u.deg,
            frame="icrs",
        )

        d = SkyCoord(
            r["dasch_ra_deg"] * u.deg,
            r["dasch_dec_deg"] * u.deg,
            frame="icrs",
        )

        east, north = (
            p.spherical_offsets_to(d)
        )

        pk, dk = endpoint_keys(r)

        item = dict(r)

        item.update({
            "east_offset_arcsec":
                float(
                    east.to_value(
                        u.arcsec
                    )
                ),

            "north_offset_arcsec":
                float(
                    north.to_value(
                        u.arcsec
                    )
                ),

            "min_snr":
                min(
                    r["poss_snr"],
                    r["dasch_snr"],
                ),

            "same_polarity":
                (
                    r["poss_polarity"]
                    == r["dasch_polarity"]
                ),

            "poss_endpoint_raw_degree":
                raw_p_degree[pk],

            "dasch_endpoint_raw_degree":
                raw_d_degree[dk],

            "poss_endpoint_strict_degree":
                strict_p_degree[pk],

            "dasch_endpoint_strict_degree":
                strict_d_degree[dk],

            "raw_endpoint_unique":
                (
                    raw_p_degree[pk] == 1
                    and raw_d_degree[dk] == 1
                ),

            "strict_endpoint_unique":
                (
                    strict_p_degree[pk] == 1
                    and strict_d_degree[dk] == 1
                ),
        })

        strict_rows.append(
            item
        )

    # Outcome-independent ordering for inspection:
    # separation first, then minimum SNR.
    strict_rows.sort(
        key=lambda r: (
            r["separation_arcsec"],
            -r["min_snr"],
        )
    )

    for i, r in enumerate(
        strict_rows,
        1,
    ):
        r["strict_rank"] = i

    # --------------------------------------------------------
    # Concentration by native detector tile.
    # --------------------------------------------------------

    pt = Counter(
        r["poss_tile_id"]
        for r in strict_rows
    )

    dt = Counter(
        r["dasch_tile_id"]
        for r in strict_rows
    )

    tile_rows = [
        {
            "archive":
                "POSS-I",
            "tile_id":
                k,
            "strict_match_count":
                v,
        }
        for k, v in
        sorted(
            pt.items(),
            key=lambda kv: (
                -kv[1],
                kv[0],
            ),
        )
    ]

    tile_rows.extend([
        {
            "archive":
                "DASCH",
            "tile_id":
                k,
            "strict_match_count":
                v,
        }
        for k, v in
        sorted(
            dt.items(),
            key=lambda kv: (
                -kv[1],
                kv[0],
            ),
        )
    ])

    same_pol = sum(
        r["same_polarity"]
        for r in strict_rows
    )

    unique_raw = sum(
        r["raw_endpoint_unique"]
        for r in strict_rows
    )

    unique_strict = sum(
        r["strict_endpoint_unique"]
        for r in strict_rows
    )

    thresholds = {}

    for t in (
        4.0,
        5.0,
        7.0,
        10.0,
    ):
        thresholds[str(t)] = {
            "both_snr_ge":
                sum(
                    r["min_snr"] >= t
                    for r in strict_rows
                ),

            "both_snr_ge_and_same_polarity":
                sum(
                    r["min_snr"] >= t
                    and r["same_polarity"]
                    for r in strict_rows
                ),
        }

    east_summary = robust_summary(
        r["east_offset_arcsec"]
        for r in strict_rows
    )

    north_summary = robust_summary(
        r["north_offset_arcsec"]
        for r in strict_rows
    )

    strict_sep_summary = robust_summary(
        r["separation_arcsec"]
        for r in strict_rows
    )

    strict_null = next(
        r
        for r in radial_rows
        if r["radius_arcsec"] == 3.0
    )

    summary = {
        "status":
            "COMPLETE",

        "analysis_kind":
            "post_detection_raw_match_triage",

        "detector_rerun":
            False,

        "pixels_read":
            False,

        "external_catalogue_query":
            False,

        "canonical_order":
            61,

        "actual_overlap_s":
            float(
                report[
                    "actual_overlap_s"
                ]
            ),

        "guards":
            guards,

        "counts": {
            "poss_candidates":
                int(
                    report[
                        "poss_candidate_count"
                    ]
                ),

            "dasch_candidates":
                int(
                    report[
                        "dasch_candidate_count_in_acquired_bbox"
                    ]
                ),

            "raw_le_10arcsec":
                len(rows),

            "raw_le_3arcsec":
                len(strict),

            "strict_same_polarity":
                same_pol,

            "strict_raw_endpoint_unique":
                unique_raw,

            "strict_endpoint_unique_within_3arcsec":
                unique_strict,
        },

        "conditional_radial_area_null": {
            "description":
                (
                    "Conditional on the observed <=10 arcsec "
                    "pair set, unrelated spatially uniform "
                    "pairs have P(R<=r)=(r/10)^2. This is a "
                    "diagnostic only, not a full source-density "
                    "or plate-error null model."
                ),

            "strict_observed":
                strict_null[
                    "observed_count"
                ],

            "strict_expected":
                strict_null[
                    "conditional_area_expected_count"
                ],

            "strict_binomial_sd":
                strict_null[
                    "binomial_sd"
                ],

            "strict_z":
                strict_null[
                    "z_vs_conditional_area_null"
                ],
        },

        "strict_separation_arcsec":
            strict_sep_summary,

        "strict_vector_offsets_arcsec": {
            "east":
                east_summary,
            "north":
                north_summary,
        },

        "strict_snr_thresholds":
            thresholds,

        "endpoint_multiplicity": {
            "raw_unique_poss_endpoints":
                len(raw_p_degree),

            "raw_unique_dasch_endpoints":
                len(raw_d_degree),

            "raw_poss_endpoints_degree_gt1":
                sum(
                    v > 1
                    for v in raw_p_degree.values()
                ),

            "raw_dasch_endpoints_degree_gt1":
                sum(
                    v > 1
                    for v in raw_d_degree.values()
                ),

            "strict_unique_poss_endpoints":
                len(strict_p_degree),

            "strict_unique_dasch_endpoints":
                len(strict_d_degree),

            "strict_poss_endpoints_degree_gt1":
                sum(
                    v > 1
                    for v in strict_p_degree.values()
                ),

            "strict_dasch_endpoints_degree_gt1":
                sum(
                    v > 1
                    for v in strict_d_degree.values()
                ),
        },

        "top_strict_tiles": {
            "poss":
                pt.most_common(10),

            "dasch":
                dt.most_common(10),
        },

        "next_stage":
            (
                "Gaia DR3/static-source rejection with "
                "epoch propagation to the 1953 exposure epoch, "
                "followed by local morphology/PSF/saturation "
                "and registration vetting for survivors."
            ),
    }

    write_csv(
        OUT_STRICT,
        strict_rows,
        STRICT_FIELDS,
    )

    write_csv(
        OUT_RADIAL,
        radial_rows,
        RADIAL_FIELDS,
    )

    write_csv(
        OUT_TILES,
        tile_rows,
        TILE_FIELDS,
    )

    tmp = OUT_JSON.with_suffix(
        ".json.tmp"
    )

    tmp.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    tmp.replace(
        OUT_JSON
    )

    print(
        "Report guards: PASS"
    )
    print(
        f"Raw <=10 arcsec: {len(rows)}"
    )
    print(
        f"Strict <=3 arcsec: {len(strict)}"
    )
    print()

    print(
        "CONDITIONAL RADIAL-AREA NULL"
    )
    print(
        f"  expected <=3\": "
        f"{strict_null['conditional_area_expected_count']:.3f}"
    )
    print(
        f"  observed <=3\": "
        f"{strict_null['observed_count']}"
    )
    print(
        f"  binomial SD:   "
        f"{strict_null['binomial_sd']:.3f}"
    )
    print(
        f"  z:             "
        f"{strict_null['z_vs_conditional_area_null']:.3f}"
    )
    print()

    print(
        "STRICT MATCH STRUCTURE"
    )
    print(
        f"  same polarity: "
        f"{same_pol}/{len(strict)}"
    )
    print(
        f"  unique endpoints in raw <=10\" graph: "
        f"{unique_raw}/{len(strict)}"
    )
    print(
        f"  unique endpoints within strict graph: "
        f"{unique_strict}/{len(strict)}"
    )
    print(
        f"  median east offset: "
        f"{east_summary['median']:.4f}\""
    )
    print(
        f"  median north offset: "
        f"{north_summary['median']:.4f}\""
    )
    print(
        f"  east robust sigma: "
        f"{east_summary['robust_sigma']:.4f}\""
    )
    print(
        f"  north robust sigma: "
        f"{north_summary['robust_sigma']:.4f}\""
    )
    print()

    print(
        "STRICT MATCHES BY MINIMUM SNR"
    )
    for t in (
        "4.0",
        "5.0",
        "7.0",
        "10.0",
    ):
        q = thresholds[t]
        print(
            f"  >= {t:4s}: "
            f"{q['both_snr_ge']:2d} "
            f"(same polarity "
            f"{q['both_snr_ge_and_same_polarity']:2d})"
        )

    print()
    print(
        "Top DASCH strict-match tiles:"
    )
    for k, v in dt.most_common(10):
        print(
            f"  {k}: {v}"
        )

    print()
    print(
        "Outputs:"
    )
    print(
        " ",
        OUT_JSON,
    )
    print(
        " ",
        OUT_STRICT,
    )
    print(
        " ",
        OUT_RADIAL,
    )
    print(
        " ",
        OUT_TILES,
    )
    print()
    print(
        "No detector parameters changed."
    )
    print(
        "No image pixels were read."
    )
    print(
        "No candidate was discarded."
    )


if __name__ == "__main__":
    main()
