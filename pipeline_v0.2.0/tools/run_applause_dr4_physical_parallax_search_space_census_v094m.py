#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime,timezone
import argparse,csv,hashlib,json,math,re
import numpy as np
from scipy.spatial import cKDTree
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_physical_parallax_search_space_census_contract_v094m.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_physical_parallax_search_space_census_parent_provenance_v094m.json"
EXPECTED="3b59ee389ec1432cfd278e5df98089368fc76dc507ec50d7a4ba53ab142093c1"
RESULT=ROOT/"results"/"applause_dr4_physical_parallax_search_space_census_v094m"
AU=149597870.7;RE=6378.137;ASEC=206264.80624709636
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
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
 d=datetime.fromisoformat(s)
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.astimezone(timezone.utc)
def parse_poly(v):
 nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
 if len(nums)<8:return None
 nums=nums[-8:];return [(nums[i]%360,nums[i+1]) for i in range(0,8,2)]
def xyz(ra,dec):
 ra=np.deg2rad(np.asarray(ra,float));dec=np.deg2rad(np.asarray(dec,float));c=np.cos(dec)
 return np.column_stack((c*np.cos(ra),c*np.sin(ra),np.sin(dec)))
def arcsec(d):
 d=np.clip(np.asarray(d,float),0,2);return np.degrees(2*np.arcsin(d/2))*3600
def center(polys):
 q=np.vstack([xyz([ra],[dec])[0] for p in polys for ra,dec in p]);v=q.sum(0);v/=np.linalg.norm(v)
 return math.degrees(math.atan2(v[1],v[0]))%360,math.degrees(math.asin(v[2]))
def proj(ra,dec,ra0,dec0):
 r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0)
 dr=(r-r0+math.pi)%(2*math.pi)-math.pi;den=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr)
 ok=den>1e-10;x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
 x[ok]=np.cos(d[ok])*np.sin(dr[ok])/den[ok];y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/den[ok]
 return x*ASEC,y*ASEC,ok
def inside(x,y,p):
 px=np.asarray([q[0] for q in p]);py=np.asarray([q[1] for q in p]);z=np.zeros(len(x),bool);j=len(px)-1
 for i in range(len(px)):
  cross=((py[i]>y)!=(py[j]>y))&np.isfinite(x)&np.isfinite(y);den=py[j]-py[i]
  if abs(den)>1e-20:z^=cross&(x<(px[j]-px[i])*(y-py[i])/den+px[i])
  j=i
 return z
def common_mask(ra,dec,pa,pb):
 ra0,dec0=center([pa,pb]);x,y,ok=proj(ra,dec,ra0,dec0)
 ax,ay,_=proj([q[0] for q in pa],[q[1] for q in pa],ra0,dec0);bx,by,_=proj([q[0] for q in pb],[q[1] for q in pb],ra0,dec0)
 return ok&inside(x,y,list(zip(ax,ay)))&inside(x,y,list(zip(bx,by)))
def subset(a,m):return {k:v[m] for k,v in a.items() if hasattr(v,"__len__") and len(v)==len(m)}
def mutual(a,b):
 if len(a["source_id"])==0 or len(b["source_id"])==0:return []
 xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb);da,j=tb.query(xa);db,i=ta.query(xb);s=arcsec(da)
 return [(ii,int(jj),float(s[ii])) for ii,jj in enumerate(j.astype(int)) if int(i[int(jj)])==ii]
def load_npz(p):
 z=np.load(p,allow_pickle=False);return {k:np.asarray(z[k]) for k in z.files if not k.endswith("_scalar")}
def corrected_coords(site,lon,lat):
 if lon is None or lat is None:return None,None
 if site=="Dr. Remeis-Observatory, Bamberg, Germany":return lat,lon
 return lon,lat
def ecef(lat,lon):
 a=6378.137;f=1/298.257223563;e2=f*(2-f);p=math.radians(lat);l=math.radians(lon);N=a/math.sqrt(1-e2*math.sin(p)**2)
 return np.array([N*math.cos(p)*math.cos(l),N*math.cos(p)*math.sin(l),N*(1-e2)*math.sin(p)])
def jd(d):
 return d.timestamp()/86400.0+2440587.5
def eci_from_ecef(v,d):
 J=jd(d);T=(J-2451545.0)/36525.0
 th=math.radians((280.46061837+360.98564736629*(J-2451545.0)+0.000387933*T*T-T*T*T/38710000.0)%360)
 c,s=math.cos(th),math.sin(th);x,y,z=v
 return np.array([c*x-s*y,s*x+c*y,z])
def tangent_components(v,ra,dec):
 r,d=math.radians(ra),math.radians(dec);era=np.array([-math.sin(r),math.cos(r),0.0]);ed=np.array([-math.cos(r)*math.sin(d),-math.sin(r)*math.sin(d),math.cos(d)])
 return float(v@era),float(v@ed)
def dur_weighted_baseline(sitea,siteb,ovs):
 va,vb=ecef(sitea[0],sitea[1]),ecef(siteb[0],siteb[1]);tot=0.0;acc=np.zeros(3)
 for q in ovs:
  s,e=parse_dt(q.get("start_utc")),parse_dt(q.get("end_utc"))
  if not s or not e or e<=s:continue
  w=(e-s).total_seconds();m=s+(e-s)/2
  acc+=w*(eci_from_ecef(vb,m)-eci_from_ecef(va,m));tot+=w
 return (None,0.0) if tot<=0 else (acc/tot,tot)
def bbin(x):
 if x<100:return "LT100"
 if x<250:return "GE100_LT250"
 if x<500:return "GE250_LT500"
 if x<1000:return "GE500_LT1000"
 return "GE1000"
def dbin(au):
 if au<.01:return "LT0P01"
 if au<.1:return "GE0P01_LT0P1"
 if au<1:return "GE0P1_LT1"
 if au<10:return "GE1_LT10"
 if au<100:return "GE10_LT100"
 return "GE100"
def pbin(deg):
 if deg<.1:return "LT0P1"
 if deg<.5:return "GE0P1_LT0P5"
 if deg<1:return "GE0P5_LT1"
 if deg<2:return "GE1_LT2"
 if deg<5:return "GE2_LT5"
 if deg<10:return "GE5_LT10"
 return "GE10"
def med(v):return None if not v else float(np.median(np.asarray(v,float)))
def pct(v,p):return None if not v else float(np.percentile(np.asarray(v,float),p))
def self_test():
 d=parse_dt("1955-01-01T00:00:00+00:00");assert abs(jd(d)-2435108.5)<1e-6
 v=ecef(0,0);assert abs(np.linalg.norm(v)-6378.137)<1e-6
 print("v094m self-test PASS");return 0
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit("v094m contract SHA mismatch")
 p=json.loads(PROV.read_text(encoding="utf-8"));plan=list(rows(ROOT/p["frozen_plan"]["path"]));inv=list(rows(ROOT/p["source_cache_inventory"]["path"]))
 keypath={}
 for n,r in enumerate(inv,1):
  q=ROOT/r["relative_path"]
  if not q.is_file() or q.stat().st_size!=int(r["size_bytes"]) or sha(q)!=r["sha256"]:raise SystemExit(f"cache mismatch {n}")
  keypath[(inum(r["scan_id"]),inum(r["solution_num"]))]=q
  if n%200==0:log(f"source-cache verification: {n}/1386")
 polys={}
 for r in rows(ROOT/p["solution_full"]["path"]):
  sid=inum(r.get("solution_id"));q=parse_poly(r.get("stc_polygon"))
  if sid is not None and q is not None:polys[sid]=q
 plate={}
 for r in rows(ROOT/p["plate_site_cache"]["path"]):
  pid=inum(r.get("plate_id"));site=str(r.get("site_name") or "").strip();lon=fnum(r.get("site_longitude"));lat=fnum(r.get("site_latitude"))
  if pid is not None:
   cl=corrected_coords(site,lon,lat);plate[pid]=(site,cl[1],cl[0]) if cl!=(None,None) else (site,None,None)
 cache=OrderedDict()
 def get(k):
  if k in cache:cache.move_to_end(k);return cache[k]
  x=load_npz(keypath[k]);cache[k]=x
  while len(cache)>10:cache.popitem(last=False)
  return x
 glob=Counter();siteagg=defaultdict(Counter);epochagg=defaultdict(Counter);timagg=defaultdict(Counter)
 baselines=[];dmaxs=[];pmaxs=[];dens=[];burden={1:[],2:[],3:[]}
 for ix,r in enumerate(plan,1):
  ka=(inum(r["scan_id_a"]),inum(r["solution_num_a"]));kb=(inum(r["scan_id_b"]),inum(r["solution_num_b"]))
  pa,pb=polys[inum(r["solution_id_a"])],polys[inum(r["solution_id_b"])]
  A0,B0=get(ka),get(kb);A=subset(A0,common_mask(A0["ra"],A0["dec"],pa,pb));B=subset(B0,common_mask(B0["ra"],B0["dec"],pa,pb))
  ga=np.asarray(A["gaia_id"],dtype=np.int64);gb=np.asarray(B["gaia_id"],dtype=np.int64)
  shared=set(int(x) for x in ga if int(x)>0).intersection(int(x) for x in gb if int(x)>0)
  ua=np.array([int(x)>0 and int(x) not in shared for x in ga],bool);ub=np.array([int(x)>0 and int(x) not in shared for x in gb],bool)
  c=Counter();c["opportunities"]=1;c["hq_a"]=len(ga);c["hq_b"]=len(gb);c["shared_gaia_unique"]=len(shared)
  c["unshared_a"]=int(ua.sum());c["unshared_b"]=int(ub.sum());c["unshared_unique_gaia_a"]=len(set(int(x) for x in ga[ua]));c["unshared_unique_gaia_b"]=len(set(int(x) for x in gb[ub]))
  # exact v094l reference definition
  refs=0
  for ia,ib,s in mutual(A,B):
   g1,g2=int(ga[ia]),int(gb[ib]);da=fnum(A["gaiaedr3_dist"][ia]);db=fnum(B["gaiaedr3_dist"][ib])
   if g1>0 and g1==g2 and s<=5 and da is not None and db is not None and da<=1 and db<=1:refs+=1
  c["tight_same_gaia_refs"]=refs
  if refs>=30:c["local_model_reference_eligible"]=1
  timing=str(r["timing_bin"]);sitepair=str(r["site_pair"]);epoch=str(r["epoch_label"])
  if timing!="OVERLAP":
   c["motion_parallax_degenerate_hold"]=1
  else:
   c["overlap_opportunity"]=1
   try:ovs=json.loads(r["fragment_overlap_intervals_json"])
   except:ovs=[]
   pma,pmb=plate.get(inum(r["plate_a"])),plate.get(inum(r["plate_b"]))
   if not pma or not pmb or None in (pma[1],pma[2],pmb[1],pmb[2]) or not ovs:
    c["overlap_geometry_hold"]=1
   else:
    bvec,sec=dur_weighted_baseline((pma[1],pma[2]),(pmb[1],pmb[2]),ovs)
    if bvec is None:c["overlap_geometry_hold"]=1
    else:
     ra0,dec0=center([pa,pb]);bx,by=tangent_components(bvec,ra0,dec0);bp=math.hypot(bx,by)
     if bp<=0:c["overlap_geometry_hold"]=1
     else:
      c["physical_overlap_geometry_eligible"]=1
      if refs>=30:c["physical_and_local_model_eligible"]=1
      theta2=math.radians(2/3600);dmax=bp/math.tan(theta2);pmax=math.degrees(math.atan2(bp,RE))
      area=fnum(r.get("common_tangent_area_deg2")) or 0.0
      da=c["unshared_a"]/area if area>0 else 0.0;db=c["unshared_b"]/area if area>0 else 0.0
      eqdiam=2*math.sqrt(area/math.pi) if area>0 else 0.0;track=min(pmax,eqdiam)
      baselines.append(bp);dmaxs.append(dmax/AU);pmaxs.append(pmax);dens.extend([da,db])
      c[f"projected_baseline_{bbin(bp)}"]+=1;c[f"dmax_au_{dbin(dmax/AU)}"]+=1;c[f"earth_radius_parallax_{pbin(pmax)}"]+=1
      for w in (1,2,3):
       # density in arcsec^-2, expected count for a straight corridor proxy.
       ea=2*w*(track*3600)*(db/(3600**2));eb=2*w*(track*3600)*(da/(3600**2))
       burden[w].extend([ea,eb])
  for k,v in c.items():
   glob[k]+=v;siteagg[sitepair][k]+=v;epochagg[epoch][k]+=v;timagg[timing][k]+=v
  if ix%100==0:log(f"v094m search-space census: {ix}/1240")
 if glob["opportunities"]!=1240:raise SystemExit("mechanical opportunity-count HOLD")
 RESULT.mkdir(parents=True,exist_ok=True)
 def wagg(path,d):
  fs=["group"]+sorted({k for c in d.values() for k in c})
  with path.open("w",encoding="utf-8",newline="") as f:
   w=csv.DictWriter(f,fieldnames=fs);w.writeheader()
   for g,c in sorted(d.items(),key=lambda kv:(-kv[1].get("opportunities",0),kv[0])):z={"group":g};z.update(c);w.writerow(z)
 sp=RESULT/"site_pair_search_space_summary_v094m.csv";ep=RESULT/"epoch_search_space_summary_v094m.csv";tp=RESULT/"timing_search_space_summary_v094m.csv"
 wagg(sp,siteagg);wagg(ep,epochagg);wagg(tp,timagg)
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_physical_parallax_search_space_census_v094m","contract_sha256":EXPECTED,
         "parent_provenance_sha256":sha(PROV),"aggregate":dict(glob),
         "physical_geometry":{"projected_baseline_km_median":med(baselines),"projected_baseline_km_p10":pct(baselines,10),"projected_baseline_km_p90":pct(baselines,90),
           "max_resolvable_distance_au_median":med(dmaxs),"max_resolvable_distance_au_p10":pct(dmaxs,10),"max_resolvable_distance_au_p90":pct(dmaxs,90),
           "earth_radius_parallax_deg_median":med(pmaxs),"earth_radius_parallax_deg_p10":pct(pmaxs,10),"earth_radius_parallax_deg_p90":pct(pmaxs,90)},
         "unshared_density_per_deg2":{"median":med(dens),"p90":pct(dens,90)},
         "corridor_burden_expected_random_per_source":{str(w):{"median":med(v),"p90":pct(v,90)} for w,v in burden.items()},
         "site_pair_summary":{g:dict(c) for g,c in siteagg.items()},"epoch_summary":{g:dict(c) for g,c in epochagg.items()},"timing_summary":{g:dict(c) for g,c in timagg.items()},
         "guards":{"network_queries":0,"physical_source_pairing":0,"controls":0,"pixels":0,"registration":0,"candidate_inspection":0,
                   "source_or_gaia_ids_emitted":0,"coordinates_emitted":0,"angular_pair_radius_applied":False},
         "interpretive_stop":"Interpret physical search extent and source-density/corridor burden before the no-angular-radius physical matcher."}
 rp=RESULT/"applause_dr4_physical_parallax_search_space_census_v094m.json";rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 man=RESULT/"v094m_output_manifest.sha256";man.write_text("".join(f"{sha(x)}  {x.name}\n" for x in (sp,ep,tp,rp)),encoding="utf-8")
 print("\n"+"="*100);print("v094m PHYSICAL PARALLAX SEARCH-SPACE CENSUS COMPLETE");print("="*100)
 print(f"Opportunities processed:                         {glob['opportunities']}")
 print(f"Actual-overlap opportunities:                    {glob['overlap_opportunity']}")
 print(f"Non-overlap <=5min motion/parallax HOLDs:        {glob['motion_parallax_degenerate_hold']}")
 print(f"Physical overlap geometry eligible:              {glob['physical_overlap_geometry_eligible']}")
 print(f"Overlap + >=30 tight same-Gaia refs:              {glob['physical_and_local_model_eligible']}")
 print(f"Unshared strict-HQ source incidences A+B:         {glob['unshared_a']+glob['unshared_b']:,}")
 print(f"Median projected simultaneous baseline km:       {med(baselines)}")
 print(f"Median Dmax for >=2arcsec parallax (AU):          {med(dmaxs)}")
 print(f"Median Earth-radius parallax extent (deg):        {med(pmaxs)}")
 print(f"Median unshared-source surface density /deg^2:    {med(dens)}")
 for w in (1,2,3):print(f"Expected random corridor matches/source, ±{w}arcsec median/p90: {med(burden[w])} / {pct(burden[w],90)}")
 print("Angular source-pair maximum radius applied:      False")
 print("Physical source pairs emitted:                   0")
 print("Network / controls / pixels / registration:      0 / 0 / 0 / 0")
 print("STOP: interpret search-space burden before freezing physical matcher.")
 return 0
if __name__=="__main__":raise SystemExit(main())
