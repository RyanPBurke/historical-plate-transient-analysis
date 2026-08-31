from __future__ import annotations
from pathlib import Path
import csv, hashlib, json, math
import numpy as np

ROOT=Path.cwd()
V42=ROOT/'results/order11_followup_match3_v042/order11_match3_gaia_epoch_report_v042.json'
V44=ROOT/'results/order11_followup_match3_v044/order11_match3_sparse_astrometry_report_v044.json'
V44B=ROOT/'results/order11_followup_match3_v044b/order11_match3_sparse_robustness_audit_v044b.json'
OUT=ROOT/'results/order11_followup_match3_v045a'
ADJ_POLICY=ROOT/'config/candidate_adjudication_policy_v001.json'
EXPECTED_ADJ_POLICY_SHA='a42be953f8162520de83f3b9d4e7e8f9cf2935d9a78b7b743de267107bea3af5'
P_TILE=ROOT/'work/order11_native_full_v028/poss_tiles/P_x01024-02048_y09216-10240.npy'
P_CSV=ROOT/'work/order11_native_full_v028/poss_tiles/P_x01024-02048_y09216-10240_candidates.csv'
D_TILE=ROOT/'work/order11_native_full_v028/dasch_tiles/D_x08192-09216_y17408-18432.npy'
D_CSV=ROOT/'work/order11_native_full_v028/dasch_tiles/D_x08192-09216_y17408-18432_candidates.csv'
EXPECTED={
 P_TILE:'5622cb1fecd220a38a215516498e91a9b7094709689770bdff4c9473ad798dc1',
 P_CSV:'e74a7e0427ad84aa31815229248a3cf699a369ed25ca754eefabdbdf498068e8',
 D_TILE:'0453217bac1cbdf24025e16edaa490842521f716ced20f4d23be524693c2b151',
 D_CSV:'e92e5df6d7ff90659dd7c676f03c655916ffee0496b8aeabba9b8ba877b1bae5',
}
P_IDX,P_X,P_Y,P_SNR,P_POL=59,277,104,32.00980256157333,1
D_IDX,D_X,D_Y,D_SNR,D_POL=12,787,87,11.153908972149074,1
PREF=(0.75,1.25); FALLBACK=(0.50,1.50); MIN_CONTROLS=12; MAX_CONTROLS=32; EXCL=32.0; R=10; OUTLIER_Z=3.5

def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def rcsv(p):
 with p.open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def fnum(v):
 try:
  x=float(str(v).strip());return x if math.isfinite(x) else None
 except:return None

def inum(v):
 try:return int(float(str(v).strip()))
 except:return None

def robust_sigma(vals):
 a=np.asarray([float(x) for x in vals if x is not None and math.isfinite(float(x))],float)
 if len(a)==0:return None
 med=float(np.median(a));return 1.4826*float(np.median(np.abs(a-med)))

def metrics(a,x,y):
 h,w=a.shape
 if x-R<0 or y-R<0 or x+R>=w or y+R>=h:return None
 p=a[y-R:y+R+1,x-R:x+R+1].astype(float)
 yy,xx=np.mgrid[-R:R+1,-R:R+1];rr=np.hypot(xx,yy)
 bg=float(np.median(p[rr>=7]));q=np.clip(p-bg,0,None);flux=float(q.sum())
 if flux<=0:return None
 cx=float((q*xx).sum()/flux);cy=float((q*yy).sum()/flux);dx=xx-cx;dy=yy-cy
 mxx=float((q*dx*dx).sum()/flux);myy=float((q*dy*dy).sum()/flux);mxy=float((q*dx*dy).sum()/flux)
 vals=np.linalg.eigvalsh(np.array([[mxx,mxy],[mxy,myy]],float));minor=math.sqrt(max(vals[0],0));major=math.sqrt(max(vals[1],0))
 f3=float(q[rr<=3].sum());f5=float(q[rr<=5].sum());f8=float(q[rr<=8].sum());peak=float(q.max())
 return {'background':bg,'flux_total':flux,'sigma_major_px':major,'sigma_minor_px':minor,'ellipticity':None if major<=0 else 1-minor/major,'centroid_offset_px':math.hypot(cx,cy),'concentration_f3_f8':None if f8<=0 else f3/f8,'peak_to_flux5':None if f5<=0 else peak/f5,'peak_excess':peak}

def select(rows,idx,x,y,snr,pol):
 pool=[]
 for r in rows:
  i=inum(r.get('candidate_index'));xx=inum(r.get('local_x'));yy=inum(r.get('local_y'));s=fnum(r.get('snr'));po=inum(r.get('polarity'))
  if None in (i,xx,yy,s,po) or i==idx or po!=pol:continue
  if math.hypot(xx-x,yy-y)<EXCL:continue
  pool.append((i,xx,yy,s,po))
 def take(ratio):
  lo,hi=ratio;z=[q for q in pool if snr*lo<=q[3]<=snr*hi];z.sort(key=lambda q:(abs(math.log(max(q[3],1e-9)/snr)),q[0]));return z[:MAX_CONTROLS]
 got=take(PREF);policy='preferred_0.75_1.25'
 if len(got)<MIN_CONTROLS:got=take(FALLBACK);policy='fallback_0.50_1.50'
 return got,policy

def archive(name,npyp,csvp,idx,x,y,snr,pol):
 a=np.load(npyp,mmap_mode='r');rows=rcsv(csvp);tm=metrics(a,x,y);ctrl,policy=select(rows,idx,x,y,snr,pol);audit=[]
 for i,xx,yy,s,po in ctrl:
  m=metrics(a,xx,yy)
  if m:audit.append({'archive':name,'candidate_index':i,'local_x':xx,'local_y':yy,'snr':s,'polarity':po,**m})
 keys=['sigma_major_px','sigma_minor_px','ellipticity','centroid_offset_px','concentration_f3_f8','peak_to_flux5'];rz={};outs=[]
 for k in keys:
  vals=[q[k] for q in audit if q.get(k) is not None];tv=None if tm is None else tm.get(k)
  if tv is None or len(vals)<3:rz[k]=None;continue
  med=float(np.median(vals));sig=robust_sigma(vals);z=None if not sig else (tv-med)/sig;rz[k]=z
  if z is not None and abs(z)>OUTLIER_Z:outs.append(k)
 if tm is None:cls='MORPHOLOGY_TARGET_UNMEASURABLE'
 elif len(audit)<3:cls='INSUFFICIENT_MORPHOLOGY_CONTROLS'
 elif outs:cls='MORPHOLOGY_OUTLIER_VS_SNR_MATCHED_CONTROLS'
 else:cls='MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS'
 return {'classification':cls,'control_policy':policy,'control_count':len(audit),'target_metrics':tm,'robust_z':rz,'outlier_metrics':outs},audit

def wjson(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8');t.replace(p)

def wcsv(p,rows):
 fields=sorted({k for r in rows for k in r}) if rows else ['empty'];t=p.with_suffix(p.suffix+'.tmp')
 with t.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 t.replace(p)

def main():
 print('='*120);print('ORDER 11 — MATCH 3 MORPHOLOGY + CONSOLIDATED DISPOSITION v045a');print('='*120)
 print('Reads exact frozen target tiles and non-target same-tile controls. NO DETECTOR RERUN. NO CANDIDATE STATE MUTATION.\n')
 for p,h in EXPECTED.items():
  if not p.is_file():raise RuntimeError(f'Missing frozen input: {p}')
  if sha(p)!=h:raise RuntimeError(f'REFUSING hash mismatch: {p}')
 if not V42.is_file() or not V44.is_file() or not V44B.is_file():raise RuntimeError('Missing v042/v044/v044b prerequisite')
 if not ADJ_POLICY.is_file():raise RuntimeError(f'Missing frozen candidate adjudication policy: {ADJ_POLICY}')
 if sha(ADJ_POLICY)!=EXPECTED_ADJ_POLICY_SHA:raise RuntimeError('REFUSING candidate adjudication policy hash mismatch')
 policy=json.loads(ADJ_POLICY.read_text(encoding='utf-8'))
 v42=json.loads(V42.read_text(encoding='utf-8'));v44=json.loads(V44.read_text(encoding='utf-8'));v44b=json.loads(V44B.read_text(encoding='utf-8'));acls=str(v44.get('classification'));rcls=str(v44b.get('classification'))
 pm,pa=archive('POSS',P_TILE,P_CSV,P_IDX,P_X,P_Y,P_SNR,P_POL);dm,da=archive('DASCH',D_TILE,D_CSV,D_IDX,D_X,D_Y,D_SNR,D_POL)
 print(f"POSS morphology:  {pm['classification']} controls={pm['control_count']}")
 print(f"DASCH morphology: {dm['classification']} controls={dm['control_count']}")
 morph_ok=pm['classification']=='MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS' and dm['classification']=='MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS'
 if 'SUPPORTS_PERSISTENT_GAIA_SOURCE_ASSOCIATION' in acls and morph_ok:final='CLOSED_PERSISTENT_SOURCE_EXPLANATION_STRONGLY_SUPPORTED'
 elif 'SUPPORTS_GAIA_ASSOCIATION_WITHIN_5ARCSEC' in acls and morph_ok:final='CLOSED_PERSISTENT_SOURCE_EXPLANATION_DIAGNOSTIC'
 elif 'DOES_NOT_SUPPORT_STRICT_RAW_COINCIDENCE' in acls and rcls=='SPARSE_MISMATCH_ROBUST_TO_ANY_SINGLE_DASCH_REFERENCE':final='CLOSED_COMMON_SKY_COINCIDENCE_SPARSE_REGISTRATION_ROBUST'
 elif 'DOES_NOT_SUPPORT_STRICT_RAW_COINCIDENCE' in acls:final='UNRESOLVED_ASTROMETRY_REQUIRES_BETTER_REFERENCE_SOLUTION'
 elif 'SUPPORTS_CROSS_OBSERVATORY_MATCH_NOT_TARGET_GAIA' in acls and morph_ok:final='SURVIVES_TO_SENSITIVITY_QUALIFIED_RECURRENCE'
 else:final='UNRESOLVED_REQUIRES_SENSITIVITY_QUALIFIED_RECURRENCE'
 policy_sha=sha(ADJ_POLICY)
 report={'status':'COMPLETE','analysis_kind':'order11_match3_morphology_final_v045a','classification':final,'physical_overlap':{'start_utc':v42['measurement']['physical_overlap_start_utc'],'end_utc':v42['measurement']['physical_overlap_end_utc'],'actual_overlap_s':2700.0},'astrometry_classification':acls,'sparse_robustness_classification':rcls,'morphology':{'POSS':pm,'DASCH':dm},'candidate_adjudication_policy':{'path':str(ADJ_POLICY.relative_to(ROOT)),'sha256':policy_sha,'policy_id':policy.get('policy_id')},'science_image_pixels_read':True,'non_science_pixels_read':True,'detector_rerun':False,'candidate_state_mutation':False,'interpretation_boundary':'A sparse-field closure applies only to the static/common-sky two-observatory coincidence branch and requires the separate v044b single-reference robustness audit. It does not classify either individual photographic feature as transient or persistent. Frozen detections and all evidence remain preserved. Morphology is contextual when astrometry already closes the common-sky branch.'}
 OUT.mkdir(parents=True,exist_ok=True);wjson(OUT/'order11_match3_final_adjudication_v045a.json',report);wjson(OUT/'candidate_adjudication_policy_v001.snapshot.json',policy);wcsv(OUT/'order11_match3_poss_morphology_controls_v045.csv',pa);wcsv(OUT/'order11_match3_dasch_morphology_controls_v045.csv',da)
 print('\nFINAL MATCH-3 DISPOSITION:',final);print('Report:',OUT/'order11_match3_final_adjudication_v045a.json')
if __name__=='__main__':main()
