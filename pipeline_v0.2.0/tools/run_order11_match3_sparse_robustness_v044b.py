from __future__ import annotations
from pathlib import Path
import csv, json, math, hashlib
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

ROOT = Path.cwd()
V42 = ROOT/'results/order11_followup_match3_v042/order11_match3_gaia_epoch_report_v042.json'
V42S = ROOT/'results/order11_followup_match3_v042/order11_match3_gaia_sources_v042.csv'
V44 = ROOT/'results/order11_followup_match3_v044/order11_match3_sparse_astrometry_report_v044.json'
PREF = ROOT/'results/order11_followup_match3_v044/order11_match3_poss_independent_gaia_refs_v044.csv'
DREF = ROOT/'results/order11_followup_match3_v044/order11_match3_dasch_independent_gaia_refs_v044.csv'
POLICY = ROOT/'config/candidate_adjudication_policy_v001.json'
OUT = ROOT/'results/order11_followup_match3_v044b'
EXPECTED_POLICY_SHA='a42be953f8162520de83f3b9d4e7e8f9cf2935d9a78b7b743de267107bea3af5'
TARGET_GAIA='2850550110521018240'
STRICT=3.0
DIAGNOSTIC=5.0

def sha(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def rcsv(p):
    with p.open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def f(v):
    try:
        x=float(str(v).strip()); return x if math.isfinite(x) else None
    except:return None

def wjson(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+'.tmp')
    t.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8'); t.replace(p)

def wcsv(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True); fields=sorted({k for r in rows for k in r}) if rows else ['empty']; t=p.with_suffix(p.suffix+'.tmp')
    with t.open('w',encoding='utf-8',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)
    t.replace(p)

def main():
    print('='*120)
    print('ORDER 11 — MATCH 3 SPARSE-ASTROMETRY SINGLE-REFERENCE ROBUSTNESS AUDIT v044b')
    print('='*120)
    print('NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n')
    for p in (V42,V42S,V44,PREF,DREF,POLICY):
        if not p.is_file(): raise RuntimeError(f'Missing required input: {p}')
    if sha(POLICY)!=EXPECTED_POLICY_SHA: raise RuntimeError('REFUSING: adjudication policy hash mismatch')
    v44=json.loads(V44.read_text(encoding='utf-8'))
    if v44.get('status')!='COMPLETE' or v44.get('analysis_kind')!='order11_match3_independent_gaia_sparse_astrometry_v044':
        raise RuntimeError('REFUSING: unexpected v044 prerequisite')
    if 'DOES_NOT_SUPPORT_STRICT_RAW_COINCIDENCE' not in str(v44.get('classification')):
        print('v044 classification does not require sparse-mismatch robustness audit; recording NOT_APPLICABLE.')
    p=rcsv(PREF); d=rcsv(DREF)
    if len(p)<3 or len(d)<4:
        raise RuntimeError(f'REFUSING: expected >=3 POSS and >=4 DASCH refs for this audit, got {len(p)}/{len(d)}')
    pe=np.array([f(r['archive_minus_gaia_east_arcsec']) for r in p],float)
    pn=np.array([f(r['archive_minus_gaia_north_arcsec']) for r in p],float)
    de=np.array([f(r['archive_minus_gaia_east_arcsec']) for r in d],float)
    dn=np.array([f(r['archive_minus_gaia_north_arcsec']) for r in d],float)
    if not (np.isfinite(pe).all() and np.isfinite(pn).all() and np.isfinite(de).all() and np.isfinite(dn).all()):
        raise RuntimeError('REFUSING: non-finite reference offsets')
    mpe,mpn=float(np.median(pe)),float(np.median(pn))
    mde,mdn=float(np.median(de)),float(np.median(dn))
    vm=v44.get('measurement') or {}
    for key,val in [('median_poss_minus_gaia_east_arcsec',mpe),('median_poss_minus_gaia_north_arcsec',mpn),('median_dasch_minus_gaia_east_arcsec',mde),('median_dasch_minus_gaia_north_arcsec',mdn)]:
        old=f(vm.get(key))
        if old is None or abs(old-val)>1e-9: raise RuntimeError(f'REFUSING: recomputed {key} differs from v044: {val} vs {old}')
    v42=json.loads(V42.read_text(encoding='utf-8')); m=v42['measurement']
    pt=SkyCoord(float(m['poss']['ra_deg'])*u.deg,float(m['poss']['dec_deg'])*u.deg,frame='icrs')
    dt=SkyCoord(float(m['dasch']['ra_deg'])*u.deg,float(m['dasch']['dec_deg'])*u.deg,frame='icrs')
    src=[r for r in rcsv(V42S) if str(r.get('source_id','')).strip()==TARGET_GAIA]
    if len(src)!=1: raise RuntimeError('REFUSING: target Gaia row count !=1')
    tg=SkyCoord(float(src[0]['target_epoch_ra_deg'])*u.deg,float(src[0]['target_epoch_dec_deg'])*u.deg,frame='icrs')
    pc=pt.spherical_offsets_by((-mpe)*u.arcsec,(-mpn)*u.arcsec)
    full_dc=dt.spherical_offsets_by((-mde)*u.arcsec,(-mdn)*u.arcsec)
    full_pd=float(pc.separation(full_dc).arcsec)
    full_dg=float(full_dc.separation(tg).arcsec)
    full_pg=float(pc.separation(tg).arcsec)
    rows=[]
    for i,r in enumerate(d):
        mask=np.ones(len(d),dtype=bool); mask[i]=False
        le=float(np.median(de[mask])); ln=float(np.median(dn[mask]))
        dc=dt.spherical_offsets_by((-le)*u.arcsec,(-ln)*u.arcsec)
        pd=float(pc.separation(dc).arcsec); dg=float(dc.separation(tg).arcsec)
        left_e=float(de[i]-le); left_n=float(dn[i]-ln)
        rows.append({
            'left_out_row':i,
            'left_out_gaia_source_id':r.get('gaia_source_id'),
            'left_out_candidate_index':r.get('candidate_index'),
            'fit_n':len(d)-1,
            'dasch_median_east_arcsec':le,
            'dasch_median_north_arcsec':ln,
            'left_out_residual_arcsec':math.hypot(left_e,left_n),
            'corrected_poss_dasch_sep_arcsec':pd,
            'corrected_dasch_to_target_gaia_arcsec':dg,
            'strict_common_sky_survives':pd<=STRICT,
            'diagnostic_common_sky_survives':pd<=DIAGNOSTIC,
        })
    vals=[r['corrected_poss_dasch_sep_arcsec'] for r in rows]
    all_gt3=all(x>STRICT for x in vals); all_gt5=all(x>DIAGNOSTIC for x in vals)
    if 'DOES_NOT_SUPPORT_STRICT_RAW_COINCIDENCE' not in str(v44.get('classification')):
        cls='SPARSE_ROBUSTNESS_NOT_APPLICABLE'
    elif all_gt3:
        cls='SPARSE_MISMATCH_ROBUST_TO_ANY_SINGLE_DASCH_REFERENCE'
    else:
        cls='SPARSE_MISMATCH_NOT_ROBUST_TO_SINGLE_REFERENCE_REMOVAL'
    report={
        'status':'COMPLETE',
        'analysis_kind':'order11_match3_sparse_single_reference_robustness_v044b',
        'classification':cls,
        'v044_classification':v44.get('classification'),
        'fixed_policy':{
            'purpose':'Audit sensitivity of the diagnostic sparse-field result to any single DASCH reference; does not upgrade sparse astrometry to the primary common-reference solution.',
            'strict_gate_arcsec':STRICT,'diagnostic_gate_arcsec':DIAGNOSTIC,
            'leave_one_out_archive':'DASCH','poss_solution':'full independent Gaia median using all reciprocal references',
            'candidate_and_target_gaia_excluded_from_registration':True,
        },
        'counts':{'poss_references':len(p),'dasch_references':len(d),'dasch_leave_one_out_trials':len(rows)},
        'full_solution':{'corrected_poss_dasch_sep_arcsec':full_pd,'corrected_poss_to_target_gaia_arcsec':full_pg,'corrected_dasch_to_target_gaia_arcsec':full_dg},
        'leave_one_out_summary':{
            'corrected_poss_dasch_min_arcsec':min(vals),'corrected_poss_dasch_max_arcsec':max(vals),
            'all_trials_above_3arcsec':all_gt3,'all_trials_above_5arcsec':all_gt5,
            'max_left_out_reference_residual_arcsec':max(r['left_out_residual_arcsec'] for r in rows),
        },
        'interpretation_boundary':'This certifies only robustness of the sparse diagnostic mismatch to removal of any one DASCH reference. It does not prove either photographic feature is transient or persistent and does not substitute for a >=5 common-reference local solution.',
        'network_access':False,'science_image_pixels_read':False,'non_science_pixels_read':False,'detector_rerun':False,'candidate_state_mutation':False,
    }
    wjson(OUT/'order11_match3_sparse_robustness_audit_v044b.json',report)
    wcsv(OUT/'order11_match3_sparse_robustness_trials_v044b.csv',rows)
    print('Classification:',cls)
    print(f'Full corrected P-D: {full_pd:.3f}"')
    print(f'Leave-one-DASCH-reference-out corrected P-D range: {min(vals):.3f}" .. {max(vals):.3f}"')
    print(f'All trials >3": {all_gt3} | all trials >5": {all_gt5}')
    print('Report:',OUT/'order11_match3_sparse_robustness_audit_v044b.json')

if __name__=='__main__': main()
