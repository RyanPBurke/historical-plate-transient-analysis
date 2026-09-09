#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from bisect import bisect_right
import argparse, csv, hashlib, json, math, os, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT/"research"/"prospective_freezes"/"v094v_source_free_site_reference_acquisition_repair_contract.json"
EXPECTED_CONTRACT_SHA = "8f0f40b58027ba5f1b006648304ab7e40a6cc38de5c8d290e0b3d2007848cdf8"
V094T_DIR = ROOT/"results"/"applause_dr4_source_free_opportunity_population_repair_v094t"
V094T_CSV = V094T_DIR/"applause_dr4_source_free_cross_site_opportunities_v094t.csv"
V094T_MANIFEST = V094T_DIR/"v094t_output_manifest.sha256"
V094U_DIR = ROOT/"results"/"applause_dr4_v094u_site_reference_coverage_preflight"
V094U_REPORT = V094U_DIR/"v094u_site_reference_coverage_preflight.json"
V094U_MANIFEST = V094U_DIR/"v094u_output_manifest.sha256"
V094S_PROV = ROOT/"research"/"prospective_freezes"/"v094s_source_free_opportunity_population_parent_provenance.json"
RESULT = ROOT/"work"/"applause_dr4_v094v_site_reference_acquisition"

APPLAUSE_URL = "https://www.plate-archive.org/tap/sync"
DELTAT_URL = "https://maia.usno.navy.mil/ser7/deltat.data"
MISSING = {
    "Calar Alto Observatory, Spain": 12,
    "La Silla, Chile": 11,
    "Observatorio de Fisica Cosmica, San Miguel, Argentina": 24,
}
EPS_DEG=1e-9

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        yield from csv.DictReader(f)

def fnum(v):
    try:
        x=float(str(v).strip())
        return x if math.isfinite(x) else None
    except:return None

def inum(v):
    x=fnum(v)
    if x is None:return None
    q=int(round(x));return q if abs(x-q)<1e-9 else None

def parse_dt(v):
    s=str(v or "").strip().replace("Z","+00:00")
    if not s:return None
    d=datetime.fromisoformat(s)
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def localname(tag): return str(tag).split("}")[-1]

def manifest_check(manifest,base):
    seen={}
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2:continue
        digest,name=q[0].lower(),q[1].strip()
        p=Path(base)/name
        if not p.is_file() or sha(p)!=digest:
            raise SystemExit(f"Parent manifest HOLD: {name}")
        seen[name]=digest
    return seen

def post_form(url,params,timeout=90,attempts=4):
    data=urllib.parse.urlencode(params).encode("ascii")
    last=None
    for i in range(attempts):
        try:
            req=urllib.request.Request(url,data=data,method="POST",
                headers={"Content-Type":"application/x-www-form-urlencoded",
                         "User-Agent":"historical-plate-transient-analysis/v094v"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                body=r.read();status=getattr(r,"status",200);headers=dict(r.headers.items())
            if status!=200:raise RuntimeError(f"HTTP {status}")
            return status,headers,body
        except Exception as e:
            last=e
            if i+1<attempts:time.sleep((2,5,10)[min(i,2)])
    raise RuntimeError(f"POST failed after {attempts} attempts: {last}")

def get_bytes(url,timeout=90,attempts=4):
    last=None
    for i in range(attempts):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"historical-plate-transient-analysis/v094v"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                body=r.read();status=getattr(r,"status",200);headers=dict(r.headers.items())
            if status!=200:raise RuntimeError(f"HTTP {status}")
            return status,headers,body
        except Exception as e:
            last=e
            if i+1<attempts:time.sleep((2,5,10)[min(i,2)])
    raise RuntimeError(f"GET failed after {attempts} attempts: {last}")

def parse_votable_tabledata(body):
    root=ET.fromstring(body)
    statuses=[]
    for el in root.iter():
        if localname(el.tag)=="INFO" and str(el.attrib.get("name","")).upper()=="QUERY_STATUS":
            statuses.append(str(el.attrib.get("value","")).upper())
    if not statuses or "ERROR" in statuses or "OVERFLOW" in statuses or statuses[-1]!="OK":
        raise RuntimeError(f"TAP QUERY_STATUS HOLD: {statuses}")
    table=None
    for el in root.iter():
        if localname(el.tag)=="TABLE":
            table=el;break
    if table is None:raise RuntimeError("No TABLE in VOTable")
    fields=[str(el.attrib.get("name") or el.attrib.get("ID") or "").strip()
            for el in table if localname(el.tag)=="FIELD"]
    if not fields:raise RuntimeError("No FIELD definitions in VOTable")
    needed={"plate_id","site_name","site_longitude","site_latitude","site_elevation"}
    if not needed.issubset(set(fields)):
        raise RuntimeError(f"VOTable missing columns: {sorted(needed-set(fields))}")
    tabledata=None
    for el in table.iter():
        if localname(el.tag)=="TABLEDATA":
            tabledata=el;break
    if tabledata is None:raise RuntimeError("VOTable is not TABLEDATA serialization")
    out=[]
    for tr in tabledata:
        if localname(tr.tag)!="TR":continue
        vals=[(td.text or "").strip() for td in tr if localname(td.tag)=="TD"]
        if len(vals)!=len(fields):raise RuntimeError("VOTable row/field length mismatch")
        d=dict(zip(fields,vals));out.append({k:d.get(k) for k in needed})
    return out,statuses

def parse_monthly_deltat(text):
    rec=[]
    for line in text.splitlines():
        q=line.split()
        if len(q)<4:continue
        try:
            y,m,d=int(q[0]),int(q[1]),int(q[2]);v=float(q[3])
            dt=datetime(y,m,d,tzinfo=timezone.utc)
        except:continue
        if not math.isfinite(v):raise RuntimeError("Non-finite monthly DeltaT")
        rec.append((dt,v))
    if len(rec)<200:raise RuntimeError(f"Monthly DeltaT parse too small: {len(rec)}")
    dates=[d for d,_ in rec]
    if len(set(dates))!=len(dates) or dates!=sorted(dates):
        raise RuntimeError("Monthly DeltaT dates not unique/strictly increasing")
    return rec

def parse_historic_deltat(p):
    rec=[]
    for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
        q=line.split()
        if len(q)<3:continue
        try:y=float(q[0]);v=float(q[1])
        except:continue
        if math.isfinite(y) and math.isfinite(v):rec.append((y,v))
    if len(rec)<500:raise RuntimeError("Historic DeltaT parse too small")
    rec.sort()
    return rec

def decimal_year(d):
    a=datetime(d.year,1,1,tzinfo=timezone.utc);b=datetime(d.year+1,1,1,tzinfo=timezone.utc)
    return d.year+(d-a).total_seconds()/(b-a).total_seconds()

def interp_pairs(rec,x):
    xs=[a for a,_ in rec]
    if x<xs[0] or x>xs[-1]:return None
    j=bisect_right(xs,x)
    if j==0:return rec[0][1]
    if j>=len(rec):return rec[-1][1]
    x0,y0=rec[j-1];x1,y1=rec[j]
    if x1==x0:return y0
    return y0+(y1-y0)*(x-x0)/(x1-x0)

def self_test():
    xml=b"""<?xml version="1.0"?><VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
    <RESOURCE><INFO name="QUERY_STATUS" value="OK"/><TABLE>
    <FIELD name="plate_id" datatype="int"/><FIELD name="site_name" datatype="char" arraysize="*"/>
    <FIELD name="site_longitude" datatype="double"/><FIELD name="site_latitude" datatype="double"/>
    <FIELD name="site_elevation" datatype="float"/>
    <DATA><TABLEDATA><TR><TD>1</TD><TD>X</TD><TD>2.0</TD><TD>3.0</TD><TD>4.0</TD></TR></TABLEDATA></DATA>
    </TABLE></RESOURCE></VOTABLE>"""
    rr,st=parse_votable_tabledata(xml)
    assert st[-1]=="OK" and inum(rr[0]["plate_id"])==1 and fnum(rr[0]["site_elevation"])==4.0
    synthetic=[]
    for i in range(240):
        y=1973+i//12;m=i%12+1
        synthetic.append(f"{y:04d} {m:02d} 1 {43+i/100:.4f}")
    mm=parse_monthly_deltat("\n".join(synthetic))
    assert len(mm)==240
    assert abs(interp_pairs([(1.0,2.0),(2.0,4.0)],1.5)-3.0)<1e-12
    print("v094v acquisition self-test PASS")
    return 0

def validate_existing_result():
    if not RESULT.is_dir():return False
    report=RESULT/"v094v_acquisition_report.json"
    manifest=RESULT/"v094v_acquisition_manifest.sha256"
    if not report.is_file() or not manifest.is_file():
        raise SystemExit("Existing v094v final directory is incomplete; preserve and inspect manually")
    manifest_check(manifest,RESULT)
    q=json.loads(report.read_text(encoding="utf-8"))
    if q.get("status")!="COMPLETE" or q.get("outcome")!="ACQUISITION_COMPLETE_READY_FOR_COVERAGE_REPLAY":
        raise SystemExit("Existing v094v final directory report is not complete")
    print("Reusing already completed and manifest-validated v094v acquisition.")
    return True

def run(repo_root,contract_freeze_commit):
    repo_root=Path(repo_root).resolve()
    r3b_hist=repo_root/"pipeline_v0.2.0"/"research"/"prospective_freezes"/"v094r3b_historical_geometry_validation"/"inputs"/"acquisition"/"references"/"historic_deltat.data"
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("v094v contract SHA mismatch")
    if validate_existing_result():return 0
    for p in (V094T_CSV,V094T_MANIFEST,V094U_REPORT,V094U_MANIFEST,V094S_PROV,r3b_hist):
        if not p.is_file():raise SystemExit(f"Missing required parent input: {p}")
    manifest_check(V094T_MANIFEST,V094T_DIR);manifest_check(V094U_MANIFEST,V094U_DIR)
    u=json.loads(V094U_REPORT.read_text(encoding="utf-8"))
    if u.get("outcome")!="SITE_OR_REFERENCE_ACQUISITION_REQUIRED":raise SystemExit("v094u outcome replay HOLD")
    if set(u.get("missing_or_ambiguous_sites") or [])!=set(MISSING):raise SystemExit("v094u missing-site set replay HOLD")
    if u["parent_v094t"]["overlap_utc_max"]!="1992-11-25T04:50:00+00:00":raise SystemExit("v094u overlap maximum replay HOLD")

    prov=json.loads(V094S_PROV.read_text(encoding="utf-8"))
    cache_rec=(prov.get("inputs") or {}).get("plate_site_cache")
    if not cache_rec:raise SystemExit("v094s provenance missing plate_site_cache")
    cache_path=ROOT/cache_rec["path"]
    if not cache_path.is_file() or sha(cache_path)!=str(cache_rec["sha256"]).lower():raise SystemExit("v094s frozen plate cache hash HOLD")
    cache={}
    for r in rows(cache_path):
        pid=inum(r.get("plate_id"))
        if pid is not None:cache[pid]=(str(r.get("site_name") or "").strip(),fnum(r.get("site_longitude")),fnum(r.get("site_latitude")))

    required=defaultdict(set)
    for r in rows(V094T_CSV):
        if str(r.get("timing_bin") or "")!="OVERLAP":continue
        for suff in ("a","b"):
            site=str(r.get(f"site_{suff}") or "").strip()
            if site in MISSING:
                pid=inum(r.get(f"plate_{suff}"))
                if pid is None:raise SystemExit("Missing plate id in v094t repair selection")
                required[site].add(pid)
    counts={s:len(required[s]) for s in MISSING}
    if counts!=MISSING or sum(counts.values())!=47:raise SystemExit(f"Exact repair plate-set replay HOLD: {counts}")

    expected_by_plate={}
    for site,pids in required.items():
        for pid in pids:
            c=cache.get(pid)
            if c is None:raise SystemExit(f"Required plate missing frozen cache: {pid}")
            if c[0]!=site:raise SystemExit(f"Frozen cache site mismatch for {pid}: {c[0]} != {site}")
            if c[1] is None or c[2] is None:raise SystemExit(f"Frozen cache coordinate missing for {pid}")
            expected_by_plate[pid]=(site,c[1],c[2])

    stage=RESULT.parent/(RESULT.name+".__staging__."+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"."+str(os.getpid()))
    stage.mkdir(parents=True,exist_ok=False)

    ids=sorted(expected_by_plate)
    query=("SELECT plate_id,site_name,site_longitude,site_latitude,site_elevation FROM applause_dr4.plate "
           "WHERE plate_id IN ("+",".join(map(str,ids))+") ORDER BY plate_id")
    params={"REQUEST":"doQuery","LANG":"ADQL","MAXREC":str(len(ids)+1),"QUERY":query}
    try:status,headers,body=post_form(APPLAUSE_URL,params)
    except Exception as e:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: {e}")
    (stage/"applause_response.vot").write_bytes(body)
    request_meta={"url":APPLAUSE_URL,"method":"POST","retrieved_utc":datetime.now(timezone.utc).isoformat(),
                  "parameters":params,"requested_plate_ids":ids,"response_status":status,
                  "response_headers":headers,"response_sha256":hashlib.sha256(body).hexdigest()}
    (stage/"applause_request.json").write_text(json.dumps(request_meta,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    try:rr,statuses=parse_votable_tabledata(body)
    except Exception as e:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: {e}")

    seen={};plate_rows=[];by_site=defaultdict(set)
    for x in rr:
        pid=inum(x["plate_id"]);site=str(x["site_name"] or "").strip()
        lon=fnum(x["site_longitude"]);lat=fnum(x["site_latitude"]);elev=fnum(x["site_elevation"])
        if None in (pid,lon,lat,elev) or not site:raise SystemExit("APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: null/invalid row")
        if pid in seen:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: duplicate plate {pid}")
        seen[pid]=1
        if pid not in expected_by_plate:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: extra plate {pid}")
        es,elon,elat=expected_by_plate[pid]
        if site!=es:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: site mismatch {pid}: {site} != {es}")
        if abs(lon-elon)>EPS_DEG or abs(lat-elat)>EPS_DEG:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: lon/lat mismatch {pid}")
        by_site[site].add((lon,lat,elev))
        plate_rows.append({"plate_id":pid,"site_name":site,"site_longitude":lon,"site_latitude":lat,"site_elevation_m":elev})
    if set(seen)!=set(ids):raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: returned ID set mismatch missing={sorted(set(ids)-set(seen))}")

    site_rows=[]
    for site in sorted(MISSING):
        tuples=by_site.get(site,set())
        if len(tuples)!=1:raise SystemExit(f"APPLAUSE_SITE_METADATA_ACQUISITION_HOLD: {site} has {len(tuples)} metadata tuples")
        lon,lat,elev=next(iter(tuples))
        site_rows.append({"site_name":site,"site_longitude":lon,"site_latitude":lat,"site_elevation_m":elev,
                          "required_plate_count":len(required[site])})
    with (stage/"applause_acquired_plate_site_metadata.csv").open("w",encoding="utf-8",newline="") as f:
        fields=["plate_id","site_name","site_longitude","site_latitude","site_elevation_m"];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(plate_rows,key=lambda r:r["plate_id"]))
    with (stage/"applause_acquired_site_metadata.csv").open("w",encoding="utf-8",newline="") as f:
        fields=["site_name","site_longitude","site_latitude","site_elevation_m","required_plate_count"];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(site_rows)

    try:ds,dheaders,dbytes=get_bytes(DELTAT_URL)
    except Exception as e:raise SystemExit(f"DELTAT_ACQUISITION_OR_COMPATIBILITY_HOLD: {e}")
    (stage/"deltat.data").write_bytes(dbytes)
    try:monthly=parse_monthly_deltat(dbytes.decode("ascii","strict"))
    except Exception as e:raise SystemExit(f"DELTAT_ACQUISITION_OR_COMPATIBILITY_HOLD: {e}")
    if monthly[-1][0]<datetime(1992,12,1,tzinfo=timezone.utc):raise SystemExit("DELTAT_ACQUISITION_OR_COMPATIBILITY_HOLD: monthly domain does not cover required 1992 endpoint")

    historic=parse_historic_deltat(r3b_hist);diffs=[]
    for d,v in monthly:
        y=decimal_year(d)
        if 1973.0<=y<=1984.5:
            pred=interp_pairs(historic,y)
            if pred is not None:diffs.append(abs(v-pred))
    if not diffs or max(diffs)>0.1:raise SystemExit(f"DELTAT_ACQUISITION_OR_COMPATIBILITY_HOLD: historic/monthly gross compatibility max={max(diffs) if diffs else None}")
    dmeta={"url":DELTAT_URL,"method":"GET","retrieved_utc":datetime.now(timezone.utc).isoformat(),
           "response_status":ds,"response_headers":dheaders,"sha256":hashlib.sha256(dbytes).hexdigest(),
           "size_bytes":len(dbytes),"records":len(monthly),"first_date":monthly[0][0].date().isoformat(),
           "last_date":monthly[-1][0].date().isoformat(),"required_overlap_max":"1992-11-25T04:50:00+00:00",
           "historic_overlap_max_abs_difference_seconds":max(diffs),"uncertainty_column_available":False}
    (stage/"deltat_request.json").write_text(json.dumps(dmeta,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    report={
        "status":"COMPLETE","outcome":"ACQUISITION_COMPLETE_READY_FOR_COVERAGE_REPLAY",
        "analysis_kind":"v094v_source_free_site_reference_acquisition_repair",
        "contract_sha256":EXPECTED_CONTRACT_SHA,"contract_freeze_commit":contract_freeze_commit,
        "selection":{"sites":MISSING,"required_plate_count":47,"requested_plate_ids":ids},
        "applause":{"query_status":statuses,"returned_rows":len(rr),"unique_plate_ids":len(seen),
                    "site_metadata_rows":site_rows,"response_sha256":hashlib.sha256(body).hexdigest()},
        "deltat":dmeta,
        "unchanged_reference":{"iers_c01_sha256":"846cb53ae1055de1cd80ab78e065b05ad0bc3b224bf8eafe27f428eb12da3ffb","reacquired":False},
        "guards":{"source_catalog_reads":0,"candidate_identity_inspection":0,"private_candidate_map_reads":0,
                  "pixels":0,"registration":0,"real_source_pairing":0,"finite_distance_geometry":0,
                  "distance_grid_evaluation":0,"threshold_retuning":0,
                  "network_hosts_used":["www.plate-archive.org","maia.usno.navy.mil"]},
        "next_stage":"Freeze coverage/reuse replay combining 7 inherited r3b sites + 3 acquired sites and historic+monthly DeltaT; no geometry yet."
    }
    rp=stage/"v094v_acquisition_report.json";rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    files=sorted([p for p in stage.iterdir() if p.is_file() and p.name!="v094v_acquisition_manifest.sha256"],key=lambda p:p.name)
    mp=stage/"v094v_acquisition_manifest.sha256";mp.write_text("".join(f"{sha(p)}  {p.name}\n" for p in files),encoding="utf-8")
    if RESULT.exists():raise SystemExit("v094v final output appeared before atomic publication")
    os.replace(stage,RESULT)

    print("\n"+"="*108)
    print("v094v SOURCE-FREE SITE / REFERENCE ACQUISITION COMPLETE")
    print("="*108)
    print("Outcome:                                      ACQUISITION_COMPLETE_READY_FOR_COVERAGE_REPLAY")
    print(f"APPLAUSE required / returned plates:          47 / {len(rr)}")
    print(f"Repaired sites:                               {len(site_rows)}")
    for r in site_rows:print(f"  {r['site_name']}: {r['required_plate_count']} plates; elevation={r['site_elevation_m']} m")
    print(f"Monthly DeltaT records/domain:                {len(monthly)} / {monthly[0][0].date()} .. {monthly[-1][0].date()}")
    print(f"Historic/monthly max compatibility diff:      {max(diffs):.6f} s")
    print("IERS C01 reacquired:                          False")
    print("Source catalogues / identities / geometry:    0 / 0 / 0")
    print("STOP: exact acquisition inputs must be banked, then coverage replay frozen.")
    return 0

def verify_copy(src,dst):
    src=Path(src);dst=Path(dst)
    manifest=src/"v094v_acquisition_manifest.sha256"
    if not manifest.is_file():raise SystemExit("Source acquisition manifest missing")
    expected={}
    for line in manifest.read_text().splitlines():
        q=line.strip().split(None,1)
        if len(q)==2:expected[q[1]]=q[0].lower()
    for name,digest in expected.items():
        p=dst/name
        if not p.is_file() or sha(p)!=digest:raise SystemExit(f"Bank-copy verification HOLD: {name}")
    dm=dst/"v094v_acquisition_manifest.sha256"
    if not dm.is_file() or dm.read_bytes()!=manifest.read_bytes():raise SystemExit("Bank manifest byte mismatch")
    actual={p.name for p in dst.iterdir() if p.is_file()};want=set(expected)|{"v094v_acquisition_manifest.sha256"}
    if actual!=want:raise SystemExit(f"Bank-copy file-set HOLD: {sorted(actual ^ want)}")
    print("v094v bank-copy hash/file-set verification PASS")
    return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");ap.add_argument("--repo-root");ap.add_argument("--contract-freeze-commit");ap.add_argument("--verify-copy",nargs=2,metavar=("SRC","DST"))
    a=ap.parse_args()
    if a.self_test:return self_test()
    if a.verify_copy:return verify_copy(*a.verify_copy)
    if not a.repo_root or not a.contract_freeze_commit:raise SystemExit("--repo-root and --contract-freeze-commit required")
    return run(a.repo_root,a.contract_freeze_commit)

if __name__=="__main__":raise SystemExit(main())
