#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter, defaultdict
import argparse, csv, hashlib, importlib.util, json, math, subprocess, time, urllib.parse, urllib.request, re, xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree

CONTRACT_REL=Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_catalogue_independence_completeness_contract_v094f.json')
PROV_REL=Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_catalogue_independence_completeness_parent_provenance_v094f.json')
INV_REL=Path('pipeline_v0.2.0/research/prospective_freezes/applause_dr4_v094c_source_cache_inventory_v094e.csv')
RUNNER_REL=Path('pipeline_v0.2.0/tools/run_applause_dr4_catalogue_independence_completeness_audit_v094f.py')
EXPECTED_PARENT='7dc5f1dde1e9b9d84b3b760a4792f23e324609a6'
TAP_ASYNC='https://www.plate-archive.org/tap/async'
PROCESS_FIELDS=['process_id','scan_id','plate_id','archive_id','num_exposures','threshold','num_sources','num_true_sources','num_artifacts','num_solutions','color_term','bright_limit','num_gaia_edr3','faint_limit','mag_range','calibrated','completed','pyplate_version']
THRESH=[0.01,0.1,0.5,1.0,3.0,5.0]
SHIFTS=[(30,0),(-30,0),(0,30),(0,-30),(60,0),(-60,0),(0,60),(0,-60)]

def sha256(p):
    h=hashlib.sha256();
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open('r',encoding='utf-8-sig',newline='') as f: yield from csv.DictReader(f)

def safe_float(v):
    try:
        x=float(str(v if v is not None else '').strip()); return x if math.isfinite(x) else None
    except: return None

def safe_int(v):
    x=safe_float(v)
    if x is None: return None
    r=int(round(x)); return r if abs(x-r)<1e-8 else None

def ratio(a,b): return None if not b else a/b

def median(vals):
    a=sorted(x for x in vals if x is not None and math.isfinite(float(x)))
    if not a:return None
    n=len(a); return float(a[n//2]) if n%2 else (float(a[n//2-1])+float(a[n//2]))/2

def verify_git(repo, freeze):
    subprocess.run(['git','-C',str(repo),'cat-file','-e',freeze+'^{commit}'],check=True,stdout=subprocess.DEVNULL)
    for rel in (CONTRACT_REL,PROV_REL,RUNNER_REL):
        frozen=subprocess.check_output(['git','-C',str(repo),'show',f'{freeze}:{rel.as_posix()}'])
        local=(repo/rel).read_bytes()
        if frozen!=local: raise RuntimeError(f'Frozen Git byte mismatch: {rel}')

def load_module(project, prov):
    p=project/prov['frozen_local_inputs']['v094c_runner']
    spec=importlib.util.spec_from_file_location('v094c_frozen',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def verify_inputs(project, repo, prov):
    pairs=[
      (project/prov['v094e']['report'],prov['v094e']['report_sha256']),
      (project/prov['v094e']['per_triplet'],prov['v094e']['per_triplet_sha256']),
      (project/prov['v094e']['order_bins'],prov['v094e']['order_bins_sha256']),
      (project/prov['v094e']['output_manifest'],prov['v094e']['output_manifest_sha256']),
      (project/prov['frozen_local_inputs']['v093_scan_cache'],prov['frozen_local_inputs']['v093_scan_cache_sha256']),
      (project/prov['frozen_local_inputs']['v093_solution_cache'],prov['frozen_local_inputs']['v093_solution_cache_sha256']),
      (project/prov['frozen_local_inputs']['v094d_master_registry'],prov['frozen_local_inputs']['v094d_master_registry_sha256']),
      (project/prov['frozen_local_inputs']['v094c_runner'],prov['frozen_local_inputs']['v094c_runner_sha256']),
      (repo/INV_REL,prov['frozen_local_inputs']['source_cache_inventory_sha256'])]
    for p,h in pairs:
        if not p.is_file() or sha256(p)!=h: raise RuntimeError(f'Parent input hash mismatch: {p}')
    inv=list(rows(repo/INV_REL))
    if len(inv)!=1073: raise RuntimeError('source inventory row count mismatch')
    for i,r in enumerate(inv,1):
        p=project/r['relative_path']
        if not p.is_file() or p.stat().st_size!=int(r['size_bytes']) or sha256(p)!=r['sha256']:
            raise RuntimeError(f'source cache mismatch scan={r["scan_id"]}')
        if i%100==0: print(f'source-cache verification: {i}/1073',flush=True)
    return inv

def parse_stc(v):
    nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ''))]
    if len(nums)<8:return None
    nums=nums[-8:]; p=[(nums[i]%360,nums[i+1]) for i in range(0,8,2)]
    return None if any(not(-90<=d<=90) for _,d in p) else p

def process_id_from_source_id(s):
    x=int(s); base=40_000_000_000_000
    if x<base:return None
    return (x-base)//10_000_000

def scan_cache_info(project, inv):
    info={}; fingerprints=defaultdict(list); process_to_scans=defaultdict(set)
    for i,r in enumerate(inv,1):
        sid=int(r['scan_id']); p=project/r['relative_path']; z=np.load(p,allow_pickle=False)
        ids=np.asarray(z['source_id'],dtype=np.int64); ra=np.asarray(z['ra'],dtype=np.float64); dec=np.asarray(z['dec'],dtype=np.float64)
        pids=sorted(set(process_id_from_source_id(x) for x in ids if process_id_from_source_id(x) is not None))
        for pid in pids: process_to_scans[pid].add(sid)
        order=np.lexsort((dec,ra)) if len(ra) else np.asarray([],dtype=np.int64)
        h=hashlib.sha256(); h.update(np.asarray([len(ra)],dtype='<i8').tobytes()); h.update(ra[order].astype('<f8').tobytes()); h.update(dec[order].astype('<f8').tobytes())
        fp=h.hexdigest(); fingerprints[fp].append(sid)
        info[sid]={'scan_id':sid,'cache_rows':len(ra),'process_ids':pids,'process_id_count':len(pids),'coordinate_fingerprint':fp}
        if i%100==0: print(f'scan fingerprint audit: {i}/1073',flush=True)
    return info,fingerprints,process_to_scans

def discover_result_url(job):
    try:
        with urllib.request.urlopen(job,timeout=120) as r: body=r.read().decode('utf-8','replace')
        root=ET.fromstring(body)
        for el in root.iter():
            if el.tag.lower().endswith('result'):
                href=el.attrib.get('{http://www.w3.org/1999/xlink}href') or el.attrib.get('href')
                if href:return urllib.parse.urljoin(job+'/',href)
    except: pass
    for s in ('/results/result','/results/votable'):
        u=job+s
        try:
            with urllib.request.urlopen(u,timeout=120) as r: head=r.read(512)
            if b'VOTABLE' in head.upper(): return u
        except: pass
    raise RuntimeError('could not discover TAP result URL')

def tap_process_batch(process_ids, out, batch_index):
    from astropy.table import Table
    ids=','.join(map(str,process_ids)); q=f"SELECT {','.join(PROCESS_FIELDS)} FROM applause_dr4.process WHERE process_id IN ({ids})"
    out.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(1,6):
        try:
            print(f'process TAP batch {batch_index}: {len(process_ids)} ids, attempt {attempt}',flush=True)
            data=urllib.parse.urlencode({'REQUEST':'doQuery','LANG':'ADQL','FORMAT':'votable','QUERY':q,'MAXREC':'10000','PHASE':'RUN'}).encode()
            req=urllib.request.Request(TAP_ASYNC,data=data,method='POST')
            with urllib.request.urlopen(req,timeout=180) as r:
                job=r.geturl().rstrip('/'); body=r.read(20000).decode('utf-8','replace'); loc=r.headers.get('Location')
                if loc: job=urllib.parse.urljoin(job+'/',loc).rstrip('/')
            if '/tap/async/' not in job:
                m=re.search(r'https?://[^"\s<]+/tap/async/[^"\s<]+',body)
                if m:job=m.group(0).rstrip('/')
            if '/tap/async/' not in job: raise RuntimeError('cannot resolve TAP job')
            t0=time.time()
            while True:
                with urllib.request.urlopen(job+'/phase',timeout=120) as r: ph=r.read().decode().strip().upper()
                if 'COMPLETED' in ph: break
                if 'ERROR' in ph or 'ABORTED' in ph: raise RuntimeError(f'TAP phase {ph}')
                if time.time()-t0>3600: raise RuntimeError('TAP process batch >1h')
                time.sleep(10)
            u=discover_result_url(job); data=urllib.request.urlopen(u,timeout=300).read(); out.write_bytes(data)
            tbl=Table.read(out,format='votable')
            return tbl
        except Exception as e:
            if attempt==5: raise
            print(f'process TAP batch {batch_index} retry: {e}',flush=True); time.sleep(15*attempt)

def acquire_process_metadata(project, process_ids):
    from astropy.table import Table, vstack
    work=project/'work'/'applause_dr4_catalogue_independence_completeness_audit_v094f'/'process_tap'
    tables=[]; ids=sorted(process_ids); batch=200
    for bi,start in enumerate(range(0,len(ids),batch),1):
        group=ids[start:start+batch]; p=work/f'process_batch_{bi:03d}.vot'
        if p.is_file():
            try: tbl=Table.read(p,format='votable')
            except: p.unlink(); tbl=tap_process_batch(group,p,bi)
        else: tbl=tap_process_batch(group,p,bi)
        tables.append(tbl)
    alltbl=vstack(tables,metadata_conflicts='silent') if tables else Table()
    meta={}
    for r in alltbl:
        pid=safe_int(r['process_id']);
        if pid is None:continue
        d={}
        for c in PROCESS_FIELDS:
            try:
                v=r[c]
                if np.ma.is_masked(v): d[c]=None
                elif isinstance(v,bytes): d[c]=v.decode('utf-8','replace')
                elif hasattr(v,'item'): d[c]=v.item()
                else:d[c]=v
            except:d[c]=None
        meta[pid]=d
    state=work/'process_metadata_summary.json'; state.write_text(json.dumps({'requested_process_ids':len(ids),'returned_process_ids':len(meta),'raw_batches':len(tables)},indent=2)+'\n')
    return meta

def load_scan_geometry(project, prov):
    st=list(rows(project/prov['frozen_local_inputs']['v093_scan_cache'])); sol=list(rows(project/prov['frozen_local_inputs']['v093_solution_cache']))
    plate_scans=defaultdict(list)
    for r in st:
        pid=safe_int(r.get('plate_id')); sid=safe_int(r.get('scan_id'))
        if pid is not None and sid is not None: plate_scans[pid].append(sid)
    scan_polys=defaultdict(list)
    for r in sol:
        sid=safe_int(r.get('scan_id')); p=parse_stc(r.get('stc_polygon'))
        if sid is not None and p: scan_polys[sid].append(p)
    for pid in list(plate_scans): plate_scans[pid]=sorted(set(s for s in plate_scans[pid] if scan_polys.get(s)))
    return plate_scans,scan_polys

def offset_coords(ra,dec,dx,dy):
    ra=np.asarray(ra,float); dec=np.asarray(dec,float); d2=np.clip(dec+dy/3600.0,-89.999999,89.999999); c=np.cos(np.deg2rad(dec)); c=np.where(np.abs(c)<1e-6,1e-6,c); r2=(ra+dx/(3600.0*c))%360.0; return r2,d2

def cumulative_sep(dists):
    return {str(t):int(np.count_nonzero(dists<=t)) for t in THRESH}

def role_process_summary(scan_ids,scan_info,pmeta):
    vals=defaultdict(list)
    for sid in scan_ids:
        for pid in scan_info[sid]['process_ids']:
            m=pmeta.get(pid,{})
            for k in ('num_sources','num_true_sources','num_artifacts','faint_limit','bright_limit','threshold','color_term','num_gaia_edr3'):
                x=safe_float(m.get(k))
                if x is not None: vals[k].append(x)
    out={f'median_{k}':median(v) for k,v in vals.items()}
    ns=out.get('median_num_sources'); nt=out.get('median_num_true_sources'); na=out.get('median_num_artifacts')
    out['true_fraction']=ratio(nt,ns); out['artifact_fraction']=ratio(na,ns)
    return out

def scan_count_summary(scan_ids,scan_info): return median([scan_info[s]['cache_rows'] for s in scan_ids])

def load_exposure_archives(project,prov):
    p=project/prov['frozen_local_inputs']['v094d_master_registry']; out={}
    for r in rows(p):
        eid=safe_int(r.get('exposure_id'))
        if eid is not None: out[eid]=safe_int(r.get('archive_id'))
    return out

def fingerprint_summary(fps,scan_to_plate):
    dup=[v for v in fps.values() if len(v)>1]; cross=[]
    for scans in dup:
        plates=sorted(set(scan_to_plate.get(s) for s in scans if scan_to_plate.get(s) is not None))
        if len(plates)>1: cross.append({'scan_ids':scans,'plate_ids':plates})
    return {'duplicate_fingerprint_groups':len(dup),'scans_in_duplicate_groups':sum(len(x) for x in dup),'cross_plate_duplicate_groups':len(cross),'cross_plate_examples':cross[:20]}

def summarize_window(per,lo,hi):
    rr=[r for r in per if r['matchable_ordinal'] is not None and lo<=r['matchable_ordinal']<=hi]
    def wsum(k):return sum(int(r.get(k) or 0) for r in rr)
    obs_num=wsum('observed_confirm'); obs_den=wsum('control_mismatch_positions')
    n30=sum(int(r.get('null30_matches') or 0) for r in rr); d30=sum(int(r.get('null30_valid') or 0) for r in rr)
    n60=sum(int(r.get('null60_matches') or 0) for r in rr); d60=sum(int(r.get('null60_valid') or 0) for r in rr)
    return {'triplets':len(rr),'candidate_rows':sum(int(r.get('candidate_csv_rows') or 0) for r in rr),'observed_confirm_rate':ratio(obs_num,obs_den),'null30_rate':ratio(n30,d30),'null60_rate':ratio(n60,d60),'observed_to_null30_ratio':ratio(ratio(obs_num,obs_den),ratio(n30,d30)) if d30 and n30 else None,'observed_to_null60_ratio':ratio(ratio(obs_num,obs_den),ratio(n60,d60)) if d60 and n60 else None,'median_control_to_positive_cache_count_ratio':median([safe_float(r.get('control_to_positive_cache_count_ratio')) for r in rr]),'median_control_to_independent_cache_count_ratio':median([safe_float(r.get('control_to_independent_cache_count_ratio')) for r in rr]),'median_control_minus_positive_faint_limit':median([safe_float(r.get('control_minus_positive_faint_limit')) for r in rr]),'median_control_minus_independent_faint_limit':median([safe_float(r.get('control_minus_independent_faint_limit')) for r in rr])}

def self_test():
    ra=np.array([10.]);dec=np.array([30.]);r,d=offset_coords(ra,dec,30,0); assert r[0]>10 and abs(d[0]-30)<1e-9
    assert process_id_from_source_id(40_000_000_000_000+123*10_000_000+9)==123
    print('v094f self-test PASS'); return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project-root');ap.add_argument('--repo-root');ap.add_argument('--freeze-commit');ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
    if a.self_test:return self_test()
    if not all((a.project_root,a.repo_root,a.freeze_commit)):ap.error('project/repo/freeze required')
    project=Path(a.project_root).resolve();repo=Path(a.repo_root).resolve();freeze=a.freeze_commit.strip();verify_git(repo,freeze)
    contract=json.loads((repo/CONTRACT_REL).read_text());prov=json.loads((repo/PROV_REL).read_text())
    if contract.get('status')!='PROSPECTIVE_CATALOGUE_INDEPENDENCE_COMPLETENESS_AUDIT' or prov.get('status')!='FROZEN_PARENT_PROVENANCE_PREPARED_BEFORE_V094F_EXECUTION':raise RuntimeError('contract/provenance status mismatch')
    inv=verify_inputs(project,repo,prov); print('Frozen v094f parent inputs verified',flush=True)
    scan_info,fps,process_to_scans=scan_cache_info(project,inv)
    process_ids=set(pid for x in scan_info.values() for pid in x['process_ids'])
    print(f'Unique process IDs derived from frozen source caches: {len(process_ids)}',flush=True)
    pmeta=acquire_process_metadata(project,process_ids)
    print(f'Process metadata returned: {len(pmeta)}/{len(process_ids)}',flush=True)
    plate_scans,scan_polys=load_scan_geometry(project,prov); mod=load_module(project,prov); cache=mod.PlateLRU()
    vper=list(rows(project/prov['v094e']['per_triplet']))
    archives=load_exposure_archives(project,prov)
    per=[]; pair_acc=defaultdict(lambda:{'candidate_rows':0,'triplets':0})
    scan_to_plate={}
    for pid,ss in plate_scans.items():
        for sid in ss:scan_to_plate[sid]=pid
    for n,r in enumerate(vper,1):
        mo=safe_int(r.get('matchable_ordinal')); ti=safe_int(r.get('triplet_index')); pp=safe_int(r.get('positive_plate')); qp=safe_int(r.get('independent_plate')); cp=safe_int(r.get('control_plate'))
        base={'triplet_index':ti,'matchable_ordinal':mo,'canonical_pair':r.get('canonical_pair'),'positive_plate':pp,'independent_plate':qp,'control_plate':cp,'positive_exposure':safe_int(r.get('positive_exposure')),'independent_exposure':safe_int(r.get('independent_exposure')),'control_exposure':safe_int(r.get('control_exposure')),'candidate_csv_rows':safe_int(r.get('candidate_csv_rows')) or 0,'zero_source_hold':str(r.get('zero_source_hold')).lower() in ('true','1','yes')}
        base['positive_archive_id']=archives.get(base['positive_exposure']);base['independent_archive_id']=archives.get(base['independent_exposure']);base['control_archive_id']=archives.get(base['control_exposure'])
        if base['zero_source_hold'] or mo is None:
            base['status']='ZERO_SOURCE_HOLD';per.append(base);continue
        ps=plate_scans.get(pp,[]);qs=plate_scans.get(qp,[]);cs=plate_scans.get(cp,[])
        pdata=cache.get(pp,ps);qdata=cache.get(qp,qs);cdata=cache.get(cp,cs)
        if not(pdata['usable'] and qdata['usable'] and cdata['usable']):raise RuntimeError(f'Unexpected unusable source data triplet {ti}')
        pra,pdec=pdata['rep_ra'],pdata['rep_dec']; covp=mod.coverage_count_batch(pra,pdec,ps,scan_polys);covq=mod.coverage_count_batch(pra,pdec,qs,scan_polys);covc=mod.coverage_count_batch(pra,pdec,cs,scan_polys);common=(covp>=1)&(covq>=1)&(covc>=1);idx=np.flatnonzero(common)
        if len(idx):
            xyz=mod.xyz(pra[idx],pdec[idx]);dc,_=cdata['all_tree'].query(xyz,k=1);csep=mod.arcsec_from_chord_array(dc);mm=csep>mod.BUSKO_R_ARCSEC; midx=idx[mm]
        else:midx=np.asarray([],dtype=np.int64)
        qtree=cKDTree(mod.xyz(qdata['rep_ra'],qdata['rep_dec'])) if len(qdata['rep_ra']) else None
        if qtree is not None and len(midx):
            dq,_=qtree.query(mod.xyz(pra[midx],pdec[midx]),k=1);qsep=mod.arcsec_from_chord_array(dq);obs=int(np.count_nonzero(qsep<=mod.CONFIRM_DIAG_ARCSEC))
        else:qsep=np.asarray([],float);obs=0
        base['control_mismatch_positions']=len(midx);base['observed_confirm']=obs;base['observed_confirm_rate']=ratio(obs,len(midx))
        for dist in (30,60):
            nm=nv=0
            for dx,dy in [s for s in SHIFTS if abs(s[0])+abs(s[1])==dist]:
                sr,sd=offset_coords(pra[midx],pdec[midx],dx,dy); valid=mod.coverage_count_batch(sr,sd,qs,scan_polys)>=1; nv+=int(np.count_nonzero(valid))
                if qtree is not None and np.any(valid):
                    dd,_=qtree.query(mod.xyz(sr[valid],sd[valid]),k=1);sep=mod.arcsec_from_chord_array(dd);nm+=int(np.count_nonzero(sep<=mod.CONFIRM_DIAG_ARCSEC))
            base[f'null{dist}_matches']=nm;base[f'null{dist}_valid']=nv;base[f'null{dist}_rate']=ratio(nm,nv)
        base['observed_to_null30_ratio']=ratio(base['observed_confirm_rate'],base['null30_rate']) if base['null30_rate'] else None;base['observed_to_null60_ratio']=ratio(base['observed_confirm_rate'],base['null60_rate']) if base['null60_rate'] else None
        # Unconditional P->I overlap inside independent coverage, independent of control mismatch.
        qcov=np.flatnonzero(covq>=1)
        if qtree is not None and len(qcov):
            d,_=qtree.query(mod.xyz(pra[qcov],pdec[qcov]),k=1); sepall=mod.arcsec_from_chord_array(d)
        else:sepall=np.asarray([],float)
        for t,cnt in cumulative_sep(sepall).items():base['p_to_i_le_'+t.replace('.','p')+'_count']=cnt;base['p_to_i_le_'+t.replace('.','p')+'_fraction']=ratio(cnt,len(sepall))
        base['p_to_i_denominator']=len(sepall)
        pcount=scan_count_summary(ps,scan_info);qcount=scan_count_summary(qs,scan_info);ccount=scan_count_summary(cs,scan_info)
        base['positive_median_cache_rows_per_scan']=pcount;base['independent_median_cache_rows_per_scan']=qcount;base['control_median_cache_rows_per_scan']=ccount;base['control_to_positive_cache_count_ratio']=ratio(ccount,pcount);base['control_to_independent_cache_count_ratio']=ratio(ccount,qcount)
        pm=role_process_summary(ps,scan_info,pmeta);qm=role_process_summary(qs,scan_info,pmeta);cm=role_process_summary(cs,scan_info,pmeta)
        for pref,m in [('positive',pm),('independent',qm),('control',cm)]:
            for k,v in m.items():base[pref+'_'+k]=v
        base['control_minus_positive_faint_limit']=None if cm.get('median_faint_limit') is None or pm.get('median_faint_limit') is None else cm['median_faint_limit']-pm['median_faint_limit'];base['control_minus_independent_faint_limit']=None if cm.get('median_faint_limit') is None or qm.get('median_faint_limit') is None else cm['median_faint_limit']-qm['median_faint_limit']
        base['status']='AUDITED';per.append(base)
        pk=(pp,qp);pair_acc[pk]['candidate_rows']+=base['candidate_csv_rows'];pair_acc[pk]['triplets']+=1;pair_acc[pk]['p_to_i_denominator']=base['p_to_i_denominator']
        for t in THRESH:pair_acc[pk]['p_to_i_le_'+str(t).replace('.','p')+'_fraction']=base.get('p_to_i_le_'+str(t).replace('.','p')+'_fraction')
        pair_acc[pk]['positive_plate']=pp;pair_acc[pk]['independent_plate']=qp;pair_acc[pk]['positive_scans']=';'.join(map(str,ps));pair_acc[pk]['independent_scans']=';'.join(map(str,qs))
        if n%25==0:print(f'catalogue independence audit: {n}/784 triplets',flush=True)
    outdir=project/'results'/'applause_dr4_catalogue_independence_completeness_audit_v094f';outdir.mkdir(parents=True,exist_ok=True)
    perpath=outdir/'per_triplet_catalogue_independence_completeness_v094f.csv';pairpath=outdir/'science_pair_catalogue_overlap_v094f.csv';scanpath=outdir/'scan_process_fingerprint_audit_v094f.csv';reportpath=outdir/'applause_dr4_catalogue_independence_completeness_audit_v094f.json';manifest=outdir/'v094f_output_manifest.sha256'
    fields=sorted(set().union(*(x.keys() for x in per)))
    with perpath.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(per)
    pairs=list(pair_acc.values());pfields=sorted(set().union(*(x.keys() for x in pairs))) if pairs else []
    with pairpath.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=pfields);w.writeheader();w.writerows(pairs)
    srows=[]
    for sid,x in sorted(scan_info.items()):
        m={};
        if len(x['process_ids'])==1:m=pmeta.get(x['process_ids'][0],{})
        srows.append({'scan_id':sid,'plate_id':scan_to_plate.get(sid),'cache_rows':x['cache_rows'],'process_id_count':x['process_id_count'],'derived_process_ids_semicolon':';'.join(map(str,x['process_ids'])),'coordinate_fingerprint_prefix':x['coordinate_fingerprint'][:16],'process_num_sources':m.get('num_sources'),'process_num_true_sources':m.get('num_true_sources'),'process_num_artifacts':m.get('num_artifacts'),'process_faint_limit':m.get('faint_limit'),'process_color_term':m.get('color_term'),'process_calibrated':m.get('calibrated'),'process_completed':m.get('completed')})
    with scanpath.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(srows[0].keys()));w.writeheader();w.writerows(srows)
    audited=[x for x in per if x.get('status')=='AUDITED']; outside275=[x for x in audited if not(251<=x['matchable_ordinal']<=275)]; outside300=[x for x in audited if not(251<=x['matchable_ordinal']<=300)]
    def sumgroup(rr):
        on=sum(x['observed_confirm'] for x in rr);od=sum(x['control_mismatch_positions'] for x in rr);n30=sum(x['null30_matches'] for x in rr);d30=sum(x['null30_valid'] for x in rr);n60=sum(x['null60_matches'] for x in rr);d60=sum(x['null60_valid'] for x in rr)
        return {'triplets':len(rr),'candidate_rows':sum(x['candidate_csv_rows'] for x in rr),'observed_confirm_rate':ratio(on,od),'null30_rate':ratio(n30,d30),'null60_rate':ratio(n60,d60),'observed_to_null30_ratio':ratio(ratio(on,od),ratio(n30,d30)) if n30 else None,'observed_to_null60_ratio':ratio(ratio(on,od),ratio(n60,d60)) if n60 else None,'median_control_to_positive_cache_count_ratio':median([x.get('control_to_positive_cache_count_ratio') for x in rr]),'median_control_to_independent_cache_count_ratio':median([x.get('control_to_independent_cache_count_ratio') for x in rr]),'median_control_minus_positive_faint_limit':median([x.get('control_minus_positive_faint_limit') for x in rr]),'median_control_minus_independent_faint_limit':median([x.get('control_minus_independent_faint_limit') for x in rr])}
    archive_rows=Counter()
    for x in audited:archive_rows[f"P{x.get('positive_archive_id')}|I{x.get('independent_archive_id')}|C{x.get('control_archive_id')}"]+=x['candidate_csv_rows']
    fp=fingerprint_summary(fps,scan_to_plate); shared_process=[{'process_id':pid,'scan_ids':sorted(ss),'plate_ids':sorted(set(scan_to_plate.get(s) for s in ss))} for pid,ss in process_to_scans.items() if len(ss)>1]
    report={'status':'COMPLETE','analysis_kind':'applause_dr4_catalogue_independence_completeness_audit_v094f','freeze_commit':freeze,'guards':contract['guards'],'input_reproduction':{'triplets':len(per),'audited_matchable':len(audited),'candidate_rows_from_v094e_per_triplet':sum(x['candidate_csv_rows'] for x in per),'candidate_csv_reads':0,'source_calib_queries':0},'mechanism_tests':{'all_matchable':sumgroup(audited),'window_251_275':sumgroup([x for x in audited if 251<=x['matchable_ordinal']<=275]),'outside_251_275':sumgroup(outside275),'window_251_300':sumgroup([x for x in audited if 251<=x['matchable_ordinal']<=300]),'outside_251_300':sumgroup(outside300)},'scan_catalogue_identity':{**fp,'derived_process_ids_shared_across_multiple_scans_count':len(shared_process),'shared_process_examples':shared_process[:20]},'archive_role_candidate_rows_top20':archive_rows.most_common(20),'process_acquisition':{'derived_process_ids':len(process_ids),'returned_process_metadata':len(pmeta)},'interpretive_boundary':contract['interpretive_boundary'],'next_stop':contract['next_stop'],'outputs':{}}
    for p in (perpath,pairpath,scanpath):report['outputs'][p.name]={'sha256':sha256(p),'size_bytes':p.stat().st_size}
    reportpath.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');manifest.write_text('\n'.join(f'{sha256(p)}  {p.name}' for p in (perpath,pairpath,scanpath,reportpath))+'\n',encoding='ascii')
    w=report['mechanism_tests']['window_251_300'];o=report['mechanism_tests']['outside_251_300']
    print('\n'+'='*96);print('v094f CATALOGUE INDEPENDENCE / COMPLETENESS AUDIT COMPLETE');print('='*96)
    print(f"Matchable triplets audited:               {len(audited)}")
    print(f"Candidate CSV reads:                      0")
    print(f"251-300 observed confirm rate:            {w['observed_confirm_rate']:.4%}")
    print(f"251-300 shifted-null 30arcsec rate:       {w['null30_rate']:.4%}")
    print(f"251-300 shifted-null 60arcsec rate:       {w['null60_rate']:.4%}")
    print(f"251-300 observed/null30 ratio:            {w['observed_to_null30_ratio'] if w['observed_to_null30_ratio'] is not None else 'NA'}")
    print(f"Outside 251-300 observed confirm rate:    {o['observed_confirm_rate']:.4%}")
    print(f"Outside shifted-null 60arcsec rate:       {o['null60_rate']:.4%}")
    print(f"251-300 median C/P cache-count ratio:     {w['median_control_to_positive_cache_count_ratio']}")
    print(f"251-300 median C/I cache-count ratio:     {w['median_control_to_independent_cache_count_ratio']}")
    print(f"251-300 median C-P faint-limit delta:     {w['median_control_minus_positive_faint_limit']}")
    print(f"Cross-plate exact catalogue fingerprints: {fp['cross_plate_duplicate_groups']}")
    print(f"Process IDs shared across scans:          {len(shared_process)}")
    print('STOP: interpret mechanism evidence before corrected population, candidate inspection, or registration.')
    return 0
if __name__=='__main__':raise SystemExit(main())
