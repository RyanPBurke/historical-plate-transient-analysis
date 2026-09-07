#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime,timezone
import argparse,csv,hashlib,json,math,re
import numpy as np
from scipy.spatial import cKDTree
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_no_radius_epipolar_parallax_matcher_contract_v094n.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_no_radius_epipolar_parallax_matcher_parent_provenance_v094n.json"
EXPECTED="f4c3e6260bf8139ab7ac370e2f9f5a28d46353685dd17f1d07ead516dfb1b643"
RESULT=ROOT/"results"/"applause_dr4_no_radius_epipolar_parallax_matcher_v094n"
WORK=ROOT/"work"/"applause_dr4_no_radius_epipolar_parallax_matcher_v094n"
AU=149597870.7;RE=6378.137;ASEC=206264.80624709636
GEN_TOL=math.radians(7/3600);FINAL_TOL=math.radians(2/3600);MIN_DISP=math.radians(2/3600)
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
def one_xyz(ra,dec):return xyz([ra],[dec])[0]
def radec(v):
 v=np.asarray(v,float);v=v/np.linalg.norm(v);return math.degrees(math.atan2(v[1],v[0]))%360,math.degrees(math.asin(np.clip(v[2],-1,1)))
def arcsec_from_dot(a,b):
 c=float(np.clip(np.dot(a,b),-1,1));return math.degrees(math.acos(c))*3600
def center(polys):
 q=np.vstack([one_xyz(ra,dec) for p in polys for ra,dec in p]);v=q.sum(0);v/=np.linalg.norm(v);return radec(v)
def proj(ra,dec,ra0,dec0):
 r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0)
 dr=(r-r0+math.pi)%(2*math.pi)-math.pi;den=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr)
 ok=den>1e-10;x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
 x[ok]=np.cos(d[ok])*np.sin(dr[ok])/den[ok];y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/den[ok]
 return x*ASEC,y*ASEC,ok
def unproj(xa,ya,ra0,dec0):
 x=float(xa)/ASEC;y=float(ya)/ASEC;rho=math.hypot(x,y);r0=math.radians(ra0);d0=math.radians(dec0)
 if rho<1e-15:return ra0,dec0
 c=math.atan(rho);sc,cc=math.sin(c),math.cos(c)
 dec=math.asin(cc*math.sin(d0)+(y*sc*math.cos(d0)/rho))
 ra=r0+math.atan2(x*sc,rho*math.cos(d0)*cc-y*math.sin(d0)*sc)
 return math.degrees(ra)%360,math.degrees(dec)
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
 xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb);da,j=tb.query(xa);db,i=ta.query(xb)
 out=[]
 for ii,jj in enumerate(j.astype(int)):
  if int(i[int(jj)])==ii:
   s=arcsec_from_dot(xa[ii],xb[int(jj)]);out.append((ii,int(jj),s))
 return out
def load_npz(p):
 z=np.load(p,allow_pickle=False);return {k:np.asarray(z[k]) for k in z.files if not k.endswith("_scalar")}
def corrected_coords(site,lon,lat):
 if lon is None or lat is None:return None,None
 if site=="Dr. Remeis-Observatory, Bamberg, Germany":return lat,lon
 return lon,lat
def ecef(lat,lon):
 a=6378.137;f=1/298.257223563;e2=f*(2-f);p=math.radians(lat);l=math.radians(lon);N=a/math.sqrt(1-e2*math.sin(p)**2)
 return np.array([N*math.cos(p)*math.cos(l),N*math.cos(p)*math.sin(l),N*(1-e2)*math.sin(p)])
def jd(d):return d.timestamp()/86400+2440587.5
def eci(v,d):
 J=jd(d);T=(J-2451545)/36525;th=math.radians((280.46061837+360.98564736629*(J-2451545)+.000387933*T*T-T*T*T/38710000)%360)
 c,s=math.cos(th),math.sin(th);x,y,z=v;return np.array([c*x-s*y,s*x+c*y,z])
def baseline(sitea,siteb,ovs):
 va,vb=ecef(sitea[0],sitea[1]),ecef(siteb[0],siteb[1]);acc=np.zeros(3);tot=0
 for q in ovs:
  s,e=parse_dt(q.get("start_utc")),parse_dt(q.get("end_utc"))
  if not s or not e or e<=s:continue
  w=(e-s).total_seconds();m=s+(e-s)/2;acc+=w*(eci(vb,m)-eci(va,m));tot+=w
 return (None,None,None) if tot<=0 else (acc/tot,eci(va,s+(e-s)/2),eci(vb,s+(e-s)/2))
def fit_affine(A,B):
 keep=np.ones(len(A),bool)
 for _ in range(5):
  if keep.sum()<20:return None,None
  X=np.column_stack([np.ones(keep.sum()),A[keep,0],A[keep,1]])
  cx=np.linalg.lstsq(X,B[keep,0],rcond=None)[0];cy=np.linalg.lstsq(X,B[keep,1],rcond=None)[0]
  XX=np.column_stack([np.ones(len(A)),A[:,0],A[:,1]])
  pred=np.column_stack([XX@cx,XX@cy]);rr=np.hypot(*(B-pred).T);med=np.median(rr[keep]);mad=np.median(np.abs(rr[keep]-med));sig=max(.05,1.4826*mad)
  new=rr<=med+4*sig
  if np.array_equal(new,keep):break
  keep=new
 if keep.sum()<20:return None,None
 return True,keep
def basis_about_baseline(B):
 e3=B/np.linalg.norm(B);ref=np.array([0.,0.,1.])
 if abs(e3@ref)>.9:ref=np.array([1.,0.,0.])
 e1=ref-(ref@e3)*e3;e1/=np.linalg.norm(e1);e2=np.cross(e3,e1);e2/=np.linalg.norm(e2)
 return e1,e2,e3
def phi_alpha(v,e1,e2,e3):
 x=v@e1;y=v@e2;z=np.clip(v@e3,-1,1);return math.atan2(y,x)%(2*math.pi),math.acos(z)
def circular_ranges(phi,w):
 lo=phi-w;hi=phi+w;tw=2*math.pi
 if w>=math.pi:return [(0.,tw)]
 if lo<0:return [(0.,hi),(lo+tw,tw)]
 if hi>=tw:return [(lo,tw),(0.,hi-tw)]
 return [(lo,hi)]
def candidate_pairs_epipolar(Avec,Bvec,e1,e2,e3,tol):
 aphi=np.array([phi_alpha(v,e1,e2,e3)[0] for v in Avec]);order=np.argsort(aphi);sphi=aphi[order]
 out=[]
 sint=math.sin(tol)
 for jb,v in enumerate(Bvec):
  ph,al=phi_alpha(v,e1,e2,e3);sa=abs(math.sin(al))
  w=math.pi if sa<=sint else math.asin(min(1.0,sint/sa))
  for lo,hi in circular_ranges(ph,w):
   l=np.searchsorted(sphi,lo,"left");h=np.searchsorted(sphi,hi,"right")
   for pos in range(l,h):out.append((int(order[pos]),jb))
 return out
def local_reference_model(A,B,pa,pb):
 refs=[]
 for ia,ib,s in mutual(A,B):
  g1,g2=int(A["gaia_id"][ia]),int(B["gaia_id"][ib]);da=fnum(A["gaiaedr3_dist"][ia]);db=fnum(B["gaiaedr3_dist"][ib])
  if g1>0 and g1==g2 and s<=5 and da is not None and db is not None and da<=1 and db<=1:refs.append((ia,ib))
 if len(refs)<30:return None
 ra0,dec0=center([pa,pb]);ax,ay,_=proj(A["ra"],A["dec"],ra0,dec0);bx,by,_=proj(B["ra"],B["dec"],ra0,dec0)
 RA=np.array([[ax[i],ay[i]] for i,j in refs]);RB=np.array([[bx[j],by[j]] for i,j in refs]);ok,keep=fit_affine(RA,RB)
 if ok is None:return None
 kb=RB[keep];off=(RB-RA)[keep];tree=cKDTree(kb)
 return {"ra0":ra0,"dec0":dec0,"tree":tree,"bref":kb,"off":off}
def correct_b(v,model):
 if model is None:return v
 ra,dec=radec(v);x,y,_=proj([ra],[dec],model["ra0"],model["dec0"]);q=np.array([x[0],y[0]])
 k=min(25,len(model["bref"]));dd,ii=model["tree"].query(q,k=k);ii=np.atleast_1d(ii)
 if len(ii)<10:return v
 off=np.median(model["off"][ii],axis=0);ra2,dec2=unproj(q[0]-off[0],q[1]-off[1],model["ra0"],model["dec0"])
 return one_xyz(ra2,dec2)
def ray_solution(rA,rB,nA,nB):
 b=float(nA@nB);den=1-b*b
 if den<1e-15:return None
 w=rA-rB;d=float(nA@w);e=float(nB@w);tA=(b*e-d)/den;tB=(e-b*d)/den
 pA=rA+tA*nA;pB=rB+tB*nB;mid=(pA+pB)/2;miss=float(np.linalg.norm(pA-pB));scale=max(1e-12,(abs(tA)+abs(tB))/2)
 return tA,tB,mid,miss,math.atan2(miss,scale)
def distbin(dkm):
 au=dkm/AU
 if au<.01:return "EARTH_TO_0P01AU"
 if au<.1:return "0P01_TO_0P1AU"
 if au<1:return "0P1_TO_1AU"
 return "GE1AU"
def dispbin(a):
 s=math.degrees(abs(a))*3600
 if s<5:return "2_TO_5ARCSEC"
 if s<30:return "5_TO_30ARCSEC"
 if s<60:return "30_TO_60ARCSEC"
 if s<600:return "1_TO_10ARCMIN"
 if s<3600:return "10_TO_60ARCMIN"
 return "GE1DEG"
def candhash(pairid,sa,sb):
 return hashlib.sha256(f"{pairid}|{int(sa)}|{int(sb)}".encode()).hexdigest()
def self_test():
 B=np.array([400.,0.,0.]);e1,e2,e3=basis_about_baseline(B);nA=np.array([0.,1.,0.])
 # Object at +y, site B displaced +x -> B direction has polar angle > A.
 R=np.array([0.,100000.,0.]);nB=(R-B);nB/=np.linalg.norm(nB)
 _,aa=phi_alpha(nA,e1,e2,e3);_,bb=phi_alpha(nB,e1,e2,e3);assert bb>aa
 assert abs(math.degrees(bb-aa)*3600-825.05)<2
 print("v094n self-test PASS");return 0
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit("v094n contract SHA mismatch")
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
 RESULT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
 private=WORK/"private_candidate_map_v094n.csv";blind=RESULT/"blinded_physical_match_ledger_v094n.csv"
 pf=["candidate_hash","class","calibration_tier","pair_id","source_id_a","source_id_b","gaia_id_a","gaia_id_b","ra_a","dec_a","ra_b","dec_b","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec","geocentric_distance_km"]
 bf=["candidate_hash","class","calibration_tier","signed_disparity_arcsec","cross_track_arcsec","closure_arcsec","distance_bin","disparity_bin"]
 glob=Counter();siteagg=defaultdict(Counter);epochagg=defaultdict(Counter);tieragg=defaultdict(Counter);distagg=defaultdict(Counter);dispagg=defaultdict(Counter)
 opp_phys=Counter();source_phys=Counter();pair_phys=Counter()
 with private.open("w",encoding="utf-8",newline="") as fp,blind.open("w",encoding="utf-8",newline="") as fb:
  wp=csv.DictWriter(fp,fieldnames=pf);wb=csv.DictWriter(fb,fieldnames=bf);wp.writeheader();wb.writeheader()
  for ix,r in enumerate(plan,1):
   glob["opportunities"]+=1
   if str(r["timing_bin"])!="OVERLAP":
    glob["nonoverlap_hold"]+=1
    continue
   glob["overlap_opportunities"]+=1
   ka=(inum(r["scan_id_a"]),inum(r["solution_num_a"]));kb=(inum(r["scan_id_b"]),inum(r["solution_num_b"]))
   pa,pb=polys[inum(r["solution_id_a"])],polys[inum(r["solution_id_b"])]
   A0,B0=get(ka),get(kb);A=subset(A0,common_mask(A0["ra"],A0["dec"],pa,pb));B=subset(B0,common_mask(B0["ra"],B0["dec"],pa,pb))
   ga=np.asarray(A["gaia_id"],np.int64);gb=np.asarray(B["gaia_id"],np.int64);shared=set(int(x) for x in ga if int(x)>0).intersection(int(x) for x in gb if int(x)>0)
   ma=np.array([int(x)>0 and int(x) not in shared for x in ga]);mb=np.array([int(x)>0 and int(x) not in shared for x in gb]);UA=subset(A,ma);UB=subset(B,mb)
   model=local_reference_model(A,B,pa,pb);tier="CALIBRATED_LOCAL25" if model is not None else "HOLD_UNCALIBRATED_ASTROMETRY"
   if model is not None:glob["calibrated_opportunities"]+=1
   try:ovs=json.loads(r["fragment_overlap_intervals_json"])
   except:ovs=[]
   pma,pmb=plate.get(inum(r["plate_a"])),plate.get(inum(r["plate_b"]))
   if not pma or not pmb or None in (pma[1],pma[2],pmb[1],pmb[2]) or not ovs:
    glob["geometry_hold"]+=1;continue
   # Duration-weighted baseline and approximate site positions at the first overlap midpoint for ray origins.
   va,vb=ecef(pma[1],pma[2]),ecef(pmb[1],pmb[2]);acc=np.zeros(3);tot=0.;tmid=None
   for q in ovs:
    s,e=parse_dt(q.get("start_utc")),parse_dt(q.get("end_utc"))
    if not s or not e or e<=s:continue
    w=(e-s).total_seconds();m=s+(e-s)/2
    if tmid is None:tmid=m
    acc+=w*(eci(vb,m)-eci(va,m));tot+=w
   if tot<=0 or tmid is None:glob["geometry_hold"]+=1;continue
   Bvec=acc/tot;rA=eci(va,tmid);rB=rA+Bvec
   e1,e2,e3=basis_about_baseline(Bvec)
   Avec=xyz(UA["ra"],UA["dec"]);Bvecs=xyz(UB["ra"],UB["dec"])
   gen=candidate_pairs_epipolar(Avec,Bvecs,e1,e2,e3,GEN_TOL);glob["generator_pairs"]+=len(gen)
   for ia,ib in gen:
    na=Avec[ia];nb_raw=Bvecs[ib];nb=correct_b(nb_raw,model) if model is not None else nb_raw
    pha,ala=phi_alpha(na,e1,e2,e3);phb,alb=phi_alpha(nb,e1,e2,e3)
    normal=np.cross(e3,na);nn=np.linalg.norm(normal)
    if nn<1e-15:continue
    normal/=nn;xt=math.asin(min(1.0,abs(float(nb@normal))))
    if xt>FINAL_TOL:continue
    disp=alb-ala
    # map to principal signed polar difference; alpha is in [0,pi], so direct difference is already principal.
    if abs(disp)<MIN_DISP:continue
    sep=arcsec_from_dot(na,nb)
    bp=float(np.linalg.norm(Bvec-(Bvec@na)*na));dmax=bp/math.tan(MIN_DISP) if bp>0 else 0
    site=str(r["site_pair"]);epoch=str(r["epoch_label"])
    if disp>0:
     sol=ray_solution(rA,rB,na,nb)
     if sol is None:continue
     tA,tB,mid,miss,closure=sol
     if tA<=0 or tB<=0:continue
     D=float(np.linalg.norm(mid))
     if D<RE or D>dmax or closure>FINAL_TOL:continue
     # basic visibility consistency
     if float(na@rA)<=0 or float(nb@rB)<=0:
      glob["below_horizon_physical_hold"]+=1;continue
     cls="PHYSICAL_PARALLAX_GEOMETRY"
     glob["physical_matches"]+=1
     if model is not None:glob["calibrated_physical_matches"]+=1
     db=distbin(D);sb=dispbin(disp);h=candhash(r["pair_id"],UA["source_id"][ia],UB["source_id"][ib])
     opp_phys[ix]+=1;source_phys[int(UA["source_id"][ia])]+=1;source_phys[int(UB["source_id"][ib])]+=1;pair_phys[(int(UA["source_id"][ia]),int(UB["source_id"][ib]))]+=1
     rec={"candidate_hash":h,"class":cls,"calibration_tier":tier,"signed_disparity_arcsec":math.degrees(disp)*3600,
          "cross_track_arcsec":math.degrees(xt)*3600,"closure_arcsec":math.degrees(closure)*3600,"distance_bin":db,"disparity_bin":sb}
     wb.writerow(rec)
     rap,decp=radec(nb)
     wp.writerow({**rec,"pair_id":r["pair_id"],"source_id_a":int(UA["source_id"][ia]),"source_id_b":int(UB["source_id"][ib]),
                  "gaia_id_a":int(UA["gaia_id"][ia]),"gaia_id_b":int(UB["gaia_id"][ib]),"ra_a":float(UA["ra"][ia]),"dec_a":float(UA["dec"][ia]),
                  "ra_b":rap,"dec_b":decp,"geocentric_distance_km":D})
     siteagg[site]["physical"]+=1;epochagg[epoch]["physical"]+=1;tieragg[tier]["physical"]+=1;distagg[db]["physical"]+=1;dispagg[sb]["physical"]+=1
    else:
     # matched anti-parallax sign null: same plane/tolerance and absolute stereo disparity/range scale.
     ad=-disp
     tA_abs=np.linalg.norm(Bvec)*abs(math.sin(alb))/max(1e-15,abs(math.sin(ad)))
     if tA_abs<RE or tA_abs>dmax:continue
     cls="ANTI_PARALLAX_SIGN_NULL";glob["anti_matches"]+=1
     if model is not None:glob["calibrated_anti_matches"]+=1
     db=distbin(tA_abs);sb=dispbin(ad);h=candhash("ANTI|"+r["pair_id"],UA["source_id"][ia],UB["source_id"][ib])
     rec={"candidate_hash":h,"class":cls,"calibration_tier":tier,"signed_disparity_arcsec":math.degrees(disp)*3600,
          "cross_track_arcsec":math.degrees(xt)*3600,"closure_arcsec":"","distance_bin":db,"disparity_bin":sb}
     wb.writerow(rec)
     rap,decp=radec(nb)
     wp.writerow({**rec,"pair_id":r["pair_id"],"source_id_a":int(UA["source_id"][ia]),"source_id_b":int(UB["source_id"][ib]),
                  "gaia_id_a":int(UA["gaia_id"][ia]),"gaia_id_b":int(UB["gaia_id"][ib]),"ra_a":float(UA["ra"][ia]),"dec_a":float(UA["dec"][ia]),
                  "ra_b":rap,"dec_b":decp,"geocentric_distance_km":tA_abs})
     siteagg[site]["anti"]+=1;epochagg[epoch]["anti"]+=1;tieragg[tier]["anti"]+=1;distagg[db]["anti"]+=1;dispagg[sb]["anti"]+=1
   if ix%50==0:log(f"v094n physical matcher: {ix}/1240; generator={glob['generator_pairs']:,}; physical={glob['physical_matches']:,}; anti={glob['anti_matches']:,}")
 if glob["overlap_opportunities"]!=1081 or glob["nonoverlap_hold"]!=159:raise SystemExit("Mechanical timing-count HOLD")
 def wagg(path,d):
  with path.open("w",encoding="utf-8",newline="") as f:
   w=csv.DictWriter(f,fieldnames=["group","physical","anti"]);w.writeheader()
   for g,c in sorted(d.items(),key=lambda kv:(-kv[1].get("physical",0),kv[0])):w.writerow({"group":g,"physical":c.get("physical",0),"anti":c.get("anti",0)})
 sp=RESULT/"site_pair_physical_null_summary_v094n.csv";ep=RESULT/"epoch_physical_null_summary_v094n.csv";tp=RESULT/"calibration_tier_physical_null_summary_v094n.csv";dp=RESULT/"distance_physical_null_summary_v094n.csv";xp=RESULT/"disparity_physical_null_summary_v094n.csv"
 for path,d in ((sp,siteagg),(ep,epochagg),(tp,tieragg),(dp,distagg),(xp,dispagg)):wagg(path,d)
 phys=glob["physical_matches"];anti=glob["anti_matches"];cphys=glob["calibrated_physical_matches"];canti=glob["calibrated_anti_matches"]
 reuse={"physical_candidate_count":phys,"opportunities_with_physical":sum(1 for v in opp_phys.values() if v>0),
        "top1_opportunity_share":(max(opp_phys.values(),default=0)/phys if phys else 0),
        "top5_opportunity_share":(sum(sorted(opp_phys.values(),reverse=True)[:5])/phys if phys else 0),
        "repeated_source_endpoint_fraction":((sum(source_phys.values())-len(source_phys))/sum(source_phys.values()) if source_phys else 0),
        "repeated_exact_source_pair_fraction":((sum(pair_phys.values())-len(pair_phys))/sum(pair_phys.values()) if pair_phys else 0)}
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_no_radius_epipolar_parallax_matcher_v094n","contract_sha256":EXPECTED,
         "parent_provenance_sha256":sha(PROV),"aggregate":dict(glob),
         "ratios":{"physical_to_anti":None if not anti else phys/anti,"calibrated_physical_to_anti":None if not canti else cphys/canti},
         "reuse_concentration":reuse,
         "private_candidate_map":{"path":str(private.relative_to(ROOT)).replace("\\","/"),"sha256":sha(private),"DO_NOT_INSPECT_BEFORE_AGGREGATE_INTERPRETATION":True},
         "output_hashes":{},"guards":{"network_queries":0,"controls":0,"pixels":0,"fits":0,"candidate_human_inspection":0,
          "angular_pair_radius_maximum_applied":False,"nonoverlap_motion_pairing":0}}
 rp=RESULT/"applause_dr4_no_radius_epipolar_parallax_matcher_v094n.json"
 for q in (blind,sp,ep,tp,dp,xp):report["output_hashes"][q.name]=sha(q)
 rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 man=RESULT/"v094n_output_manifest.sha256";man.write_text("".join(f"{sha(q)}  {q.name}\n" for q in (blind,sp,ep,tp,dp,xp,rp)),encoding="utf-8")
 print("\n"+"="*104);print("v094n NO-RADIUS EPIPOLAR PARALLAX MATCHER COMPLETE");print("="*104)
 print(f"Opportunities processed:                       {glob['opportunities']}")
 print(f"Actual-overlap opportunities paired:           {glob['overlap_opportunities']}")
 print(f"Non-overlap <=5min held:                       {glob['nonoverlap_hold']}")
 print(f"Calibrated overlap opportunities:              {glob['calibrated_opportunities']}")
 print(f"Raw epipolar generator pairs (7arcsec strip):  {glob['generator_pairs']:,}")
 print(f"Physical-sign geometry matches:                {phys:,}")
 print(f"Anti-parallax sign-null matches:               {anti:,}")
 print(f"Physical / anti ratio:                         {None if not anti else phys/anti}")
 print(f"Calibrated physical matches:                   {cphys:,}")
 print(f"Calibrated anti-null matches:                  {canti:,}")
 print(f"Calibrated physical / anti ratio:              {None if not canti else cphys/canti}")
 print(f"Opportunities with >=1 physical match:         {reuse['opportunities_with_physical']}")
 print(f"Physical top-1 opportunity share:              {reuse['top1_opportunity_share']}")
 print(f"Physical top-5 opportunity share:              {reuse['top5_opportunity_share']}")
 print(f"Repeated physical source-endpoint fraction:    {reuse['repeated_source_endpoint_fraction']}")
 print(f"Repeated exact physical source-pair fraction:  {reuse['repeated_exact_source_pair_fraction']}")
 print("Angular source-pair maximum radius applied:    False")
 print("Private candidate identities inspected:        0")
 print("Network / controls / pixels / registration:   0 / 0 / 0 / 0")
 print("STOP: interpret physical-vs-null aggregate before any candidate identity inspection.")
 return 0
if __name__=="__main__":raise SystemExit(main())
