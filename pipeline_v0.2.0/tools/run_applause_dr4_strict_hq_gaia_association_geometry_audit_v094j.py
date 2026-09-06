#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime
import argparse,csv,hashlib,json,math,re
import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_strict_hq_gaia_association_geometry_contract_v094j.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_strict_hq_gaia_association_geometry_parent_provenance_v094j.json"
INV=ROOT/"research"/"prospective_freezes"/"applause_dr4_v094i_strict_hq_source_cache_inventory_v094j.csv"
EXPECTED_CONTRACT_SHA="db600ec1cec6e2a861ce711f52a52dd22f10a1ff0a1824ea4771b8e4a2d8bffa"
RESULT=ROOT/"results"/"applause_dr4_strict_hq_gaia_association_geometry_audit_v094j"

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def log(s=""):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
def fnum(v):
 try:
  x=float(str(v if v is not None else "").strip());return x if math.isfinite(x) else None
 except:return None
def inum(v):
 x=fnum(v)
 if x is None:return None
 r=int(round(x));return r if abs(x-r)<1e-7 else None
def parse_poly(v):
 nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
 if len(nums)<8:return None
 nums=nums[-8:];p=[(nums[i]%360.0,nums[i+1]) for i in range(0,8,2)]
 return None if any(not(-90<=d<=90) for _,d in p) else p
def xyz(ra,dec):
 ra=np.deg2rad(np.asarray(ra,float));dec=np.deg2rad(np.asarray(dec,float));c=np.cos(dec)
 return np.column_stack((c*np.cos(ra),c*np.sin(ra),np.sin(dec)))
def arcsec_from_chord(d):
 d=np.clip(np.asarray(d,float),0.0,2.0);return np.degrees(2*np.arcsin(d/2))*3600.0
def sepbin(x):
 if x is None or not math.isfinite(float(x)):return "MISSING"
 x=float(x)
 if x<=1:return "LE1"
 if x<=3:return "GT1_LE3"
 if x<=5:return "GT3_LE5"
 if x<=10:return "GT5_LE10"
 if x<=30:return "GT10_LE30"
 if x<=60:return "GT30_LE60"
 return "GT60"
def gaiabin(x):
 if x is None or not math.isfinite(float(x)):return "MISSING"
 x=float(x)
 if x<=.5:return "LE0P5"
 if x<=1:return "GT0P5_LE1"
 if x<=2:return "GT1_LE2"
 if x<=5:return "GT2_LE5"
 return "GT5"
def ratiobin(dist,radius):
 if dist is None or radius is None or not math.isfinite(float(dist)) or not math.isfinite(float(radius)) or float(radius)<=0:return "MISSING_OR_INVALID"
 x=float(dist)/float(radius)
 if x<=.25:return "LE0P25"
 if x<=.5:return "GT0P25_LE0P5"
 if x<=.75:return "GT0P5_LE0P75"
 if x<=1:return "GT0P75_LE1"
 return "GT1"
def neighbin(x):
 if x is None:return "MISSING"
 try:x=int(x)
 except:return "MISSING"
 if x<0:return "MISSING"
 if x==0:return "0"
 if x==1:return "1"
 if x<=3:return "2_3"
 return "4PLUS"
def tangent_center(polys):
 xs=ys=zs=0.0
 for poly in polys:
  for ra,dec in poly:
   r,d=math.radians(ra),math.radians(dec);c=math.cos(d);xs+=c*math.cos(r);ys+=c*math.sin(r);zs+=math.sin(d)
 return math.degrees(math.atan2(ys,xs))%360.0,math.degrees(math.atan2(zs,math.hypot(xs,ys)))
def project_points(ra,dec,ra0,dec0):
 r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0);dr=(r-r0+math.pi)%(2*math.pi)-math.pi
 cosc=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr);ok=cosc>1e-10;x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
 x[ok]=np.cos(d[ok])*np.sin(dr[ok])/cosc[ok];y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/cosc[ok]
 return x,y,ok
def project_poly(poly,ra0,dec0):
 ra=np.asarray([x[0] for x in poly]);dec=np.asarray([x[1] for x in poly]);x,y,ok=project_points(ra,dec,ra0,dec0);return None if not np.all(ok) else list(zip(x.tolist(),y.tolist()))
def inside_projected(x,y,poly):
 if poly is None:return np.zeros(len(x),dtype=bool)
 px=np.asarray([p[0] for p in poly]);py=np.asarray([p[1] for p in poly]);inside=np.zeros(len(x),dtype=bool);j=len(px)-1;valid=np.isfinite(x)&np.isfinite(y)
 for i in range(len(px)):
  yi,yj=py[i],py[j];cross=((yi>y)!=(yj>y))&valid;den=yj-yi
  if abs(den)>1e-20:
   xcross=(px[j]-px[i])*(y-yi)/den+px[i];inside^=cross&(x<xcross)
  j=i
 return inside
def common_mask(ra,dec,pa,pb):
 ra0,dec0=tangent_center([pa,pb]);x,y,ok=project_points(ra,dec,ra0,dec0)
 return ok&inside_projected(x,y,project_poly(pa,ra0,dec0))&inside_projected(x,y,project_poly(pb,ra0,dec0))
def subset(x,m):return {k:v[m] for k,v in x.items() if hasattr(v,'__len__') and len(v)==len(m)}
def mutual_geometry(a,b):
 na,nb=len(a["source_id"]),len(b["source_id"]);pairs=[]
 if na==0 or nb==0:return pairs
 xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb);da,ib=tb.query(xa,k=1);db,ia=ta.query(xb,k=1);sa=arcsec_from_chord(da)
 for i,j in enumerate(ib.astype(int)):
  if j<nb and int(ia[j])==i:pairs.append((i,j,float(sa[i])))
 return pairs
def angsep_one(ra1,de1,ra2,de2):
 a=xyz([ra1],[de1])[0];b=xyz([ra2],[de2])[0];d=float(np.linalg.norm(a-b));return float(arcsec_from_chord([d])[0])
def load_polys(p):
 out={}
 for r in rows(p):
  sid=inum(r.get("solution_id"));poly=parse_poly(r.get("stc_polygon"))
  if sid is not None and poly is not None:out[sid]=poly
 return out
def cache_load(path):
 z=np.load(path,allow_pickle=False);return {k:np.asarray(z[k]) for k in z.files if not k.endswith("_scalar")}
def self_test():
 assert gaiabin(.4)=="LE0P5" and gaiabin(3)=="GT2_LE5" and ratiobin(.5,2)=="LE0P25" and neighbin(4)=="4PLUS"
 a={"source_id":np.array([1,2]),"ra":np.array([0.,1.]),"dec":np.array([0.,0.]),"gaia_id":np.array([10,20])};b={"source_id":np.array([3,4]),"ra":np.array([.0001,1.0001]),"dec":np.array([0.,0.]),"gaia_id":np.array([10,30])}
 p=mutual_geometry(a,b);assert len(p)==2 and p[0][2]<1
 print("v094j self-test PASS");return 0
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("v094j contract SHA mismatch")
 if not PROV.is_file() or not INV.is_file():raise SystemExit("Missing frozen v094j provenance/inventory")
 prov=json.loads(PROV.read_text(encoding="utf-8"))
 if prov.get("status")!="PARENT_PROVENANCE_PREPARED_BEFORE_V094J_AGGREGATE_GEOMETRY":raise SystemExit("Bad v094j provenance status")
 for sec,key,hkey in (("v094i_results","report","report_sha256"),("v094i_results","manifest","manifest_sha256"),("v094i_frozen","plan","plan_sha256"),("v094i_frozen","parent_provenance","parent_provenance_sha256"),("v094d_solution_full","path","sha256")):
  rec=prov[sec];p=ROOT/rec[key]
  if not p.is_file() or sha(p)!=rec[hkey]:raise SystemExit(f"Frozen parent mismatch: {sec}.{key}")
 inv=list(rows(INV))
 if len(inv)!=1386 or sha(INV)!=prov["source_cache_inventory"]["sha256"]:raise SystemExit("v094j source inventory mismatch")
 keypath={};total_rows=0
 for i,r in enumerate(inv,1):
  k=(inum(r["scan_id"]),inum(r["solution_num"]));p=ROOT/r["relative_path"]
  if None in k or not p.is_file() or p.stat().st_size!=int(r["size_bytes"]) or sha(p)!=r["sha256"]:raise SystemExit(f"Frozen strict-HQ source cache mismatch: {k}")
  keypath[k]=p;total_rows+=int(r["rows"])
  if i%200==0:log(f"source-cache verification: {i}/1386")
 plan=list(rows(ROOT/prov["v094i_frozen"]["plan"]))
 if len(plan)!=1240:raise SystemExit("Expected 1240 v094i plan rows")
 polys=load_polys(ROOT/prov["v094d_solution_full"]["path"]);cache=OrderedDict()
 def get(k):
  if k in cache:cache.move_to_end(k);return cache[k]
  x=cache_load(keypath[k]);cache[k]=x
  while len(cache)>10:cache.popitem(last=False)
  return x
 glob=Counter();siteagg=defaultdict(Counter);teagg=defaultdict(Counter)
 RESULT.mkdir(parents=True,exist_ok=True);perp=RESULT/"per_opportunity_hq_gaia_geometry_v094j.csv"
 fields=["pair_id","site_pair","timing_bin","epoch_label","hq_a","hq_b","gaia_present_a","gaia_present_b","mutual_total","mutual_le5","mutual_le60","mutual_same_gaia_total","mutual_same_gaia_le5","mutual_same_gaia_le60","mutual_different_gaia_total","mutual_different_gaia_le5","mutual_different_gaia_le60","mutual_different_gaia_both_tight_le1_le5","mutual_different_gaia_pair_closer_than_both_own_gaia_le5","shared_gaia_identities","shared_gaia_minsep_le5","shared_gaia_minsep_le60"]
 with perp.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for ix,r in enumerate(plan,1):
   ka=(inum(r["scan_id_a"]),inum(r["solution_num_a"]));kb=(inum(r["scan_id_b"]),inum(r["solution_num_b"]));sa,sb=inum(r["solution_id_a"]),inum(r["solution_id_b"]);pa,pb=polys.get(sa),polys.get(sb)
   if pa is None or pb is None:raise SystemExit(f"Missing solution polygon: {r['pair_id']}")
   A,B=get(ka),get(kb);Ac=subset(A,common_mask(A["ra"],A["dec"],pa,pb));Bc=subset(B,common_mask(B["ra"],B["dec"],pa,pb));na,nb=len(Ac["source_id"]),len(Bc["source_id"])
   ga,gb=Ac["gaia_id"],Bc["gaia_id"];q=Counter()
   # Source-level Gaia match-quality diagnostics are incidence counts, retained in every aggregate stratum.
   for role,X in (("a",Ac),("b",Bc)):
    n=len(X["source_id"]);q[f"gaia_{role}_incidences"]+=n
    for d,mr,ng in zip(X["gaiaedr3_dist"],X["match_radius"],X["gaiaedr3_neighbors"]):
     q[f"gaia_dist_{role}_{gaiabin(d)}"]+=1;q[f"gaia_ratio_{role}_{ratiobin(d,mr)}"]+=1;q[f"gaia_neighbors_{role}_{neighbin(ng)}"]+=1
   mp=mutual_geometry(Ac,Bc);c=Counter()
   for ia,ib,ss in mp:
    g1,g2=int(ga[ia]),int(gb[ib]);ident="SAME_GAIA" if g1>0 and g2>0 and g1==g2 else ("DIFFERENT_GAIA" if g1>0 and g2>0 else "GAIA_UNRESOLVED");b=sepbin(ss);c["mutual_total"]+=1;c[f"mutual_{ident}_{b}"]+=1
    if ss<=5:
     c["mutual_le5"]+=1;c[f"mutual_{ident}_le5"]+=1
     da=float(Ac["gaiaedr3_dist"][ia]);db=float(Bc["gaiaedr3_dist"][ib])
     if ident=="DIFFERENT_GAIA" and math.isfinite(da) and math.isfinite(db):
      if da<=1 and db<=1:c["mutual_DIFFERENT_GAIA_both_tight_le1_le5"]+=1
      if ss<da and ss<db:c["mutual_DIFFERENT_GAIA_pair_closer_than_both_own_gaia_le5"]+=1
    if ss<=60:c["mutual_le60"]+=1;c[f"mutual_{ident}_le60"]+=1
   # Same-Gaia identity geometry independent of mutual-nearest-neighbour assignment.
   amap=defaultdict(list);bmap=defaultdict(list)
   for i,g in enumerate(ga):
    if int(g)>0:amap[int(g)].append(i)
   for i,g in enumerate(gb):
    if int(g)>0:bmap[int(g)].append(i)
   shared=set(amap).intersection(bmap);c["shared_gaia_identities"]+=len(shared)
   for g in shared:
    best=float("inf")
    for ia in amap[g]:
     for ib in bmap[g]:
      ss=angsep_one(Ac["ra"][ia],Ac["dec"][ia],Bc["ra"][ib],Bc["dec"][ib]);best=min(best,ss)
    c[f"shared_gaia_minsep_{sepbin(best)}"]+=1
    if best<=5:c["shared_gaia_minsep_le5"]+=1
    if best<=60:c["shared_gaia_minsep_le60"]+=1
   out={"pair_id":r["pair_id"],"site_pair":r["site_pair"],"timing_bin":r["timing_bin"],"epoch_label":r["epoch_label"],"hq_a":na,"hq_b":nb,"gaia_present_a":int(np.sum(ga>0)),"gaia_present_b":int(np.sum(gb>0)),"mutual_total":c["mutual_total"],"mutual_le5":c["mutual_le5"],"mutual_le60":c["mutual_le60"],"mutual_same_gaia_total":sum(v for k,v in c.items() if k.startswith("mutual_SAME_GAIA_") and not k.endswith(("le5","le60"))),"mutual_same_gaia_le5":c["mutual_SAME_GAIA_le5"],"mutual_same_gaia_le60":c["mutual_SAME_GAIA_le60"],"mutual_different_gaia_total":sum(v for k,v in c.items() if k.startswith("mutual_DIFFERENT_GAIA_") and not k.endswith(("le5","le60")) and "both_tight" not in k and "pair_closer" not in k),"mutual_different_gaia_le5":c["mutual_DIFFERENT_GAIA_le5"],"mutual_different_gaia_le60":c["mutual_DIFFERENT_GAIA_le60"],"mutual_different_gaia_both_tight_le1_le5":c["mutual_DIFFERENT_GAIA_both_tight_le1_le5"],"mutual_different_gaia_pair_closer_than_both_own_gaia_le5":c["mutual_DIFFERENT_GAIA_pair_closer_than_both_own_gaia_le5"],"shared_gaia_identities":c["shared_gaia_identities"],"shared_gaia_minsep_le5":c["shared_gaia_minsep_le5"],"shared_gaia_minsep_le60":c["shared_gaia_minsep_le60"]};w.writerow(out)
   vals={"opportunities":1,"hq_a":na,"hq_b":nb,"gaia_present_a":out["gaia_present_a"],"gaia_present_b":out["gaia_present_b"]}
   vals.update(q);vals.update(c)
   for k,v in vals.items():glob[k]+=v;siteagg[r["site_pair"]][k]+=v;teagg[f"{r['timing_bin']}|{r['epoch_label']}"][k]+=v
   if ix%100==0:log(f"v094j aggregate geometry: {ix}/1240")
 if glob["hq_a"]+glob["hq_b"]!=15042219:raise SystemExit(f"Mechanical consistency HOLD: HQ incidence replay {glob['hq_a']+glob['hq_b']} != 15042219")
 if glob["gaia_present_a"]+glob["gaia_present_b"]!=15042219:raise SystemExit("Mechanical consistency HOLD: strict-HQ Gaia-present total no longer equals HQ incidence total")
 if glob["shared_gaia_identities"]!=472992:raise SystemExit(f"Mechanical consistency HOLD: shared Gaia identity replay {glob['shared_gaia_identities']} != 472992")
 def writeagg(p,d):
  allk=sorted({k for c in d.values() for k in c});fields=["group"]+allk
  with p.open("w",encoding="utf-8",newline="") as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
   for g,c in sorted(d.items(),key=lambda kv:(-kv[1].get("opportunities",0),kv[0])):
    rr={"group":g};rr.update(c);w.writerow(rr)
 sitep=RESULT/"site_pair_hq_gaia_geometry_summary_v094j.csv";tep=RESULT/"timing_epoch_hq_gaia_geometry_summary_v094j.csv";writeagg(sitep,siteagg);writeagg(tep,teagg)
 # compact useful fractions
 total=glob["hq_a"]+glob["hq_b"];dist_le1=sum(glob[k] for k in ("gaia_dist_a_LE0P5","gaia_dist_a_GT0P5_LE1","gaia_dist_b_LE0P5","gaia_dist_b_GT0P5_LE1"));ratio_le05=sum(glob[k] for k in ("gaia_ratio_a_LE0P25","gaia_ratio_a_GT0P25_LE0P5","gaia_ratio_b_LE0P25","gaia_ratio_b_GT0P25_LE0P5"))
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_strict_hq_gaia_association_geometry_audit_v094j","contract_sha256":EXPECTED_CONTRACT_SHA,"parent_provenance_sha256":sha(PROV),"source_inventory_sha256":sha(INV),"opportunities":1240,"aggregate":dict(glob),"fractions":{"gaia_match_distance_le1_arcsec":None if not total else dist_le1/total,"gaia_dist_to_match_radius_le0p5":None if not total else ratio_le05/total,"mutual_different_gaia_fraction_le5":None if not glob["mutual_le5"] else glob["mutual_DIFFERENT_GAIA_le5"]/glob["mutual_le5"],"mutual_same_gaia_fraction_le5":None if not glob["mutual_le5"] else glob["mutual_SAME_GAIA_le5"]/glob["mutual_le5"]},"site_pair_summary":{g:dict(c) for g,c in sorted(siteagg.items(),key=lambda kv:(-kv[1]["opportunities"],kv[0]))},"timing_epoch_summary":{g:dict(c) for g,c in sorted(teagg.items())},"guards":{"network_queries":0,"candidate_csv_reads":0,"candidate_inspection":0,"source_or_gaia_ids_emitted":0,"source_coordinates_emitted":0,"controls":0,"pixels":0,"registration":0,"detector_runs":0,"physical_parallax_pairing":0,"quality_threshold_relaxation":0},"interpretive_stop":"Interpret strict-HQ Gaia association quality and same-vs-different-Gaia mutual geometry before physical parallax pairing or quality-threshold sensitivity."}
 rp=RESULT/"applause_dr4_strict_hq_gaia_association_geometry_audit_v094j.json";report["output_hashes"]={p.name:sha(p) for p in (perp,sitep,tep)};rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8");man=RESULT/"v094j_output_manifest.sha256";man.write_text("".join(f"{sha(p)}  {p.name}\n" for p in (perp,sitep,tep,rp)),encoding="utf-8")
 print("\n"+"="*98);print("v094j STRICT-HQ GAIA ASSOCIATION / CROSS-SITE GEOMETRY AUDIT COMPLETE");print("="*98)
 print(f"Opportunities processed:                         {glob['opportunities']}")
 print(f"Strict-HQ common source incidences A+B:          {total:,}")
 print(f"Gaia-present strict-HQ incidences A+B:           {glob['gaia_present_a']+glob['gaia_present_b']:,}")
 print(f"Gaia match distance <=1 arcsec fraction:         {report['fractions']['gaia_match_distance_le1_arcsec']}")
 print(f"Gaia distance/match-radius <=0.5 fraction:        {report['fractions']['gaia_dist_to_match_radius_le0p5']}")
 print(f"All-HQ mutual nearest pairs <=5 arcsec:           {glob['mutual_le5']:,}")
 print(f"  same-Gaia <=5 arcsec:                          {glob['mutual_SAME_GAIA_le5']:,}")
 print(f"  different-Gaia <=5 arcsec:                     {glob['mutual_DIFFERENT_GAIA_le5']:,}")
 print(f"  different-Gaia both own Gaia <=1 arcsec:       {glob['mutual_DIFFERENT_GAIA_both_tight_le1_le5']:,}")
 print(f"Different-Gaia mutual nearest pairs <=60 arcsec: {glob['mutual_DIFFERENT_GAIA_le60']:,}")
 print(f"Shared Gaia identities replayed:                 {glob['shared_gaia_identities']:,}")
 print(f"Shared Gaia identities with min sep <=5 arcsec:  {glob['shared_gaia_minsep_le5']:,}")
 print("Network / controls / pixels / registration:      0 / 0 / 0 / 0")
 print("Candidate/source/Gaia IDs emitted:               0")
 print("STOP: interpret Gaia-association quality and same-vs-different-Gaia geometry before parallax or threshold relaxation.")
 return 0
if __name__=="__main__":raise SystemExit(main())
