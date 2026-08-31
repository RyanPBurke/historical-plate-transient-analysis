from __future__ import annotations
from pathlib import Path
import csv, hashlib, json

ROOT=Path.cwd()
FOOT=ROOT/'results'/'wide_census_exact_footprint_v052.json'
QUEUE=ROOT/'results'/'wide_census_exact_footprint_queue_v051.csv'
POLICY=ROOT/'config'/'candidate_adjudication_policy_v002.json'
OUT_JSON=ROOT/'results'/'wide_census_detector_execution_plan_v053.json'
OUT_CSV=ROOT/'results'/'wide_census_detector_execution_queue_v053.csv'
HOLD_CSV=ROOT/'results'/'wide_census_detector_execution_holds_v053.csv'
EXPECTED_POLICY_ID='candidate_adjudication_policy_v002'

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def read_csv(p):
    with Path(p).open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def write_csv(path,rows,fields):
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    tmp.replace(path)

def main():
    print('='*132);print('WIDE CENSUS — FROZEN DETECTOR EXECUTION PLAN v053');print('='*132)
    print('NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n')
    for p in (FOOT,QUEUE,POLICY):
        if not p.is_file():raise RuntimeError(f'REFUSING: missing input {p}')
    policy=json.loads(POLICY.read_text(encoding='utf-8'))
    if policy.get('policy_id')!=EXPECTED_POLICY_ID:raise RuntimeError('REFUSING: candidate policy mismatch')
    foot=json.loads(FOOT.read_text(encoding='utf-8'))
    if foot.get('status')!='COMPLETE':raise RuntimeError('REFUSING: v052 exact-footprint census incomplete')
    qmap={x['canonical_pair']:x for x in read_csv(QUEUE)}
    survivors=[];holds=[];closed=[]
    for pair in foot.get('pairs',[]):
        src=qmap.get(pair['canonical_pair'])
        if src is None:raise RuntimeError(f"REFUSING: v051 row missing for {pair['canonical_pair']}")
        cls=pair['classification']
        base={'canonical_pair':pair['canonical_pair'],'time_gate':pair['time_gate'],'physical_overlap_s':pair.get('physical_overlap_s'),
              'exact_footprint_classification':cls,'exposure_a':pair['exposure_a'],'archive_a':pair['archive_a'],'site_a':pair['site_a'],'kind_a':src['kind_a'],
              'physical_plate_key_a':src['physical_plate_key_a'],'applause_plate_id_a':src['applause_plate_id_a'],'dasch_plate_id_a':src['dasch_plate_id_a'],
              'exposure_b':pair['exposure_b'],'archive_b':pair['archive_b'],'site_b':pair['site_b'],'kind_b':src['kind_b'],
              'physical_plate_key_b':src['physical_plate_key_b'],'applause_plate_id_b':src['applause_plate_id_b'],'dasch_plate_id_b':src['dasch_plate_id_b'],
              'candidate_science_state':'NOT_EVALUATED'}
        if cls=='TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST':base.update({'detector_execution_eligible':True,'queue_state':'READY_FOR_FROZEN_DETECTOR_EXECUTION'});survivors.append(base)
        elif cls=='NO_TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST':base.update({'detector_execution_eligible':False,'queue_state':'CLOSED_NO_TRUE_SKY_OVERLAP'});closed.append(base)
        else:base.update({'detector_execution_eligible':False,'queue_state':'HOLD_EXACT_FOOTPRINT_RESOLUTION'});holds.append(base)
    tier={'LE5_MIN':0,'GT5_LE10_MIN':1,'GT10_LE15_MIN':2}
    survivors.sort(key=lambda x:(tier.get(x['time_gate'],9),-float(x['physical_overlap_s'] or 0),x['canonical_pair']))
    for i,x in enumerate(survivors,1):x['detector_execution_priority']=i
    fields=['detector_execution_priority','canonical_pair','time_gate','physical_overlap_s','exact_footprint_classification','queue_state','detector_execution_eligible','candidate_science_state','exposure_a','archive_a','site_a','kind_a','physical_plate_key_a','applause_plate_id_a','dasch_plate_id_a','exposure_b','archive_b','site_b','kind_b','physical_plate_key_b','applause_plate_id_b','dasch_plate_id_b']
    write_csv(OUT_CSV,survivors,fields);write_csv(HOLD_CSV,holds,fields)
    families={}
    for x in survivors:
        fam=' <-> '.join(sorted((x['kind_a'],x['kind_b'])));families[fam]=families.get(fam,0)+1
    aps=sorted({int(x[k]) for x in survivors for k in ('applause_plate_id_a','applause_plate_id_b') if str(x.get(k,'')).strip()})
    das=sorted({str(x[k]).strip() for x in survivors for k in ('dasch_plate_id_a','dasch_plate_id_b') if str(x.get(k,'')).strip()})
    payload={'status':'COMPLETE','analysis_kind':'wide_census_detector_execution_plan_v053','guards':{'network_access':False,'science_pixels_read':False,'non_science_pixels_read':False,'transient_detector_rerun':False,'candidate_state_mutation':False},
             'input_sha256':{'footprint_v052':sha(FOOT),'footprint_queue_v051':sha(QUEUE),'policy':sha(POLICY)},
             'robust_true_overlap_opportunity_count':len(survivors),'exact_footprint_hold_count':len(holds),'closed_no_true_overlap_count':len(closed),'detector_execution_eligible_count':len(survivors),'candidate_science_positive_count':0,
             'pair_family_counts':families,'unique_applause_physical_plates_for_detector':len(aps),'unique_applause_plate_ids':aps,'unique_dasch_plates_for_detector':len(das),'unique_dasch_plate_ids':das,
             'execution_order':'<=5-minute timing gate first, then >5-10, then >10-15; within a gate, longer actual exposure overlap first.',
             'interpretation_boundary':'This is an observing-opportunity execution queue, not a transient list. The frozen detector and generic adjudication policy must still be applied independently.',
             'next_stage':'Preflight/cache all pixel products required by the detector queue, estimate disk/runtime, then execute the resumable frozen-detector batch.'}
    tmp=OUT_JSON.with_suffix(OUT_JSON.suffix+'.tmp');tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8');tmp.replace(OUT_JSON)
    print(f'Robust true-overlap opportunities: {len(survivors)}');print(f'Exact-footprint holds: {len(holds)}');print(f'Closed no true sky overlap: {len(closed)}');print('Pair-family counts:',json.dumps(families,sort_keys=True));print(f'Unique APPLAUSE physical plates for detector: {len(aps)}');print(f'Unique DASCH plates for detector: {len(das)}');print('CANDIDATE SCIENCE POSITIVES: 0');print(f'Detector queue: {OUT_CSV}');print('\nSTAGE STATUS: PASS');return 0

if __name__=='__main__':raise SystemExit(main())
