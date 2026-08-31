from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import re

ROOT = Path.cwd()

V057 = ROOT / "research" / "prospective_freezes" / "wide_census_postdetector_adjudication_contract_v001.json"
V061 = ROOT / "research" / "prospective_freezes" / "wide_census_postdetector_execution_plan_v061.json"
V062 = ROOT / "results" / "wide_census_population_controls_v062" / "wide_census_population_controls_v062.json"

RAW = ROOT / "results" / "wide_census_pair_raw_matches_v056.csv"
PAIR_PLAN = ROOT / "results" / "wide_census_detector_pair_plan_v054.json"
PAIR_SUM = ROOT / "results" / "wide_census_pair_raw_match_summary_v056.csv"

TIMING_CANDIDATES = [
    ROOT / "results" / "wide_census_true_overlap_survivors_v052.csv",
    ROOT / "results" / "wide_census_exact_footprint_v052.csv",
    ROOT / "results" / "wide_census_timing_survivors_for_footprint_v050.csv",
    ROOT / "results" / "wide_census_timing_survivors_for_footprint_v049a.csv",
    ROOT / "results" / "wide_census_timing_survivors_for_footprint_v049.csv",
]

OUTDIR = ROOT / "results" / "wide_census_gaia_registration_preflight_v063"
OUT_JSON = OUTDIR / "wide_census_gaia_registration_preflight_v063.json"
OUT_PAIR = OUTDIR / "wide_census_gaia_registration_pair_workload_v063.csv"
OUT_QUERY = OUTDIR / "wide_census_gaia_ordinary_query_cells_v063.csv"
OUT_HPM = OUTDIR / "wide_census_gaia_hpm_pair_queries_v063.csv"

FREEZE = ROOT / "research" / "prospective_freezes" / "wide_census_gaia_reference_acquisition_contract_v001.json"

EXPECTED_V057_SHA = "1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad"
EXPECTED_V061_SHA = "08330cb1c1693e1b40cfb7e41dd35abe721206df3a6437511cb0e642e6b5bfd3"
EXPECTED_PAIRS = 33
EXPECTED_RAW = 512788
EXPECTED_STRICT = 185532

# Transport partition only; NOT a scientific threshold.
BASE_CELL_DEG = 0.25
ORDINARY_J2016_MARGIN_ARCSEC = 120.0
HPM_J2016_MARGIN_ARCSEC = 900.0
HPM_MIN_MASYR = 1700.0
GAIA_MAXREC = 50000
MIN_SUBDIVIDED_CELL_DEG = 0.03125

# Science/adjudication values already frozen by v057/v002.
REFERENCE_ACQUISITION_ARCSEC = 15.0
SCIENCE_EXCLUSION_ARCSEC = 30.0
REFERENCE_WINDOWS_ARCMIN = [5.0, 10.0, 20.0, 30.0]
MIN_COMMON_REFS = 5
SPARSE_MIN_PER_ARCHIVE = 3


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def pick(row, *names, default=None):
    if not isinstance(row, dict):
        return default
    m = {norm(k): k for k in row}
    for name in names:
        k = m.get(norm(name))
        if k is not None and row.get(k) not in (None, ""):
            return row.get(k)
    return default


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x = fnum(v)
    return None if x is None else int(x)


def parse_dt(v):
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def midpoint_radec(ra1, dec1, ra2, dec2):
    r1, r2 = math.radians(ra1), math.radians(ra2)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    a = (
        math.cos(d1)*math.cos(r1),
        math.cos(d1)*math.sin(r1),
        math.sin(d1),
    )
    b = (
        math.cos(d2)*math.cos(r2),
        math.cos(d2)*math.sin(r2),
        math.sin(d2),
    )
    v = [a[i]+b[i] for i in range(3)]
    q = math.sqrt(sum(x*x for x in v))
    if q == 0:
        raise RuntimeError("antipodal raw-match endpoints")
    v = [x/q for x in v]
    return (
        math.degrees(math.atan2(v[1], v[0])) % 360.0,
        math.degrees(math.asin(max(-1.0, min(1.0, v[2])))),
    )


def angsep_deg(ra1, dec1, ra2, dec2):
    r1, r2 = math.radians(ra1), math.radians(ra2)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def canonical_pair(row):
    return str(pick(row, "canonical_pair", "pair_key", "canonical_pair_key", default="")).strip()


def timing_map(pair_objects):
    """
    Build exact canonical-pair -> physical overlap interval map.
    Prefer timing already embedded in v054 pair objects, then fall back to
    existing v052/v050/v049 survivor CSV products. Never invent timing.
    """
    out = {}
    provenance = {}

    for p in pair_objects:
        cp = str(p.get("canonical_pair", "")).strip()
        s = pick(p, "overlap_start_utc", "physical_overlap_start_utc")
        e = pick(p, "overlap_end_utc", "physical_overlap_end_utc")
        if cp and s and e:
            out[cp] = (str(s), str(e))
            provenance[cp] = "wide_census_detector_pair_plan_v054.json"

    for path in TIMING_CANDIDATES:
        if not path.is_file():
            continue
        rows = read_csv(path)
        for r in rows:
            cp = canonical_pair(r)
            if not cp or cp in out:
                continue
            s = pick(r, "overlap_start_utc", "physical_overlap_start_utc", "actual_overlap_start_utc")
            e = pick(r, "overlap_end_utc", "physical_overlap_end_utc", "actual_overlap_end_utc")
            if s and e:
                out[cp] = (str(s), str(e))
                provenance[cp] = str(path.relative_to(ROOT)).replace("\\", "/")

    return out, provenance


def raw_pair_index(row, canonical_to_idx):
    idx = inum(pick(row, "pair_index", "opportunity_index"))
    if idx is not None:
        # v056 pair indices are 1-based.
        if 1 <= idx <= EXPECTED_PAIRS:
            return idx
        # Defensive allowance for explicit 0-based schemas.
        if 0 <= idx < EXPECTED_PAIRS:
            return idx + 1
    cp = canonical_pair(row)
    return canonical_to_idx.get(cp)


def raw_coords(row):
    a_ra = fnum(pick(
        row,
        "endpoint_a_ra_deg", "a_ra_deg", "ra_a_deg", "candidate_a_ra_deg",
        "left_ra_deg", "poss_ra_deg",
    ))
    a_dec = fnum(pick(
        row,
        "endpoint_a_dec_deg", "a_dec_deg", "dec_a_deg", "candidate_a_dec_deg",
        "left_dec_deg", "poss_dec_deg",
    ))
    b_ra = fnum(pick(
        row,
        "endpoint_b_ra_deg", "b_ra_deg", "ra_b_deg", "candidate_b_ra_deg",
        "right_ra_deg", "dasch_ra_deg",
    ))
    b_dec = fnum(pick(
        row,
        "endpoint_b_dec_deg", "b_dec_deg", "dec_b_deg", "candidate_b_dec_deg",
        "right_dec_deg", "dasch_dec_deg",
    ))
    if None in (a_ra, a_dec, b_ra, b_dec):
        return None
    return a_ra, a_dec, b_ra, b_dec


def cell_id(ra, dec):
    # Fixed global RA/Dec partition. Query completeness comes from the
    # circumscribed-circle radius below, not from treating this as a metric grid.
    ira = int(math.floor((ra % 360.0) / BASE_CELL_DEG))
    idec = int(math.floor((dec + 90.0) / BASE_CELL_DEG))
    return ira, idec


def cell_query(ira, idec):
    ra0 = (ira + 0.5) * BASE_CELL_DEG
    dec0 = -90.0 + (idec + 0.5) * BASE_CELL_DEG

    # The spherical farthest-corner distance is evaluated explicitly.
    corners = [
        (ira*BASE_CELL_DEG, -90.0 + idec*BASE_CELL_DEG),
        ((ira+1)*BASE_CELL_DEG, -90.0 + idec*BASE_CELL_DEG),
        (ira*BASE_CELL_DEG, -90.0 + (idec+1)*BASE_CELL_DEG),
        ((ira+1)*BASE_CELL_DEG, -90.0 + (idec+1)*BASE_CELL_DEG),
    ]
    far = max(angsep_deg(ra0, dec0, ra, dec) for ra, dec in corners)
    radius_deg = far + ORDINARY_J2016_MARGIN_ARCSEC / 3600.0
    return ra0 % 360.0, dec0, radius_deg


def vector_center(points):
    v = [0.0, 0.0, 0.0]
    for ra, dec in points:
        r, d = math.radians(ra), math.radians(dec)
        v[0] += math.cos(d)*math.cos(r)
        v[1] += math.cos(d)*math.sin(r)
        v[2] += math.sin(d)
    q = math.sqrt(sum(x*x for x in v))
    if q == 0:
        raise RuntimeError("cannot determine pair raw-match center")
    v = [x/q for x in v]
    return (
        math.degrees(math.atan2(v[1], v[0])) % 360.0,
        math.degrees(math.asin(max(-1.0, min(1.0, v[2])))),
    )


def main():
    print("="*132)
    print("WIDE CENSUS — GAIA REGISTRATION REFERENCE-ACQUISITION PREFLIGHT v063")
    print("="*132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("Plans scalable Gaia acquisition; DOES NOT inspect Gaia outcomes or perform registration.\n")

    for p in (V057, V061, V062, RAW, PAIR_PLAN, PAIR_SUM):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing prerequisite {p}")

    if sha(V057) != EXPECTED_V057_SHA:
        raise RuntimeError("REFUSING: v057 prospective contract SHA changed")
    if sha(V061) != EXPECTED_V061_SHA:
        raise RuntimeError("REFUSING: v061 execution plan SHA changed")

    v62 = json.loads(V062.read_text(encoding="utf-8"))
    if v62.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: v062 population controls are not complete")

    pair_obj = json.loads(PAIR_PLAN.read_text(encoding="utf-8"))
    pairs = pair_obj.get("pairs", [])
    sums = read_csv(PAIR_SUM)
    if len(pairs) != EXPECTED_PAIRS or len(sums) != EXPECTED_PAIRS:
        raise RuntimeError("REFUSING: expected 33 pair-plan and pair-summary rows")

    for idx, (p, s) in enumerate(zip(pairs, sums), 1):
        if str(p.get("canonical_pair")) != str(s.get("canonical_pair")):
            raise RuntimeError(f"REFUSING: pair identity mismatch at {idx}")

    cp_to_idx = {str(p["canonical_pair"]): i for i, p in enumerate(pairs, 1)}
    tmap, tprov = timing_map(pairs)
    missing_timing = [p["canonical_pair"] for p in pairs if p["canonical_pair"] not in tmap]
    if missing_timing:
        raise RuntimeError(
            "REFUSING: physical overlap timing could not be recovered for "
            f"{len(missing_timing)} robust pairs: {missing_timing[:8]}"
        )

    print("Frozen science thresholds: inherited unchanged from v057/v002")
    print("Transport partition: 0.25 deg global cells; ordinary Gaia margin 120\"")
    print("High-PM rescue: one pair-level query, pm>=1700 mas/yr, +900\" margin")
    print("MAXREC handling: transport-only recursive quarter-cell subdivision")
    print()

    cells = {i: set() for i in range(1, EXPECTED_PAIRS+1)}
    points = {i: [] for i in range(1, EXPECTED_PAIRS+1)}
    counts = {i: 0 for i in range(1, EXPECTED_PAIRS+1)}
    strict = {i: 0 for i in range(1, EXPECTED_PAIRS+1)}

    total = 0
    total_strict = 0
    raw_fields = None

    with RAW.open(newline="", encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        raw_fields = list(rdr.fieldnames or [])
        for n, r in enumerate(rdr, 1):
            idx = raw_pair_index(r, cp_to_idx)
            if idx is None:
                raise RuntimeError(f"REFUSING: raw row {n} cannot be mapped to a pair")
            q = raw_coords(r)
            if q is None:
                raise RuntimeError(
                    f"REFUSING: raw row {n} coordinate schema unsupported; fields={raw_fields}"
                )
            ra1, dec1, ra2, dec2 = q
            ra, dec = midpoint_radec(ra1, dec1, ra2, dec2)
            cells[idx].add(cell_id(ra, dec))
            points[idx].append((ra, dec))
            counts[idx] += 1
            sep = fnum(pick(r, "separation_arcsec", "sep_arcsec", "raw_separation_arcsec"))
            if sep is None:
                raise RuntimeError(f"REFUSING: raw row {n} lacks separation")
            if sep <= 3.0:
                strict[idx] += 1
                total_strict += 1
            total += 1

    if total != EXPECTED_RAW or total_strict != EXPECTED_STRICT:
        raise RuntimeError(
            f"REFUSING: raw-match totals changed: total={total}, strict={total_strict}"
        )

    query_rows = []
    hpm_rows = []
    pair_rows = []

    for idx, p in enumerate(pairs, 1):
        cp = p["canonical_pair"]
        start_s, end_s = tmap[cp]
        start, end = parse_dt(start_s), parse_dt(end_s)
        if not end > start:
            raise RuntimeError(f"REFUSING: invalid physical overlap pair {idx}")
        epoch = start + (end-start)/2

        for ira, idec in sorted(cells[idx]):
            cra, cdec, radius = cell_query(ira, idec)
            query_rows.append({
                "pair_index": idx,
                "canonical_pair": cp,
                "cell_ira": ira,
                "cell_idec": idec,
                "cell_size_deg": BASE_CELL_DEG,
                "query_ra_deg": cra,
                "query_dec_deg": cdec,
                "query_radius_deg": radius,
                "ordinary_j2016_margin_arcsec": ORDINARY_J2016_MARGIN_ARCSEC,
                "maxrec": GAIA_MAXREC,
                "if_maxrec_hit": (
                    f"subdivide cell into four recursively down to "
                    f"{MIN_SUBDIVIDED_CELL_DEG} deg; transport-only"
                ),
                "registration_epoch_utc": epoch.isoformat(),
            })

        center = vector_center(points[idx])
        far = max(angsep_deg(center[0], center[1], ra, dec) for ra, dec in points[idx])
        hpm_radius = far + HPM_J2016_MARGIN_ARCSEC/3600.0
        hpm_rows.append({
            "pair_index": idx,
            "canonical_pair": cp,
            "query_ra_deg": center[0],
            "query_dec_deg": center[1],
            "query_radius_deg": hpm_radius,
            "pm_min_masyr": HPM_MIN_MASYR,
            "j2016_margin_arcsec": HPM_J2016_MARGIN_ARCSEC,
            "registration_epoch_utc": epoch.isoformat(),
        })

        pair_rows.append({
            "pair_index": idx,
            "canonical_pair": cp,
            "endpoint_a": p["endpoint_a"],
            "endpoint_b": p["endpoint_b"],
            "raw_le10_matches": counts[idx],
            "raw_le3_matches": strict[idx],
            "ordinary_query_cells": len(cells[idx]),
            "hpm_queries": 1,
            "physical_overlap_start_utc": start.isoformat(),
            "physical_overlap_end_utc": end.isoformat(),
            "registration_epoch_utc": epoch.isoformat(),
            "timing_provenance": tprov[cp],
        })

    # Freeze implementation mechanics before Gaia outcomes exist.
    freeze_obj = {
        "contract_id": "wide_census_gaia_reference_acquisition_contract_v001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "science_policy_source": {
            "v057_sha256": EXPECTED_V057_SHA,
            "v061_execution_plan_sha256": EXPECTED_V061_SHA,
        },
        "purpose": (
            "Scalable Gaia DR3 reference acquisition for the already-frozen "
            "candidate-independent primary/sparse astrometric registration."
        ),
        "science_parameters_unchanged": {
            "reference_windows_arcmin": REFERENCE_WINDOWS_ARCMIN,
            "minimum_common_same_gaia_references": MIN_COMMON_REFS,
            "reference_acquisition_arcsec": REFERENCE_ACQUISITION_ARCSEC,
            "science_exclusion_arcsec": SCIENCE_EXCLUSION_ARCSEC,
            "primary_fit": "translation-only median; no clipping; no higher-order fit",
            "sparse_minimum_references_per_archive": SPARSE_MIN_PER_ARCHIVE,
            "sparse_confidence": "diagnostic_only",
        },
        "gaia": {
            "release": "DR3",
            "table": "gaiadr3.gaia_source",
            "ordinary_j2016_coverage_arcsec": ORDINARY_J2016_MARGIN_ARCSEC,
            "hpm_rescue_j2016_coverage_arcsec": HPM_J2016_MARGIN_ARCSEC,
            "hpm_rescue_min_masyr": HPM_MIN_MASYR,
            "epoch": "midpoint of each pair's authoritative physical overlap interval",
            "propagation": (
                "proper motion to registration epoch; include distance/RV perspective "
                "terms when physically usable; conservative PM-only fallback"
            ),
        },
        "transport_partition": {
            "base_cell_deg": BASE_CELL_DEG,
            "ordinary_query_geometry": (
                "one Gaia cone per occupied raw-match-midpoint cell; cone radius is "
                "spherical farthest cell corner plus 120 arcsec"
            ),
            "candidate_domain": (
                "occupied cells are generated from all <=10 arcsec raw-match midpoints; "
                "no SNR/polarity/morphology/catalogue pruning"
            ),
            "maxrec": GAIA_MAXREC,
            "maxrec_recovery": (
                "recursively quarter only the affected transport cell until response "
                f"is below MAXREC or cell size reaches {MIN_SUBDIVIDED_CELL_DEG} deg; "
                "no science threshold changes"
            ),
            "hpm_query_geometry": (
                "one high-PM pair-level cone containing every raw-match midpoint plus "
                "900 arcsec; deduplicate by Gaia source_id"
            ),
        },
        "offline_reference_construction": {
            "match_each_archive_independently": True,
            "matching": "reciprocal-nearest detector-candidate <-> epoch-propagated Gaia within 15 arcsec",
            "primary_reference": "same Gaia source_id matched independently in both archives",
            "per_target_exclusion": (
                "exclude the target raw endpoints and any reference Gaia/source within "
                "30 arcsec of the target midpoint before selecting local 5/10/20/30 arcmin window"
            ),
            "window_choice": "smallest 5/10/20/30 arcmin window containing >=5 primary references",
            "sparse_trigger": "<5 primary common references at 30 arcmin",
            "no_outcome_based_pruning": True,
        },
        "interpretation_boundary": (
            "This contract freezes query/caching mechanics only. Gaia association and "
            "astrometric outcomes have not been read. Transport subdivision is not a "
            "scientific decision and cannot promote/reject a candidate."
        ),
    }

    if FREEZE.is_file():
        old = json.loads(FREEZE.read_text(encoding="utf-8"))
        if old.get("contract_id") != freeze_obj["contract_id"]:
            raise RuntimeError("REFUSING: incompatible Gaia acquisition freeze already exists")
    else:
        write_json(FREEZE, freeze_obj)

    write_csv(
        OUT_QUERY, query_rows,
        [
            "pair_index","canonical_pair","cell_ira","cell_idec","cell_size_deg",
            "query_ra_deg","query_dec_deg","query_radius_deg",
            "ordinary_j2016_margin_arcsec","maxrec","if_maxrec_hit",
            "registration_epoch_utc",
        ],
    )
    write_csv(
        OUT_HPM, hpm_rows,
        [
            "pair_index","canonical_pair","query_ra_deg","query_dec_deg",
            "query_radius_deg","pm_min_masyr","j2016_margin_arcsec",
            "registration_epoch_utc",
        ],
    )
    write_csv(
        OUT_PAIR, pair_rows,
        [
            "pair_index","canonical_pair","endpoint_a","endpoint_b",
            "raw_le10_matches","raw_le3_matches","ordinary_query_cells",
            "hpm_queries","physical_overlap_start_utc","physical_overlap_end_utc",
            "registration_epoch_utc","timing_provenance",
        ],
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_gaia_registration_preflight_v063",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "gaia_outcomes_read": False,
            "astrometric_registration_run": False,
            "candidate_state_mutation": False,
            "automation_registry_mutation": False,
        },
        "input_sha256": {
            "v057": sha(V057),
            "v061": sha(V061),
            "v062": sha(V062),
            "raw_matches": sha(RAW),
            "pair_plan": sha(PAIR_PLAN),
            "pair_summary": sha(PAIR_SUM),
        },
        "verified": {
            "pairs": EXPECTED_PAIRS,
            "raw_le10": total,
            "raw_le3": total_strict,
            "all_physical_registration_epochs_resolved": True,
        },
        "workload": {
            "ordinary_gaia_query_cells": len(query_rows),
            "hpm_pair_queries": len(hpm_rows),
            "base_cell_deg": BASE_CELL_DEG,
            "ordinary_query_cells_min_per_pair": min(r["ordinary_query_cells"] for r in pair_rows),
            "ordinary_query_cells_median_per_pair": sorted(r["ordinary_query_cells"] for r in pair_rows)[len(pair_rows)//2],
            "ordinary_query_cells_max_per_pair": max(r["ordinary_query_cells"] for r in pair_rows),
        },
        "freeze": {
            "path": str(FREEZE.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha(FREEZE),
        },
        "raw_match_schema": raw_fields,
        "next_stage": (
            "Execute cached Gaia DR3 ordinary/HPM acquisition under this frozen "
            "transport plan, propagate to each physical-overlap epoch, construct "
            "target-independent common-reference pools, then perform offline "
            "5/10/20/30 arcmin primary registration for all raw matches."
        ),
    }
    write_json(OUT_JSON, report)

    print("="*132)
    print("GAIA REGISTRATION PREFLIGHT COMPLETE")
    print("="*132)
    print("Pairs:", EXPECTED_PAIRS)
    print("Raw <=10 matches:", total)
    print("Raw <=3 matches:", total_strict)
    print("Ordinary Gaia query cells:", len(query_rows))
    print("High-PM pair queries:", len(hpm_rows))
    print(
        "Ordinary cells per pair min/median/max:",
        report["workload"]["ordinary_query_cells_min_per_pair"],
        report["workload"]["ordinary_query_cells_median_per_pair"],
        report["workload"]["ordinary_query_cells_max_per_pair"],
    )
    print("Gaia outcomes read: 0")
    print("Registration runs: 0")
    print("Freeze:", FREEZE)
    print("Freeze SHA256:", sha(FREEZE))
    print("STAGE STATUS: PASS")


if __name__ == "__main__":
    main()
