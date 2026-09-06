#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, hashlib, json

V094E_COMMIT = "7dc5f1dde1e9b9d84b3b760a4792f23e324609a6"

def sha256(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()

def rel(p, root): return str(Path(p).resolve().relative_to(Path(root).resolve())).replace('\\','/')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root',required=True); ap.add_argument('--repo-root',required=True)
    a=ap.parse_args(); project=Path(a.project_root).resolve(); repo=Path(a.repo_root).resolve()
    e_dir=project/'results'/'applause_dr4_aggregate_pathology_audit_v094e'
    e_report=e_dir/'applause_dr4_aggregate_pathology_audit_v094e.json'
    e_per=e_dir/'per_triplet_mechanical_funnel_v094e.csv'
    e_bins=e_dir/'matchable_order_25bin_pathology_v094e.csv'
    e_manifest=e_dir/'v094e_output_manifest.sha256'
    for p in (e_report,e_per,e_bins,e_manifest):
        if not p.is_file(): raise FileNotFoundError(p)
    report=json.loads(e_report.read_text(encoding='utf-8'))
    ir=report.get('input_reproduction',{})
    if report.get('status')!='COMPLETE' or ir.get('candidate_rows')!=327883 or ir.get('triplets')!=784 or ir.get('zero_source_holds')!=21 or ir.get('matchable_triplets')!=763:
        raise RuntimeError('v094e aggregate parent state does not match frozen expected counts')
    if ir.get('per_triplet_candidate_reproduction')!='PASS' or ir.get('global_mechanical_counter_reproduction')!='PASS':
        raise RuntimeError('v094e mechanical reproduction was not PASS')
    inv=repo/'pipeline_v0.2.0'/'research'/'prospective_freezes'/'applause_dr4_v094c_source_cache_inventory_v094e.csv'
    scan=project/'work'/'applause_dr4_busko_first_cross_observatory_opportunity_census_v093'/'tap_cache'/'scan.csv'
    sol=project/'work'/'applause_dr4_busko_first_cross_observatory_opportunity_census_v093'/'tap_cache'/'solution.csv'
    master=project/'results'/'applause_dr4_fragment_timing_recoverability_audit_v094d'/'master_fragment_timing_recoverability_registry_v094d.csv'
    v094c_runner=project/'tools'/'run_applause_dr4_tierA_busko_source_census_v094c.py'
    for p in (inv,scan,sol,master,v094c_runner):
        if not p.is_file(): raise FileNotFoundError(p)
    with inv.open('r',encoding='utf-8-sig',newline='') as f:
        invrows=list(csv.DictReader(f))
    if len(invrows)!=1073: raise RuntimeError(f'expected 1073 source-cache inventory rows, got {len(invrows)}')
    out=repo/'pipeline_v0.2.0'/'research'/'prospective_freezes'/'applause_dr4_catalogue_independence_completeness_parent_provenance_v094f.json'
    obj={
      'status':'FROZEN_PARENT_PROVENANCE_PREPARED_BEFORE_V094F_EXECUTION',
      'parent_v094e_freeze_commit':V094E_COMMIT,
      'v094e':{
        'report':rel(e_report,project),'report_sha256':sha256(e_report),
        'per_triplet':rel(e_per,project),'per_triplet_sha256':sha256(e_per),
        'order_bins':rel(e_bins,project),'order_bins_sha256':sha256(e_bins),
        'output_manifest':rel(e_manifest,project),'output_manifest_sha256':sha256(e_manifest),
        'known_aggregate':{
          'candidate_rows':ir['candidate_rows'],'triplets':ir['triplets'],'zero_source_holds':ir['zero_source_holds'],'matchable_triplets':ir['matchable_triplets'],
          'order_251_275_share':report['order_concentration']['matchable_ordinal_251_275']['share'],
          'order_251_300_share':report['order_concentration']['matchable_ordinal_251_300']['share'],
          'exact_coordinate_reuse_fraction':report['recurrence_and_reuse']['exact_candidate_coordinate_string']['fraction_rows_in_reused_signatures']
        }
      },
      'frozen_local_inputs':{
        'source_cache_inventory_repo_path':'pipeline_v0.2.0/research/prospective_freezes/applause_dr4_v094c_source_cache_inventory_v094e.csv',
        'source_cache_inventory_sha256':sha256(inv),'source_cache_inventory_rows':len(invrows),
        'v093_scan_cache':rel(scan,project),'v093_scan_cache_sha256':sha256(scan),
        'v093_solution_cache':rel(sol,project),'v093_solution_cache_sha256':sha256(sol),
        'v094d_master_registry':rel(master,project),'v094d_master_registry_sha256':sha256(master),
        'v094c_runner':rel(v094c_runner,project),'v094c_runner_sha256':sha256(v094c_runner)
      },
      'guards_at_provenance_preparation':{
        'candidate_csv_read':False,'candidate_coordinates_read':False,'candidate_source_ids_read':False,'v094f_results_seen':False,'network_queries':0
      }
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'v094f parent provenance prepared: {out}')
    print(f'v094e report sha256: {obj["v094e"]["report_sha256"]}')
    print(f'source inventory: {len(invrows)} scans')
    return 0
if __name__=='__main__': raise SystemExit(main())
