#!/usr/bin/env python3
"""
v075 — Pair 17 epoch-aware Gaia static-source triage.

Prospectively frozen contract:
  research/prospective_freezes/pair17_epoch_aware_gaia_static_triage_contract_v075.json
  SHA256 76901ffba61cd07c5bd1d797a78112967cc85bd1dc032e137e5a878fd462cfed

This execution stage:
  * uses frozen pair-17 v068a membership;
  * uses frozen v056 detector candidates;
  * uses already-acquired offline Gaia DR3 transport only;
  * reuses the frozen v068a Gaia reader/propagation/reciprocal-nearest machinery;
  * performs no detector or astrometric-registration rerun;
  * makes no candidate disposition changes;
  * does not interpret Gaia absence as transience;
  * does not let catalogue association alone close a candidate.

PRIMARY population:
  PRIMARY registration + corrected <=3 arcsec + LOO max <=3 arcsec (expected n=424)

DIAGNOSTIC population:
  PRIMARY registration + corrected <=3 arcsec + LOO max >3 arcsec (expected n=179)
"""

from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import json
import math
import re
import socket
import sys

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"
TOOLS = ROOT / "tools"

PAIR_INDEX = 17
ENDPOINT_A = "APPLAUSE:14120"
ENDPOINT_B = "APPLAUSE:132654"
EPOCH_ISO = "1953-12-02T20:48:58.500000+00:00"

CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "pair17_epoch_aware_gaia_static_triage_contract_v075.json"
)
POLICY = TOOLS / "candidate_adjudication_policy_v002.json"
V057_BUILDER = TOOLS / "freeze_wide_census_postdetector_contract_v057.py"
V068A_SCRIPT = TOOLS / "run_wide_census_gaia_registration_v068a.py"

V068 = RESULTS / "wide_census_gaia_registration_v068a"
PAIR_SUMMARY = V068 / "pair_17_summary_v068a.json"
PAIR_REG = V068 / "pair_17_registrations_v068a.csv"

V065 = RESULTS / "wide_census_gaia_reference_coverage_audit_v065"
PAIR_CELLS = V065 / "wide_census_gaia_reference_candidate_cells_v065.csv"

V064 = RESULTS / "wide_census_gaia_acquisition_v064"
V066 = RESULTS / "wide_census_gaia_supplemental_acquisition_v066"

V056_TILES = RESULTS / "wide_census_detector_execution_v056" / "tiles"

OUT = RESULTS / "pair17_epoch_aware_gaia_static_triage_v075"
OUT_ROWS = OUT / "pair17_epoch_aware_gaia_static_triage_v075.csv"
OUT_SUMMARY = OUT / "pair17_epoch_aware_gaia_static_triage_v075.json"
OUT_PM = OUT / "pair17_gaia_pm_incomplete_context_v075.csv"
OUT_INPUTS = OUT / "pair17_static_triage_input_manifest_v075.csv"

EXPECTED_SHA = {
    CONTRACT:
        "76901ffba61cd07c5bd1d797a78112967cc85bd1dc032e137e5a878fd462cfed",
    POLICY:
        "eb8512724b2ef23b3ee88e5ffcfab8088144c984f0b75adb7b68e87198cb4cbd",
    V057_BUILDER:
        "d7a82a05225aa873e8d0b0e861c550c2a1102a9420b6092081fea814395993cb",
    V068A_SCRIPT:
        "9376ed5244b5defe074732dbb92e7870b618e25001cd2da4162b48dff549e0f2",
    PAIR_SUMMARY:
        "754c13ad9f4ce82ee0ec0c70b61a85189a06f7be57360abc0e4eae05f5aa039d",
    PAIR_REG:
        "ebbe6ff5513681a3b98a2f4deda1d4b5c7f563ca284dd399e631237cdae4b7a1",
}

EXPECTED_COUNTS = {
    "primary_registered": 1618,
    "corrected_le3": 603,
    "primary_loo": 424,
    "diagnostic": 179,
}

STRICT_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
ACQUISITION_ARCSEC = 15.0


# --------------------------------------------------------------------------------------
# Guards / utilities
# --------------------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def fail(msg):
    raise RuntimeError(msg)


def block_network():
    """Fail hard if any code in this process tries to open a network connection."""
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def denied_connect(self, *args, **kwargs):
        raise RuntimeError("NETWORK ACCESS DISALLOWED BY v075")

    def denied_create_connection(*args, **kwargs):
        raise RuntimeError("NETWORK ACCESS DISALLOWED BY v075")

    socket.socket.connect = denied_connect
    socket.create_connection = denied_create_connection
    return original_connect, original_create_connection


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        fail(f"Cannot import frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_csv_atomic(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json_atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def truth(v):
    return str(v).strip().lower() in {"true", "1", "yes"}


def ffloat(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fint(v):
    try:
        return int(str(v).strip())
    except Exception:
        try:
            x = float(v)
            if math.isfinite(x) and x.is_integer():
                return int(x)
        except Exception:
            pass
    return None


def spherical_sep_arcsec(ra1, dec1, ra2, dec2):
    r1 = math.radians(float(ra1))
    d1 = math.radians(float(dec1))
    r2 = math.radians(float(ra2))
    d2 = math.radians(float(dec2))
    sd = math.sin((d2 - d1) / 2.0)
    sr = math.sin((r2 - r1) / 2.0)
    a = sd * sd + math.cos(d1) * math.cos(d2) * sr * sr
    a = min(1.0, max(0.0, a))
    return math.degrees(2.0 * math.asin(math.sqrt(a))) * 3600.0


def chord_radius_arcsec(arcsec):
    return 2.0 * math.sin(math.radians(arcsec / 3600.0) / 2.0)


# --------------------------------------------------------------------------------------
# Pair membership
# --------------------------------------------------------------------------------------

def load_pair_membership():
    with PAIR_REG.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    primary_registered = sum(r["registration_mode"] == "PRIMARY" for r in rows)

    corrected = [
        r for r in rows
        if r["registration_mode"] == "PRIMARY" and truth(r["corrected_le3"])
    ]

    primary = []
    diagnostic = []

    for r in corrected:
        loo = ffloat(r["loo_corrected_sep_max_arcsec"])
        if loo is None:
            fail("PRIMARY corrected<=3 row has non-finite LOO max")
        if loo <= STRICT_ARCSEC:
            primary.append(r)
        else:
            diagnostic.append(r)

    got = {
        "primary_registered": primary_registered,
        "corrected_le3": len(corrected),
        "primary_loo": len(primary),
        "diagnostic": len(diagnostic),
    }

    if got != EXPECTED_COUNTS:
        fail(f"Frozen pair-17 population changed: expected {EXPECTED_COUNTS}, got {got}")

    # Identity uniqueness is part of the already-observed mechanical topology result.
    keys = set()
    for r in corrected:
        k = (
            r["a_tile_id"], int(r["a_candidate_index"]),
            r["b_tile_id"], int(r["b_candidate_index"]),
        )
        if k in keys:
            fail(f"Duplicate registered pair identity in frozen pair 17: {k}")
        keys.add(k)

    return corrected, {id(r): "PRIMARY_424" for r in primary}


# --------------------------------------------------------------------------------------
# Frozen v056 detector candidates
# --------------------------------------------------------------------------------------

def endpoint_dir_name(endpoint):
    return endpoint.replace(":", "_").replace("/", "_").replace("?", "_")


def find_endpoint_dir(endpoint):
    preferred = V056_TILES / endpoint_dir_name(endpoint)
    if preferred.is_dir():
        return preferred

    # Operational fallback: endpoint_key is authoritative; inspect one row only
    # from candidate CSVs in plausibly named directories.
    token = endpoint.split(":", 1)[1]
    candidates = [
        p for p in V056_TILES.iterdir()
        if p.is_dir() and token in p.name
    ]
    for d in sorted(candidates):
        for p in sorted(d.glob("*_candidates.csv"))[:3]:
            try:
                q = pd.read_csv(p, nrows=1)
            except Exception:
                continue
            if "endpoint_key" in q.columns and len(q) and str(q.iloc[0]["endpoint_key"]) == endpoint:
                return d
    fail(f"Cannot resolve frozen v056 endpoint directory for {endpoint}")


def load_endpoint_candidates(endpoint):
    d = find_endpoint_dir(endpoint)
    files = sorted(d.glob("*_candidates.csv"))
    if not files:
        fail(f"No frozen v056 candidate CSVs for {endpoint}: {d}")

    frames = []
    manifest = []

    for p in files:
        df = pd.read_csv(p)
        if len(df) == 0:
            continue

        required = {"endpoint_key", "tile_id", "candidate_index", "ra_deg", "dec_deg"}
        if not required.issubset(df.columns):
            fail(f"Unexpected v056 schema in {p}: {list(df.columns)}")

        bad = df["endpoint_key"].astype(str) != endpoint
        if bool(bad.any()):
            fail(f"Endpoint-key mismatch inside {p}")

        frames.append(df)
        manifest.append({
            "kind": "v056_candidate_csv",
            "endpoint": endpoint,
            "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            "size_bytes": p.stat().st_size,
            "sha256": sha256(p),
        })

    if not frames:
        fail(f"All candidate files empty for {endpoint}")

    full = pd.concat(frames, ignore_index=True)

    if full[["ra_deg", "dec_deg"]].isna().any().any():
        fail(f"Non-finite detector coordinates in {endpoint}")

    # The immutable detector identity is endpoint + tile_id + candidate_index.
    id_map = {}
    for idx, r in full.iterrows():
        k = (str(r["tile_id"]), int(r["candidate_index"]))
        if k in id_map:
            fail(f"Duplicate frozen detector identity for {endpoint}: {k}")
        id_map[k] = int(idx)

    return full, id_map, manifest


# --------------------------------------------------------------------------------------
# Exact pair-17 Gaia source domain
# --------------------------------------------------------------------------------------

def infer_pair_cell_keys(df, valid_keys):
    if "pair_index" not in df.columns:
        fail(f"PAIR_CELLS lacks pair_index: {list(df.columns)}")

    pair = df[pd.to_numeric(df["pair_index"], errors="coerce") == PAIR_INDEX].copy()
    if len(pair) == 0:
        fail("PAIR_CELLS has no pair 17 rows")

    # Prefer columns explicitly describing a cell. Then prove the candidate
    # pair against the actual frozen v064/v066 leaf-index keys.
    numeric_cols = []
    for c in pair.columns:
        if c == "pair_index":
            continue
        vals = [fint(v) for v in pair[c].tolist()]
        if all(v is not None for v in vals):
            numeric_cols.append(c)

    def name_score(a, b):
        s = 0
        la, lb = a.lower(), b.lower()
        if "cell" in la:
            s += 3
        if "cell" in lb:
            s += 3
        if any(x in la for x in ("ra", "lon", "ix", "_i", "x")):
            s += 1
        if any(x in lb for x in ("dec", "lat", "iy", "_j", "y")):
            s += 1
        return s

    solutions = []
    cols = numeric_cols
    for a in cols:
        for b in cols:
            if a == b:
                continue
            keys = [(int(fint(x)), int(fint(y))) for x, y in zip(pair[a], pair[b])]
            uniq = list(dict.fromkeys(keys))
            hits = sum(k in valid_keys for k in uniq)
            if hits == len(uniq):
                solutions.append((name_score(a, b), len(uniq), a, b, uniq))

    if not solutions:
        fail(
            "Could not infer pair-cell key columns by exact membership in the "
            "frozen v064/v066 leaf indices."
        )

    solutions.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    best = solutions[0]

    # Multiple schemas are acceptable only if they generate exactly the same keys.
    best_set = set(best[4])
    conflicting = [
        x for x in solutions
        if x[0] == best[0] and x[1] == best[1] and set(x[4]) != best_set
    ]
    if conflicting:
        fail(
            "Ambiguous PAIR_CELLS schema: equally ranked column pairs produce "
            "different valid cell sets."
        )

    return best[4], {"column_x": best[2], "column_y": best[3], "rows": len(pair)}


def call_official_pair_loader(reg, keys, records, idx64, idx66):
    errors = []

    # Most v068a implementations construct a set/list of integer cell tuples.
    for mode, cells in (("integer_cell_tuples", keys), ("pair_cell_records", records)):
        try:
            out = reg.load_pair_gaia(PAIR_INDEX, cells, idx64, idx66)
            if not isinstance(out, tuple) or len(out) != 2:
                fail("Frozen load_pair_gaia returned unexpected object")
            gaia, meta = out
            return gaia, meta, mode
        except Exception as e:
            errors.append((mode, repr(e)))

    fail(f"Frozen v068a load_pair_gaia failed for both supported input shapes: {errors}")


def gaia_transport_files_for_keys(reg, keys, idx64, idx66, official_ids):
    paths = []
    seen = set()

    def add(p):
        p = Path(p)
        if p not in seen:
            seen.add(p)
            paths.append(p)

    for key in keys:
        for p in idx64.get(tuple(key), []):
            add(p)
        for p in idx66.get(tuple(key), []):
            add(p)

    # Add pair-specific HPM-looking files first.
    pair_re = re.compile(r"(?:pair[_-]?0*17(?:\D|$)|(?:^|\D)0*17[_-].*hpm)", re.I)
    all_hpm = []

    for base in (V064, V066):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            low = str(p).lower()
            if "hpm" not in low:
                continue
            if not (low.endswith(".csv") or low.endswith(".csv.gz")):
                continue
            all_hpm.append(p)
            if pair_re.search(p.name):
                add(p)

    def source_ids_in(path):
        try:
            q = reg.read_gaia_file(path)
        except Exception:
            return set()
        if "source_id" not in q.columns or len(q) == 0:
            return set()
        return set(int(x) for x in q["source_id"].tolist())

    covered = set()
    for p in paths:
        covered |= (source_ids_in(p) & official_ids)

    missing = official_ids - covered

    # If a pair-specific HPM filename convention was not recognised, locate only
    # files containing still-missing official source IDs. This is operational
    # source-domain recovery, not a candidate-outcome decision.
    if missing:
        for p in sorted(all_hpm):
            if p in seen:
                continue
            ids = source_ids_in(p)
            if ids & missing:
                add(p)
                covered |= (ids & official_ids)
                missing = official_ids - covered
                if not missing:
                    break

    if missing:
        fail(
            f"Could not reconstruct all official v068a finite-PM Gaia rows; "
            f"{len(missing)} source_id values remain unresolved."
        )

    return paths


def load_raw_gaia_context(reg, paths):
    frames = []
    manifest = []

    for p in paths:
        q = reg.read_gaia_file(p)
        if len(q):
            frames.append(q)
        manifest.append({
            "kind": "gaia_transport",
            "endpoint": "",
            "path": str(Path(p).relative_to(ROOT)).replace("\\", "/"),
            "size_bytes": Path(p).stat().st_size,
            # Intentionally hash the exact transport bytes used by v075.
            "sha256": sha256(Path(p)),
        })

    if not frames:
        fail("No Gaia transport rows available for pair 17")

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.drop_duplicates(subset=["source_id"], keep="first").reset_index(drop=True)

    finite_pos = (
        np.isfinite(pd.to_numeric(raw["ra"], errors="coerce").to_numpy())
        & np.isfinite(pd.to_numeric(raw["dec"], errors="coerce").to_numpy())
    )

    finite_motion = finite_pos.copy()
    for c in ("ref_epoch", "pmra", "pmdec"):
        finite_motion &= np.isfinite(pd.to_numeric(raw[c], errors="coerce").to_numpy())

    incomplete = raw.loc[finite_pos & ~finite_motion].copy().reset_index(drop=True)
    return raw, incomplete, manifest


# --------------------------------------------------------------------------------------
# Candidate <-> Gaia association
# --------------------------------------------------------------------------------------

def full_reciprocal_associations(reg, det_df, gaia_prop, gaia_meta_df):
    det = det_df[["ra_deg", "dec_deg"]].to_numpy(dtype=np.float64)
    matched = reg.reciprocal_match(det, gaia_prop)

    # Returned detector coordinates are direct slices from `det`, so exact float
    # tuple identity maps them back without re-solving the match.
    coordinate_to_indices = defaultdict(list)
    for i, (ra, dec) in enumerate(det):
        coordinate_to_indices[(float(ra), float(dec))].append(i)

    meta_by_sid = {}
    for _, r in gaia_meta_df.iterrows():
        meta_by_sid[int(r["source_id"])] = r.to_dict()

    out = {}
    duplicate_coordinate_matches = 0

    n = len(matched["source_id"])
    for j in range(n):
        k = (float(matched["det_ra"][j]), float(matched["det_dec"][j]))
        idxs = coordinate_to_indices.get(k, [])

        if len(idxs) != 1:
            duplicate_coordinate_matches += 1
            continue

        i = idxs[0]
        sid = int(matched["source_id"][j])
        sep = spherical_sep_arcsec(
            matched["det_ra"][j],
            matched["det_dec"][j],
            matched["gaia_ra"][j],
            matched["gaia_dec"][j],
        )

        out[i] = {
            "source_id": sid,
            "gaia_epoch_ra_deg": float(matched["gaia_ra"][j]),
            "gaia_epoch_dec_deg": float(matched["gaia_dec"][j]),
            "separation_arcsec": sep,
            "source_meta": meta_by_sid.get(sid, {}),
        }

    return out, duplicate_coordinate_matches


def build_incomplete_context(reg, incomplete):
    if len(incomplete) == 0:
        return None

    ra = pd.to_numeric(incomplete["ra"], errors="coerce").to_numpy(dtype=float)
    dec = pd.to_numeric(incomplete["dec"], errors="coerce").to_numpy(dtype=float)
    good = np.isfinite(ra) & np.isfinite(dec)
    if not good.any():
        return None

    inc = incomplete.loc[good].reset_index(drop=True)
    vec = reg.unit_vectors(
        pd.to_numeric(inc["ra"], errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(inc["dec"], errors="coerce").to_numpy(dtype=float),
    )
    return inc, cKDTree(vec)


def incomplete_nearest(reg, ctx, ra, dec):
    if ctx is None:
        return {
            "present": False,
            "source_id": "",
            "static_catalog_sep_arcsec": "",
            "ref_epoch": "",
        }

    inc, tree = ctx
    v = reg.unit_vectors(np.array([ra]), np.array([dec]))[0]
    dist, idx = tree.query(
        v, k=1, distance_upper_bound=chord_radius_arcsec(ACQUISITION_ARCSEC)
    )

    if idx >= len(inc) or not math.isfinite(float(dist)):
        return {
            "present": False,
            "source_id": "",
            "static_catalog_sep_arcsec": "",
            "ref_epoch": "",
        }

    r = inc.iloc[int(idx)]
    sep = spherical_sep_arcsec(ra, dec, float(r["ra"]), float(r["dec"]))
    return {
        "present": True,
        "source_id": int(r["source_id"]),
        "static_catalog_sep_arcsec": sep,
        "ref_epoch": r.get("ref_epoch", ""),
    }


def endpoint_assoc(det_index, assoc_map):
    a = assoc_map.get(det_index)
    if a is None:
        return {
            "source_id": "",
            "gaia_epoch_ra_deg": "",
            "gaia_epoch_dec_deg": "",
            "separation_arcsec": "",
            "strict": False,
            "diagnostic": False,
            "meta": {},
        }

    sep = float(a["separation_arcsec"])
    return {
        "source_id": int(a["source_id"]),
        "gaia_epoch_ra_deg": a["gaia_epoch_ra_deg"],
        "gaia_epoch_dec_deg": a["gaia_epoch_dec_deg"],
        "separation_arcsec": sep,
        "strict": sep <= STRICT_ARCSEC,
        "diagnostic": sep <= DIAGNOSTIC_ARCSEC,
        "meta": a["source_meta"],
    }


def triage_class(a, b, inc_a, inc_b):
    usable_a = bool(a["diagnostic"])
    usable_b = bool(b["diagnostic"])

    if usable_a and usable_b:
        if int(a["source_id"]) == int(b["source_id"]):
            if a["strict"] and b["strict"]:
                return "SAME_GAIA_STRICT_BOTH_ENDPOINTS"
            return "SAME_GAIA_DIAGNOSTIC_ONLY"
        return "DIFFERENT_GAIA_SOURCES"

    # A nearby Gaia row lacking usable proper motion is contextual ambiguity only.
    # It can prevent a clean one/no-Gaia label but can never create source identity.
    unresolved_pm = (
        (not usable_a and inc_a["present"])
        or (not usable_b and inc_b["present"])
    )
    if unresolved_pm:
        return "GAIA_ASSOCIATION_AMBIGUOUS_OR_PM_INCOMPLETE"

    if usable_a ^ usable_b:
        return "ONE_ENDPOINT_GAIA_ONLY"

    return "NO_GAIA_WITHIN_5_ARCSEC"


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main():
    print("=" * 132)
    print("PAIR 17 — EPOCH-AWARE GAIA STATIC-SOURCE TRIAGE v075")
    print("=" * 132)
    print("Prospective contract: FROZEN")
    print("Network:              DISALLOWED")
    print("Detector rerun:       NO")
    print("Registration rerun:   NO")
    print("Disposition changes:  NONE")
    print()

    block_network()

    for p, expected in EXPECTED_SHA.items():
        if not p.is_file():
            fail(f"Missing frozen input: {p}")
        actual = sha256(p)
        if actual.lower() != expected.lower():
            fail(
                f"Frozen SHA mismatch:\n  {p}\n"
                f"  expected {expected}\n  actual   {actual}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    contract = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    if contract.get("contract_id") != "pair17_epoch_aware_gaia_static_triage_v075":
        fail("Wrong v075 contract id")

    corrected_rows, primary_identity = load_pair_membership()
    print()
    print("Frozen pair-17 population reproduced:")
    print("  PRIMARY registered:         1,618")
    print("  PRIMARY corrected <=3:        603")
    print("  PRIMARY LOO robust <=3:        424")
    print("  diagnostic corrected set:      179")

    reg = load_module(V068A_SCRIPT, "wide_census_v068a_frozen")

    # Resolve Gaia pair source domain.
    idx64 = reg.build_leaf_index(V064 / "cache" / "ordinary", compressed=False)
    idx66 = reg.build_leaf_index(V066 / "cache" / "ordinary", compressed=True)

    cells_df = pd.read_csv(PAIR_CELLS)
    valid_keys = set(idx64) | set(idx66)
    keys, key_meta = infer_pair_cell_keys(cells_df, valid_keys)

    pair_rows_df = cells_df[
        pd.to_numeric(cells_df["pair_index"], errors="coerce") == PAIR_INDEX
    ]
    records = pair_rows_df.to_dict("records")

    gaia_df, gaia_load_meta, loader_mode = call_official_pair_loader(
        reg, keys, records, idx64, idx66
    )

    if len(gaia_df) == 0:
        fail("Frozen v068a pair loader returned zero Gaia rows")

    print()
    print("Gaia pair domain:")
    print(f"  inferred cell-key columns: {key_meta['column_x']} / {key_meta['column_y']}")
    print(f"  unique ordinary cells:     {len(keys):,}")
    print(f"  v068a loader input mode:    {loader_mode}")
    print(f"  finite-motion Gaia rows:    {len(gaia_df):,}")

    official_ids = set(int(x) for x in gaia_df["source_id"].tolist())
    transport_paths = gaia_transport_files_for_keys(
        reg, keys, idx64, idx66, official_ids
    )
    raw_gaia, incomplete_gaia, gaia_manifest = load_raw_gaia_context(
        reg, transport_paths
    )

    # Prove the custom transport resolution contains every source used by the
    # frozen official loader. We do not replace official finite rows with it.
    raw_ids = set(int(x) for x in raw_gaia["source_id"].tolist())
    if not official_ids.issubset(raw_ids):
        fail("Resolved transport set does not contain every official v068a source_id")

    print(f"  resolved Gaia transport files: {len(transport_paths):,}")
    print(f"  deduplicated raw Gaia rows:     {len(raw_gaia):,}")
    print(f"  PM-incomplete finite-position:  {len(incomplete_gaia):,}")

    gaia_prop = reg.propagate_gaia(gaia_df, EPOCH_ISO)

    # Load exact frozen detector populations.
    det_a, ids_a, manifest_a = load_endpoint_candidates(ENDPOINT_A)
    det_b, ids_b, manifest_b = load_endpoint_candidates(ENDPOINT_B)

    assoc_a, duplicate_match_a = full_reciprocal_associations(
        reg, det_a, gaia_prop, gaia_df
    )
    assoc_b, duplicate_match_b = full_reciprocal_associations(
        reg, det_b, gaia_prop, gaia_df
    )

    incomplete_ctx = build_incomplete_context(reg, incomplete_gaia)

    print()
    print("Full frozen detector populations:")
    print(f"  A {ENDPOINT_A}: {len(det_a):,} candidates")
    print(f"  B {ENDPOINT_B}: {len(det_b):,} candidates")
    print(f"  reciprocal Gaia matches A/B: {len(assoc_a):,} / {len(assoc_b):,}")
    print(
        f"  exact-coordinate identity ambiguities A/B: "
        f"{duplicate_match_a} / {duplicate_match_b}"
    )

    # If reciprocal_match returned a duplicated detector coordinate, the match is
    # intentionally omitted from candidate identity rather than guessed.
    results = []

    standard_measurements = (
        "x", "y", "x_global", "y_global",
        "ra_deg", "dec_deg", "snr", "signal", "polarity",
        "noise", "local_sigma", "threshold",
    )

    for ordinal, r in enumerate(corrected_rows, 1):
        ka = (str(r["a_tile_id"]), int(r["a_candidate_index"]))
        kb = (str(r["b_tile_id"]), int(r["b_candidate_index"]))

        if ka not in ids_a:
            fail(f"Missing frozen A detector identity: {ka}")
        if kb not in ids_b:
            fail(f"Missing frozen B detector identity: {kb}")

        ia = ids_a[ka]
        ib = ids_b[kb]

        da = det_a.iloc[ia].to_dict()
        db = det_b.iloc[ib].to_dict()

        aa = endpoint_assoc(ia, assoc_a)
        ab = endpoint_assoc(ib, assoc_b)

        inc_a = incomplete_nearest(
            reg, incomplete_ctx, float(da["ra_deg"]), float(da["dec_deg"])
        )
        inc_b = incomplete_nearest(
            reg, incomplete_ctx, float(db["ra_deg"]), float(db["dec_deg"])
        )

        cls = triage_class(aa, ab, inc_a, inc_b)
        pop = primary_identity.get(id(r), "DIAGNOSTIC_179")

        row = {
            "v075_ordinal": ordinal,
            "pair_index": PAIR_INDEX,
            "population": pop,
            "raw_match_row": r["raw_match_row"],
            "raw_separation_arcsec": r["raw_separation_arcsec"],
            "corrected_separation_arcsec": r["corrected_separation_arcsec"],
            "loo_corrected_sep_min_arcsec": r["loo_corrected_sep_min_arcsec"],
            "loo_corrected_sep_max_arcsec": r["loo_corrected_sep_max_arcsec"],
            "window_arcmin": r["window_arcmin"],
            "common_same_gaia_refs": r["common_same_gaia_refs"],
            "triage_class": cls,

            "a_endpoint": ENDPOINT_A,
            "a_tile_id": r["a_tile_id"],
            "a_candidate_index": r["a_candidate_index"],
            "a_gaia_source_id": aa["source_id"],
            "a_gaia_epoch_ra_deg": aa["gaia_epoch_ra_deg"],
            "a_gaia_epoch_dec_deg": aa["gaia_epoch_dec_deg"],
            "a_gaia_separation_arcsec": aa["separation_arcsec"],
            "a_gaia_strict_le3": aa["strict"],
            "a_gaia_diagnostic_le5": aa["diagnostic"],
            "a_pm_incomplete_static_neighbor_within15": inc_a["present"],
            "a_pm_incomplete_source_id": inc_a["source_id"],
            "a_pm_incomplete_static_catalog_sep_arcsec":
                inc_a["static_catalog_sep_arcsec"],
            "a_pm_incomplete_ref_epoch": inc_a["ref_epoch"],

            "b_endpoint": ENDPOINT_B,
            "b_tile_id": r["b_tile_id"],
            "b_candidate_index": r["b_candidate_index"],
            "b_gaia_source_id": ab["source_id"],
            "b_gaia_epoch_ra_deg": ab["gaia_epoch_ra_deg"],
            "b_gaia_epoch_dec_deg": ab["gaia_epoch_dec_deg"],
            "b_gaia_separation_arcsec": ab["separation_arcsec"],
            "b_gaia_strict_le3": ab["strict"],
            "b_gaia_diagnostic_le5": ab["diagnostic"],
            "b_pm_incomplete_static_neighbor_within15": inc_b["present"],
            "b_pm_incomplete_source_id": inc_b["source_id"],
            "b_pm_incomplete_static_catalog_sep_arcsec":
                inc_b["static_catalog_sep_arcsec"],
            "b_pm_incomplete_ref_epoch": inc_b["ref_epoch"],

            "same_gaia_source_id": (
                bool(aa["source_id"]) and bool(ab["source_id"])
                and int(aa["source_id"]) == int(ab["source_id"])
            ),
            "candidate_disposition_changed": False,
        }

        # Preserve useful frozen detector measurements without assuming every
        # v056 schema variant has every optional field.
        for c in standard_measurements:
            row[f"a_{c}"] = da.get(c, "")
            row[f"b_{c}"] = db.get(c, "")

        # Gaia metadata, including parallax if present in frozen transport schema.
        for prefix, a in (("a", aa), ("b", ab)):
            m = a["meta"]
            for c in ("ra", "dec", "ref_epoch", "pmra", "pmdec", "parallax"):
                row[f"{prefix}_gaia_catalog_{c}"] = m.get(c, "")

        results.append(row)

    if len(results) != 603:
        fail(f"v075 result row count is not 603: {len(results)}")

    primary_rows = [r for r in results if r["population"] == "PRIMARY_424"]
    diagnostic_rows = [r for r in results if r["population"] == "DIAGNOSTIC_179"]

    if len(primary_rows) != 424 or len(diagnostic_rows) != 179:
        fail(
            f"Population partition changed after execution: "
            f"{len(primary_rows)} / {len(diagnostic_rows)}"
        )

    def class_counts(rows):
        return dict(sorted(Counter(r["triage_class"] for r in rows).items()))

    # PM-incomplete rows are preserved as catalogue context and never promoted
    # into an epoch-aware identity assertion.
    pm_rows = []
    for _, r in incomplete_gaia.iterrows():
        pm_rows.append({
            "source_id": r.get("source_id", ""),
            "ra_catalog_deg": r.get("ra", ""),
            "dec_catalog_deg": r.get("dec", ""),
            "ref_epoch": r.get("ref_epoch", ""),
            "pmra": r.get("pmra", ""),
            "pmdec": r.get("pmdec", ""),
            "parallax": r.get("parallax", ""),
            "interpretation":
                "PM_INCOMPLETE_CATALOGUE_CONTEXT_ONLY_NOT_EPOCH_PROPAGATED",
        })

    input_manifest = manifest_a + manifest_b + gaia_manifest
    input_manifest.append({
        "kind": "pair_cells_csv",
        "endpoint": "",
        "path": str(PAIR_CELLS.relative_to(ROOT)).replace("\\", "/"),
        "size_bytes": PAIR_CELLS.stat().st_size,
        "sha256": sha256(PAIR_CELLS),
    })

    row_fields = list(results[0].keys())
    write_csv_atomic(OUT_ROWS, results, row_fields)

    pm_fields = [
        "source_id", "ra_catalog_deg", "dec_catalog_deg", "ref_epoch",
        "pmra", "pmdec", "parallax", "interpretation",
    ]
    write_csv_atomic(OUT_PM, pm_rows, pm_fields)

    manifest_fields = ["kind", "endpoint", "path", "size_bytes", "sha256"]
    write_csv_atomic(OUT_INPUTS, input_manifest, manifest_fields)

    summary = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_epoch_aware_gaia_static_triage_v075",
        "contract_sha256": EXPECTED_SHA[CONTRACT],
        "pair_index": PAIR_INDEX,
        "canonical_pair": "APPLAUSE:132654 | APPLAUSE:14120",
        "epoch_utc": EPOCH_ISO,
        "physical_exposure_overlap_s": 299.0,
        "frozen_population": {
            "primary_registered": 1618,
            "primary_corrected_le3": 603,
            "primary_loo_robust_le3": 424,
            "diagnostic_corrected_not_loo": 179,
        },
        "gaia": {
            "catalogue": "Gaia DR3",
            "official_v068a_finite_motion_rows": len(gaia_df),
            "resolved_transport_files": len(transport_paths),
            "deduplicated_raw_transport_rows": len(raw_gaia),
            "pm_incomplete_finite_position_rows": len(incomplete_gaia),
            "cell_key_inference": key_meta,
            "official_loader_input_mode": loader_mode,
            "official_loader_metadata": gaia_load_meta,
        },
        "detector": {
            "endpoint_a_candidates": len(det_a),
            "endpoint_b_candidates": len(det_b),
            "endpoint_a_reciprocal_gaia_matches": len(assoc_a),
            "endpoint_b_reciprocal_gaia_matches": len(assoc_b),
            "endpoint_a_duplicate_coordinate_match_ambiguities":
                duplicate_match_a,
            "endpoint_b_duplicate_coordinate_match_ambiguities":
                duplicate_match_b,
        },
        "triage_counts": {
            "primary_424": class_counts(primary_rows),
            "diagnostic_179": class_counts(diagnostic_rows),
            "all_603": class_counts(results),
        },
        "interpretation_boundaries": {
            "catalogue_absence_is_transience": False,
            "catalogue_association_alone_closes_pair": False,
            "v075_changes_candidate_dispositions": False,
            "strict_same_gaia_both_endpoints":
                "strong persistent-source support requiring downstream state handling under the frozen policy; v075 itself does not close",
            "unexplained_primary_survivors":
                "proceed to separately frozen morphology context and sensitivity-qualified recurrence/injection-recovery",
        },
        "guards": {
            "network_access": False,
            "detector_rerun": False,
            "astrometric_registration_rerun": False,
            "candidate_disposition_changes": False,
            "threshold_retuning": False,
            "manual_review": False,
        },
        "outputs": {
            "triage_csv": str(OUT_ROWS.relative_to(ROOT)).replace("\\", "/"),
            "pm_incomplete_context_csv":
                str(OUT_PM.relative_to(ROOT)).replace("\\", "/"),
            "input_manifest_csv":
                str(OUT_INPUTS.relative_to(ROOT)).replace("\\", "/"),
        },
    }

    write_json_atomic(OUT_SUMMARY, summary)

    print()
    print("=" * 132)
    print("v075 STATIC-SOURCE TRIAGE COMPLETE")
    print("=" * 132)
    print("PRIMARY 424 triage:")
    for k, v in class_counts(primary_rows).items():
        print(f"  {k}: {v}")
    print()
    print("DIAGNOSTIC 179 triage:")
    for k, v in class_counts(diagnostic_rows).items():
        print(f"  {k}: {v}")
    print()
    print("Catalogue absence interpreted as transience: NO")
    print("Catalogue association changed disposition:   NO")
    print("Network calls:                               0")
    print("Detector reruns:                             0")
    print("Registrations rerun:                         0")
    print("Candidate dispositions changed:              NONE")
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
