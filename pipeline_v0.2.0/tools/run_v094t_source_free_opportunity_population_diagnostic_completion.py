#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import argparse,csv,hashlib,json,math,re,os
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'research'/'prospective_freezes'/'v094t_source_free_opportunity_population_diagnostic_completion_contract.json'
PROV=ROOT/'research'/'prospective_freezes'/'v094s_source_free_opportunity_population_parent_provenance.json'
EXPECTED='5a1758652f9f27b808339561674a0183affa202789e1774bd89dc9c4296f420e'
RESULT=ROOT/'results'/'applause_dr4_source_free_opportunity_population_repair_v094t'
MAX_GAP=900.0;TOL=0.001
SPUTNIK=datetime(1957,10,4,19,28,34,tzinfo=timezone.utc)
KNOWN_V093E_SITES={'Dr. Remeis-Observatory, Bamberg, Germany','Hamburg-Bergedorf, Germany','Bonn, Germany','Castel Gandolfo, Italy','Boyden Observatory, Bloemfontein, South Africa','Potsdam-Telegrafenberg','Mount John Observatory, Lake Tekapo, New Zealand'}
EXPECTED_OLD_BINS={'OVERLAP':1081,'GT0_LE5MIN':159,'GT5_LE10MIN':160,'GT10_LE15MIN':141}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def rows(p):
 with Path(p).open('r',encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)
def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
def fnum(v):
 try:
  x=float(str(v if v is not None else '').strip());return x if math.isfinite(x) else None
 except:return None
def inum(v):
 x=fnum(v)
 if x is None:return None
 q=int(round(x));return q if abs(x-q)<1e-9 else None
def norm_site(v):return ' '.join(re.sub(r'[^a-z0-9]+',' ',str(v or '').strip().lower()).split())
def parse_dt(v):
 s=str(v or '').strip().replace('Z','+00:00')
 if not s:return None
 try:d=datetime.fromisoformat(s)
 except:return None
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.astimezone(timezone.utc)
def iso(d):return '' if d is None else d.isoformat()
def parse_poly(v):
 a=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ''))]
 if len(a)<8:return None
 a=a[-8:];p=[(a[i]%360,a[i+1]) for i in range(0,8,2)]
 return None if any(not(-90<=d<=90) for _,d in p) else p
def angsep(ra1,de1,ra2,de2):
 r1,r2=math.radians(ra1),math.radians(ra2);d1,d2=math.radians(de1),math.radians(de2)
 c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
 return math.degrees(math.acos(max(-1,min(1,c))))
def hav(lat1,lon1,lat2,lon2):
 if None in (lat1,lon1,lat2,lon2):return None
 p1,p2=map(math.radians,(lat1,lat2));dp=math.radians(lat2-lat1);dl=math.radians(lon2-lon1)
 a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 6371.0088*2*math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))
def corrected_coords(site,lon,lat):
 if lon is None or lat is None:return None,None,'MISSING_COORDS'
 if site=='Dr. Remeis-Observatory, Bamberg, Germany':return lat,lon,'V093E_VALIDATED_SWAP'
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
 r0=math.radians(ra0);d0=math.radians(dec0);out=[]
 for ra,dec in poly:
  r=math.radians(ra);d=math.radians(dec);dr=(r-r0+math.pi)%(2*math.pi)-math.pi
  cosc=math.sin(d0)*math.sin(d)+math.cos(d0)*math.cos(d)*math.cos(dr)
  if cosc<=1e-8:return None
  out.append((math.cos(d)*math.sin(dr)/cosc,(math.cos(d0)*math.sin(d)-math.sin(d0)*math.cos(d)*math.cos(dr))/cosc))
 return out
def area(poly):
 if not poly or len(poly)<3:return 0.0
 return abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2)
def signed_area(poly):return sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2
def clip_convex(subject,clip):
 if not subject or not clip:return []
 cp=clip[:] if signed_area(clip)>=0 else list(reversed(clip));out=subject[:]
 def inside(p,a,b):return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])>=-1e-14
 def inter(s,e,a,b):
  x1,y1=s;x2,y2=e;x3,y3=a;x4,y4=b;den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
  if abs(den)<1e-18:return e
  return (((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/den,((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/den)
 for i in range(len(cp)):
  a,b=cp[i],cp[(i+1)%len(cp)];inp=out;out=[]
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
 pts=pa+pb;xs=ys=zs=0.0
 for ra,dec in pts:
  r,d=math.radians(ra),math.radians(dec);c=math.cos(d);xs+=c*math.cos(r);ys+=c*math.sin(r);zs+=math.sin(d)
 ra0=math.degrees(math.atan2(ys,xs))%360;dec0=math.degrees(math.atan2(zs,math.hypot(xs,ys)))
 a=gnomonic(pa,ra0,dec0);b=gnomonic(pb,ra0,dec0)
 if not a or not b:return None
 aa,ab=area(a),area(b);inter=clip_convex(a,b);ai=area(inter)
 if ai<=1e-14 or aa<=0 or ab<=0:return {'positive':False,'area_deg2':0.0,'frac_a':0.0,'frac_b':0.0,'frac_smaller':0.0}
 conv=(180/math.pi)**2;return {'positive':True,'area_deg2':ai*conv,'frac_a':ai/aa,'frac_b':ai/ab,'frac_smaller':ai/min(aa,ab)}
def legacy_geometry_fields(pa,pb,metric_fn=None):
 fn=metric_fn or poly_intersection_metrics;m=fn(pa,pb)
 if m is None:return {'legacy_infinity_geometry_status':'LEGACY_TANGENT_UNRESOLVED','old_common_positive_infinity_footprint':'','old_common_tangent_area_deg2':'','old_common_fraction_of_a':'','old_common_fraction_of_b':'','old_common_fraction_of_smaller':''}
 p=bool(m['positive'])
 return {'legacy_infinity_geometry_status':('LEGACY_TANGENT_POSITIVE' if p else 'LEGACY_TANGENT_NONPOSITIVE'),'old_common_positive_infinity_footprint':p,'old_common_tangent_area_deg2':f"{m['area_deg2']:.10f}",'old_common_fraction_of_a':f"{m['frac_a']:.10f}",'old_common_fraction_of_b':f"{m['frac_b']:.10f}",'old_common_fraction_of_smaller':f"{m['frac_smaller']:.10f}"}
SCIENCE_FIELDS=['pair_id','exposure_a','exposure_b','plate_a','plate_b','solution_id_a','solution_id_b','scan_id_a','scan_id_b','timing_bin','min_fragment_gap_seconds','fragment_overlap_intervals_json','fragment_overlap_count','total_fragment_overlap_seconds','max_fragment_overlap_seconds','fragment_pair_count_evaluated','timing_status_a','timing_status_b','num_sub_a','num_sub_b']
def sig(r):return tuple(str(r.get(k,'')) for k in SCIENCE_FIELDS)
def interval_metric(a,b):
 s1,e1=a['start'],a['end'];s2,e2=b['start'],b['end'];st=max(s1,s2);en=min(e1,e2)
 if en>st:return 0.0,{'start_utc':iso(st),'end_utc':iso(en),'duration_seconds':(en-st).total_seconds(),'a_fragment':a['label'],'b_fragment':b['label']}
 if e1<=s2:return (s2-e1).total_seconds(),None
 return (s1-e2).total_seconds(),None
def valid_fragments(exposure,subs,eid):
 r=exposure.get(eid)
 if r is None:return 'MISSING_EXPOSURE',[]
 n=r['num_sub']
 if n is None:return 'TIMING_STRUCTURALLY_UNRESOLVED_NUM_SUB',[]
 if n>1:
  ss=subs.get(eid,[])
  if len(ss)!=n:return 'SUBEXPOSURE_COUNT_MISMATCH',[]
  ids=[q['subexposure_id'] for q in ss];nums=[q['subexposure_num'] for q in ss]
  if None in ids or len(set(ids))!=len(ids):return 'SUBEXPOSURE_ID_INVALID',[]
  if None in nums or len(set(nums))!=len(nums):return 'SUBEXPOSURE_NUM_INVALID',[]
  iv=[]
  for q in ss:
   s,e=q['start'],q['end']
   if s is None or e is None or e<=s:return 'SUBEXPOSURE_INTERVAL_INVALID',[]
   iv.append((s,e,str(q['subexposure_id'])))
  iv.sort(key=lambda q:(q[0],q[1],q[2]))
  for q1,q2 in zip(iv,iv[1:]):
   if q2[0]<q1[1]:return 'SUBEXPOSURE_INTERVALS_OVERLAP',[]
  return 'FRAGMENTS_EXPOSURE_SUB',[{'start':s,'end':e,'label':lab} for s,e,lab in iv]
 s,e=r['start'],r['end']
 if s is None or e is None or e<=s:return 'PARENT_INTERVAL_INVALID',[]
 return 'PROVISIONAL_PARENT_INTERVAL',[{'start':s,'end':e,'label':'PARENT_PROVISIONAL_CONTINUOUS'}]
def master_intervals(v):
 try:q=json.loads(str(v or '[]'))
 except:return None
 out=[]
 for x in q:
  s,e=parse_dt(x.get('start_utc')),parse_dt(x.get('end_utc'))
  if not s or not e or e<=s:return None
  out.append((s,e))
 return sorted(out)
def interval_sets_equal(a,b,tol=TOL):
 if a is None or len(a)!=len(b):return False
 aa=sorted((q['start'],q['end']) for q in a)
 for (sa,ea),(sb,eb) in zip(aa,b):
  if abs((sa-sb).total_seconds())>tol or abs((ea-eb).total_seconds())>tol:return False
 return True
def self_test():
 t=parse_dt('1955-01-01T00:00:00+00:00');a={'start':t,'end':t.replace(minute=10),'label':'a'};b={'start':t.replace(minute=5),'end':t.replace(minute=15),'label':'b'}
 g,o=interval_metric(a,b);assert g==0 and abs(o['duration_seconds']-300)<1e-9
 p1=[(0,0),(1,0),(1,1),(0,1)];p2=[(.5,.5),(1.5,.5),(1.5,1.5),(.5,1.5)];assert legacy_geometry_fields(p1,p2)['legacy_infinity_geometry_status']=='LEGACY_TANGENT_POSITIVE'
 p3=[(5,0),(6,0),(6,1),(5,1)];assert legacy_geometry_fields(p1,p3)['legacy_infinity_geometry_status']=='LEGACY_TANGENT_NONPOSITIVE'
 u=legacy_geometry_fields(p1,p2,lambda a,b:None);assert u['legacy_infinity_geometry_status']=='LEGACY_TANGENT_UNRESOLVED' and u['old_common_positive_infinity_footprint']=='' and u['old_common_tangent_area_deg2']==''
 print('v094t diagnostic-completion self-test PASS');return 0
def run():
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit('v094t contract SHA mismatch')
 if not PROV.is_file():raise SystemExit('Missing v094s parent provenance')
 p=json.loads(PROV.read_text(encoding='utf-8'))
 if p.get('status')!='PARENT_PROVENANCE_PREPARED_BEFORE_V094S_PAIRING':raise SystemExit('Bad v094s provenance')
 for k,r in p['inputs'].items():
  f=ROOT/r['path']
  if not f.is_file() or sha(f)!=r['sha256']:raise SystemExit(f'Runtime frozen input mismatch: {k}')
 path={k:ROOT/r['path'] for k,r in p['inputs'].items()}
 plate={}
 for r in rows(path['plate_site_cache']):
  pid=inum(r.get('plate_id'))
  if pid is None:continue
  site=str(r.get('site_name') or '').strip();lon,lat=fnum(r.get('site_longitude')),fnum(r.get('site_latitude'));clon,clat,crule=corrected_coords(site,lon,lat)
  plate[pid]={'site':site,'site_key':norm_site(site),'observatory':str(r.get('observatory') or '').strip(),'lon':clon,'lat':clat,'coord_rule':crule,'archive_id':inum(r.get('archive_id'))}
 valid_scans=defaultdict(set)
 for r in rows(path['scan_full']):
  pid,sid=inum(r.get('plate_id')),inum(r.get('scan_id'))
  if pid is not None and sid is not None and str(r.get('filename_scan') or '').strip():valid_scans[pid].add(sid)
 sols=defaultdict(list)
 for r in rows(path['solution_full']):
  pid,sid=inum(r.get('plate_id')),inum(r.get('scan_id'));poly=parse_poly(r.get('stc_polygon'))
  if pid is None or sid is None or sid not in valid_scans.get(pid,set()) or poly is None:continue
  ra,dec=fnum(r.get('ra_icrs')),fnum(r.get('dec_icrs'))
  if ra is None or dec is None:continue
  sols[pid].append({'solution_id':inum(r.get('solution_id')),'scan_id':sid,'ra':ra,'dec':dec,'fov1':fnum(r.get('fov1')),'fov2':fnum(r.get('fov2')),'num_xmatch':inum(r.get('num_xmatch')) or 0,'poly':poly})
 exraw={}
 for r in rows(path['exposure_full']):
  eid=inum(r.get('exposure_id'))
  if eid is not None:exraw[eid]={'num_sub':inum(r.get('num_sub')),'start':parse_dt(r.get('ut_start')),'end':parse_dt(r.get('ut_end'))}
 subs=defaultdict(list)
 for r in rows(path['exposure_sub_full']):
  eid=inum(r.get('exposure_id'))
  if eid is not None:subs[eid].append({'subexposure_id':inum(r.get('subexposure_id')),'subexposure_num':inum(r.get('subexposure_num')),'start':parse_dt(r.get('ut_start')),'end':parse_dt(r.get('ut_end'))})
 holds=Counter();timing_status=Counter();fragment_status=Counter();exposures={};master_rows=0;timing_replay_mismatch=0
 eligible_status={'PROVISIONAL_PARENT_INTERVAL_NO_EXPLICIT_WARNING','OPPORTUNITY_TIMING_SUPPORTED_FEATURE_FRAGMENT_UNIDENTIFIED'}
 for r in rows(path['v094d_master']):
  master_rows+=1;status=str(r.get('timing_confirmatory_status') or '').strip();timing_status[status]+=1
  if status not in eligible_status:holds['TIMING_NOT_CONFIRMATORY_ELIGIBLE']+=1;continue
  eid,pid=inum(r.get('exposure_id')),inum(r.get('plate_id'));ra,dec=fnum(r.get('ra_icrs')),fnum(r.get('dec_icrs'))
  if None in (eid,pid,ra,dec):holds['MISSING_PARENT_ID_OR_COORDINATES']+=1;continue
  pm=plate.get(pid)
  if pm is None:holds['MISSING_PLATE_METADATA']+=1;continue
  if not pm['site_key']:holds['AMBIGUOUS_SITE_IDENTITY']+=1;continue
  cand=[]
  for s in sols.get(pid,[]):
   sep=angsep(ra,dec,s['ra'],s['dec']);diag=None if s['fov1'] is None or s['fov2'] is None else math.hypot(s['fov1'],s['fov2']);plaus=True if diag is None else sep<=max(1.0,.75*diag)
   cand.append((sep,-s['num_xmatch'],s['solution_id'] if s['solution_id'] is not None else 10**18,plaus,s))
  if not cand:holds['NO_VALID_SCAN_SOLUTION_POLYGON']+=1;continue
  cand.sort(key=lambda x:(x[0],x[1],x[2]));sep,_,_,plaus,s=cand[0]
  if not plaus:holds['SOLUTION_ASSOCIATION_IMPLAUSIBLE']+=1;continue
  fst,iv=valid_fragments(exraw,subs,eid);fragment_status[fst]+=1
  if not iv:holds[fst]+=1;continue
  oldiv=master_intervals(r.get('fragment_intervals_json'))
  if not interval_sets_equal(iv,oldiv):timing_replay_mismatch+=1
  exposures[eid]={'eid':eid,'pid':pid,'archive_id':inum(r.get('archive_id')),'site':pm['site'],'site_key':pm['site_key'],'observatory':pm['observatory'],'lon':pm['lon'],'lat':pm['lat'],'coord_rule':pm['coord_rule'],'intervals':iv,'timing_status':status,'num_sub':exraw[eid]['num_sub'],'poly':s['poly'],'solution_id':s['solution_id'],'scan_id':s['scan_id'],'solution_sep_deg':sep}
 print(f'Full-population timing interval mismatches: {timing_replay_mismatch}')
 if master_rows!=139539:raise SystemExit(f'Replay HOLD: master rows {master_rows} != 139539')
 if len(exposures)!=56703:raise SystemExit(f'Replay HOLD: eligible exposures {len(exposures)} != 56703')
 if timing_replay_mismatch!=0:raise SystemExit(f'Replay HOLD: {timing_replay_mismatch} independently reconstructed interval-set mismatches')
 frags=[]
 for e in exposures.values():
  for x in e['intervals']:frags.append((x['start'],x['end'],e['eid'],x))
 frags.sort(key=lambda z:(z[0],z[1],z[2]));active=[];pairs={};same_site=set()
 for ix,(st,en,eid,frag) in enumerate(frags,1):
  cutoff=st.timestamp()-MAX_GAP;active=[q for q in active if q[1].timestamp()>=cutoff];ea=exposures[eid]
  for ast,aen,oeid,ofrag in active:
   if oeid==eid:continue
   eb=exposures[oeid];key=(oeid,eid) if oeid<eid else (eid,oeid)
   if ea['site_key']==eb['site_key']:same_site.add(key);continue
   gap,ov=interval_metric(frag,ofrag)
   if ov is not None:ov['exposure_current']=eid;ov['exposure_active']=oeid
   if gap>MAX_GAP+1e-9:continue
   rec=pairs.setdefault(key,{'min_gap':1e99,'overlaps':[],'fragment_pair_count':0});rec['fragment_pair_count']+=1
   if ov is not None:rec['overlaps'].append(ov);rec['min_gap']=0.0
   elif gap<rec['min_gap']:rec['min_gap']=gap
  active.append((st,en,eid,frag))
  if ix%10000==0:log(f'fragment sweep {ix:,}/{len(frags):,}; pairs={len(pairs):,}')
 if len(pairs)!=13177:raise SystemExit(f'Replay HOLD: temporal pairs {len(pairs)} != 13177')
 if RESULT.exists():raise SystemExit(f'Publication HOLD: final v094t result directory already exists: {RESULT}')
 stage=RESULT.parent/(RESULT.name+'.__staging__.'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.'+str(os.getpid()));stage.mkdir(parents=True,exist_ok=False)
 outp=stage/'applause_dr4_source_free_cross_site_opportunities_v094t.csv'
 fields=['pair_id','exposure_a','exposure_b','plate_a','plate_b','archive_a','archive_b','site_a','site_b','observatory_a','observatory_b','site_coord_rule_a','site_coord_rule_b','site_separation_km_diagnostic','site_separation_band','timing_bin','min_fragment_gap_seconds','fragment_overlap_intervals_json','fragment_overlap_count','total_fragment_overlap_seconds','max_fragment_overlap_seconds','fragment_pair_count_evaluated','timing_status_a','timing_status_b','num_sub_a','num_sub_b','solution_id_a','solution_id_b','scan_id_a','scan_id_b','solution_association_sep_deg_a','solution_association_sep_deg_b','legacy_infinity_geometry_status','old_common_positive_infinity_footprint','old_common_tangent_area_deg2','old_common_fraction_of_a','old_common_fraction_of_b','old_common_fraction_of_smaller','gate_le5min','gate_le10min','gate_le15min','in_1951_1955','pre_sputnik','epoch_label']
 allbins=Counter();oldbins=Counter();newbins=Counter();geometry_status=Counter();unresolved_pair_ids=[];sitepairs=Counter();baseline=Counter();epochs=Counter();stable_le5=set();expected_signatures={}
 with outp.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for n,(key,pr) in enumerate(sorted(pairs.items()),1):
   ea,eb=exposures[key[0]],exposures[key[1]];ovs=pr['overlaps'];gap=0.0 if ovs else pr['min_gap']
   if ovs:bin_='OVERLAP'
   elif gap<=300:bin_='GT0_LE5MIN'
   elif gap<=600:bin_='GT5_LE10MIN'
   else:bin_='GT10_LE15MIN'
   geom=legacy_geometry_fields(ea['poly'],eb['poly']);gstat=geom['legacy_infinity_geometry_status'];geometry_status[gstat]+=1
   if gstat=='LEGACY_TANGENT_UNRESOLVED':unresolved_pair_ids.append(f'{key[0]}|{key[1]}')
   oldpos=(gstat=='LEGACY_TANGENT_POSITIVE');d=hav(ea['lat'],ea['lon'],eb['lat'],eb['lon']);bb=baseline_band(d)
   starts=[x['start'] for x in ea['intervals']+eb['intervals']];ends=[x['end'] for x in ea['intervals']+eb['intervals']];tmin,tmax=min(starts),max(ends)
   in5155=(tmin>=datetime(1951,1,1,tzinfo=timezone.utc) and tmax<datetime(1956,1,1,tzinfo=timezone.utc));pre=tmax<SPUTNIK;epoch='IN_1951_1955' if in5155 else ('PRE_SPUTNIK' if pre else 'POST_SPUTNIK_OR_SAME_LAUNCH_DATE')
   total=sum(x['duration_seconds'] for x in ovs);mx=max([x['duration_seconds'] for x in ovs],default=0.0)
   row={'pair_id':f'{key[0]}|{key[1]}','exposure_a':key[0],'exposure_b':key[1],'plate_a':ea['pid'],'plate_b':eb['pid'],'archive_a':ea['archive_id'],'archive_b':eb['archive_id'],'site_a':ea['site'],'site_b':eb['site'],'observatory_a':ea['observatory'],'observatory_b':eb['observatory'],'site_coord_rule_a':ea['coord_rule'],'site_coord_rule_b':eb['coord_rule'],'site_separation_km_diagnostic':'' if d is None else f'{d:.6f}','site_separation_band':bb,'timing_bin':bin_,'min_fragment_gap_seconds':f'{gap:.6f}','fragment_overlap_intervals_json':json.dumps(ovs,separators=(',',':'),sort_keys=True),'fragment_overlap_count':len(ovs),'total_fragment_overlap_seconds':f'{total:.6f}','max_fragment_overlap_seconds':f'{mx:.6f}','fragment_pair_count_evaluated':pr['fragment_pair_count'],'timing_status_a':ea['timing_status'],'timing_status_b':eb['timing_status'],'num_sub_a':ea['num_sub'],'num_sub_b':eb['num_sub'],'solution_id_a':ea['solution_id'],'solution_id_b':eb['solution_id'],'scan_id_a':ea['scan_id'],'scan_id_b':eb['scan_id'],'solution_association_sep_deg_a':f"{ea['solution_sep_deg']:.8f}",'solution_association_sep_deg_b':f"{eb['solution_sep_deg']:.8f}",'legacy_infinity_geometry_status':gstat,'old_common_positive_infinity_footprint':geom['old_common_positive_infinity_footprint'],'old_common_tangent_area_deg2':geom['old_common_tangent_area_deg2'],'old_common_fraction_of_a':geom['old_common_fraction_of_a'],'old_common_fraction_of_b':geom['old_common_fraction_of_b'],'old_common_fraction_of_smaller':geom['old_common_fraction_of_smaller'],'gate_le5min':bin_ in ('OVERLAP','GT0_LE5MIN'),'gate_le10min':bin_ in ('OVERLAP','GT0_LE5MIN','GT5_LE10MIN'),'gate_le15min':True,'in_1951_1955':in5155,'pre_sputnik':pre,'epoch_label':epoch}
   expected_signatures[row['pair_id']]=sig(row);w.writerow(row);allbins[bin_]+=1;(oldbins if oldpos else newbins)[bin_]+=1;sitepairs[' | '.join(sorted((ea['site'],eb['site'])))]+=1;baseline[bb]+=1;epochs[epoch]+=1
   if oldpos and bin_ in ('OVERLAP','GT0_LE5MIN'):stable_le5.add((key[0],key[1],ea['solution_id'],eb['solution_id']))
   if n%3000==0:log(f'population output {n:,}/13,177')
 observed={};dups=[];outrows=0
 for r in rows(outp):
  outrows+=1;k=str(r.get('pair_id') or '')
  if k in observed:dups.append(k)
  observed[k]=sig(r)
 expkeys=set(expected_signatures);obskeys=set(observed);miss=expkeys-obskeys;extra_keys=obskeys-expkeys;sigbad={k for k in expkeys&obskeys if expected_signatures[k]!=observed[k]}
 if outrows!=13177 or len(observed)!=13177 or dups or miss or extra_keys or sigbad:raise SystemExit(f"Replay HOLD: staged output rows={outrows} unique={len(observed)} dup={len(dups)} missing={len(miss)} extra={len(extra_keys)} signatures={len(sigbad)}; staging preserved at {stage}")
 if sum(oldbins.values())!=1541 or dict(oldbins)!=EXPECTED_OLD_BINS:raise SystemExit(f'Replay HOLD: old common-positive counts {dict(oldbins)} total={sum(oldbins.values())}')
 oldplan=set()
 for r in rows(path['old_le5_plan']):
  a,b=inum(r['exposure_a']),inum(r['exposure_b']);sa,sb=inum(r['solution_id_a']),inum(r['solution_id_b'])
  if a>b:a,b,sa,sb=b,a,sb,sa
  oldplan.add((a,b,sa,sb))
 missing=oldplan-stable_le5;extra=stable_le5-oldplan
 if len(oldplan)!=1240 or missing or extra:raise SystemExit(f'Replay HOLD: old <=5 stable keys plan={len(oldplan)} missing={len(missing)} extra={len(extra)}')
 report={'status':'COMPLETE','analysis_kind':'applause_dr4_source_free_opportunity_population_repair_v094t','parent_v094s_commit':'0f56c8397e8ebdd154a9ec026bfe084e5863c7e9','legacy_infinity_geometry_status_counts':dict(geometry_status),'legacy_infinity_geometry_unresolved_pair_ids':unresolved_pair_ids,'staged_output_replay':{'rows':outrows,'unique_pair_keys':len(observed),'duplicate_pair_key_count':len(dups),'missing_pair_key_count':len(miss),'extra_pair_key_count':len(extra_keys),'science_signature_mismatch_count':len(sigbad),'science_signature_fields':SCIENCE_FIELDS},'contract_sha256':EXPECTED,'parent_provenance_sha256':sha(PROV),'master_rows':master_rows,'eligible_exposures':len(exposures),'full_population_timing_interval_mismatches':timing_replay_mismatch,'continuous_fragment_records':len(frags),'distinct_site_temporal_pairs_le15min':len(pairs),'exclusive_timing_bins_all':dict(allbins),'cumulative_timing_gates_all':{'LE5MIN_INCLUDING_OVERLAP':allbins['OVERLAP']+allbins['GT0_LE5MIN'],'LE10MIN_INCLUDING_OVERLAP':allbins['OVERLAP']+allbins['GT0_LE5MIN']+allbins['GT5_LE10MIN'],'LE15MIN_INCLUDING_OVERLAP':len(pairs)},'old_common_positive_replay':{'rows':sum(oldbins.values()),'exclusive_timing_bins':dict(oldbins),'old_le5_plan_keys':len(oldplan),'missing_old_le5_keys':len(missing),'extra_old_le5_keys':len(extra)},'newly_retained_without_old_positive_intersection':{'rows':sum(newbins.values()),'exclusive_timing_bins':dict(newbins),'overlap_rows':newbins['OVERLAP'],'includes_legacy_tangent_nonpositive_and_unresolved':True,'unresolved_rows':geometry_status['LEGACY_TANGENT_UNRESOLVED']},'same_site_temporal_context_pairs':len(same_site),'fragment_reconstruction_status_counts':dict(fragment_status),'exposure_preflight_holds':dict(holds),'site_baseline_band_counts_diagnostic_only':dict(baseline),'epoch_counts_all':dict(epochs),'top_site_pairs_all':sitepairs.most_common(30),'guards':{'source_catalog_reads':0,'candidate_identity_inspection':0,'private_candidate_map_reads':0,'network':0,'pixels':0,'registration':0,'real_source_pairing':0},'next_stage':'Acquire/freeze elevations for any newly relevant plates and validate corrected time-dependent geometry/observable synthetic recovery on newly recovered OVERLAP opportunities.','output_hashes':{outp.name:sha(outp)}}
 rp=stage/'applause_dr4_source_free_opportunity_population_repair_v094t.json';rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');man=stage/'v094t_output_manifest.sha256';man.write_text(f"{sha(outp)}  {outp.name}\n{sha(rp)}  {rp.name}\n",encoding='utf-8')
 if RESULT.exists():raise SystemExit(f'Publication HOLD: final result directory appeared before publish; staging preserved at {stage}')
 os.replace(stage,RESULT)
 print('\n'+'='*108);print('v094t SOURCE-FREE CROSS-SITE OPPORTUNITY DIAGNOSTIC COMPLETION COMPLETE');print('='*108)
 print(f'Master exposure rows:                         {master_rows:,}');print(f'Eligible exposures:                           {len(exposures):,}');print(f'Full-pop timing interval mismatches:           {timing_replay_mismatch}');print(f'Distinct-site temporal pairs <=15 min:         {len(pairs):,}');print(f'All exclusive timing bins:                     {dict(allbins)}');print(f'Old common-positive replay rows/bins:          {sum(oldbins.values()):,} / {dict(oldbins)}');print(f'Old <=5 stable-key replay missing/extra:       {len(missing)} / {len(extra)}');print(f'Not-old-positive retained rows:                {sum(newbins.values()):,}');print(f'Not-old-positive timing bins:                  {dict(newbins)}');print(f'Legacy geometry statuses:                      {dict(geometry_status)}');print(f'Legacy tangent unresolved rows:                {geometry_status["LEGACY_TANGENT_UNRESOLVED"]:,}');print(f'Staged output key/signature replay:            {outrows:,} rows / {len(observed):,} unique / 0 mismatches');print('Source catalogues / identities / network:      0 / 0 / 0');print('STOP: source-free census complete; finite-distance geometry must be separately frozen before any source matcher.');return 0
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');a=ap.parse_args();return self_test() if a.self_test else run()
if __name__=='__main__':raise SystemExit(main())
