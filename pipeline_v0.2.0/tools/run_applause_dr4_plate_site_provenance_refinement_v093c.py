#!/usr/bin/env python3
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv, hashlib, json, math, re, urllib.parse, urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT/'research'/'prospective_freezes'/'applause_dr4_plate_site_provenance_refinement_contract_v093c.json'
EXPECTED_CONTRACT_SHA = 'fb2159d6b8d4415c3c8ffde068cd3b75763da79427b07646c300aac356f07766'
PARENT = ROOT/'results'/'applause_dr4_busko_first_cross_observatory_opportunity_census_v093'
PARENT_REPORT = PARENT/'applause_dr4_busko_first_cross_observatory_opportunity_census_v093.json'
SCI = PARENT/'applause_dr4_cross_observatory_space_time_opportunities_v093.csv'
COMP = PARENT/'applause_dr4_cross_observatory_short_lag_comparisons_v093.csv'
WORK = ROOT/'work'/'applause_dr4_plate_site_provenance_refinement_v093c'
CACHE = WORK/'tap_cache'
OUT = ROOT/'results'/'applause_dr4_plate_site_provenance_refinement_v093c'
TAP_SYNC = 'https://www.plate-archive.org/tap/sync'
PLATE_QUERY = '''SELECT plate_id, archive_id, plate_num, series, numexp,
 observatory, site_name, site_longitude, site_latitude,
 telescope, instrument, plate_quality
 FROM applause_dr4.plate'''

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def log(x=''):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {x}", flush=True)

def rows(p):
    with Path(p).open('r',encoding='utf-8-sig',newline='') as f:
        yield from csv.DictReader(f)

def wcsv(p, rr, fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+'.tmp')
    with t.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rr)
    t.replace(p)

def fnum(v):
    try:
        x=float(str(v or '').strip()); return x if math.isfinite(x) else None
    except: return None

def inum(v):
    x=fnum(v); return None if x is None else int(round(x))

def norm_site(v):
    s=re.sub(r'[^a-z0-9]+',' ',str(v or '').strip().lower())
    return ' '.join(s.split())

def hav_km(lat1,lon1,lat2,lon2):
    if None in (lat1,lon1,lat2,lon2): return None
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 6371.0088*2*math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))

def dist_band(d):
    if d is None:return 'COORDS_INCOMPLETE'
    if d<1:return 'LT1KM'
    if d<10:return 'GE1_LT10KM'
    if d<50:return 'GE10_LT50KM'
    if d<100:return 'GE50_LT100KM'
    return 'GE100KM'

def same_control_site(a,b):
    na,nb=norm_site(a['site_name']),norm_site(b['site_name'])
    if na and nb: return na==nb,'SITE_NAME'
    d=hav_km(a['lat'],a['lon'],b['lat'],b['lon'])
    return ((d is not None and d<1.0), 'COORDS_LT1KM' if d is not None else 'INSUFFICIENT_SITE_METADATA')

def tap_plate():
    CACHE.mkdir(parents=True,exist_ok=True)
    out=CACHE/'plate.csv'; meta=CACHE/'plate.query.json'
    if out.is_file() and out.stat().st_size>100:
        with out.open('r',encoding='utf-8-sig',newline='') as f: hdr=next(csv.reader(f),[])
        if 'plate_id' in [x.lower() for x in hdr]:
            log(f"Reuse plate cache: {out.stat().st_size/1024/1024:.1f} MiB sha={sha(out)[:16]}...")
            return out
    q=' '.join(PLATE_QUERY.split())
    data=urllib.parse.urlencode({'REQUEST':'doQuery','LANG':'ADQL','FORMAT':'csv','MAXREC':'200000','QUERY':q}).encode()
    req=urllib.request.Request(TAP_SYNC,data=data,method='POST')
    tmp=out.with_suffix('.csv.part')
    log('Downloading APPLAUSE DR4 plate metadata...')
    with urllib.request.urlopen(req,timeout=3600) as r,tmp.open('wb') as f:
        while True:
            b=r.read(1024*1024)
            if not b: break
            f.write(b)
    tmp.replace(out)
    meta.write_text(json.dumps({'query':q,'sha256':sha(out),'size_bytes':out.stat().st_size,'completed_utc':datetime.now(timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return out

def main():
    log('='*110); log('APPLAUSE DR4 — PLATE-SITE PROVENANCE REFINEMENT v093c'); log('='*110)
    log('NO source catalogue inspection; NO pixels; v093 is read-only.')
    if sha(CONTRACT)!=EXPECTED_CONTRACT_SHA: raise RuntimeError('v093c contract SHA mismatch')
    parent=json.loads(PARENT_REPORT.read_text(encoding='utf-8'))
    if parent.get('status')!='COMPLETE': raise RuntimeError('v093 parent not COMPLETE')
    for p in (SCI,COMP):
        exp=parent.get('output_hashes',{}).get(p.name)
        if not exp or sha(p)!=exp: raise RuntimeError(f'v093 parent output SHA mismatch: {p}')

    plate_path=tap_plate(); plate={}
    for r in rows(plate_path):
        pid=inum(r.get('plate_id'))
        if pid is None: continue
        plate[pid]={
            'plate_id':pid,'archive_id':inum(r.get('archive_id')),'plate_num':str(r.get('plate_num') or '').strip(),
            'series':str(r.get('series') or '').strip(),'numexp':inum(r.get('numexp')),
            'observatory':str(r.get('observatory') or '').strip(),'site_name':str(r.get('site_name') or '').strip(),
            'lon':fnum(r.get('site_longitude')),'lat':fnum(r.get('site_latitude')),
            'telescope':str(r.get('telescope') or '').strip(),'instrument':str(r.get('instrument') or '').strip(),
            'plate_quality':str(r.get('plate_quality') or '').strip(),
        }
    log(f'Plate metadata rows loaded: {len(plate)}')

    comp_by_pair=defaultdict(list)
    for r in rows(COMP): comp_by_pair[r['canonical_pair']].append(r)

    refined=[]; refined_comp=[]; missing=Counter(); site_bands=Counter()
    strong_tiers=Counter(); ge50_tiers=Counter(); ge100_tiers=Counter()
    physical_all=set(); comparison_reuse=Counter(); one_minute=Counter()

    sci_count=0
    for s in rows(SCI):
        sci_count+=1
        pa=plate.get(inum(s.get('plate_a'))); pb=plate.get(inum(s.get('plate_b')))
        if pa is None or pb is None:
            missing['science_plate_metadata_missing']+=1; continue
        na,nb=norm_site(pa['site_name']),norm_site(pb['site_name'])
        d=hav_km(pa['lat'],pa['lon'],pb['lat'],pb['lon'])
        band=dist_band(d); site_bands[band]+=1
        distinct_names=bool(na and nb and na!=nb)
        strong=bool(distinct_names and d is not None and d>=10)
        ge50=bool(distinct_names and d is not None and d>=50)
        ge100=bool(distinct_names and d is not None and d>=100)

        valid=[]
        for c in comp_by_pair.get(s['canonical_pair'],[]):
            ppos=plate.get(inum(c.get('positive_plate_id'))); pcmp=plate.get(inum(c.get('comparison_plate_id')))
            if ppos is None or pcmp is None:
                missing['comparison_plate_metadata_missing']+=1; continue
            if ppos['archive_id']!=pcmp['archive_id']:
                missing['comparison_archive_mismatch']+=1; continue
            if ppos['plate_id']==pcmp['plate_id']:
                missing['comparison_same_physical_plate']+=1; continue
            same,why=same_control_site(ppos,pcmp)
            rc=dict(c)
            rc.update({
                'positive_site_name':ppos['site_name'],'comparison_site_name':pcmp['site_name'],
                'positive_site_latitude':ppos['lat'],'positive_site_longitude':ppos['lon'],
                'comparison_site_latitude':pcmp['lat'],'comparison_site_longitude':pcmp['lon'],
                'same_site_control':same,'same_site_control_basis':why,
                'positive_plate_numexp':ppos['numexp'],'comparison_plate_numexp':pcmp['numexp'],
                'positive_telescope':ppos['telescope'],'comparison_telescope':pcmp['telescope'],
                'positive_instrument':ppos['instrument'],'comparison_instrument':pcmp['instrument'],
            })
            refined_comp.append(rc)
            if same and str(c.get('primary_common_coverage_ge50pct')).strip().lower() in {'true','1'}: valid.append(rc)
        valid.sort(key=lambda c:(float(c['endpoint_interval_gap_seconds']),inum(c['comparison_plate_id']) or -1))
        best=valid[0] if valid else None
        phys=tuple(sorted((pa['plate_id'],pb['plate_id']))); physical_all.add(phys)
        r=dict(s)
        r.update({
            'plate_site_a':pa['site_name'],'plate_observatory_a':pa['observatory'],'plate_site_lat_a':pa['lat'],'plate_site_lon_a':pa['lon'],
            'plate_numexp_a':pa['numexp'],'plate_telescope_a':pa['telescope'],'plate_instrument_a':pa['instrument'],
            'plate_site_b':pb['site_name'],'plate_observatory_b':pb['observatory'],'plate_site_lat_b':pb['lat'],'plate_site_lon_b':pb['lon'],
            'plate_numexp_b':pb['numexp'],'plate_telescope_b':pb['telescope'],'plate_instrument_b':pb['instrument'],
            'recorded_site_names_distinct':distinct_names,'site_separation_km':'' if d is None else f'{d:.6f}',
            'site_separation_band':band,'strong_independence_ge10km':strong,'independence_ge50km':ge50,'independence_ge100km':ge100,
            'same_site_primary_control_count':len(valid),'best_same_site_control_endpoint':'' if not best else best['comparison_for_endpoint'],
            'best_same_site_control_exposure':'' if not best else best['comparison_exposure_id'],
            'best_same_site_control_plate':'' if not best else best['comparison_plate_id'],
            'best_same_site_control_gap_minutes':'' if not best else best['endpoint_interval_gap_minutes'],
            'best_same_site_control_tier':'' if not best else best['tier'],
        })
        refined.append(r)
        if best:
            comparison_reuse[str(best['comparison_plate_id'])]+=1
            if abs(float(best['endpoint_interval_gap_minutes'])-1.0)<1e-9:
                one_minute[f"science_plates={phys};comparison_plate={best['comparison_plate_id']};endpoint={best['comparison_for_endpoint']}"]+=1
            if strong: strong_tiers[best['tier']]+=1
            if ge50: ge50_tiers[best['tier']]+=1
            if ge100: ge100_tiers[best['tier']]+=1

    refined.sort(key=lambda r:(0 if r['strong_independence_ge10km'] else 1, {'A_LE30MIN':0,'B_GT30_LE60MIN':1,'C_GT60_LE120MIN':2}.get(r['best_same_site_control_tier'],9), float(r['best_same_site_control_gap_minutes'] or 1e99), -float(r['physical_overlap_seconds']), r['canonical_pair']))
    OUT.mkdir(parents=True,exist_ok=True)
    wcsv(OUT/'applause_dr4_plate_site_refined_opportunities_v093c.csv',refined,list(refined[0].keys()) if refined else [])
    wcsv(OUT/'applause_dr4_plate_site_refined_comparisons_v093c.csv',refined_comp,list(refined_comp[0].keys()) if refined_comp else [])

    strong_rows=[r for r in refined if r['strong_independence_ge10km'] and r['best_same_site_control_tier']]
    unique_strong_phys={tuple(sorted((inum(r['plate_a']),inum(r['plate_b'])))) for r in strong_rows}
    report={
        'status':'COMPLETE','analysis_kind':'applause_dr4_plate_site_provenance_refinement_v093c',
        'contract_sha256':EXPECTED_CONTRACT_SHA,'parent_report_sha256':sha(PARENT_REPORT),'plate_cache_sha256':sha(plate_path),
        'plate_metadata_rows':len(plate),'parent_science_exposure_pair_rows':sci_count,
        'parent_unique_physical_science_plate_pairs':len(physical_all),'site_separation_band_counts':dict(site_bands),
        'strong_independent_exposure_pair_rows_with_same_site_primary_control':len(strong_rows),
        'strong_independent_unique_physical_science_plate_pairs_with_same_site_primary_control':len(unique_strong_phys),
        'strong_ge10km_best_control_tier_counts':dict(strong_tiers),'ge50km_best_control_tier_counts':dict(ge50_tiers),'ge100km_best_control_tier_counts':dict(ge100_tiers),
        'comparison_plate_reuse_top20':comparison_reuse.most_common(20),'one_minute_structure_top20':one_minute.most_common(20),
        'metadata_or_guard_holds':dict(missing),
        'top_25_strong_opportunities':[
            {'canonical_pair':r['canonical_pair'],'sites':[r['plate_site_a'],r['plate_site_b']],'site_separation_km':r['site_separation_km'],
             'physical_overlap_seconds':r['physical_overlap_seconds'],'science_plates':[r['plate_a'],r['plate_b']],
             'science_numexp':[r['plate_numexp_a'],r['plate_numexp_b']],'comparison_plate':r['best_same_site_control_plate'],
             'comparison_gap_minutes':r['best_same_site_control_gap_minutes'],'tier':r['best_same_site_control_tier']} for r in strong_rows[:25]],
        'guards':{'source_catalog_queries':0,'pixel_downloads':0,'fits_reads':0,'detector_runs':0,'candidate_adjudication':0,'candidate_disposition_changes':0,'v093_outputs_modified':False}
    }
    rp=OUT/'applause_dr4_plate_site_provenance_refinement_v093c.json'
    rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    log(''); log('='*110); log('v093c COMPLETE'); log('='*110)
    log(f"Parent exposure-pair rows: {sci_count}")
    log(f"Unique physical science plate pairs: {len(physical_all)}")
    log(f"Site bands: {dict(site_bands)}")
    log(f"Strong >=10 km + same-site primary control rows: {len(strong_rows)}")
    log(f"Strong unique physical science plate pairs: {len(unique_strong_phys)}")
    log(f"Strong tier counts: {dict(strong_tiers)}")
    log(f">=50 km tier counts: {dict(ge50_tiers)}")
    log(f">=100 km tier counts: {dict(ge100_tiers)}")
    for i,r in enumerate(strong_rows[:20],1):
        log(f"TOP {i:02d} {r['canonical_pair']} {r['plate_site_a']} / {r['plate_site_b']} dist={r['site_separation_km']}km overlap={r['physical_overlap_seconds']}s control={r['best_same_site_control_gap_minutes']}min {r['best_same_site_control_tier']} plates={r['plate_a']}|{r['plate_b']} comp={r['best_same_site_control_plate']}")
    log(f"REPORT SHA256: {sha(rp)}"); log('STAGE STATUS: COMPLETE')

if __name__=='__main__': main()
