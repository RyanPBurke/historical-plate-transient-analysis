#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import defaultdict, Counter, OrderedDict
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import re
import shutil

import numpy as np
from astropy.table import Table
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "applause_dr4_tierA_busko_source_census_zero_source_continuation_contract_v094c.json"
)
EXPECTED_CONTRACT_SHA = "a1565dcae73c886441c901d99386dcf07d5c29dbd6307c9c7ea98964f5e7bec7"

V094B_CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "applause_dr4_tierA_busko_source_census_storage_amendment_v094b.json"
)
EXPECTED_V094B_CONTRACT_SHA = "d277b2ca4ca85f5c225989c9bb0694a1b0a9fc70749f41e5b08b13ac9989009b"

V094B_RUNNER = ROOT / "tools" / "run_applause_dr4_tierA_busko_source_census_v094b.py"
EXPECTED_V094B_RUNNER_SHA = "67d2b6a27d168e9b4653375288b0f0e8b47644721365e46b2aa21c56119860b7"

PARENT = ROOT / "results" / "applause_dr4_site_coordinate_semantics_repair_v093e"
PARENT_BANK = PARENT / "applause_dr4_v093e_bank_manifest.json"
EXPECTED_PARENT_BANK_SHA = "1889b93e4f104bd025ce221cb7435cfe53041e6f702835ac603e5da6a8ac2139"
OPP = PARENT / "applause_dr4_site_coordinate_repaired_opportunities_v093e.csv"
COMP = PARENT / "applause_dr4_site_coordinate_repaired_comparisons_v093e.csv"

V093_CACHE = (
    ROOT / "work"
    / "applause_dr4_busko_first_cross_observatory_opportunity_census_v093"
    / "tap_cache"
)
SCAN_CACHE = V093_CACHE / "scan.csv"
SOLUTION_CACHE = V093_CACHE / "solution.csv"

V094B_WORK = ROOT / "work" / "applause_dr4_tierA_busko_source_census_v094b"
V094B_NPZ = V094B_WORK / "source_scan_minimal_npz"
V094B_STATE = V094B_WORK / "state"
V094B_ACQ = V094B_STATE / "source_acquisition_manifest_v094b.json"
V094B_SALVAGE = V094B_STATE / "v094a_salvage_manifest_v094b.json"
V094B_SELECTION = V094B_STATE / "selection_snapshot_v094b.json"

WORK = ROOT / "work" / "applause_dr4_tierA_busko_source_census_v094c"
STATE = WORK / "state"
RESULT = ROOT / "results" / "applause_dr4_tierA_busko_source_census_v094c"

EXPECTED_ZERO = [109445, 114677, 114682, 114813, 115031, 115911, 116377, 116528, 117980]

BUSKO_R_ARCSEC = 5.0
CONFIRM_PRIMARY_ARCSEC = 3.0
CONFIRM_DIAG_ARCSEC = 5.0
MIN_SITE_KM = 100.0
SPUTNIK = datetime(1957, 10, 4, 19, 28, 34, tzinfo=timezone.utc)
PLATE_CACHE_MAX = 8
MATCH_CHUNK = 100000
MIN_FREE_GB = 10.0


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def log(s=""):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}", flush=True)


def rows(p):
    with Path(p).open("r", encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def fnum(v):
    try:
        x = float(str(v or "").strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x = fnum(v)
    return None if x is None else int(round(x))


def bval(v):
    return str(v or "").strip().lower() in {"1", "true", "yes"}


def parse_dt(v):
    s = str(v or "").strip().replace("Z", "+00:00")
    if not s:
        return None
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def wjson(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)


def load_table_any(path):
    with Path(path).open("rb") as f:
        head = f.read(512).lstrip()
    if head.startswith(b"<?xml") or b"<VOTABLE" in head.upper():
        return Table.read(path, format="votable")
    return Table.read(path, format="ascii.csv")


def parse_stc(v):
    nums = [
        float(x)
        for x in re.findall(
            r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',
            str(v or "")
        )
    ]
    if len(nums) < 8:
        return None
    nums = nums[-8:]
    p = [(nums[i] % 360.0, nums[i + 1]) for i in range(0, 8, 2)]
    if any(not (-90 <= d <= 90) for _, d in p):
        return None
    return p


def xyz(ra, dec):
    ra = np.deg2rad(np.asarray(ra, dtype=float))
    dec = np.deg2rad(np.asarray(dec, dtype=float))
    c = np.cos(dec)
    return np.column_stack((c * np.cos(ra), c * np.sin(ra), np.sin(dec)))


def chord(arcsec):
    a = math.radians(arcsec / 3600.0)
    return 2 * math.sin(a / 2)


def arcsec_from_chord_array(d):
    d = np.clip(np.asarray(d, dtype=float), 0.0, 2.0)
    return np.degrees(2 * np.arcsin(d / 2.0)) * 3600.0


def free_gb():
    return shutil.disk_usage(ROOT).free / (1024 ** 3)


def minimal_npz_path(sid):
    return V094B_NPZ / f"scan_{int(sid)}.npz"


def empty_npz_ok(p):
    try:
        z = np.load(p, allow_pickle=False)
        return len(z["source_id"]) == 0 and len(z["ra"]) == 0 and len(z["dec"]) == 0
    except Exception:
        return False


def write_empty_npz(sid):
    p = minimal_npz_path(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".npz.tmp")
    with tmp.open("wb") as f:
        np.savez_compressed(
            f,
            source_id=np.asarray([], dtype=np.int64),
            ra=np.asarray([], dtype=np.float64),
            dec=np.asarray([], dtype=np.float64),
        )
    tmp.replace(p)
    if not empty_npz_ok(p):
        raise RuntimeError(f"Empty-NPZ verification failed for scan {sid}")
    return p


def audit_zero_rows(zero_ids):
    if not V094B_ACQ.is_file():
        raise RuntimeError("Missing v094b acquisition manifest")
    acq = json.loads(V094B_ACQ.read_text(encoding="utf-8"))
    if acq.get("status") != "COMPLETE":
        raise RuntimeError(f"v094b acquisition manifest is not COMPLETE: {acq.get('status')}")

    evidence = {}

    for rec in acq.get("completed_batches", []):
        if rec.get("status") != "COMPLETE":
            continue
        requested = {int(x) for x in rec.get("scan_ids", [])}
        written = {int(x) for x in rec.get("minimal_scan_products", {}).keys()}
        for sid in zero_ids:
            if sid in requested and sid not in written:
                evidence[sid] = {
                    "source": "v094b_completed_minimal_batch",
                    "batch_scan_ids": sorted(requested),
                    "batch_rows": rec.get("rows"),
                    "raw_sha256": rec.get("raw_sha256"),
                    "status": "CONFIRMED_ZERO_ROWS_IN_COMPLETE_RESPONSE",
                }

    if V094B_SALVAGE.is_file():
        salvage = json.loads(V094B_SALVAGE.read_text(encoding="utf-8"))
        for rec in salvage.get("files", []):
            if rec.get("error"):
                continue
            path = str(rec.get("path") or "")
            m = re.search(r"batch_\d+_([0-9_]+)\.vot$", path)
            if not m:
                continue
            requested = {int(x) for x in m.group(1).split("_") if x}
            written = {int(x) for x in rec.get("written_needed_scans", {}).keys()}
            for sid in zero_ids:
                if sid in requested and sid not in written:
                    evidence[sid] = {
                        "source": "v094a_salvaged_complete_votable",
                        "batch_scan_ids": sorted(requested),
                        "batch_rows": rec.get("votable_rows"),
                        "raw_sha256": rec.get("raw_sha256"),
                        "status": "CONFIRMED_ZERO_ROWS_IN_COMPLETE_RESPONSE",
                    }

    unconfirmed = sorted(set(zero_ids) - set(evidence))
    if unconfirmed:
        raise RuntimeError(
            f"PROVENANCE HOLD: zero-row classification not confirmed for scans {unconfirmed}"
        )

    return evidence, acq


def load_scan(sid):
    p = minimal_npz_path(sid)
    if not p.is_file():
        return None
    z = np.load(p, allow_pickle=False)
    ok = np.isfinite(z["ra"]) & np.isfinite(z["dec"])
    return {
        "source_id": np.asarray(z["source_id"][ok], dtype=np.int64),
        "ra": np.asarray(z["ra"][ok], dtype=np.float64),
        "dec": np.asarray(z["dec"][ok], dtype=np.float64),
    }


def unwrap_ra(values, ref):
    a = np.asarray(values, dtype=float).copy()
    a[a - ref > 180.0] -= 360.0
    a[a - ref < -180.0] += 360.0
    return a


def inside_poly_batch(ra, dec, poly):
    ra = np.asarray(ra, dtype=float)
    dec = np.asarray(dec, dtype=float)
    if len(ra) == 0:
        return np.zeros(0, dtype=bool)

    pra = np.asarray([p[0] for p in poly], dtype=float)
    pdec = np.asarray([p[1] for p in poly], dtype=float)
    ref = float(pra[0])
    px = unwrap_ra(pra, ref)
    x = unwrap_ra(ra, ref)
    y = dec

    inside = np.zeros(len(x), dtype=bool)
    j = len(px) - 1
    for i in range(len(px)):
        yi = pdec[i]
        yj = pdec[j]
        cross = ((yi > y) != (yj > y))
        denom = (yj - yi)
        if abs(denom) > 0:
            xcross = (px[j] - px[i]) * (y - yi) / denom + px[i]
            inside ^= cross & (x < xcross)
        j = i
    return inside


def coverage_count_batch(ra, dec, scan_ids, scan_polys):
    out = np.zeros(len(ra), dtype=np.int16)
    for sid in scan_ids:
        one = np.zeros(len(ra), dtype=bool)
        for poly in scan_polys.get(sid, []):
            one |= inside_poly_batch(ra, dec, poly)
        out += one.astype(np.int16)
    return out


def build_plate_data(scan_ids):
    scan_ids = list(map(int, scan_ids))
    loaded = []
    for sid in scan_ids:
        z = load_scan(sid)
        if z is None:
            return {"usable": False, "reason": "MISSING_CACHE", "scan_ids": scan_ids}
        if len(z["ra"]) == 0:
            return {"usable": False, "reason": "ZERO_SOURCE_ROWS", "scan_ids": scan_ids}
        loaded.append((sid, z))

    if len(loaded) not in (1, 2):
        raise RuntimeError(
            f"PROVENANCE HOLD: unexpected scan multiplicity {len(loaded)} for scans {scan_ids}"
        )

    all_ra = np.concatenate([z["ra"] for _, z in loaded])
    all_dec = np.concatenate([z["dec"] for _, z in loaded])
    all_tree = cKDTree(xyz(all_ra, all_dec))

    if len(loaded) == 1:
        sid, z = loaded[0]
        n = len(z["ra"])
        return {
            "usable": True,
            "support_class": "SINGLE_SCAN",
            "support_count": 1,
            "scan_ids": [sid],
            "rep_ra": z["ra"],
            "rep_dec": z["dec"],
            "rep_source1": z["source_id"],
            "rep_source2": np.full(n, -1, dtype=np.int64),
            "all_tree": all_tree,
        }

    (sid1, z1), (sid2, z2) = loaded
    x1 = xyz(z1["ra"], z1["dec"])
    x2 = xyz(z2["ra"], z2["dec"])
    t1 = cKDTree(x1)
    t2 = cKDTree(x2)

    d12, k12 = t2.query(x1, k=1, distance_upper_bound=chord(BUSKO_R_ARCSEC))
    d21, k21 = t1.query(x2, k=1, distance_upper_bound=chord(BUSKO_R_ARCSEC))

    i1 = np.arange(len(x1), dtype=np.int64)
    finite = np.isfinite(d12) & (k12 < len(x2))
    mutual = np.zeros(len(x1), dtype=bool)
    valid_i = i1[finite]
    valid_j = k12[finite].astype(np.int64)
    mutual[valid_i] = (
        np.isfinite(d21[valid_j])
        & (k21[valid_j].astype(np.int64) == valid_i)
    )

    ii = np.flatnonzero(mutual)
    jj = k12[ii].astype(np.int64)

    if len(ii) == 0:
        return {
            "usable": True,
            "support_class": "MULTISCAN_CONFIRMED",
            "support_count": 2,
            "scan_ids": [sid1, sid2],
            "rep_ra": np.asarray([], dtype=np.float64),
            "rep_dec": np.asarray([], dtype=np.float64),
            "rep_source1": np.asarray([], dtype=np.int64),
            "rep_source2": np.asarray([], dtype=np.int64),
            "all_tree": all_tree,
        }

    vv = x1[ii] + x2[jj]
    norms = np.linalg.norm(vv, axis=1)
    good = norms > 0
    vv = vv[good] / norms[good][:, None]
    ii = ii[good]
    jj = jj[good]

    rep_dec = np.degrees(np.arcsin(vv[:, 2]))
    rep_ra = np.degrees(np.arctan2(vv[:, 1], vv[:, 0])) % 360.0

    return {
        "usable": True,
        "support_class": "MULTISCAN_CONFIRMED",
        "support_count": 2,
        "scan_ids": [sid1, sid2],
        "rep_ra": rep_ra.astype(np.float64),
        "rep_dec": rep_dec.astype(np.float64),
        "rep_source1": z1["source_id"][ii],
        "rep_source2": z2["source_id"][jj],
        "all_tree": all_tree,
    }


class PlateLRU:
    def __init__(self, maxsize=PLATE_CACHE_MAX):
        self.maxsize = int(maxsize)
        self.cache = OrderedDict()

    def get(self, plate_id, scan_ids):
        key = (int(plate_id), tuple(map(int, scan_ids)))
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value

        value = build_plate_data(scan_ids)
        self.cache[key] = value

        while len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

        return value


def source_id_text(s1, s2):
    if int(s2) < 0:
        return str(int(s1))
    return f"{int(s1)};{int(s2)}"


def main():
    log("=" * 110)
    log("APPLAUSE DR4 — ZERO-ROW REPAIR + TIER-A SOURCE MATCHING v094c")
    log("=" * 110)
    log("No network queries; no pixels; no external catalogues; no quality thresholding.")
    log("Catalogue absence remains triage only, not a qualified negative.")
    log("")

    if sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v094c contract SHA mismatch")
    if sha(V094B_CONTRACT) != EXPECTED_V094B_CONTRACT_SHA:
        raise RuntimeError("v094b contract SHA mismatch")
    if sha(V094B_RUNNER) != EXPECTED_V094B_RUNNER_SHA:
        raise RuntimeError("v094b runner SHA mismatch")
    if sha(PARENT_BANK) != EXPECTED_PARENT_BANK_SHA:
        raise RuntimeError("v093e parent bank SHA mismatch")

    sel = json.loads(V094B_SELECTION.read_text(encoding="utf-8"))
    needed = set(map(int, sel.get("needed_scan_ids", [])))
    if (
        sel.get("controls") != 784
        or sel.get("triplets") != 784
        or sel.get("eligible") != 784
        or len(needed) != 1073
    ):
        raise RuntimeError("v094b selection snapshot differs from frozen population")

    unexpected_missing = sorted(
        sid for sid in needed
        if not minimal_npz_path(sid).is_file() and sid not in EXPECTED_ZERO
    )
    if unexpected_missing:
        raise RuntimeError(
            f"PROVENANCE HOLD: unexpected missing scan caches: {unexpected_missing}"
        )

    for sid in EXPECTED_ZERO:
        p = minimal_npz_path(sid)
        if p.is_file() and not empty_npz_ok(p):
            raise RuntimeError(
                f"PROVENANCE HOLD: expected zero-row scan {sid} has a non-empty cache"
            )

    evidence, acq = audit_zero_rows(set(EXPECTED_ZERO))
    STATE.mkdir(parents=True, exist_ok=True)
    audit_path = STATE / "zero_source_audit_v094c.json"
    wjson(audit_path, {
        "status": "COMPLETE",
        "confirmed_zero_source_scan_ids": EXPECTED_ZERO,
        "evidence": {str(k): v for k, v in sorted(evidence.items())},
        "v094b_acquisition_manifest_sha256": sha(V094B_ACQ),
        "v094b_salvage_manifest_sha256": (
            sha(V094B_SALVAGE) if V094B_SALVAGE.is_file() else None
        ),
    })

    for sid in EXPECTED_ZERO:
        p = minimal_npz_path(sid)
        if not p.is_file():
            p = write_empty_npz(sid)
        log(f"Confirmed zero-row scan {sid}: explicit empty cache sha={sha(p)[:16]}...")

    remaining_missing = sorted(
        sid for sid in needed if not minimal_npz_path(sid).is_file()
    )
    if remaining_missing:
        raise RuntimeError(
            f"PROVENANCE HOLD: caches still missing after zero-row repair: {remaining_missing}"
        )

    parent_bank = json.loads(PARENT_BANK.read_text(encoding="utf-8"))
    ph = {x["name"]: x["sha256"] for x in parent_bank.get("files", [])}
    for p in (OPP, COMP):
        if ph.get(p.name) != sha(p):
            raise RuntimeError(f"Parent input SHA mismatch: {p.name}")

    opp = {r["canonical_pair"]: r for r in rows(OPP)}
    controls = []
    holds = Counter()

    for c in rows(COMP):
        if c.get("tier") != "A_LE30MIN":
            continue
        if not bval(c.get("primary_common_coverage_ge50pct")):
            continue
        if not bval(c.get("same_site_control")):
            continue

        o = opp.get(c["canonical_pair"])
        if o is None:
            continue

        sep = fnum(o.get("corrected_site_separation_km"))
        if sep is None or sep < MIN_SITE_KM:
            holds["site_lt100km_or_missing"] += 1
            continue

        ep = c.get("comparison_for_endpoint")
        if ep == "A":
            p_plate, q_plate = inum(o.get("plate_a")), inum(o.get("plate_b"))
            p_exp, q_exp = inum(o.get("exposure_a")), inum(o.get("exposure_b"))
            p_num, q_num = inum(o.get("plate_numexp_a")), inum(o.get("plate_numexp_b"))
        elif ep == "B":
            p_plate, q_plate = inum(o.get("plate_b")), inum(o.get("plate_a"))
            p_exp, q_exp = inum(o.get("exposure_b")), inum(o.get("exposure_a"))
            p_num, q_num = inum(o.get("plate_numexp_b")), inum(o.get("plate_numexp_a"))
        else:
            holds["bad_endpoint_label"] += 1
            continue

        c_plate = inum(c.get("comparison_plate_id"))
        c_exp = inum(c.get("comparison_exposure_id"))
        c_num = inum(c.get("comparison_plate_numexp"))

        if None in (p_plate, q_plate, c_plate, p_exp, q_exp, c_exp):
            holds["identity_missing"] += 1
            continue

        if not (p_num == 1 and q_num == 1 and c_num == 1):
            holds["multi_exposure_triplet"] += 1
            continue

        controls.append({
            "canonical_pair": c["canonical_pair"],
            "endpoint": ep,
            "positive_plate": p_plate,
            "independent_plate": q_plate,
            "control_plate": c_plate,
            "positive_exposure": p_exp,
            "independent_exposure": q_exp,
            "control_exposure": c_exp,
            "gap_minutes": fnum(c.get("endpoint_interval_gap_minutes")),
            "temporal_relation": c.get("temporal_relation"),
            "site_separation_km": sep,
            "science_overlap_start_utc": o.get("physical_overlap_start_utc"),
            "science_overlap_end_utc": o.get("physical_overlap_end_utc"),
        })

    unique = {}
    for r in controls:
        key = (r["positive_plate"], r["independent_plate"], r["control_plate"])
        if key not in unique or (
            (r["gap_minutes"] or 1e99) < (unique[key]["gap_minutes"] or 1e99)
        ):
            unique[key] = r
    triplets = list(unique.values())

    st = load_table_any(SCAN_CACHE)
    plate_scans = defaultdict(list)
    for r in st:
        try:
            plate_scans[int(r["plate_id"])].append(int(r["scan_id"]))
        except Exception:
            pass
    for pid in list(plate_scans):
        plate_scans[pid] = sorted(set(plate_scans[pid]))

    solt = load_table_any(SOLUTION_CACHE)
    scan_polys = defaultdict(list)
    for r in solt:
        try:
            sid = int(r["scan_id"])
        except Exception:
            continue
        p = parse_stc(r["stc_polygon"])
        if p:
            scan_polys[sid].append(p)

    eligible = []
    reconstructed_needed = set()
    multiplicity = Counter()

    for r in triplets:
        ps = [s for s in plate_scans.get(r["positive_plate"], []) if scan_polys.get(s)]
        qs = [s for s in plate_scans.get(r["independent_plate"], []) if scan_polys.get(s)]
        cs = [s for s in plate_scans.get(r["control_plate"], []) if scan_polys.get(s)]
        multiplicity[f"P{len(ps)}_I{len(qs)}_C{len(cs)}"] += 1

        if min(len(ps), len(qs), len(cs)) < 1:
            continue

        x = dict(r)
        x["positive_scan_ids"] = ps
        x["independent_scan_ids"] = qs
        x["control_scan_ids"] = cs
        eligible.append(x)

        reconstructed_needed.update(ps)
        reconstructed_needed.update(qs)
        reconstructed_needed.update(cs)

    if (
        len(controls) != 784
        or len(triplets) != 784
        or len(eligible) != 784
        or reconstructed_needed != needed
    ):
        raise RuntimeError(
            "PROVENANCE HOLD: v094c reconstructed population differs from frozen v094b population"
        )

    zero_set = set(EXPECTED_ZERO)
    zero_holds = []
    matchable = []

    for ti, r in enumerate(eligible, 1):
        all_scans = (
            set(r["positive_scan_ids"])
            | set(r["independent_scan_ids"])
            | set(r["control_scan_ids"])
        )
        zero_hits = sorted(all_scans & zero_set)
        if zero_hits:
            zero_holds.append({
                "triplet_index": ti,
                "canonical_pair": r["canonical_pair"],
                "zero_source_scan_ids": ";".join(map(str, zero_hits)),
                "positive_plate": r["positive_plate"],
                "independent_plate": r["independent_plate"],
                "control_plate": r["control_plate"],
                "status": "HELD_ZERO_SOURCE_SCAN_NOT_EVIDENCE_OF_ABSENCE",
            })
        else:
            matchable.append((ti, r))

    RESULT.mkdir(parents=True, exist_ok=True)

    hold_path = RESULT / "applause_dr4_tierA_zero_source_triplet_holds_v094c.csv"
    hold_fields = [
        "triplet_index", "canonical_pair", "zero_source_scan_ids",
        "positive_plate", "independent_plate", "control_plate", "status",
    ]
    with hold_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=hold_fields)
        w.writeheader()
        w.writerows(zero_holds)

    log(f"Frozen Tier-A triplets: {len(eligible)}")
    log(f"Triplets held for confirmed zero-row scan provenance: {len(zero_holds)}")
    log(f"Triplets entering mechanical matching: {len(matchable)}")
    log(f"Scan multiplicity classes: {dict(multiplicity)}")
    log(f"Disk free before matching: {free_gb():.2f} GiB")
    log("")

    candidate_path = (
        RESULT / "applause_dr4_tierA_busko_independent_catalogue_candidates_v094c.csv"
    )
    fields = [
        "triplet_index", "canonical_pair", "confirmation_class", "epoch_stratum",
        "science_overlap_start_utc", "science_overlap_end_utc", "site_separation_km",
        "positive_plate", "positive_exposure", "independent_plate", "independent_exposure",
        "control_plate", "control_exposure", "control_relation", "control_gap_minutes",
        "candidate_ra_icrs", "candidate_dec_icrs",
        "positive_scan_support", "positive_scan_support_class", "positive_scan_ids",
        "positive_source_ids", "independent_sep_arcsec",
        "independent_scan_support", "independent_scan_support_class",
        "independent_scan_ids", "independent_source_ids",
        "control_available_scan_count", "control_nearest_catalog_sep_arcsec",
        "positive_scan_coverage_count", "independent_scan_coverage_count",
        "control_scan_coverage_count", "catalogue_absence_is_qualified_negative",
        "candidate_disposition",
    ]

    counters = Counter()
    class_counts = Counter()
    epoch_counts = Counter()
    support_counts = Counter()
    candidate_count = 0
    pcache = PlateLRU()

    with candidate_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for processed, (ti, r) in enumerate(matchable, 1):
            if processed % 25 == 1 and free_gb() < MIN_FREE_GB:
                raise RuntimeError(
                    f"STORAGE HOLD: free disk {free_gb():.2f} GiB below {MIN_FREE_GB:.1f} GiB"
                )

            pdata = pcache.get(r["positive_plate"], r["positive_scan_ids"])
            qdata = pcache.get(r["independent_plate"], r["independent_scan_ids"])
            cdata = pcache.get(r["control_plate"], r["control_scan_ids"])

            if not pdata["usable"] or not qdata["usable"] or not cdata["usable"]:
                counters["triplet_source_data_unusable"] += 1
                continue

            q_ra = qdata["rep_ra"]
            q_dec = qdata["rep_dec"]
            q_tree = cKDTree(xyz(q_ra, q_dec)) if len(q_ra) else None

            p_ra = pdata["rep_ra"]
            p_dec = pdata["rep_dec"]

            for start in range(0, len(p_ra), MATCH_CHUNK):
                end = min(start + MATCH_CHUNK, len(p_ra))
                ra = p_ra[start:end]
                dec = p_dec[start:end]

                covp = coverage_count_batch(ra, dec, pdata["scan_ids"], scan_polys)
                covq = coverage_count_batch(ra, dec, qdata["scan_ids"], scan_polys)
                covc = coverage_count_batch(ra, dec, cdata["scan_ids"], scan_polys)

                covered = (covp >= 1) & (covq >= 1) & (covc >= 1)
                counters["candidate_not_covered_all3"] += int(np.count_nonzero(~covered))
                if not np.any(covered):
                    continue

                local = np.flatnonzero(covered)
                xyz_cov = xyz(ra[local], dec[local])

                d_control, _ = cdata["all_tree"].query(xyz_cov, k=1)
                control_sep = arcsec_from_chord_array(d_control)
                mismatch = control_sep > BUSKO_R_ARCSEC

                counters["control_catalog_match_le5"] += int(np.count_nonzero(~mismatch))
                counters["busko_catalog_mismatch"] += int(np.count_nonzero(mismatch))
                if not np.any(mismatch):
                    continue

                local2 = local[mismatch]
                control_sep2 = control_sep[mismatch]

                if q_tree is None:
                    counters["no_independent_representative_catalog"] += len(local2)
                    continue

                d_q, q_idx = q_tree.query(xyz(ra[local2], dec[local2]), k=1)
                q_sep = arcsec_from_chord_array(d_q)
                confirmed = q_sep <= CONFIRM_DIAG_ARCSEC

                counters["no_independent_match_le5"] += int(np.count_nonzero(~confirmed))
                if not np.any(confirmed):
                    continue

                final_local = local2[confirmed]
                final_csep = control_sep2[confirmed]
                final_qsep = q_sep[confirmed]
                final_qidx = np.asarray(q_idx[confirmed], dtype=np.int64)

                sdt = parse_dt(r["science_overlap_start_utc"])
                epoch = (
                    "PRE_SPUTNIK"
                    if sdt and sdt < SPUTNIK
                    else "POST_SPUTNIK_OR_SAME_LAUNCH_DATE"
                )

                for jj, pi in enumerate(final_local):
                    qi = int(final_qidx[jj])
                    qsep = float(final_qsep[jj])
                    cls = (
                        "PRIMARY_LE3"
                        if qsep <= CONFIRM_PRIMARY_ARCSEC
                        else "DIAGNOSTIC_GT3_LE5"
                    )

                    p_global = start + int(pi)

                    row = {
                        "triplet_index": ti,
                        "canonical_pair": r["canonical_pair"],
                        "confirmation_class": cls,
                        "epoch_stratum": epoch,
                        "science_overlap_start_utc": r["science_overlap_start_utc"],
                        "science_overlap_end_utc": r["science_overlap_end_utc"],
                        "site_separation_km": f"{r['site_separation_km']:.6f}",
                        "positive_plate": r["positive_plate"],
                        "positive_exposure": r["positive_exposure"],
                        "independent_plate": r["independent_plate"],
                        "independent_exposure": r["independent_exposure"],
                        "control_plate": r["control_plate"],
                        "control_exposure": r["control_exposure"],
                        "control_relation": r["temporal_relation"],
                        "control_gap_minutes": f"{r['gap_minutes']:.6f}",
                        "candidate_ra_icrs": f"{float(p_ra[p_global]):.10f}",
                        "candidate_dec_icrs": f"{float(p_dec[p_global]):.10f}",
                        "positive_scan_support": pdata["support_count"],
                        "positive_scan_support_class": pdata["support_class"],
                        "positive_scan_ids": ";".join(map(str, pdata["scan_ids"])),
                        "positive_source_ids": source_id_text(
                            pdata["rep_source1"][p_global],
                            pdata["rep_source2"][p_global],
                        ),
                        "independent_sep_arcsec": f"{qsep:.6f}",
                        "independent_scan_support": qdata["support_count"],
                        "independent_scan_support_class": qdata["support_class"],
                        "independent_scan_ids": ";".join(map(str, qdata["scan_ids"])),
                        "independent_source_ids": source_id_text(
                            qdata["rep_source1"][qi],
                            qdata["rep_source2"][qi],
                        ),
                        "control_available_scan_count": len(cdata["scan_ids"]),
                        "control_nearest_catalog_sep_arcsec": f"{float(final_csep[jj]):.6f}",
                        "positive_scan_coverage_count": int(covp[int(pi)]),
                        "independent_scan_coverage_count": int(covq[int(pi)]),
                        "control_scan_coverage_count": int(covc[int(pi)]),
                        "catalogue_absence_is_qualified_negative": False,
                        "candidate_disposition": "UNADJUDICATED_CATALOGUE_COINCIDENCE",
                    }
                    writer.writerow(row)

                    candidate_count += 1
                    counters[cls] += 1
                    class_counts[cls] += 1
                    epoch_counts[epoch] += 1
                    support_counts[
                        f"{pdata['support_class']}|{qdata['support_class']}"
                    ] += 1

            if processed % 25 == 0:
                f.flush()
                log(
                    f"Mechanical source matching: {processed}/{len(matchable)} matchable triplets, "
                    f"candidate rows={candidate_count}, free={free_gb():.2f} GiB"
                )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_tierA_busko_source_census_v094c",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "parent_v094b_contract_sha256": EXPECTED_V094B_CONTRACT_SHA,
        "parent_v094b_runner_sha256": EXPECTED_V094B_RUNNER_SHA,
        "v094b_acquisition_manifest_sha256": sha(V094B_ACQ),
        "zero_source_audit_sha256": sha(audit_path),
        "confirmed_zero_source_scan_ids": EXPECTED_ZERO,
        "frozen_tierA_triplets": len(eligible),
        "zero_source_held_triplets": len(zero_holds),
        "mechanically_matchable_triplets": len(matchable),
        "mechanical_counter": dict(counters),
        "catalogue_candidate_rows": candidate_count,
        "catalogue_candidate_unique_positions_3arcsec_reporting_only": None,
        "global_3arcsec_deduplication_status": "DEFERRED_MEMORY_BOUNDED_POST_CENSUS_STAGE",
        "confirmation_class_counts": dict(class_counts),
        "scan_support_class_counts": dict(support_counts),
        "epoch_stratum_counts": dict(epoch_counts),
        "catalogue_absence_is_qualified_negative": False,
        "candidate_dispositions_changed": False,
        "candidate_csv_sha256": sha(candidate_path),
        "zero_source_hold_csv_sha256": sha(hold_path),
        "guards": {
            "network_queries": 0,
            "external_catalogue_queries": 0,
            "pixel_downloads": 0,
            "fits_reads": 0,
            "detector_runs": 0,
            "source_quality_thresholds_applied": 0,
            "candidate_disposition_changes": 0,
        },
    }

    report_path = RESULT / "applause_dr4_tierA_busko_source_census_v094c.json"
    wjson(report_path, report)

    bank = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_tierA_busko_source_census_v094c_bank_manifest",
        "report_sha256": sha(report_path),
        "candidate_csv_sha256": sha(candidate_path),
        "zero_source_hold_csv_sha256": sha(hold_path),
        "zero_source_audit_sha256": sha(audit_path),
        "v094b_acquisition_manifest_sha256": sha(V094B_ACQ),
        "minimal_per_scan_cache_reused_from_v094b": True,
        "candidate_dispositions_changed": False,
    }
    bank_path = RESULT / "applause_dr4_v094c_bank_manifest.json"
    wjson(bank_path, bank)

    log("")
    log("=" * 110)
    log("v094c ZERO-ROW REPAIR + TIER-A SOURCE MATCHING COMPLETE")
    log("=" * 110)
    log(f"Confirmed zero-row scans: {len(EXPECTED_ZERO)}")
    log(f"Triplets held for zero-row provenance: {len(zero_holds)}")
    log(f"Triplets mechanically matched: {len(matchable)}")
    log(f"Catalogue candidate rows: {candidate_count}")
    log(f"Confirmation classes: {dict(class_counts)}")
    log(f"Scan-support classes: {dict(support_counts)}")
    log(f"Epoch strata: {dict(epoch_counts)}")
    log("Global <=3\" candidate deduplication: DEFERRED (no candidate rows deleted).")
    log("IMPORTANT: catalogue mismatches/coincidences only; no qualified negatives or transient dispositions.")
    log(f"REPORT SHA256: {sha(report_path)}")
    log(f"BANK MANIFEST SHA256: {sha(bank_path)}")
    log("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
