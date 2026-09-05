#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "applause_dr4_busko_first_cross_observatory_opportunity_census_contract_v093.json"
)
EXPECTED_CONTRACT_SHA = "dd2e81e8df1eb4504fd902ef122fd512f64afd884923e936e20929cd6b772766"

WORK = ROOT / "work" / "applause_dr4_busko_first_cross_observatory_opportunity_census_v093"
CACHE = WORK / "tap_cache"
STATE = WORK / "state"
RESULT = ROOT / "results" / "applause_dr4_busko_first_cross_observatory_opportunity_census_v093"

TAP_ASYNC = "https://www.plate-archive.org/tap/async"
TAP_SYNC = "https://www.plate-archive.org/tap/sync"

SITE_MAP = {
    1:"Potsdam", 2:"Potsdam", 3:"Potsdam", 4:"Potsdam", 5:"Potsdam", 6:"UNKNOWN",
    101:"Hamburg", 102:"Hamburg", 103:"Hamburg", 104:"Calar Alto", 105:"Bonn",
    106:"Hamburg", 107:"Hamburg", 108:"La Silla", 109:"Hamburg", 110:"Hamburg",
    111:"Hamburg", 202:"South Africa", 203:"South Africa", 204:"New Zealand",
    205:"Argentina", 206:"South Africa", 207:"South Africa", 208:"Bamberg",
    301:"Tartu", 401:"Tautenburg", 501:"Castel Gandolfo",
}

QUERIES = {
    "archive": """
        SELECT archive_id, archive_name, institute, num_plates, num_scans
        FROM applause_dr4.archive
    """,
    "exposure": """
        SELECT exposure_id, plate_id, archive_id, exposure_num,
               ra_icrs, dec_icrs, ut_start, ut_end, jd_start, jd_end,
               exptime, flag_time, num_sub
        FROM applause_dr4.exposure
        WHERE ut_start IS NOT NULL
          AND ut_end IS NOT NULL
          AND ra_icrs IS NOT NULL
          AND dec_icrs IS NOT NULL
    """,
    "scan": """
        SELECT scan_id, plate_id, archive_id, filename_scan, naxis1, naxis2
        FROM applause_dr4.scan
        WHERE filename_scan IS NOT NULL
    """,
    "solution": """
        SELECT solution_id, scan_id, plate_id, archive_id, solution_num,
               ra_icrs, dec_icrs, fov1, fov2, stc_polygon, num_xmatch
        FROM applause_dr4.solution
        WHERE stc_polygon IS NOT NULL
          AND ra_icrs IS NOT NULL
          AND dec_icrs IS NOT NULL
    """,
}

CADENCE_MAX_S = 7200.0
BUSKO_PRIMARY_FRAC = 0.50
COMPARISON_COMMON_COVER_FRAC = 0.50


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str = ""):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def compact_query(q: str) -> str:
    return " ".join(q.split())


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
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


def parse_dt(v):
    s = str(v or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        d = None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except Exception:
                pass
        if d is None:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_phase(text: str) -> str:
    u = text.upper()
    for p in ("COMPLETED","ERROR","ABORTED","EXECUTING","QUEUED","PENDING","HELD"):
        if p in u:
            return p
    return text.strip()[:100].upper()


def download_url(url: str, dest: Path, timeout=3600):
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=timeout) as r, tmp.open("wb") as out:
        total = 0
        while True:
            b = r.read(1024*1024)
            if not b:
                break
            out.write(b)
            total += len(b)
            if total and total % (25*1024*1024) < 1024*1024:
                log(f"    downloaded {total/1024/1024:.1f} MiB")
    tmp.replace(dest)


def validate_csv(path: Path, expected_any):
    if not path.is_file() or path.stat().st_size < 20:
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            hdr = next(rd, [])
        low = {str(x).strip().lower() for x in hdr}
        return any(x.lower() in low for x in expected_any)
    except Exception:
        return False


def tap_query(name: str, query: str, expected_any):
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{name}.csv"
    meta = CACHE / f"{name}.query.json"

    if validate_csv(out, expected_any):
        log(f"TAP cache reuse: {name} ({out.stat().st_size/1024/1024:.1f} MiB, sha={sha(out)[:16]}...)")
        return out

    q = compact_query(query)
    record = {
        "name": name,
        "query": q,
        "started_utc": now_utc(),
        "tap_async": TAP_ASYNC,
        "tap_sync": TAP_SYNC,
        "attempts": [],
    }
    write_json(meta, record)

    for attempt in range(1, 7):
        try:
            log(f"TAP async submit {name}, attempt {attempt}")
            data = urllib.parse.urlencode({
                "REQUEST": "doQuery",
                "LANG": "ADQL",
                "FORMAT": "csv",
                "QUERY": q,
                "QUEUE": "1h",
                "MAXREC": "500000",
                "PHASE": "RUN",
            }).encode("utf-8")
            req = urllib.request.Request(TAP_ASYNC, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=180) as r:
                job_url = r.geturl().rstrip("/")
                body = r.read(10000).decode("utf-8", "replace")
                location = r.headers.get("Location")
                if location:
                    job_url = urllib.parse.urljoin(job_url + "/", location).rstrip("/")

            if "/tap/async/" not in job_url:
                m = re.search(r'https?://[^"\s<]+/tap/async/[^"\s<]+', body)
                if m:
                    job_url = m.group(0).rstrip("/")
            if "/tap/async/" not in job_url:
                raise RuntimeError(f"Could not resolve TAP job URL; final URL={job_url!r}")

            record["attempts"].append({"attempt":attempt, "job_url":job_url, "submitted_utc":now_utc()})
            write_json(meta, record)
            log(f"    job: {job_url}")

            t0 = time.time()
            while True:
                with urllib.request.urlopen(job_url + "/phase", timeout=120) as r:
                    phase_text = r.read().decode("utf-8", "replace")
                phase = parse_phase(phase_text)
                elapsed = time.time() - t0
                log(f"    phase={phase} elapsed={elapsed/60:.1f} min")
                if phase == "COMPLETED":
                    break
                if phase in {"ERROR","ABORTED"}:
                    err = ""
                    try:
                        with urllib.request.urlopen(job_url + "/error", timeout=120) as r:
                            err = r.read().decode("utf-8", "replace")[:5000]
                    except Exception:
                        pass
                    raise RuntimeError(f"TAP job {phase}: {err}")
                if elapsed > 4*3600:
                    raise RuntimeError("TAP async job exceeded 4 h")
                time.sleep(20)

            log(f"    retrieving CSV result for {name}")
            download_url(job_url + "/results/csv", out, timeout=3600)
            if not validate_csv(out, expected_any):
                raise RuntimeError(f"Downloaded TAP result does not validate as expected CSV: {out}")

            record["completed_utc"] = now_utc()
            record["result_sha256"] = sha(out)
            record["result_size_bytes"] = out.stat().st_size
            record["successful_mode"] = "async"
            write_json(meta, record)
            log(f"TAP COMPLETE {name}: {out.stat().st_size/1024/1024:.1f} MiB")
            return out
        except Exception as e:
            log(f"    async attempt {attempt} failed: {e}")
            record["attempts"].append({"attempt":attempt, "error":repr(e), "failed_utc":now_utc()})
            write_json(meta, record)
            if out.exists():
                try:
                    out.unlink()
                except Exception:
                    pass
            time.sleep(min(180, 15 * attempt))

    for attempt in range(1, 4):
        try:
            log(f"TAP sync fallback {name}, attempt {attempt}")
            data = urllib.parse.urlencode({
                "REQUEST":"doQuery",
                "LANG":"ADQL",
                "FORMAT":"csv",
                "QUERY":q,
                "MAXREC":"500000",
            }).encode("utf-8")
            req = urllib.request.Request(TAP_SYNC, data=data, method="POST")
            tmp = out.with_suffix(".csv.part")
            with urllib.request.urlopen(req, timeout=3600) as r, tmp.open("wb") as f:
                while True:
                    b = r.read(1024*1024)
                    if not b:
                        break
                    f.write(b)
            tmp.replace(out)
            if not validate_csv(out, expected_any):
                raise RuntimeError("Sync TAP response failed CSV validation")
            record["completed_utc"] = now_utc()
            record["result_sha256"] = sha(out)
            record["result_size_bytes"] = out.stat().st_size
            record["successful_mode"] = "sync"
            write_json(meta, record)
            return out
        except Exception as e:
            log(f"    sync fallback attempt {attempt} failed: {e}")
            time.sleep(30 * attempt)

    raise RuntimeError(f"Unable to acquire required APPLAUSE TAP table: {name}")


def angular_sep_deg(ra1, dec1, ra2, dec2):
    r1,r2 = math.radians(ra1),math.radians(ra2)
    d1,d2 = math.radians(dec1),math.radians(dec2)
    c = math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c = max(-1.0,min(1.0,c))
    return math.degrees(math.acos(c))


def parse_stc_polygon(v):
    s = str(v or "").strip()
    nums = [float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?', s)]
    if len(nums) < 8:
        return None
    nums = nums[-8:]
    pts = [(nums[i] % 360.0, nums[i+1]) for i in range(0,8,2)]
    if any(not (-90 <= dec <= 90) for _,dec in pts):
        return None
    return pts


def vec(ra,dec):
    r,d=math.radians(ra),math.radians(dec)
    c=math.cos(d)
    return (c*math.cos(r), c*math.sin(r), math.sin(d))


def norm3(v):
    n=math.sqrt(sum(x*x for x in v))
    if n == 0:
        return None
    return tuple(x/n for x in v)


def mean_center(polys):
    vs=[vec(ra,dec) for p in polys for ra,dec in p]
    s=(sum(v[0] for v in vs),sum(v[1] for v in vs),sum(v[2] for v in vs))
    return norm3(s)


def tangent_basis(c):
    east=norm3((-c[1],c[0],0.0))
    if east is None:
        east=(1.0,0.0,0.0)
    north=norm3((
        c[1]*east[2]-c[2]*east[1],
        c[2]*east[0]-c[0]*east[2],
        c[0]*east[1]-c[1]*east[0],
    ))
    return east,north


def signed_area(poly):
    return sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1]
               for i in range(len(poly)))/2.0


def ensure_ccw(poly):
    return list(reversed(poly)) if signed_area(poly) < 0 else list(poly)


def project_poly(poly,c,east,north):
    out=[]
    for ra,dec in poly:
        v=vec(ra,dec)
        den=sum(v[i]*c[i] for i in range(3))
        if den <= 1e-8:
            return None
        x=sum(v[i]*east[i] for i in range(3))/den
        y=sum(v[i]*north[i] for i in range(3))/den
        out.append((x,y))
    return ensure_ccw(out)


def area(poly):
    if not poly or len(poly)<3:
        return 0.0
    return abs(signed_area(poly))


def inside(p,a,b):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]) >= -1e-12


def line_intersection(s,e,a,b):
    x1,y1=s; x2,y2=e; x3,y3=a; x4,y4=b
    den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
    if abs(den)<1e-15:
        return e
    px=((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/den
    py=((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/den
    return (px,py)


def clip(subject, clipper):
    out=list(subject)
    for i in range(len(clipper)):
        inp=out
        out=[]
        if not inp:
            break
        a=clipper[i]; b=clipper[(i+1)%len(clipper)]
        s=inp[-1]
        for e in inp:
            if inside(e,a,b):
                if not inside(s,a,b):
                    out.append(line_intersection(s,e,a,b))
                out.append(e)
            elif inside(s,a,b):
                out.append(line_intersection(s,e,a,b))
            s=e
    return ensure_ccw(out) if len(out)>=3 else []


def pair_overlap_metrics(p1,p2):
    c=mean_center([p1,p2])
    if c is None:
        return None
    east,north=tangent_basis(c)
    a=project_poly(p1,c,east,north)
    b=project_poly(p2,c,east,north)
    if not a or not b:
        return None
    inter=clip(a,b)
    aa,ab,ai=area(a),area(b),area(inter)
    if aa<=0 or ab<=0:
        return None
    return {
        "area_a":aa,"area_b":ab,"area_intersection":ai,
        "fraction_a":ai/aa,"fraction_b":ai/ab,
        "fraction_smaller":ai/min(aa,ab),
    }


def triple_common_coverage(p1,p2,p3):
    c=mean_center([p1,p2,p3])
    if c is None:
        return 0.0
    east,north=tangent_basis(c)
    a=project_poly(p1,c,east,north)
    b=project_poly(p2,c,east,north)
    d=project_poly(p3,c,east,north)
    if not a or not b or not d:
        return 0.0
    common=clip(a,b)
    ac=area(common)
    if ac<=0:
        return 0.0
    triple=clip(common,d)
    return min(1.0,max(0.0,area(triple)/ac))


def interval_gap(a_start,a_end,b_start,b_end):
    if b_end <= a_start:
        return (a_start-b_end).total_seconds(), "PRECEDING"
    if b_start >= a_end:
        return (b_start-a_end).total_seconds(), "FOLLOWING"
    return 0.0, "OVERLAPPING"


def tier(gap):
    if gap <= 1800:
        return "A_LE30MIN"
    if gap <= 3600:
        return "B_GT30_LE60MIN"
    if gap <= 7200:
        return "C_GT60_LE120MIN"
    return ""


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    tmp.replace(path)


def load_archives(path):
    rows=[]
    seen=set()
    for r in read_csv(path):
        aid=inum(r.get("archive_id"))
        if aid is None:
            continue
        seen.add(aid)
        rows.append({
            "archive_id":aid,
            "archive_name":str(r.get("archive_name") or "").strip(),
            "institute":str(r.get("institute") or "").strip(),
            "num_plates":inum(r.get("num_plates")),
            "num_scans":inum(r.get("num_scans")),
            "site_group":SITE_MAP.get(aid,"UNKNOWN"),
        })
    return rows,seen


def load_scans(path):
    by_plate=defaultdict(list)
    for r in read_csv(path):
        pid=inum(r.get("plate_id")); sid=inum(r.get("scan_id")); aid=inum(r.get("archive_id"))
        if None in (pid,sid,aid):
            continue
        by_plate[pid].append({
            "scan_id":sid,"archive_id":aid,
            "filename_scan":str(r.get("filename_scan") or "").strip(),
            "naxis1":inum(r.get("naxis1")),"naxis2":inum(r.get("naxis2")),
        })
    return by_plate


def load_solutions(path,scans_by_plate):
    by_plate=defaultdict(list)
    scan_ids={pid:{x["scan_id"] for x in rr} for pid,rr in scans_by_plate.items()}
    bad_poly=0
    for r in read_csv(path):
        pid=inum(r.get("plate_id")); sid=inum(r.get("scan_id"))
        if pid is None or sid is None or sid not in scan_ids.get(pid,set()):
            continue
        poly=parse_stc_polygon(r.get("stc_polygon"))
        if poly is None:
            bad_poly+=1
            continue
        ra=fnum(r.get("ra_icrs")); dec=fnum(r.get("dec_icrs"))
        if ra is None or dec is None:
            continue
        by_plate[pid].append({
            "solution_id":inum(r.get("solution_id")),
            "scan_id":sid,
            "archive_id":inum(r.get("archive_id")),
            "solution_num":inum(r.get("solution_num")),
            "ra":ra,"dec":dec,
            "fov1":fnum(r.get("fov1")),"fov2":fnum(r.get("fov2")),
            "num_xmatch":inum(r.get("num_xmatch")) or 0,
            "polygon":poly,
        })
    return by_plate,bad_poly


def build_exposure_registry(exp_path, scans_by_plate, solutions_by_plate):
    registry=[]
    stats=Counter()
    for r in read_csv(exp_path):
        stats["exposure_rows"]+=1
        eid=inum(r.get("exposure_id")); pid=inum(r.get("plate_id")); aid=inum(r.get("archive_id"))
        ra=fnum(r.get("ra_icrs")); dec=fnum(r.get("dec_icrs"))
        st=parse_dt(r.get("ut_start")); en=parse_dt(r.get("ut_end"))
        if None in (eid,pid,aid) or ra is None or dec is None or st is None or en is None or en<=st:
            stats["timing_or_center_invalid"]+=1
            continue
        if not scans_by_plate.get(pid):
            stats["no_scan"]+=1
            continue
        sols=solutions_by_plate.get(pid,[])
        if not sols:
            stats["no_solution_polygon"]+=1
            continue
        ranked=[]
        for s in sols:
            sep=angular_sep_deg(ra,dec,s["ra"],s["dec"])
            ranked.append((sep,-s["num_xmatch"],s))
        ranked.sort(key=lambda x:(x[0],x[1],x[2]["solution_id"] or -1))
        sep,_,sol=ranked[0]
        diag=None
        if sol["fov1"] is not None and sol["fov2"] is not None:
            diag=math.hypot(sol["fov1"],sol["fov2"])
        assoc_plausible = True if diag is None else (sep <= max(1.0,0.75*diag))
        if not assoc_plausible:
            stats["solution_association_implausible"]+=1
            continue
        site=SITE_MAP.get(aid,"UNKNOWN")
        registry.append({
            "exposure_id":eid,"plate_id":pid,"archive_id":aid,"site_group":site,
            "start":st,"end":en,"ra":ra,"dec":dec,
            "exptime":fnum(r.get("exptime")),"flag_time":str(r.get("flag_time") or "").strip(),
            "num_sub":inum(r.get("num_sub")),"solution_id":sol["solution_id"],"scan_id":sol["scan_id"],
            "solution_assoc_sep_deg":sep,"fov1":sol["fov1"],"fov2":sol["fov2"],"polygon":sol["polygon"],
        })
        stats["usable"]+=1
        if site=="UNKNOWN":
            stats["usable_unknown_site"]+=1
    return registry,stats


def busko_pairs(registry):
    by_archive=defaultdict(list)
    for e in registry:
        by_archive[e["archive_id"]].append(e)
    pairs=[]
    index=defaultdict(list)
    counts=Counter()
    for aid,arr in sorted(by_archive.items()):
        arr.sort(key=lambda e:(e["start"],e["end"],e["exposure_id"]))
        log(f"Busko cadence scan archive {aid}: {len(arr)} usable exposures")
        for i,a in enumerate(arr):
            for j in range(i+1,len(arr)):
                b=arr[j]
                if (b["start"]-a["end"]).total_seconds() > CADENCE_MAX_S:
                    break
                if a["plate_id"]==b["plate_id"]:
                    continue
                gap,rel=interval_gap(a["start"],a["end"],b["start"],b["end"])
                if rel=="OVERLAPPING" or gap>CADENCE_MAX_S:
                    continue
                m=pair_overlap_metrics(a["polygon"],b["polygon"])
                if not m or m["area_intersection"]<=0:
                    continue
                counts["any_field_overlap"]+=1
                primary=m["fraction_smaller"]>=BUSKO_PRIMARY_FRAC
                if primary:
                    counts["primary_ge50"]+=1
                row={
                    "archive_id":aid,"site_group":a["site_group"],
                    "exposure_a":a["exposure_id"],"plate_a":a["plate_id"],
                    "start_a_utc":a["start"].isoformat(),"end_a_utc":a["end"].isoformat(),
                    "exposure_b":b["exposure_id"],"plate_b":b["plate_id"],
                    "start_b_utc":b["start"].isoformat(),"end_b_utc":b["end"].isoformat(),
                    "gap_seconds":f"{gap:.3f}","gap_minutes":f"{gap/60:.6f}",
                    "tier":tier(gap),"relation_b_to_a":rel,
                    "footprint_fraction_a":f"{m['fraction_a']:.8f}",
                    "footprint_fraction_b":f"{m['fraction_b']:.8f}",
                    "footprint_fraction_smaller":f"{m['fraction_smaller']:.8f}",
                    "busko_primary_ge50pct":primary,"chronological_rank_delta":j-i,
                }
                pairs.append(row)
                if primary:
                    index[a["exposure_id"]].append((b,gap,rel,m["fraction_smaller"]))
                    index[b["exposure_id"]].append((a,gap,"PRECEDING" if rel=="FOLLOWING" else "FOLLOWING",m["fraction_smaller"]))
    return pairs,index,counts


def cross_observatory_pairs(registry,busko_index):
    arr=sorted(registry,key=lambda e:(e["start"],e["end"],e["exposure_id"]))
    active=[]
    science=[]
    comparisons=[]
    counts=Counter()

    for idx,b in enumerate(arr,1):
        active=[a for a in active if a["end"]>b["start"]]
        for a in active:
            if a["site_group"]=="UNKNOWN" or b["site_group"]=="UNKNOWN":
                counts["unknown_site_skipped"]+=1
                continue
            if a["site_group"]==b["site_group"]:
                counts["same_site_temporal_overlap"]+=1
                continue
            ov_start=max(a["start"],b["start"])
            ov_end=min(a["end"],b["end"])
            if ov_end<=ov_start:
                continue
            counts["distinct_site_temporal_overlap"]+=1
            m=pair_overlap_metrics(a["polygon"],b["polygon"])
            if not m or m["area_intersection"]<=0:
                continue
            counts["distinct_site_space_time_overlap"]+=1

            if (a["site_group"],a["archive_id"],a["exposure_id"]) <= (b["site_group"],b["archive_id"],b["exposure_id"]):
                x,y=a,b
            else:
                x,y=b,a
            key=f"APPLAUSE:{x['exposure_id']} | APPLAUSE:{y['exposure_id']}"
            base={
                "canonical_pair":key,
                "site_a":x["site_group"],"archive_a":x["archive_id"],
                "exposure_a":x["exposure_id"],"plate_a":x["plate_id"],"scan_a":x["scan_id"],
                "start_a_utc":x["start"].isoformat(),"end_a_utc":x["end"].isoformat(),
                "site_b":y["site_group"],"archive_b":y["archive_id"],
                "exposure_b":y["exposure_id"],"plate_b":y["plate_id"],"scan_b":y["scan_id"],
                "start_b_utc":y["start"].isoformat(),"end_b_utc":y["end"].isoformat(),
                "physical_overlap_start_utc":ov_start.isoformat(),
                "physical_overlap_end_utc":ov_end.isoformat(),
                "physical_overlap_seconds":f"{(ov_end-ov_start).total_seconds():.3f}",
                "science_footprint_fraction_a":f"{m['fraction_a']:.8f}",
                "science_footprint_fraction_b":f"{m['fraction_b']:.8f}",
                "science_footprint_fraction_smaller":f"{m['fraction_smaller']:.8f}",
            }

            comp_rows=[]
            for label,endpoint in (("A",x),("B",y)):
                for comp,_,_,field_frac in busko_index.get(endpoint["exposure_id"],[]):
                    g,relation=interval_gap(endpoint["start"],endpoint["end"],comp["start"],comp["end"])
                    if relation=="OVERLAPPING" or g<=0 or g>CADENCE_MAX_S:
                        continue
                    cover=triple_common_coverage(x["polygon"],y["polygon"],comp["polygon"])
                    if cover<=0:
                        continue
                    cr={
                        "canonical_pair":key,"comparison_for_endpoint":label,
                        "positive_exposure_id":endpoint["exposure_id"],"positive_plate_id":endpoint["plate_id"],
                        "comparison_exposure_id":comp["exposure_id"],"comparison_plate_id":comp["plate_id"],
                        "comparison_scan_id":comp["scan_id"],"comparison_start_utc":comp["start"].isoformat(),
                        "comparison_end_utc":comp["end"].isoformat(),"endpoint_interval_gap_seconds":f"{g:.3f}",
                        "endpoint_interval_gap_minutes":f"{g/60:.6f}","tier":tier(g),
                        "temporal_relation":relation,
                        "endpoint_pair_field_overlap_fraction_smaller":f"{field_frac:.8f}",
                        "comparison_coverage_fraction_of_science_common_footprint":f"{cover:.8f}",
                        "primary_common_coverage_ge50pct":cover>=COMPARISON_COMMON_COVER_FRAC,
                    }
                    comp_rows.append(cr)
                    comparisons.append(cr)

            prim=[r for r in comp_rows if r["primary_common_coverage_ge50pct"]]
            prim.sort(key=lambda r:(float(r["endpoint_interval_gap_seconds"]),r["comparison_exposure_id"]))
            anyc=sorted(comp_rows,key=lambda r:(float(r["endpoint_interval_gap_seconds"]),r["comparison_exposure_id"]))
            chosen=prim[0] if prim else None
            chosen_any=anyc[0] if anyc else None
            s=dict(base)
            s.update({
                "primary_comparison_count_ge50pct_common":len(prim),
                "any_partial_comparison_count":len(anyc),
                "best_primary_comparison_endpoint":"" if not chosen else chosen["comparison_for_endpoint"],
                "best_primary_comparison_exposure":"" if not chosen else chosen["comparison_exposure_id"],
                "best_primary_comparison_gap_minutes":"" if not chosen else chosen["endpoint_interval_gap_minutes"],
                "best_primary_comparison_tier":"" if not chosen else chosen["tier"],
                "best_any_comparison_gap_minutes":"" if not chosen_any else chosen_any["endpoint_interval_gap_minutes"],
                "best_any_comparison_tier":"" if not chosen_any else chosen_any["tier"],
            })
            science.append(s)

        active.append(b)
        if idx % 10000 == 0:
            log(f"Cross-site sweep: {idx}/{len(arr)} exposures; active={len(active)}; space-time pairs={len(science)}")

    return science,comparisons,counts


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--resume",action="store_true")
    _=ap.parse_args()

    WORK.mkdir(parents=True,exist_ok=True)
    CACHE.mkdir(parents=True,exist_ok=True)
    STATE.mkdir(parents=True,exist_ok=True)
    RESULT.mkdir(parents=True,exist_ok=True)

    log("="*110)
    log("APPLAUSE DR4 — BUSKO-FIRST CROSS-OBSERVATORY OPPORTUNITY CENSUS v093")
    log("="*110)
    log("Metadata-only opportunity selection. NO source catalogues, NO pixels, NO detector, NO candidate outcomes.")
    log("Primary cadence gap = actual positive-endpoint exposure interval to independent comparison exposure interval.")
    log("Tiers frozen: <=30 min, >30-60 min, >60-120 min.")
    log("")

    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v093 contract missing or SHA mismatch")

    started=now_utc()
    query_files={}
    expected={
        "archive":["archive_id"],"exposure":["exposure_id"],
        "scan":["scan_id"],"solution":["solution_id","stc_polygon"],
    }
    for name in ("archive","exposure","scan","solution"):
        query_files[name]=tap_query(name,QUERIES[name],expected[name])

    archives,archive_ids=load_archives(query_files["archive"])
    log(f"Archive rows: {len(archives)}; unique archive IDs: {len(archive_ids)}")
    if len(archive_ids)!=27:
        log(f"WARNING: expected 27 APPLAUSE DR4 archive IDs; observed {len(archive_ids)}. Continuing with explicit warning.")

    scans=load_scans(query_files["scan"])
    log(f"Physical plates with scan rows: {len(scans)}")
    solutions,bad_poly=load_solutions(query_files["solution"],scans)
    log(f"Physical plates with usable STC solution polygons: {len(solutions)}; bad polygon rows skipped={bad_poly}")

    registry,regstats=build_exposure_registry(query_files["exposure"],scans,solutions)
    log(f"Digitally usable exposure registry: {len(registry)}")
    log(f"Registry stats: {dict(regstats)}")

    reg_rows=[]
    for e in registry:
        reg_rows.append({
            "exposure_id":e["exposure_id"],"plate_id":e["plate_id"],"archive_id":e["archive_id"],
            "site_group":e["site_group"],"start_utc":e["start"].isoformat(),"end_utc":e["end"].isoformat(),
            "duration_seconds":f"{(e['end']-e['start']).total_seconds():.3f}",
            "ra_icrs":f"{e['ra']:.10f}","dec_icrs":f"{e['dec']:.10f}",
            "scan_id":e["scan_id"],"solution_id":e["solution_id"],
            "solution_assoc_sep_deg":f"{e['solution_assoc_sep_deg']:.8f}",
            "fov1_deg":"" if e["fov1"] is None else f"{e['fov1']:.8f}",
            "fov2_deg":"" if e["fov2"] is None else f"{e['fov2']:.8f}",
            "flag_time":e["flag_time"],"num_sub":e["num_sub"],
        })
    write_csv(
        RESULT/"applause_dr4_digitally_usable_exposure_registry_v093.csv",reg_rows,
        ["exposure_id","plate_id","archive_id","site_group","start_utc","end_utc","duration_seconds",
         "ra_icrs","dec_icrs","scan_id","solution_id","solution_assoc_sep_deg","fov1_deg","fov2_deg",
         "flag_time","num_sub"]
    )

    busko,busko_index,bcounts=busko_pairs(registry)
    log(f"Within-archive short-cadence sky-overlap pairs: {len(busko)}; counts={dict(bcounts)}")
    write_csv(
        RESULT/"applause_dr4_within_archive_busko_opportunities_v093.csv",busko,
        ["archive_id","site_group","exposure_a","plate_a","start_a_utc","end_a_utc",
         "exposure_b","plate_b","start_b_utc","end_b_utc","gap_seconds","gap_minutes","tier",
         "relation_b_to_a","footprint_fraction_a","footprint_fraction_b","footprint_fraction_smaller",
         "busko_primary_ge50pct","chronological_rank_delta"]
    )

    science,comparisons,ccounts=cross_observatory_pairs(registry,busko_index)
    log(f"Cross-observatory space-time footprint pairs: {len(science)}; sweep counts={dict(ccounts)}")
    write_csv(
        RESULT/"applause_dr4_cross_observatory_space_time_opportunities_v093.csv",science,
        ["canonical_pair","site_a","archive_a","exposure_a","plate_a","scan_a","start_a_utc","end_a_utc",
         "site_b","archive_b","exposure_b","plate_b","scan_b","start_b_utc","end_b_utc",
         "physical_overlap_start_utc","physical_overlap_end_utc","physical_overlap_seconds",
         "science_footprint_fraction_a","science_footprint_fraction_b","science_footprint_fraction_smaller",
         "primary_comparison_count_ge50pct_common","any_partial_comparison_count",
         "best_primary_comparison_endpoint","best_primary_comparison_exposure",
         "best_primary_comparison_gap_minutes","best_primary_comparison_tier",
         "best_any_comparison_gap_minutes","best_any_comparison_tier"]
    )
    write_csv(
        RESULT/"applause_dr4_cross_observatory_short_lag_comparisons_v093.csv",comparisons,
        ["canonical_pair","comparison_for_endpoint","positive_exposure_id","positive_plate_id",
         "comparison_exposure_id","comparison_plate_id","comparison_scan_id",
         "comparison_start_utc","comparison_end_utc","endpoint_interval_gap_seconds",
         "endpoint_interval_gap_minutes","tier","temporal_relation",
         "endpoint_pair_field_overlap_fraction_smaller",
         "comparison_coverage_fraction_of_science_common_footprint","primary_common_coverage_ge50pct"]
    )

    primary=[s for s in science if s["best_primary_comparison_tier"]]
    tier_counts=Counter(s["best_primary_comparison_tier"] for s in primary)
    archive_pairs=Counter(f"{s['archive_a']}|{s['archive_b']}" for s in science)
    site_pairs=Counter(" | ".join(sorted((s["site_a"],s["site_b"]))) for s in science)
    ranked=sorted(primary,key=lambda s:(
        {"A_LE30MIN":0,"B_GT30_LE60MIN":1,"C_GT60_LE120MIN":2}.get(s["best_primary_comparison_tier"],9),
        float(s["best_primary_comparison_gap_minutes"] or 1e99),
        -float(s["physical_overlap_seconds"]),s["canonical_pair"]
    ))
    rank_rows=[]
    for i,s in enumerate(ranked,1):
        r=dict(s); r["rank"]=i; rank_rows.append(r)
    write_csv(
        RESULT/"applause_dr4_ranked_cross_observatory_fast_transient_opportunities_v093.csv",rank_rows,
        ["rank","canonical_pair","site_a","archive_a","exposure_a","plate_a","site_b","archive_b",
         "exposure_b","plate_b","physical_overlap_seconds","science_footprint_fraction_smaller",
         "best_primary_comparison_endpoint","best_primary_comparison_exposure",
         "best_primary_comparison_gap_minutes","best_primary_comparison_tier",
         "primary_comparison_count_ge50pct_common","any_partial_comparison_count"]
    )

    archive_summary=[]
    busko_by_archive=Counter(r["archive_id"] for r in busko if str(r["busko_primary_ge50pct"]).lower() in {"true","1"})
    usable_by_archive=Counter(e["archive_id"] for e in registry)
    cross_by_archive=Counter()
    ranked_by_archive=Counter()
    for s in science:
        cross_by_archive[s["archive_a"]]+=1; cross_by_archive[s["archive_b"]]+=1
    for s in primary:
        ranked_by_archive[s["archive_a"]]+=1; ranked_by_archive[s["archive_b"]]+=1
    meta_by_id={r["archive_id"]:r for r in archives}
    for aid in sorted(archive_ids):
        m=meta_by_id[aid]
        archive_summary.append({
            "archive_id":aid,"archive_name":m["archive_name"],"institute":m["institute"],
            "site_group":m["site_group"],"declared_num_plates":m["num_plates"],"declared_num_scans":m["num_scans"],
            "usable_exposures":usable_by_archive[aid],"busko_primary_short_cadence_pairs":busko_by_archive[aid],
            "cross_observatory_space_time_pairs_touching_archive":cross_by_archive[aid],
            "ranked_short_lag_cross_observatory_pairs_touching_archive":ranked_by_archive[aid],
            "independence_eligible":m["site_group"]!="UNKNOWN",
        })
    write_csv(
        RESULT/"applause_dr4_archive_coverage_summary_v093.csv",archive_summary,
        ["archive_id","archive_name","institute","site_group","declared_num_plates","declared_num_scans",
         "usable_exposures","busko_primary_short_cadence_pairs",
         "cross_observatory_space_time_pairs_touching_archive",
         "ranked_short_lag_cross_observatory_pairs_touching_archive","independence_eligible"]
    )

    report={
        "status":"COMPLETE",
        "analysis_kind":"applause_dr4_busko_first_cross_observatory_opportunity_census_v093",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "started_utc":started,"completed_utc":now_utc(),
        "scope":"APPLAUSE DR4 all archive collections returned by archive table",
        "source_detection_inspected":False,"pixels_inspected":False,"candidate_outcomes_inspected":False,
        "archive_count_observed":len(archive_ids),"archive_count_expected":27,
        "registry_stats":dict(regstats),"usable_exposure_count":len(registry),
        "within_archive_busko_pair_count_any_overlap":len(busko),"within_archive_busko_counts":dict(bcounts),
        "cross_observatory_sweep_counts":dict(ccounts),
        "cross_observatory_space_time_pair_count":len(science),
        "cross_observatory_pairs_with_primary_short_lag_comparison":len(primary),
        "best_primary_comparison_tier_counts":dict(tier_counts),
        "site_pair_counts":dict(site_pairs),"archive_pair_counts":dict(archive_pairs),
        "top_25_ranked_opportunities":[
            {
                "rank":i+1,"canonical_pair":s["canonical_pair"],"sites":[s["site_a"],s["site_b"]],
                "archives":[s["archive_a"],s["archive_b"]],
                "physical_overlap_seconds":s["physical_overlap_seconds"],
                "comparison_endpoint":s["best_primary_comparison_endpoint"],
                "comparison_exposure":s["best_primary_comparison_exposure"],
                "comparison_gap_minutes":s["best_primary_comparison_gap_minutes"],
                "tier":s["best_primary_comparison_tier"],
            } for i,s in enumerate(ranked[:25])
        ],
        "tap_cache":{
            name:{
                "path":str(path.relative_to(ROOT)).replace("\\","/"),
                "sha256":sha(path),"size_bytes":path.stat().st_size
            } for name,path in query_files.items()
        },
        "output_hashes":{},
        "guards":{
            "source_catalog_queries":0,"pixel_downloads":0,"fits_pixel_reads":0,
            "detector_runs":0,"candidate_adjudication":0,"candidate_disposition_changes":0
        }
    }
    for p in sorted(RESULT.glob("*.csv")):
        report["output_hashes"][p.name]=sha(p)
    report_path=RESULT/"applause_dr4_busko_first_cross_observatory_opportunity_census_v093.json"
    write_json(report_path,report)

    log("")
    log("="*110)
    log("v093 APPLAUSE DR4 OPPORTUNITY CENSUS COMPLETE")
    log("="*110)
    log(f"Usable exposures: {len(registry)}")
    log(f"Busko-primary same-archive cadence pairs: {bcounts.get('primary_ge50',0)}")
    log(f"Cross-observatory space-time pairs: {len(science)}")
    log(f"Cross-observatory pairs with >=50% common-field short-lag comparison: {len(primary)}")
    log(f"Best comparison tier counts: {dict(tier_counts)}")
    for i,s in enumerate(ranked[:20],1):
        log(
            f"TOP {i:02d} {s['canonical_pair']} {s['site_a']} / {s['site_b']} "
            f"overlap={s['physical_overlap_seconds']}s "
            f"comparison={s['best_primary_comparison_gap_minutes']}min {s['best_primary_comparison_tier']}"
        )
    log(f"Report: {report_path}")
    log("STAGE STATUS: COMPLETE")


if __name__=="__main__":
    main()
