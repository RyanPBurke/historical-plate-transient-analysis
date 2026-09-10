#!/usr/bin/env python3
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import argparse,csv,hashlib,json,subprocess
CONTRACT_SHA="5b615291e8bc2f5c1a9e1ba5379d0cd80b4b2f7803e3556dbd5cced838ea6520"
BANKED_COMMIT="2d30c9f780d2f2c9d572f81843af9d1c141444ad"
FREEZE_COMMIT="928bc7dad5ab399c9e45efe040322810d5a4e8c4"
EXPECTED={"pair":"109499e0f231ea4fb7e32af839105203bd8325e7a392339b55b3d5d9905dbd8d","fragment":"360ca4579c1dc6148a0059099dcb6dcab3a213cc243aaeb617c9524e13e2ce3e","witness":"b54785cf206726c02de03627d6a05ea9f199f22e0bfef2a8b0a270e4f59bf1de","report":"6523f124d77f2c518d9a8d4d132f63cc6e99fc0c9e7c393e1eefc0517f8e3baa"}
POS="FINITE_GEOMETRY_ADMISSIBLE_WITNESS"; NEG="FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE"; UNR="FINITE_GEOMETRY_UNRESOLVED"
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8388608),b''): h.update(b)
 return h.hexdigest()
def git(repo,*a):
 q=subprocess.run(['git','-C',str(repo),*a],capture_output=True,text=True)
 if q.returncode: raise SystemExit('GIT_HOLD: '+' '.join(a)+' '+q.stderr.strip())
 return q.stdout.strip()
def rcsv(p):
 with Path(p).open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def wcsv(p,fields,rows):
 with Path(p).open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n',extrasaction='ignore');w.writeheader();w.writerows(rows)
def rowsha(r):return hashlib.sha256('\x1f'.join(str(r.get(k,'')) for k in r.keys()).encode()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--repo-root',required=True);a.add_argument('--output-dir',required=True);a.add_argument('--contract',required=True);x=a.parse_args()
 repo=Path(x.repo_root).resolve();out=Path(x.output_dir).resolve();contract=Path(x.contract).resolve()
 if sha(contract)!=CONTRACT_SHA:raise SystemExit('CONTRACT_HOLD')
 if git(repo,'branch','--show-current')!='main':raise SystemExit('GIT_HOLD: not main')
 if git(repo,'status','--porcelain','--untracked-files=no'):raise SystemExit('GIT_HOLD: tracked tree not clean')
 git(repo,'fetch','origin','main');head=git(repo,'rev-parse','HEAD');origin=git(repo,'rev-parse','origin/main')
 if head!=origin or head!=BANKED_COMMIT:raise SystemExit(f'GIT_HOLD: expected banked commit {BANKED_COMMIT}, got HEAD={head} origin/main={origin}')
 q=subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',FREEZE_COMMIT,BANKED_COMMIT])
 if q.returncode:raise SystemExit('GIT_HOLD: RC4 freeze ancestry failed')
 parent=repo/'pipeline_v0.2.0/research/prospective_freezes/v094y_continuous_finite_geometry_admissibility_rc4/production_outputs'
 p={'pair':parent/'v094y_pair_admissibility.csv','fragment':parent/'v094y_fragment_admissibility.csv','witness':parent/'v094y_witnesses.csv','report':parent/'v094y_continuous_finite_geometry_admissibility.json'}
 for k,v in p.items():
  if not v.is_file() or sha(v)!=EXPECTED[k]:raise SystemExit(f'PARENT_HOLD: {k}')
 pairs,frags,wits=rcsv(p['pair']),rcsv(p['fragment']),rcsv(p['witness'])
 if (len(pairs),len(frags),len(wits))!=(8807,8925,3383):raise SystemExit('PARENT_HOLD: row counts')
 if Counter(r['pair_status'] for r in pairs)!=Counter({NEG:6152,POS:2652,UNR:3}):raise SystemExit('PARENT_HOLD: pair counts')
 if Counter(r['fragment_status'] for r in frags)!=Counter({NEG:6242,POS:2680,UNR:3}):raise SystemExit('PARENT_HOLD: fragment counts')
 fk={(r['pair_index'],r['pair_id'],r['fragment_index']):r for r in frags}
 if len(fk)!=8925:raise SystemExit('PARENT_HOLD: duplicate fragment key')
 wc=Counter((r['pair_index'],r['pair_id'],r['fragment_index']) for r in wits)
 for k,n in wc.items():
  if k not in fk or fk[k]['fragment_status']!=POS:raise SystemExit('PARENT_HOLD: witness linkage')
 for k,r in fk.items():
  n=wc.get(k,0)
  if r['fragment_status']==POS and n<1:raise SystemExit('PARENT_HOLD: positive fragment lacks witness')
  if r['fragment_status']!=POS and n:raise SystemExit('PARENT_HOLD: witness on non-positive fragment')
 sp=[r for r in pairs if r['pair_status'] in {POS,UNR}]; sf=[r for r in frags if r['fragment_status'] in {POS,UNR}]
 if len(sp)!=2655 or len(sf)!=2683:raise SystemExit('DERIVATION_HOLD: expected 2655/2683')
 sk={(r['pair_index'],r['pair_id']) for r in sp};by=defaultdict(list)
 for r in frags:by[(r['pair_index'],r['pair_id'])].append(r)
 if any((r['pair_index'],r['pair_id']) not in sk for r in sf):raise SystemExit('DERIVATION_HOLD: orphan selected fragment')
 for r in sp:
  fs=by[(r['pair_index'],r['pair_id'])]
  if r['pair_status']==POS and not any(f['fragment_status']==POS for f in fs):raise SystemExit('DERIVATION_HOLD: positive pair lacks positive fragment')
  if r['pair_status']==UNR and not any(f['fragment_status']==UNR for f in fs):raise SystemExit('DERIVATION_HOLD: unresolved pair lacks unresolved fragment')
 if out.exists():raise SystemExit('OUTPUT_HOLD: output exists')
 out.mkdir(parents=True)
 pr=[]
 for r in sp:
  fs=[f for f in by[(r['pair_index'],r['pair_id'])] if f['fragment_status'] in {POS,UNR}]
  pr.append({'pair_index':r['pair_index'],'pair_id':r['pair_id'],'plate_a':r.get('plate_a',''),'plate_b':r.get('plate_b',''),'site_a':r.get('site_a',''),'site_b':r.get('site_b',''),'parent_pair_status':r['pair_status'],'downstream_pair_class':'GEOMETRY_ADMISSIBLE' if r['pair_status']==POS else 'RETAINED_UNRESOLVED','eligible_fragment_count':len(fs),'admissible_fragment_count':sum(f['fragment_status']==POS for f in fs),'unresolved_fragment_count':sum(f['fragment_status']==UNR for f in fs),'witness_count':sum(wc.get((f['pair_index'],f['pair_id'],f['fragment_index']),0) for f in fs),'parent_pair_row_sha256':rowsha(r)})
 fr=[]
 for r in sf:
  k=(r['pair_index'],r['pair_id'],r['fragment_index']);fr.append({'pair_index':r['pair_index'],'pair_id':r['pair_id'],'fragment_index':r['fragment_index'],'start_utc':r['start_utc'],'end_utc':r['end_utc'],'duration_seconds':r['duration_seconds'],'parent_fragment_status':r['fragment_status'],'downstream_fragment_class':'GEOMETRY_ADMISSIBLE' if r['fragment_status']==POS else 'RETAINED_UNRESOLVED','witness_count':wc.get(k,0),'parent_fragment_row_sha256':rowsha(r)})
 pr.sort(key=lambda r:int(r['pair_index']));fr.sort(key=lambda r:(int(r['pair_index']),int(r['fragment_index'])))
 pf=['pair_index','pair_id','plate_a','plate_b','site_a','site_b','parent_pair_status','downstream_pair_class','eligible_fragment_count','admissible_fragment_count','unresolved_fragment_count','witness_count','parent_pair_row_sha256']
 ff=['pair_index','pair_id','fragment_index','start_utc','end_utc','duration_seconds','parent_fragment_status','downstream_fragment_class','witness_count','parent_fragment_row_sha256']
 wcsv(out/'v094z_matcher_pairs.csv',pf,pr);wcsv(out/'v094z_matcher_fragments.csv',ff,fr)
 summary={'analysis_kind':'v094z_source_blind_matcher_population','status':'COMPLETE','completed_utc':datetime.now(timezone.utc).isoformat(),'parent_banked_result_commit':head,'population_pairs':2655,'population_fragments':2683,'pair_class_counts':dict(Counter(r['downstream_pair_class'] for r in pr)),'fragment_class_counts':dict(Counter(r['downstream_fragment_class'] for r in fr)),'linked_parent_witness_rows':sum(int(r['witness_count']) for r in fr),'excluded_certified_nonadmissible_pairs':6152,'excluded_certified_nonadmissible_fragments':6242,'guards':{'source_catalog_reads':0,'candidate_identity_reads':0,'pixels':0,'fits':0,'registration':0,'network':0,'source_matching':0},'next_matcher_allowed':True,'matcher_semantics':'Matcher may use only retained rows and must still test candidate-specific finite geometry at candidate time/direction.'}
 (out/'v094z_matcher_population.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 names=['v094z_matcher_pairs.csv','v094z_matcher_fragments.csv','v094z_matcher_population.json']
 with (out/'v094z_output_manifest.sha256').open('w',encoding='utf-8',newline='\n') as f:
  for n in names:f.write(f'{sha(out/n)}  {n}\n')
 print('v094z MATCHER POPULATION PASS')
 print('pairs=2655 fragments=2683 linked_witnesses='+str(summary['linked_parent_witness_rows']))
 print('pair_classes='+json.dumps(summary['pair_class_counts'],sort_keys=True))
 print('fragment_classes='+json.dumps(summary['fragment_class_counts'],sort_keys=True))
 print('source/catalog/pixel/network reads=0')
 print('output='+str(out))
if __name__=='__main__':main()
