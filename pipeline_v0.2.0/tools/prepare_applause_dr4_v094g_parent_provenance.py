#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse, csv, hashlib, json, math

PARENT_COMMIT = "9fba0d822795c2eea894989b4feca7a3e42e70f1"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def rel(p: Path, root: Path) -> str:
    return str(p.resolve().relative_to(root.resolve())).replace('\\', '/')


def close(a, b, tol=5e-5):
    try:
        return math.isfinite(float(a)) and abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-root', required=True)
    ap.add_argument('--repo-root', required=True)
    args = ap.parse_args()
    project = Path(args.project_root).resolve()
    repo = Path(args.repo_root).resolve()

    result = project / 'results' / 'applause_dr4_catalogue_independence_completeness_audit_v094f'
    report = result / 'applause_dr4_catalogue_independence_completeness_audit_v094f.json'
    per = result / 'per_triplet_catalogue_independence_completeness_v094f.csv'
    pair = result / 'science_pair_catalogue_overlap_v094f.csv'
    scan = result / 'scan_process_fingerprint_audit_v094f.csv'
    manifest = result / 'v094f_output_manifest.sha256'
    for p in (report, per, pair, scan, manifest):
        if not p.is_file():
            raise FileNotFoundError(p)

    obj = json.loads(report.read_text(encoding='utf-8'))
    if obj.get('status') != 'COMPLETE' or obj.get('analysis_kind') != 'applause_dr4_catalogue_independence_completeness_audit_v094f':
        raise RuntimeError('v094f report status/analysis mismatch')
    ir = obj.get('input_reproduction', {})
    if ir.get('audited_matchable') != 763 or ir.get('candidate_csv_reads') != 0:
        raise RuntimeError('v094f parent state does not match expected audited population/guards')
    w = obj.get('mechanism_tests', {}).get('window_251_300', {})
    o = obj.get('mechanism_tests', {}).get('outside_251_300', {})
    if not close(w.get('observed_confirm_rate'), 0.44343033265650356, 1e-10):
        raise RuntimeError('v094f 251-300 observed confirm rate differs from frozen known result')
    if not close(o.get('observed_confirm_rate'), 0.006231584966291305, 1e-10):
        raise RuntimeError('v094f outside observed confirm rate differs from frozen known result')
    sci = obj.get('scan_catalogue_identity', {})
    if sci.get('cross_plate_duplicate_groups') != 1 or sci.get('derived_process_ids_shared_across_multiple_scans_count') != 0:
        raise RuntimeError('v094f scan/process identity result differs from frozen known result')

    # Verify required parent Git artifacts exist locally and freeze their hashes in the new provenance record.
    v094f_contract = repo / 'pipeline_v0.2.0' / 'research' / 'prospective_freezes' / 'applause_dr4_catalogue_independence_completeness_contract_v094f.json'
    v094f_prov = repo / 'pipeline_v0.2.0' / 'research' / 'prospective_freezes' / 'applause_dr4_catalogue_independence_completeness_parent_provenance_v094f.json'
    v094f_runner = repo / 'pipeline_v0.2.0' / 'tools' / 'run_applause_dr4_catalogue_independence_completeness_audit_v094f.py'
    source_inv = repo / 'pipeline_v0.2.0' / 'research' / 'prospective_freezes' / 'applause_dr4_v094c_source_cache_inventory_v094e.csv'
    for p in (v094f_contract, v094f_prov, v094f_runner, source_inv):
        if not p.is_file():
            raise FileNotFoundError(p)

    vp = json.loads(v094f_prov.read_text(encoding='utf-8'))
    fi = vp.get('frozen_local_inputs', {})
    v093_scan = project / fi['v093_scan_cache']
    v093_solution = project / fi['v093_solution_cache']
    v094c_runner = project / fi['v094c_runner']
    v094d_master = project / fi['v094d_master_registry']
    for p in (v093_scan, v093_solution, v094c_runner, v094d_master):
        if not p.is_file():
            raise FileNotFoundError(p)

    with source_inv.open('r', encoding='utf-8-sig', newline='') as f:
        inv_rows = list(csv.DictReader(f))
    if len(inv_rows) != 1073:
        raise RuntimeError(f'expected 1073 source-cache inventory rows, got {len(inv_rows)}')

    out = repo / 'pipeline_v0.2.0' / 'research' / 'prospective_freezes' / 'applause_dr4_gaia_identity_control_recovery_parent_provenance_v094g.json'
    provenance = {
        'status': 'FROZEN_PARENT_PROVENANCE_PREPARED_BEFORE_V094G_EXECUTION',
        'parent_v094f_freeze_commit': PARENT_COMMIT,
        'guards_at_provenance_preparation': {
            'candidate_csv_read': False,
            'candidate_coordinates_read': False,
            'candidate_source_ids_read': False,
            'source_calib_queries': 0,
            'gaia_network_queries': 0,
            'v094g_results_seen': False,
        },
        'v094f_results': {
            'report': rel(report, project), 'report_sha256': sha256(report),
            'per_triplet': rel(per, project), 'per_triplet_sha256': sha256(per),
            'science_pair_overlap': rel(pair, project), 'science_pair_overlap_sha256': sha256(pair),
            'scan_process_fingerprint': rel(scan, project), 'scan_process_fingerprint_sha256': sha256(scan),
            'output_manifest': rel(manifest, project), 'output_manifest_sha256': sha256(manifest),
            'known_aggregate': {
                'matchable_triplets': ir['audited_matchable'],
                'candidate_csv_reads': ir['candidate_csv_reads'],
                'window_251_300_observed_confirm_rate': w.get('observed_confirm_rate'),
                'window_251_300_null30_rate': w.get('null30_rate'),
                'window_251_300_null60_rate': w.get('null60_rate'),
                'window_251_300_observed_to_null30_ratio': w.get('observed_to_null30_ratio'),
                'window_251_300_control_to_positive_cache_ratio': w.get('median_control_to_positive_cache_count_ratio'),
                'window_251_300_control_to_independent_cache_ratio': w.get('median_control_to_independent_cache_count_ratio'),
                'window_251_300_control_minus_positive_faint_limit': w.get('median_control_minus_positive_faint_limit'),
                'outside_251_300_observed_confirm_rate': o.get('observed_confirm_rate'),
                'outside_251_300_null60_rate': o.get('null60_rate'),
                'cross_plate_duplicate_fingerprint_groups': sci.get('cross_plate_duplicate_groups'),
                'shared_process_ids_across_scans': sci.get('derived_process_ids_shared_across_multiple_scans_count'),
            },
        },
        'frozen_git_parent_artifacts': {
            'v094f_contract_repo_path': rel(v094f_contract, repo), 'v094f_contract_sha256': sha256(v094f_contract),
            'v094f_parent_provenance_repo_path': rel(v094f_prov, repo), 'v094f_parent_provenance_sha256': sha256(v094f_prov),
            'v094f_runner_repo_path': rel(v094f_runner, repo), 'v094f_runner_sha256': sha256(v094f_runner),
            'source_cache_inventory_repo_path': rel(source_inv, repo), 'source_cache_inventory_sha256': sha256(source_inv),
            'source_cache_inventory_rows': len(inv_rows),
        },
        'frozen_local_inputs': {
            'v093_scan_cache': rel(v093_scan, project), 'v093_scan_cache_sha256': sha256(v093_scan),
            'v093_solution_cache': rel(v093_solution, project), 'v093_solution_cache_sha256': sha256(v093_solution),
            'v094c_runner': rel(v094c_runner, project), 'v094c_runner_sha256': sha256(v094c_runner),
            'v094d_master_registry': rel(v094d_master, project), 'v094d_master_registry_sha256': sha256(v094d_master),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'v094g parent provenance prepared: {out}')
    print(f'v094f report sha256: {sha256(report)}')
    print(f'source inventory: {len(inv_rows)} scans')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
