#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,sys

EXPECTED_MASTER_SHA="76a84077ac6163ba4061c269167871290990cd11ffe3767506e973b84c150c8d"
EXPECTED_V094D_REPORT_SHA="79dc2cc3dfffce54c7109c802cb8f5c9454530238890d4e7ed7d74558918c7c9"
EXPECTED_PLATE_NORMALIZED_SHA="ffbe89d8f4fd895f5b5596de0d6889d6a58e75fecade1692d5307503cb7cd402"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root',required=True); ap.add_argument('--repo-root',required=True)
    a=ap.parse_args(); root=Path(a.project_root).resolve(); repo=Path(a.repo_root).resolve()
    master=root/'results'/'applause_dr4_fragment_timing_recoverability_audit_v094d'/'master_fragment_timing_recoverability_registry_v094d.csv'
    report=root/'results'/'applause_dr4_fragment_timing_recoverability_audit_v094d'/'applause_dr4_fragment_timing_recoverability_audit_v094d.json'
    state=root/'work'/'applause_dr4_fragment_timing_recoverability_audit_v094d'/'state'
    norm=root/'work'/'applause_dr4_fragment_timing_recoverability_audit_v094d'/'tap_normalized_csv'
    scan=norm/'scan_full.csv'; sol=norm/'solution_full.csv'
    plate_candidates=[
      root/'work'/'applause_dr4_plate_site_provenance_refinement_v093c'/'tap_cache'/'plate.csv',
      root/'work'/'applause_dr4_plate_site_provenance_refinement_v093d'/'tap_cache'/'plate.csv'
    ]
    plate=next((p for p in plate_candidates if p.is_file() and sha(p)==EXPECTED_PLATE_NORMALIZED_SHA),None)
    req=[master,report,scan,sol]
    for p in req:
        if not p.is_file(): raise SystemExit(f'Missing required frozen parent file: {p}')
    if sha(master)!=EXPECTED_MASTER_SHA: raise SystemExit('v094d master registry SHA mismatch')
    if sha(report)!=EXPECTED_V094D_REPORT_SHA: raise SystemExit('v094d report SHA mismatch')
    if plate is None: raise SystemExit('Could not find the exact v093d normalized plate cache with expected SHA')
    acquisitions={}
    for name,p in [('scan_full',scan),('solution_full',sol)]:
        meta=state/f'{name}_tap_acquisition.json'
        if not meta.is_file(): raise SystemExit(f'Missing v094d acquisition state: {meta}')
        m=json.loads(meta.read_text(encoding='utf-8'))
        actual=sha(p); expected=m.get('normalized_sha256')
        if not expected or actual!=expected: raise SystemExit(f'{name} normalized CSV is not bound to v094d acquisition state')
        acquisitions[name]={'path':str(p.relative_to(root)).replace('\\','/'),'sha256':actual,'rows':m.get('row_count')}
    # Metadata-only site inventory, prepared before the v094h freeze. No temporal pairing or source inspection.
    site_counts={}; rows=0
    with plate.open('r',encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            rows+=1; s=str(r.get('site_name') or '').strip(); site_counts[s]=site_counts.get(s,0)+1
    out={
      'status':'PARENT_PROVENANCE_PREPARED_BEFORE_V094H_EXECUTION',
      'v094d_master':{'path':str(master.relative_to(root)).replace('\\','/'),'sha256':sha(master),'rows_expected':139539},
      'v094d_report':{'path':str(report.relative_to(root)).replace('\\','/'),'sha256':sha(report)},
      'v094d_normalized':acquisitions,
      'v093d_plate_cache':{'path':str(plate.relative_to(root)).replace('\\','/'),'sha256':sha(plate),'rows':rows},
      'plate_site_name_counts_before_pairing':dict(sorted(site_counts.items())),
      'guards':{'source_catalog_reads':0,'candidate_csv_reads':0,'pixels':0,'temporal_pairing':0,'candidate_outcomes_seen':0}
    }
    dest=repo/'pipeline_v0.2.0'/'research'/'prospective_freezes'/'applause_dr4_fragment_aware_cross_site_opportunity_census_parent_provenance_v094h.json'
    dest.parent.mkdir(parents=True,exist_ok=True); dest.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'v094h parent provenance prepared: {dest}')
    print(f'plate metadata rows: {rows}; distinct raw site_name values: {len(site_counts)}')
    print(f'v094d master sha256: {out["v094d_master"]["sha256"]}')
    return 0
if __name__=='__main__': raise SystemExit(main())
