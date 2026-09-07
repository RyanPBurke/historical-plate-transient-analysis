#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime
import argparse,csv,hashlib,json,math,re
import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_local_astrometric_field_audit_contract_v094l.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_local_astrometric_field_audit_parent_provenance_v094l.json"
EXPECTED="b0e1434d3cf321d539c4f72734971868a9d0e84b77182e02c7902b12e4e8e820"
RESULT=ROOT/"results"/"applause_dr4_local_astrometric_field_audit_v094l"

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
  x=float(v);return x if math.isfinite(x) else None
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
def arcsec(d):
 d=np.clip(np.asarray(d,float),0,2);return np.degrees(2*np.arcsin(d/2))*3600
def center(polys):
 q=np.vstack([xyz([ra],[dec])[0] for p in polys for ra,dec in p]);v=q.sum(axis=0);v/=np.linalg.norm(v)
 return math.degrees(math.atan2(v[1],v[0]))%360,math.degrees(math.asin(v[2]))
def proj(ra,dec,ra0,dec0):
 r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0)
 dr=(r-r0+math.pi)%(2*math.pi)-math.pi;den=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr)
 ok=den>1e-10;x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
 x[ok]=np.cos(d[ok])*np.sin(dr[ok])/den[ok];y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/den[ok]
 return x*206264.80624709636,y*206264.80624709636,ok
def inside(x,y,p):
 px=np.asarray([q[0] for q in p]);py=np.asarray([q[1] for q in p]);z=np.zeros(len(x),bool);j=len(px)-1
 for i in range(len(px)):
  cross=((py[i]>y)!=(py[j]>y)) & np.isfinite(x)&np.isfinite(y)
  den=py[j]-py[i]
  if abs(den)>1e-20:z^=cross & (x < (px[j]-px[i])*(y-py[i])/den+px[i])
  j=i
 return z
def common_mask(ra,dec,pa,pb):
 ra0,dec0=center([pa,pb]);x,y,ok=proj(ra,dec,ra0,dec0)
 ax,ay,_=proj([q[0] for q in pa],[q[1] for q in pa],ra0,dec0);bx,by,_=proj([q[0] for q in pb],[q[1] for q in pb],ra0,dec0)
 return ok & inside(x,y,list(zip(ax,ay))) & inside(x,y,list(zip(bx,by)))
def subset(a,m):return {k:v[m] for k,v in a.items() if hasattr(v,"__len__") and len(v)==len(m)}
def mutual(a,b):
 if len(a["source_id"])==0 or len(b["source_id"])==0:return []
 xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb);da,j=tb.query(xa);db,i=ta.query(xb);s=arcsec(da)
 return [(ii,int(jj),float(s[ii])) for ii,jj in enumerate(j.astype(int)) if int(i[int(jj)])==ii]
def load_npz(p):
 z=np.load(p,allow_pickle=False);return {k:np.asarray(z[k]) for k in z.files if not k.endswith("_scalar")}
def rbin(x):
 if x<=.5:return "LE0P5"
 if x<=1:return "GT0P5_LE1"
 if x<=2:return "GT1_LE2"
 if x<=3:return "GT2_LE3"
 if x<=5:return "GT3_LE5"
 return "GT5"
def fit_affine(A,B):
 keep=np.ones(len(A),bool)
 for _ in range(5):
  if keep.sum()<20:return None,None
  X=np.column_stack([np.ones(keep.sum()),A[keep,0],A[keep,1]])
  cx=np.linalg.lstsq(X,B[keep,0],rcond=None)[0];cy=np.linalg.lstsq(X,B[keep,1],rcond=None)[0]
  pred=np.column_stack([np.column_stack([np.ones(len(A)),A[:,0],A[:,1]])@cx,
                        np.column_stack([np.ones(len(A)),A[:,0],A[:,1]])@cy])
  rr=np.hypot(*(B-pred).T);med=np.median(rr[keep]);mad=np.median(np.abs(rr[keep]-med));sig=max(0.05,1.4826*mad)
  new=rr<=med+4*sig
  if np.array_equal(new,keep):break
  keep=new
 if keep.sum()<20:return None,None
 X=np.column_stack([np.ones(keep.sum()),A[keep,0],A[keep,1]])
 return (np.linalg.lstsq(X,B[keep,0],rcond=None)[0],np.linalg.lstsq(X,B[keep,1],rcond=None)[0]),keep
def apply_aff(c,p):
 X=np.array([1.0,p[0],p[1]]);return np.array([X@c[0],X@c[1]])
def fold(sa,sb):
 h=hashlib.sha256(f"{int(sa)}|{int(sb)}".encode()).digest();return h[0]%5
def pct(vals,p):
 return None if not vals else float(np.percentile(np.asarray(vals,float),p))
def self_test():
 A=np.array([[0,0],[1,0],[0,1],[1,1],[2,0],[0,2],[2,2],[3,0],[0,3],[3,3],
             [4,0],[0,4],[4,4],[5,0],[0,5],[5,5],[6,0],[0,6],[6,6],[7,0],
             [0,7],[7,7],[8,0],[0,8],[8,8],[9,0],[0,9],[9,9],[10,0],[0,10]],float)
 B=np.column_stack([2+1.001*A[:,0]+.002*A[:,1],-1-.001*A[:,0]+.999*A[:,1]])
 c,k=fit_affine(A,B);assert c is not None and np.hypot(*(apply_aff(c,A[0])-B[0]))<1e-6
 print("v094l self-test PASS");return 0
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit("v094l contract SHA mismatch")
 prov=json.loads(PROV.read_text(encoding="utf-8"))
 plan=list(rows(ROOT/prov["frozen_plan"]["path"]));inv=list(rows(ROOT/prov["source_cache_inventory"]["path"]))
 keypath={}
 for n,r in enumerate(inv,1):
  p=ROOT/r["relative_path"]
  if not p.is_file() or p.stat().st_size!=int(r["size_bytes"]) or sha(p)!=r["sha256"]:raise SystemExit(f"cache mismatch row {n}")
  keypath[(inum(r["scan_id"]),inum(r["solution_num"]))]=p
  if n%200==0:log(f"source-cache verification: {n}/1386")
 polys={}
 for r in rows(ROOT/prov["v094d_solution_full"]["path"]):
  sid=inum(r.get("solution_id"));p=parse_poly(r.get("stc_polygon"))
  if sid is not None and p is not None:polys[sid]=p
 cache=OrderedDict()
 def get(k):
  if k in cache:cache.move_to_end(k);return cache[k]
  x=load_npz(keypath[k]);cache[k]=x
  while len(cache)>10:cache.popitem(last=False)
  return x
 glob=Counter();site=defaultdict(Counter);te=defaultdict(Counter);cv_all=[]
 for ix,r in enumerate(plan,1):
  ka=(inum(r["scan_id_a"]),inum(r["solution_num_a"]));kb=(inum(r["scan_id_b"]),inum(r["solution_num_b"]))
  pa,pb=polys[inum(r["solution_id_a"])],polys[inum(r["solution_id_b"])]
  A0,B0=get(ka),get(kb);A=subset(A0,common_mask(A0["ra"],A0["dec"],pa,pb));B=subset(B0,common_mask(B0["ra"],B0["dec"],pa,pb))
  ra0,dec0=center([pa,pb]);Ax,Ay,_=proj(A["ra"],A["dec"],ra0,dec0);Bx,By,_=proj(B["ra"],B["dec"],ra0,dec0)
  m=mutual(A,B);refs=[];targets=[]
  for ia,ib,s in m:
   g1,g2=int(A["gaia_id"][ia]),int(B["gaia_id"][ib]);da=fnum(A["gaiaedr3_dist"][ia]);db=fnum(B["gaiaedr3_dist"][ib])
   if g1>0 and g1==g2 and s<=5 and da is not None and db is not None and da<=1 and db<=1:
    refs.append((ia,ib))
   elif g1>0 and g2>0 and g1!=g2 and s<=5:
    targets.append((ia,ib,s))
  c=Counter();c["targets_raw"]=len(targets)
  if len(refs)>=30 and targets:
   RA=np.array([[Ax[i],Ay[i]] for i,j in refs]);RB=np.array([[Bx[j],By[j]] for i,j in refs])
   coeff,keep=fit_affine(RA,RB)
   if coeff is not None:
    c["model_eligible"]=1;c["refs_initial"]=len(refs);c["refs_retained"]=int(keep.sum())
    # deterministic 5-fold CV using same reference definition
    cv=[]
    folds=np.array([fold(A["source_id"][i],B["source_id"][j]) for i,j in refs])
    for f in range(5):
     train=folds!=f;test=folds==f
     if train.sum()<20 or test.sum()==0:continue
     cc,kk=fit_affine(RA[train],RB[train])
     if cc is None:continue
     for p,q in zip(RA[test],RB[test]):cv.append(float(np.linalg.norm(apply_aff(cc,p)-q)))
    cv_all.extend(cv);c["cv_n"]+=len(cv)
    for x in cv:c[f"cv_{rbin(x)}"]+=1
    keptA=RA[keep];keptOff=RB[keep]-RA[keep];tree=cKDTree(keptA)
    for ia,ib,s in targets:
     aa=np.array([Ax[ia],Ay[ia]]);bb=np.array([Bx[ib],By[ib]])
     # raw
     c[f"raw_{rbin(s)}"]+=1
     # affine
     ar=float(np.linalg.norm(apply_aff(coeff,aa)-bb));c["affine_evaluable"]+=1;c[f"affine_{rbin(ar)}"]+=1
     # local translation
     k=min(25,len(keptA));dd,nn=tree.query(aa,k=k);nn=np.atleast_1d(nn)
     if len(nn)>=10:
      off=np.median(keptOff[nn],axis=0);lr=float(np.linalg.norm((aa+off)-bb))
      c["local_evaluable"]+=1;c[f"local_{rbin(lr)}"]+=1
  for k,v in c.items():
   glob[k]+=v;site[r["site_pair"]][k]+=v;te[f"{r['timing_bin']}|{r['epoch_label']}"][k]+=v
  glob["opportunities"]+=1;site[r["site_pair"]]["opportunities"]+=1;te[f"{r['timing_bin']}|{r['epoch_label']}"]["opportunities"]+=1
  if ix%100==0:log(f"v094l local-field audit: {ix}/1240")
 if glob["targets_raw"]!=7874:raise SystemExit(f"Mechanical consistency HOLD: targets {glob['targets_raw']} != 7874")
 RESULT.mkdir(parents=True,exist_ok=True)
 def wagg(p,d):
  fs=["group"]+sorted({k for q in d.values() for k in q})
  with p.open("w",encoding="utf-8",newline="") as f:
   w=csv.DictWriter(f,fieldnames=fs);w.writeheader()
   for g,c in sorted(d.items(),key=lambda kv:(-kv[1].get("targets_raw",0),kv[0])):z={"group":g};z.update(c);w.writerow(z)
 sp=RESULT/"site_pair_local_field_summary_v094l.csv";tp=RESULT/"timing_epoch_local_field_summary_v094l.csv";wagg(sp,site);wagg(tp,te)
 def le(prefix,bins):
  return sum(glob.get(f"{prefix}_{b}",0) for b in bins)
 aff1=le("affine",["LE0P5","GT0P5_LE1"]);aff2=aff1+glob.get("affine_GT1_LE2",0)
 loc1=le("local",["LE0P5","GT0P5_LE1"]);loc2=loc1+glob.get("local_GT1_LE2",0)
 report={"status":"COMPLETE","analysis_kind":"applause_dr4_local_astrometric_field_audit_v094l","contract_sha256":EXPECTED,
         "parent_provenance_sha256":sha(PROV),"aggregate":dict(glob),
         "cross_validation":{"n":len(cv_all),"median_arcsec":pct(cv_all,50),"p90_arcsec":pct(cv_all,90),"p95_arcsec":pct(cv_all,95)},
         "fractions":{"affine_le1":None if not glob["affine_evaluable"] else aff1/glob["affine_evaluable"],
                      "affine_le2":None if not glob["affine_evaluable"] else aff2/glob["affine_evaluable"],
                      "local_le1":None if not glob["local_evaluable"] else loc1/glob["local_evaluable"],
                      "local_le2":None if not glob["local_evaluable"] else loc2/glob["local_evaluable"]},
         "site_pair_summary":{g:dict(c) for g,c in site.items()},"timing_epoch_summary":{g:dict(c) for g,c in te.items()},
         "guards":{"network_queries":0,"controls":0,"pixels":0,"fits":0,"registration":0,"coordinate_products_written":0,
                   "physical_parallax_pairing":0,"quality_threshold_relaxation":0,"candidate_inspection":0,
                   "source_or_gaia_ids_emitted":0,"coordinates_emitted":0}}
 rp=RESULT/"applause_dr4_local_astrometric_field_audit_v094l.json"
 rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 man=RESULT/"v094l_output_manifest.sha256";man.write_text("".join(f"{sha(p)}  {p.name}\n" for p in (sp,tp,rp)),encoding="utf-8")
 print("\n"+"="*100);print("v094l LOCAL ASTROMETRIC FIELD AUDIT COMPLETE");print("="*100)
 print(f"Opportunities processed:                      {glob['opportunities']}")
 print(f"DIFFERENT_GAIA <=5 raw targets:              {glob['targets_raw']:,}")
 print(f"Model-eligible opportunities:                 {glob['model_eligible']}")
 print(f"Affine-evaluable targets:                     {glob['affine_evaluable']:,}")
 print(f"Local-25-evaluable targets:                   {glob['local_evaluable']:,}")
 print(f"Same-Gaia held-out CV residual median arcsec: {pct(cv_all,50)}")
 print(f"Same-Gaia held-out CV residual p90 arcsec:    {pct(cv_all,90)}")
 print(f"Same-Gaia held-out CV residual p95 arcsec:    {pct(cv_all,95)}")
 print(f"Affine residual <=1 arcsec:                   {aff1:,}")
 print(f"Affine residual <=2 arcsec:                   {aff2:,}")
 print(f"Affine <=1 fraction of evaluable:             {report['fractions']['affine_le1']}")
 print(f"Affine <=2 fraction of evaluable:             {report['fractions']['affine_le2']}")
 print(f"Local-25 residual <=1 arcsec:                 {loc1:,}")
 print(f"Local-25 residual <=2 arcsec:                 {loc2:,}")
 print(f"Local-25 <=1 fraction of evaluable:           {report['fractions']['local_le1']}")
 print(f"Local-25 <=2 fraction of evaluable:           {report['fractions']['local_le2']}")
 print("Network / controls / pixels / registration:  0 / 0 / 0 / 0")
 print("Candidate/source/Gaia IDs emitted:           0")
 print("STOP: interpret local-field residuals before physical parallax or threshold relaxation.")
 return 0
if __name__=="__main__":raise SystemExit(main())
