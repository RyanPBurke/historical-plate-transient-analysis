#!/usr/bin/env python3
"""Rebuild the canonical corrected <=5-minute pair tables.

This fixes two problems in the legacy overlap builder:
1) POSS-I VI/25 times are Palomar local/PST, including after-midnight observing-night rollover.
2) POSS plate number + band is not globally unique, so current IDs include VI/25 recno.

Inputs are the preserved source_data/ and checkpoints/ files in this repository.
"""
from __future__ import annotations
import math, re
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'source_data'; CP=ROOT/'checkpoints'; OUT=ROOT/'current'
OUT.mkdir(exist_ok=True)

def hms(v):
    try:
        h,m,s=map(float,re.split(r'[:\s]+',str(v).strip())[:3]); return 15*(h+m/60+s/3600)
    except Exception: return math.nan

def dms(v):
    try:
        a=re.split(r'[:\s]+',str(v).strip()); sign=-1 if a[0].startswith('-') else 1
        return sign*(abs(float(a[0]))+float(a[1])/60+float(a[2])/3600)
    except Exception: return math.nan

def poss_start(obs,clock):
    t=pd.Timestamp(f'{obs} {clock}')
    if t.hour<12: t+=pd.Timedelta(days=1)
    return (t+pd.Timedelta(hours=8)).tz_localize('UTC')

def short(v):
    s=str(v); return s.rsplit('/',1)[-1] if 'dasch/q/' in s else s

raw=pd.read_csv(SRC/'poss1_plate_metadata.csv',dtype=str,low_memory=False)
raw['recnum']=pd.to_numeric(raw.recno,errors='coerce')
p=raw[raw.recnum.notna()].copy(); p['recnum']=p.recnum.astype(int)
p['ra']=p['_RA.icrs'].map(hms); p['dec']=p['_DE.icrs'].map(dms); p['poss']=p.POSS.str.strip()
rows=[]
for _,r in p.iterrows():
    if not re.match(r'^19\d\d-\d\d-\d\d$',str(r.Obs)): continue
    for band,tcol,ecol in [('E','ObsE','Eexp'),('O','ObsO','Oexp')]:
        c=str(r[tcol]).strip(); dur=pd.to_numeric(r[ecol],errors='coerce')
        if not re.match(r'^\d\d?:\d\d$',c) or pd.isna(dur): continue
        st=poss_start(r.Obs,c)
        rows.append({'legacy_id':f'POSS-I:{r.poss}:{band}','unique_id':f'POSS-I:{r.poss}:{band}:rec{r.recnum}',
                     'recno':r.recnum,'poss':r.poss,'band':band,'start':st,'duration_s':float(dur)*60,'ra':r.ra,'dec':r.dec})
px=pd.DataFrame(rows)
counts=px.groupby('legacy_id').size(); dupids=set(counts[counts>1].index)
px[px.legacy_id.isin(dupids)].sort_values(['legacy_id','recno']).to_csv(OUT/'duplicate_poss_legacy_ids.csv',index=False)

cp=pd.read_csv(CP/'corrected_poss47_true_wcs_screen.csv')
mapping=[]
for i,r in cp.iterrows():
    for side in 'ab':
        eid=str(r[f'exposure_{side}'])
        if not eid.startswith('POSS-I:'): continue
        m=re.match(r'^POSS-I:(\d+):([EO])$',eid); poss,band=m.groups()
        c=px[(px.poss==poss)&(px.band==band)].copy(); target=pd.to_datetime(r[f'start_{side}_utc'],utc=True,format='mixed')
        c['dt']=(c.start-target).abs().dt.total_seconds(); c['dc']=((c.ra-r[f'ra_{side}_deg'])**2+(c.dec-r[f'dec_{side}_deg'])**2)**.5
        c['cost']=c.dt+c.dc*3600; b=c.sort_values('cost').iloc[0]
        if b['dt']>1 or b['dc']>.01: raise RuntimeError(f'uncertain mapping rank {r["rank"]} {eid}')
        cp.loc[i,f'exposure_{side}_legacy']=eid; cp.loc[i,f'exposure_{side}']=b.unique_id; cp.loc[i,f'poss_recno_{side}']=int(b.recno)
        mapping.append({'rank':int(r['rank']),'legacy_id':eid,'unique_id':b.unique_id,'recno':int(b.recno)})
for side in 'ab':
    cp[f'start_{side}_utc']=pd.to_datetime(cp[f'start_{side}_utc'],utc=True,format='mixed')
    cp[f'end_{side}_utc']=cp[f'start_{side}_utc']+pd.to_timedelta(cp[f'duration_{side}_s'],unit='s')
cp['actual_exposure_overlap_s']=(cp[['end_a_utc','end_b_utc']].min(axis=1)-cp[['start_a_utc','start_b_utc']].max(axis=1)).dt.total_seconds().clip(lower=0)
cp['actual_exposure_overlap_minutes']=cp.actual_exposure_overlap_s/60
cp['overlap_fraction_a']=cp.actual_exposure_overlap_s/cp.duration_a_s; cp['overlap_fraction_b']=cp.actual_exposure_overlap_s/cp.duration_b_s
cp.to_csv(OUT/'corrected_poss47_unique_ids_with_exposure_overlap.csv',index=False)
pd.DataFrame(mapping).to_csv(OUT/'poss47_unique_id_mapping.csv',index=False)

old=pd.read_csv(SRC/'archive_pair_overlap_candidates.csv')
non=old[(old.midpoint_delta_minutes<=5)&~old.exposure_a.astype(str).str.contains('POSS-I')&~old.exposure_b.astype(str).str.contains('POSS-I')].copy()
assert len(non)==27
for c in ['start_a_utc','end_a_utc','start_b_utc','end_b_utc']: non[c]=pd.to_datetime(non[c],utc=True,format='mixed')
non['actual_exposure_overlap_s']=(non[['end_a_utc','end_b_utc']].min(axis=1)-non[['start_a_utc','start_b_utc']].max(axis=1)).dt.total_seconds().clip(lower=0)
non['actual_exposure_overlap_minutes']=non.actual_exposure_overlap_s/60
non['overlap_fraction_a']=non.actual_exposure_overlap_s/non.duration_a_s; non['overlap_fraction_b']=non.actual_exposure_overlap_s/non.duration_b_s
prog=pd.read_csv(CP/'AUTHORITATIVE_nonposs_sub5_progress.csv')
non['_key']=[' | '.join(sorted([short(a),short(b)])) for a,b in zip(non.exposure_a,non.exposure_b)]
prog['_key']=[' | '.join(sorted([short(a),short(b)])) for a,b in zip(prog.a_short,prog.b_short)]
non=non.merge(prog[['_key','status','notes']],on='_key',how='left',validate='one_to_one')
non.to_csv(OUT/'nonposs27_with_exposure_overlap.csv',index=False)
print('rebuilt:',len(cp),'POSS +',len(non),'non-POSS =',len(cp)+len(non))
