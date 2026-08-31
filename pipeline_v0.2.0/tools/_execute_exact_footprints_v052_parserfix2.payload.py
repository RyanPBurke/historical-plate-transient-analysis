from __future__ import annotations

from pathlib import Path
import base64, csv, gzip, hashlib, io, json, math, re, urllib.parse, urllib.request
import numpy as np
from astropy.io import fits
from astropy.io.votable import parse_single_table
from astropy.wcs import WCS

ROOT = Path.cwd()
PLAN = ROOT / 'results' / 'wide_census_footprint_plan_v051.json'
QUEUE = ROOT / 'results' / 'wide_census_exact_footprint_queue_v051.csv'
TIMING = ROOT / 'results' / 'wide_census_physical_timing_final_v050.json'
APPLAUSE_META = ROOT / 'research' / 'census_inputs' / 'applause_exposures_1951_1955.csv'
POLICY = ROOT / 'config' / 'candidate_adjudication_policy_v002.json'
OUT_DIR = ROOT / 'results' / 'wide_census_exact_footprint_v052'
CACHE = OUT_DIR / 'cache'
CHECKPOINT = OUT_DIR / 'checkpoint_v052.json'
OUT_JSON = ROOT / 'results' / 'wide_census_exact_footprint_v052.json'
OUT_CSV = ROOT / 'results' / 'wide_census_exact_footprint_v052.csv'
SURVIVOR_CSV = ROOT / 'results' / 'wide_census_true_overlap_survivors_v052.csv'
HOLD_CSV = ROOT / 'results' / 'wide_census_footprint_holds_v052.csv'
TAP_URL = 'https://www.plate-archive.org/tap/sync'
DASCH_API = 'https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package'
UA = 'historical-transient-pipeline/exact-footprint-v052-parserfix1'
EXPECTED_QUEUE_ROWS = 82
EXPECTED_APPLAUSE_PLATES = 49
EXPECTED_DASCH_PLATES = 24
EXPECTED_POLICY_ID = 'candidate_adjudication_policy_v002'
REMOTE_BATCH_DASCH = 8
MAX_TRANSPORT_ATTEMPTS = 4


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline='', encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    tmp.replace(path)


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def post_json(url, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'User-Agent': UA, 'Accept': 'application/json', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode('utf-8')), getattr(response, 'status', None), response.geturl()


def _scalar_text(value):
    if value is None:
        return ''
    try:
        if np.ma.is_masked(value):
            return ''
    except Exception:
        pass
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='strict')
    try:
        value = value.item()
    except Exception:
        pass
    return str(value)


def _rows_to_csv_bytes(rows):
    if not rows:
        raise RuntimeError('Cannot normalize empty APPLAUSE result')
    preferred = [
        'plate_id', 'archive_id', 'solution_id', 'process_id', 'scan_id',
        'solution_num', 'ra_icrs', 'dec_icrs', 'fov1', 'fov2', 'stc_polygon',
    ]
    fields = [x for x in preferred if any(x in r for r in rows)]
    extras = sorted({k for r in rows for k in r} - set(fields))
    fields.extend(extras)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=fields,
        extrasaction='ignore',
        lineterminator='\n',
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode('utf-8')


def applause_tap_query(plate_ids):
    ids = ','.join(str(int(x)) for x in sorted(set(plate_ids)))
    query = f'''SELECT plate_id, archive_id, solution_id, process_id, scan_id, solution_num,
       ra_icrs, dec_icrs, fov1, fov2, stc_polygon
FROM applause_dr4.solution
WHERE plate_id IN ({ids})
ORDER BY plate_id, scan_id, solution_num, solution_id'''

    data = urllib.parse.urlencode({
        'REQUEST': 'doQuery',
        'LANG': 'ADQL',
        'FORMAT': 'csv',
        'QUERY': query,
    }).encode('utf-8')
    req = urllib.request.Request(
        TAP_URL,
        data=data,
        method='POST',
        headers={
            'User-Agent': UA,
            'Accept': 'text/csv,application/x-votable+xml,text/xml,*/*',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read()
        status = getattr(response, 'status', None)
        final_url = response.geturl()
        content_type = str(response.headers.get('Content-Type', '') or '')

    probe = raw[:1000].lstrip().lower()
    if b'<votable' in probe or 'votable' in content_type.lower():
        response_format = 'votable'
        try:
            table = parse_single_table(
                io.BytesIO(raw)
            ).to_table(use_names_over_ids=True)
        except Exception as exc:
            raise RuntimeError(
                f'APPLAUSE TAP VOTable parse failed: {type(exc).__name__}: {exc}'
            ) from exc

        rows = []
        for record in table:
            row = {}
            for name in table.colnames:
                row[str(name).lower()] = _scalar_text(record[name])
            rows.append(row)

    else:
        try:
            text = raw.decode('utf-8-sig', errors='strict')
        except Exception as exc:
            raise RuntimeError(
                f'APPLAUSE TAP response is neither parseable VOTable nor UTF-8 CSV: {exc}'
            ) from exc

        if '<html' in text[:500].lower():
            raise RuntimeError(
                'APPLAUSE TAP returned HTML instead of a table; first 300 chars: '
                + repr(text[:300])
            )

        response_format = 'csv'
        rows = [
            {str(k).lower(): v for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))
        ]

    if not rows:
        raise RuntimeError(
            f'APPLAUSE TAP returned zero solution rows in {response_format} representation'
        )

    normalized_csv = _rows_to_csv_bytes(rows)
    return (
        rows,
        raw,
        normalized_csv,
        response_format,
        content_type,
        status,
        final_url,
        query,
    )


def fnum(v):
    try:
        x = float(str(v).strip()); return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    try: return int(float(str(v).strip()))
    except Exception: return None


def angular_sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = math.sin((d2-d1)/2)**2 + math.cos(d1)*math.cos(d2)*math.sin((r2-r1)/2)**2
    return math.degrees(2 * math.asin(math.sqrt(min(1.0, max(0.0, a)))))


def parse_stc_polygon(value):
    if value is None: return None
    nums = [float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?', str(value).strip())]
    if len(nums) != 8: return None
    poly = [(nums[i] % 360.0, nums[i+1]) for i in range(0, 8, 2)]
    return poly if all(-90 <= d <= 90 for _, d in poly) else None


def unitvec(ra_deg, dec_deg):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return np.array([math.cos(dec)*math.cos(ra), math.cos(dec)*math.sin(ra), math.sin(dec)], float)


def tangent_basis(polys):
    vectors = [unitvec(ra, dec) for p in polys for ra, dec in p]
    center = np.sum(vectors, axis=0); n = float(np.linalg.norm(center))
    if not math.isfinite(n) or n <= 1e-12: raise RuntimeError('Degenerate footprint center')
    center /= n
    east = np.cross(np.array([0.,0.,1.]), center)
    if np.linalg.norm(east) < 1e-8: east = np.cross(np.array([1.,0.,0.]), center)
    east /= np.linalg.norm(east); north = np.cross(center, east); north /= np.linalg.norm(north)
    return center, east, north


def project_poly(poly, center, east, north):
    out = []
    for ra, dec in poly:
        v = unitvec(ra, dec); den = float(np.dot(v, center))
        if den <= 0: raise RuntimeError('Footprint exceeds gnomonic hemisphere')
        out.append((float(np.dot(v,east))/den, float(np.dot(v,north))/den))
    return out


def area2(poly):
    return sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))


def ensure_ccw(poly): return list(reversed(poly)) if area2(poly) < 0 else list(poly)


def inside(p,a,b): return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]) >= -1e-14


def line_intersection(p1,p2,q1,q2):
    x1,y1=p1; x2,y2=p2; x3,y3=q1; x4,y4=q2
    den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
    if abs(den)<1e-15: return p2
    return (((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/den,
            ((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/den)


def convex_clip(subject, clipper):
    output=list(subject)
    for i in range(len(clipper)):
        a,b=clipper[i],clipper[(i+1)%len(clipper)]; inp=output; output=[]
        if not inp: break
        s=inp[-1]
        for e in inp:
            if inside(e,a,b):
                if not inside(s,a,b): output.append(line_intersection(s,e,a,b))
                output.append(e)
            elif inside(s,a,b): output.append(line_intersection(s,e,a,b))
            s=e
    return output


def polygon_overlap(pa,pb):
    c,e,n=tangent_basis([pa,pb]); a=ensure_ccw(project_poly(pa,c,e,n)); b=ensure_ccw(project_poly(pb,c,e,n))
    clipped=convex_clip(a,b)
    if len(clipped)<3: return False,0.0
    ar=abs(area2(clipped))/2.0
    return ar>1e-12, ar*(180/math.pi)**2


def applause_cache_path(): return CACHE/'applause_solution_rows.csv'
def applause_meta_path(): return CACHE/'applause_solution_query_meta.json'
def dasch_cache_path(plate): return CACHE/'dasch'/f'{plate}.json'


def checkpoint_default(): return {'status':'IN_PROGRESS','attempts':{},'transport_terminal':{},'last_error':None}


def mark_transport(cp,key,exc):
    n=int(cp['attempts'].get(key,0))+1; cp['attempts'][key]=n
    cp['last_error']={'key':key,'attempt':n,'type':type(exc).__name__,'message':str(exc)}
    if n>=MAX_TRANSPORT_ATTEMPTS: cp['transport_terminal'][key]=cp['last_error']
    write_json(CHECKPOINT,cp); return n


def load_applause_exposure_meta():
    return {int(float(x['exposure_id'])):x for x in read_csv(APPLAUSE_META)}


def applause_candidates(exposure, plate_id, solution_rows, apmeta):
    eid=int(str(exposure).split(':')[1]); meta=apmeta.get(eid)
    if meta is None: return {'status':'UNRESOLVED_APPLAUSE_EXPOSURE_METADATA','candidates':[]}
    era,edec=fnum(meta.get('ra_icrs')),fnum(meta.get('dec_icrs'))
    if era is None or edec is None: return {'status':'UNRESOLVED_APPLAUSE_EXPOSURE_CENTER','candidates':[]}
    usable=[]
    for row in solution_rows:
        if inum(row.get('plate_id')) != int(plate_id): continue
        poly=parse_stc_polygon(row.get('stc_polygon')); ra=fnum(row.get('ra_icrs')); dec=fnum(row.get('dec_icrs'))
        if poly is None or ra is None or dec is None: continue
        usable.append((angular_sep_deg(era,edec,ra,dec),row,poly))
    if not usable: return {'status':'UNRESOLVED_APPLAUSE_NO_EXACT_POLYGON','candidates':[]}
    by_scan={}
    for sep,row,poly in usable: by_scan.setdefault(inum(row.get('scan_id')),[]).append((sep,row,poly))
    selected=[]
    for scan,group in sorted(by_scan.items(),key=lambda kv:str(kv[0])):
        group.sort(key=lambda x:(x[0],inum(x[1].get('solution_num')) or 0,inum(x[1].get('solution_id')) or 0)); best=group[0][0]
        for sep,row,poly in group:
            if sep<=best+0.02:
                selected.append({'polygon':poly,'solution_id':inum(row.get('solution_id')),'solution_num':inum(row.get('solution_num')),
                                 'scan_id':inum(row.get('scan_id')),'process_id':inum(row.get('process_id')),
                                 'center_sep_from_exposure_deg':sep})
    best=min(x['center_sep_from_exposure_deg'] for x in selected)
    if best>5.0: return {'status':'UNRESOLVED_APPLAUSE_SOLUTION_EXPOSURE_ASSOCIATION','best_center_sep_deg':best,'candidates':[]}
    return {'status':'RESOLVED','method':'APPLAUSE_DR4_STC_POLYGON_PER_SCAN_NEAREST_EXPOSURE_CENTER',
            'exposure_id':eid,'plate_id':int(plate_id),'candidate_count':len(selected),'scan_count':len({x['scan_id'] for x in selected}),'candidates':selected}


def wcs_solution_keys(header):
    keys=set()
    if 'CTYPE1' in header and 'CTYPE2' in header: keys.add(' ')
    for name in header:
        m=re.fullmatch(r'CTYPE1([A-Z])',str(name))
        if m and f'CTYPE2{m.group(1)}' in header: keys.add(m.group(1))
    return sorted(keys,key=lambda x:(x!=' ',x))


def wcs_polygon_and_center(header,key,width,height):
    w=WCS(header,key=key).celestial
    px=np.array([[-.5,-.5],[width-.5,-.5],[width-.5,height-.5],[-.5,height-.5]],float)
    world=w.all_pix2world(px,0); poly=[(float(ra)%360,float(dec)) for ra,dec in world]
    cen=w.all_pix2world(np.array([[(width-1)/2,(height-1)/2]],float),0)[0]
    return poly,(float(cen[0])%360,float(cen[1]))


def dasch_candidates(plate,selected_expnum,package):
    meta=package.get('metadata') or {}; astrom=meta.get('astrometry') or {}; mosaic=meta.get('mosaic') or {}; hgz=astrom.get('b01HeaderGz')
    if not hgz: return {'status':'UNRESOLVED_DASCH_NO_ASTROMETRY_HEADER','candidates':[]}
    try: width,height=int(mosaic['b01Width']),int(mosaic['b01Height'])
    except Exception: return {'status':'UNRESOLVED_DASCH_MOSAIC_SHAPE','candidates':[]}
    em=[x for x in (astrom.get('exposures') or []) if inum(x.get('number'))==inum(selected_expnum)]
    if len(em)!=1: return {'status':'UNRESOLVED_DASCH_SELECTED_EXPOSURE','selected_expnum':selected_expnum,'matching_metadata_exposures':len(em),'candidates':[]}
    era,edec=fnum(em[0].get('raDeg')),fnum(em[0].get('decDeg'))
    if era is None or edec is None: return {'status':'UNRESOLVED_DASCH_EXPOSURE_CENTER','candidates':[]}
    header=fits.Header.fromstring(gzip.decompress(base64.b64decode(hgz)),sep='\n')
    finite=[]
    for key in wcs_solution_keys(header):
        try:
            poly,center=wcs_polygon_and_center(header,key,width,height); sep=angular_sep_deg(era,edec,center[0],center[1]); finite.append((sep,key,poly,center))
        except Exception: pass
    if not finite: return {'status':'UNRESOLVED_DASCH_NO_USABLE_WCS','candidates':[]}
    finite.sort(key=lambda x:(x[0],x[1])); best=finite[0][0]
    if best>5.0: return {'status':'UNRESOLVED_DASCH_WCS_EXPOSURE_ASSOCIATION','best_center_sep_deg':best,'selected_expnum':selected_expnum,'candidates':[]}
    cand=[]
    for sep,key,poly,center in finite:
        if sep<=best+0.05: cand.append({'polygon':poly,'wcs_key':'PRIMARY' if key==' ' else key,'center_sep_from_exposure_deg':sep})
    return {'status':'RESOLVED','method':'DASCH_DR7_TPV_WCS_MATCHED_TO_SELECTED_LOGBOOK_EXPOSURE_CENTER',
            'plate_id':plate,'selected_expnum':inum(selected_expnum),'candidate_count':len(cand),'candidates':cand}


def side_geometry(row,side,timing_pair,ap_rows,apmeta,dasch_packages):
    kind=row[f'kind_{side}']; exposure=row[f'exposure_{side}']
    if kind=='APPLAUSE':
        return applause_candidates(exposure,int(float(row[f'applause_plate_id_{side}'])),ap_rows,apmeta)
    if kind=='DASCH':
        plate=row[f'dasch_plate_id_{side}'].strip().lower(); expnum=(timing_pair.get(f'side_{side}') or {}).get('number')
        if expnum is None: return {'status':'UNRESOLVED_DASCH_TIMING_EXPNUM_MISSING','plate_id':plate,'candidates':[]}
        return dasch_candidates(plate,expnum,dasch_packages.get(plate,{}))
    return {'status':'UNRESOLVED_UNSUPPORTED_ARCHIVE_KIND','kind':kind,'candidates':[]}


def evaluate_pair(row,ga,gb):
    r={'exact_footprint_priority':int(row['exact_footprint_priority']),'canonical_pair':row['canonical_pair'],
       'timing_validation_priority':int(row['timing_validation_priority']),'time_gate':row['time_gate'],
       'physical_overlap_s':fnum(row.get('physical_overlap_s')),'exposure_a':row['exposure_a'],'archive_a':row['archive_a'],'site_a':row['site_a'],
       'exposure_b':row['exposure_b'],'archive_b':row['archive_b'],'site_b':row['site_b'],'geometry_a':ga,'geometry_b':gb,
       'science_eligible':False,'detector_execution_eligible':False}
    if ga.get('status')!='RESOLVED' or gb.get('status')!='RESOLVED': r['classification']='EXACT_FOOTPRINT_UNRESOLVED'; return r
    combos=[]
    for ca in ga['candidates']:
        for cb in gb['candidates']:
            try:
                ov,area=polygon_overlap(ca['polygon'],cb['polygon']); combos.append({'overlap':bool(ov),'area':area})
            except Exception as exc: combos.append({'overlap':None,'error':f'{type(exc).__name__}: {exc}'})
    valid=[x for x in combos if x.get('overlap') is not None]
    if len(valid)!=len(combos) or not valid:
        r.update({'classification':'EXACT_FOOTPRINT_GEOMETRY_AMBIGUOUS','combination_count':len(combos),'valid_combination_count':len(valid)}); return r
    pos=sum(bool(x['overlap']) for x in valid); r['combination_count']=len(valid); r['overlap_combination_count']=pos
    r['max_intersection_area_tangent_deg2']=max((x['area'] for x in valid),default=0.0); r['min_intersection_area_tangent_deg2']=min((x['area'] for x in valid),default=0.0)
    if pos==len(valid): r['classification']='TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST'; r['detector_execution_eligible']=True
    elif pos==0: r['classification']='NO_TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST'
    else: r['classification']='EXACT_FOOTPRINT_OVERLAP_AMBIGUOUS_ACROSS_SOLUTIONS'
    return r


def main():
    print('='*132); print('WIDE CENSUS — EXACT ARCHIVE-DERIVED SKY FOOTPRINT RESOLVER v052 (TAP parser fix 1)'); print('='*132)
    print('NETWORK: APPLAUSE DR4 TAP astrometric polygons + DASCH DR7 mosaic-package metadata.')
    print('NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n')
    for p in (PLAN,QUEUE,TIMING,APPLAUSE_META,POLICY):
        if not p.is_file(): raise RuntimeError(f'REFUSING: missing input {p}')
    policy=load_json(POLICY,{})
    if policy.get('policy_id')!=EXPECTED_POLICY_ID: raise RuntimeError('REFUSING: candidate policy mismatch')
    plan=load_json(PLAN,{})
    if plan.get('status')!='COMPLETE' or int(plan.get('exact_footprint_queue_count',-1))!=82: raise RuntimeError('REFUSING: v051 plan mismatch')
    if int(plan.get('unique_applause_physical_plates_needed',-1))!=49 or int(plan.get('unique_dasch_plates_needed',-1))!=24: raise RuntimeError('REFUSING: v051 plate counts changed')
    queue=read_csv(QUEUE)
    if len(queue)!=82: raise RuntimeError(f'REFUSING: expected 82 queue rows, got {len(queue)}')
    timing=load_json(TIMING,{}); timing_by_pair={x['canonical_pair']:x for x in timing.get('pairs',[])}
    ap_ids=sorted({int(float(row[k])) for row in queue for k in ('applause_plate_id_a','applause_plate_id_b') if str(row.get(k,'')).strip()})
    dplates=sorted({str(row[k]).strip().lower() for row in queue for k in ('dasch_plate_id_a','dasch_plate_id_b') if str(row.get(k,'')).strip()})
    CACHE.mkdir(parents=True,exist_ok=True); cp=load_json(CHECKPOINT,checkpoint_default())
    ap_cache=applause_cache_path()
    if not ap_cache.is_file():
        key='applause:solution_batch'
        if key in cp['transport_terminal']: raise RuntimeError('APPLAUSE TAP reached terminal transport failure')
        try:
            rows,raw,normalized,response_format,content_type,status,final_url,query=applause_tap_query(ap_ids)
            ap_cache.parent.mkdir(parents=True,exist_ok=True)
            ap_cache.write_bytes(normalized)
            raw_ext = '.votable.xml' if response_format == 'votable' else '.csv'
            raw_path = CACHE / ('applause_solution_response' + raw_ext)
            raw_path.write_bytes(raw)
            write_json(
                applause_meta_path(),
                {
                    'http_status': status,
                    'final_url': final_url,
                    'query': query,
                    'row_count': len(rows),
                    'response_format': response_format,
                    'content_type': content_type,
                    'raw_response_path': str(raw_path.relative_to(ROOT)).replace('\\\\','/'),
                    'raw_response_sha256': hashlib.sha256(raw).hexdigest(),
                    'normalized_csv_sha256': hashlib.sha256(normalized).hexdigest(),
                },
            )
            print(
                f'APPLAUSE TAP: cached {len(rows)} solution rows for {len(ap_ids)} plates '
                f'from {response_format.upper()} response'
            )
        except Exception as exc:
            n=mark_transport(cp,key,exc)
            print(
                f'APPLAUSE transport/parser retry {n}/{MAX_TRANSPORT_ATTEMPTS}: '
                f'{type(exc).__name__}: {exc}'
            )
            return 10
    remote=0
    for plate in dplates:
        path=dasch_cache_path(plate)
        if path.is_file(): continue
        key=f'dasch:{plate}'
        if key in cp['transport_terminal']:
            write_json(path,{'status':'METADATA_TRANSPORT_UNRESOLVED','plate_id':plate,'transport':cp['transport_terminal'][key]}); continue
        if remote>=REMOTE_BATCH_DASCH: break
        try:
            pkg,status,final=post_json(DASCH_API,{'plate_id':plate,'binning':1}); pkg['_audit_http_status']=status; pkg['_audit_final_url']=final; write_json(path,pkg); print(f'DASCH {plate}: cached package metadata')
        except Exception as exc:
            n=mark_transport(cp,key,exc); print(f'DASCH transport retry {n}/{MAX_TRANSPORT_ATTEMPTS} {plate}: {type(exc).__name__}: {exc}')
        remote+=1
    d_done=sum(dasch_cache_path(x).is_file() for x in dplates); cp.update({'status':'IN_PROGRESS','applause_done':ap_cache.is_file(),'applause_plate_count':len(ap_ids),'dasch_done':d_done,'dasch_total':len(dplates)}); write_json(CHECKPOINT,cp)
    if d_done<len(dplates): print(f'\nCHECKPOINT: APPLAUSE batch=done | DASCH {d_done}/{len(dplates)}'); print('RETURN 10: checkpointed IN_PROGRESS'); return 10
    ap_rows=read_csv(ap_cache); apmeta=load_applause_exposure_meta(); dpkg={p:load_json(dasch_cache_path(p),{}) for p in dplates}
    results=[]
    for i,row in enumerate(queue,1):
        t=timing_by_pair.get(row['canonical_pair'])
        if t is None: raise RuntimeError(f"REFUSING: timing pair missing: {row['canonical_pair']}")
        result=evaluate_pair(row,side_geometry(row,'a',t,ap_rows,apmeta,dpkg),side_geometry(row,'b',t,ap_rows,apmeta,dpkg)); results.append(result)
        print(f"[{i:02d}/{len(queue):02d}] {result['classification']} :: {row['canonical_pair']}")
    counts={}
    for row in results: counts[row['classification']]=counts.get(row['classification'],0)+1
    survivors=[x for x in results if x['classification']=='TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST']
    holds=[x for x in results if x['classification'] in ('EXACT_FOOTPRINT_UNRESOLVED','EXACT_FOOTPRINT_GEOMETRY_AMBIGUOUS','EXACT_FOOTPRINT_OVERLAP_AMBIGUOUS_ACROSS_SOLUTIONS')]
    fields=['exact_footprint_priority','canonical_pair','timing_validation_priority','time_gate','physical_overlap_s','exposure_a','archive_a','site_a','exposure_b','archive_b','site_b','classification','detector_execution_eligible','science_eligible','combination_count','overlap_combination_count','max_intersection_area_tangent_deg2','min_intersection_area_tangent_deg2']
    for path,rows in ((OUT_CSV,results),(SURVIVOR_CSV,survivors),(HOLD_CSV,holds)):
        tmp=path.with_suffix(path.suffix+'.tmp')
        with tmp.open('w',newline='',encoding='utf-8') as fh: w=csv.DictWriter(fh,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
        tmp.replace(path)
    payload={'status':'COMPLETE','analysis_kind':'wide_census_exact_footprint_v052','guards':{'network_access':True,'science_pixels_read':False,'non_science_pixels_read':False,'transient_detector_rerun':False,'candidate_state_mutation':False},
             'input_sha256':{'plan':sha(PLAN),'queue':sha(QUEUE),'timing':sha(TIMING),'applause_metadata':sha(APPLAUSE_META),'policy':sha(POLICY)},
             'classification_counts':counts,'true_overlap_survivor_count':len(survivors),'hold_count':len(holds),'detector_execution_eligible_count':len(survivors),'science_eligible_count':0,
             'interpretation_boundary':'Exact-footprint survival defines an observing opportunity eligible for the frozen detector, not evidence that a transient exists. Ambiguous/unresolved geometry is held.',
             'pairs':results,'next_stage':'Freeze robust true-overlap survivors into a detector-execution queue; keep exact-footprint holds separate.'}
    write_json(OUT_JSON,payload); cp.update({'status':'COMPLETE','classification_counts':counts,'true_overlap_survivor_count':len(survivors),'hold_count':len(holds)}); write_json(CHECKPOINT,cp)
    print('\n'+'='*132); print('EXACT FOOTPRINT CENSUS COMPLETE'); print('='*132); print('Classification counts:',json.dumps(counts,sort_keys=True)); print(f'Robust true-overlap survivors: {len(survivors)}'); print(f'Geometry holds: {len(holds)}'); print(f'Detector-execution eligible opportunities: {len(survivors)}'); print('SCIENCE ELIGIBLE CANDIDATES: 0'); print(f'Report: {OUT_JSON}'); print('\nSTAGE STATUS: PASS'); return 0

if __name__=='__main__': raise SystemExit(main())
