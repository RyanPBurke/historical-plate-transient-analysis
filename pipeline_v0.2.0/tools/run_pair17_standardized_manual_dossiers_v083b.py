#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
import csv, hashlib, html, json, math, os
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from astropy.coordinates import SkyCoord
import astropy.units as u
from scipy.ndimage import gaussian_filter
import struct, zlib

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"pair17_standardized_manual_dossiers_contract_v083.json"
EXPECTED_CONTRACT_SHA="ac6ed350c0f55e1a4d3010ecadcf20c963baa185718d860fa6a0f38318ed669f"
V075=ROOT/"results"/"pair17_epoch_aware_gaia_static_triage_v075"/"pair17_epoch_aware_gaia_static_triage_v075.csv"
V079=ROOT/"results"/"pair17_pixel_followup_scan_plan_and_acquisition_v079"; V079_ACQ=V079/"pair17_scan_acquisition_manifest_v079.csv"; V079_BANK=V079/"pair17_v079b_bank_manifest.json"
V080=ROOT/"results"/"pair17_registered_native_pixel_recurrence_sensitivity_v080"; V080_TARGETS=V080/"pair17_registered_target_coordinates_v080.csv"; V080_PLATES=V080/"pair17_native_pixel_plate_measurements_v080.csv"; V080_CAND=V080/"pair17_native_pixel_candidate_summary_v080.csv"; V080_BANK=V080/"pair17_v080a_bank_manifest.json"
V081=ROOT/"results"/"pair17_temporal_bracketing_census_v081"; V081_OPPS=V081/"pair17_temporal_bracketing_opportunities_v081.csv"; V081_BANK=V081/"pair17_v081a_bank_manifest.json"
V082=ROOT/"results"/"pair17_survivor_chronology_native_pixel_synthesis_v082"; V082_EVID=V082/"pair17_survivor_evidence_table_v082.csv"; V082_CLOSE=V082/"pair17_close_time_native_pixel_measurements_v082.csv"; V082_BANK=V082/"pair17_v082_bank_manifest.json"
EXPECTED={V075:"cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097",V079_BANK:"d3bd17cb6c9da62feb17d10bd8f7b86789ee11b63acc8d131407ba0b785e1e42",V080_BANK:"f2ba81ab1222162e3d94a57d61d4f92da14ec37fef3dab4e54abd060ca699327",V081_BANK:"b361e0165061550bacd31f44ec0926dc450b2242b52e5b73de571deb7d56172d",V082_BANK:"fb0ab1a0d8d3afdd681bf24fd995086948f4b28fafa2473dd5752e067748338f"}
SURV=["293118","293470","293841","294052","294130","294179"]
OUT=ROOT/"results"/"pair17_standardized_manual_dossiers_v083"; OUT_SEL=OUT/"pair17_manual_dossier_selection_v083.csv"; OUT_MAN=OUT/"pair17_manual_dossier_panel_manifest_v083.csv"; OUT_JSON=OUT/"pair17_standardized_manual_dossiers_v083.json"; OUT_INDEX=OUT/"index.html"
CONTEXT=240.0; ZOOM=60.0; PLO=1.0; PHI=99.5; HPCLIP=5.0; BGSIG=8.0
SCI={"HAMBURG":{"plate_id":7685,"basename":"LA08164_y.fits","endpoint":"a","exposure":"APPLAUSE:14120"},"BAMBERG":{"plate_id":89580,"basename":"012673_1953_h.fits","endpoint":"b","exposure":"APPLAUSE:132654"}}

def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def rows(p):
 with Path(p).open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(p,rr):
 p.parent.mkdir(parents=True,exist_ok=True); fields=list(rr[0].keys()) if rr else []; t=p.with_suffix(p.suffix+'.tmp')
 with t.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');
  if fields:w.writeheader();w.writerows(rr)
 t.replace(p)
def write_json(p,o):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8');t.replace(p)
def num(v):
 try:
  x=float(str(v).strip());return x if math.isfinite(x) else None
 except:return None
def integer(v):
 x=num(v);return None if x is None else int(x)
def truth(v):return str(v).strip().lower() in {'1','true','yes','y'}
def safe(s):return ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in str(s))
def unique_file(b):
 m=[]
 for parent in (ROOT/'work',ROOT/'results'):
  if parent.exists():m.extend(p.resolve() for p in parent.rglob(b) if p.is_file())
 m=sorted(set(m))
 if len(m)!=1:raise RuntimeError(f'Expected one {b}; found {len(m)}: {m}')
 return m[0]
def acq_map():
 out={}
 for r in rows(V079_ACQ):
  sid,pid=integer(r.get('scan_id')),integer(r.get('physical_plate_id'))
  if sid is not None and pid is not None:out[(sid,pid)]={**r,'_path':ROOT/str(r.get('local_path') or '').replace('/',os.sep)}
 return out
def choose_wcs(h):
 w=WCS(h).celestial
 if w.pixel_n_dim!=2 or w.world_n_dim!=2:raise RuntimeError('No usable celestial WCS')
 return w
def pixscale(w):
 a=np.asarray(proj_plane_pixel_scales(w),dtype=float)*3600.0;a=a[np.isfinite(a)&(a>0)]
 if a.size==0:raise RuntimeError('No finite pixel scale')
 return float(np.median(a))
def cut(data,cx,cy,width,scale):
 half=max(8,int(math.ceil((width/scale)/2.0)));x=int(round(cx));y=int(round(cy));ny,nx=data.shape;x0,x1=max(0,x-half),min(nx,x+half+1);y0,y1=max(0,y-half),min(ny,y+half+1);a=np.asarray(data[y0:y1,x0:x1],dtype=float);return a,x0,y0,float(cx-x0),float(cy-y0)
def rsig(a):
 q=np.asarray(a,dtype=float);q=q[np.isfinite(q)]
 if q.size==0:return None
 med=float(np.median(q));mad=float(np.median(np.abs(q-med)));s=1.4826*mad;return s if math.isfinite(s) and s>0 else None
def rawnorm(a):
 q=np.asarray(a,dtype=float);f=q[np.isfinite(q)]
 if f.size<10:raise RuntimeError('Insufficient finite pixels')
 lo,hi=np.percentile(f,[PLO,PHI]);
 if not math.isfinite(lo) or not math.isfinite(hi) or hi<=lo:lo,hi=float(np.min(f)),float(np.max(f))
 if hi<=lo:hi=lo+1
 z=np.clip((q-lo)/(hi-lo),0,1);z[~np.isfinite(z)]=0;return z,lo,hi
def _png_chunk(kind,data):
 payload=kind+data
 return struct.pack(">I",len(data))+payload+struct.pack(">I",zlib.crc32(payload)&0xffffffff)

def _write_gray_png(p,image):
 arr=np.asarray(image,dtype=np.uint8)
 if arr.ndim!=2:raise RuntimeError("PNG writer expects 2-D grayscale image")
 h,w=arr.shape
 raw=b"".join(b"\x00"+arr[y,:].tobytes(order="C") for y in range(h))
 png=bytearray(b"\x89PNG\r\n\x1a\n")
 png.extend(_png_chunk(b"IHDR",struct.pack(">IIBBBBB",w,h,8,0,0,0,0)))
 png.extend(_png_chunk(b"IDAT",zlib.compress(raw,9)))
 png.extend(_png_chunk(b"IEND",b""))
 tmp=p.with_suffix(p.suffix+".tmp");tmp.write_bytes(bytes(png));tmp.replace(p)

def _crosshair(image,cx,cy):
 arr=np.array(image,dtype=np.uint8,copy=True);h,w=arr.shape
 x=int(round(float(cx)));y=int(round(float(cy)))
 arm=max(4,int(round(min(h,w)*.08)));gap=max(2,int(round(min(h,w)*.025)))
 def hseg(yy,a,b):
  if not (0<=yy<h):return
  a=max(0,a);b=min(w-1,b)
  if a>b:return
  if yy-1>=0:arr[yy-1,a:b+1]=0
  if yy+1<h:arr[yy+1,a:b+1]=0
  arr[yy,a:b+1]=255
 def vseg(xx,a,b):
  if not (0<=xx<w):return
  a=max(0,a);b=min(h-1,b)
  if a>b:return
  if xx-1>=0:arr[a:b+1,xx-1]=0
  if xx+1<w:arr[a:b+1,xx+1]=0
  arr[a:b+1,xx]=255
 hseg(y,x-arm,x-gap);hseg(y,x+gap,x+arm)
 vseg(x,y-arm,y-gap);vseg(x,y+gap,y+arm)
 return arr

def save_png(p,a,cx,cy,title,hp=False):
 p.parent.mkdir(parents=True,exist_ok=True);q=np.asarray(a,dtype=float)
 if hp:
  fin=np.isfinite(q);fill=float(np.nanmedian(q[fin])) if np.any(fin) else 0
  work=np.where(fin,q,fill);im=work-gaussian_filter(work,BGSIG)
  s=rsig(im);clip=HPCLIP*s if s is not None else max(1.0,float(np.std(im)))
  norm=np.clip((im+clip)/(2.0*clip),0,1);norm[~np.isfinite(norm)]=0.5
  image=np.rint(norm*255.0).astype(np.uint8)
 else:
  im,lo,hi=rawnorm(q);image=np.rint(im*255.0).astype(np.uint8)
 # v083a operational repair: title remains in HTML metadata rather than being
 # burned into the PNG; crop/stretch/high-pass/crosshair semantics are unchanged.
 _write_gray_png(p,_crosshair(image,cx,cy))
def target_pixel(m,target,w):
 c=target
 if str(m.get('registration_mode') or '')=='PRIMARY':
  e,n=num(m.get('registration_shift_east_arcsec')),num(m.get('registration_shift_north_arcsec'))
  if e is not None and n is not None:c=target.spherical_offsets_by(e*u.arcsec,n*u.arcsec)
 xy=np.asarray(w.all_world2pix([[float(c.ra.deg),float(c.dec.deg)]],0),dtype=float)[0]
 if not np.all(np.isfinite(xy)):raise RuntimeError('Non-finite target pixel')
 return float(xy[0]),float(xy[1])

def main():
 print('='*120);print('PAIR 17 — STANDARDIZED MANUAL DOSSIERS v083b');print('='*120);print('Operational repairs: stdlib PNG backend; science endpoints centered from frozen v075 RA/Dec via science WCS');print('Scientific contract changed: NO')
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise RuntimeError('v083 contract mismatch')
 for p,e in EXPECTED.items():
  if not p.is_file() or sha(p)!=e:raise RuntimeError(f'Frozen input mismatch: {p}')
  print('HASH PASS:',p.relative_to(ROOT))
 tri={str(r['raw_match_row']):r for r in rows(V075)};targets={str(r['raw_match_row']):r for r in rows(V080_TARGETS)};plate=rows(V080_PLATES);chron=rows(V081_OPPS);evid={str(r['raw_match_row']):r for r in rows(V082_EVID)};close=rows(V082_CLOSE)
 if sorted(evid,key=int)!=sorted(SURV,key=int):raise RuntimeError('Survivor population changed')
 acq=acq_map();science_paths={o:unique_file(m['basename']) for o,m in SCI.items()}
 neg=defaultdict(list)
 for r in plate:
  rid=str(r.get('raw_match_row') or '')
  if rid in SURV and truth(r.get('sensitivity_qualified_negative')):neg[rid].append(r)
 cmap=defaultdict(list)
 for r in chron:
  rid=str(r.get('raw_match_row') or '')
  if rid in SURV:cmap[(rid,integer(r.get('physical_plate_id')),integer(r.get('scan_id')))].append(r)
 cclose=defaultdict(list)
 for r in close:cclose[str(r.get('raw_match_row') or '')].append(r)
 sel=[]
 for rid in SURV:
  for obs in ('HAMBURG','BAMBERG'):
   m=SCI[obs];sel.append({'raw_match_row':rid,'panel_role':f'SCIENCE_{obs}','observatory':obs,'selection_basis':'FROZEN_SCIENCE_PAIR','physical_plate_id':m['plate_id'],'scan_id':'','filename_scan':m['basename'],'relation_to_common_overlap':'SCIENCE','gap_seconds':0,'gap_hours':0,'same_science_series':True,'measurement_source':'V075_SCIENCE_ENDPOINT'})
 for rid in SURV:
  for obs in ('HAMBURG','BAMBERG'):
   joined=[]
   for m in neg[rid]:
    for c in cmap.get((rid,integer(m.get('physical_plate_id')),integer(m.get('scan_id'))),[]):
     if str(c.get('observatory') or '')==obs:joined.append((m,c))
   for rel in ('PRECEDING','FOLLOWING'):
    same=[mc for mc in joined if str(mc[1].get('relation_to_common_overlap') or '')==rel and truth(mc[1].get('same_science_series'))];anyp=[mc for mc in joined if str(mc[1].get('relation_to_common_overlap') or '')==rel];pool=same if same else anyp
    if not pool:continue
    pool.sort(key=lambda mc:(float(mc[1].get('gap_seconds') or 1e99),integer(mc[1].get('physical_plate_id')) or 0,integer(mc[1].get('scan_id')) or 0));m,c=pool[0]
    sel.append({'raw_match_row':rid,'panel_role':f'{obs}_{rel}_QUALIFIED_NEGATIVE','observatory':obs,'selection_basis':'NEAREST_SAME_SERIES_SENSITIVITY_QUALIFIED_NEGATIVE' if same else 'FALLBACK_NEAREST_ANY_SERIES_SAME_OBSERVATORY_SENSITIVITY_QUALIFIED_NEGATIVE','physical_plate_id':integer(m.get('physical_plate_id')),'scan_id':integer(m.get('scan_id')),'filename_scan':m.get('filename_scan',''),'relation_to_common_overlap':rel,'gap_seconds':c.get('gap_seconds',''),'gap_hours':c.get('gap_hours',''),'exposure_start_utc':c.get('exposure_start_utc',''),'exposure_end_utc':c.get('exposure_end_utc',''),'same_science_series':c.get('same_science_series',''),'measurement_source':'BANKED_V080'})
 for rid in SURV:
  for m in cclose.get(rid,[]):
   key=(rid,integer(m.get('physical_plate_id')),integer(m.get('scan_id')));cc=cmap.get(key,[]);cc=sorted(cc,key=lambda r:float(r.get('gap_seconds') or 1e99));c=cc[0] if cc else {}
   sel.append({'raw_match_row':rid,'panel_role':'V082_CLOSE_TIME','observatory':c.get('observatory',m.get('archive_family','')),'selection_basis':'ALL_FROZEN_V082_CLOSE_TIME','physical_plate_id':integer(m.get('physical_plate_id')),'scan_id':integer(m.get('scan_id')),'filename_scan':m.get('filename_scan',''),'relation_to_common_overlap':c.get('relation_to_common_overlap',m.get('v081_nearest_relation','')),'gap_seconds':c.get('gap_seconds',m.get('v081_nearest_gap_seconds','')),'gap_hours':c.get('gap_hours',m.get('v081_nearest_gap_hours','')),'exposure_start_utc':c.get('exposure_start_utc',m.get('v081_nearest_exposure_start_utc','')),'exposure_end_utc':c.get('exposure_end_utc',m.get('v081_nearest_exposure_end_utc','')),'same_science_series':c.get('same_science_series',''),'measurement_source':'BANKED_V082'})
 group={}
 for r in sel:
  k=(r['raw_match_row'],int(r['physical_plate_id']),str(r.get('scan_id') or ''),str(r['filename_scan']))
  if k not in group:group[k]={**r,'_roles':[r['panel_role']], '_bases':[r['selection_basis']]}
  else:group[k]['_roles'].append(r['panel_role']);group[k]['_bases'].append(r['selection_basis'])
 selected=[]
 for k in sorted(group,key=lambda x:(int(x[0]),x[1],x[2],x[3])):
  r=group[k];r['panel_role']=';'.join(sorted(set(r.pop('_roles'))));r['selection_basis']=';'.join(sorted(set(r.pop('_bases'))));selected.append(r)
 write_csv(OUT_SEL,selected)
 meas={}
 for r in plate+close:meas[(str(r.get('raw_match_row') or ''),integer(r.get('physical_plate_id')),integer(r.get('scan_id')))]=r
 OUT.mkdir(parents=True,exist_ok=True);manifest=[];bycand=defaultdict(list)
 for i,panel in enumerate(selected,1):
  rid=panel['raw_match_row'];pid=int(panel['physical_plate_id']);sid=integer(panel.get('scan_id'));science='SCIENCE_' in panel['panel_role']
  if science:
   obs=panel['observatory'];path=science_paths[obs];tr=tri[rid];ep=SCI[obs]['endpoint'];m={};cx=cy=None
  else:
   aq=acq.get((sid,pid));
   if aq is None:raise RuntimeError(f'Missing acquired scan {sid}/{pid}')
   path=aq['_path'];m=meas.get((rid,pid,sid));
   if m is None:raise RuntimeError(f'Missing measurement {rid}/{pid}/{sid}')
  fsha=sha(path);fsize=path.stat().st_size
  with fits.open(path,mode='readonly',memmap=True,lazy_load_hdus=True,do_not_scale_image_data=True,ignore_missing_end=True) as hd:
   data=hd[0].data;w=choose_wcs(hd[0].header);scale=pixscale(w)
   if science:
    # v083b operational repair: some frozen v075 endpoint rows have blank
    # *_x_global/*_y_global provenance fields. Center the science panel on
    # the exact frozen endpoint sky coordinate instead, projected through
    # this science scan's celestial WCS. This changes no candidate identity,
    # panel selection, sky coordinate, crop size, stretch, or interpretation.
    ra=num(tr.get(f'{ep}_ra_deg'));dec=num(tr.get(f'{ep}_dec_deg'))
    if ra is None or dec is None:raise RuntimeError(f'Missing frozen v075 science endpoint sky coordinate for candidate {rid} endpoint {ep}')
    pix=np.asarray(w.all_world2pix([[ra,dec]],0),dtype=float)[0]
    if not np.all(np.isfinite(pix)):raise RuntimeError(f'Non-finite science endpoint WCS pixel for candidate {rid} endpoint {ep}')
    cx,cy=float(pix[0]),float(pix[1])
   else:
    t=targets[rid];target=SkyCoord(float(t['registered_target_ra_deg'])*u.deg,float(t['registered_target_dec_deg'])*u.deg,frame='icrs');cx,cy=target_pixel(m,target,w)
   context,_,_,lxc,lyc=cut(data,cx,cy,CONTEXT,scale);zoom,_,_,lxz,lyz=cut(data,cx,cy,ZOOM,scale)
  d=OUT/f'candidate_{rid}'/'panels';d.mkdir(parents=True,exist_ok=True);base=f'{i:03d}_{safe(panel["panel_role"])}_plate{pid}'+(f'_scan{sid}' if sid is not None else '')
  nc=d/f'{base}_context_raw.npy';nz=d/f'{base}_zoom_raw.npy';np.save(nc,np.asarray(context));np.save(nz,np.asarray(zoom));pc=d/f'{base}_context.png';pz=d/f'{base}_zoom.png';ph=d/f'{base}_zoom_highpass.png';title=f'candidate {rid} | {panel["panel_role"]} | plate {pid}';save_png(pc,context,lxc,lyc,title+f' | context {CONTEXT:.0f}"');save_png(pz,zoom,lxz,lyz,title+f' | zoom {ZOOM:.0f}"');save_png(ph,zoom,lxz,lyz,title+' | high-pass',True)
  rec={**panel,'source_fits_path':str(path.relative_to(ROOT)).replace('\\','/'),'source_fits_size_bytes':fsize,'source_fits_sha256':fsha,'pixel_scale_arcsec':scale,'target_pixel_x':cx,'target_pixel_y':cy,'context_npy':str(nc.relative_to(OUT)).replace('\\','/'),'context_npy_sha256':sha(nc),'zoom_npy':str(nz.relative_to(OUT)).replace('\\','/'),'zoom_npy_sha256':sha(nz),'context_png':str(pc.relative_to(OUT)).replace('\\','/'),'context_png_sha256':sha(pc),'zoom_png':str(pz.relative_to(OUT)).replace('\\','/'),'zoom_png_sha256':sha(pz),'zoom_highpass_png':str(ph.relative_to(OUT)).replace('\\','/'),'zoom_highpass_png_sha256':sha(ph),'registration_mode':m.get('registration_mode','SCIENCE'),'registration_refs':m.get('registration_refs',''),'registration_shift_east_arcsec':m.get('registration_shift_east_arcsec',''),'registration_shift_north_arcsec':m.get('registration_shift_north_arcsec',''),'strict_native_recurrence':m.get('strict_native_recurrence',''),'diagnostic_native_peak_count':m.get('diagnostic_native_peak_count',''),'closest_corrected_peak_sep_arcsec':m.get('closest_corrected_peak_sep_arcsec',''),'forced_target_residual_sigma':m.get('forced_target_residual_sigma',''),'sensitivity_qualified_negative':m.get('sensitivity_qualified_negative',''),'worst_sixway_90pct_recovery_snr':m.get('worst_sixway_90pct_recovery_snr','')}
  manifest.append(rec);bycand[rid].append(rec);print(f'Rendered {i}/{len(selected)} candidate={rid} role={panel["panel_role"]} plate={pid} gap_h={panel.get("gap_hours","")}')
 write_csv(OUT_MAN,manifest)
 for rid in SURV:
  t=targets[rid];e=evid[rid];body=["<!doctype html><html><head><meta charset='utf-8'><style>body{font-family:Arial,sans-serif;max-width:1500px;margin:20px auto;padding:0 20px}table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #aaa;padding:6px;vertical-align:top}.panel{border:1px solid #aaa;padding:10px;margin:18px 0}.imgs{display:flex;flex-wrap:wrap;gap:10px}.imgs img{width:31%;min-width:300px;height:auto}code{font-size:.9em}</style></head><body>",f'<h1>Pair 17 candidate {rid}</h1>',f'<p>Registered RA {html.escape(str(t["registered_target_ra_deg"]))}, Dec {html.escape(str(t["registered_target_dec_deg"]))}; v080 qualified negatives {html.escape(str(e.get("v080_sensitivity_qualified_negative_physical_plate_count","")))}</p>']
  for r in bycand[rid]:
   body += ["<div class='panel'>",f'<h2>{html.escape(str(r["panel_role"]))}</h2>',f'<p>{html.escape(str(r.get("observatory","")))} | plate {r.get("physical_plate_id","")} | relation {html.escape(str(r.get("relation_to_common_overlap","")))} | gap {html.escape(str(r.get("gap_hours","")))} h</p>',f'<p>registration={html.escape(str(r.get("registration_mode","")))} refs={html.escape(str(r.get("registration_refs","")))} | closest peak={html.escape(str(r.get("closest_corrected_peak_sep_arcsec","")))} arcsec | sensitivity-qualified negative={html.escape(str(r.get("sensitivity_qualified_negative","")))}</p>',f'<p><code>{html.escape(str(r["source_fits_path"]))}</code><br>SHA256 {html.escape(str(r["source_fits_sha256"]))}</p>',"<div class='imgs'>",f'<img src="{html.escape(str(r["context_png"]))}">',f'<img src="{html.escape(str(r["zoom_png"]))}">',f'<img src="{html.escape(str(r["zoom_highpass_png"]))}">',"</div></div>"]
  body.append('</body></html>');(OUT/f'candidate_{rid}'/'index.html').write_text('\n'.join(body),encoding='utf-8')
 links=[f'<li><a href="candidate_{rid}/index.html">candidate {rid}</a> — v080 qualified negatives: {html.escape(str(evid[rid].get("v080_sensitivity_qualified_negative_physical_plate_count","")))}; close-time: {html.escape(str(evid[rid].get("close_time_classes","NONE") or "NONE"))}</li>' for rid in SURV]
 OUT_INDEX.write_text("<!doctype html><html><head><meta charset='utf-8'><title>Pair 17 v083 dossiers</title></head><body><h1>Pair 17 standardized manual dossiers v083</h1><p>Panel selection/rendering were frozen before visual inspection; no disposition changes.</p><ul>"+'\n'.join(links)+"</ul></body></html>",encoding='utf-8')
 report={'status':'COMPLETE','analysis_kind':'pair17_standardized_manual_dossiers_v083','contract_sha256':EXPECTED_CONTRACT_SHA,'operational_repair':'v083b: retain v083a stdlib PNG repair; replace blank science *_x_global/*_y_global fields with frozen v075 endpoint RA/Dec projected through exact science-scan WCS','original_v083_runner_sha256':'874657babdf16cd40e4ec8e381bc78b1f8814a86212b6b7abda8ba0afe520296','parent_v083a_runner_sha256':'7b33d6845829f9de4a279ef04510ecc96bce3fcaa2bc3076ba7d8215bb1d28f9','scientific_contract_changed_by_v083b':False,'population':{'candidates':6,'candidate_ids':SURV,'population_label':'PRIMARY_424'},'selection':{'panels_total':len(selected),'science_panels':sum('SCIENCE_' in r['panel_role'] for r in selected),'close_time_panels':sum('V082_CLOSE_TIME' in r['panel_role'] for r in selected),'comparison_negative_panels':sum('QUALIFIED_NEGATIVE' in r['panel_role'] for r in selected)},'rendering':{'context_width_arcsec':CONTEXT,'zoom_width_arcsec':ZOOM,'raw_percentiles':[PLO,PHI],'highpass_background_sigma_px':BGSIG,'highpass_clip_sigma':HPCLIP,'grayscale_only':True},'guards':{'network_calls':0,'new_scan_downloads':0,'threshold_retuning':False,'candidate_disposition_changes':False,'manual_interpretation_during_generation':False},'outputs':{'index_html':str(OUT_INDEX.relative_to(ROOT)).replace('\\','/'),'selection_csv':str(OUT_SEL.relative_to(ROOT)).replace('\\','/'),'panel_manifest_csv':str(OUT_MAN.relative_to(ROOT)).replace('\\','/')}};write_json(OUT_JSON,report)
 print('='*120);print('v083b STANDARDIZED MANUAL DOSSIERS COMPLETE');print('Candidates: 6');print('Panels rendered:',len(selected));print('Root index:',OUT_INDEX);print('Disposition changes: NONE');print('STAGE STATUS: COMPLETE')
if __name__=='__main__':main()
