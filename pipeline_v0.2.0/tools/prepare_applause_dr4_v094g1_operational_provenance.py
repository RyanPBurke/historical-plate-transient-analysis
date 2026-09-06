#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, json, subprocess

PARENT = 'edb7663eac6d6e57cefecbc7e18ee5a553238484'
EXPECTED_SAMPLE_SHA = 'd2b39fdbad4af36934be356b894affe227c4e211ac5e113a90609dc5c19b9c33'
ORIG_PROV_REL = Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_gaia_identity_control_recovery_parent_provenance_v094g.json')
ORIG_CONTRACT_REL = Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_gaia_identity_control_recovery_contract_v094g.json')
ORIG_RUNNER_REL = Path('pipeline_v0.2.0/tools/run_applause_dr4_gaia_identity_control_recovery_audit_v094g.py')
OUT_REL = Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_gaia_identity_control_recovery_operational_provenance_v094g1.json')

def sha256(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def git_bytes(repo, rel):
    return subprocess.check_output(['git','-C',str(repo),'show',f'{PARENT}:{rel.as_posix()}'])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root',required=True); ap.add_argument('--repo-root',required=True)
    a=ap.parse_args(); project=Path(a.project_root).resolve(); repo=Path(a.repo_root).resolve()
    subprocess.run(['git','-C',str(repo),'cat-file','-e',PARENT+'^{commit}'],check=True,stdout=subprocess.DEVNULL)
    for rel in (ORIG_PROV_REL,ORIG_CONTRACT_REL,ORIG_RUNNER_REL):
        p=repo/rel
        if not p.is_file() or p.read_bytes()!=git_bytes(repo,rel):
            raise RuntimeError(f'original frozen v094g artifact differs from {PARENT}: {rel}')

    orig=json.loads((repo/ORIG_PROV_REL).read_text(encoding='utf-8'))
    if orig.get('status')!='FROZEN_PARENT_PROVENANCE_PREPARED_BEFORE_V094G_EXECUTION':
        raise RuntimeError('original v094g provenance status mismatch')

    work=project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'
    sci=work/'tap_raw'/'science_source_calib'
    ctrl=work/'tap_raw'/'control_source_calib'
    plate=work/'tap_raw'/'plate_metadata'
    success_files=[]
    for d in (sci,ctrl,plate):
        if d.exists():
            success_files += [p for p in d.rglob('*.vot') if p.is_file() and p.stat().st_size>0]
            success_files += [p for p in d.rglob('*.query.sha256') if p.is_file() and p.stat().st_size>0]
    if success_files:
        raise RuntimeError('v094g has successfully cached TAP response(s); refuse blind operational amendment: '+', '.join(str(p) for p in success_files[:10]))

    result=project/'results'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'applause_dr4_gaia_identity_control_recovery_audit_v094g.json'
    if result.is_file():
        try:
            status=json.loads(result.read_text(encoding='utf-8')).get('status')
        except Exception:
            status='UNREADABLE'
        raise RuntimeError(f'v094g result already exists with status={status}; refuse operational amendment')

    sample=work/'state'/'deterministic_sample_internal_v094g.jsonl'
    sample_state={'present':sample.is_file(),'expected_sha256':EXPECTED_SAMPLE_SHA}
    if sample.is_file():
        sample_state['sha256']=sha256(sample)
        sample_state['size_bytes']=sample.stat().st_size
        if sample_state['sha256']!=EXPECTED_SAMPLE_SHA:
            raise RuntimeError('v094g deterministic sample hash differs from expected frozen reconstruction')

    obj=dict(orig)
    obj['status']='FROZEN_V094G1_OPERATIONAL_AMENDMENT_PROVENANCE'
    obj['parent_v094g_freeze_commit']=PARENT
    obj['original_v094g_frozen_artifacts']={
        'contract_repo_path':ORIG_CONTRACT_REL.as_posix(),'contract_sha256':hashlib.sha256(git_bytes(repo,ORIG_CONTRACT_REL)).hexdigest(),
        'provenance_repo_path':ORIG_PROV_REL.as_posix(),'provenance_sha256':hashlib.sha256(git_bytes(repo,ORIG_PROV_REL)).hexdigest(),
        'runner_repo_path':ORIG_RUNNER_REL.as_posix(),'runner_sha256':hashlib.sha256(git_bytes(repo,ORIG_RUNNER_REL)).hexdigest()
    }
    obj['pre_amendment_failure_state']={
        'successful_science_or_control_or_plate_votables_found':0,
        'successful_query_sha_markers_found':0,
        'v094g_result_report_present':False,
        'deterministic_sample':sample_state,
        'observed_failure_from_console':'HTTP 504 Gateway Timeout on first 2000-source science source_calib batch; five attempts; no successful batch',
        'science_outcomes_seen_before_amendment':False
    }
    out=repo/OUT_REL; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'v094g1 operational provenance prepared: {out}')
    print(f'successfully cached v094g TAP responses: 0')
    print(f'deterministic sample present/hash verified: {sample_state["present"]}')
    return 0

if __name__=='__main__': raise SystemExit(main())
