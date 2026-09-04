#!/usr/bin/env python3
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta
import csv, hashlib, json, math, os

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"pair17_temporal_bracketing_census_contract_v081.json"
EXPECTED_CONTRACT_SHA="f0c45348477dc6a7094a739e34766bf5867cf94c3fec3c71066fbf594b060b63"

V077=ROOT/"results"/"pair17_applause_independent_plate_opportunity_census_v077a"
OPPS=V077/"pair17_candidate_plate_opportunities_v077a.csv"
V077BANK=V077/"pair17_v077a_bank_manifest.json"

V079=ROOT/"results"/"pair17_pixel_followup_scan_plan_and_acquisition_v079"
ACQ=V079/"pair17_scan_acquisition_manifest_v079.csv"
V079BANK=V079/"pair17_v079b_bank_manifest.json"

V080=ROOT/"results"/"pair17_registered_native_pixel_recurrence_sensitivity_v080"
CAND=V080/"pair17_native_pixel_candidate_summary_v080.csv"
V080BANK=V080/"pair17_v080a_bank_manifest.json"

EXPECTED={
 OPPS:"f8bd8a1bc322d0a9dc0239e29f676975f8ff692e17e040e2786cc196caf24b1d",
 V077BANK:"86545f2e4fa228c9472665bfe59ba7625314c548c0117bc00442265d8a1e97ef",
 V079BANK:"d3bd17cb6c9da62feb17d10bd8f7b86789ee11b63acc8d131407ba0b785e1e42",
 V080BANK:"f2ba81ab1222162e3d94a57d61d4f92da14ec37fef3dab4e54abd060ca699327",
}

OUT=ROOT/"results"/"pair17_temporal_bracketing_census_v081"
OUT_ALL=OUT/"pair17_temporal_bracketing_opportunities_v081.csv"
OUT_SUM=OUT/"pair17_temporal_bracketing_candidate_summary_v081.csv"
OUT_Q=OUT/"pair17_temporal_bracketing_acquisition_queue_v081.csv"
OUT_AMB=OUT/"pair17_temporal_bracketing_timing_ambiguous_v081.csv"
OUT_JSON=OUT/"pair17_temporal_bracketing_census_v081.json"

SCIENCE={7685,89580}
START=datetime.fromisoformat("1953-12-02T20:46:29+00:00")
END=datetime.fromisoformat("1953-12-02T20:51:28+00:00")
SERIES={"HAMBURG":"HAM-LA","BAMBERG":"Bamberg-North"}
BANDS=[1,2,6,24]

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
 return h.hexdigest()

def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))

def write_csv(p,rr):
 p.parent.mkdir(parents=True,exist_ok=True)
 fields=list(rr[0].keys()) if rr else []
 t=p.with_suffix(p.suffix+".tmp")
 with t.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
  if fields: w.writeheader(); w.writerows(rr)
 t.replace(p)

def write_json(p,o):
 p.parent.mkdir(parents=True,exist_ok=True)
 t=p.with_suffix(p.suffix+".tmp")
 t.write_text(json.dumps(o,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
 t.replace(p)

def num(v):
 try:
  x=float(str(v).strip()); return x if math.isfinite(x) else None
 except: return None

def integer(v):
 x=num(v); return None if x is None else int(x)

def dt(v):
 s=str(v or "").strip().replace("Z","+00:00")
 if not s:return None
 try:
  x=datetime.fromisoformat(s)
  if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
  return x.astimezone(timezone.utc)
 except:return None

def split(v): return [x.strip() for x in str(v or "").split(";") if x.strip()]

def obs(row):
 s=(str(row.get("filename_scan") or "")+" "+str(row.get("archive_names") or "")+" "+str(row.get("institutes") or "")).lower()
 if "ham-la" in s or "hamburg" in s:return "HAMBURG"
 if "bamberg-north" in s or "bamberg" in s:return "BAMBERG"
 return "OTHER"

def series(row):
 s=str(row.get("filename_scan") or "").replace("\\","/")
 for token in ("HAM-LA","Bamberg-North"):
  if token.lower() in s.lower():return token
 return ""

def relation(a,b):
 if b<START:return "PRECEDING",(START-b).total_seconds(),0.0
 if a>END:return "FOLLOWING",(a-END).total_seconds(),0.0
 return "OVERLAPPING",0.0,max(0.0,(min(b,END)-max(a,START)).total_seconds())

def intervals(row,fields):
 starts=split(row.get("exposure_start_values"))
 if not starts:return [],"NO_START_VALUES"
 if "exposure_end_values" in fields:
  ends=split(row.get("exposure_end_values"))
  if len(starts)!=len(ends):return [],"START_END_COUNT_MISMATCH"
  out=[]
  for i,(sv,ev) in enumerate(zip(starts,ends),1):
   a,b=dt(sv),dt(ev)
   if a is None or b is None or b<=a:return [],"BAD_INTERVAL"
   out.append((i,a,b,"START_END"))
  return out,""
 dur=[x for x in ("exposure_duration_values","exptime_values","exposure_exptime_values") if x in fields]
 if len(dur)!=1:return [],"NO_UNAMBIGUOUS_END_OR_DURATION"
 ds=split(row.get(dur[0]))
 if len(starts)!=len(ds):return [],"START_DURATION_COUNT_MISMATCH"
 out=[]
 for i,(sv,dv) in enumerate(zip(starts,ds),1):
  a=dt(sv); sec=num(dv)
  if a is None or sec is None or sec<=0:return [],"BAD_DURATION"
  out.append((i,a,a+timedelta(seconds=sec),"START_DURATION:"+dur[0]))
 return out,""

def main():
 print("="*120)
 print("PAIR 17 — TEMPORAL BRACKETING CENSUS v081")
 print("="*120)
 print("Metadata only; no network, FITS pixels, detector, injection or manual review.")
 if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA: raise RuntimeError("v081 contract mismatch")
 for p,e in EXPECTED.items():
  if not p.is_file() or sha(p)!=e: raise RuntimeError(f"Frozen input mismatch: {p}")
  print("HASH PASS:",p.relative_to(ROOT))

 surv={}
 for r in rows(CAND):
  if r.get("mechanical_evidence_state")=="TRANSIENT_LIKE_NATIVE_NONRECURRENCE_SUPPORTED":
   surv[str(r["raw_match_row"])]=r.get("population","")
 if len(surv)!=6: raise RuntimeError(f"Expected 6 frozen candidates; got {len(surv)}")
 print("Frozen population:",len(surv),dict(Counter(surv.values())))

 acquired={integer(r.get("scan_id")) for r in rows(ACQ)} if ACQ.is_file() else set()
 allr=[];amb=[];seen=0;matched=0

 with OPPS.open("r",encoding="utf-8-sig",newline="") as f:
  rd=csv.DictReader(f); fields=set(rd.fieldnames or [])
  if "exposure_start_values" not in fields: raise RuntimeError("No exposure_start_values")
  if "exposure_end_values" not in fields and len([x for x in ("exposure_duration_values","exptime_values","exposure_exptime_values") if x in fields])!=1:
   raise RuntimeError("No prospectively accepted end/duration field; schema repair required before chronology exposure")
  for r in rd:
   seen+=1; rid=str(r.get("raw_match_row") or "")
   if rid not in surv:continue
   matched+=1
   pid=integer(r.get("physical_opportunity_plate_id"))
   if pid is None or pid in SCIENCE:continue
   ob=obs(r)
   if ob not in SERIES:continue
   ser=series(r); same=(ser.lower()==SERIES[ob].lower())
   ints,reason=intervals(r,fields)
   if not ints:
    amb.append({"raw_match_row":rid,"population":surv[rid],"physical_plate_id":pid,"scan_id":r.get("scan_id",""),"filename_scan":r.get("filename_scan",""),"observatory":ob,"series":ser,"reason":reason})
    continue
   for idx,a,b,src in ints:
    rel,gap,ov=relation(a,b)
    rec={
      "raw_match_row":rid,"population":surv[rid],"physical_plate_id":pid,
      "scan_id":integer(r.get("scan_id")),"archive_id":integer(r.get("archive_id")),
      "filename_scan":r.get("filename_scan",""),"observatory":ob,"series":ser,
      "science_series":SERIES[ob],"same_science_series":same,
      "coverage_class":r.get("coverage_class",""),"edge_distance_arcsec":r.get("edge_distance_arcsec",""),
      "exposure_index":idx,"exposure_start_utc":a.isoformat(),"exposure_end_utc":b.isoformat(),
      "exposure_duration_seconds":(b-a).total_seconds(),"timing_source":src,
      "relation_to_common_overlap":rel,"gap_seconds":gap,"gap_hours":gap/3600.0,
      "comparison_overlap_seconds":ov,"file_size":integer(r.get("file_size")),
      "fits_checksum":r.get("fits_checksum",""),"already_acquired_v079":integer(r.get("scan_id")) in acquired
    }
    for band in BANDS:rec[f"within_{band}h"]=gap<=band*3600
    allr.append(rec)

 if seen!=496009:raise RuntimeError(f"v077a row count changed: {seen}")
 if not matched:raise RuntimeError("No v077a opportunities for frozen six")

 allr.sort(key=lambda r:(int(r["raw_match_row"]),r["observatory"],float(r["gap_seconds"]),r["relation_to_common_overlap"],int(r["physical_plate_id"])))

 qmap={}
 for r in allr:
  include=(r["same_science_series"] and r["within_24h"]) or ((not r["same_science_series"]) and r["within_6h"])
  if not include or r["scan_id"] is None:continue
  k=(r["scan_id"],r["filename_scan"])
  q=qmap.setdefault(k,{"scan_id":r["scan_id"],"filename_scan":r["filename_scan"],"physical_plate_id":r["physical_plate_id"],"archive_id":r["archive_id"],"observatory":r["observatory"],"series":r["series"],"same_science_series":r["same_science_series"],"file_size":r["file_size"],"fits_checksum":r["fits_checksum"],"already_acquired_v079":r["already_acquired_v079"],"candidate_ids":set(),"relations":set(),"minimum_gap_seconds":float(r["gap_seconds"])})
  q["candidate_ids"].add(r["raw_match_row"]);q["relations"].add(r["relation_to_common_overlap"]);q["minimum_gap_seconds"]=min(q["minimum_gap_seconds"],float(r["gap_seconds"]))
 queue=[]
 for k in sorted(qmap):
  q=qmap[k]; q["candidate_count"]=len(q["candidate_ids"]);q["candidate_ids"]=";".join(sorted(q["candidate_ids"],key=int));q["relations"]=";".join(sorted(q["relations"]));queue.append(q)

 summary=[]
 for rid in sorted(surv,key=int):
  cr=[r for r in allr if r["raw_match_row"]==rid]
  s={"raw_match_row":rid,"population":surv[rid]}
  for ob in SERIES:
   oo=[r for r in cr if r["observatory"]==ob]
   for band in BANDS:
    s[f"{ob.lower()}_same_series_within_{band}h"]=sum(r["same_science_series"] and r[f"within_{band}h"] for r in oo)
   for rel in ("PRECEDING","FOLLOWING","OVERLAPPING"):
    rr=[r for r in oo if r["same_science_series"] and r["relation_to_common_overlap"]==rel]
    rr.sort(key=lambda r:(float(r["gap_seconds"]),int(r["physical_plate_id"])))
    p=f"{ob.lower()}_same_series_{rel.lower()}"
    s[p+"_count"]=len(rr);s[p+"_nearest_plate_id"]=rr[0]["physical_plate_id"] if rr else "";s[p+"_nearest_gap_seconds"]=rr[0]["gap_seconds"] if rr else "";s[p+"_nearest_start_utc"]=rr[0]["exposure_start_utc"] if rr else "";s[p+"_nearest_end_utc"]=rr[0]["exposure_end_utc"] if rr else ""
  s["bilateral_same_series_bracketing_both_observatories_within_24h"]=all(
   any(r["observatory"]==ob and r["same_science_series"] and r["relation_to_common_overlap"]==rel and r["within_24h"] for r in cr)
   for ob in SERIES for rel in ("PRECEDING","FOLLOWING")
  )
  summary.append(s)

 OUT.mkdir(parents=True,exist_ok=True);write_csv(OUT_ALL,allr);write_csv(OUT_SUM,summary);write_csv(OUT_Q,queue);write_csv(OUT_AMB,amb)
 bands={}
 for band in BANDS:
  bands[str(band)]={"same_series_intervals":sum(r["same_science_series"] and r[f"within_{band}h"] for r in allr),"candidates_with_same_series":len({r["raw_match_row"] for r in allr if r["same_science_series"] and r[f"within_{band}h"]})}
 newbytes=sum(int(q["file_size"]) for q in queue if q["file_size"] is not None and not q["already_acquired_v079"])
 report={"status":"COMPLETE","analysis_kind":"pair17_temporal_bracketing_census_v081","contract_sha256":EXPECTED_CONTRACT_SHA,
 "population":{"total":6,"split":dict(Counter(surv.values()))},
 "chronology":{"usable_exposure_intervals":len(allr),"timing_ambiguous":len(amb),"band_counts":bands,
 "bilateral_same_series_bracketing_both_observatories_within_24h":sum(bool(x["bilateral_same_series_bracketing_both_observatories_within_24h"]) for x in summary)},
 "v082_queue":{"unique_scans":len(queue),"already_acquired_v079":sum(q["already_acquired_v079"] for q in queue),"new_scans_required":sum(not q["already_acquired_v079"] for q in queue),"known_new_bytes":newbytes},
 "guards":{"network_calls":0,"fits_pixel_reads":0,"detector_calls":0,"injection_measurements":0,"candidate_disposition_changes":False,"manual_image_review":False}}
 write_json(OUT_JSON,report)

 print("="*120);print("v081 TEMPORAL BRACKETING CENSUS COMPLETE")
 print("Population:",report["population"])
 for band in BANDS:print(f"<= {band} h same-series: {bands[str(band)]['same_series_intervals']} intervals; {bands[str(band)]['candidates_with_same_series']}/6 candidates")
 print("Bilateral same-series pre+post <=24h at BOTH observatories:",report["chronology"]["bilateral_same_series_bracketing_both_observatories_within_24h"],"/ 6")
 print("v082 queue:",len(queue),"unique scans;",report["v082_queue"]["new_scans_required"],"new;",f"{newbytes/(1024**3):.2f} GiB")
 print("FITS pixel reads: 0; dispositions: NONE; STATUS: COMPLETE")

if __name__=="__main__": main()
