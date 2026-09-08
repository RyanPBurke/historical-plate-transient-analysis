#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess
PARENT="81e008b51446cee6a5023e0b184415ba7500b9b5"
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def header(p):
 with Path(p).open('r',encoding='utf-8-sig',newline='') as f:return next(csv.reader(f))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--project-root',required=True);ap.add_argument('--repo-root',required=True);a=ap.parse_args()
 root=Path(a.project_root).resolve();repo=Path(a.repo_root).resolve()
 subprocess.run(['git','-C',str(repo),'cat-file','-e',PARENT+'^{commit}'],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',PARENT,'HEAD'],check=True,stdout=subprocess.DEVNULL)
 hprov=root/'research'/'prospective_freezes'/'applause_dr4_fragment_aware_cross_site_opportunity_census_parent_provenance_v094h.json'
 qprov=root/'research'/'prospective_freezes'/'applause_dr4_exact_gaia_identity_and_timing_reconstruction_parent_provenance_v094q.json'
 oldrunner=root/'tools'/'run_applause_dr4_fragment_aware_cross_site_opportunity_census_v094h.py'
 oldplan=root/'research'/'prospective_freezes'/'applause_dr4_le5min_source_state_opportunity_plan_v094i.csv'
 for p in (hprov,qprov,oldrunner,oldplan):
  if not p.is_file():raise SystemExit(f'Missing frozen lineage file: {p}')
 hp=json.loads(hprov.read_text(encoding='utf-8'));qp=json.loads(qprov.read_text(encoding='utf-8'))
 req={'v094d_master':hp['v094d_master'],'plate_site_cache':hp['v093d_plate_cache'],'scan_full':hp['v094d_normalized']['scan_full'],'solution_full':hp['v094d_normalized']['solution_full'],'exposure_full':qp['v094d_exposure_full'],'exposure_sub_full':qp['v094d_exposure_sub_full'],'old_le5_plan':{'path':str(oldplan.relative_to(root)).replace('\\','/'),'sha256':sha(oldplan),'rows':1240}}
 schemas={}
 for k,r in req.items():
  p=root/r['path']
  if not p.is_file() or sha(p)!=r['sha256']:raise SystemExit(f'Frozen input hash mismatch: {k}: {p}')
  schemas[k]=header(p)
 needed={'v094d_master':{'exposure_id','plate_id','ra_icrs','dec_icrs','timing_confirmatory_status','fragment_intervals_json'},'plate_site_cache':{'plate_id','site_name','site_longitude','site_latitude'},'scan_full':{'plate_id','scan_id','filename_scan'},'solution_full':{'plate_id','scan_id','solution_id','ra_icrs','dec_icrs','stc_polygon'},'exposure_full':{'exposure_id','num_sub','ut_start','ut_end'},'exposure_sub_full':{'exposure_id','subexposure_id','subexposure_num','ut_start','ut_end'},'old_le5_plan':{'exposure_a','exposure_b','solution_id_a','solution_id_b','timing_bin'}}
 for k,names in needed.items():
  miss=names-set(schemas[k])
  if miss:raise SystemExit(f'Schema HOLD {k}: missing {sorted(miss)}')
 prov={'status':'PARENT_PROVENANCE_PREPARED_BEFORE_V094S_PAIRING','required_parent_git_commit':PARENT,'inputs':req,'schemas':schemas,'lineage':{'v094h_parent_provenance':{'path':str(hprov.relative_to(root)).replace('\\','/'),'sha256':sha(hprov)},'v094q_parent_provenance':{'path':str(qprov.relative_to(root)).replace('\\','/'),'sha256':sha(qprov)},'v094h_runner':{'path':str(oldrunner.relative_to(root)).replace('\\','/'),'sha256':sha(oldrunner)}},'preparation_guards':{'temporal_pairing':0,'sky_intersection_outcomes':0,'source_catalog_reads':0,'candidate_identity_reads':0,'pixels':0,'network':0}}
 dest=root/'research'/'prospective_freezes'/'v094s_source_free_opportunity_population_parent_provenance.json';dest.write_text(json.dumps(prov,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print('v094s parent provenance prepared:',dest);print('Input/schema/hash verification: PASS');print('Temporal pairing / sky outcomes computed: 0 / 0');return 0
if __name__=='__main__':raise SystemExit(main())
