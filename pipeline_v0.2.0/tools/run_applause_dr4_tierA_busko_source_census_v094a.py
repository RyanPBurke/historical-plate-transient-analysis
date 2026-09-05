#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np
from astropy.table import Table
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "applause_dr4_tierA_busko_source_census_scan_availability_amendment_v094a.json"
)
EXPECTED_CONTRACT_SHA = "853dc03e1c83110291e1713f8703ee1ccacf60315374e11228bb563fb8b5fccb"

PARENT_BANK = (
    ROOT / "results" / "applause_dr4_site_coordinate_semantics_repair_v093e"
    / "applause_dr4_v093e_bank_manifest.json"
)
EXPECTED_PARENT_BANK_SHA = "1889b93e4f104bd025ce221cb7435cfe53041e6f702835ac603e5da6a8ac2139"

PARENT = ROOT / "results" / "applause_dr4_site_coordinate_semantics_repair_v093e"
OPP = PARENT / "applause_dr4_site_coordinate_repaired_opportunities_v093e.csv"
COMP = PARENT / "applause_dr4_site_coordinate_repaired_comparisons_v093e.csv"

V093_CACHE = (
    ROOT / "work"
    / "applause_dr4_busko_first_cross_observatory_opportunity_census_v093"
    / "tap_cache"
)
SCAN_CACHE = V093_CACHE / "scan.csv"
SOLUTION_CACHE = V093_CACHE / "solution.csv"

WORK = ROOT / "work" / "applause_dr4_tierA_busko_source_census_v094a"
RAW = WORK / "source_votable_batches"
NPZ = WORK / "source_scan_npz"
STATE = WORK / "state"
RESULT = ROOT / "results" / "applause_dr4_tierA_busko_source_census_v094a"

TAP_ASYNC = "https://www.plate-archive.org/tap/async"

BUSKO_R_ARCSEC = 5.0
CONFIRM_PRIMARY_ARCSEC = 3.0
CONFIRM_DIAG_ARCSEC = 5.0
MIN_SITE_KM = 100.0
SPUTNIK = datetime(1957, 10, 4, 19, 28, 34, tzinfo=timezone.utc)

MAXREC = 2000000
INITIAL_BATCH_SCANS = 6

SOURCE_FIELDS = [
    "source_id", "process_id", "scan_id", "plate_id", "archive_id", "solution_num",
    "ra_icrs", "dec_icrs", "ra_error", "dec_error", "nn_dist",
    "natmag", "natmag_error", "phot_range_flags", "sextractor_flags", "model_prediction"
]


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


def wcsv(p, rr, fields):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rr:
            w.writerow(r)
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


def wrap_ra(ra, ref):
    x = ra
    while x - ref > 180:
        x -= 360
    while x - ref < -180:
        x += 360
    return x


def point_in_poly(ra, dec, poly):
    if not poly:
        return False
    ref = ra
    c = math.cos(math.radians(dec))
    pts = [(wrap_ra(r, ref) * c, d) for r, d in poly]
    x = ra * c
    y = dec
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xcross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xcross:
                inside = not inside
        j = i
    return inside


def xyz(ra, dec):
    ra = np.deg2rad(np.asarray(ra, dtype=float))
    dec = np.deg2rad(np.asarray(dec, dtype=float))
    c = np.cos(dec)
    return np.column_stack((c * np.cos(ra), c * np.sin(ra), np.sin(dec)))


def chord(arcsec):
    a = math.radians(arcsec / 3600.0)
    return 2 * math.sin(a / 2)


def arcsec_from_chord(d):
    d = max(0.0, min(2.0, float(d)))
    return math.degrees(2 * math.asin(d / 2)) * 3600.0


def source_query(scan_ids):
    ids = ",".join(str(int(x)) for x in scan_ids)
    fields = ", ".join(SOURCE_FIELDS)
    return (
        f"SELECT {fields} FROM applause_dr4.source_calib "
        f"WHERE scan_id IN ({ids}) AND ra_icrs IS NOT NULL AND dec_icrs IS NOT NULL"
    )


def phase_text(job):
    with urllib.request.urlopen(job + "/phase", timeout=120) as r:
        return r.read().decode("utf-8", "replace").strip().upper()


def discover_result_url(job):
    try:
        with urllib.request.urlopen(job, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
        root = ET.fromstring(body)
        for el in root.iter():
            if el.tag.lower().endswith("result"):
                href = (
                    el.attrib.get("{http://www.w3.org/1999/xlink}href")
                    or el.attrib.get("href")
                )
                if href:
                    return urllib.parse.urljoin(job + "/", href)
    except Exception:
        pass

    for suffix in ("/results/result", "/results/votable", "/results/csv"):
        u = job + suffix
        try:
            with urllib.request.urlopen(u, timeout=120) as r:
                head = r.read(512)
            if b"VOTABLE" in head.upper() or head.lstrip().startswith(b"<?xml"):
                return u
        except Exception:
            pass
    raise RuntimeError(f"Could not discover TAP result URL for {job}")


def submit_batch(batch_index, scan_ids):
    RAW.mkdir(parents=True, exist_ok=True)
    name = f"batch_{batch_index:04d}_" + "_".join(map(str, scan_ids))
    out = RAW / f"{name}.vot"
    meta = RAW / f"{name}.json"
    wanted = sorted(map(int, scan_ids))

    if out.is_file() and meta.is_file():
        m = json.loads(meta.read_text(encoding="utf-8"))
        if (
            m.get("status") == "COMPLETE"
            and m.get("scan_ids") == wanted
            and m.get("sha256") == sha(out)
        ):
            tbl = Table.read(out, format="votable")
            return out, len(tbl)

    q = source_query(wanted)
    rec = {"status": "STARTED", "scan_ids": wanted, "query": q, "attempts": []}
    wjson(meta, rec)

    last = None
    for attempt in range(1, 5):
        try:
            log(f"Batch {batch_index:04d}: submit scans={wanted}, attempt={attempt}")
            data = urllib.parse.urlencode({
                "REQUEST": "doQuery",
                "LANG": "ADQL",
                "FORMAT": "votable",
                "QUERY": q,
                "QUEUE": "1h",
                "MAXREC": str(MAXREC),
                "PHASE": "RUN",
            }).encode()
            req = urllib.request.Request(TAP_ASYNC, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=180) as r:
                job = r.geturl().rstrip("/")
                body = r.read(10000).decode("utf-8", "replace")
                loc = r.headers.get("Location")
                if loc:
                    job = urllib.parse.urljoin(job + "/", loc).rstrip("/")
            if "/tap/async/" not in job:
                m = re.search(r'https?://[^"\s<]+/tap/async/[^"\s<]+', body)
                if m:
                    job = m.group(0).rstrip("/")
            if "/tap/async/" not in job:
                raise RuntimeError(f"Could not resolve TAP async job URL: {job}")

            t0 = time.time()
            while True:
                ph = phase_text(job)
                if "COMPLETED" in ph:
                    break
                if "ERROR" in ph or "ABORTED" in ph:
                    raise RuntimeError(f"TAP job phase {ph}")
                if time.time() - t0 > 4 * 3600:
                    raise RuntimeError("TAP source batch exceeded 4h")
                time.sleep(20)

            u = discover_result_url(job)
            tmp = out.with_suffix(".vot.part")
            with urllib.request.urlopen(u, timeout=3600) as r, tmp.open("wb") as f:
                while True:
                    b = r.read(1024 * 1024)
                    if not b:
                        break
                    f.write(b)
            tmp.replace(out)

            tbl = Table.read(out, format="votable")
            cols = {str(c).lower() for c in tbl.colnames}
            missing = [c for c in SOURCE_FIELDS if c not in cols]
            if missing:
                raise RuntimeError(f"Source VOTable missing columns: {missing}")

            n = len(tbl)
            rec.update({
                "status": "COMPLETE",
                "rows": n,
                "sha256": sha(out),
                "size_bytes": out.stat().st_size,
                "completed_utc": datetime.now(timezone.utc).isoformat(),
            })
            wjson(meta, rec)
            log(
                f"Batch {batch_index:04d}: COMPLETE rows={n} "
                f"size={out.stat().st_size/1024/1024:.1f} MiB"
            )
            return out, n
        except Exception as e:
            last = e
            rec["attempts"].append({"attempt": attempt, "error": repr(e)})
            wjson(meta, rec)
            log(f"Batch {batch_index:04d}: attempt {attempt} failed: {e}")
            time.sleep(20 * attempt)

    raise RuntimeError(f"Source batch {batch_index} failed: {last}")


def acquire_adaptive(scan_ids):
    queue = [sorted(map(int, scan_ids))]
    completed = []
    batch_index = 0

    while queue:
        scans = queue.pop(0)
        batch_index += 1
        out, n = submit_batch(batch_index, scans)

        if n >= MAXREC:
            if len(scans) == 1:
                raise RuntimeError(
                    f"Single scan {scans[0]} reached MAXREC={MAXREC}; "
                    "cannot use truncated source table."
                )
            mid = len(scans) // 2
            log(f"Batch {batch_index:04d} hit MAXREC; splitting {scans}")
            queue.insert(0, scans[mid:])
            queue.insert(0, scans[:mid])
            continue

        completed.append((out, scans, n))

    return completed


def to_npz(vot):
    tbl = Table.read(vot, format="votable")
    NPZ.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    for i, v in enumerate(tbl["scan_id"]):
        try:
            groups[int(v)].append(i)
        except Exception:
            pass

    for sid, inds in groups.items():
        p = NPZ / f"scan_{sid}.npz"
        if p.is_file():
            continue
        idx = np.asarray(inds, dtype=int)

        def arr(name, dtype=float):
            col = tbl[name][idx]
            if np.ma.isMaskedArray(col):
                if np.issubdtype(np.dtype(dtype), np.floating):
                    return np.asarray(col.filled(np.nan), dtype=dtype)
                return np.asarray(col.filled(-1), dtype=dtype)
            return np.asarray(col, dtype=dtype)

        np.savez_compressed(
            p,
            source_id=arr("source_id", np.int64),
            process_id=arr("process_id", np.int64),
            scan_id=arr("scan_id", np.int64),
            plate_id=arr("plate_id", np.int64),
            archive_id=arr("archive_id", np.int64),
            solution_num=arr("solution_num", np.int32),
            ra=arr("ra_icrs", float),
            dec=arr("dec_icrs", float),
            ra_error=arr("ra_error", float),
            dec_error=arr("dec_error", float),
            nn_dist=arr("nn_dist", float),
            natmag=arr("natmag", float),
            natmag_error=arr("natmag_error", float),
            phot_range_flags=arr("phot_range_flags", np.int32),
            sextractor_flags=arr("sextractor_flags", np.int32),
            model_prediction=arr("model_prediction", float),
        )


def load_scan(sid):
    p = NPZ / f"scan_{sid}.npz"
    if not p.is_file():
        return None
    z = np.load(p, allow_pickle=False)
    ok = np.isfinite(z["ra"]) & np.isfinite(z["dec"])
    return {k: z[k][ok] for k in z.files}


class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


def plate_representatives(scan_ids):
    data = []
    offsets = {}
    n = 0

    for sid in scan_ids:
        z = load_scan(sid)
        if z is None or len(z["ra"]) == 0:
            continue
        offsets[sid] = (n, n + len(z["ra"]))
        data.append((sid, z))
        n += len(z["ra"])

    if n == 0:
        return [], None, {}, []

    all_ra = np.concatenate([z["ra"] for _, z in data])
    all_dec = np.concatenate([z["dec"] for _, z in data])
    all_sid = np.concatenate(
        [np.full(len(z["ra"]), sid, dtype=np.int64) for sid, z in data]
    )
    all_source = np.concatenate([z["source_id"] for _, z in data])
    all_xyz = xyz(all_ra, all_dec)
    tree_all = cKDTree(all_xyz)

    # Single-scan plate: every calibrated detection is a representative.
    if len(data) == 1:
        sid, z = data[0]
        reps = []
        for i in range(len(z["ra"])):
            reps.append({
                "ra": float(z["ra"][i]),
                "dec": float(z["dec"][i]),
                "scan_ids": [int(sid)],
                "source_ids": [int(z["source_id"][i])],
                "support_count": 1,
                "scan_support_class": "SINGLE_SCAN",
            })
        return reps, tree_all, {
            "ra": all_ra, "dec": all_dec, "sid": all_sid, "source": all_source
        }, [int(sid)]

    # Multi-scan plate: only retain detections matched across >=2 distinct scans.
    uf = UF(n)
    for i in range(len(data)):
        sid1, z1 = data[i]
        a0, a1 = offsets[sid1]
        x1 = all_xyz[a0:a1]
        for j in range(i + 1, len(data)):
            sid2, z2 = data[j]
            b0, b1 = offsets[sid2]
            x2 = all_xyz[b0:b1]
            if len(x1) == 0 or len(x2) == 0:
                continue
            t2 = cKDTree(x2)
            d12, k12 = t2.query(
                x1, k=1, distance_upper_bound=chord(BUSKO_R_ARCSEC)
            )
            t1 = cKDTree(x1)
            d21, k21 = t1.query(
                x2, k=1, distance_upper_bound=chord(BUSKO_R_ARCSEC)
            )
            for ii, (dd, jj) in enumerate(zip(d12, k12)):
                if not np.isfinite(dd) or jj >= len(x2):
                    continue
                if k21[jj] == ii and np.isfinite(d21[jj]):
                    uf.union(a0 + ii, b0 + int(jj))

    groups = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)

    reps = []
    for inds in groups.values():
        scans = sorted(set(int(all_sid[i]) for i in inds))
        if len(scans) < 2:
            continue
        vv = all_xyz[inds].mean(axis=0)
        vv = vv / np.linalg.norm(vv)
        dec = math.degrees(math.asin(vv[2]))
        ra = math.degrees(math.atan2(vv[1], vv[0])) % 360
        reps.append({
            "ra": ra,
            "dec": dec,
            "scan_ids": scans,
            "source_ids": [int(all_source[i]) for i in inds],
            "support_count": len(scans),
            "scan_support_class": "MULTISCAN_CONFIRMED",
        })

    return reps, tree_all, {
        "ra": all_ra, "dec": all_dec, "sid": all_sid, "source": all_source
    }, [int(sid) for sid, _ in data]


def nearest_tree(tree, ra, dec):
    if tree is None:
        return None, None
    d, i = tree.query(xyz([ra], [dec])[0], k=1)
    return arcsec_from_chord(d), int(i)


def coverage_count(ra, dec, scan_ids, scan_polys):
    return sum(
        1
        for sid in scan_ids
        if any(point_in_poly(ra, dec, p) for p in scan_polys.get(sid, []))
    )


def main():
    log("=" * 110)
    log("APPLAUSE DR4 — TIER-A BUSKO SOURCE CENSUS v094a")
    log("=" * 110)
    log("Availability amendment: >=1 astrometric scan per plate.")
    log("Where >=2 scans exist, X/Y-style cross-scan consistency is required.")
    log("External catalogues: 0; pixels: 0; source quality thresholds: NONE.")
    log("Catalogue absence is triage only, NOT a qualified negative.")
    log("")

    if sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v094a contract SHA mismatch")
    if sha(PARENT_BANK) != EXPECTED_PARENT_BANK_SHA:
        raise RuntimeError("v093e parent bank SHA mismatch")

    parent_bank = json.loads(PARENT_BANK.read_text(encoding="utf-8"))
    ph = {x["name"]: x["sha256"] for x in parent_bank.get("files", [])}
    for p in (OPP, COMP):
        if ph.get(p.name) != sha(p):
            raise RuntimeError(f"Parent banked input mismatch: {p.name}")

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
            p_plate = inum(o.get("plate_a"))
            q_plate = inum(o.get("plate_b"))
            p_exp = inum(o.get("exposure_a"))
            q_exp = inum(o.get("exposure_b"))
            p_num = inum(o.get("plate_numexp_a"))
            q_num = inum(o.get("plate_numexp_b"))
        elif ep == "B":
            p_plate = inum(o.get("plate_b"))
            q_plate = inum(o.get("plate_a"))
            p_exp = inum(o.get("exposure_b"))
            q_exp = inum(o.get("exposure_a"))
            p_num = inum(o.get("plate_numexp_b"))
            q_num = inum(o.get("plate_numexp_a"))
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
        k = (r["positive_plate"], r["independent_plate"], r["control_plate"])
        if k not in unique or (
            (r["gap_minutes"] or 1e99) < (unique[k]["gap_minutes"] or 1e99)
        ):
            unique[k] = r
    triplets = list(unique.values())

    log(f"Tier-A single-exposure comparison rows: {len(controls)}")
    log(f"Unique directed physical triplets: {len(triplets)}")
    log(f"Selection holds: {dict(holds)}")

    st = load_table_any(SCAN_CACHE)
    plate_scans = defaultdict(list)
    for r in st:
        try:
            pid = int(r["plate_id"])
            sid = int(r["scan_id"])
        except Exception:
            continue
        plate_scans[pid].append(sid)
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
    needed = set()
    scan_holds = Counter()
    multiplicity = Counter()

    for r in triplets:
        ps = [sid for sid in plate_scans.get(r["positive_plate"], []) if scan_polys.get(sid)]
        qs = [sid for sid in plate_scans.get(r["independent_plate"], []) if scan_polys.get(sid)]
        cs = [sid for sid in plate_scans.get(r["control_plate"], []) if scan_polys.get(sid)]

        multiplicity[f"P{len(ps)}_I{len(qs)}_C{len(cs)}"] += 1

        if min(len(ps), len(qs), len(cs)) < 1:
            scan_holds["missing_astrometric_scan_on_triplet"] += 1
            continue

        x = dict(r)
        x.update({
            "positive_scan_ids": ps,
            "independent_scan_ids": qs,
            "control_scan_ids": cs,
        })
        eligible.append(x)
        needed.update(ps)
        needed.update(qs)
        needed.update(cs)

    log(f"Triplets with >=1 astrometric scan on all 3 plates: {len(eligible)}")
    log(f"Unique source scans required: {len(needed)}")
    log(f"Scan multiplicity classes: {dict(multiplicity)}")
    log(f"Scan holds: {dict(scan_holds)}")

    RESULT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    wjson(
        STATE / "selection_snapshot_v094a.json",
        {
            "tierA_single_exposure_comparison_rows": len(controls),
            "unique_directed_physical_triplets": len(triplets),
            "scan_eligible_triplets": len(eligible),
            "needed_scan_ids": sorted(needed),
            "selection_holds": dict(holds),
            "scan_holds": dict(scan_holds),
            "scan_multiplicity_classes": dict(multiplicity),
        },
    )

    if not eligible:
        raise RuntimeError(
            "PROVENANCE HOLD: amended >=1-scan rule still yielded zero eligible triplets"
        )

    scan_list = sorted(needed)
    initial_batches = [
        scan_list[i:i + INITIAL_BATCH_SCANS]
        for i in range(0, len(scan_list), INITIAL_BATCH_SCANS)
    ]

    completed = []
    for group in initial_batches:
        got = acquire_adaptive(group)
        for vot, scans, n in got:
            to_npz(vot)
            completed.append({
                "scan_ids": scans,
                "rows": n,
                "votable": str(vot.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha(vot),
                "size_bytes": vot.stat().st_size,
            })
        wjson(
            STATE / "source_acquisition_manifest_v094a.json",
            {
                "status": "RUNNING",
                "needed_scan_ids": scan_list,
                "completed_batches": completed,
            },
        )

    acq = {
        "status": "COMPLETE",
        "needed_scan_ids": scan_list,
        "completed_batches": completed,
    }
    acq_path = STATE / "source_acquisition_manifest_v094a.json"
    wjson(acq_path, acq)

    scan_rows = {}
    zero = []
    for sid in scan_list:
        z = load_scan(sid)
        n = 0 if z is None else len(z["ra"])
        scan_rows[sid] = n
        if n == 0:
            zero.append(sid)

    log(f"Scans with zero calibrated source rows: {len(zero)}")

    rep_cache = {}

    def reps(pid):
        if pid not in rep_cache:
            rep_cache[pid] = plate_representatives(plate_scans.get(pid, []))
        return rep_cache[pid]

    candidates = []
    counters = Counter()

    for ti, r in enumerate(eligible, 1):
        pcls, ptree, pall, ps_used = reps(r["positive_plate"])
        qcls, qtree, qall, qs_used = reps(r["independent_plate"])
        ccls, ctree, call, cs_used = reps(r["control_plate"])

        if min(len(ps_used), len(qs_used), len(cs_used)) < 1:
            counters["source_data_missing_on_triplet"] += 1
            continue

        qxyz = (
            xyz([x["ra"] for x in qcls], [x["dec"] for x in qcls])
            if qcls else np.empty((0, 3))
        )
        qctree = cKDTree(qxyz) if len(qxyz) else None

        for pc in pcls:
            ra, dec = pc["ra"], pc["dec"]

            covp = coverage_count(ra, dec, ps_used, scan_polys)
            covq = coverage_count(ra, dec, qs_used, scan_polys)
            covc = coverage_count(ra, dec, cs_used, scan_polys)

            if min(covp, covq, covc) < 1:
                counters["candidate_not_covered_all3"] += 1
                continue

            csep, _ = nearest_tree(ctree, ra, dec)
            if csep is not None and csep <= BUSKO_R_ARCSEC:
                counters["control_catalog_match_le5"] += 1
                continue

            counters["busko_catalog_mismatch"] += 1

            if qctree is None:
                counters["no_independent_representative_catalog"] += 1
                continue

            dd, qi = qctree.query(xyz([ra], [dec])[0], k=1)
            qsep = arcsec_from_chord(dd)
            if qsep > CONFIRM_DIAG_ARCSEC:
                counters["no_independent_match_le5"] += 1
                continue

            qc = qcls[int(qi)]
            cls = (
                "PRIMARY_LE3"
                if qsep <= CONFIRM_PRIMARY_ARCSEC
                else "DIAGNOSTIC_GT3_LE5"
            )
            counters[cls] += 1

            sdt = parse_dt(r["science_overlap_start_utc"])
            epoch = (
                "PRE_SPUTNIK"
                if sdt and sdt < SPUTNIK
                else "POST_SPUTNIK_OR_SAME_LAUNCH_DATE"
            )

            candidates.append({
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
                "candidate_ra_icrs": f"{ra:.10f}",
                "candidate_dec_icrs": f"{dec:.10f}",
                "positive_scan_support": pc["support_count"],
                "positive_scan_support_class": pc["scan_support_class"],
                "positive_scan_ids": ";".join(map(str, pc["scan_ids"])),
                "positive_source_ids": ";".join(map(str, pc["source_ids"])),
                "independent_sep_arcsec": f"{qsep:.6f}",
                "independent_scan_support": qc["support_count"],
                "independent_scan_support_class": qc["scan_support_class"],
                "independent_scan_ids": ";".join(map(str, qc["scan_ids"])),
                "independent_source_ids": ";".join(map(str, qc["source_ids"])),
                "control_available_scan_count": len(cs_used),
                "control_nearest_catalog_sep_arcsec": (
                    "" if csep is None else f"{csep:.6f}"
                ),
                "positive_scan_coverage_count": covp,
                "independent_scan_coverage_count": covq,
                "control_scan_coverage_count": covc,
                "catalogue_absence_is_qualified_negative": False,
                "candidate_disposition": "UNADJUDICATED_CATALOGUE_COINCIDENCE",
            })

        if ti % 25 == 0:
            log(
                f"Mechanical source matching: {ti}/{len(eligible)} triplets, "
                f"candidate rows={len(candidates)}"
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

    cand_path = (
        RESULT / "applause_dr4_tierA_busko_independent_catalogue_candidates_v094a.csv"
    )
    wcsv(cand_path, candidates, fields)

    unique_count = 0
    if candidates:
        vv = xyz(
            [float(x["candidate_ra_icrs"]) for x in candidates],
            [float(x["candidate_dec_icrs"]) for x in candidates],
        )
        tree = cKDTree(vv)
        uf = UF(len(candidates))
        for i, j in tree.query_pairs(chord(3.0)):
            uf.union(i, j)
        unique_count = len({uf.find(i) for i in range(len(candidates))})

    epoch_counts = Counter(x["epoch_stratum"] for x in candidates)
    class_counts = Counter(x["confirmation_class"] for x in candidates)
    support_counts = Counter(
        f"{x['positive_scan_support_class']}|{x['independent_scan_support_class']}"
        for x in candidates
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_tierA_busko_source_census_v094a",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "parent_v093e_bank_manifest_sha256": EXPECTED_PARENT_BANK_SHA,
        "amendment_reason": (
            "v094 dual-scan-all-three availability rule yielded zero source-eligible "
            "triplets before any source query; v094a uses >=1 scan and applies multi-scan "
            "consistency only when multiple scans exist."
        ),
        "parent_v094_candidate_outcomes_seen_before_amendment": 0,
        "all_qualifying_tierA_controls_processed": True,
        "tierA_single_exposure_comparison_rows": len(controls),
        "unique_directed_single_exposure_physical_triplets": len(triplets),
        "scan_eligible_triplets": len(eligible),
        "scan_multiplicity_classes": dict(multiplicity),
        "unique_source_scans_requested": len(scan_list),
        "zero_source_scan_ids": zero,
        "mechanical_counter": dict(counters),
        "catalogue_candidate_rows": len(candidates),
        "catalogue_candidate_unique_positions_3arcsec_reporting_only": unique_count,
        "confirmation_class_counts": dict(class_counts),
        "scan_support_class_counts": dict(support_counts),
        "epoch_stratum_counts": dict(epoch_counts),
        "selection_holds": dict(holds),
        "scan_holds": dict(scan_holds),
        "catalogue_absence_is_qualified_negative": False,
        "candidate_dispositions_changed": False,
        "source_acquisition_manifest_sha256": sha(acq_path),
        "candidate_csv_sha256": sha(cand_path),
        "guards": {
            "external_catalogue_queries": 0,
            "pixel_downloads": 0,
            "fits_reads": 0,
            "detector_runs": 0,
            "source_quality_thresholds_applied": 0,
            "candidate_disposition_changes": 0,
        },
    }

    report_path = RESULT / "applause_dr4_tierA_busko_source_census_v094a.json"
    wjson(report_path, report)

    bank = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_tierA_busko_source_census_v094a_bank_manifest",
        "report_sha256": sha(report_path),
        "candidate_csv_sha256": sha(cand_path),
        "source_acquisition_manifest_sha256": sha(acq_path),
        "raw_source_cache_not_copied_to_repository": True,
        "candidate_dispositions_changed": False,
    }
    bank_path = RESULT / "applause_dr4_v094a_bank_manifest.json"
    wjson(bank_path, bank)

    log("")
    log("=" * 110)
    log("v094a TIER-A SOURCE CENSUS COMPLETE")
    log("=" * 110)
    log(f"Tier-A single-exposure comparison rows: {len(controls)}")
    log(f"Unique directed physical triplets: {len(triplets)}")
    log(f"Scan-eligible triplets: {len(eligible)}")
    log(f"Scan multiplicity classes: {dict(multiplicity)}")
    log(f"Source scans requested: {len(scan_list)}; zero-source scans={len(zero)}")
    log(f"Catalogue candidate rows: {len(candidates)}; unique positions~3\"={unique_count}")
    log(f"Confirmation classes: {dict(class_counts)}")
    log(f"Scan-support classes: {dict(support_counts)}")
    log(f"Epoch strata: {dict(epoch_counts)}")
    log("IMPORTANT: catalogue coincidences/mismatches only; no qualified negatives or transient dispositions.")
    log(f"REPORT SHA256: {sha(report_path)}")
    log(f"BANK MANIFEST SHA256: {sha(bank_path)}")
    log("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
