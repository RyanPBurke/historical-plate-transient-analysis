#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import argparse,csv,hashlib,json,math,re,sys

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'research'/'prospective_freezes'/'applause_dr4_fragment_aware_cross_site_opportunity_census_contract_v094h.json'
PROVENANCE=ROOT/'research'/'prospective_freezes'/'applause_dr4_fragment_aware_cross_site_opportunity_census_parent_provenance_v094h.json'
EXPECTED_CONTRACT_SHA='4f6504aa088c90e756c6feadccf57a89998ef571f7ed792686ba5d4dad8ed0b9'
RESULT=ROOT/'results'/'applause_dr4_fragment_aware_cross_site_opportunity_census_v094h'
MAX_GAP=900.0
SPUTNIK=datetime(1957,10,4,19,28,34,tzinfo=timezone.utc)
KNOWN_V093E_SITES={
 'Dr. Remeis-Observatory, Bamberg, Germany','Hamburg-Bergedorf, Germany','Bonn, Germany',
 'Castel Gandolfo, Italy','Boyden Observatory, Bloemfontein, South Africa','Potsdam-Telegrafenberg',
 'Mount John Observatory, Lake Tekapo, New Zealand'
}

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()

def log(s=''): print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
def fnum(v):
 try:
  x=float(str(v if v is not None else '').strip()); return x if math.isfinite(x) else None
 except:return None
def inum(v):
 x=fnum(v)
 if x is None:return None
 r=int(round(x)); return r if abs(x-r)<1e-9 else None
def bval(v):return str(v or '').strip().lower() in {'1','true','yes'}
def norm_site(v):
 s=re.sub(r'[^a-z0-9]+',' ',str(v or '').strip().lower()); return ' '.join(s.split())
def parse_dt(v):
 s=str(v or '').strip().replace('Z','+00:00')
 if not s:return None
 try:d=datetime.fromisoformat(s)
 except:return None
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.astimezone(timezone.utc)
def iso(d):return '' if d is None else d.isoformat()
def parse_poly(v):
 nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ''))]
 if len(nums)<8:return None
 nums=nums[-8:]; p=[(nums[i]%360.0,nums[i+1]) for i in range(0,8,2)]
 return None if any(not(-90<=d<=90) for _,d in p) else p
def angsep(ra1,de1,ra2,de2):
 r1,r2=math.radians(ra1),math.radians(ra2); d1,d2=math.radians(de1),math.radians(de2)
 c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
 return math.degrees(math.acos(max(-1,min(1,c))))
def hav(lat1,lon1,lat2,lon2):
 if None in (lat1,lon1,lat2,lon2):return None
 p1,p2=map(math.radians,(lat1,lat2)); dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
 a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 6371.0088*2*math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))
def corrected_coords(site,lon,lat):
 if lon is None or lat is None:return None,None,'MISSING_COORDS'
 if site=='Dr. Remeis-Observatory, Bamberg, Germany': return lat,lon,'V093E_VALIDATED_SWAP'
 return lon,lat,('V093E_VALIDATED_NORMAL' if site in KNOWN_V093E_SITES else 'SCHEMA_FIELDS_AS_NAMED_NOT_V093E_SITE_VALIDATED')
def baseline_band(d):
 if d is None:return 'UNKNOWN'
 if d<10:return 'LT10'
 if d<50:return 'GE10_LT50'
 if d<100:return 'GE50_LT100'
 if d<500:return 'GE100_LT500'
 if d<1000:return 'GE500_LT1000'
 return 'GE1000'

def gnomonic(poly,ra0,dec0):
 r0=math.radians(ra0); d0=math.radians(dec0); out=[]
 for ra,dec in poly:
  r=math.radians(ra); d=math.radians(dec); dr=(r-r0+math.pi)%(2*math.pi)-math.pi
  cosc=math.sin(d0)*math.sin(d)+math.cos(d0)*math.cos(d)*math.cos(dr)
  if cosc<=1e-8:return None
  x=math.cos(d)*math.sin(dr)/cosc
  y=(math.cos(d0)*math.sin(d)-math.sin(d0)*math.cos(d)*math.cos(dr))/cosc
  out.append((x,y))
 return out
def area(poly):
 if not poly or len(poly)<3:return 0.0
 return abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2)
def signed_area(poly):
 return sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2
def clip_convex(subject,clip):
 if not subject or not clip:return []
 cp=clip[:] if signed_area(clip)>=0 else list(reversed(clip)); out=subject[:]
 def inside(p,a,b):return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])>=-1e-14
 def inter(s,e,a,b):
  x1,y1=s;x2,y2=e;x3,y3=a;x4,y4=b
  den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
  if abs(den)<1e-18:return e
  px=((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/den
  py=((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/den
  return (px,py)
 for i in range(len(cp)):
  a,b=cp[i],cp[(i+1)%len(cp)]; inp=out; out=[]
  if not inp:break
  s=inp[-1]
  for e in inp:
   ie,is_=inside(e,a,b),inside(s,a,b)
   if ie:
    if not is_:out.append(inter(s,e,a,b))
    out.append(e)
   elif is_:out.append(inter(s,e,a,b))
   s=e
 return out
def poly_intersection_metrics(pa,pb):
 # Shared tangent point from unit-vector mean of polygon vertices.
 pts=pa+pb; xs=ys=zs=0.0
 for ra,dec in pts:
  r,d=math.radians(ra),math.radians(dec); c=math.cos(d); xs+=c*math.cos(r);ys+=c*math.sin(r);zs+=math.sin(d)
 ra0=math.degrees(math.atan2(ys,xs))%360; dec0=math.degrees(math.atan2(zs,math.hypot(xs,ys)))
 a=gnomonic(pa,ra0,dec0); b=gnomonic(pb,ra0,dec0)
 if not a or not b:return None
 aa,ab=area(a),area(b); inter=clip_convex(a,b); ai=area(inter)
 if ai<=1e-14 or aa<=0 or ab<=0:return {'positive':False,'area_deg2':0.0,'frac_a':0.0,'frac_b':0.0,'frac_smaller':0.0}
 conv=(180/math.pi)**2
 return {'positive':True,'area_deg2':ai*conv,'frac_a':ai/aa,'frac_b':ai/ab,'frac_smaller':ai/min(aa,ab)}

def interval_metric(a,b):
 s1,e1=a['start'],a['end'];s2,e2=b['start'],b['end']
 st=max(s1,s2); en=min(e1,e2)
 if en>st:return 0.0,{'start_utc':iso(st),'end_utc':iso(en),'duration_seconds':(en-st).total_seconds(),'a_fragment':a['label'],'b_fragment':b['label']}
 if e1<=s2:return (s2-e1).total_seconds(),None
 return (s1-e2).total_seconds(),None

def self_test():
 t=parse_dt('1955-01-01T00:00:00+00:00'); a={'start':t,'end':t.replace(minute=10),'label':'a'}; b={'start':t.replace(minute=5),'end':t.replace(minute=15),'label':'b'}
 g,o=interval_metric(a,b); assert g==0 and abs(o['duration_seconds']-300)<1e-6
 p1=[(0,0),(1,0),(1,1),(0,1)];p2=[(.5,.5),(1.5,.5),(1.5,1.5),(.5,1.5)];m=poly_intersection_metrics(p1,p2);assert m and m['positive'] and m['frac_smaller']>0.2
 assert norm_site('  Bonn, Germany ')=='bonn germany'; assert corrected_coords('Dr. Remeis-Observatory, Bamberg, Germany',49.9,10.9)[0]==10.9
 print('v094h self-test PASS');return 0

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
 if a.self_test:return self_test()
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit('v094h contract SHA mismatch')
 if not PROVENANCE.is_file():raise SystemExit('Missing frozen v094h parent provenance')
 prov=json.loads(PROVENANCE.read_text(encoding='utf-8'))
 for k in ('v094d_master','v094d_report','v093d_plate_cache'):
  rec=prov[k];p=ROOT/rec['path']
  if not p.is_file() or sha(p)!=rec['sha256']:raise SystemExit(f'Frozen parent provenance mismatch: {k}')
 for rec in prov['v094d_normalized'].values():
  p=ROOT/rec['path']
  if not p.is_file() or sha(p)!=rec['sha256']:raise SystemExit(f'Frozen v094d normalized input mismatch: {p}')
 master_path=ROOT/prov['v094d_master']['path']; plate_path=ROOT/prov['v093d_plate_cache']['path']; scan_path=ROOT/prov['v094d_normalized']['scan_full']['path']; sol_path=ROOT/prov['v094d_normalized']['solution_full']['path']
 log('Frozen v094h parent inputs verified')
 plate={}
 with plate_path.open('r',encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   pid=inum(r.get('plate_id'))
   if pid is None:continue
   site=str(r.get('site_name') or '').strip();lon=fnum(r.get('site_longitude'));lat=fnum(r.get('site_latitude'));clon,clat,crule=corrected_coords(site,lon,lat)
   plate[pid]={'site':site,'site_key':norm_site(site),'observatory':str(r.get('observatory') or '').strip(),'lon':clon,'lat':clat,'coord_rule':crule,'archive_id':inum(r.get('archive_id'))}
 valid_scans=defaultdict(set)
 with scan_path.open('r',encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   pid,sid=inum(r.get('plate_id')),inum(r.get('scan_id'))
   if pid is not None and sid is not None and str(r.get('filename_scan') or '').strip():valid_scans[pid].add(sid)
 sols=defaultdict(list)
 with sol_path.open('r',encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   pid,sid=inum(r.get('plate_id')),inum(r.get('scan_id'));poly=parse_poly(r.get('stc_polygon'))
   if pid is None or sid is None or sid not in valid_scans.get(pid,set()) or poly is None:continue
   ra,dec=fnum(r.get('ra_icrs')),fnum(r.get('dec_icrs'))
   if ra is None or dec is None:continue
   sols[pid].append({'solution_id':inum(r.get('solution_id')),'scan_id':sid,'ra':ra,'dec':dec,'fov1':fnum(r.get('fov1')),'fov2':fnum(r.get('fov2')),'num_xmatch':inum(r.get('num_xmatch')) or 0,'poly':poly})
 holds=Counter(); exposures={}; master_rows=0; timing_status=Counter()
 eligible_status={'PROVISIONAL_PARENT_INTERVAL_NO_EXPLICIT_WARNING','OPPORTUNITY_TIMING_SUPPORTED_FEATURE_FRAGMENT_UNIDENTIFIED'}
 with master_path.open('r',encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   master_rows+=1; status=str(r.get('timing_confirmatory_status') or '').strip();timing_status[status]+=1
   if status not in eligible_status:holds['TIMING_NOT_CONFIRMATORY_ELIGIBLE']+=1;continue
   eid,pid=inum(r.get('exposure_id')),inum(r.get('plate_id'));ra,dec=fnum(r.get('ra_icrs')),fnum(r.get('dec_icrs'))
   if None in (eid,pid,ra,dec):holds['MISSING_PARENT_ID_OR_COORDINATES']+=1;continue
   pm=plate.get(pid)
   if pm is None:holds['MISSING_PLATE_METADATA']+=1;continue
   if not pm['site_key']:holds['AMBIGUOUS_SITE_IDENTITY']+=1;continue
   cand=[]
   for s in sols.get(pid,[]):
    sep=angsep(ra,dec,s['ra'],s['dec']);diag=None if s['fov1'] is None or s['fov2'] is None else math.hypot(s['fov1'],s['fov2']);plaus=True if diag is None else sep<=max(1.0,.75*diag)
    cand.append((sep,-s['num_xmatch'],s['solution_id'] if s['solution_id'] is not None else 10**18,plaus,s,diag))
   if not cand:holds['NO_VALID_SCAN_SOLUTION_POLYGON']+=1;continue
   cand.sort(key=lambda x:(x[0],x[1],x[2]));sep,_,_,plaus,s,diag=cand[0]
   if not plaus:holds['SOLUTION_ASSOCIATION_IMPLAUSIBLE']+=1;continue
   try:jj=json.loads(str(r.get('fragment_intervals_json') or '[]'))
   except:jj=[]
   iv=[]
   for j,x in enumerate(jj):
    st,en=parse_dt(x.get('start_utc')),parse_dt(x.get('end_utc'))
    if st and en and en>st:iv.append({'start':st,'end':en,'label':str(x.get('subexposure_id') or x.get('kind') or j)})
   if not iv:holds['NO_SUPPORTED_FRAGMENT_INTERVALS']+=1;continue
   exposures[eid]={'eid':eid,'pid':pid,'archive_id':inum(r.get('archive_id')),'site':pm['site'],'site_key':pm['site_key'],'observatory':pm['observatory'],'lon':pm['lon'],'lat':pm['lat'],'coord_rule':pm['coord_rule'],'intervals':iv,'timing_status':status,'num_sub':inum(r.get('num_sub_parsed')),'poly':s['poly'],'solution_id':s['solution_id'],'scan_id':s['scan_id'],'solution_sep_deg':sep,'ut_mid':parse_dt(r.get('ut_mid_raw'))}
 if master_rows!=139539:raise SystemExit(f'Expected 139539 master exposures, observed {master_rows}')
 log(f'Population preflight: {len(exposures):,} timing/site/footprint-eligible exposures; holds={dict(holds)}')
 frags=[]
 for e in exposures.values():
  for x in e['intervals']:frags.append((x['start'],x['end'],e['eid'],x))
 frags.sort(key=lambda z:(z[0],z[1],z[2])); active=[]; pairs={}; same_site_pairs=set()
 for idx,(st,en,eid,frag) in enumerate(frags,1):
  cutoff=st.timestamp()-MAX_GAP; active=[q for q in active if q[1].timestamp()>=cutoff]
  ea=exposures[eid]
  for ast,aen,oeid,ofrag in active:
   if oeid==eid:continue
   eb=exposures[oeid]; key=(oeid,eid) if oeid<eid else (eid,oeid)
   if ea['site_key']==eb['site_key']:
    # Context only; a pair may be encountered through multiple fragment combinations.
    same_site_pairs.add(key);continue
   gap,ov=interval_metric(frag,ofrag)
   if ov is not None:
    ov['exposure_current']=eid; ov['exposure_active']=oeid
   if gap>MAX_GAP+1e-9:continue
   rec=pairs.setdefault(key,{'min_gap':1e99,'overlaps':[],'fragment_pair_count':0});rec['fragment_pair_count']+=1
   if ov is not None:rec['overlaps'].append(ov);rec['min_gap']=0.0
   elif gap<rec['min_gap']:rec['min_gap']=gap
  active.append((st,en,eid,frag))
  if idx%10000==0:log(f'fragment time sweep: {idx:,}/{len(frags):,}; distinct-site temporal pairs={len(pairs):,}')
 log(f'Temporal sweep complete: {len(pairs):,} distinct-site exposure pairs within <=15 min/overlap before sky intersection')
 RESULT.mkdir(parents=True,exist_ok=True); outp=RESULT/'applause_dr4_fragment_aware_cross_site_opportunities_v094h.csv'
 fields=['pair_id','exposure_a','exposure_b','plate_a','plate_b','archive_a','archive_b','site_a','site_b','observatory_a','observatory_b','site_coord_rule_a','site_coord_rule_b','site_separation_km_diagnostic','site_separation_band','timing_bin','min_fragment_gap_seconds','fragment_overlap_intervals_json','fragment_overlap_count','total_fragment_overlap_seconds','max_fragment_overlap_seconds','fragment_pair_count_evaluated','timing_status_a','timing_status_b','num_sub_a','num_sub_b','parent_midpoint_separation_seconds_secondary','solution_id_a','solution_id_b','scan_id_a','scan_id_b','solution_association_sep_deg_a','solution_association_sep_deg_b','common_tangent_area_deg2','common_fraction_of_a','common_fraction_of_b','common_fraction_of_smaller','common_ge50pct_smaller_diagnostic','gate_le5min','gate_le10min','gate_le15min','in_1951_1955','pre_sputnik','epoch_label']
 counts=Counter();baseline_counts=Counter();sitepairs=Counter();era_counts=Counter();geometry_holds=Counter();rows_out=0
 with outp.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for i,(key,pr) in enumerate(sorted(pairs.items()),1):
   ea,eb=exposures[key[0]],exposures[key[1]];m=poly_intersection_metrics(ea['poly'],eb['poly'])
   if not m or not m['positive']:geometry_holds['NO_POSITIVE_SKY_FOOTPRINT_INTERSECTION']+=1;continue
   ovs=pr['overlaps']; gap=0.0 if ovs else pr['min_gap']
   if ovs:bin_='OVERLAP'
   elif gap<=300:bin_='GT0_LE5MIN'
   elif gap<=600:bin_='GT5_LE10MIN'
   else:bin_='GT10_LE15MIN'
   d=hav(ea['lat'],ea['lon'],eb['lat'],eb['lon']);bb=baseline_band(d)
   starts=[x['start'] for x in ea['intervals']+eb['intervals']]; ends=[x['end'] for x in ea['intervals']+eb['intervals']]; tmin=min(starts);tmax=max(ends)
   in5155=(tmin>=datetime(1951,1,1,tzinfo=timezone.utc) and tmax<datetime(1956,1,1,tzinfo=timezone.utc));pre=tmax<SPUTNIK;epoch='IN_1951_1955' if in5155 else ('PRE_SPUTNIK' if pre else 'POST_SPUTNIK_OR_SAME_LAUNCH_DATE')
   midsep='' if ea['ut_mid'] is None or eb['ut_mid'] is None else abs((ea['ut_mid']-eb['ut_mid']).total_seconds())
   total=sum(x['duration_seconds'] for x in ovs);mx=max([x['duration_seconds'] for x in ovs],default=0.0)
   row={'pair_id':f"{key[0]}|{key[1]}",'exposure_a':key[0],'exposure_b':key[1],'plate_a':ea['pid'],'plate_b':eb['pid'],'archive_a':ea['archive_id'],'archive_b':eb['archive_id'],'site_a':ea['site'],'site_b':eb['site'],'observatory_a':ea['observatory'],'observatory_b':eb['observatory'],'site_coord_rule_a':ea['coord_rule'],'site_coord_rule_b':eb['coord_rule'],'site_separation_km_diagnostic':'' if d is None else f'{d:.6f}','site_separation_band':bb,'timing_bin':bin_,'min_fragment_gap_seconds':f'{gap:.6f}','fragment_overlap_intervals_json':json.dumps(ovs,separators=(',',':'),sort_keys=True),'fragment_overlap_count':len(ovs),'total_fragment_overlap_seconds':f'{total:.6f}','max_fragment_overlap_seconds':f'{mx:.6f}','fragment_pair_count_evaluated':pr['fragment_pair_count'],'timing_status_a':ea['timing_status'],'timing_status_b':eb['timing_status'],'num_sub_a':ea['num_sub'],'num_sub_b':eb['num_sub'],'parent_midpoint_separation_seconds_secondary':midsep,'solution_id_a':ea['solution_id'],'solution_id_b':eb['solution_id'],'scan_id_a':ea['scan_id'],'scan_id_b':eb['scan_id'],'solution_association_sep_deg_a':f"{ea['solution_sep_deg']:.8f}",'solution_association_sep_deg_b':f"{eb['solution_sep_deg']:.8f}",'common_tangent_area_deg2':f"{m['area_deg2']:.10f}",'common_fraction_of_a':f"{m['frac_a']:.10f}",'common_fraction_of_b':f"{m['frac_b']:.10f}",'common_fraction_of_smaller':f"{m['frac_smaller']:.10f}",'common_ge50pct_smaller_diagnostic':m['frac_smaller']>=.5,'gate_le5min':(bin_ in ('OVERLAP','GT0_LE5MIN')),'gate_le10min':(bin_ in ('OVERLAP','GT0_LE5MIN','GT5_LE10MIN')),'gate_le15min':True,'in_1951_1955':in5155,'pre_sputnik':pre,'epoch_label':epoch}
   w.writerow(row);rows_out+=1;counts[bin_]+=1;baseline_counts[bb]+=1;sitepairs[' | '.join(sorted((ea['site'],eb['site'])))]+=1;era_counts[epoch]+=1
   if i%5000==0:log(f'sky-footprint census: {i:,}/{len(pairs):,} temporal pairs; retained={rows_out:,}')
 report={'status':'COMPLETE','analysis_kind':'applause_dr4_fragment_aware_cross_site_opportunity_census_v094h','contract_sha256':EXPECTED_CONTRACT_SHA,'parent_provenance_sha256':sha(PROVENANCE),'master_exposure_rows':master_rows,'timing_confirmatory_status_counts':dict(timing_status),'exposure_preflight_holds':dict(holds),'eligible_exposures_with_site_and_footprint':len(exposures),'continuous_fragment_records':len(frags),'same_site_temporal_pair_context_count':len(same_site_pairs),'distinct_site_temporal_pairs_before_sky_intersection':len(pairs),'sky_intersection_holds':dict(geometry_holds),'opportunity_rows':rows_out,'exclusive_timing_bin_counts':dict(counts),'cumulative_gate_counts':{'LE5MIN_INCLUDING_OVERLAP':counts['OVERLAP']+counts['GT0_LE5MIN'],'LE10MIN_INCLUDING_OVERLAP':counts['OVERLAP']+counts['GT0_LE5MIN']+counts['GT5_LE10MIN'],'LE15MIN_INCLUDING_OVERLAP':rows_out},'site_baseline_band_counts_diagnostic_only':dict(baseline_counts),'epoch_counts':dict(era_counts),'top_site_pairs':sitepairs.most_common(30),'minimum_site_distance_exclusion_applied':False,'candidate_csv_reads':0,'source_catalog_queries':0,'pixel_reads':0,'detector_runs':0,'interpretive_stop':'Interpret denominator, site ambiguity, timing and geometry holds before any source-level search.','output_hashes':{outp.name:sha(outp)}}
 rp=RESULT/'applause_dr4_fragment_aware_cross_site_opportunity_census_v094h.json';rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 man=RESULT/'v094h_output_manifest.sha256';man.write_text(f"{sha(outp)}  {outp.name}\n{sha(rp)}  {rp.name}\n",encoding='utf-8')
 log('');print('='*96);print('v094h FRAGMENT-AWARE CROSS-SITE OPPORTUNITY CENSUS COMPLETE');print('='*96)
 print(f'Master exposure rows:                  {master_rows}')
 print(f'Eligible site/timing/footprint exposures: {len(exposures)}')
 print(f'Continuous fragment records:           {len(frags)}')
 print(f'Distinct-site temporal pairs <=15 min: {len(pairs)}')
 print(f'Positive sky-footprint opportunities:  {rows_out}')
 print(f'Exclusive timing bins:                 {dict(counts)}')
 print(f'Cumulative <=5 min:                    {report["cumulative_gate_counts"]["LE5MIN_INCLUDING_OVERLAP"]}')
 print(f'Cumulative <=10 min:                   {report["cumulative_gate_counts"]["LE10MIN_INCLUDING_OVERLAP"]}')
 print(f'Cumulative <=15 min:                   {rows_out}')
 print(f'Baseline bands (diagnostic only):      {dict(baseline_counts)}')
 print(f'Epoch counts:                          {dict(era_counts)}')
 print(f'Same-site temporal context pairs:      {len(same_site_pairs)}')
 print('Minimum site-distance cutoff applied:  False')
 print('STOP: inspect aggregate opportunity/hold structure before any source search, registration, pixels, or candidates.')
 return 0
if __name__=='__main__':raise SystemExit(main())
