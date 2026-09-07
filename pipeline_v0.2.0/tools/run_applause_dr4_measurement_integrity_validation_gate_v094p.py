#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import OrderedDict,Counter
from datetime import datetime,timezone
import argparse,csv,hashlib,json,math,warnings
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_measurement_integrity_validation_gate_contract_v094p.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_measurement_integrity_validation_gate_parent_provenance_v094p.json"
EXPECTED="8071cd07333efc9b443b03f57f903bc56650323885f8a639dea0a929d1d7b5a6";RE=6378.137;AU=149597870.7

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
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
def parse_dt(v):
 s=str(v or "").strip().replace("Z","+00:00")
 if not s:return None
 try:d=datetime.fromisoformat(s)
 except:return None
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.astimezone(timezone.utc)
def qstats(vals):
 if not vals:return {"n":0,"min":None,"p10":None,"median":None,"p90":None,"p95":None,"max":None}
 a=np.asarray(vals,float);return {"n":int(len(a)),"min":float(np.min(a)),"p10":float(np.percentile(a,10)),"median":float(np.median(a)),"p90":float(np.percentile(a,90)),"p95":float(np.percentile(a,95)),"max":float(np.max(a))}
def exact_int_col(col,name):
 a=np.ma.asarray(col);mask=np.ma.getmaskarray(a);data=np.asarray(a.data);out=np.empty(len(data),dtype=np.int64)
 if np.issubdtype(data.dtype,np.integer):out[:]=data.astype(np.int64,copy=False)
 else:
  for i,v in enumerate(data):
   if mask[i]:out[i]=-1;continue
   s=str(v).strip()
   if not s:out[i]=-1;continue
   if any(c in s.lower() for c in (".","e")):raise RuntimeError(f"{name} raw column is not exact integer dtype/string: {data.dtype}")
   out[i]=int(s)
 out[mask]=-1;return out
def parse_poly(v):
 import re
 a=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
 if len(a)<8:return None
 a=a[-8:];p=[(a[i]%360,a[i+1]) for i in range(0,8,2)];return None if any(not(-90<=d<=90) for _,d in p) else p
def xyz(ra,dec):
 ra=np.deg2rad(np.asarray(ra,float));dec=np.deg2rad(np.asarray(dec,float));c=np.cos(dec);return np.column_stack((c*np.cos(ra),c*np.sin(ra),np.sin(dec)))
def one_xyz(ra,dec):return xyz([ra],[dec])[0]
def center(polys):
 q=np.vstack([one_xyz(ra,dec) for p in polys for ra,dec in p]);v=q.sum(0);v/=np.linalg.norm(v);return math.degrees(math.atan2(v[1],v[0]))%360,math.degrees(math.asin(np.clip(v[2],-1,1)))
def project(ra,dec,ra0,dec0):
 r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0);dr=(r-r0+math.pi)%(2*math.pi)-math.pi
 den=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr);ok=den>1e-10;x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
 x[ok]=np.cos(d[ok])*np.sin(dr[ok])/den[ok];y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/den[ok];return x,y,ok
def inside(x,y,p):
 px=np.asarray([q[0] for q in p]);py=np.asarray([q[1] for q in p]);z=np.zeros(len(x),bool);j=len(px)-1
 for i in range(len(px)):
  cross=((py[i]>y)!=(py[j]>y))&np.isfinite(x)&np.isfinite(y);den=py[j]-py[i]
  if abs(den)>1e-20:z^=cross&(x<(px[j]-px[i])*(y-py[i])/den+px[i])
  j=i
 return z
def poly_mask(ra,dec,p):
 ra0,dec0=center([p]);x,y,ok=project(ra,dec,ra0,dec0);px,py,pok=project([q[0] for q in p],[q[1] for q in p],ra0,dec0)
 return np.zeros(len(np.asarray(ra)),bool) if not np.all(pok) else ok&inside(x,y,list(zip(px,py)))
def common_mask(ra,dec,pa,pb):
 ra0,dec0=center([pa,pb]);x,y,ok=project(ra,dec,ra0,dec0);ax,ay,aok=project([q[0] for q in pa],[q[1] for q in pa],ra0,dec0);bx,by,bok=project([q[0] for q in pb],[q[1] for q in pb],ra0,dec0)
 return np.zeros(len(np.asarray(ra)),bool) if (not np.all(aok) or not np.all(bok)) else ok&inside(x,y,list(zip(ax,ay)))&inside(x,y,list(zip(bx,by)))
def corrected_coords(site,lon,lat):
 if lon is None or lat is None:return None,None
 return (lat,lon) if site=="Dr. Remeis-Observatory, Bamberg, Germany" else (lon,lat)
def ecef(lat,lon):
 a=6378.137;f=1/298.257223563;e2=f*(2-f);p=math.radians(lat);l=math.radians(lon);N=a/math.sqrt(1-e2*math.sin(p)**2);return np.array([N*math.cos(p)*math.cos(l),N*math.cos(p)*math.sin(l),N*(1-e2)*math.sin(p)])
def gmst_eci(v,d):
 J=d.timestamp()/86400+2440587.5;T=(J-2451545)/36525;th=math.radians((280.46061837+360.98564736629*(J-2451545)+.000387933*T*T-T*T*T/38710000)%360);c,s=math.cos(th),math.sin(th);x,y,z=v;return np.array([c*x-s*y,s*x+c*y,z])
def angle_arcsec(a,b):
 a=np.asarray(a,float);b=np.asarray(b,float);na=np.linalg.norm(a);nb=np.linalg.norm(b)
 if na<=0 or nb<=0:return None
 return math.degrees(math.acos(float(np.clip((a@b)/(na*nb),-1,1))))*3600
def xt_arcsec(B,ua,ub):
 n=np.cross(B,ua);nn=np.linalg.norm(n)
 if nn<=1e-15:return None
 n/=nn;return math.degrees(math.asin(min(1.,abs(float(ub@n)))))*3600
class LRU:
 def __init__(self,n=8):self.n=n;self.d=OrderedDict()
 def get(self,k,p):
  if k in self.d:self.d.move_to_end(k);return self.d[k]
  z=np.load(p,allow_pickle=False);x={q:np.asarray(z[q]) for q in z.files if not q.endswith("_scalar")};self.d[k]=x
  while len(self.d)>self.n:self.d.popitem(last=False)
  return x

def gaia_audit(root,p):
 from astropy.table import Table
 inv=list(rows(root/p["source_cache_inventory"]["path"]));rec={(inum(r["scan_id"]),inum(r["solution_num"])):r for r in inv};positive={k for k,r in rec.items() if int(r["rows"])>0};done=set();first={};coll=set();conflicts=0;tot=pos=chg=poschg=0;mx=0;srcmis=0
 for fi,rr in enumerate(p["raw_votables"]["files"],1):
  f=root/rr["path"]
  if not f.is_file() or f.stat().st_size!=int(rr["size_bytes"]) or sha(f)!=rr["sha256"]:raise SystemExit(f"Raw provenance mismatch: {f}")
  t=Table.read(f,format="votable");cm={str(c).lower():str(c) for c in t.colnames};req=("source_id","scan_id","solution_num","gaiaedr3_id")
  if any(x not in cm for x in req):raise SystemExit(f"Raw file missing required fields: {f}")
  src=exact_int_col(t[cm["source_id"]],"source_id");scan=exact_int_col(t[cm["scan_id"]],"scan_id");sol=exact_int_col(t[cm["solution_num"]],"solution_num");gid=exact_int_col(t[cm["gaiaedr3_id"]],"gaiaedr3_id")
  if len(src):
   for sid,sn in np.unique(np.column_stack((scan,sol)),axis=0):
    k=(int(sid),int(sn))
    if k not in positive or k in done:continue
    m=(scan==sid)&(sol==sn);rs=src[m];rg=gid[m];r=rec[k];cf=root/r["relative_path"]
    if not cf.is_file() or cf.stat().st_size!=int(r["size_bytes"]) or sha(cf)!=r["sha256"]:raise SystemExit(f"Cache mismatch: {cf}")
    z=np.load(cf,allow_pickle=False);cs=np.asarray(z["source_id"],np.int64);cg=np.asarray(z["gaia_id"],np.int64)
    if len(rs)!=len(cs):continue
    ir=np.argsort(rs);ic=np.argsort(cs)
    if not np.array_equal(rs[ir],cs[ic]):srcmis+=1;continue
    rg=rg[ir];cg=cg[ic];done.add(k);tot+=len(rg);pm=rg>0;pos+=int(pm.sum());chg+=int(np.sum(rg!=cg));poschg+=int(np.sum((rg>0)!=(cg>0)));bm=(rg>0)&(cg>0)
    if np.any(bm):
     dd=np.abs(rg[bm].astype(object)-cg[bm].astype(object));mx=max(mx,int(max(dd)) if len(dd) else 0)
     for cval,rval in np.unique(np.column_stack((cg[bm],rg[bm])),axis=0):
      cval=int(cval);rval=int(rval);pv=first.get(cval)
      if pv is None:first[cval]=rval
      elif pv!=rval:coll.add(cval);conflicts+=1
  del t
  if fi%25==0:log(f"Gaia exact-ID audit: {fi}/{len(p['raw_votables']['files'])}; keys {len(done)}/{len(positive)}")
 return {"positive_row_cache_keys":len(positive),"positive_row_cache_keys_exactly_verified":len(done),"positive_row_cache_keys_not_verified":len(positive-done),"source_id_set_mismatch_keys":srcmis,"rows_compared":tot,"positive_exact_raw_gaia_rows":pos,"gaia_id_rows_changed_by_cached_conversion":chg,"gaia_id_changed_fraction_positive_rows":chg/pos if pos else None,"gaia_positive_status_changes":poschg,"max_absolute_integer_delta":mx,"cached_gaia_values_with_multiple_distinct_exact_raw_ids":len(coll),"additional_distinct_mapping_conflict_events":conflicts,"exact_raw_coverage_complete_for_positive_row_keys":len(done)==len(positive),"ids_emitted":0}

def timing_frame_footprint(root,p):
 from astropy.coordinates import EarthLocation
 from astropy.time import Time
 import astropy.units as u
 from astropy.utils import iers
 iers.conf.auto_download=False
 try:iers.conf.iers_degraded_accuracy="warn"
 except:pass
 plan=list(rows(root/p["frozen_plan"]["path"]));exp={}
 for r in rows(root/p["v094d_exposure_full"]["path"]):
  e=inum(r.get("exposure_id"));
  if e is not None:exp[e]=inum(r.get("num_sub"))
 if sha(root/p["v094d_exposure_sub_full"]["path"])!=p["v094d_exposure_sub_full"]["sha256"]:raise SystemExit("exposure_sub hash mismatch")
 site={}
 for r in rows(root/p["plate_site_cache"]["path"]):
  pid=inum(r.get("plate_id"));nm=str(r.get("site_name") or "").strip();lon=fnum(r.get("site_longitude"));lat=fnum(r.get("site_latitude"));cl=corrected_coords(nm,lon,lat)
  if pid is not None:site[pid]=(nm,cl[0],cl[1])
 polys={}
 for r in rows(root/p["solution_full"]["path"]):
  sid=inum(r.get("solution_id"));q=parse_poly(r.get("stc_polygon"));
  if sid is not None and q is not None:polys[sid]=q
 inv=list(rows(root/p["source_cache_inventory"]["path"]));kp={(inum(r["scan_id"]),inum(r["solution_num"])):root/r["relative_path"] for r in inv};cache=LRU(8)
 overlap=multi=anyms=bothms=0;maxdur=[];alldur=[];totdur=[];fg=[];sweep=[];warn=Counter();syn={str(d):{"x":[],"gt2":0,"gt7":0,"n":0} for d in (2*RE,0.01*AU,0.1*AU)};fa=[];fb=[];own=common=sideop=0;sidefrac=[]
 def proper(lon,lat,dt):
  loc=EarthLocation.from_geodetic(lon*u.deg,lat*u.deg,0*u.m,ellipsoid="WGS84")
  with warnings.catch_warnings(record=True) as ww:
   warnings.simplefilter("always");v=loc.get_gcrs(Time(dt)).cartesian.xyz.to_value(u.km)
   for w in ww:warn[type(w.message).__name__]+=1
  return np.asarray(v,float)
 for ix,r in enumerate(plan,1):
  if str(r.get("timing_bin"))!="OVERLAP":continue
  overlap+=1
  try:o=json.loads(r.get("fragment_overlap_intervals_json") or "[]")
  except:o=[]
  iv=[]
  for q in o:
   s,e=parse_dt(q.get("start_utc")),parse_dt(q.get("end_utc"))
   if s and e and e>s:iv.append((s,e));alldur.append((e-s).total_seconds())
  if len(iv)>1:multi+=1
  if not iv:continue
  maxdur.append(max((e-s).total_seconds() for s,e in iv));totdur.append(sum((e-s).total_seconds() for s,e in iv))
  na,nb=exp.get(inum(r.get("exposure_a"))),exp.get(inum(r.get("exposure_b")))
  if (na and na>1) or (nb and nb>1):anyms+=1
  if (na and na>1) and (nb and nb>1):bothms+=1
  sa,sb=site.get(inum(r.get("plate_a"))),site.get(inum(r.get("plate_b")))
  if not sa or not sb or None in (sa[1],sa[2],sb[1],sb[2]):continue
  lona,lata,lonb,latb=sa[1],sa[2],sb[1],sb[2];va,vb=ecef(lata,lona),ecef(latb,lonb);bc=np.zeros(3);bp=np.zeros(3);tw=0.
  for s,e in iv:
   w=(e-s).total_seconds();m=s+(e-s)/2;cg=gmst_eci(vb,m)-gmst_eci(va,m);pg=proper(lonb,latb,m)-proper(lona,lata,m);bc+=w*cg;bp+=w*pg;tw+=w;a=angle_arcsec(cg,pg)
   if a is not None:fg.append(a)
   ps=proper(lonb,latb,s)-proper(lona,lata,s);pe=proper(lonb,latb,e)-proper(lona,lata,e);a=angle_arcsec(ps,pe)
   if a is not None:sweep.append(a)
  if tw<=0:continue
  bc/=tw;bp/=tw;a=angle_arcsec(bc,bp)
  if a is not None:fg.append(a)
  sidA,sidB=inum(r.get("solution_id_a")),inum(r.get("solution_id_b"));pa,pb=polys.get(sidA),polys.get(sidB)
  if pa and pb:
   cr,cd=center([pa,pb]);axis=one_xyz(cr,cd)
   for s,e in iv:
    for t in (s,e):
     ra=proper(lona,lata,t);rb=proper(lonb,latb,t)
     for D in (2*RE,0.01*AU,0.1*AU):
      obj=D*axis;ua=obj-ra;ub=obj-rb;ua/=np.linalg.norm(ua);ub/=np.linalg.norm(ub);xt=xt_arcsec(bp,ua,ub)
      if xt is not None:
       z=syn[str(D)];z["x"].append(xt);z["n"]+=1;z["gt2"]+=xt>2;z["gt7"]+=xt>7
  av,bv=fnum(r.get("common_fraction_of_a")),fnum(r.get("common_fraction_of_b"));fa.append(av) if av is not None else None;fb.append(bv) if bv is not None else None
  ka=(inum(r.get("scan_id_a")),inum(r.get("solution_num_a")));kb=(inum(r.get("scan_id_b")),inum(r.get("solution_num_b")))
  if pa and pb and ka in kp and kb in kp:
   A=cache.get(ka,kp[ka]);B=cache.get(kb,kp[kb]);oa=poly_mask(A["ra"],A["dec"],pa);ob=poly_mask(B["ra"],B["dec"],pb);ca=common_mask(A["ra"],A["dec"],pa,pb);cb=common_mask(B["ra"],B["dec"],pa,pb);oi=int(oa.sum()+ob.sum());ci=int(ca.sum()+cb.sum());own+=oi;common+=ci;sideop+=oi>ci
   if oi:sidefrac.append((oi-ci)/oi)
  if ix%100==0:log(f"Timing/frame/footprint audit: plan row {ix}/1240")
 if overlap!=1081:raise SystemExit(f"Overlap replay mismatch: {overlap}")
 timing={"overlap_opportunities":overlap,"opportunities_with_multiple_overlap_intervals":multi,"opportunities_with_any_num_sub_gt1":anyms,"opportunities_with_both_num_sub_gt1":bothms,"max_single_overlap_interval_seconds":qstats(maxdur),"all_overlap_interval_duration_seconds":qstats(alldur),"total_overlap_seconds_per_opportunity":qstats(totdur),"opportunities_max_interval_gt_60s":sum(x>60 for x in maxdur),"opportunities_max_interval_gt_300s":sum(x>300 for x in maxdur),"opportunities_max_interval_gt_600s":sum(x>600 for x in maxdur),"opportunities_max_interval_gt_1800s":sum(x>1800 for x in maxdur)}
 frame={"current_gmst_vs_astropy_gcrs_baseline_angle_arcsec":qstats(fg),"proper_gcrs_baseline_start_to_end_sweep_arcsec":qstats(sweep),"astropy_iers_auto_download":False,"astropy_warning_classes":dict(warn)}
 ss={D:{"samples":z["n"],"cross_track_arcsec":qstats(z["x"]),"fraction_over_2arcsec":z["gt2"]/z["n"] if z["n"] else None,"fraction_over_7arcsec":z["gt7"]/z["n"] if z["n"] else None} for D,z in syn.items()}
 footprint={"common_fraction_of_a":qstats(fa),"common_fraction_of_b":qstats(fb),"own_footprint_strict_hq_source_incidences":own,"common_intersection_strict_hq_source_incidences":common,"side_only_strict_hq_source_incidences":own-common,"side_only_incidence_fraction":(own-common)/own if own else None,"opportunities_with_any_side_only_strict_hq_sources":sideop,"per_opportunity_side_only_fraction":qstats(sidefrac)}
 return timing,frame,ss,footprint

def self_test():
 x=2**60+128
 assert int(float(x))!=x
 a=np.ma.array(np.array([x],dtype=np.int64),mask=[False]);assert exact_int_col(a,"gaia")[0]==x
 p=[(0,0),(1,0),(1,1),(0,1)];assert poly_mask(np.array([.5,1.5]),np.array([.5,.5]),p).tolist()==[True,False]
 print("v094p measurement-integrity self-test PASS");return 0

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit("v094p contract SHA mismatch")
 p=json.loads(PROV.read_text(encoding="utf-8"))
 if p.get("status")!="PARENT_PROVENANCE_PREPARED_BEFORE_V094P_MEASUREMENT_INTEGRITY_VALUES":raise SystemExit("Bad v094p provenance")
 for sec in ("frozen_plan","source_cache_inventory","plate_site_cache","solution_full","v094d_exposure_full","v094d_exposure_sub_full"):
  rec=p[sec];f=ROOT/rec["path"]
  if not f.is_file() or sha(f)!=rec["sha256"]:raise SystemExit(f"Runtime frozen-input mismatch: {sec}")
 log("Starting exact Gaia-ID integrity audit from retained raw VOTables (NO network)");gaia=gaia_audit(ROOT,p)
 log("Starting timing / celestial-frame / footprint audit");timing,frame,synth,foot=timing_frame_footprint(ROOT,p)
 rd=ROOT/"results"/"applause_dr4_measurement_integrity_validation_gate_v094p";rd.mkdir(parents=True,exist_ok=True);rp=rd/"applause_dr4_measurement_integrity_validation_gate_v094p.json"
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_measurement_integrity_validation_gate_v094p","contract_sha256":EXPECTED,"parent_provenance_sha256":sha(PROV),"gaia_id_integrity":gaia,"timing_fragment_integrity":timing,"celestial_frame_integrity":frame,"synthetic_time_within_overlap_recovery":synth,"footprint_scope_integrity":foot,"inference_status":{"v094n_v094o_parallax_inference":"HOLD_METHOD_VALIDATION","v094o_rotation_counts":"EXPLORATORY_DIRECTIONAL_DIAGNOSTIC_ONLY","candidate_unblinding_allowed":False},"guards":{"network_queries":0,"private_candidate_map_reads":0,"candidate_identity_inspection":0,"source_or_gaia_ids_emitted":0,"coordinates_emitted":0,"pixels":0,"fits":0,"registration":0,"new_physical_source_pairing":0}}
 rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8");(rd/"v094p_output_manifest.sha256").write_text(f"{sha(rp)}  {rp.name}\n",encoding="utf-8")
 print("\n"+"="*108);print("v094p MEASUREMENT-INTEGRITY VALIDATION GATE COMPLETE");print("="*108)
 print(f"Gaia positive-row cache keys verified:        {gaia['positive_row_cache_keys_exactly_verified']} / {gaia['positive_row_cache_keys']}")
 print(f"Gaia rows compared:                           {gaia['rows_compared']:,}")
 print(f"Gaia ID rows changed by float conversion:     {gaia['gaia_id_rows_changed_by_cached_conversion']:,}")
 print(f"Gaia positivity changes:                      {gaia['gaia_positive_status_changes']:,}")
 print(f"Cached Gaia values with >1 exact raw ID:       {gaia['cached_gaia_values_with_multiple_distinct_exact_raw_ids']:,}")
 print(f"Overlap opportunities:                        {timing['overlap_opportunities']}")
 print(f"Any side num_sub>1:                           {timing['opportunities_with_any_num_sub_gt1']}")
 print(f"Max-overlap interval >10 min opportunities:   {timing['opportunities_max_interval_gt_600s']}")
 print(f"GMST-vs-GCRS baseline median arcsec:           {frame['current_gmst_vs_astropy_gcrs_baseline_angle_arcsec']['median']}")
 print(f"GMST-vs-GCRS baseline p95 arcsec:              {frame['current_gmst_vs_astropy_gcrs_baseline_angle_arcsec']['p95']}")
 for D,z in synth.items():print(f"Synthetic D={D} km: fraction >7arcsec timing XT: {z['fraction_over_7arcsec']}")
 print(f"Own-footprint strict-HQ incidences:            {foot['own_footprint_strict_hq_source_incidences']:,}")
 print(f"Common-intersection strict-HQ incidences:      {foot['common_intersection_strict_hq_source_incidences']:,}")
 print(f"Side-only strict-HQ incidence fraction:        {foot['side_only_incidence_fraction']}")
 print("Private candidate identities inspected:        0");print("Network / pixels / registration / pairing:    0 / 0 / 0 / 0");print("STOP: interpret measurement integrity before rebuilding any parallax matcher.")
 return 0
if __name__=="__main__":raise SystemExit(main())
