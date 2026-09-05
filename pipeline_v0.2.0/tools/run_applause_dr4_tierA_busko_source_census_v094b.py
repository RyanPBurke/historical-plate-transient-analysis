#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
import re
import shutil
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
    / "applause_dr4_tierA_busko_source_census_storage_amendment_v094b.json"
)
EXPECTED_CONTRACT_SHA = "d277b2ca4ca85f5c225989c9bb0694a1b0a9fc70749f41e5b08b13ac9989009b"

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

V094A_WORK = ROOT / "work" / "applause_dr4_tierA_busko_source_census_v094a"
V094A_RAW = V094A_WORK / "source_votable_batches"
V094A_NPZ = V094A_WORK / "source_scan_npz"

WORK = ROOT / "work" / "applause_dr4_tierA_busko_source_census_v094b"
RAW = WORK / "source_votable_temp"
NPZ = WORK / "source_scan_minimal_npz"
STATE = WORK / "state"
RESULT = ROOT / "results" / "applause_dr4_tierA_busko_source_census_v094b"

TAP_ASYNC = "https://www.plate-archive.org/tap/async"

BUSKO_R_ARCSEC = 5.0
CONFIRM_PRIMARY_ARCSEC = 3.0
CONFIRM_DIAG_ARCSEC = 5.0
MIN_SITE_KM = 100.0
SPUTNIK = datetime(1957, 10, 4, 19, 28, 34, tzinfo=timezone.utc)

MAXREC = 2000000
BATCH_SCANS = 6
MIN_FREE_GB = 5.0

SOURCE_FIELDS = ["source_id", "scan_id", "ra_icrs", "dec_icrs"]


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


def free_gb(path):
    u = shutil.disk_usage(path)
    return u.free / (1024 ** 3)


def guard_space(label):
    g = free_gb(ROOT)
    log(f"Disk free before {label}: {g:.2f} GiB")
    if g < MIN_FREE_GB:
        raise RuntimeError(
            f"STORAGE HOLD: only {g:.2f} GiB free; minimum guard is {MIN_FREE_GB:.1f} GiB"
        )


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
    return (
        "SELECT source_id, scan_id, ra_icrs, dec_icrs "
        "FROM applause_dr4.source_calib "
        f"WHERE scan_id IN ({ids}) "
        "AND ra_icrs IS NOT NULL AND dec_icrs IS NOT NULL"
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


def minimal_npz_path(sid):
    return NPZ / f"scan_{int(sid)}.npz"


def write_minimal_scan_npz(sid, source_id, ra, dec):
    NPZ.mkdir(parents=True, exist_ok=True)
    p = minimal_npz_path(sid)
    source_id = np.asarray(source_id, dtype=np.int64)
    ra = np.asarray(ra, dtype=np.float64)
    dec = np.asarray(dec, dtype=np.float64)
    ok = np.isfinite(ra) & np.isfinite(dec)
    source_id = source_id[ok]
    ra = ra[ok]
    dec = dec[ok]

    tmp = p.with_suffix(".npz.tmp")
    with tmp.open("wb") as f:
        np.savez_compressed(f, source_id=source_id, ra=ra, dec=dec)
    tmp.replace(p)

    z = np.load(p, allow_pickle=False)
    if not (len(z["source_id"]) == len(z["ra"]) == len(z["dec"])):
        raise RuntimeError(f"Minimal NPZ verification failed for scan {sid}")
    return p, len(z["ra"])


def convert_votable_to_minimal(vot):
    tbl = Table.read(vot, format="votable")
    cols = {str(c).lower(): str(c) for c in tbl.colnames}
    missing = [c for c in SOURCE_FIELDS if c not in cols]
    if missing:
        raise RuntimeError(f"VOTable missing minimal discovery fields: {missing}")

    groups = defaultdict(list)
    for i, v in enumerate(tbl[cols["scan_id"]]):
        try:
            groups[int(v)].append(i)
        except Exception:
            pass

    written = {}
    total = 0
    for sid, inds in groups.items():
        idx = np.asarray(inds, dtype=int)

        def col(name, dtype):
            x = tbl[cols[name]][idx]
            if np.ma.isMaskedArray(x):
                fill = np.nan if np.issubdtype(np.dtype(dtype), np.floating) else -1
                x = x.filled(fill)
            return np.asarray(x, dtype=dtype)

        p, n = write_minimal_scan_npz(
            sid,
            col("source_id", np.int64),
            col("ra_icrs", np.float64),
            col("dec_icrs", np.float64),
        )
        written[int(sid)] = {"rows": n, "sha256": sha(p)}
        total += n

    return len(tbl), written, total


def salvage_v094a(needed):
    STATE.mkdir(parents=True, exist_ok=True)
    manifest_path = STATE / "v094a_salvage_manifest_v094b.json"
    manifest = {
        "status": "RUNNING",
        "source": str(V094A_RAW.relative_to(ROOT)).replace("\\", "/"),
        "files": [],
    }

    if not V094A_RAW.is_dir():
        wjson(manifest_path, {**manifest, "status": "NO_V094A_RAW_CACHE"})
        return

    files = sorted(V094A_RAW.glob("*.vot"))
    log(f"v094a raw VOTables available for salvage: {len(files)}")

    for i, vot in enumerate(files, 1):
        guard_space(f"salvage {i}/{len(files)}")
        raw_sha = sha(vot)
        raw_size = vot.stat().st_size
        try:
            n_raw, written, n_min = convert_votable_to_minimal(vot)
            # Only keep scan products that are still part of the frozen v094b scan set.
            for sid in list(written):
                if sid not in needed:
                    p = minimal_npz_path(sid)
                    if p.exists():
                        p.unlink()
                    written.pop(sid, None)

            manifest["files"].append({
                "path": str(vot.relative_to(ROOT)).replace("\\", "/"),
                "raw_sha256": raw_sha,
                "raw_size_bytes": raw_size,
                "votable_rows": n_raw,
                "minimal_rows_before_needed_filter": n_min,
                "written_needed_scans": written,
                "raw_deleted_after_verified_conversion": True,
            })
            wjson(manifest_path, manifest)

            # Delete the huge raw VOTable only after verified conversion + manifest write.
            vot.unlink()

            # Delete its sidecar JSON after preserving essential provenance in salvage manifest.
            sidecar = vot.with_suffix(".json")
            if sidecar.exists():
                sidecar.unlink()

            # Delete superseded full-field per-scan v094a NPZs for converted scans.
            for sid in written:
                old = V094A_NPZ / f"scan_{sid}.npz"
                if old.exists():
                    old.unlink()

            log(
                f"Salvaged {i}/{len(files)}: rows={n_raw}, "
                f"needed_scans={len(written)}, reclaimed={raw_size/1024/1024:.1f} MiB"
            )
        except Exception as e:
            manifest["files"].append({
                "path": str(vot.relative_to(ROOT)).replace("\\", "/"),
                "raw_sha256": raw_sha,
                "raw_size_bytes": raw_size,
                "error": repr(e),
                "raw_deleted_after_verified_conversion": False,
            })
            wjson(manifest_path, manifest)
            raise

    # Any remaining old full-field NPZ with a successfully available minimal replacement is superseded.
    if V094A_NPZ.is_dir():
        removed = 0
        for old in V094A_NPZ.glob("scan_*.npz"):
            m = re.match(r"scan_(\d+)\.npz$", old.name)
            if not m:
                continue
            sid = int(m.group(1))
            if minimal_npz_path(sid).is_file():
                old.unlink()
                removed += 1
        log(f"Deleted superseded full-field v094a NPZ files: {removed}")

    manifest["status"] = "COMPLETE"
    manifest["completed_utc"] = datetime.now(timezone.utc).isoformat()
    wjson(manifest_path, manifest)


def submit_minimal_batch(batch_index, scan_ids):
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"batch_{batch_index:04d}.vot"
    meta = RAW / f"batch_{batch_index:04d}.json"
    wanted = sorted(map(int, scan_ids))
    q = source_query(wanted)

    rec = {"status": "STARTED", "scan_ids": wanted, "query": q, "attempts": []}
    wjson(meta, rec)

    last = None
    for attempt in range(1, 5):
        try:
            guard_space(f"source batch {batch_index:04d}")
            log(f"Minimal batch {batch_index:04d}: scans={wanted}, attempt={attempt}")

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
                raise RuntimeError(f"Could not resolve TAP job URL: {job}")

            t0 = time.time()
            while True:
                ph = phase_text(job)
                if "COMPLETED" in ph:
                    break
                if "ERROR" in ph or "ABORTED" in ph:
                    raise RuntimeError(f"TAP job phase {ph}")
                if time.time() - t0 > 4 * 3600:
                    raise RuntimeError("TAP minimal source batch exceeded 4h")
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
            n = len(tbl)
            if n >= MAXREC:
                rec.update({
                    "status": "MAXREC",
                    "rows": n,
                    "sha256": sha(out),
                    "size_bytes": out.stat().st_size,
                })
                wjson(meta, rec)
                return out, n, rec

            raw_sha = sha(out)
            raw_size = out.stat().st_size
            n_raw, written, n_min = convert_votable_to_minimal(out)
            if n_raw != n or n_min != n:
                raise RuntimeError(
                    f"Minimal conversion row mismatch: table={n} converted={n_min}"
                )

            rec.update({
                "status": "COMPLETE",
                "rows": n,
                "raw_sha256": raw_sha,
                "raw_size_bytes": raw_size,
                "minimal_scan_products": written,
                "raw_deleted_after_verified_conversion": True,
                "completed_utc": datetime.now(timezone.utc).isoformat(),
            })
            wjson(meta, rec)

            # Raw response is no longer needed after manifest + verified minimal caches.
            out.unlink()
            log(
                f"Minimal batch {batch_index:04d}: COMPLETE rows={n}, "
                f"transient_raw={raw_size/1024/1024:.1f} MiB, raw deleted"
            )
            return None, n, rec

        except Exception as e:
            last = e
            rec["attempts"].append({"attempt": attempt, "error": repr(e)})
            wjson(meta, rec)
            log(f"Minimal batch {batch_index:04d}: attempt {attempt} failed: {e}")
            time.sleep(20 * attempt)

    raise RuntimeError(f"Minimal source batch {batch_index} failed: {last}")


def acquire_missing(scan_ids):
    missing = [sid for sid in sorted(scan_ids) if not minimal_npz_path(sid).is_file()]
    log(f"Source scans already available in minimal cache: {len(scan_ids)-len(missing)}")
    log(f"Source scans still to acquire: {len(missing)}")

    queue = [
        missing[i:i + BATCH_SCANS]
        for i in range(0, len(missing), BATCH_SCANS)
    ]
    manifest_path = STATE / "source_acquisition_manifest_v094b.json"
    completed = []
    bi = 0

    while queue:
        group = queue.pop(0)
        bi += 1
        out, n, rec = submit_minimal_batch(bi, group)

        if rec.get("status") == "MAXREC":
            # Do not use a truncated batch. Delete it and split.
            if out and out.exists():
                out.unlink()
            if len(group) == 1:
                raise RuntimeError(
                    f"Single scan {group[0]} reached MAXREC={MAXREC}; cannot proceed without pagination"
                )
            mid = len(group) // 2
            queue.insert(0, group[mid:])
            queue.insert(0, group[:mid])
            log(f"Minimal batch {bi:04d} hit MAXREC; split {group}")
            continue

        completed.append(rec)
        wjson(manifest_path, {
            "status": "RUNNING",
            "needed_scan_ids": sorted(scan_ids),
            "completed_batches": completed,
        })

    wjson(manifest_path, {
        "status": "COMPLETE",
        "needed_scan_ids": sorted(scan_ids),
        "completed_batches": completed,
        "all_scan_npz_present": all(minimal_npz_path(s).is_file() for s in scan_ids),
    })
    return manifest_path


def load_scan(sid):
    p = minimal_npz_path(sid)
    if not p.is_file():
        return None
    z = np.load(p, allow_pickle=False)
    ok = np.isfinite(z["ra"]) & np.isfinite(z["dec"])
    return {
        "source_id": z["source_id"][ok],
        "ra": z["ra"][ok],
        "dec": z["dec"][ok],
    }


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
        return [], None, [], []

    all_ra = np.concatenate([z["ra"] for _, z in data])
    all_dec = np.concatenate([z["dec"] for _, z in data])
    all_sid = np.concatenate(
        [np.full(len(z["ra"]), sid, dtype=np.int64) for sid, z in data]
    )
    all_source = np.concatenate([z["source_id"] for _, z in data])
    all_xyz = xyz(all_ra, all_dec)
    tree_all = cKDTree(all_xyz)

    if len(data) == 1:
        sid, z = data[0]
        reps = [{
            "ra": float(z["ra"][i]),
            "dec": float(z["dec"][i]),
            "scan_ids": [int(sid)],
            "source_ids": [int(z["source_id"][i])],
            "support_count": 1,
            "scan_support_class": "SINGLE_SCAN",
        } for i in range(len(z["ra"]))]
        return reps, tree_all, [int(sid)], all_source

    uf = UF(n)
    for i in range(len(data)):
        sid1, _ = data[i]
        a0, a1 = offsets[sid1]
        x1 = all_xyz[a0:a1]
        for j in range(i + 1, len(data)):
            sid2, _ = data[j]
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

    return reps, tree_all, [int(sid) for sid, _ in data], all_source


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
    log("APPLAUSE DR4 — TIER-A BUSKO SOURCE CENSUS v094b")
    log("=" * 110)
    log("Storage amendment: minimal source columns + immediate raw-batch deletion.")
    log("No candidate outcomes were seen before this amendment.")
    log("External catalogues: 0; pixels: 0; quality thresholds: NONE.")
    log("")

    if sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v094b contract SHA mismatch")
    if sha(PARENT_BANK) != EXPECTED_PARENT_BANK_SHA:
        raise RuntimeError("v093e bank SHA mismatch")

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
        k = (r["positive_plate"], r["independent_plate"], r["control_plate"])
        if k not in unique or (
            (r["gap_minutes"] or 1e99) < (unique[k]["gap_minutes"] or 1e99)
        ):
            unique[k] = r
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
    needed = set()
    multiplicity = Counter()

    for r in triplets:
        ps = [s for s in plate_scans.get(r["positive_plate"], []) if scan_polys.get(s)]
        qs = [s for s in plate_scans.get(r["independent_plate"], []) if scan_polys.get(s)]
        cs = [s for s in plate_scans.get(r["control_plate"], []) if scan_polys.get(s)]

        multiplicity[f"P{len(ps)}_I{len(qs)}_C{len(cs)}"] += 1
        if min(len(ps), len(qs), len(cs)) < 1:
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

    log(f"Tier-A single-exposure comparison rows: {len(controls)}")
    log(f"Unique directed physical triplets: {len(triplets)}")
    log(f"Scan-eligible triplets: {len(eligible)}")
    log(f"Unique source scans required: {len(needed)}")
    log(f"Scan multiplicity classes: {dict(multiplicity)}")
    log(f"Selection holds: {dict(holds)}")

    if len(controls) != 784 or len(triplets) != 784 or len(eligible) != 784 or len(needed) != 1073:
        raise RuntimeError(
            "PROVENANCE HOLD: v094b reconstructed availability population differs from frozen v094a census"
        )

    STATE.mkdir(parents=True, exist_ok=True)
    wjson(STATE / "selection_snapshot_v094b.json", {
        "controls": len(controls),
        "triplets": len(triplets),
        "eligible": len(eligible),
        "needed_scan_ids": sorted(needed),
        "multiplicity": dict(multiplicity),
        "holds": dict(holds),
    })

    guard_space("v094a salvage")
    salvage_v094a(set(needed))
    log(f"Disk free after salvage: {free_gb(ROOT):.2f} GiB")

    acq_path = acquire_missing(set(needed))
    if not all(minimal_npz_path(s).is_file() for s in needed):
        missing = [s for s in needed if not minimal_npz_path(s).is_file()]
        raise RuntimeError(f"PROVENANCE HOLD: missing minimal source caches for scans {missing[:20]}")

    log(f"All {len(needed)} source scans available in minimal cache.")
    log(f"Persistent minimal cache size: {sum(p.stat().st_size for p in NPZ.glob('*.npz'))/1024/1024/1024:.3f} GiB")
    log(f"Disk free before matching: {free_gb(ROOT):.2f} GiB")

    rep_cache = {}

    def reps(pid):
        if pid not in rep_cache:
            rep_cache[pid] = plate_representatives(
                [s for s in plate_scans.get(pid, []) if s in needed]
            )
        return rep_cache[pid]

    candidates = []
    counters = Counter()

    for ti, r in enumerate(eligible, 1):
        pcls, ptree, ps_used, _ = reps(r["positive_plate"])
        qcls, qtree, qs_used, _ = reps(r["independent_plate"])
        _, ctree, cs_used, _ = reps(r["control_plate"])

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
        "candidate_ra_icrs", "candidate_dec_icrs", "positive_scan_support",
        "positive_scan_support_class", "positive_scan_ids", "positive_source_ids",
        "independent_sep_arcsec", "independent_scan_support",
        "independent_scan_support_class", "independent_scan_ids", "independent_source_ids",
        "control_available_scan_count", "control_nearest_catalog_sep_arcsec",
        "positive_scan_coverage_count", "independent_scan_coverage_count",
        "control_scan_coverage_count", "catalogue_absence_is_qualified_negative",
        "candidate_disposition",
    ]
    cand = RESULT / "applause_dr4_tierA_busko_independent_catalogue_candidates_v094b.csv"
    wcsv(cand, candidates, fields)

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

    class_counts = Counter(x["confirmation_class"] for x in candidates)
    epoch_counts = Counter(x["epoch_stratum"] for x in candidates)
    support_counts = Counter(
        f"{x['positive_scan_support_class']}|{x['independent_scan_support_class']}"
        for x in candidates
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_tierA_busko_source_census_v094b",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "parent_v093e_bank_manifest_sha256": EXPECTED_PARENT_BANK_SHA,
        "storage_amendment_pre_candidate": True,
        "tierA_single_exposure_comparison_rows": len(controls),
        "unique_directed_single_exposure_physical_triplets": len(triplets),
        "scan_eligible_triplets": len(eligible),
        "unique_source_scans": len(needed),
        "minimal_cache_size_bytes": sum(p.stat().st_size for p in NPZ.glob("*.npz")),
        "mechanical_counter": dict(counters),
        "catalogue_candidate_rows": len(candidates),
        "catalogue_candidate_unique_positions_3arcsec_reporting_only": unique_count,
        "confirmation_class_counts": dict(class_counts),
        "scan_support_class_counts": dict(support_counts),
        "epoch_stratum_counts": dict(epoch_counts),
        "catalogue_absence_is_qualified_negative": False,
        "candidate_dispositions_changed": False,
        "source_acquisition_manifest_sha256": sha(acq_path),
        "candidate_csv_sha256": sha(cand),
        "guards": {
            "external_catalogue_queries": 0,
            "pixel_downloads": 0,
            "fits_reads": 0,
            "detector_runs": 0,
            "source_quality_thresholds_applied": 0,
            "candidate_disposition_changes": 0,
        },
    }

    rp = RESULT / "applause_dr4_tierA_busko_source_census_v094b.json"
    wjson(rp, report)

    bank = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_tierA_busko_source_census_v094b_bank_manifest",
        "report_sha256": sha(rp),
        "candidate_csv_sha256": sha(cand),
        "source_acquisition_manifest_sha256": sha(acq_path),
        "raw_source_votables_retained": False,
        "minimal_per_scan_cache_retained_in_work": True,
        "candidate_dispositions_changed": False,
    }
    bp = RESULT / "applause_dr4_v094b_bank_manifest.json"
    wjson(bp, bank)

    log("")
    log("=" * 110)
    log("v094b STORAGE-EFFICIENT TIER-A SOURCE CENSUS COMPLETE")
    log("=" * 110)
    log(f"Minimal cache size: {report['minimal_cache_size_bytes']/1024/1024/1024:.3f} GiB")
    log(f"Catalogue candidate rows: {len(candidates)}; unique positions~3\"={unique_count}")
    log(f"Confirmation classes: {dict(class_counts)}")
    log(f"Scan-support classes: {dict(support_counts)}")
    log(f"Epoch strata: {dict(epoch_counts)}")
    log("IMPORTANT: catalogue mismatches only; no qualified negatives or transient dispositions.")
    log(f"REPORT SHA256: {sha(rp)}")
    log(f"BANK MANIFEST SHA256: {sha(bp)}")
    log("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
