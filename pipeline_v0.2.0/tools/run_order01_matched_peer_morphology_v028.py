from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import csv, hashlib, json, math
import numpy as np

ROOT = Path.cwd()
BASE = ROOT / 'results' / 'order01_native_full_v028'
WORK = ROOT / 'work' / 'order01_native_full_v028'

PAIR_REPORT = BASE / 'order01_whole_pair_report.json'
PS1_REPORT = BASE / 'order01_ps1_static_report_v028.json'
PS1_TRIAGE = BASE / 'order01_ps1_static_triage_v028.csv'
STRICT = BASE / 'order01_strict_match_triage_v028.csv'
POSS_CAND = BASE / 'order01_poss_native_candidates.csv'
DASCH_CAND = BASE / 'order01_dasch_native_candidates.csv'

OUTDIR = BASE / 'order01_matched_peer_morphology_v028'
OUT_ENDPOINT = OUTDIR / 'order01_matched_peer_endpoint_metrics_v028.csv'
OUT_CONTROL = OUTDIR / 'order01_matched_peer_controls_v028.csv'
OUT_SUMMARY = OUTDIR / 'order01_matched_peer_candidate_summary_v028.csv'
OUT_REPORT = OUTDIR / 'order01_matched_peer_morphology_report_v028.json'

EXPECTED_DETECTOR_SHA = '709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7'
EXPECTED_METHOD_SHA = '2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1'
EXPECTED_POLICY_SHA = '44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7'
EXPECTED_RANKS = [5, 6, 8, 10, 12, 24, 25, 26, 29, 30, 36]
EXPECTED_RAW10 = 476
EXPECTED_STRICT3 = 38
EXPECTED_POSS_CAND = 366482
EXPECTED_DASCH_CAND = 3986

MIN_PREFERRED_CONTROLS = 12
MAX_CONTROLS = 32
EXCLUSION_RADIUS_PX = 32.0
PREFERRED_SNR_RATIO = (0.75, 1.25)
FALLBACK_SNR_RATIO = (0.50, 1.50)
CUT_RADIUS = 20

CONTINUOUS_METRICS = [
    'sigma_major_px', 'sigma_minor_px', 'ellipticity',
    'peak_to_flux5', 'concentration_flux3_flux8', 'centroid_offset_px',
]
COUNT_METRICS = ['plateau_count_3x3', 'local_extreme_count_3x3']

ENDPOINT_FIELDS = [
    'strict_rank','archive','endpoint_status','tile_id','candidate_index','global_x','global_y',
    'snr','polarity','control_selection_mode','control_count','local_bg','local_sigma',
    'peak_bgsub_polarity','sigma_major_px','sigma_minor_px','ellipticity','peak_to_flux5',
    'concentration_flux3_flux8','centroid_offset_px','plateau_count_3x3','local_extreme_count_3x3',
    'sigma_major_peer_percentile','sigma_minor_peer_percentile','ellipticity_peer_percentile',
    'peak_to_flux5_peer_percentile','concentration_peer_percentile','centroid_offset_peer_percentile',
    'plateau_peer_percentile','local_extreme_peer_percentile',
    'matched_peer_extreme_continuous_metric_count','matched_peer_count_metric_ge95_count',
    'tile_npy_path','tile_npy_sha256','error'
]
CONTROL_FIELDS = [
    'strict_rank','archive','control_order','selection_mode','tile_id','candidate_index','global_x','global_y',
    'distance_from_science_px','snr','snr_ratio','polarity','local_bg','local_sigma','peak_bgsub_polarity',
    'sigma_major_px','sigma_minor_px','ellipticity','peak_to_flux5','concentration_flux3_flux8',
    'centroid_offset_px','plateau_count_3x3','local_extreme_count_3x3'
]
SUMMARY_FIELDS = [
    'strict_rank','pair_separation_arcsec','poss_snr','dasch_snr','poss_polarity','dasch_polarity','same_polarity',
    'poss_endpoint_status','dasch_endpoint_status','poss_control_count','dasch_control_count',
    'poss_matched_peer_extreme_continuous_metric_count','dasch_matched_peer_extreme_continuous_metric_count',
    'poss_matched_peer_count_metric_ge95_count','dasch_matched_peer_count_metric_ge95_count','pair_morphology_status'
]


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    tmp.replace(path)


def as_bool(v):
    return str(v).strip().lower() in {'true','1','yes','y','t'}


def ffloat(v):
    try:
        x = float(str(v).strip())
    except Exception:
        return None
    return x if math.isfinite(x) else None


def fint(v):
    try:
        return int(str(v).strip())
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return None


def percentile_midrank(value, values):
    vals = np.asarray([float(x) for x in values if x is not None and math.isfinite(float(x))], dtype=float)
    if value is None or not math.isfinite(float(value)) or len(vals) == 0:
        return None
    v = float(value)
    lt = int(np.sum(vals < v)); eq = int(np.sum(vals == v))
    return 100.0 * (lt + 0.5*eq) / len(vals)


def morphology(arr, lx, ly, polarity):
    ix, iy = int(round(float(lx))), int(round(float(ly)))
    r = CUT_RADIUS
    y0, y1 = iy-r, iy+r+1; x0, x1 = ix-r, ix+r+1
    if y0 < 0 or x0 < 0 or y1 > arr.shape[0] or x1 > arr.shape[1]:
        raise RuntimeError('candidate lacks full 41x41 native morphology cutout')
    cut = np.asarray(arr[y0:y1, x0:x1], dtype=float)
    yy, xx = np.indices(cut.shape); cx = cy = r
    rr = np.hypot(xx-cx, yy-cy)
    ann = cut[(rr >= 12) & (rr <= 20) & np.isfinite(cut)]
    if ann.size < 100:
        raise RuntimeError('insufficient finite morphology annulus')
    bg = float(np.median(ann)); mad = float(np.median(np.abs(ann-bg))); sigma = 1.4826*mad
    if not math.isfinite(sigma) or sigma <= 0:
        raise RuntimeError(f'invalid local morphology sigma: {sigma}')
    oriented = int(polarity) * (cut-bg); oriented[~np.isfinite(oriented)] = 0.0
    positive = np.clip(oriented, 0.0, None); peak = float(oriented[cy,cx])
    flux = lambda rad: float(positive[rr <= rad].sum())
    f3, f5, f8 = flux(3), flux(5), flux(8)
    weights = positive * (rr <= 6); wsum = float(weights.sum())
    if wsum > 0:
        dx = float((weights*(xx-cx)).sum()/wsum); dy = float((weights*(yy-cy)).sum()/wsum)
        ux, uy = (xx-cx)-dx, (yy-cy)-dy
        mxx = float((weights*ux*ux).sum()/wsum); myy = float((weights*uy*uy).sum()/wsum)
        mxy = float((weights*ux*uy).sum()/wsum)
        vals = np.clip(np.linalg.eigvalsh(np.array([[mxx,mxy],[mxy,myy]], dtype=float)), 0, None)
        smin, smaj = float(math.sqrt(vals[0])), float(math.sqrt(vals[1]))
        ell = 1.0 - smin/smaj if smaj > 0 else 1.0
        cent = float(math.hypot(dx,dy))
    else:
        smin = smaj = ell = cent = float('nan')
    core3 = cut[cy-1:cy+2, cx-1:cx+2]; center_raw = cut[cy,cx]
    plateau = int(np.count_nonzero(core3 == center_raw))
    extreme = np.nanmax(cut) if polarity >= 0 else np.nanmin(cut)
    local_extreme = int(np.count_nonzero(core3 == extreme))
    return {
        'local_bg':bg,'local_sigma':sigma,'peak_bgsub_polarity':peak,
        'centroid_offset_px':cent,'sigma_major_px':smaj,'sigma_minor_px':smin,'ellipticity':ell,
        'peak_to_flux5':peak/f5 if f5>0 else float('nan'),
        'concentration_flux3_flux8':f3/f8 if f8>0 else float('nan'),
        'plateau_count_3x3':plateau,'local_extreme_count_3x3':local_extreme,
    }


def load_tile_inventory(tile_dir, archive):
    if not tile_dir.is_dir():
        raise RuntimeError(f'missing {archive} tile directory: {tile_dir}')
    by_tile = {}
    for jp in sorted(tile_dir.glob('*.json')):
        try: obj = json.loads(jp.read_text(encoding='utf-8'))
        except Exception: continue
        if obj.get('complete') is not True: continue
        tid = str(obj.get('tile_id','')).strip(); core = obj.get('core'); ext = obj.get('extended'); ref = obj.get('npy_path')
        if not tid or not isinstance(core,list) or len(core)!=4 or not isinstance(ext,list) or len(ext)!=4 or not ref:
            continue
        npy = Path(str(ref)); npy = npy if npy.is_absolute() else ROOT/npy
        if not npy.is_file(): raise RuntimeError(f'{archive} {tid}: missing NPY {npy}')
        actual = sha_file(npy); recorded = str(obj.get('npy_file_sha256') or '').strip().lower()
        if recorded and recorded != actual: raise RuntimeError(f'{archive} {tid}: NPY SHA mismatch')
        if tid in by_tile: raise RuntimeError(f'{archive}: duplicate completed metadata for {tid}')
        by_tile[tid] = {
            'archive':archive,'tile_id':tid,'core':tuple(map(int,core)),'extended':tuple(map(int,ext)),
            'shape':tuple(map(int,obj.get('shape',[]))),'npy_path':npy,'npy_sha256':actual,'meta_path':jp,
        }
    if not by_tile: raise RuntimeError(f'{archive}: no completed tile metadata found')
    return by_tile


ARRAY_CACHE = {}
def load_tile(meta):
    key = (meta['archive'], meta['tile_id'])
    if key in ARRAY_CACHE: return ARRAY_CACHE[key]
    arr = np.load(meta['npy_path'], mmap_mode='r')
    ex0,ex1,ey0,ey1 = meta['extended']; expected = (ey1-ey0, ex1-ex0)
    if arr.ndim != 2 or tuple(arr.shape) != expected:
        raise RuntimeError(f'{key}: NPY shape {arr.shape} != expected {expected}')
    if meta['shape'] and tuple(arr.shape) != meta['shape']:
        raise RuntimeError(f'{key}: NPY shape {arr.shape} != metadata shape {meta["shape"]}')
    ARRAY_CACHE[key] = arr
    return arr


def candidate_spec(sr, archive):
    p = archive.lower()
    return {'tile_id':str(sr[f'{p}_tile_id']), 'candidate_index':int(float(sr[f'{p}_candidate_index'])),
            'snr':float(sr[f'{p}_snr']), 'polarity':int(float(sr[f'{p}_polarity']))}


def exact_candidate(by_tile, spec):
    hits = [r for r in by_tile.get(spec['tile_id'],[]) if fint(r.get('candidate_index')) == spec['candidate_index']]
    if len(hits) != 1:
        raise RuntimeError(f'{spec["tile_id"]} candidate {spec["candidate_index"]}: exact aggregate match count={len(hits)}')
    r = hits[0]; snr = ffloat(r.get('snr')); pol = fint(r.get('polarity')); gx = ffloat(r.get('global_x')); gy = ffloat(r.get('global_y'))
    if snr is None or abs(snr-spec['snr']) > 1e-9 or pol != spec['polarity'] or gx is None or gy is None:
        raise RuntimeError(f'{spec["tile_id"]} candidate {spec["candidate_index"]}: aggregate guard failure')
    return r


def peer_candidates(rows, spec, gx0, gy0):
    cand=[]
    for r in rows:
        pol=fint(r.get('polarity')); snr=ffloat(r.get('snr')); gx=ffloat(r.get('global_x')); gy=ffloat(r.get('global_y')); idx=fint(r.get('candidate_index'))
        if pol != spec['polarity'] or snr is None or snr <= 0 or gx is None or gy is None or idx is None: continue
        dist=math.hypot(gx-gx0,gy-gy0)
        if dist < EXCLUSION_RADIUS_PX: continue
        ratio=snr/spec['snr']; cand.append({'candidate_index':idx,'global_x':gx,'global_y':gy,'distance':dist,'snr':snr,'ratio':ratio})
    pref=[q for q in cand if PREFERRED_SNR_RATIO[0] <= q['ratio'] <= PREFERRED_SNR_RATIO[1]]
    fall=[q for q in cand if FALLBACK_SNR_RATIO[0] <= q['ratio'] <= FALLBACK_SNR_RATIO[1]]
    if len(pref) >= MIN_PREFERRED_CONTROLS:
        pool=pref; mode='same_tile_same_polarity_snr_ratio_0.75_1.25'; pool.sort(key=lambda q:(q['distance'],abs(math.log(q['ratio'])),q['snr'],q['candidate_index']))
    elif len(fall) >= MIN_PREFERRED_CONTROLS:
        pool=fall; mode='same_tile_same_polarity_snr_ratio_0.50_1.50_fallback'; pool.sort(key=lambda q:(q['distance'],abs(math.log(q['ratio'])),q['snr'],q['candidate_index']))
    else:
        pool=cand; mode='same_tile_same_polarity_nearest_snr_fallback'; pool.sort(key=lambda q:(abs(math.log(q['ratio'])),q['distance'],q['snr'],q['candidate_index']))
    return pool[:MAX_CONTROLS], mode


def evaluate_endpoint(rank, archive, sr, by_tile, inv):
    spec=candidate_spec(sr,archive); tid=spec['tile_id']
    if tid not in inv: raise RuntimeError(f'rank {rank} {archive}: no completed metadata for {tid}')
    meta=inv[tid]; arr=load_tile(meta); science=exact_candidate(by_tile,spec)
    gx=float(science['global_x']); gy=float(science['global_y']); ex0,ex1,ey0,ey1=meta['extended']
    sci=morphology(arr,gx-ex0,gy-ey0,spec['polarity'])
    peers,mode=peer_candidates(by_tile[tid],spec,gx,gy); controls=[]; mets=[]
    for q in peers:
        try: met=morphology(arr,q['global_x']-ex0,q['global_y']-ey0,spec['polarity'])
        except Exception: continue
        mets.append(met); controls.append({'strict_rank':rank,'archive':archive,'control_order':len(controls)+1,'selection_mode':mode,
            'tile_id':tid,'candidate_index':q['candidate_index'],'global_x':q['global_x'],'global_y':q['global_y'],
            'distance_from_science_px':q['distance'],'snr':q['snr'],'snr_ratio':q['ratio'],'polarity':spec['polarity'],**met})
    if len(mets) < 5:
        return {'strict_rank':rank,'archive':archive,'endpoint_status':'INSUFFICIENT_USABLE_MATCHED_CONTROLS','tile_id':tid,
            'candidate_index':spec['candidate_index'],'global_x':gx,'global_y':gy,'snr':spec['snr'],'polarity':spec['polarity'],
            'control_selection_mode':mode,'control_count':len(mets),'tile_npy_path':str(meta['npy_path']),'tile_npy_sha256':meta['npy_sha256'],
            'error':f'only {len(mets)} usable matched controls; endpoint retained unresolved'}, controls
    pct={k:percentile_midrank(sci[k],[m[k] for m in mets]) for k in CONTINUOUS_METRICS+COUNT_METRICS}
    ext=sum(pct[k] is not None and (pct[k] <= 5 or pct[k] >= 95) for k in CONTINUOUS_METRICS)
    chi=sum(pct[k] is not None and pct[k] >= 95 for k in COUNT_METRICS)
    ep={'strict_rank':rank,'archive':archive,'endpoint_status':'MATCHED_PEER_MORPHOLOGY_COMPLETE','tile_id':tid,'candidate_index':spec['candidate_index'],
        'global_x':gx,'global_y':gy,'snr':spec['snr'],'polarity':spec['polarity'],'control_selection_mode':mode,'control_count':len(mets),**sci,
        'sigma_major_peer_percentile':pct['sigma_major_px'],'sigma_minor_peer_percentile':pct['sigma_minor_px'],
        'ellipticity_peer_percentile':pct['ellipticity'],'peak_to_flux5_peer_percentile':pct['peak_to_flux5'],
        'concentration_peer_percentile':pct['concentration_flux3_flux8'],'centroid_offset_peer_percentile':pct['centroid_offset_px'],
        'plateau_peer_percentile':pct['plateau_count_3x3'],'local_extreme_peer_percentile':pct['local_extreme_count_3x3'],
        'matched_peer_extreme_continuous_metric_count':ext,'matched_peer_count_metric_ge95_count':chi,
        'tile_npy_path':str(meta['npy_path']),'tile_npy_sha256':meta['npy_sha256'],'error':None}
    return ep,controls


def endpoint_safe(rank, archive, sr, by_tile, inv):
    try: return evaluate_endpoint(rank,archive,sr,by_tile,inv)
    except Exception as exc:
        spec=candidate_spec(sr,archive)
        return {'strict_rank':rank,'archive':archive,'endpoint_status':'MORPHOLOGY_UNRESOLVED_ERROR','tile_id':spec['tile_id'],
            'candidate_index':spec['candidate_index'],'snr':spec['snr'],'polarity':spec['polarity'],'control_count':0,'error':repr(exc)}, []


def main():
    print('='*108)
    print('ORDER 01 — NATIVE PIXEL + SNR-MATCHED PEER MORPHOLOGY v028')
    print('='*108)
    print('Gaia+PS1-clean 5" survivors only. No detector rerun. Same-tile/same-polarity controls selected only by SNR and position.')
    print('No candidate gate is changed. No candidate is deleted or promoted.\n')
    for p in [PAIR_REPORT,PS1_REPORT,PS1_TRIAGE,STRICT,POSS_CAND,DASCH_CAND]:
        if not p.is_file(): raise RuntimeError(f'missing required file: {p}')
    detector=ROOT/'src/transient_pipeline/detector.py'; method=ROOT/'config/frozen_method.json'; policy=ROOT/'research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json'
    for p in [detector,method,policy]:
        if not p.is_file(): raise RuntimeError(f'missing frozen input: {p}')
    pair=json.loads(PAIR_REPORT.read_text(encoding='utf-8')); ps1=json.loads(PS1_REPORT.read_text(encoding='utf-8'))
    strict_rows=read_csv(STRICT); ps1_rows=read_csv(PS1_TRIAGE); poss_rows=read_csv(POSS_CAND); dasch_rows=read_csv(DASCH_CAND)
    survivor_report=[int(x) for x in ps1.get('survivor_ranks_5arcsec',[])]
    survivor_csv=sorted(int(r['strict_rank']) for r in ps1_rows if as_bool(r['survives_gaia_and_ps1_5arcsec']))
    guards={'pair_complete':pair.get('status')=='COMPLETE','order':int(pair.get('canonical_order',-1))==1,
        'detector_report':pair.get('detector_sha256')==EXPECTED_DETECTOR_SHA,'detector_file':sha_file(detector)==EXPECTED_DETECTOR_SHA,
        'method_report':pair.get('method_sha256')==EXPECTED_METHOD_SHA,'method_file':sha_file(method)==EXPECTED_METHOD_SHA,
        'policy_file':sha_file(policy)==EXPECTED_POLICY_SHA,'raw10':int(pair.get('raw_le_10arcsec',-1))==EXPECTED_RAW10,
        'strict3':int(pair.get('raw_le_3arcsec',-1))==EXPECTED_STRICT3,'poss_candidate_count':len(poss_rows)==EXPECTED_POSS_CAND,
        'dasch_candidate_count':len(dasch_rows)==EXPECTED_DASCH_CAND,'ps1_complete':ps1.get('status')=='COMPLETE',
        'ps1_survivor_report':survivor_report==EXPECTED_RANKS,'ps1_survivor_csv':survivor_csv==EXPECTED_RANKS,
        'ps1_no_detector':ps1.get('detector_rerun') is False,'ps1_no_pixels':ps1.get('image_pixels_read') is False}
    if not all(guards.values()): raise RuntimeError('REFUSING: completed-stage guard failure: '+json.dumps(guards,sort_keys=True))
    strict_by_rank={int(r['strict_rank']):r for r in strict_rows}
    if any(r not in strict_by_rank for r in EXPECTED_RANKS): raise RuntimeError('PS1 survivor missing from strict table')
    poss_by=defaultdict(list); dasch_by=defaultdict(list)
    for r in poss_rows: poss_by[str(r['tile_id'])].append(r)
    for r in dasch_rows: dasch_by[str(r['tile_id'])].append(r)
    poss_inv=load_tile_inventory(WORK/'poss_tiles','POSS'); dasch_inv=load_tile_inventory(WORK/'dasch_tiles','DASCH')
    print('Completed-stage guards: PASS')
    print('Matched-peer policy: same tile/polarity; exclude <32 px; prefer SNR 0.75–1.25; fallback 0.50–1.50 if <12; max 32 controls.')
    print('Extreme definitions: continuous <=5th or >=95th percentile; count metric >=95th percentile.')
    print(f'Completed tile metadata: POSS={len(poss_inv)} DASCH={len(dasch_inv)}\n')
    endpoints=[]; controls=[]; summaries=[]; per_rank={}
    for rank in EXPECTED_RANKS:
        sr=strict_by_rank[rank]
        pe,pc=endpoint_safe(rank,'POSS',sr,poss_by,poss_inv); de,dc=endpoint_safe(rank,'DASCH',sr,dasch_by,dasch_inv)
        endpoints += [pe,de]; controls += pc+dc
        complete=pe['endpoint_status']=='MATCHED_PEER_MORPHOLOGY_COMPLETE' and de['endpoint_status']=='MATCHED_PEER_MORPHOLOGY_COMPLETE'
        if complete:
            pext=int(pe['matched_peer_extreme_continuous_metric_count']); dext=int(de['matched_peer_extreme_continuous_metric_count'])
            pchi=int(pe['matched_peer_count_metric_ge95_count']); dchi=int(de['matched_peer_count_metric_ge95_count'])
            if pext==dext==pchi==dchi==0: status='NO_MATCHED_PEER_MORPHOLOGY_EXTREME_EITHER_ENDPOINT'
            elif (pext>0 or pchi>0) and (dext>0 or dchi>0): status='MATCHED_PEER_EXTREMES_ON_BOTH_ENDPOINTS'
            else: status='MATCHED_PEER_EXTREME_ON_ONE_ENDPOINT'
        else: status='MORPHOLOGY_UNRESOLVED_AT_ONE_OR_MORE_ENDPOINTS'
        s={'strict_rank':rank,'pair_separation_arcsec':float(sr['separation_arcsec']),'poss_snr':float(sr['poss_snr']),'dasch_snr':float(sr['dasch_snr']),
            'poss_polarity':int(float(sr['poss_polarity'])),'dasch_polarity':int(float(sr['dasch_polarity'])),
            'same_polarity':int(float(sr['poss_polarity']))==int(float(sr['dasch_polarity'])),
            'poss_endpoint_status':pe['endpoint_status'],'dasch_endpoint_status':de['endpoint_status'],
            'poss_control_count':int(pe.get('control_count') or 0),'dasch_control_count':int(de.get('control_count') or 0),
            'poss_matched_peer_extreme_continuous_metric_count':pe.get('matched_peer_extreme_continuous_metric_count'),
            'dasch_matched_peer_extreme_continuous_metric_count':de.get('matched_peer_extreme_continuous_metric_count'),
            'poss_matched_peer_count_metric_ge95_count':pe.get('matched_peer_count_metric_ge95_count'),
            'dasch_matched_peer_count_metric_ge95_count':de.get('matched_peer_count_metric_ge95_count'),'pair_morphology_status':status}
        summaries.append(s); per_rank[str(rank)]={'summary':s,'POSS':pe,'DASCH':de}
        def fp(ep,k):
            v=ep.get(k); return 'NA' if v is None else f'{float(v):.1f}'
        print(f'strict #{rank:02d}: {status}')
        print(f"  POSS  {pe['endpoint_status']} controls={int(pe.get('control_count') or 0):2d} ext={pe.get('matched_peer_extreme_continuous_metric_count')} count-hi={pe.get('matched_peer_count_metric_ge95_count')} ell={fp(pe,'ellipticity_peer_percentile')} sharp={fp(pe,'peak_to_flux5_peer_percentile')} conc={fp(pe,'concentration_peer_percentile')} cent={fp(pe,'centroid_offset_peer_percentile')}")
        print(f"  DASCH {de['endpoint_status']} controls={int(de.get('control_count') or 0):2d} ext={de.get('matched_peer_extreme_continuous_metric_count')} count-hi={de.get('matched_peer_count_metric_ge95_count')} ell={fp(de,'ellipticity_peer_percentile')} sharp={fp(de,'peak_to_flux5_peer_percentile')} conc={fp(de,'concentration_peer_percentile')} cent={fp(de,'centroid_offset_peer_percentile')}")
    write_csv(OUT_ENDPOINT,endpoints,ENDPOINT_FIELDS); write_csv(OUT_CONTROL,controls,CONTROL_FIELDS); write_csv(OUT_SUMMARY,summaries,SUMMARY_FIELDS)
    counts={}
    for r in summaries: counts[r['pair_morphology_status']]=counts.get(r['pair_morphology_status'],0)+1
    report={'status':'COMPLETE','analysis_kind':'order01_native_snr_matched_peer_morphology_v028','guards':guards,'input_survivor_ranks':EXPECTED_RANKS,
        'fixed_peer_policy':{'policy_origin':'completed_order61_discovery_plate_peer_audit_v028c','same_tile':True,'same_polarity':True,
            'exclude_within_science_candidate_px':EXCLUSION_RADIUS_PX,'preferred_snr_ratio':list(PREFERRED_SNR_RATIO),'minimum_preferred_controls':MIN_PREFERRED_CONTROLS,
            'fallback_snr_ratio':list(FALLBACK_SNR_RATIO),'maximum_controls':MAX_CONTROLS,'minimum_usable_controls_for_endpoint_result':5,
            'matched_peer_extreme_definition':'continuous empirical midrank percentile <=5 or >=95','count_metric_high_definition':'empirical midrank percentile >=95'},
        'morphology_function':{'origin':'unchanged quantitative function from vet_order61_survivor_morphology_v028.py','native_pixels':True,'resampling':False,
            'cutout_px':[41,41],'background_annulus_px':[12,20],'robust_sigma':'1.4826*MAD','continuous_metrics':CONTINUOUS_METRICS,'count_metrics':COUNT_METRICS},
        'implementation_generalisation':{'hardcoded_full_plate_dimensions_used':False,'tile_core_and_extended_bounds_source':'completed per-tile execution metadata',
            'candidate_identity':'exact tile_id + candidate_index from completed aggregate candidate CSV','endpoint_errors_are_conservative_unresolved_not_negative':True},
        'pair_status_counts':counts,'per_rank':per_rank,'detector_rerun':False,'science_candidate_pixels_read':True,'matched_control_pixels_read':True,
        'candidate_deleted':False,'candidate_promoted':False,
        'next_stage':'For candidates without convincing defect-like morphology, run frozen recovery/injection sensitivity and historical independent-plate recurrence before any Branch-C escalation.',
        'outputs':{'endpoint_metrics_csv':str(OUT_ENDPOINT),'matched_controls_csv':str(OUT_CONTROL),'candidate_summary_csv':str(OUT_SUMMARY)}}
    write_json(OUT_REPORT,report)
    print('\n'+'='*108); print('ORDER 01 MATCHED-PEER MORPHOLOGY COMPLETE'); print('='*108)
    print('Pair status counts:',json.dumps(counts,sort_keys=True)); print('Report:',OUT_REPORT); print('Summary:',OUT_SUMMARY); print('Endpoints:',OUT_ENDPOINT); print('Controls:',OUT_CONTROL)
    print('\nNo detector was rerun.\nNo candidate gate was changed.\nNo candidate was deleted or promoted.')


if __name__ == '__main__':
    main()
