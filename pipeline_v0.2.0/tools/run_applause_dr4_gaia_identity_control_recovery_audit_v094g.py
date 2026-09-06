#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import Counter, defaultdict
import argparse, csv, hashlib, heapq, importlib.util, json, math, re, subprocess, time
import urllib.parse, urllib.request, xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial import cKDTree

CONTRACT_REL = Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_gaia_identity_control_recovery_contract_v094g.json')
PROV_REL = Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_gaia_identity_control_recovery_parent_provenance_v094g.json')
RUNNER_REL = Path('pipeline_v0.2.0/tools/run_applause_dr4_gaia_identity_control_recovery_audit_v094g.py')
INV_REL = Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_v094c_source_cache_inventory_v094e.csv')
PARENT_COMMIT = '9fba0d822795c2eea894989b4feca7a3e42e70f1'
TAP_ASYNC = 'https://www.plate-archive.org/tap/async'

POPULATION_COUNTS = {'W251_275': 243829, 'W276_300': 60601, 'OUTSIDE_251_300': 23453}
SAMPLE_TARGETS = {'W251_275': 10000, 'W276_300': 5000, 'OUTSIDE_251_300': 10000}

SCIENCE_FIELDS = [
    'source_id','process_id','scan_id','plate_id','archive_id','annular_bin','dist_edge',
    'sextractor_flags','model_prediction','ra_icrs','dec_icrs','ra_error','dec_error','nn_dist',
    'natmag','natmag_error','phot_range_flags','phot_calib_flags','color_term','cat_natmag',
    'gaiaedr3_gmag','gaiaedr3_id','gaiaedr3_bp_rp','gaiaedr3_dist','gaiaedr3_neighbors','match_radius'
]
CONTROL_FIELDS = [
    'source_id','process_id','scan_id','plate_id','archive_id','sextractor_flags','model_prediction',
    'ra_icrs','dec_icrs','ra_error','dec_error','nn_dist','natmag','natmag_error','phot_range_flags',
    'color_term','cat_natmag','gaiaedr3_gmag','gaiaedr3_id','gaiaedr3_bp_rp','gaiaedr3_dist','gaiaedr3_neighbors'
]
PLATE_FIELDS = [
    'plate_id','archive_id','series','emulsion','filter','plate_quality','observatory','site_name',
    'telescope','instrument','method_code','ota_scale'
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def rows(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def safe_float(v):
    try:
        x = float(str(v if v is not None else '').strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def safe_int(v):
    x = safe_float(v)
    if x is None:
        return None
    r = int(round(x))
    return r if abs(x - r) < 1e-7 else None


def bval(v):
    return str(v if v is not None else '').strip().lower() in {'1','true','yes'}


def median(vals):
    a = sorted(float(x) for x in vals if x is not None and math.isfinite(float(x)))
    if not a:
        return None
    n = len(a)
    return a[n//2] if n % 2 else (a[n//2-1] + a[n//2]) / 2.0


def ratio(a, b):
    return None if not b else a / b


def wilson(k, n, z=1.959963984540054):
    if not n:
        return {'low': None, 'high': None}
    p = k / n
    den = 1.0 + z*z/n
    ctr = (p + z*z/(2*n)) / den
    half = z * math.sqrt((p*(1-p)/n) + z*z/(4*n*n)) / den
    return {'low': max(0.0, ctr-half), 'high': min(1.0, ctr+half)}


def angular_sep_arcsec(ra1, dec1, ra2, dec2):
    if None in (ra1, dec1, ra2, dec2):
        return None
    r1, r2 = math.radians(float(ra1)), math.radians(float(ra2))
    d1, d2 = math.radians(float(dec1)), math.radians(float(dec2))
    c = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c)) * 3600.0


def verify_git(repo: Path, freeze: str):
    subprocess.run(['git','-C',str(repo),'cat-file','-e',freeze+'^{commit}'], check=True, stdout=subprocess.DEVNULL)
    for rel in (CONTRACT_REL, PROV_REL, RUNNER_REL):
        frozen = subprocess.check_output(['git','-C',str(repo),'show',f'{freeze}:{rel.as_posix()}'])
        local = (repo / rel).read_bytes()
        if frozen != local:
            raise RuntimeError(f'Frozen Git byte mismatch: {rel}')
    if subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',PARENT_COMMIT,freeze]).returncode != 0:
        raise RuntimeError('v094g freeze does not descend from frozen v094f parent')


def verify_parent_inputs(project: Path, repo: Path, prov: dict):
    checks = []
    vr = prov['v094f_results']
    checks += [
        (project/vr['report'], vr['report_sha256']),
        (project/vr['per_triplet'], vr['per_triplet_sha256']),
        (project/vr['science_pair_overlap'], vr['science_pair_overlap_sha256']),
        (project/vr['scan_process_fingerprint'], vr['scan_process_fingerprint_sha256']),
        (project/vr['output_manifest'], vr['output_manifest_sha256']),
    ]
    fg = prov['frozen_git_parent_artifacts']
    checks += [
        (repo/fg['v094f_contract_repo_path'], fg['v094f_contract_sha256']),
        (repo/fg['v094f_parent_provenance_repo_path'], fg['v094f_parent_provenance_sha256']),
        (repo/fg['v094f_runner_repo_path'], fg['v094f_runner_sha256']),
        (repo/fg['source_cache_inventory_repo_path'], fg['source_cache_inventory_sha256']),
    ]
    fl = prov['frozen_local_inputs']
    checks += [
        (project/fl['v093_scan_cache'], fl['v093_scan_cache_sha256']),
        (project/fl['v093_solution_cache'], fl['v093_solution_cache_sha256']),
        (project/fl['v094c_runner'], fl['v094c_runner_sha256']),
        (project/fl['v094d_master_registry'], fl['v094d_master_registry_sha256']),
    ]
    for p, h in checks:
        if not p.is_file() or sha256(p) != h:
            raise RuntimeError(f'Frozen parent input hash mismatch: {p}')

    inv_path = repo / fg['source_cache_inventory_repo_path']
    inv = list(rows(inv_path))
    if len(inv) != 1073:
        raise RuntimeError('source cache inventory row count mismatch')
    for i, r in enumerate(inv, 1):
        p = project / r['relative_path']
        if (not p.is_file() or p.stat().st_size != int(r['size_bytes']) or sha256(p) != r['sha256']):
            raise RuntimeError(f'source cache changed: scan={r["scan_id"]}')
        if i % 100 == 0:
            print(f'source-cache verification: {i}/1073', flush=True)
    return inv


def load_v094c_module(project: Path, prov: dict):
    p = project / prov['frozen_local_inputs']['v094c_runner']
    spec = importlib.util.spec_from_file_location('v094c_frozen_for_v094g', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def parse_stc(v):
    nums = [float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?', str(v or ''))]
    if len(nums) < 8:
        return None
    nums = nums[-8:]
    pts = [(nums[i] % 360.0, nums[i+1]) for i in range(0,8,2)]
    return None if any(not(-90 <= d <= 90) for _,d in pts) else pts


def load_geometry(project: Path, prov: dict):
    st = list(rows(project / prov['frozen_local_inputs']['v093_scan_cache']))
    sol = list(rows(project / prov['frozen_local_inputs']['v093_solution_cache']))
    plate_scans = defaultdict(list)
    for r in st:
        pid, sid = safe_int(r.get('plate_id')), safe_int(r.get('scan_id'))
        if pid is not None and sid is not None:
            plate_scans[pid].append(sid)
    scan_polys = defaultdict(list)
    for r in sol:
        sid = safe_int(r.get('scan_id'))
        poly = parse_stc(r.get('stc_polygon'))
        if sid is not None and poly:
            scan_polys[sid].append(poly)
    for pid in list(plate_scans):
        plate_scans[pid] = sorted(set(s for s in plate_scans[pid] if scan_polys.get(s)))
    return plate_scans, scan_polys


def stratum_for_ordinal(mo):
    if 251 <= mo <= 275:
        return 'W251_275'
    if 276 <= mo <= 300:
        return 'W276_300'
    return 'OUTSIDE_251_300'


def hash64(payload: dict):
    text = f"{payload['triplet_index']}|{payload['p1']}|{payload['p2']}|{payload['q1']}|{payload['q2']}"
    return int.from_bytes(hashlib.sha256(text.encode('ascii')).digest()[:8], 'big', signed=False)


def offer_bottom_k(heaps, stratum, payload):
    k = SAMPLE_TARGETS[stratum]
    hv = hash64(payload)
    item = (-hv, text_key(payload), payload)
    h = heaps[stratum]
    if len(h) < k:
        heapq.heappush(h, item)
    elif hv < -h[0][0]:
        heapq.heapreplace(h, item)


def text_key(p):
    return f"{p['triplet_index']}:{p['p1']}:{p['p2']}:{p['q1']}:{p['q2']}"


def build_deterministic_sample(project: Path, prov: dict, mod, plate_scans, scan_polys):
    per_path = project / prov['v094f_results']['per_triplet']
    per = list(rows(per_path))
    if len(per) != 784:
        raise RuntimeError(f'expected 784 v094f per-triplet rows, got {len(per)}')
    cache = mod.PlateLRU()
    heaps = {k: [] for k in SAMPLE_TARGETS}
    pop = Counter()
    triplet_rows = {}
    replay_total = 0

    for n, r in enumerate(per, 1):
        mo = safe_int(r.get('matchable_ordinal'))
        if mo is None or bval(r.get('zero_source_hold')):
            continue
        ti = safe_int(r.get('triplet_index'))
        pp, qp, cp = safe_int(r.get('positive_plate')), safe_int(r.get('independent_plate')), safe_int(r.get('control_plate'))
        ps, qs, cs = plate_scans.get(pp, []), plate_scans.get(qp, []), plate_scans.get(cp, [])
        pdata, qdata, cdata = cache.get(pp, ps), cache.get(qp, qs), cache.get(cp, cs)
        if not (pdata['usable'] and qdata['usable'] and cdata['usable']):
            raise RuntimeError(f'unexpected unusable source data at triplet {ti}')
        pra, pdec = pdata['rep_ra'], pdata['rep_dec']
        covp = mod.coverage_count_batch(pra, pdec, ps, scan_polys)
        covq = mod.coverage_count_batch(pra, pdec, qs, scan_polys)
        covc = mod.coverage_count_batch(pra, pdec, cs, scan_polys)
        idx = np.flatnonzero((covp >= 1) & (covq >= 1) & (covc >= 1))
        if len(idx):
            dc, _ = cdata['all_tree'].query(mod.xyz(pra[idx], pdec[idx]), k=1)
            csep = mod.arcsec_from_chord_array(dc)
            midx = idx[csep > mod.BUSKO_R_ARCSEC]
        else:
            midx = np.asarray([], dtype=np.int64)
        if len(qdata['rep_ra']) and len(midx):
            qtree = cKDTree(mod.xyz(qdata['rep_ra'], qdata['rep_dec']))
            dq, qi = qtree.query(mod.xyz(pra[midx], pdec[midx]), k=1)
            qsep = mod.arcsec_from_chord_array(dq)
            good = qsep <= mod.CONFIRM_DIAG_ARCSEC
            final_p = midx[good]
            final_q = np.asarray(qi[good], dtype=np.int64)
        else:
            final_p = np.asarray([], dtype=np.int64)
            final_q = np.asarray([], dtype=np.int64)

        expected = safe_int(r.get('candidate_csv_rows')) or 0
        if len(final_p) != expected:
            raise RuntimeError(f'v094g mechanical replay mismatch triplet={ti}: replay={len(final_p)} expected={expected}')
        replay_total += len(final_p)
        stratum = stratum_for_ordinal(mo)
        pop[stratum] += len(final_p)
        triplet_rows[ti] = r

        for pi, qj in zip(final_p, final_q):
            p1 = int(pdata['rep_source1'][int(pi)])
            p2 = int(pdata['rep_source2'][int(pi)])
            q1 = int(qdata['rep_source1'][int(qj)])
            q2 = int(qdata['rep_source2'][int(qj)])
            payload = {
                'stratum': stratum, 'triplet_index': ti, 'matchable_ordinal': mo,
                'positive_plate': pp, 'independent_plate': qp, 'control_plate': cp,
                'positive_scans': tuple(int(x) for x in ps),
                'independent_scans': tuple(int(x) for x in qs),
                'control_scans': tuple(int(x) for x in cs),
                'p1': p1, 'p2': p2, 'q1': q1, 'q2': q2,
                'p_ra': float(pra[int(pi)]), 'p_dec': float(pdec[int(pi)]),
                'q_ra': float(qdata['rep_ra'][int(qj)]), 'q_dec': float(qdata['rep_dec'][int(qj)]),
                'control_faint_limit': safe_float(r.get('control_median_faint_limit')),
                'control_color_term': safe_float(r.get('control_median_color_term')),
            }
            offer_bottom_k(heaps, stratum, payload)
        if n % 25 == 0:
            print(f'v094g candidate replay/sample: {n}/784 triplets', flush=True)

    if replay_total != 327883:
        raise RuntimeError(f'candidate replay total {replay_total} != 327883')
    if dict(pop) != POPULATION_COUNTS:
        raise RuntimeError(f'stratum population mismatch: {dict(pop)} expected={POPULATION_COUNTS}')

    sample = []
    for s, heap in heaps.items():
        items = sorted([(-a, p) for a, _, p in heap], key=lambda x: (x[0], text_key(x[1])))
        if len(items) != SAMPLE_TARGETS[s]:
            raise RuntimeError(f'sample size mismatch {s}: {len(items)}')
        for hv, p in items:
            p['sample_hash64'] = hv
            sample.append(p)
    sample.sort(key=lambda p: (p['stratum'], p['sample_hash64'], text_key(p)))
    return sample, dict(pop), triplet_rows


def discover_result_url(job):
    try:
        with urllib.request.urlopen(job, timeout=120) as r:
            body = r.read().decode('utf-8','replace')
        root = ET.fromstring(body)
        for el in root.iter():
            if el.tag.lower().endswith('result'):
                href = el.attrib.get('{http://www.w3.org/1999/xlink}href') or el.attrib.get('href')
                if href:
                    return urllib.parse.urljoin(job+'/', href)
    except Exception:
        pass
    for suffix in ('/results/result','/results/votable'):
        u = job + suffix
        try:
            with urllib.request.urlopen(u, timeout=120) as r:
                head = r.read(512)
            if b'VOTABLE' in head.upper() or head.lstrip().startswith(b'<?xml'):
                return u
        except Exception:
            pass
    raise RuntimeError(f'Could not discover TAP result URL for {job}')


def table_colnames(tbl):
    return {str(c).lower() for c in tbl.colnames}


def tap_table(query: str, raw: Path, label: str, expected_cols, maxrec=500000):
    from astropy.table import Table
    raw.parent.mkdir(parents=True, exist_ok=True)
    q = ' '.join(query.split())
    qsha = hashlib.sha256(q.encode('utf-8')).hexdigest()
    qpath = raw.with_suffix(raw.suffix + '.query.sha256')
    if raw.is_file() and qpath.is_file() and qpath.read_text().strip() == qsha:
        try:
            tbl = Table.read(raw, format='votable')
            if set(expected_cols).issubset(table_colnames(tbl)):
                return tbl, 'CACHE_REUSED'
        except Exception:
            pass
        raw.unlink(missing_ok=True)
    for attempt in range(1, 6):
        try:
            print(f'{label}: attempt {attempt}', flush=True)
            data = urllib.parse.urlencode({
                'REQUEST':'doQuery','LANG':'ADQL','FORMAT':'votable','QUERY':q,
                'MAXREC':str(maxrec),'PHASE':'RUN'
            }).encode('utf-8')
            req = urllib.request.Request(TAP_ASYNC, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=180) as r:
                job = r.geturl().rstrip('/')
                body = r.read(20000).decode('utf-8','replace')
                loc = r.headers.get('Location')
                if loc:
                    job = urllib.parse.urljoin(job+'/', loc).rstrip('/')
            if '/tap/async/' not in job:
                m = re.search(r'https?://[^"\s<]+/tap/async/[^"\s<]+', body)
                if m:
                    job = m.group(0).rstrip('/')
            if '/tap/async/' not in job:
                raise RuntimeError('cannot resolve TAP job URL')
            t0 = time.time()
            while True:
                with urllib.request.urlopen(job+'/phase', timeout=120) as r:
                    phase = r.read().decode('utf-8','replace').strip().upper()
                if 'COMPLETED' in phase:
                    break
                if 'ERROR' in phase or 'ABORTED' in phase:
                    raise RuntimeError(f'TAP phase {phase}')
                if time.time() - t0 > 2*3600:
                    raise RuntimeError('TAP query exceeded 2 hours')
                time.sleep(10)
            u = discover_result_url(job)
            tmp = raw.with_suffix(raw.suffix + '.tmp')
            with urllib.request.urlopen(u, timeout=600) as r, tmp.open('wb') as f:
                while True:
                    b = r.read(8*1024*1024)
                    if not b:
                        break
                    f.write(b)
            tmp.replace(raw)
            tbl = Table.read(raw, format='votable')
            missing = set(expected_cols) - table_colnames(tbl)
            if missing:
                raise RuntimeError(f'TAP result missing columns {sorted(missing)}')
            if len(tbl) >= maxrec:
                raise RuntimeError(f'TAP result reached MAXREC={maxrec}; refuse possible truncation')
            qpath.write_text(qsha+'\n', encoding='ascii')
            return tbl, 'COMPLETE'
        except Exception as e:
            print(f'{label}: retry after error: {e}', flush=True)
            if attempt == 5:
                raise
            time.sleep(15*attempt)
    raise RuntimeError('unreachable TAP failure')


def cell(row, c):
    try:
        v = row[c]
        if np.ma.is_masked(v):
            return None
        if isinstance(v, bytes):
            return v.decode('utf-8','replace')
        if hasattr(v, 'item'):
            return v.item()
        return v
    except Exception:
        return None


def acquire_science_metadata(project: Path, source_ids):
    work = project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'tap_raw'/'science_source_calib'
    ids = sorted(set(int(x) for x in source_ids if int(x) >= 0))
    meta = {}
    batch_size = 2000
    nb = (len(ids)+batch_size-1)//batch_size
    for bi, start in enumerate(range(0, len(ids), batch_size), 1):
        group = ids[start:start+batch_size]
        q = f"SELECT {','.join(SCIENCE_FIELDS)} FROM applause_dr4.source_calib WHERE source_id IN ({','.join(map(str,group))})"
        tbl, status = tap_table(q, work/f'batch_{bi:04d}.vot', f'science source_calib batch {bi}/{nb}', SCIENCE_FIELDS, maxrec=10000)
        for r in tbl:
            sid = safe_int(cell(r,'source_id'))
            if sid is None:
                continue
            if sid in meta:
                raise RuntimeError(f'duplicate source_id in source_calib results: {sid}')
            meta[sid] = {c: cell(r,c) for c in SCIENCE_FIELDS}
    missing = sorted(set(ids)-set(meta))
    state = project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'state'
    state.mkdir(parents=True, exist_ok=True)
    (state/'science_source_calib_acquisition.json').write_text(json.dumps({
        'requested_unique_source_ids': len(ids), 'returned_unique_source_ids': len(meta),
        'missing_source_ids_count': len(missing), 'batches': nb
    }, indent=2)+'\n', encoding='utf-8')
    if missing:
        raise RuntimeError(f'source_calib missing {len(missing)} frozen sample source IDs; refuse incomplete mechanism audit')
    return meta, {'requested':len(ids),'returned':len(meta),'batches':nb}


def rep_summary(source_ids, meta):
    ids = [int(x) for x in source_ids if int(x) >= 0]
    rr = [meta[x] for x in ids]
    gaia = [safe_int(r.get('gaiaedr3_id')) for r in rr]
    gaia = [x for x in gaia if x is not None and x > 0]
    uniq = sorted(set(gaia))
    if not uniq:
        gstatus, gid = 'MISSING', None
    elif len(uniq) > 1:
        gstatus, gid = 'CONFLICT', None
    else:
        gid = uniq[0]
        gstatus = 'CONSENSUS_COMPLETE' if len(gaia) == len(rr) else 'CONSENSUS_PARTIAL'
    def med(field): return median([safe_float(r.get(field)) for r in rr])
    flags = [safe_int(r.get('sextractor_flags')) for r in rr]
    phot = [safe_int(r.get('phot_range_flags')) for r in rr]
    return {
        'gaia_status':gstatus,'gaia_id':gid,'underlying_sources':len(rr),
        'model_prediction':med('model_prediction'),'gaia_dist':med('gaiaedr3_dist'),'nn_dist':med('nn_dist'),
        'cat_natmag':med('cat_natmag'),'color_term':med('color_term'),'bp_rp':med('gaiaedr3_bp_rp'),
        'gmag':med('gaiaedr3_gmag'),'ra_error':med('ra_error'),'dec_error':med('dec_error'),
        'sextractor_flags_all_zero': bool(flags) and all(x == 0 for x in flags if x is not None) and all(x is not None for x in flags),
        'phot_range_flags': phot,
    }


def build_control_targets(sample, classifications):
    by_scan = defaultdict(set)
    for p, c in zip(sample, classifications):
        if c['science_identity'] != 'SAME_GAIA':
            continue
        gid = c['gaia_id']
        for sid in p['control_scans']:
            by_scan[int(sid)].add(int(gid))
    return by_scan


def make_control_query_batches(by_scan, max_pairs=1800, max_clauses=50):
    clauses = []
    for sid in sorted(by_scan):
        gids = sorted(by_scan[sid])
        for start in range(0, len(gids), 700):
            chunk = gids[start:start+700]
            clauses.append((sid, chunk))
    batches, cur, count = [], [], 0
    for sid, gids in clauses:
        if cur and (count + len(gids) > max_pairs or len(cur) >= max_clauses):
            batches.append(cur); cur=[]; count=0
        cur.append((sid,gids)); count += len(gids)
    if cur:
        batches.append(cur)
    return batches


def acquire_control_recovery(project: Path, by_scan):
    work = project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'tap_raw'/'control_source_calib'
    requested_pairs = {(int(s),int(g)) for s,gg in by_scan.items() for g in gg}
    batches = make_control_query_batches(by_scan)
    found = defaultdict(list)
    for bi, batch in enumerate(batches, 1):
        wh = []
        for sid, gids in batch:
            wh.append(f"(scan_id={sid} AND gaiaedr3_id IN ({','.join(map(str,gids))}))")
        q = f"SELECT {','.join(CONTROL_FIELDS)} FROM applause_dr4.source_calib WHERE " + ' OR '.join(wh)
        tbl, status = tap_table(q, work/f'batch_{bi:04d}.vot', f'control same-Gaia recovery batch {bi}/{len(batches)}', CONTROL_FIELDS, maxrec=100000)
        for r in tbl:
            sid, gid = safe_int(cell(r,'scan_id')), safe_int(cell(r,'gaiaedr3_id'))
            if sid is None or gid is None or (sid,gid) not in requested_pairs:
                continue
            found[(sid,gid)].append({c:cell(r,c) for c in CONTROL_FIELDS})
    state = project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'state'
    state.mkdir(parents=True, exist_ok=True)
    recovered_pairs = sum(1 for k in requested_pairs if found.get(k))
    (state/'control_source_calib_acquisition.json').write_text(json.dumps({
        'requested_scan_gaia_pairs':len(requested_pairs),'recovered_scan_gaia_pairs':recovered_pairs,
        'query_batches':len(batches),'returned_rows':sum(len(v) for v in found.values())
    }, indent=2)+'\n', encoding='utf-8')
    return found, {'requested_pairs':len(requested_pairs),'recovered_pairs':recovered_pairs,'batches':len(batches),'returned_rows':sum(len(v) for v in found.values())}


def acquire_plate_metadata(project: Path, plate_ids):
    work = project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'tap_raw'/'plate_metadata'
    ids = sorted(set(int(x) for x in plate_ids if x is not None))
    out = {}
    batch_size = 500
    nb = (len(ids)+batch_size-1)//batch_size
    for bi,start in enumerate(range(0,len(ids),batch_size),1):
        group=ids[start:start+batch_size]
        q=f"SELECT {','.join(PLATE_FIELDS)} FROM applause_dr4.plate WHERE plate_id IN ({','.join(map(str,group))})"
        tbl,status=tap_table(q,work/f'batch_{bi:03d}.vot',f'plate metadata batch {bi}/{nb}',PLATE_FIELDS,maxrec=5000)
        for r in tbl:
            pid=safe_int(cell(r,'plate_id'))
            if pid is not None: out[pid]={c:cell(r,c) for c in PLATE_FIELDS}
    return out, {'requested':len(ids),'returned':len(out),'batches':nb}


def norm_text(v):
    s = str(v if v is not None else '').strip()
    return s.casefold() if s else None


def estimate_control_margin(ps, qs, control_color_term, control_faint_limit):
    if control_color_term is None or control_faint_limit is None:
        return None
    preds=[]
    for r in (ps,qs):
        cat, ct, bp = r.get('cat_natmag'), r.get('color_term'), r.get('bp_rp')
        if None in (cat,ct,bp):
            continue
        rp = cat - ct*bp
        preds.append(rp + control_color_term*bp)
    pred = median(preds)
    return None if pred is None else control_faint_limit - pred


def sep_bin(x):
    if x is None:return 'UNKNOWN'
    if x <= 5:return 'LE5'
    if x <= 10:return 'GT5_LE10'
    if x <= 30:return 'GT10_LE30'
    if x <= 60:return 'GT30_LE60'
    return 'GT60'


def margin_bin(x):
    if x is None:return 'UNKNOWN'
    if x < -0.5:return 'LT_NEG0P5'
    if x < 0:return 'NEG0P5_TO_0'
    if x < 0.5:return '0_TO_0P5'
    if x < 1.0:return '0P5_TO_1'
    return 'GE1'


def classify_sample(sample, science_meta, control_found, plate_meta):
    classifications=[]
    consistency_violations=0
    for p in sample:
        ps=rep_summary([p['p1'],p['p2']],science_meta)
        qs=rep_summary([p['q1'],p['q2']],science_meta)
        if ps['gaia_status'].startswith('CONSENSUS') and qs['gaia_status'].startswith('CONSENSUS'):
            if ps['gaia_id']==qs['gaia_id']:
                ident='SAME_GAIA'; gid=ps['gaia_id']
            else:
                ident='DIFFERENT_GAIA'; gid=None
        elif ps['gaia_status']=='CONFLICT' or qs['gaia_status']=='CONFLICT':
            ident='GAIA_CONFLICT'; gid=None
        else:
            ident='GAIA_UNRESOLVED'; gid=None

        recovered=[]
        min_sep=None
        recovery_quality=[]
        if ident=='SAME_GAIA':
            for sid in p['control_scans']:
                for r in control_found.get((int(sid),int(gid)),[]):
                    ra,dec=safe_float(r.get('ra_icrs')),safe_float(r.get('dec_icrs'))
                    sep=angular_sep_arcsec(p['p_ra'],p['p_dec'],ra,dec)
                    recovered.append((sep,r))
            valid=[x for x in recovered if x[0] is not None]
            if valid:
                min_sep=min(x[0] for x in valid)
            if min_sep is not None and min_sep <= 5.000001:
                consistency_violations += 1

        margin=estimate_control_margin(ps,qs,p.get('control_color_term'),p.get('control_faint_limit')) if ident=='SAME_GAIA' and not recovered else None
        pmodel,qmodel=ps.get('model_prediction'),qs.get('model_prediction')
        both_true = pmodel is not None and qmodel is not None and pmodel>=0.9 and qmodel>=0.9
        any_art = (pmodel is not None and pmodel<0.1) or (qmodel is not None and qmodel<0.1)

        pm,qm,cm=plate_meta.get(p['positive_plate'],{}),plate_meta.get(p['independent_plate'],{}),plate_meta.get(p['control_plate'],{})
        pe,qe,ce=norm_text(pm.get('emulsion')),norm_text(qm.get('emulsion')),norm_text(cm.get('emulsion'))
        pf,qf,cf=norm_text(pm.get('filter')),norm_text(qm.get('filter')),norm_text(cm.get('filter'))
        science_emulsion_same = None if pe is None or qe is None else pe==qe
        science_filter_same = None if pf is None or qf is None else pf==qf
        control_emulsion_diff = None if not science_emulsion_same or ce is None else ce!=pe
        control_filter_diff = None if not science_filter_same or cf is None else cf!=pf

        if recovered:
            rmodels=[safe_float(r.get('model_prediction')) for _,r in recovered]
            recovery_model=median(rmodels)
        else: recovery_model=None
        classifications.append({
            'stratum':p['stratum'],'triplet_index':p['triplet_index'],'matchable_ordinal':p['matchable_ordinal'],
            'science_identity':ident,'gaia_id':gid,'positive_gaia_status':ps['gaia_status'],'independent_gaia_status':qs['gaia_status'],
            'both_science_true_like':both_true,'any_science_artifact_like':any_art,
            'positive_model_prediction':pmodel,'independent_model_prediction':qmodel,
            'positive_gaia_dist':ps.get('gaia_dist'),'independent_gaia_dist':qs.get('gaia_dist'),
            'positive_nn_dist':ps.get('nn_dist'),'independent_nn_dist':qs.get('nn_dist'),
            'control_same_gaia_recovered':bool(recovered),'control_recovery_min_sep_arcsec':min_sep,
            'control_recovery_sep_bin':sep_bin(min_sep) if recovered else 'NOT_RECOVERED',
            'control_recovery_model_prediction':recovery_model,
            'no_recovery_detectability_margin_mag':margin,'no_recovery_margin_bin':margin_bin(margin) if not recovered and ident=='SAME_GAIA' else 'NA',
            'science_emulsion_same':science_emulsion_same,'science_filter_same':science_filter_same,
            'control_emulsion_diff_when_science_same':control_emulsion_diff,
            'control_filter_diff_when_science_same':control_filter_diff,
            'positive_phot_flags':ps.get('phot_range_flags',[]),'independent_phot_flags':qs.get('phot_range_flags',[]),
        })
    return classifications, consistency_violations


def summarize_stratum(name, population, sample_rows, classes):
    c=[x for x in classes if x['stratum']==name]
    n=len(c); ids=Counter(x['science_identity'] for x in c)
    same=ids['SAME_GAIA']; resolved=same+ids['DIFFERENT_GAIA']
    rec=sum(x['science_identity']=='SAME_GAIA' and x['control_same_gaia_recovered'] for x in c)
    norec=same-rec
    true_like=sum(bool(x['both_science_true_like']) for x in c)
    artifact=sum(bool(x['any_science_artifact_like']) for x in c)
    sep=Counter(x['control_recovery_sep_bin'] for x in c if x['science_identity']=='SAME_GAIA' and x['control_same_gaia_recovered'])
    mb=Counter(x['no_recovery_margin_bin'] for x in c if x['science_identity']=='SAME_GAIA' and not x['control_same_gaia_recovered'])
    em=Counter('MISSING' if x['science_emulsion_same'] is None else ('SCIENCE_SAME_CONTROL_DIFF' if x['science_emulsion_same'] and x['control_emulsion_diff_when_science_same'] else ('SCIENCE_SAME_CONTROL_SAME_OR_MISSING' if x['science_emulsion_same'] else 'SCIENCE_DIFFERENT')) for x in c)
    fi=Counter('MISSING' if x['science_filter_same'] is None else ('SCIENCE_SAME_CONTROL_DIFF' if x['science_filter_same'] and x['control_filter_diff_when_science_same'] else ('SCIENCE_SAME_CONTROL_SAME_OR_MISSING' if x['science_filter_same'] else 'SCIENCE_DIFFERENT')) for x in c)
    unique_gaia=len(set(x['gaia_id'] for x in c if x['science_identity']=='SAME_GAIA' and x['gaia_id'] is not None))
    same_ci=wilson(same,n); rec_ci=wilson(rec,same)
    return {
        'stratum':name,'population_candidate_rows':population,'sample_rows':n,'sample_fraction':n/population,
        'same_gaia_rows':same,'same_gaia_fraction_all':ratio(same,n),'same_gaia_ci95_low':same_ci['low'],'same_gaia_ci95_high':same_ci['high'],
        'different_gaia_rows':ids['DIFFERENT_GAIA'],'gaia_unresolved_rows':ids['GAIA_UNRESOLVED'],'gaia_conflict_rows':ids['GAIA_CONFLICT'],
        'same_gaia_fraction_among_both_resolved':ratio(same,resolved),
        'unique_same_gaia_ids_in_sample':unique_gaia,'same_gaia_rows_per_unique_gaia':ratio(same,unique_gaia),
        'both_science_true_like_rows':true_like,'both_science_true_like_fraction':ratio(true_like,n),
        'any_science_artifact_like_rows':artifact,'any_science_artifact_like_fraction':ratio(artifact,n),
        'same_gaia_control_recovered_rows':rec,'same_gaia_control_recovered_fraction':ratio(rec,same),
        'same_gaia_control_recovered_ci95_low':rec_ci['low'],'same_gaia_control_recovered_ci95_high':rec_ci['high'],
        'same_gaia_control_not_recovered_rows':norec,
        'control_recovery_sep_bins_json':json.dumps(dict(sep),sort_keys=True,separators=(',',':')),
        'no_recovery_detectability_margin_bins_json':json.dumps(dict(mb),sort_keys=True,separators=(',',':')),
        'median_positive_model_prediction':median([x['positive_model_prediction'] for x in c]),
        'median_independent_model_prediction':median([x['independent_model_prediction'] for x in c]),
        'median_positive_gaia_dist_arcsec':median([x['positive_gaia_dist'] for x in c]),
        'median_independent_gaia_dist_arcsec':median([x['independent_gaia_dist'] for x in c]),
        'median_positive_nn_dist_arcsec':median([x['positive_nn_dist'] for x in c]),
        'median_independent_nn_dist_arcsec':median([x['independent_nn_dist'] for x in c]),
        'median_control_recovery_sep_arcsec':median([x['control_recovery_min_sep_arcsec'] for x in c if x['control_same_gaia_recovered']]),
        'median_no_recovery_detectability_margin_mag':median([x['no_recovery_detectability_margin_mag'] for x in c if not x['control_same_gaia_recovered']]),
        'no_recovery_predicted_ge1mag_brighter_than_control_limit_fraction':ratio(mb['GE1'],norec),
        'no_recovery_predicted_fainter_than_control_limit_fraction':ratio(mb['LT_NEG0P5']+mb['NEG0P5_TO_0'],norec),
        'emulsion_role_pattern_json':json.dumps(dict(em),sort_keys=True,separators=(',',':')),
        'filter_role_pattern_json':json.dumps(dict(fi),sort_keys=True,separators=(',',':')),
    }


def write_csv(path, rr):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields=list(rr[0].keys()) if rr else []
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rr)


def aggregate_triplets(classes):
    acc=defaultdict(Counter); meta={}
    for x in classes:
        ti=x['triplet_index'];meta[ti]=(x['stratum'],x['matchable_ordinal'])
        a=acc[ti];a['sample_rows']+=1;a['same_gaia']+=x['science_identity']=='SAME_GAIA';a['different_gaia']+=x['science_identity']=='DIFFERENT_GAIA';a['gaia_unresolved']+=x['science_identity']=='GAIA_UNRESOLVED';a['gaia_conflict']+=x['science_identity']=='GAIA_CONFLICT';a['control_same_gaia_recovered']+=x['science_identity']=='SAME_GAIA' and x['control_same_gaia_recovered'];a['same_gaia_no_control_recovery']+=x['science_identity']=='SAME_GAIA' and not x['control_same_gaia_recovered'];a['same_gaia_no_control_recovery_ge1mag_bright']+=x['science_identity']=='SAME_GAIA' and not x['control_same_gaia_recovered'] and x['no_recovery_margin_bin']=='GE1';a['both_science_true_like']+=x['both_science_true_like'];a['any_science_artifact_like']+=x['any_science_artifact_like']
    out=[]
    for ti in sorted(acc):
        a=acc[ti];s,mo=meta[ti];n=a['sample_rows'];same=a['same_gaia']
        out.append({'triplet_index':ti,'matchable_ordinal':mo,'stratum':s,'sample_rows':n,'same_gaia_rows':same,'same_gaia_fraction':ratio(same,n),'different_gaia_rows':a['different_gaia'],'gaia_unresolved_rows':a['gaia_unresolved'],'gaia_conflict_rows':a['gaia_conflict'],'control_same_gaia_recovered_rows':a['control_same_gaia_recovered'],'control_recovery_fraction_of_same_gaia':ratio(a['control_same_gaia_recovered'],same),'same_gaia_no_control_recovery_rows':a['same_gaia_no_control_recovery'],'same_gaia_no_control_recovery_ge1mag_bright_rows':a['same_gaia_no_control_recovery_ge1mag_bright'],'both_science_true_like_fraction':ratio(a['both_science_true_like'],n),'any_science_artifact_like_fraction':ratio(a['any_science_artifact_like'],n)})
    return out


def save_internal_sample(project, sample):
    state=project/'work'/'applause_dr4_gaia_identity_control_recovery_audit_v094g'/'state';state.mkdir(parents=True,exist_ok=True)
    p=state/'deterministic_sample_internal_v094g.jsonl'
    with p.open('w',encoding='utf-8') as f:
        for r in sample:
            f.write(json.dumps(r,sort_keys=True,separators=(',',':'))+'\n')
    return p,sha256(p)


def self_test():
    assert stratum_for_ordinal(251)=='W251_275' and stratum_for_ordinal(300)=='W276_300' and stratum_for_ordinal(301)=='OUTSIDE_251_300'
    ci=wilson(50,100); assert 0.39<ci['low']<0.41 and 0.59<ci['high']<0.61
    assert angular_sep_arcsec(10,20,10,20) < 0.01
    meta={1:{'gaiaedr3_id':7,'model_prediction':0.99},2:{'gaiaedr3_id':7,'model_prediction':0.98}}
    r=rep_summary([1,2],meta); assert r['gaia_status']=='CONSENSUS_COMPLETE' and r['gaia_id']==7
    heaps={'W251_275':[],'W276_300':[],'OUTSIDE_251_300':[]}
    old=dict(SAMPLE_TARGETS); SAMPLE_TARGETS['W251_275']=2
    for i in range(10): offer_bottom_k(heaps,'W251_275',{'triplet_index':1,'p1':i,'p2':-1,'q1':i+100,'q2':-1})
    assert len(heaps['W251_275'])==2
    SAMPLE_TARGETS.update(old)
    print('v094g self-test PASS')
    return 0


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project-root');ap.add_argument('--repo-root');ap.add_argument('--freeze-commit');ap.add_argument('--self-test',action='store_true');args=ap.parse_args()
    if args.self_test:return self_test()
    if not all((args.project_root,args.repo_root,args.freeze_commit)):ap.error('--project-root, --repo-root and --freeze-commit are required')
    project=Path(args.project_root).resolve();repo=Path(args.repo_root).resolve();freeze=args.freeze_commit.strip();verify_git(repo,freeze)
    contract=json.loads((repo/CONTRACT_REL).read_text(encoding='utf-8'));prov=json.loads((repo/PROV_REL).read_text(encoding='utf-8'))
    if contract.get('status')!='PROSPECTIVE_GAIA_IDENTITY_CONTROL_RECOVERY_AUDIT' or prov.get('status')!='FROZEN_PARENT_PROVENANCE_PREPARED_BEFORE_V094G_EXECUTION':raise RuntimeError('contract/provenance status mismatch')
    verify_parent_inputs(project,repo,prov);print('Frozen v094g parent inputs verified',flush=True)
    mod=load_v094c_module(project,prov);plate_scans,scan_polys=load_geometry(project,prov)
    print('Replaying frozen v094c mechanics and constructing deterministic aggregate sample...',flush=True)
    sample,pop,triplet_rows=build_deterministic_sample(project,prov,mod,plate_scans,scan_polys)
    internal_path,internal_sha=save_internal_sample(project,sample)
    print(f'Deterministic sample complete: {len(sample):,} rows; internal sample sha256={internal_sha}',flush=True)

    science_ids=set()
    for p in sample:
        science_ids.update(x for x in (p['p1'],p['p2'],p['q1'],p['q2']) if int(x)>=0)
    print(f'Acquiring fixed source_calib metadata for {len(science_ids):,} unique sampled science source IDs...',flush=True)
    science_meta,science_acq=acquire_science_metadata(project,science_ids)

    # First-pass identity classification only, to prospectively derive control scan/Gaia pairs from the frozen sample.
    preliminary=[]
    for p in sample:
        ps=rep_summary([p['p1'],p['p2']],science_meta);qs=rep_summary([p['q1'],p['q2']],science_meta)
        if ps['gaia_status'].startswith('CONSENSUS') and qs['gaia_status'].startswith('CONSENSUS') and ps['gaia_id']==qs['gaia_id']:
            preliminary.append({'science_identity':'SAME_GAIA','gaia_id':ps['gaia_id']})
        elif ps['gaia_status'].startswith('CONSENSUS') and qs['gaia_status'].startswith('CONSENSUS'):
            preliminary.append({'science_identity':'DIFFERENT_GAIA','gaia_id':None})
        elif ps['gaia_status']=='CONFLICT' or qs['gaia_status']=='CONFLICT': preliminary.append({'science_identity':'GAIA_CONFLICT','gaia_id':None})
        else: preliminary.append({'science_identity':'GAIA_UNRESOLVED','gaia_id':None})
    targets=build_control_targets(sample,preliminary)
    print(f'Control same-Gaia recovery targets: {sum(len(v) for v in targets.values()):,} scan/Gaia pairs across {len(targets):,} control scans',flush=True)
    control_found,control_acq=acquire_control_recovery(project,targets)

    plate_ids=set()
    for p in sample: plate_ids.update((p['positive_plate'],p['independent_plate'],p['control_plate']))
    plate_meta,plate_acq=acquire_plate_metadata(project,plate_ids)

    classes,violations=classify_sample(sample,science_meta,control_found,plate_meta)
    summaries=[summarize_stratum(s,pop[s],SAMPLE_TARGETS[s],classes) for s in ('W251_275','W276_300','OUTSIDE_251_300')]
    trip=aggregate_triplets(classes)

    outdir=project/'results'/'applause_dr4_gaia_identity_control_recovery_audit_v094g';outdir.mkdir(parents=True,exist_ok=True)
    strat_path=outdir/'stratum_gaia_mechanism_summary_v094g.csv';trip_path=outdir/'triplet_gaia_mechanism_aggregate_v094g.csv';report_path=outdir/'applause_dr4_gaia_identity_control_recovery_audit_v094g.json';manifest=outdir/'v094g_output_manifest.sha256'
    write_csv(strat_path,summaries);write_csv(trip_path,trip)

    bys={r['stratum']:r for r in summaries}
    report={'status':'COMPLETE' if violations==0 else 'HOLD_MECHANICAL_CONSISTENCY','analysis_kind':'applause_dr4_gaia_identity_control_recovery_audit_v094g','freeze_commit':freeze,'guards':contract['guards'],'sampling':{'population_counts':pop,'sample_targets':SAMPLE_TARGETS,'sample_rows_total':len(sample),'internal_sample_work_path':str(internal_path.relative_to(project)).replace('\\','/'),'internal_sample_sha256':internal_sha,'candidate_csv_reads':0},'network_acquisition':{'science_source_calib':science_acq,'control_same_gaia_source_calib':control_acq,'plate_metadata':plate_acq,'external_gaia_queries':0},'stratum_summaries':bys,'mechanical_consistency':{'recovered_same_gaia_control_within_frozen_5arcsec_gate_count':violations,'status':'PASS' if violations==0 else 'HOLD'},'working_data_boundary':contract['working_data_boundary'],'interpretive_boundary':contract['interpretive_boundary'],'next_stop':contract['next_stop'],'outputs':{}}
    for p in (strat_path,trip_path): report['outputs'][p.name]={'sha256':sha256(p),'size_bytes':p.stat().st_size}
    report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    manifest.write_text('\n'.join(f'{sha256(p)}  {p.name}' for p in (strat_path,trip_path,report_path))+'\n',encoding='ascii')

    print('\n'+'='*104);print('v094g GAIA IDENTITY / CONTROL RECOVERY AUDIT COMPLETE');print('='*104)
    for s in ('W251_275','W276_300','OUTSIDE_251_300'):
        r=bys[s]
        print(f"{s} sample/population:                    {r['sample_rows']:,}/{r['population_candidate_rows']:,}")
        print(f"{s} same-Gaia science fraction:           {r['same_gaia_fraction_all']:.4%}")
        print(f"{s} same-Gaia among both-resolved:         {r['same_gaia_fraction_among_both_resolved']:.4%}" if r['same_gaia_fraction_among_both_resolved'] is not None else f"{s} same-Gaia among both-resolved:         NA")
        print(f"{s} same-Gaia control recovery fraction:  {r['same_gaia_control_recovered_fraction']:.4%}" if r['same_gaia_control_recovered_fraction'] is not None else f"{s} same-Gaia control recovery fraction:  NA")
        print(f"{s} both-science true-like fraction:       {r['both_science_true_like_fraction']:.4%}" if r['both_science_true_like_fraction'] is not None else f"{s} both-science true-like fraction:       NA")
        print(f"{s} any science artifact-like fraction:    {r['any_science_artifact_like_fraction']:.4%}" if r['any_science_artifact_like_fraction'] is not None else f"{s} any science artifact-like fraction:    NA")
        print(f"{s} no-control recovery >=1mag bright frac:{r['no_recovery_predicted_ge1mag_brighter_than_control_limit_fraction']:.4%}" if r['no_recovery_predicted_ge1mag_brighter_than_control_limit_fraction'] is not None else f"{s} no-control recovery >=1mag bright frac:NA")
    print(f'Mechanical <=5 arcsec control-recovery contradictions: {violations}')
    print('Candidate CSV reads:                           0')
    print('External Gaia network queries:                 0')
    print('STOP: interpret Gaia/control-recovery mechanism before corrected population, candidate inspection, or registration.')
    if violations:
        return 2
    return 0


if __name__=='__main__':
    raise SystemExit(main())
