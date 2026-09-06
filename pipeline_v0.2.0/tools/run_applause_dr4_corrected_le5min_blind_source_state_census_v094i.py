#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime
import argparse,csv,gzip,hashlib,json,math,re,time,urllib.parse,urllib.request,xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_corrected_le5min_blind_source_state_census_contract_v094i.json"
PROVENANCE=ROOT/"research"/"prospective_freezes"/"applause_dr4_corrected_le5min_blind_source_state_parent_provenance_v094i.json"
PLAN=ROOT/"research"/"prospective_freezes"/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv"
EXPECTED_CONTRACT_SHA="19abb177af6c046958e79e35b775a1bd971a71b89c77e24037d5f48992210bc2"
TAP_ASYNC="https://www.plate-archive.org/tap/async"
MAXREC=1000000
INITIAL_KEYS=4
FIELDS=[
 "source_id","process_id","scan_id","plate_id","archive_id","solution_num",
 "model_prediction","sextractor_flags","ra_icrs","dec_icrs","ra_error","dec_error",
 "nn_dist","dist_edge","annular_bin","natmag","natmag_error","phot_range_flags",
 "gaiaedr3_id","gaiaedr3_dist","gaiaedr3_neighbors","match_radius"
]
WORK=ROOT/"work"/"applause_dr4_corrected_le5min_blind_source_state_census_v094i"
RAW=WORK/"tap_raw"
NPZ=WORK/"hq_scan_solution_npz"
STATE=WORK/"state"
RESULT=ROOT/"results"/"applause_dr4_corrected_le5min_blind_source_state_census_v094i"

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def log(s=""):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
def fnum(v):
 try:
  x=float(str(v if v is not None else "").strip());return x if math.isfinite(x) else None
 except:return None
def inum(v):
 x=fnum(v)
 if x is None:return None
 r=int(round(x));return r if abs(x-r)<1e-7 else None
def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
def wjson(p,o):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".tmp")
 t.write_text(json.dumps(o,indent=2,sort_keys=True)+"\n",encoding="utf-8");t.replace(p)
def parse_poly(v):
 nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
 if len(nums)<8:return None
 nums=nums[-8:];p=[(nums[i]%360.0,nums[i+1]) for i in range(0,8,2)]
 return None if any(not(-90<=d<=90) for _,d in p) else p
def xyz(ra,dec):
 ra=np.deg2rad(np.asarray(ra,dtype=float));dec=np.deg2rad(np.asarray(dec,dtype=float));c=np.cos(dec)
 return np.column_stack((c*np.cos(ra),c*np.sin(ra),np.sin(dec)))
def arcsec_from_chord(d):
 d=np.clip(np.asarray(d,dtype=float),0.0,2.0)
 return np.degrees(2*np.arcsin(d/2))*3600.0
def sepbin(x):
 if x is None or not math.isfinite(float(x)):return "NO_OPPOSITE_SOURCE"
 x=float(x)
 if x<=1:return "LE1"
 if x<=3:return "GT1_LE3"
 if x<=5:return "GT3_LE5"
 if x<=10:return "GT5_LE10"
 if x<=30:return "GT10_LE30"
 if x<=60:return "GT30_LE60"
 return "GT60"
def tangent_center(polys):
 xs=ys=zs=0.0
 for poly in polys:
  for ra,dec in poly:
   r,d=math.radians(ra),math.radians(dec);c=math.cos(d);xs+=c*math.cos(r);ys+=c*math.sin(r);zs+=math.sin(d)
 return math.degrees(math.atan2(ys,xs))%360.0, math.degrees(math.atan2(zs,math.hypot(xs,ys)))
def project_points(ra,dec,ra0,dec0):
 r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0)
 dr=(r-r0+math.pi)%(2*math.pi)-math.pi
 cosc=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr)
 ok=cosc>1e-10
 x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
 x[ok]=np.cos(d[ok])*np.sin(dr[ok])/cosc[ok]
 y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/cosc[ok]
 return x,y,ok
def project_poly(poly,ra0,dec0):
 ra=np.asarray([x[0] for x in poly]);dec=np.asarray([x[1] for x in poly]);x,y,ok=project_points(ra,dec,ra0,dec0)
 return None if not np.all(ok) else list(zip(x.tolist(),y.tolist()))
def inside_projected(x,y,poly):
 if poly is None:return np.zeros(len(x),dtype=bool)
 px=np.asarray([p[0] for p in poly]);py=np.asarray([p[1] for p in poly]);inside=np.zeros(len(x),dtype=bool);j=len(px)-1
 valid=np.isfinite(x)&np.isfinite(y)
 for i in range(len(px)):
  yi,yj=py[i],py[j];cross=((yi>y)!=(yj>y))&valid
  den=(yj-yi)
  if abs(den)>1e-20:
   xcross=(px[j]-px[i])*(y-yi)/den+px[i];inside^=cross&(x<xcross)
  j=i
 return inside
def common_mask(ra,dec,pa,pb):
 ra0,dec0=tangent_center([pa,pb]);x,y,ok=project_points(ra,dec,ra0,dec0)
 return ok & inside_projected(x,y,project_poly(pa,ra0,dec0)) & inside_projected(x,y,project_poly(pb,ra0,dec0))
def keyfile(key):
 sid,snum=key;return NPZ/f"scan_{sid}_solution_{snum}.npz"
def validate_npz(p,key):
 try:
  z=np.load(p,allow_pickle=False);n=len(z["source_id"])
  return all(len(z[k])==n for k in ("ra","dec","gaia_id","model_prediction","sextractor_flags")) and int(z["scan_id_scalar"][0])==key[0] and int(z["solution_num_scalar"][0])==key[1]
 except:return False
def save_key_npz(key,cols):
 NPZ.mkdir(parents=True,exist_ok=True);sid,snum=key
 p=keyfile(key);t=p.with_suffix(".npz.tmp");arrays={}
 intmap={"gaiaedr3_id":"gaia_id"}
 floatmap={"ra_icrs":"ra","dec_icrs":"dec"}
 arrays["source_id"]=np.asarray(cols["source_id"],dtype=np.int64)
 if len(np.unique(arrays["source_id"])) != len(arrays["source_id"]):
  raise RuntimeError(f"PROVENANCE HOLD: duplicate source_id within exact scan/solution key {key}")
 for name in ("process_id","plate_id","archive_id","gaiaedr3_id","gaiaedr3_neighbors","annular_bin","phot_range_flags","sextractor_flags"):
  arrays[intmap.get(name,name)]=np.asarray(cols[name],dtype=np.int64)
 for name in ("model_prediction","ra_icrs","dec_icrs","ra_error","dec_error","nn_dist","dist_edge","natmag","natmag_error","gaiaedr3_dist","match_radius"):
  arrays[floatmap.get(name,name)]=np.asarray(cols[name],dtype=np.float64)
 arrays["scan_id_scalar"]=np.asarray([sid],dtype=np.int64);arrays["solution_num_scalar"]=np.asarray([snum],dtype=np.int64)
 with t.open("wb") as f:np.savez_compressed(f,**arrays)
 t.replace(p)
 if not validate_npz(p,key):raise RuntimeError(f"NPZ verification failed for {key}")
 return p,len(arrays["source_id"])
def masked_val(v,kind):
 try:
  if np.ma.is_masked(v):return -1 if kind=="int" else np.nan
 except:pass
 if kind=="int":
  x=inum(v);return -1 if x is None else x
 x=fnum(v);return np.nan if x is None else x
def phase(job):
 with urllib.request.urlopen(job+"/phase",timeout=120) as r:return r.read().decode("utf-8","replace").strip().upper()
def discover(job):
 try:
  with urllib.request.urlopen(job,timeout=120) as r:body=r.read().decode("utf-8","replace")
  root=ET.fromstring(body)
  for el in root.iter():
   if el.tag.lower().endswith("result"):
    href=el.attrib.get("{http://www.w3.org/1999/xlink}href") or el.attrib.get("href")
    if href:return urllib.parse.urljoin(job+"/",href)
 except:pass
 for s in ("/results/result","/results/votable"):
  u=job+s
  try:
   with urllib.request.urlopen(u,timeout=120) as r:h=r.read(512)
   if b"VOTABLE" in h.upper() or h.lstrip().startswith(b"<?xml"):return u
  except:pass
 raise RuntimeError("Could not discover TAP result URL")
def tap_once(keys):
 from astropy.table import Table
 keys=tuple(sorted(keys));kh=hashlib.sha256(";".join(f"{a}:{b}" for a,b in keys).encode()).hexdigest()[:20]
 RAW.mkdir(parents=True,exist_ok=True);raw=RAW/f"group_{kh}.vot"
 cond=" OR ".join(f"(scan_id={sid} AND solution_num={sn})" for sid,sn in keys)
 q=("SELECT "+",".join(FIELDS)+" FROM applause_dr4.source_calib WHERE ("+cond+") "
    "AND ra_icrs IS NOT NULL AND dec_icrs IS NOT NULL "
    "AND model_prediction >= 0.9 AND sextractor_flags = 0")
 if raw.is_file() and raw.stat().st_size>100:
  try:return Table.read(raw,format="votable"),{"cache":"reused","raw":str(raw.relative_to(ROOT)).replace("\\","/"),"sha256":sha(raw),"keys":len(keys)}
  except:raw.unlink(missing_ok=True)
 data=urllib.parse.urlencode({"REQUEST":"doQuery","LANG":"ADQL","FORMAT":"votable","QUERY":q,"MAXREC":str(MAXREC),"PHASE":"RUN"}).encode()
 req=urllib.request.Request(TAP_ASYNC,data=data,method="POST")
 with urllib.request.urlopen(req,timeout=180) as r:
  job=r.geturl().rstrip("/");body=r.read(20000).decode("utf-8","replace");loc=r.headers.get("Location")
  if loc:job=urllib.parse.urljoin(job+"/",loc).rstrip("/")
 if "/tap/async/" not in job:
  m=re.search(r'https?://[^"\s<]+/tap/async/[^"\s<]+',body)
  if m:job=m.group(0).rstrip("/")
 if "/tap/async/" not in job:raise RuntimeError(f"Could not resolve TAP job URL: {job}")
 t0=time.time()
 while True:
  ph=phase(job)
  if "COMPLETED" in ph:break
  if "ERROR" in ph or "ABORTED" in ph:raise RuntimeError(f"TAP job {ph}")
  if time.time()-t0>4*3600:raise RuntimeError("TAP job exceeded 4 hours")
  time.sleep(10)
 url=discover(job);tmp=raw.with_suffix(".vot.part")
 with urllib.request.urlopen(url,timeout=3600) as r,tmp.open("wb") as f:
  while True:
   b=r.read(1024*1024)
   if not b:break
   f.write(b)
 tmp.replace(raw);tbl=Table.read(raw,format="votable")
 return tbl,{"cache":"network","raw":str(raw.relative_to(ROOT)).replace("\\","/"),"sha256":sha(raw),"keys":len(keys)}
def table_to_keys(tbl,keys):
 cols={str(c).lower():str(c) for c in tbl.colnames}
 miss=[x for x in FIELDS if x not in cols]
 if miss:raise RuntimeError(f"source_calib response missing fields {miss}")
 groups=defaultdict(lambda:defaultdict(list))
 for row in tbl:
  sid=masked_val(row[cols["scan_id"]],"int");sn=masked_val(row[cols["solution_num"]],"int");key=(sid,sn)
  if key not in keys:continue
  g=groups[key]
  for name in FIELDS:
   if name in ("scan_id","solution_num"):continue
   kind="int" if name in ("source_id","process_id","plate_id","archive_id","sextractor_flags","annular_bin","phot_range_flags","gaiaedr3_id","gaiaedr3_neighbors") else "float"
   g[name].append(masked_val(row[cols[name]],kind))
 out={}
 for key in keys:
  g=groups.get(key,defaultdict(list))
  for name in FIELDS:
   if name in ("scan_id","solution_num"):continue
   g.setdefault(name,[])
  p,c=save_key_npz(key,g);out[key]={"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"rows":c}
 return out
def acquire_group(keys,stats):
 keys=tuple(sorted(keys));missing=[k for k in keys if not validate_npz(keyfile(k),k)]
 if not missing:stats["keys_reused"]+=len(keys);return
 keys=tuple(missing);attempts=5 if len(keys)==1 else 2;err=None
 for at in range(1,attempts+1):
  try:
   log(f"source_calib HQ group n={len(keys)} attempt {at}")
   tbl,meta=tap_once(keys)
   if len(tbl)>=MAXREC:
    if len(keys)==1:raise RuntimeError("single scan/solution key reached MAXREC; explicit truncation HOLD")
    raise OverflowError("group reached MAXREC")
   table_to_keys(tbl,set(keys));stats["leaf_queries"]+=1;stats["rows_returned"]+=len(tbl);stats["keys_acquired"]+=len(keys);stats["raw_responses"].append(meta);return
  except Exception as e:
   err=e;log(f"source_calib group n={len(keys)} failed: {e!r}");time.sleep(min(20,2*at))
 if len(keys)>1:
  m=len(keys)//2;stats["adaptive_splits"]+=1;log(f"adaptive split {len(keys)} -> {m} + {len(keys)-m}")
  acquire_group(keys[:m],stats);acquire_group(keys[m:],stats);return
 raise RuntimeError(f"source acquisition failed for {keys}: {err!r}")
class LRU:
 def __init__(self,n=8):self.n=n;self.d=OrderedDict()
 def get(self,key):
  if key in self.d:self.d.move_to_end(key);return self.d[key]
  z=np.load(keyfile(key),allow_pickle=False);x={k:np.asarray(z[k]) for k in z.files if not k.endswith("_scalar")}
  self.d[key]=x
  while len(self.d)>self.n:self.d.popitem(last=False)
  return x
def load_solution_polys(solpath):
 out={}
 for r in rows(solpath):
  sid=inum(r.get("solution_id"));p=parse_poly(r.get("stc_polygon"))
  if sid is not None and p is not None:out[sid]=p
 return out
def count_bins(vals):
 c=Counter()
 for x in vals:c[sepbin(x)]+=1
 return c
def mutual_geometry(a,b):
 na,nb=len(a["source_id"]),len(b["source_id"]);dirA=np.full(na,np.inf);dirB=np.full(nb,np.inf);pairs=[]
 if na==0 or nb==0:return dirA,dirB,pairs
 xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb)
 da,ib=tb.query(xa,k=1);db,ia=ta.query(xb,k=1);dirA=arcsec_from_chord(da);dirB=arcsec_from_chord(db)
 for i,j in enumerate(ib.astype(int)):
  if j<nb and int(ia[j])==i:pairs.append((i,j,float(dirA[i])))
 return dirA,dirB,pairs
def subset(x,mask):return {k:v[mask] for k,v in x.items() if len(v)==len(mask)}
def self_test():
 p1=[(0,0),(1,0),(1,1),(0,1)];p2=[(.5,.5),(1.5,.5),(1.5,1.5),(.5,1.5)]
 ra=np.array([.75,.25,1.25]);dec=np.array([.75,.25,.75]);m=common_mask(ra,dec,p1,p2);assert m.tolist()==[True,False,False]
 assert sepbin(.5)=="LE1" and sepbin(4)=="GT3_LE5" and sepbin(70)=="GT60"
 a={"source_id":np.array([1,2]),"ra":np.array([0.,1.]),"dec":np.array([0.,0.])};b={"source_id":np.array([3,4]),"ra":np.array([0.0001,1.0001]),"dec":np.array([0.,0.])}
 _,_,pp=mutual_geometry(a,b);assert len(pp)==2
 print("v094i self-test PASS");return 0
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("v094i contract SHA mismatch")
 if not PROVENANCE.is_file() or not PLAN.is_file():raise SystemExit("Missing frozen v094i provenance/plan")
 prov=json.loads(PROVENANCE.read_text(encoding="utf-8"))
 if prov.get("status")!="PARENT_PROVENANCE_PREPARED_BEFORE_V094I_SOURCE_ACQUISITION":raise SystemExit("Bad v094i parent provenance status")
 if sha(PLAN)!=prov["frozen_le5_plan"]["sha256"] or int(prov["frozen_le5_plan"]["rows"])!=1240:raise SystemExit("Frozen v094i plan mismatch")
 for key,hkey in (("opportunity_csv","opportunity_csv_sha256"),("report","report_sha256"),("output_manifest","output_manifest_sha256"),("contract","contract_sha256"),("runner","runner_sha256")):
  p=ROOT/prov["v094h"][key]
  if not p.is_file() or sha(p)!=prov["v094h"][hkey]:raise SystemExit(f"Frozen v094h parent mismatch: {key}")
 solpath=ROOT/prov["v094d_solution_full"]["path"]
 if not solpath.is_file() or sha(solpath)!=prov["v094d_solution_full"]["sha256"]:raise SystemExit("Frozen solution_full mismatch")
 plan=list(rows(PLAN))
 if len(plan)!=1240:raise SystemExit("Expected 1240 frozen plan rows")
 keys=sorted({(inum(r["scan_id_a"]),inum(r["solution_num_a"])) for r in plan}|{(inum(r["scan_id_b"]),inum(r["solution_num_b"])) for r in plan})
 if any(None in k for k in keys):raise SystemExit("Null scan/solution key in plan")
 log(f"Frozen v094i inputs verified: 1,240 <=5min opportunities; {len(keys)} exact scan/solution keys")
 stats={"initial_groups":0,"leaf_queries":0,"adaptive_splits":0,"keys_acquired":0,"keys_reused":0,"rows_returned":0,"raw_responses":[]}
 for i in range(0,len(keys),INITIAL_KEYS):
  g=keys[i:i+INITIAL_KEYS];stats["initial_groups"]+=1;acquire_group(g,stats)
  if stats["initial_groups"]%25==0:log(f"source acquisition groups: {stats['initial_groups']}/{math.ceil(len(keys)/INITIAL_KEYS)}")
 inv=[]
 for key in keys:
  p=keyfile(key)
  if not validate_npz(p,key):raise SystemExit(f"Missing/invalid acquired key {key}")
  z=np.load(p,allow_pickle=False);inv.append({"scan_id":key[0],"solution_num":key[1],"rows":len(z["source_id"]),"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p)})
 STATE.mkdir(parents=True,exist_ok=True);wjson(STATE/"source_acquisition_manifest_v094i.json",{"status":"COMPLETE","stats":{k:v for k,v in stats.items() if k!="raw_responses"},"products":inv})
 polys=load_solution_polys(solpath);cache=LRU(8);RESULT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
 per_path=RESULT/"per_opportunity_source_state_v094i.csv"
 per_fields=["pair_id","site_pair","timing_bin","epoch_label","min_fragment_gap_seconds","fragment_overlap_count","hq_common_a","hq_common_b","gaia_resolved_a","gaia_resolved_b","gaia_unresolved_a","gaia_unresolved_b","same_gaia_unique_identities","unresolved_mutual_pairs_total","unresolved_mutual_le1","unresolved_mutual_gt1_le3","unresolved_mutual_gt3_le5","unresolved_mutual_gt5_le10","unresolved_mutual_gt10_le30","unresolved_mutual_gt30_le60","unresolved_mutual_gt60","unresolved_a_nearest_le5","unresolved_b_nearest_le5","zero_hq_side"]
 siteagg=defaultdict(Counter);teagg=defaultdict(Counter);glob=Counter()
 pairbank=WORK/"gaia_unresolved_mutual_pairs_le60_v094i.csv.gz";incidence=WORK/"hq_common_source_id_incidences_v094i.i64";incf=incidence.open("wb")
 with per_path.open("w",encoding="utf-8",newline="") as pf,gzip.open(pairbank,"wt",encoding="utf-8",newline="") as bf:
  w=csv.DictWriter(pf,fieldnames=per_fields);w.writeheader();bw=csv.DictWriter(bf,fieldnames=["pair_id","site_pair","timing_bin","source_id_a","source_id_b","separation_arcsec"]);bw.writeheader()
  for ix,r in enumerate(plan,1):
   ka=(inum(r["scan_id_a"]),inum(r["solution_num_a"]));kb=(inum(r["scan_id_b"]),inum(r["solution_num_b"]))
   sa,sb=inum(r["solution_id_a"]),inum(r["solution_id_b"]);pa,pb=polys.get(sa),polys.get(sb)
   if pa is None or pb is None:raise SystemExit(f"Missing selected solution polygon for {r['pair_id']}")
   A,B=cache.get(ka),cache.get(kb);ma=common_mask(A["ra"],A["dec"],pa,pb);mb=common_mask(B["ra"],B["dec"],pa,pb);Ac,Bc=subset(A,ma),subset(B,mb)
   np.asarray(np.unique(Ac["source_id"]),dtype=np.int64).tofile(incf);np.asarray(np.unique(Bc["source_id"]),dtype=np.int64).tofile(incf)
   ga,gb=Ac["gaia_id"],Bc["gaia_id"];ram=ga>0;rbm=gb>0;same=np.intersect1d(np.unique(ga[ram]),np.unique(gb[rbm]),assume_unique=True)
   ua,ub=subset(Ac,~ram),subset(Bc,~rbm);da,db,mp=mutual_geometry(ua,ub);bins=count_bins([x[2] for x in mp])
   for ia,ib,ss in mp:
    if ss<=60:bw.writerow({"pair_id":r["pair_id"],"site_pair":r["site_pair"],"timing_bin":r["timing_bin"],"source_id_a":int(ua["source_id"][ia]),"source_id_b":int(ub["source_id"][ib]),"separation_arcsec":f"{ss:.8f}"})
   out={"pair_id":r["pair_id"],"site_pair":r["site_pair"],"timing_bin":r["timing_bin"],"epoch_label":r["epoch_label"],"min_fragment_gap_seconds":r["min_fragment_gap_seconds"],"fragment_overlap_count":r["fragment_overlap_count"],"hq_common_a":len(Ac["source_id"]),"hq_common_b":len(Bc["source_id"]),"gaia_resolved_a":int(np.sum(ram)),"gaia_resolved_b":int(np.sum(rbm)),"gaia_unresolved_a":len(ua["source_id"]),"gaia_unresolved_b":len(ub["source_id"]),"same_gaia_unique_identities":len(same),"unresolved_mutual_pairs_total":len(mp),"unresolved_mutual_le1":bins["LE1"],"unresolved_mutual_gt1_le3":bins["GT1_LE3"],"unresolved_mutual_gt3_le5":bins["GT3_LE5"],"unresolved_mutual_gt5_le10":bins["GT5_LE10"],"unresolved_mutual_gt10_le30":bins["GT10_LE30"],"unresolved_mutual_gt30_le60":bins["GT30_LE60"],"unresolved_mutual_gt60":bins["GT60"],"unresolved_a_nearest_le5":int(np.sum(da<=5)) if len(da) else 0,"unresolved_b_nearest_le5":int(np.sum(db<=5)) if len(db) else 0,"zero_hq_side":int(len(Ac["source_id"])==0 or len(Bc["source_id"])==0)}
   w.writerow(out)
   vals={"opportunities":1,"hq_common_a":out["hq_common_a"],"hq_common_b":out["hq_common_b"],"gaia_resolved_a":out["gaia_resolved_a"],"gaia_resolved_b":out["gaia_resolved_b"],"gaia_unresolved_a":out["gaia_unresolved_a"],"gaia_unresolved_b":out["gaia_unresolved_b"],"same_gaia_unique_identities":out["same_gaia_unique_identities"],"unresolved_mutual_pairs_total":out["unresolved_mutual_pairs_total"],"unresolved_mutual_le5":out["unresolved_mutual_le1"]+out["unresolved_mutual_gt1_le3"]+out["unresolved_mutual_gt3_le5"],"unresolved_mutual_le60":out["unresolved_mutual_pairs_total"]-out["unresolved_mutual_gt60"],"zero_hq_side":out["zero_hq_side"]}
   for k,v in vals.items():glob[k]+=v;siteagg[r["site_pair"]][k]+=v;teagg[f"{r['timing_bin']}|{r['epoch_label']}"][k]+=v
   if ix%100==0:log(f"source-state census: {ix}/1240")
 incf.close()
 ninc=incidence.stat().st_size//8
 if ninc:
  mm=np.memmap(incidence,dtype=np.int64,mode="r");uniq,cnt=np.unique(mm,return_counts=True);reuse={"source_incidence_count":int(ninc),"unique_source_ids":int(len(uniq)),"repeated_incidence_count":int(np.sum(cnt)-len(cnt)),"sources_reused_more_than_once":int(np.sum(cnt>1)),"max_opportunity_role_reuse":int(cnt.max()),"repeated_incidence_fraction":float((np.sum(cnt)-len(cnt))/ninc)};del mm,uniq,cnt
 else:reuse={"source_incidence_count":0,"unique_source_ids":0,"repeated_incidence_count":0,"sources_reused_more_than_once":0,"max_opportunity_role_reuse":0,"repeated_incidence_fraction":None}
 def write_agg(path,d):
  fields=["group"]+sorted({k for c in d.values() for k in c})
  with path.open("w",encoding="utf-8",newline="") as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
   for g,c in sorted(d.items(),key=lambda kv:(-kv[1].get("opportunities",0),kv[0])):
    rr={"group":g};rr.update(c);w.writerow(rr)
 site_path=RESULT/"site_pair_source_state_summary_v094i.csv";te_path=RESULT/"timing_epoch_source_state_summary_v094i.csv";write_agg(site_path,siteagg);write_agg(te_path,teagg)
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_corrected_le5min_blind_source_state_census_v094i","contract_sha256":EXPECTED_CONTRACT_SHA,"parent_provenance_sha256":sha(PROVENANCE),"plan_sha256":sha(PLAN),"opportunities_processed":glob["opportunities"],"exact_scan_solution_keys":len(keys),"source_acquisition":{k:v for k,v in stats.items() if k!="raw_responses"},"aggregate_source_state":dict(glob),"source_reuse":reuse,"site_pair_summary":{g:dict(c) for g,c in sorted(siteagg.items(),key=lambda kv:(-kv[1]["opportunities"],kv[0]))},"timing_epoch_summary":{g:dict(c) for g,c in sorted(teagg.items())},"guards":{"candidate_csv_reads":0,"control_catalog_queries":0,"external_gaia_queries":0,"pixels":0,"fits":0,"registration":0,"detector_runs":0,"candidate_human_inspection":0,"candidate_disposition_changes":0},"working_machine_only":{"mutual_pair_bank":str(pairbank.relative_to(ROOT)).replace("\\","/"),"mutual_pair_bank_sha256":sha(pairbank),"source_incidence_stream":str(incidence.relative_to(ROOT)).replace("\\","/"),"source_incidence_stream_sha256":sha(incidence)},"interpretive_stop":"Interpret strict-HQ source-state and site-pair concentration before candidate inspection, pixels, registration or physical parallax pairing.","output_hashes":{}}
 rp=RESULT/"applause_dr4_corrected_le5min_blind_source_state_census_v094i.json"
 for p in (per_path,site_path,te_path):report["output_hashes"][p.name]=sha(p)
 rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8");man=RESULT/"v094i_output_manifest.sha256";man.write_text("".join(f"{sha(p)}  {p.name}\n" for p in (per_path,site_path,te_path,rp)),encoding="utf-8")
 print("\n"+"="*96);print("v094i CORRECTED <=5MIN BLIND SOURCE-STATE CENSUS COMPLETE");print("="*96)
 print(f"Opportunities processed:                   {glob['opportunities']}")
 print(f"Exact scan/solution keys acquired:         {len(keys)}")
 print(f"Strict-HQ common source incidences A+B:    {glob['hq_common_a']+glob['hq_common_b']:,}")
 print(f"Same-Gaia unique identity incidences:      {glob['same_gaia_unique_identities']:,}")
 print(f"Gaia-unresolved HQ incidences A+B:         {glob['gaia_unresolved_a']+glob['gaia_unresolved_b']:,}")
 print(f"Gaia-unresolved mutual pairs <=5 arcsec:   {glob['unresolved_mutual_le5']:,}")
 print(f"Gaia-unresolved mutual pairs <=60 arcsec:  {glob['unresolved_mutual_le60']:,}")
 print(f"Opportunities with a zero-HQ side:         {glob['zero_hq_side']}")
 print(f"Unique HQ source IDs across incidences:    {reuse['unique_source_ids']:,}")
 print(f"Repeated source-incidence fraction:        {reuse['repeated_incidence_fraction']}")
 if siteagg:
  g,c=max(siteagg.items(),key=lambda kv:kv[1]["opportunities"]);print(f"Dominant site pair:                        {g} ({c['opportunities']} opportunities)")
 print("Candidate/source/Gaia IDs emitted:         0");print("Pixels / registration / detector:          0 / 0 / 0")
 print("STOP: interpret strict-HQ aggregate source states before candidate inspection or physical parallax pairing.")
 print("\nSTOP POINT REACHED: do not inspect the machine-only source bank yet.");return 0
if __name__=="__main__":raise SystemExit(main())
