#!/usr/bin/env python3
from pathlib import Path
from collections import Counter, defaultdict
import csv, hashlib, json

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"pair17_unblind_blind_review_contract_v085.json"
EXPECTED_CONTRACT_SHA="9963422c474ea3f090a4e340063cc6d86052afd8450d5cb6535a290f6ccd90c8"
V083=ROOT/"results"/"pair17_standardized_manual_dossiers_v083"
MANIFEST=V083/"pair17_manual_dossier_panel_manifest_v083.csv"
V083BANK=V083/"pair17_v083b_bank_manifest.json"
V084A=ROOT/"results"/"pair17_blinded_manual_review_packet_v084a"
V084ABANK=V084A/"pair17_v084a_bank_manifest.json"
SCORES=V084A/"pair17_blind_review_scores_v084a.csv"
SCOREBANK=V084A/"pair17_blind_review_scores_bank_v084a.json"
OUT=ROOT/"results"/"pair17_unblind_blind_review_v085"
SALT="pair17-v084-standardized-blind-manual-review-v001"

EXPECTED={
 V083BANK:"6f0f749852db04fc5d1a9b8bde773a2f0dc273ee59d8e0832b72e3743e9b658b",
 V084ABANK:"53e4c77094d8087ac6ca7f9e80d108a2b23829874b258d0321d3970311ff0293",
}

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
 return h.hexdigest()

def rcsv(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def wcsv(p,rows,fields=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 fields=fields or list(rows[0])
 with p.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def key(r):
 s="|".join([SALT,str(r.get("raw_match_row") or ""),str(r.get("panel_role") or ""),str(r.get("physical_plate_id") or ""),str(r.get("scan_id") or ""),str(r.get("filename_scan") or "")])
 return hashlib.sha256(s.encode()).hexdigest()

def main():
 print("="*110);print("PAIR 17 — BLIND REVIEW UNBLIND v085");print("="*110)
 if sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise RuntimeError("v085 contract SHA mismatch")
 for p,e in EXPECTED.items():
  if sha(p)!=e:raise RuntimeError(f"Frozen input changed: {p}")
 if not SCOREBANK.is_file():raise RuntimeError("Blind scores are not banked; refusing to unblind")
 bank=json.loads(SCOREBANK.read_text(encoding="utf-8"))
 if bank.get("status")!="COMPLETE" or bank.get("blind_scores_banked_before_unblinding") is not True:
  raise RuntimeError("Blind score bank guard failed")
 if bank.get("canonical_csv_sha256")!=sha(SCORES):raise RuntimeError("Canonical blind score CSV changed")

 scores=rcsv(SCORES)
 if len(scores)!=32 or {r["blind_code"] for r in scores}!={f"B{i:03d}" for i in range(1,33)}:
  raise RuntimeError("Blind score population invalid")
 score={r["blind_code"]:r for r in scores}

 panels=rcsv(MANIFEST)
 if len(panels)!=32:raise RuntimeError("v083 panel population changed")
 ordered=sorted(panels,key=key)

 joined=[]
 for i,p in enumerate(ordered,1):
  code=f"B{i:03d}";s=score[code]
  role=p.get("panel_role","")
  kind=("SCIENCE" if "SCIENCE_" in role else
        "CLOSE_TIME" if "V082_CLOSE_TIME" in role else
        "QUALIFIED_NEGATIVE" if "QUALIFIED_NEGATIVE" in role else "OTHER")
  joined.append({
   "blind_code":code,
   "raw_match_row":p.get("raw_match_row",""),
   "panel_role":role,
   "panel_kind":kind,
   "observatory":p.get("observatory",""),
   "physical_plate_id":p.get("physical_plate_id",""),
   "scan_id":p.get("scan_id",""),
   "relation_to_common_overlap":p.get("relation_to_common_overlap",""),
   "gap_hours":p.get("gap_hours",""),
   "registration_mode":p.get("registration_mode",""),
   "sensitivity_qualified_negative":p.get("sensitivity_qualified_negative",""),
   "feature_at_crosshair":s["feature_at_crosshair"],
   "morphology":s["morphology"],
   "local_context":s["local_context"],
   "confidence_1_to_5":s["confidence_1_to_5"],
   "notes":s.get("notes",""),
  })

 OUT.mkdir(parents=True,exist_ok=True)
 up=OUT/"pair17_unblinded_panel_scores_v085.csv";wcsv(up,joined)

 by=defaultdict(list)
 for r in joined:by[r["raw_match_row"]].append(r)
 summary=[]
 for cid in sorted(by,key=int):
  rr=by[cid]
  def one(substr):
   x=[r for r in rr if substr in r["panel_role"]]
   return x[0] if x else None
  h=one("SCIENCE_HAMBURG");b=one("SCIENCE_BAMBERG")
  close=[r for r in rr if "V082_CLOSE_TIME" in r["panel_role"]]
  comps=[r for r in rr if r["panel_kind"]!="SCIENCE"]
  summary.append({
   "raw_match_row":cid,
   "hamburg_science_blind_code":h["blind_code"] if h else "",
   "hamburg_science_feature":h["feature_at_crosshair"] if h else "",
   "hamburg_science_morphology":h["morphology"] if h else "",
   "hamburg_science_confidence":h["confidence_1_to_5"] if h else "",
   "bamberg_science_blind_code":b["blind_code"] if b else "",
   "bamberg_science_feature":b["feature_at_crosshair"] if b else "",
   "bamberg_science_morphology":b["morphology"] if b else "",
   "bamberg_science_confidence":b["confidence_1_to_5"] if b else "",
   "both_science_definite":bool(h and b and h["feature_at_crosshair"]=="DEFINITE" and b["feature_at_crosshair"]=="DEFINITE"),
   "both_science_stellar_compact":bool(h and b and h["morphology"]=="STELLAR_COMPACT" and b["morphology"]=="STELLAR_COMPACT"),
   "close_time_blind_codes":";".join(r["blind_code"] for r in close),
   "close_time_features":";".join(r["feature_at_crosshair"] for r in close),
   "comparison_definite_count":sum(r["feature_at_crosshair"]=="DEFINITE" for r in comps),
   "comparison_weak_count":sum(r["feature_at_crosshair"]=="WEAK_OR_AMBIGUOUS" for r in comps),
   "comparison_absent_count":sum(r["feature_at_crosshair"]=="ABSENT" for r in comps),
   "crosshair_concern_notes":" | ".join(f'{r["blind_code"]}: {r["notes"]}' for r in rr if r["notes"]),
  })
 sp=OUT/"pair17_candidate_manual_review_summary_v085.csv";wcsv(sp,summary)

 report={
  "status":"COMPLETE",
  "contract_sha256":EXPECTED_CONTRACT_SHA,
  "score_bank_sha256":sha(SCOREBANK),
  "canonical_score_csv_sha256":sha(SCORES),
  "panels":32,"candidates":6,
  "blind_feature_counts":dict(Counter(r["feature_at_crosshair"] for r in scores)),
  "unblinded_panel_table_sha256":sha(up),
  "candidate_summary_sha256":sha(sp),
  "guards":{"network_calls":0,"fits_reads":0,"new_pixel_measurements":0,"threshold_retuning":False,"candidate_disposition_changes":False,"manual_scores_modified":False}
 }
 (OUT/"pair17_unblind_blind_review_v085.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(json.dumps(report,indent=2,sort_keys=True))
 print("STAGE STATUS: COMPLETE")

if __name__=="__main__":main()
