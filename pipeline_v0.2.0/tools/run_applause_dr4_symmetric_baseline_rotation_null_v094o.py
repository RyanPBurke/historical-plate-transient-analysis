#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime
import argparse,csv,hashlib,importlib.util,json,math
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_symmetric_baseline_rotation_null_contract_v094o.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_symmetric_baseline_rotation_null_parent_provenance_v094o.json"
EXPECTED="e9bf240d557fcf662889c1308362091f40c83d52acc68fc64ea68127c5afaf1d"
RESULT=ROOT/"results"/"applause_dr4_symmetric_baseline_rotation_null_v094o"
ORIGINAL=ROOT/"tools"/"run_applause_dr4_no_radius_epipolar_parallax_matcher_v094n.py"
ROTATIONS=(0,90,180,270)
RE=6378.137
FINAL_TOL=math.radians(2/3600)
MIN_DISP=math.radians(2/3600)
GEN_TOL=math.radians(7/3600)

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
def load_orig():
 spec=importlib.util.spec_from_file_location("v094n_frozen_functions",ORIGINAL)
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
def rotate_about_axis(v,axis,deg):
 axis=np.asarray(axis,float);axis=axis/np.linalg.norm(axis);v=np.asarray(v,float);t=math.radians(deg)
 return v*math.cos(t)+np.cross(axis,v)*math.sin(t)+axis*(axis@v)*(1-math.cos(t))
def rotated_baseline(B,field_axis,deg):
 field_axis=np.asarray(field_axis,float);field_axis/=np.linalg.norm(field_axis)
 par=(B@field_axis)*field_axis;perp=B-par
 return par+rotate_about_axis(perp,field_axis,deg)
def median3(a,b,c):return sorted((a,b,c))[1]
def pct(v,p):return None if not v else float(np.percentile(np.asarray(v,float),p))
def widebin(disp_rad):
 s=math.degrees(abs(disp_rad))*3600
 if s>=3600:return "GE1DEG"
 if s>=600:return "10_TO_60ARCMIN"
 return "LT10ARCMIN"
def self_test():
 c=np.array([0.,0.,1.]);B=np.array([3.,4.,5.])
 vals=[rotated_baseline(B,c,d) for d in ROTATIONS]
 for v in vals:
  assert abs(np.linalg.norm(v)-np.linalg.norm(B))<1e-10
  assert abs(v@c-B@c)<1e-10
 assert np.allclose(vals[2],np.array([-3.,-4.,5.]))
 # Median opportunity/null semantics.
 assert median3(1,9,5)==5
 print("v094o symmetric-baseline-rotation self-test PASS");return 0

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit("v094o contract SHA mismatch")
 p=json.loads(PROV.read_text(encoding="utf-8"))
 o=load_orig()
 # Verify the exact original function source bytes used for geometry.
 if sha(ORIGINAL)!=p["original_v094n_runner"]["sha256"]:raise SystemExit("Original v094n runner mismatch")
 plan=list(rows(ROOT/p["frozen_plan"]["path"]));inv=list(rows(ROOT/p["source_cache_inventory"]["path"]))
 keypath={}
 for n,r in enumerate(inv,1):
  f=ROOT/r["relative_path"]
  if not f.is_file() or f.stat().st_size!=int(r["size_bytes"]) or sha(f)!=r["sha256"]:raise SystemExit(f"cache mismatch {n}")
  keypath[(o.inum(r["scan_id"]),o.inum(r["solution_num"]))]=f
  if n%200==0:log(f"source-cache verification: {n}/1386")
 polys={}
 for r in rows(ROOT/p["solution_full"]["path"]):
  sid=o.inum(r.get("solution_id"));q=o.parse_poly(r.get("stc_polygon"))
  if sid is not None and q is not None:polys[sid]=q
 plate={}
 for r in rows(ROOT/p["plate_site_cache"]["path"]):
  pid=o.inum(r.get("plate_id"));site=str(r.get("site_name") or "").strip();lon=o.fnum(r.get("site_longitude"));lat=o.fnum(r.get("site_latitude"))
  if pid is not None:
   cl=o.corrected_coords(site,lon,lat);plate[pid]=(site,cl[1],cl[0]) if cl!=(None,None) else (site,None,None)
 cache=OrderedDict()
 def get(k):
  if k in cache:cache.move_to_end(k);return cache[k]
  x=o.load_npz(keypath[k]);cache[k]=x
  while len(cache)>10:cache.popitem(last=False)
  return x

 glob=defaultdict(Counter);siteagg=defaultdict(lambda:defaultdict(Counter));epochagg=defaultdict(lambda:defaultdict(Counter))
 tieragg=defaultdict(lambda:defaultdict(Counter));distagg=defaultdict(lambda:defaultdict(Counter));dispagg=defaultdict(lambda:defaultdict(Counter))
 wideagg=defaultdict(lambda:defaultdict(Counter))
 opp_rows=[];plate_cluster=defaultdict(lambda:{d:0 for d in ROTATIONS})
 overlap_count=nonoverlap=0;cal_opp=0
 for ix,r in enumerate(plan,1):
  if str(r["timing_bin"])!="OVERLAP":
   nonoverlap+=1;continue
  overlap_count+=1
  ka=(o.inum(r["scan_id_a"]),o.inum(r["solution_num_a"]));kb=(o.inum(r["scan_id_b"]),o.inum(r["solution_num_b"]))
  pa,pb=polys[o.inum(r["solution_id_a"])],polys[o.inum(r["solution_id_b"])]
  A0,B0=get(ka),get(kb);A=o.subset(A0,o.common_mask(A0["ra"],A0["dec"],pa,pb));B=o.subset(B0,o.common_mask(B0["ra"],B0["dec"],pa,pb))
  ga=np.asarray(A["gaia_id"],np.int64);gb=np.asarray(B["gaia_id"],np.int64)
  shared=set(int(x) for x in ga if int(x)>0).intersection(int(x) for x in gb if int(x)>0)
  ma=np.array([int(x)>0 and int(x) not in shared for x in ga],dtype=bool)
  mb=np.array([int(x)>0 and int(x) not in shared for x in gb],dtype=bool)
  UA=o.subset(A,ma);UB=o.subset(B,mb)
  model=o.local_reference_model(A,B,pa,pb);tier="CALIBRATED_LOCAL25" if model is not None else "HOLD_UNCALIBRATED_ASTROMETRY"
  if model is not None:cal_opp+=1
  try:ovs=json.loads(r["fragment_overlap_intervals_json"])
  except:ovs=[]
  pma,pmb=plate.get(o.inum(r["plate_a"])),plate.get(o.inum(r["plate_b"]))
  if not pma or not pmb or None in (pma[1],pma[2],pmb[1],pmb[2]) or not ovs:raise SystemExit("Unexpected geometry HOLD in frozen overlap population")
  va,vb=o.ecef(pma[1],pma[2]),o.ecef(pmb[1],pmb[2]);acc=np.zeros(3);tot=0.;tmid=None
  for q in ovs:
   s,e=o.parse_dt(q.get("start_utc")),o.parse_dt(q.get("end_utc"))
   if not s or not e or e<=s:continue
   w=(e-s).total_seconds();m=s+(e-s)/2
   if tmid is None:tmid=m
   acc+=w*(o.eci(vb,m)-o.eci(va,m));tot+=w
  if tot<=0 or tmid is None:raise SystemExit("Unexpected overlap timing geometry failure")
  B0vec=acc/tot;rA=o.eci(va,tmid);rBactual=rA+B0vec
  cra,cdec=o.center([pa,pb]);field_axis=o.one_xyz(cra,cdec)
  Avec=o.xyz(UA["ra"],UA["dec"]);Bvecs=o.xyz(UB["ra"],UB["dec"])
  counts={d:0 for d in ROTATIONS}
  wcounts={d:Counter() for d in ROTATIONS}
  for deg in ROTATIONS:
   Brot=rotated_baseline(B0vec,field_axis,deg);rB=rA+Brot;e1,e2,e3=o.basis_about_baseline(Brot)
   gen=o.candidate_pairs_epipolar(Avec,Bvecs,e1,e2,e3,GEN_TOL);glob[deg]["generator_pairs"]+=len(gen)
   for ia,ib in gen:
    na=Avec[ia];nbraw=Bvecs[ib];nb=o.correct_b(nbraw,model) if model is not None else nbraw
    # Real observation visibility prefilter is identical for every rotation.
    if float(na@rA)<=0 or float(nb@rBactual)<=0:continue
    pha,ala=o.phi_alpha(na,e1,e2,e3);phb,alb=o.phi_alpha(nb,e1,e2,e3)
    normal=np.cross(e3,na);nn=np.linalg.norm(normal)
    if nn<1e-15:continue
    normal/=nn;xt=math.asin(min(1.0,abs(float(nb@normal))))
    if xt>FINAL_TOL:continue
    disp=alb-ala
    if disp<MIN_DISP:continue
    sol=o.ray_solution(rA,rB,na,nb)
    if sol is None:continue
    tA,tB,mid,miss,closure=sol
    if tA<=0 or tB<=0:continue
    D=float(np.linalg.norm(mid));bp=float(np.linalg.norm(Brot-(Brot@na)*na));dmax=bp/math.tan(MIN_DISP) if bp>0 else 0
    if D<RE or D>dmax or closure>FINAL_TOL:continue
    counts[deg]+=1;glob[deg]["matches"]+=1
    if model is not None:glob[deg]["calibrated_matches"]+=1
    db=o.distbin(D);sb=o.dispbin(disp);wb=widebin(disp)
    siteagg[str(r["site_pair"])][deg]["matches"]+=1
    epochagg[str(r["epoch_label"])][deg]["matches"]+=1
    tieragg[tier][deg]["matches"]+=1
    distagg[db][deg]["matches"]+=1;dispagg[sb][deg]["matches"]+=1;wideagg[wb][deg]["matches"]+=1
  nullmed=median3(counts[90],counts[180],counts[270])
  opp_rows.append((counts[0],nullmed))
  pp=tuple(sorted((o.inum(r["plate_a"]),o.inum(r["plate_b"]))))
  for d in ROTATIONS:plate_cluster[pp][d]+=counts[d]
  if ix%50==0:log(f"v094o rotation-null: {ix}/1240; real={glob[0]['matches']:,}; n90={glob[90]['matches']:,}; n180={glob[180]['matches']:,}; n270={glob[270]['matches']:,}")

 if overlap_count!=1081 or nonoverlap!=159:raise SystemExit("Timing replay HOLD")
 if glob[0]["matches"]!=997370:raise SystemExit(f"ROT0 replay HOLD: {glob[0]['matches']} != 997370")
 if glob[0]["calibrated_matches"]!=732422:raise SystemExit(f"ROT0 calibrated replay HOLD: {glob[0]['calibrated_matches']} != 732422")

 RESULT.mkdir(parents=True,exist_ok=True)
 def wtable(path,d):
  with path.open("w",encoding="utf-8",newline="") as f:
   fields=["group"]+[f"rot{x}" for x in ROTATIONS]
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
   for g,rots in sorted(d.items(),key=lambda kv:-kv[1][0].get("matches",0)):
    w.writerow({"group":g,**{f"rot{x}":rots[x].get("matches",0) for x in ROTATIONS}})
 files=[]
 for name,d in (("site_pair",siteagg),("epoch",epochagg),("calibration_tier",tieragg),("distance",distagg),("disparity",dispagg),("wide_angle",wideagg)):
  pth=RESULT/f"{name}_rotation_summary_v094o.csv";wtable(pth,d);files.append(pth)

 deltas=[a-b for a,b in opp_rows];pos=sum(x>0 for x in deltas);neg=sum(x<0 for x in deltas);eq=sum(x==0 for x in deltas)
 plate_d=[]
 for c in plate_cluster.values():
  plate_d.append(c[0]-median3(c[90],c[180],c[270]))
 paired={"opportunities":len(opp_rows),"real_gt_nullmedian":pos,"real_lt_nullmedian":neg,"equal":eq,
         "delta_median":pct(deltas,50),"delta_p10":pct(deltas,10),"delta_p90":pct(deltas,90),
         "sum_real":sum(a for a,b in opp_rows),"sum_opportunity_null_median":sum(b for a,b in opp_rows),
         "sum_real_to_null_median_ratio":(sum(a for a,b in opp_rows)/sum(b for a,b in opp_rows) if sum(b for a,b in opp_rows) else None),
         "plate_pair_clusters":len(plate_d),"plate_real_gt_nullmedian":sum(x>0 for x in plate_d),
         "plate_real_lt_nullmedian":sum(x<0 for x in plate_d),"plate_equal":sum(x==0 for x in plate_d),
         "plate_delta_median":pct(plate_d,50)}
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_symmetric_baseline_rotation_null_v094o",
         "contract_sha256":EXPECTED,"parent_provenance_sha256":sha(PROV),
         "aggregate":{f"ROT{d}":dict(glob[d]) for d in ROTATIONS},
         "opportunity_and_plate_pair_paired_summary":paired,
         "guards":{"network_queries":0,"private_candidate_map_read":False,"candidate_identity_inspection":0,
                   "source_or_gaia_ids_emitted":0,"coordinates_emitted":0,"individual_opportunity_ids_emitted":0,
                   "angular_pair_radius_maximum_applied":False}}
 rp=RESULT/"applause_dr4_symmetric_baseline_rotation_null_v094o.json"
 report["output_hashes"]={q.name:sha(q) for q in files}
 rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8");files.append(rp)
 man=RESULT/"v094o_output_manifest.sha256";man.write_text("".join(f"{sha(q)}  {q.name}\n" for q in files),encoding="utf-8")
 print("\n"+"="*104);print("v094o SYMMETRIC BASELINE-ROTATION NULL AUDIT COMPLETE");print("="*104)
 for d in ROTATIONS:
  print(f"ROT{d:>3} matches / calibrated:                  {glob[d]['matches']:,} / {glob[d]['calibrated_matches']:,}")
 nulltot=np.median([glob[90]["matches"],glob[180]["matches"],glob[270]["matches"]])
 print(f"Real / median(total rotated null counts):       {glob[0]['matches']/nulltot if nulltot else None}")
 print(f"Opportunity real > / < / = null median:        {pos} / {neg} / {eq}")
 print(f"Opportunity delta median [p10,p90]:             {paired['delta_median']} [{paired['delta_p10']}, {paired['delta_p90']}]")
 print(f"Sum real / sum opportunity-null-median:         {paired['sum_real_to_null_median_ratio']}")
 print(f"Plate-pair real > / < / = null median:         {paired['plate_real_gt_nullmedian']} / {paired['plate_real_lt_nullmedian']} / {paired['plate_equal']}")
 print("ROT0 replay of v094n physical count:           PASS")
 print("Old asymmetric v094n anti branch used:         False")
 print("Private candidate identities inspected:        0")
 print("Network / controls / pixels / registration:   0 / 0 / 0 / 0")
 print("STOP: interpret symmetric directional null before any unblinding.")
 return 0
if __name__=="__main__":raise SystemExit(main())
