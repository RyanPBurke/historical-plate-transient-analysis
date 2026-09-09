#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
from bisect import bisect_right
import argparse, csv, hashlib, json, math, os

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"v094w_source_free_full_site_reference_coverage_replay_contract.json"
EXPECTED_CONTRACT_SHA="4eb09aabcbe6ba6ad0481c2f33afc2f0978b635aeb66cbd74dc0e195243ff3f2"
V094T=ROOT/"results"/"applause_dr4_source_free_opportunity_population_repair_v094t"
V094T_CSV=V094T/"applause_dr4_source_free_cross_site_opportunities_v094t.csv"
V094T_REPORT=V094T/"applause_dr4_source_free_opportunity_population_repair_v094t.json"
V094T_MANIFEST=V094T/"v094t_output_manifest.sha256"
V094U=ROOT/"results"/"applause_dr4_v094u_site_reference_coverage_preflight"
V094U_REPORT=V094U/"v094u_site_reference_coverage_preflight.json"
V094U_MANIFEST=V094U/"v094u_output_manifest.sha256"
V094S_PROV=ROOT/"research"/"prospective_freezes"/"v094s_source_free_opportunity_population_parent_provenance.json"
RESULT=ROOT/"results"/"applause_dr4_v094w_full_site_reference_coverage_replay"

R3B_REL=Path("pipeline_v0.2.0/research/prospective_freezes/v094r3b_historical_geometry_validation")
R3B_PLATE_REL=R3B_REL/"inputs/acquisition/applause_relevant_plate_geometry.csv"
C01_REL=R3B_REL/"inputs/acquisition/references/EOP_C01_IAU2000_1846-now.txt"
HIST_REL=R3B_REL/"inputs/acquisition/references/historic_deltat.data"
V094V_REL=Path("pipeline_v0.2.0/research/prospective_freezes/v094v_site_reference_acquisition")

R3B_PLATE_SHA="ccd5e42cf04e5c72a767a38a2b6b7d1b36f6efaecdf10c4005af04bc777400cb"
C01_SHA="846cb53ae1055de1cd80ab78e065b05ad0bc3b224bf8eafe27f428eb12da3ffb"
HIST_SHA="9f43514119060601a00624a5d9287a91b0b1f5e12bec5209bbabda90b392b70b"
MONTH_SHA="9f88e53593495a09219fe956eeadea0fa9f8e3e02c310b2aa2b70852383cdf6f"
APPLAUSE_SHA="c30f700dd6a5d6a1aeeba8030fcce0193a8282e52bc9cf7d0d55d89f2b8bcb32"
EPS=1e-9
NEW_SITES={
 "Calar Alto Observatory, Spain":(-2.537,37.23,2168.0,12),
 "La Silla, Chile":(-70.73,-29.257,2347.0,11),
 "Observatorio de Fisica Cosmica, San Miguel, Argentina":(-34.5567,-58.7317,37.0,24),
}

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()

def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)

def fnum(v):
 try:
  x=float(str(v).strip());return x if math.isfinite(x) else None
 except:return None

def inum(v):
 x=fnum(v)
 if x is None:return None
 q=int(round(x));return q if abs(x-q)<1e-9 else None

def parse_dt(v):
 s=str(v or "").strip().replace("Z","+00:00")
 if not s:return None
 try:d=datetime.fromisoformat(s)
 except:return None
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.astimezone(timezone.utc)

def decimal_year(d):
 a=datetime(d.year,1,1,tzinfo=timezone.utc);b=datetime(d.year+1,1,1,tzinfo=timezone.utc)
 return d.year+(d-a).total_seconds()/(b-a).total_seconds()

def mjd(d):
 return 40587.0+(d-datetime(1970,1,1,tzinfo=timezone.utc)).total_seconds()/86400.0

def manifest_check(manifest,base):
 seen={}
 for line in Path(manifest).read_text(encoding="utf-8").splitlines():
  q=line.strip().split(None,1)
  if len(q)!=2:continue
  digest,name=q[0].lower(),q[1].strip()
  p=Path(base)/name
  if not p.is_file() or sha(p)!=digest:raise SystemExit(f"Manifest HOLD: {name}")
  seen[name]=digest
 return seen

def parse_c01(p):
 vals=[]
 for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
  q=line.split()
  if not q:continue
  try:x=float(q[0])
  except:continue
  if math.isfinite(x):vals.append(x)
 if len(vals)<1000:raise SystemExit("C01 parse HOLD")
 return min(vals),max(vals),len(vals)

def parse_hist(p):
 rec=[]
 for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
  q=line.split()
  if len(q)<3:continue
  try:y=float(q[0]);v=float(q[1]);e=float(q[2])
  except:continue
  if all(math.isfinite(x) for x in (y,v,e)):rec.append((y,v,e))
 if len(rec)<500:raise SystemExit("Historic DeltaT parse HOLD")
 rec.sort()
 return rec

def parse_monthly(p):
 rec=[]
 for line in Path(p).read_text(encoding="ascii",errors="strict").splitlines():
  q=line.split()
  if len(q)<4:continue
  try:y,m,d=int(q[0]),int(q[1]),int(q[2]);v=float(q[3]);dt=datetime(y,m,d,tzinfo=timezone.utc)
  except:continue
  if math.isfinite(v):rec.append((dt,v))
 if len(rec)!=639:raise SystemExit(f"Monthly DeltaT row replay HOLD: {len(rec)}")
 dates=[d for d,_ in rec]
 if len(set(dates))!=len(dates) or dates!=sorted(dates):raise SystemExit("Monthly DeltaT order/uniqueness HOLD")
 return rec

def domain_contains(rec,x,key=lambda q:q[0]):
 return key(rec[0])<=x<=key(rec[-1])

def self_test():
 t=datetime(1992,11,25,4,50,tzinfo=timezone.utc)
 assert abs(decimal_year(t)-1992.899457346691)<1e-9
 assert abs(mjd(t)-48951.20138888889)<1e-8
 print("v094w full coverage replay self-test PASS")
 return 0

def run(repo_root):
 repo=Path(repo_root).resolve()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("v094w contract SHA HOLD")
 for p in (V094T_CSV,V094T_REPORT,V094T_MANIFEST,V094U_REPORT,V094U_MANIFEST,V094S_PROV):
  if not p.is_file():raise SystemExit(f"Missing parent artifact: {p}")
 manifest_check(V094T_MANIFEST,V094T);manifest_check(V094U_MANIFEST,V094U)

 r3b_plate=repo/R3B_PLATE_REL;c01=repo/C01_REL;hist=repo/HIST_REL;vbank=repo/V094V_REL
 monthly=vbank/"deltat.data";vmanifest=vbank/"v094v_acquisition_manifest.sha256"
 vacq_plate=vbank/"applause_acquired_plate_site_metadata.csv";vacq_site=vbank/"applause_acquired_site_metadata.csv"
 vreport=vbank/"v094v_acquisition_report.json";vresponse=vbank/"applause_response.vot"
 for p in (r3b_plate,c01,hist,monthly,vmanifest,vacq_plate,vacq_site,vreport,vresponse):
  if not p.is_file():raise SystemExit(f"Missing frozen repo input: {p}")
 if sha(r3b_plate)!=R3B_PLATE_SHA or sha(c01)!=C01_SHA or sha(hist)!=HIST_SHA or sha(monthly)!=MONTH_SHA or sha(vresponse)!=APPLAUSE_SHA:
  raise SystemExit("Frozen reference hash mismatch")
 manifest_check(vmanifest,vbank)
 vr=json.loads(vreport.read_text(encoding="utf-8"))
 if vr.get("status")!="COMPLETE" or vr.get("outcome")!="ACQUISITION_COMPLETE_READY_FOR_COVERAGE_REPLAY":
  raise SystemExit("v094v bank report replay HOLD")

 u=json.loads(V094U_REPORT.read_text(encoding="utf-8"))
 if u.get("outcome")!="SITE_OR_REFERENCE_ACQUISITION_REQUIRED":raise SystemExit("v094u outcome replay HOLD")
 if int(u["parent_v094t"]["overlap_rows"])!=8807 or int(u["parent_v094t"]["positive_duration_overlap_intervals"])!=8925:
  raise SystemExit("v094u population replay HOLD")

 prov=json.loads(V094S_PROV.read_text(encoding="utf-8"));crec=(prov.get("inputs") or {}).get("plate_site_cache")
 if not crec:raise SystemExit("v094s plate cache provenance missing")
 cachep=ROOT/crec["path"]
 if not cachep.is_file() or sha(cachep)!=str(crec["sha256"]).lower():raise SystemExit("v094s plate cache hash HOLD")
 cache={}
 for r in rows(cachep):
  pid=inum(r.get("plate_id"))
  if pid is not None:cache[pid]=(str(r.get("site_name") or "").strip(),fnum(r.get("site_longitude")),fnum(r.get("site_latitude")))

 r3b_by_site=defaultdict(set);r3b_by_plate={}
 n=0
 for r in rows(r3b_plate):
  n+=1;pid=inum(r.get("plate_id"));site=str(r.get("site_name") or "").strip()
  lon=fnum(r.get("site_longitude"));lat=fnum(r.get("site_latitude"));el=fnum(r.get("site_elevation"))
  if None in (pid,lon,lat,el) or not site:raise SystemExit("r3b structural HOLD")
  r3b_by_site[site].add((lon,lat,el));r3b_by_plate[pid]=(site,lon,lat,el)
 if n!=1289:raise SystemExit(f"r3b row replay HOLD: {n}")

 new_by_plate={};new_by_site=defaultdict(set)
 for r in rows(vacq_plate):
  pid=inum(r.get("plate_id"));site=str(r.get("site_name") or "").strip()
  lon=fnum(r.get("site_longitude"));lat=fnum(r.get("site_latitude"));el=fnum(r.get("site_elevation_m"))
  if None in (pid,lon,lat,el) or not site:raise SystemExit("v094v acquired plate structural HOLD")
  if pid in new_by_plate:raise SystemExit(f"v094v acquired duplicate plate: {pid}")
  new_by_plate[pid]=(site,lon,lat,el);new_by_site[site].add((lon,lat,el))
 if len(new_by_plate)!=47 or set(new_by_site)!=set(NEW_SITES):raise SystemExit("v094v acquired site/plate set HOLD")
 for site,(lon,lat,el,cnt) in NEW_SITES.items():
  if len(new_by_site[site])!=1 or next(iter(new_by_site[site]))!=(lon,lat,el):raise SystemExit(f"v094v acquired tuple HOLD: {site}")
  if sum(1 for v in new_by_plate.values() if v[0]==site)!=cnt:raise SystemExit(f"v094v acquired count HOLD: {site}")

 total=0;overlap=0;pairs=set();required=defaultdict(set);intervals=[]
 monthly_pairs=set();historic_pairs=set()
 for r in rows(V094T_CSV):
  total+=1;pidpair=str(r.get("pair_id") or "")
  if pidpair in pairs:raise SystemExit(f"Duplicate v094t pair: {pidpair}")
  pairs.add(pidpair)
  if str(r.get("timing_bin") or "")!="OVERLAP":continue
  overlap+=1
  for s in ("a","b"):
   pid=inum(r.get(f"plate_{s}"));site=str(r.get(f"site_{s}") or "").strip()
   if pid is None or not site:raise SystemExit(f"OVERLAP structural HOLD: {pidpair}")
   required[site].add(pid)
  try:ivs=json.loads(str(r.get("fragment_overlap_intervals_json") or "[]"))
  except:raise SystemExit(f"Overlap JSON HOLD: {pidpair}")
  if not isinstance(ivs,list) or not ivs:raise SystemExit(f"Empty overlap intervals: {pidpair}")
  for x in ivs:
   a=parse_dt(x.get("start_utc"));b=parse_dt(x.get("end_utc"));dur=fnum(x.get("duration_seconds"))
   if a is None or b is None or b<=a or dur is None or dur<=0 or abs((b-a).total_seconds()-dur)>0.001:
    raise SystemExit(f"Overlap interval HOLD: {pidpair}")
   intervals.append((pidpair,a,b))
   if decimal_year(a)>1984.5 or decimal_year(b)>1984.5:monthly_pairs.add(pidpair)
   else:historic_pairs.add(pidpair)
 if total!=13177 or len(pairs)!=13177 or overlap!=8807 or len(intervals)!=8925:raise SystemExit("v094t population replay HOLD")
 required_ids=set().union(*required.values())
 if len(required)!=10 or len(required_ids)!=6015:raise SystemExit(f"required site/plate replay HOLD: {len(required)} / {len(required_ids)}")
 if set(NEW_SITES)-set(required):raise SystemExit("new site missing from required population")

 missing_cache=[];site_mis=[];ll_mis=[];missing_meta=[];missing_v=[];source_counts=Counter();site_rows=[]
 site_meta={}
 for site,pids in sorted(required.items()):
  if site in NEW_SITES:
   tuples=new_by_site.get(site,set())
   if len(tuples)!=1:missing_meta.append(site);continue
   lon,lat,el=next(iter(tuples));source="V094V_APPLAUSE_ACQUIRED"
  else:
   tuples=r3b_by_site.get(site,set())
   if len(tuples)!=1:missing_meta.append(site);continue
   lon,lat,el=next(iter(tuples));source="R3B_SITE_REUSE"
  site_meta[site]=(lon,lat,el,source);source_counts[source]+=len(pids)
  direct_r3b=sum(1 for pid in pids if pid in r3b_by_plate)
  direct_v=sum(1 for pid in pids if pid in new_by_plate)
  for pid in pids:
   c=cache.get(pid)
   if c is None:missing_cache.append(pid);continue
   cs,clon,clat=c
   if cs!=site:site_mis.append((pid,site,cs));continue
   if clon is None or clat is None or abs(clon-lon)>EPS or abs(clat-lat)>EPS:ll_mis.append((pid,site,clon,clat,lon,lat));continue
   if site in NEW_SITES:
    nv=new_by_plate.get(pid)
    if nv is None:missing_v.append(pid)
    elif nv!=(site,lon,lat,el):raise SystemExit(f"v094v plate tuple inconsistency: {pid}")
  site_rows.append({"site_name":site,"required_plate_count":len(pids),"metadata_source":source,
                    "site_longitude":lon,"site_latitude":lat,"site_elevation_m":el,
                    "direct_r3b_plate_rows":direct_r3b,"direct_v094v_plate_rows":direct_v})
 failures={
  "missing_plate_cache_rows":len(set(missing_cache)),
  "site_assignment_mismatches":len(site_mis),
  "site_lonlat_mismatches":len(ll_mis),
  "site_metadata_missing_or_ambiguous":len(set(missing_meta)),
  "v094v_required_plate_rows_missing":len(set(missing_v)),
 }

 cmin,cmax,cn=parse_c01(c01);h=parse_hist(hist);m=parse_monthly(monthly)
 hmin,hmax=h[0][0],h[-1][0];mmin,mmax=m[0][0],m[-1][0]
 cfail=0;dfail=0;monthly_intervals=0;historic_intervals=0;cross_boundary=0
 for pair,a,b in intervals:
  if not(cmin<=mjd(a)<=cmax and cmin<=mjd(b)<=cmax):cfail+=1
  ya,yb=decimal_year(a),decimal_year(b)
  if ya<=1984.5 and yb<=1984.5:
   historic_intervals+=1
   if not(hmin<=ya<=hmax and hmin<=yb<=hmax):dfail+=1
  elif ya>1984.5 and yb>1984.5:
   monthly_intervals+=1
   if not(mmin<=a<=mmax and mmin<=b<=mmax):dfail+=1
  else:
   cross_boundary+=1
   boundary=datetime(1984,7,2,tzinfo=timezone.utc)  # approximate only not used for evaluation
   if not(hmin<=ya<=hmax and mmin<=b<=mmax):dfail+=1
 failures["iers_c01_coverage_failures"]=cfail
 failures["nominal_deltat_coverage_failures"]=dfail
 ready=all(v==0 for v in failures.values())
 outcome="READY_TO_FREEZE_NOMINAL_FINITE_DISTANCE_GEOMETRY" if ready else "COVERAGE_REPLAY_HOLD"

 if RESULT.exists():raise SystemExit(f"Publication HOLD: final v094w directory exists: {RESULT}")
 stage=RESULT.parent/(RESULT.name+".__staging__."+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"."+str(os.getpid()))
 stage.mkdir(parents=True,exist_ok=False)
 sf=stage/"v094w_site_foundation.csv"
 with sf.open("w",encoding="utf-8",newline="") as f:
  fields=["site_name","required_plate_count","metadata_source","site_longitude","site_latitude","site_elevation_m","direct_r3b_plate_rows","direct_v094v_plate_rows"]
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(site_rows)
 issue=stage/"v094w_coverage_issues.csv"
 with issue.open("w",encoding="utf-8",newline="") as f:
  fields=["issue_type","plate_id","expected_site","observed_site","observed_lon","observed_lat","reference_lon","reference_lat"]
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for pid in sorted(set(missing_cache)):w.writerow({"issue_type":"PLATE_CACHE_MISSING","plate_id":pid})
  for pid,es,os_ in site_mis:w.writerow({"issue_type":"SITE_ASSIGNMENT_MISMATCH","plate_id":pid,"expected_site":es,"observed_site":os_})
  for pid,s,clon,clat,lon,lat in ll_mis:w.writerow({"issue_type":"LONLAT_MISMATCH","plate_id":pid,"expected_site":s,"observed_lon":clon,"observed_lat":clat,"reference_lon":lon,"reference_lat":lat})
  for pid in sorted(set(missing_v)):w.writerow({"issue_type":"V094V_REQUIRED_PLATE_ROW_MISSING","plate_id":pid})
 report={
  "status":"COMPLETE","outcome":outcome,"analysis_kind":"v094w_source_free_full_site_reference_coverage_replay",
  "contract_sha256":EXPECTED_CONTRACT_SHA,
  "population":{"v094t_rows":total,"overlap_pairs":overlap,"positive_duration_overlap_intervals":len(intervals),
                "unique_overlap_plates":len(required_ids),"unique_overlap_sites":len(required),
                "site_metadata_plate_counts":dict(source_counts)},
  "site_foundation":{"sites":site_rows,"failures":{k:v for k,v in failures.items() if k not in ("iers_c01_coverage_failures","nominal_deltat_coverage_failures")}},
  "reference_foundation":{
   "iers_c01":{"sha256":sha(c01),"records":cn,"mjd_min":cmin,"mjd_max":cmax,"coverage_failures":cfail},
   "historic_deltat":{"sha256":sha(hist),"decimal_year_min":hmin,"decimal_year_max":hmax,"has_uncertainty_column":True},
   "monthly_deltat":{"sha256":sha(monthly),"records":len(m),"date_min":mmin.date().isoformat(),"date_max":mmax.date().isoformat(),"has_uncertainty_column":False},
   "interval_classification":{"historic_only":historic_intervals,"monthly_only":monthly_intervals,"cross_1984_5_boundary":cross_boundary,
                              "pairs_touching_monthly_reference":len(monthly_pairs),"pairs_historic_only_or_touching_historic":len(historic_pairs)},
   "nominal_deltat_coverage_failures":dfail,
   "precision_qualification":"Any interval using monthly DeltaT lacks a frozen DeltaT uncertainty value; nominal geometry may proceed, but 2-arcsec physical precision certification remains reference-uncertainty-qualified for those intervals."
  },
  "acceptance_failures":failures,
  "guards":{"network":0,"source_catalog_reads":0,"candidate_identity_inspection":0,"private_candidate_map_reads":0,"pixels":0,
            "registration":0,"real_source_pairing":0,"finite_distance_geometry":0,"distance_grid_evaluation":0,"threshold_retuning":0},
  "next_stage":("Freeze nominal finite-distance geometry + synthetic recoverability over all 8,807 OVERLAP pairs, carrying the monthly-DeltaT uncertainty qualification."
                if ready else "Repair the reported coverage discrepancy before any geometry.")
 }
 rp=stage/"v094w_full_site_reference_coverage_replay.json";rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 mp=stage/"v094w_output_manifest.sha256";mp.write_text(f"{sha(sf)}  {sf.name}\n{sha(issue)}  {issue.name}\n{sha(rp)}  {rp.name}\n",encoding="utf-8")
 os.replace(stage,RESULT)

 print("\n"+"="*108)
 print("v094w SOURCE-FREE FULL SITE / REFERENCE COVERAGE REPLAY COMPLETE")
 print("="*108)
 print(f"Outcome:                                      {outcome}")
 print(f"v094t OVERLAP pairs / intervals:             {overlap:,} / {len(intervals):,}")
 print(f"Unique OVERLAP plates / sites:               {len(required_ids):,} / {len(required):,}")
 print(f"Site metadata plate coverage r3b / v094v:    {source_counts['R3B_SITE_REUSE']:,} / {source_counts['V094V_APPLAUSE_ACQUIRED']:,}")
 print(f"Plate/site/lonlat/v094v failures:            {failures['missing_plate_cache_rows']} / {failures['site_assignment_mismatches']} / {failures['site_lonlat_mismatches']} / {failures['v094v_required_plate_rows_missing']}")
 print(f"Site metadata missing/ambiguous:             {failures['site_metadata_missing_or_ambiguous']}")
 print(f"IERS C01 coverage failures:                  {cfail}")
 print(f"Nominal DeltaT coverage failures:            {dfail}")
 print(f"DeltaT interval split historic/monthly/cross:{historic_intervals:,} / {monthly_intervals:,} / {cross_boundary:,}")
 print(f"Pairs touching monthly DeltaT:               {len(monthly_pairs):,}")
 print("Monthly DeltaT uncertainty available:         False")
 print("Source catalogues / identities / network:    0 / 0 / 0")
 print("Finite-distance geometry evaluations:         0")
 print("STOP: freeze geometry/synthetic method separately before geometry outcomes.")
 return 0

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");ap.add_argument("--repo-root")
 a=ap.parse_args()
 if a.self_test:return self_test()
 if not a.repo_root:raise SystemExit("--repo-root required")
 return run(a.repo_root)

if __name__=="__main__":raise SystemExit(main())
