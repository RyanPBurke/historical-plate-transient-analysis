#!/usr/bin/env python3
from pathlib import Path, PurePosixPath
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, unquote, quote
import csv, hashlib, html as html_lib, json, math, re, shutil, threading, time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
RESEARCH = ROOT / 'research'
CONTRACT = RESEARCH/'prospective_freezes'/'pair17_pixel_followup_scan_plan_and_acquisition_contract_v079.json'
V075 = RESULTS/'pair17_epoch_aware_gaia_static_triage_v075'/'pair17_epoch_aware_gaia_static_triage_v075.csv'
V077A = RESULTS/'pair17_applause_independent_plate_opportunity_census_v077a'
V077_OPPS = V077A/'pair17_candidate_plate_opportunities_v077a.csv'
V077_SUMMARY = V077A/'pair17_applause_independent_plate_opportunity_census_v077a.json'
V077_BANK = V077A/'pair17_v077a_bank_manifest.json'
V078 = RESULTS/'pair17_applause_catalog_recurrence_screen_v078'
V078_SUMMARY = V078/'pair17_applause_catalog_recurrence_screen_v078.json'
V078_CAND = V078/'pair17_catalog_recurrence_candidate_summary_v078.csv'
V078_PLATE = V078/'pair17_catalog_recurrence_plate_nearest_v078.csv'
V078_QUERY = V078/'pair17_catalog_recurrence_query_manifest_v078.csv'
V078_RAW = V078/'pair17_catalog_recurrence_raw_rows_v078.csv'
V078_QUEUE = V078/'pair17_pixel_followup_queue_v078.csv'
V078_BANK = V078/'pair17_v078a_bank_manifest.json'
OUT = RESULTS/'pair17_pixel_followup_scan_plan_and_acquisition_v079'
CACHE = OUT/'cache'
PAGE_CACHE = CACHE/'plate_pages'
SCAN_DIR = ROOT/'work'/'pair17_pixel_followup_v079'/'scans'
OUT_PLAN = OUT/'pair17_candidate_comparison_plan_v079.csv'
OUT_SCANQ = OUT/'pair17_unique_scan_acquisition_queue_v079.csv'
OUT_URL = OUT/'pair17_scan_url_resolution_manifest_v079.csv'
OUT_ACQ = OUT/'pair17_scan_acquisition_manifest_v079.csv'
OUT_JSON = OUT/'pair17_pixel_followup_scan_plan_and_acquisition_v079.json'

EXPECTED_CONTRACT_SHA='e1b13d4ac3a3eb96b1355ecec046eb6a69cd1f1963bc5bd1534a03f448d4fa62'
EXPECTED_SHA={
 V075:'cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097',
 V077_OPPS:'f8bd8a1bc322d0a9dc0239e29f676975f8ff692e17e040e2786cc196caf24b1d',
 V077_SUMMARY:'2e9872fc777d22e9f14bac51e4460abdba7d38352400fab095d36de0df2cd4b2',
 V077_BANK:'86545f2e4fa228c9472665bfe59ba7625314c548c0117bc00442265d8a1e97ef',
 V078_SUMMARY:'2e8d8cac0bbf91bf950941992e073059740a542cd537999bbbc46d9793769601',
 V078_CAND:'4294aa5cb8e7c4138e0a5683945c4d8eaad56aed5ca133c4f7d2ddb71d155ee5',
 V078_PLATE:'15a87820c5e48132be81eae579ddc8b72ef80e2c65cf91e3803cc275f526c7e1',
 V078_QUERY:'6f121dc567c9cdfdfd344a6134495afa08f7ca20279858ff985b1ab0dc65fe04',
 V078_RAW:'68bdfe735e1cc0c1a137c412339c5861783623123ec57b49eb62fce8645d7c2f',
 V078_QUEUE:'3be9c4049f40e9d9af43decfa9036ce186c0d6b22250ea274908e5299e461879',
 V078_BANK:'aa23e0295bba6d7a6fa05fd24a7afd402df420e9b078770b289a0e0200c1d47f',
}
SCIENCE_PLATES={7685,89580}
SCIENCE_EPOCH=datetime.fromisoformat('1953-12-02T20:48:58.500000+00:00')
NEGATIVE_TARGET=4
DOWNLOAD_WORKERS=3
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0 Safari/537.36'
CHUNK=8*1024*1024
PLATE_PAGE='https://www.plate-archive.org/objects/dr.4/plates/{archive_id}_{plate_id}/'
ORIGINAL_V079_RUNNER_SHA='7ec762e6aafa17f46c465852003b9be23e877bc325a9da9c4b7597b98a6a44aa'
V079A_RUNNER_SHA='1ebaa0acaad3b28bdca944137b114dd0a26219b977196f44b8a2f00b7bb55968'
DOWNLOAD_ATTEMPTS=5
RANGE_PROBE_BYTES=2880
LOCK=threading.Lock()

def say(*a):
    with LOCK: print(*a, flush=True)
def fail(s): raise RuntimeError(s)
def sha256(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(CHUNK),b''): h.update(b)
    return h.hexdigest()
def fint(v):
    try:return int(str(v).strip())
    except:
        try:
            x=float(v); return int(x) if math.isfinite(x) and x.is_integer() else None
        except:return None
def ffloat(v):
    try:
        x=float(str(v).strip()); return x if math.isfinite(x) else None
    except:return None
def truthy(v): return str(v).strip().lower() in {'1','true','yes','y'}
def rows(path):
    with Path(path).open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def atomic_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True); t=path.with_suffix(path.suffix+'.tmp')
    t.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8'); t.replace(path)
def atomic_csv(path,data,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True); fields=fields or (list(data[0]) if data else [])
    t=path.with_suffix(path.suffix+'.tmp')
    with t.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');
        if fields:w.writeheader();w.writerows(data)
    t.replace(path)
def parse_dt(s):
    s=str(s or '').strip()
    if not s:return None
    for x in (s,s.replace('Z','+00:00')):
        try:
            d=datetime.fromisoformat(x)
            if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        except:pass
    return None
def rep_start(s):
    ds=[parse_dt(x) for x in str(s or '').split(';')]; ds=[d for d in ds if d]
    return min(ds,key=lambda d:abs((d-SCIENCE_EPOCH).total_seconds())) if ds else None
def family(r):
    s=(str(r.get('archive_names',''))+' '+str(r.get('institutes',''))).lower()
    if 'hamburg' in s:return 'HAMBURG'
    if 'bamberg' in s:return 'BAMBERG'
    return 'OTHER'
def rank(r):
    d=r['_rep_dt']; miss=1 if d is None else 0; dt=float('inf') if d is None else abs((d-SCIENCE_EPOCH).total_seconds())
    return (0 if r.get('coverage_class')=='COVERED_INTERIOR' else 1, miss, dt, fint(r.get('physical_opportunity_plate_id')) or 10**18)

def load_queue():
    q=rows(V078_QUEUE)
    if len(q)!=23:fail(f'Expected 23 frozen survivors, got {len(q)}')
    ids=set(); pops=defaultdict(int)
    for r in q:
        rid=str(r.get('raw_match_row','')).strip(); pop=str(r.get('population','')).strip()
        if not rid or rid in ids:fail(f'Bad/duplicate queue id {rid!r}')
        if not truthy(r.get('pixel_followup_required_by_frozen_v078_branch')):fail(f'Non-frozen queue row {rid}')
        ids.add(rid); pops[pop]+=1
    if pops['PRIMARY_424']!=13 or pops['DIAGNOSTIC_179']!=10:fail(f'Population changed {dict(pops)}')
    return q,ids

def load_opps(ids):
    out=defaultdict(list); n=0
    with V077_OPPS.open('r',encoding='utf-8-sig',newline='') as f:
        rd=csv.DictReader(f)
        for r in rd:
            n+=1; rid=str(r.get('raw_match_row','')).strip()
            if rid not in ids:continue
            pid=fint(r.get('physical_opportunity_plate_id'))
            if pid is None or pid in SCIENCE_PLATES:fail(f'Invalid opportunity {rid}/{pid}')
            r['_rep_dt']=rep_start(r.get('exposure_start_values')); r['_family']=family(r); out[rid].append(r)
    if n!=496009:fail(f'Opportunity row count changed {n}')
    for rid in ids:
        if not out[rid]:fail(f'No opportunities for {rid}')
    return out

def load_context(ids):
    out=defaultdict(dict)
    with V078_PLATE.open('r',encoding='utf-8-sig',newline='') as f:
        rd=csv.DictReader(f)
        for r in rd:
            rid=str(r.get('raw_match_row','')).strip()
            if rid not in ids:continue
            pid=fint(r.get('eligible_physical_plate_id'))
            if pid is None:continue
            old=out[rid].get(pid); a=ffloat(old.get('separation_arcsec')) if old else None; b=ffloat(r.get('separation_arcsec'))
            if old is None or a is None or (b is not None and b<a):out[rid][pid]=r
    return out

def choose_neg(opps,ctx):
    pool=[r for r in opps if fint(r['physical_opportunity_plate_id']) not in ctx]
    chosen=[]; seen=set()
    def add(r,role):
        pid=fint(r['physical_opportunity_plate_id'])
        if pid in seen:return False
        seen.add(pid); chosen.append((r,role)); return True
    for fam in ('HAMBURG','BAMBERG'):
        fr=[r for r in pool if r['_family']==fam]
        bef=sorted([r for r in fr if r['_rep_dt'] and r['_rep_dt']<SCIENCE_EPOCH],key=rank)
        aft=sorted([r for r in fr if r['_rep_dt'] and r['_rep_dt']>=SCIENCE_EPOCH],key=rank)
        c=0
        if bef and add(bef[0],f'SENSITIVITY_NEGATIVE_{fam}_BEFORE'):c+=1
        if aft and add(aft[0],f'SENSITIVITY_NEGATIVE_{fam}_AFTER'):c+=1
        if c<2:
            for r in sorted([x for x in fr if fint(x['physical_opportunity_plate_id']) not in seen],key=rank):
                if add(r,f'SENSITIVITY_NEGATIVE_{fam}_FILL'):c+=1
                if c>=2:break
    if len(chosen)<NEGATIVE_TARGET:
        for r in sorted([x for x in pool if fint(x['physical_opportunity_plate_id']) not in seen],key=rank):
            add(r,'SENSITIVITY_NEGATIVE_GLOBAL_FILL')
            if len(chosen)>=NEGATIVE_TARGET:break
    return chosen[:NEGATIVE_TARGET],len(pool)

def build_plan(q,opps,ctx):
    plan=[]; summary={}
    for qr in q:
        rid=str(qr['raw_match_row']); pop=str(qr['population']); rs=opps[rid]; cx=ctx.get(rid,{})
        bypid={fint(r['physical_opportunity_plate_id']):r for r in rs}; used=set()
        strict=sorted(pid for pid,r in cx.items() if r.get('plate_recurrence_class')=='STRICT_LE3')
        if len(strict)>1:fail(f'Survivor {rid} has >1 strict plate')
        def emit(r,role,cr=None):
            pid=fint(r['physical_opportunity_plate_id'])
            if pid in used:return
            used.add(pid); d=r['_rep_dt']; delta=(d-SCIENCE_EPOCH).total_seconds() if d else None
            plan.append({
             'raw_match_row':rid,'population':pop,'v078_catalog_recurrence_class':qr.get('catalog_recurrence_class',''),
             'selection_role':role,'physical_plate_id':pid,'archive_family':r['_family'],'archive_id':fint(r.get('archive_id')),
             'archive_names':r.get('archive_names',''),'institutes':r.get('institutes',''),
             'representative_exposure_start_utc':d.isoformat() if d else '','seconds_from_science_epoch':delta,
             'coverage_class':r.get('coverage_class',''),'edge_distance_arcsec':r.get('edge_distance_arcsec',''),
             'scan_id':fint(r.get('scan_id')),'filename_scan':r.get('filename_scan',''),'expected_file_size':fint(r.get('file_size')),
             'fits_checksum':r.get('fits_checksum',''),'solution_id':fint(r.get('solution_id')),'solution_num':fint(r.get('solution_num')),
             'v078_plate_recurrence_class':cr.get('plate_recurrence_class','') if cr else 'NO_SOURCE_WITHIN_15_ARCSEC',
             'v078_nearest_separation_arcsec':cr.get('separation_arcsec','') if cr else ''})
        for pid in strict:emit(bypid[pid],'POSITIVE_STRICT_RECURRENCE_CONTROL',cx[pid])
        contextual=[]; crk={'DIAGNOSTIC_GT3_LE5':0,'WIDE_GT5_LE15':1}
        for pid,cr in cx.items():
            cls=cr.get('plate_recurrence_class','')
            if cls in crk and pid in bypid:contextual.append((crk[cls],ffloat(cr.get('separation_arcsec')) or float('inf'),pid,bypid[pid],cr))
        if contextual:
            contextual.sort(key=lambda x:(x[0],x[1],x[2])); emit(contextual[0][3],'CONTEXTUAL_3_TO_15_ARCSEC_CONTROL',contextual[0][4])
        neg,avail=choose_neg(rs,cx)
        for r,role in neg:emit(r,role)
        summary[rid]={'population':pop,'strict_positive_controls':len(strict),'contextual_control_selected':1 if contextual else 0,
                      'available_no_source_physical_plates':avail,'selected_sensitivity_negative_controls':len(neg),
                      'negative_control_shortfall':len(neg)<NEGATIVE_TARGET}
    return plan,summary

def scan_queue(plan):
    d={}
    for r in plan:
        sid=fint(r['scan_id']); fn=str(r['filename_scan']).strip(); pid=fint(r['physical_plate_id']); aid=fint(r['archive_id'])
        if sid is None or not fn or pid is None or aid is None:fail(f'Missing scan identity {r}')
        k=(sid,fn)
        if k not in d:d[k]={'scan_id':sid,'filename_scan':fn,'physical_plate_id':pid,'archive_id':aid,'expected_file_size':fint(r.get('expected_file_size')),
                            'fits_checksum':r.get('fits_checksum',''),'candidate_ids':set(),'selection_roles':set()}
        d[k]['candidate_ids'].add(str(r['raw_match_row']));d[k]['selection_roles'].add(str(r['selection_role']))
    out=[]
    for k in sorted(d):
        x=d[k]; out.append({**x,'candidate_count_using_scan':len(x['candidate_ids']),'candidate_ids':';'.join(sorted(x['candidate_ids'],key=int)),
                            'selection_roles':';'.join(sorted(x['selection_roles']))})
    return out

def plate_page(aid,pid,force=False):
    PAGE_CACHE.mkdir(parents=True,exist_ok=True)
    p=PAGE_CACHE/f'{aid}_{pid}.html'

    if p.is_file() and p.stat().st_size and not force:
        return p.read_text(encoding='utf-8',errors='replace'),True

    url=PLATE_PAGE.format(archive_id=aid,plate_id=pid)
    req=urllib.request.Request(
        url,
        headers={
            'User-Agent':UA,
            'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language':'en-GB,en;q=0.9',
            'Cache-Control':'no-cache',
        }
    )
    with urllib.request.urlopen(req,timeout=120) as resp:
        raw=resp.read()

    txt=raw.decode('utf-8',errors='replace')
    t=p.with_suffix('.html.tmp')
    t.write_text(txt,encoding='utf-8')
    t.replace(p)
    return txt,False


def normalize_scan_reference(value):
    """
    APPLAUSE DR4 scan.filename_scan can be a repository-relative path such as
    DR4/scans/HAM-LA/LA08164_y.fits, rather than only a basename.

    Preserve that exact repository-relative identity. Never append the full
    repository path after an already-derived archive folder.
    """
    raw=str(value or '').strip().replace('\\','/')
    while raw.startswith('/'):
        raw=raw[1:]

    if not raw:
        fail('Blank frozen filename_scan')

    parts=[p for p in raw.split('/') if p not in ('','.')]
    if '..' in parts:
        fail(f'Unsafe filename_scan path: {raw}')

    basename=PurePosixPath(raw).name

    if raw.lower().startswith('dr4/scans/'):
        repo_rel=raw
        source='FROZEN_REPOSITORY_RELATIVE_FILENAME_SCAN'
    elif '/' not in raw:
        repo_rel=''
        source='BASENAME_ONLY_REQUIRES_PAGE_FOLDER'
    else:
        # Preserve the raw value for provenance but do not invent semantics for
        # an unexpected path shape.
        repo_rel=''
        source='UNEXPECTED_FILENAME_SCAN_PATH_SHAPE'

    return raw,basename,repo_rel,source


def page_scan_folder(txt):
    """
    Determine a unique DR4 archive directory from the official plate page.
    Preview and scan products use the same archive-directory token in APPLAUSE.
    This is used only if filename_scan is a basename rather than the already
    repository-relative DR4/scans/... value.
    """
    unescaped=html_lib.unescape(txt)
    folders=[]

    for m in re.finditer(
        r'(?:/files/)?DR4/(?:previews|scans)/([^/"\'<> ]+)/',
        unescaped,
        flags=re.IGNORECASE,
    ):
        folder=unquote(m.group(1))
        if folder not in folders:
            folders.append(folder)

    return folders[0] if len(folders)==1 else ''


def direct_file_url(repo_rel):
    parts=[quote(p,safe='-_.~') for p in repo_rel.split('/') if p]
    return 'https://www.plate-archive.org/files/' + '/'.join(parts)


def range_probe(url,expected):
    """
    Reuse the already-proven APPLAUSE transport check from the earlier pipeline:
    a small HTTP byte-range GET against the exact direct FITS URL.
    No science pixels are interpreted; bytes are discarded after transport check.
    """
    headers={
        'User-Agent':UA,
        'Range':f'bytes=0-{RANGE_PROBE_BYTES-1}',
        'Accept':'application/fits,application/octet-stream,*/*',
        'Cache-Control':'no-cache',
    }

    req=urllib.request.Request(url,headers=headers,method='GET')

    try:
        with urllib.request.urlopen(req,timeout=120) as resp:
            status=int(getattr(resp,'status',200))
            content_range=str(resp.headers.get('Content-Range') or '')
            content_length=str(resp.headers.get('Content-Length') or '')
            final_url=resp.geturl()
            probe=resp.read(RANGE_PROBE_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            body=exc.read(1000).decode('utf-8',errors='replace')
        except Exception:
            body=''
        return {
            'ok':False,
            'http_status':int(exc.code),
            'content_range':'',
            'content_length':'',
            'final_url':url,
            'probe_bytes':0,
            'error':f'HTTP {exc.code} {exc.reason}; body={body!r}',
        }
    except Exception as exc:
        return {
            'ok':False,
            'http_status':'',
            'content_range':'',
            'content_length':'',
            'final_url':url,
            'probe_bytes':0,
            'error':f'{type(exc).__name__}: {exc}',
        }

    total=None
    m=re.search(r'/([0-9]+)$',content_range)
    if m:
        total=int(m.group(1))
    elif status==200 and content_length.isdigit():
        total=int(content_length)

    size_ok=(expected is None or total is None or int(expected)==int(total))
    status_ok=(status in (200,206))
    bytes_ok=(len(probe)>0)

    return {
        'ok':bool(status_ok and bytes_ok and size_ok),
        'http_status':status,
        'content_range':content_range,
        'content_length':content_length,
        'final_url':final_url,
        'probe_bytes':len(probe),
        'reported_total_bytes':total,
        'expected_size_match':size_ok,
        'error':'' if (status_ok and bytes_ok and size_ok) else (
            f'probe validation failed status={status} bytes={len(probe)} '
            f'expected={expected} reported_total={total}'
        ),
    }


def resolve(r):
    aid=int(r['archive_id'])
    pid=int(r['physical_plate_id'])
    expected=fint(r.get('expected_file_size'))

    raw,basename,repo_rel,source=normalize_scan_reference(
        r.get('filename_scan')
    )

    txt,cached=plate_page(aid,pid)
    unescaped=html_lib.unescape(txt)

    # Plate page must at least identify the exact frozen scan basename. This
    # keeps the v079 official-object-page provenance guard intact.
    page_mentions_basename=(basename.lower() in unescaped.lower())

    if not page_mentions_basename:
        txt,_=plate_page(aid,pid,force=True)
        unescaped=html_lib.unescape(txt)
        page_mentions_basename=(basename.lower() in unescaped.lower())
        refetched=True
    else:
        refetched=False

    if not page_mentions_basename:
        return {
            **r,
            'filename_scan_raw':raw,
            'scan_basename':basename,
            'normalized_repository_relative_scan':'',
            'scan_reference_source':source,
            'plate_page_url':PLATE_PAGE.format(
                archive_id=aid,plate_id=pid
            ),
            'plate_page_cached':cached,
            'plate_page_refetched_v079b':refetched,
            'plate_page_exact_basename_present':False,
            'resolved_scan_url':'',
            'url_resolution_method':'PLATE_PAGE_FILENAME_MISMATCH',
            'range_probe_ok':False,
            'range_probe_error':'official plate page does not mention frozen scan basename',
            'url_resolution_status':'UNRESOLVED',
        }

    if not repo_rel:
        folder=page_scan_folder(txt)
        if folder:
            repo_rel=f'DR4/scans/{folder}/{basename}'
            source=source+'+UNIQUE_OFFICIAL_PAGE_ARCHIVE_FOLDER'
        else:
            return {
                **r,
                'filename_scan_raw':raw,
                'scan_basename':basename,
                'normalized_repository_relative_scan':'',
                'scan_reference_source':source,
                'plate_page_url':PLATE_PAGE.format(
                    archive_id=aid,plate_id=pid
                ),
                'plate_page_cached':cached,
                'plate_page_refetched_v079b':refetched,
                'plate_page_exact_basename_present':True,
                'resolved_scan_url':'',
                'url_resolution_method':'NO_UNIQUE_DR4_ARCHIVE_FOLDER',
                'range_probe_ok':False,
                'range_probe_error':'',
                'url_resolution_status':'UNRESOLVED',
            }

    url=direct_file_url(repo_rel)
    probe=range_probe(url,expected)

    return {
        **r,
        'filename_scan_raw':raw,
        'scan_basename':basename,
        'normalized_repository_relative_scan':repo_rel,
        'scan_reference_source':source,
        'plate_page_url':PLATE_PAGE.format(
            archive_id=aid,plate_id=pid
        ),
        'plate_page_cached':cached,
        'plate_page_refetched_v079b':refetched,
        'plate_page_exact_basename_present':True,
        'resolved_scan_url':probe.get('final_url') or url,
        'url_resolution_method':'DIRECT_FROM_FROZEN_DR4_SCAN_FILENAME_PLUS_RANGE_PROBE',
        'range_probe_ok':probe['ok'],
        'range_probe_http_status':probe.get('http_status',''),
        'range_probe_content_range':probe.get('content_range',''),
        'range_probe_content_length':probe.get('content_length',''),
        'range_probe_reported_total_bytes':probe.get('reported_total_bytes',''),
        'range_probe_expected_size_match':probe.get('expected_size_match',''),
        'range_probe_error':probe.get('error',''),
        'url_resolution_status':'RESOLVED' if probe['ok'] else 'UNRESOLVED',
    }


def local_path(r):
    basename=str(r.get('scan_basename') or '').strip()
    if not basename:
        _,basename,_,_=normalize_scan_reference(r.get('filename_scan'))
    return SCAN_DIR/str(int(r['scan_id']))/basename

def download(r):
    dst=local_path(r)
    dst.parent.mkdir(parents=True,exist_ok=True)
    exp=fint(r.get('expected_file_size'))

    if dst.is_file() and exp is not None and dst.stat().st_size==exp:
        return {
            **r,
            'local_path':str(dst.relative_to(ROOT)).replace('\\','/'),
            'actual_file_size':exp,
            'sha256':sha256(dst),
            'download_status':'ALREADY_COMPLETE',
            'download_attempts':0,
        }

    if dst.is_file() and exp is None:
        dst.unlink()

    last_exc=None

    for attempt in range(1,DOWNLOAD_ATTEMPTS+1):
        try:
            off=dst.stat().st_size if dst.is_file() else 0

            if exp is not None and off>exp:
                fail(f'Local scan too large {dst}')

            headers={
                'User-Agent':UA,
                'Accept':'application/fits,application/octet-stream,*/*',
            }
            if off:
                headers['Range']=f'bytes={off}-'

            req=urllib.request.Request(
                r['resolved_scan_url'],headers=headers,method='GET'
            )
            resp=urllib.request.urlopen(req,timeout=180)
            status=int(getattr(resp,'status',200))

            if off and status!=206:
                resp.close()
                off=0
                headers={
                    'User-Agent':UA,
                    'Accept':'application/fits,application/octet-stream,*/*',
                }
                req=urllib.request.Request(
                    r['resolved_scan_url'],headers=headers,method='GET'
                )
                resp=urllib.request.urlopen(req,timeout=180)

            mode='ab' if off else 'wb'
            done=off
            last=time.time()

            with resp,dst.open(mode) as f:
                while True:
                    b=resp.read(CHUNK)
                    if not b:
                        break
                    f.write(b)
                    done+=len(b)
                    now=time.time()

                    if now-last>=10:
                        say(
                            f"scan {r['scan_id']} {r.get('scan_basename') or r['filename_scan']}: "
                            f"{done/(1024**2):,.1f} MiB"
                            +(f" ({100*done/exp:.1f}%)" if exp else '')
                        )
                        last=now

            actual=dst.stat().st_size

            if exp is not None and actual!=exp:
                raise RuntimeError(
                    f'Size mismatch scan {r["scan_id"]}: {actual}!={exp}'
                )

            return {
                **r,
                'local_path':str(dst.relative_to(ROOT)).replace('\\','/'),
                'actual_file_size':actual,
                'sha256':sha256(dst),
                'download_status':'COMPLETE',
                'download_attempts':attempt,
            }

        except Exception as exc:
            last_exc=exc

            retryable=True
            if isinstance(exc,urllib.error.HTTPError):
                retryable=int(exc.code) in {
                    408,429,500,502,503,504
                }

            if not retryable or attempt>=DOWNLOAD_ATTEMPTS:
                break

            say(
                f"scan {r['scan_id']} transport retry "
                f"{attempt}/{DOWNLOAD_ATTEMPTS}: "
                f"{type(exc).__name__}: {exc}"
            )
            time.sleep(min(30.0,2.0**attempt))

    raise RuntimeError(
        f"scan {r['scan_id']} {r.get('scan_basename') or r['filename_scan']} "
        f"failed after {DOWNLOAD_ATTEMPTS} attempts: "
        f"{type(last_exc).__name__}: {last_exc}"
    ) from last_exc

def main():
    print('='*132);print('PAIR 17 — FROZEN SURVIVOR COMPARISON SCAN PLAN + ACQUISITION v079b');print('='*132)
    print('Frozen survivors: 23 (13 PRIMARY + 10 DIAGNOSTIC)');print('Comparison pixels inspected: NO');print('Disposition changes: NONE\n')
    if not CONTRACT.is_file():fail(f'Missing contract {CONTRACT}')
    if sha256(CONTRACT)!=EXPECTED_CONTRACT_SHA:fail('v079 contract SHA mismatch')
    for p,e in EXPECTED_SHA.items():
        if not p.is_file():fail(f'Missing frozen input {p}')
        a=sha256(p)
        if a!=e:fail(f'SHA mismatch {p}\nexpected {e}\nactual {a}')
        print('HASH PASS:',p.relative_to(ROOT))
    q,ids=load_queue();print('\nLoading survivor opportunity universe ...');op=load_opps(ids);print('Loading v078 per-plate catalogue context ...');cx=load_context(ids)
    plan,cs=build_plan(q,op,cx);short=[rid for rid,x in cs.items() if x['negative_control_shortfall']]
    sq=scan_queue(plan);OUT.mkdir(parents=True,exist_ok=True);atomic_csv(OUT_PLAN,plan);atomic_csv(OUT_SCANQ,sq)
    known=sum(int(r['expected_file_size']) for r in sq if r.get('expected_file_size') is not None)
    print('\nv079 FROZEN COMPARISON PLAN');print('  candidate x selected-plate rows:',len(plan));print('  unique scan files required:     ',len(sq));print('  negative-control shortfalls:    ',len(short));print(f'  known expected bytes:           {known:,} ({known/(1024**3):.2f} GiB)')
    print('\nResolving official APPLAUSE scan URLs ...');urlrows=[]
    for i,r in enumerate(sq,1):
        rr=resolve(r);urlrows.append(rr)
        if i%10==0 or i==len(sq):print(f'  URL resolution {i}/{len(sq)}; unresolved={sum(x["url_resolution_status"]!="RESOLVED" for x in urlrows)}')
    atomic_csv(OUT_URL,urlrows);un=[r for r in urlrows if r['url_resolution_status']!='RESOLVED']
    if un:
        atomic_json(OUT_JSON,{'status':'OPERATIONAL_HOLD_URL_RESOLUTION','contract_sha256':EXPECTED_CONTRACT_SHA,'unresolved_scan_urls':len(un),'guards':{'comparison_pixels_inspected':0,'candidate_disposition_changes':False}})
        fail(f'{len(un)} scan URLs unresolved; held before downloads')
    outstanding=0
    for r in urlrows:
        exp=fint(r.get('expected_file_size'));dst=local_path(r)
        if exp is not None and not(dst.is_file() and dst.stat().st_size==exp):outstanding+=max(0,exp-(dst.stat().st_size if dst.is_file() else 0))
    base=SCAN_DIR.parent if SCAN_DIR.parent.exists() else ROOT;free=shutil.disk_usage(base).free;need=int(outstanding*1.25+2*(1024**3))
    print(f'\nDisk guard: outstanding={outstanding/(1024**3):.2f} GiB required_free={need/(1024**3):.2f} GiB available={free/(1024**3):.2f} GiB')
    if free<need:fail('Insufficient free disk; no science measurement performed')
    print(f'\nAcquiring {len(urlrows)} unique scans with {DOWNLOAD_WORKERS} workers ...');acq=[];fails=[]
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
        futs={ex.submit(download,r):r for r in urlrows}
        for i,f in enumerate(as_completed(futs),1):
            try:acq.append(f.result())
            except Exception as exc:fails.append({'scan_id':futs[f]['scan_id'],'filename_scan':futs[f]['filename_scan'],'error':f'{type(exc).__name__}: {exc}'})
            if i%5==0 or i==len(urlrows):say(f'Acquisition {i}/{len(urlrows)}; failures={len(fails)}')
    acq.sort(key=lambda r:(int(r['scan_id']),str(r.get('scan_basename') or r['filename_scan'])));atomic_csv(OUT_ACQ,acq)
    if fails:
        failpath=OUT/'pair17_scan_acquisition_failures_v079b.csv'
        atomic_csv(failpath,fails)
        fail(
            f'{len(fails)} acquisition failures; completed scans remain resumable; '
            f'failure details written to {failpath}'
        )
    report={'status':'COMPLETE','analysis_kind':'pair17_pixel_followup_scan_plan_and_acquisition_v079','contract_sha256':EXPECTED_CONTRACT_SHA,'operational_repair':'v079b normalize repository-relative filename_scan and verify direct FITS transport by range probe','original_v079_runner_sha256':ORIGINAL_V079_RUNNER_SHA,'v079a_runner_sha256':V079A_RUNNER_SHA,'scientific_contract_changed_by_v079b':False,
            'population':{'all':23,'primary':13,'diagnostic':10},'plan':{'candidate_selected_plate_rows':len(plan),'unique_scan_files':len(sq),'negative_control_shortfalls':short,'candidate_summary':cs},
            'acquisition':{'download_workers':DOWNLOAD_WORKERS,'unique_scans_complete':len(acq),'known_expected_bytes':known,'actual_acquired_bytes':sum(int(r['actual_file_size']) for r in acq),'scan_sha256_recorded':True},
            'guards':{'comparison_pixels_inspected':0,'detector_rerun':False,'registration_rerun':False,'injection_measurements':0,'recurrence_measurements_beyond_frozen_v078_catalogue':0,'candidate_disposition_changes':False},
            'outputs':{'candidate_comparison_plan':str(OUT_PLAN.relative_to(ROOT)).replace('\\','/'),'unique_scan_acquisition_queue':str(OUT_SCANQ.relative_to(ROOT)).replace('\\','/'),'scan_url_resolution_manifest':str(OUT_URL.relative_to(ROOT)).replace('\\','/'),'scan_acquisition_manifest':str(OUT_ACQ.relative_to(ROOT)).replace('\\','/')},
            'next_stage':'target-independent local registration plus frozen sensitivity/injection analysis'}
    atomic_json(OUT_JSON,report)
    print('\n'+'='*132);print('v079b COMPARISON SCAN PLAN + ACQUISITION COMPLETE');print('='*132)
    print('Frozen survivors:             23');print('Candidate x selected plates:',len(plan));print('Unique scans acquired:       ',len(acq));print('Negative-control shortfalls: ',len(short));print(f"Actual scan bytes acquired:  {sum(int(r['actual_file_size']) for r in acq)/(1024**3):.2f} GiB");print('Comparison pixels inspected: 0');print('Candidate dispositions:      NONE');print('STAGE STATUS: COMPLETE')
if __name__=='__main__':main()
