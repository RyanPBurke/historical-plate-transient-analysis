#!/usr/bin/env python3
"""
ORDER 01 — preserved DASCH endpoint evidence inventory v028ah

Purpose
-------
Order 01's two-observatory branch is closed at v028ag, but all six DASCH
endpoints remain preserved as unresolved single-plate detections.

This stage performs NO network access and NO detector rerun. It inventories
already-cached DASCH/DR7 evidence in the project tree for ranks
[10,24,25,26,29,30], with special attention to:

  - physical plate ai43437
  - querycat
  - lightcurve
  - platephot
  - fitted positions
  - flags
  - source/reference identities
  - exact rank/candidate identifiers
  - science RA/Dec and nearby official rows

The output is an evidence map showing which official-data questions are already
answered locally and which still require a targeted DR7 query.

No candidate state mutation.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"

OUT_JSON = BASE / "order01_dasch_preserved_endpoint_evidence_inventory_v028ah.json"
OUT_CSV = BASE / "order01_dasch_preserved_endpoint_evidence_inventory_v028ah.csv"
OUT_FILES = BASE / "order01_dasch_preserved_endpoint_evidence_files_v028ah.csv"
OUT_MD = BASE / "ORDER01_DASCH_PRESERVED_ENDPOINT_EVIDENCE_INVENTORY_V028AH.md"

RANKS = [10,24,25,26,29,30]
PLATE = "ai43437"

TEXT_SUFFIXES = {".csv",".json",".md",".txt",".log",".tsv"}
EXCLUDE_NAMES = {
    OUT_JSON.name, OUT_CSV.name, OUT_FILES.name, OUT_MD.name
}

# Search within this radius when a row with parseable RA/Dec is found.
SCIENCE_MATCH_ARCSEC = 8.0


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(path)


def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        x=float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def i(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def pick(row,*names,default=None):
    norm={str(k).lower().replace("_",""):k for k in row}
    for name in names:
        q=str(name).lower().replace("_","")
        if q in norm:
            return row[norm[q]]
    return default


def angsep_arcsec(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c=max(-1.0,min(1.0,c))
    return math.degrees(math.acos(c))*3600.0


def parse_rows(path):
    """Best-effort row parser for CSV/TSV/JSON objects/lists."""
    suf=path.suffix.lower()
    out=[]
    try:
        if suf==".csv":
            out=read_csv(path)
        elif suf==".tsv":
            with path.open("r",encoding="utf-8-sig",newline="") as fh:
                out=list(csv.DictReader(fh,delimiter="\t"))
        elif suf==".json":
            obj=json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj,list):
                out=[x for x in obj if isinstance(x,dict)]
            elif isinstance(obj,dict):
                # collect obvious row arrays recursively one level
                for k,v in obj.items():
                    if isinstance(v,list) and v and all(isinstance(x,dict) for x in v):
                        out.extend(v)
                if not out:
                    out=[obj]
    except Exception:
        return []
    return out


def infer_ra_dec(row):
    ra=f(pick(row,
        "ra_deg","ra","ra_fit","fit_ra","fitted_ra","ra_fitted",
        "ra2000","ra_j2000","raj2000","ra_target_deg","dasch_ra_deg"))
    dec=f(pick(row,
        "dec_deg","dec","dec_fit","fit_dec","fitted_dec","dec_fitted",
        "decl","dec2000","dec_j2000","dej2000","dec_target_deg","dasch_dec_deg"))
    return ra,dec


def classify_file(path,text_lower):
    name=path.name.lower()
    tags=[]
    for tag in ("querycat","lightcurve","platephot","fitted","flag","dr7","dasch","ai43437"):
        if tag in name or tag in text_lower:
            tags.append(tag)
    return tags


def main():
    print("="*128)
    print("ORDER 01 — PRESERVED DASCH ENDPOINT EVIDENCE INVENTORY v028ah")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set") != []:
        raise RuntimeError("v028ag closure guard mismatch")
    if closure.get("order01_viable_two_observatory_transient_pairs_remaining") != 0:
        raise RuntimeError("v028ag pair-count guard mismatch")

    strict_rows=read_csv(STRICT)
    native=read_csv(DASCH_NATIVE)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in RANKS}
    if sorted(strict)!=RANKS:
        raise RuntimeError("strict-rank guard mismatch")

    # Resolve exact DASCH science rows.
    science={}
    for rank in RANKS:
        sr=strict[rank]
        tile=str(pick(sr,"dasch_tile_id"))
        idx=i(pick(sr,"dasch_candidate_index","dasch_index","dasch_native_candidate_index"))
        q=[r for r in native
           if str(r.get("tile_id",""))==tile and i(r.get("candidate_index"))==idx]
        if len(q)!=1:
            raise RuntimeError(f"#{rank}: expected one DASCH native row, found {len(q)}")
        nr=q[0]
        science[rank]={
            "strict_rank":rank,
            "tile_id":tile,
            "candidate_index":idx,
            "ra_deg":f(nr.get("ra_deg")),
            "dec_deg":f(nr.get("dec_deg")),
            "snr":f(nr.get("snr")),
            "polarity":i(nr.get("polarity")),
        }

    print("Preserved DASCH science endpoints:")
    for rank in RANKS:
        s=science[rank]
        print(
            f"  #{rank}: {s['tile_id']}::{s['candidate_index']} "
            f"RA={s['ra_deg']:.8f} Dec={s['dec_deg']:.8f} "
            f"SNR={s['snr']:.3f} polarity={s['polarity']:+d}"
        )
    print()

    # Candidate evidence files.
    evidence_files=[]
    candidate_paths=[]
    for root in (BASE, ROOT/"results", ROOT/"work"):
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.name in EXCLUDE_NAMES:
                continue
            if p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                # cap scan of huge text files
                if p.stat().st_size > 80_000_000:
                    continue
                text=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:
                continue
            low=text.lower()
            name=p.name.lower()
            interesting=(
                PLATE in low or PLATE in name
                or "querycat" in low or "querycat" in name
                or "lightcurve" in low or "lightcurve" in name
                or "platephot" in low or "platephot" in name
                or ("dasch" in name and ("v028r" in name or "v028s" in name or
                                         "v028t" in name or "v028u" in name))
            )
            if not interesting:
                continue
            tags=classify_file(p,low)
            rec={
                "path":str(p),
                "relative_path":str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                "size_bytes":p.stat().st_size,
                "tags":";".join(sorted(set(tags))),
                "contains_ai43437":PLATE in low or PLATE in name,
            }
            evidence_files.append(rec)
            candidate_paths.append(p)

    print(f"Potential cached DASCH/DR7 evidence files: {len(candidate_paths)}")

    # Inspect parseable rows for proximity / rank / plate evidence.
    results=[]
    for rank in RANKS:
        s=science[rank]
        hits=[]
        for p in candidate_paths:
            rows=parse_rows(p)
            if not rows:
                continue
            for rn,row in enumerate(rows):
                row_text=json.dumps(row,default=str).lower()
                rank_field=i(pick(row,"strict_rank","rank","candidate_rank"))
                plate_hit=PLATE in row_text
                rank_hit=(rank_field==rank)

                ra,dec=infer_ra_dec(row)
                sep=None
                coord_hit=False
                if None not in (ra,dec,s["ra_deg"],s["dec_deg"]):
                    sep=angsep_arcsec(s["ra_deg"],s["dec_deg"],ra,dec)
                    coord_hit=sep<=SCIENCE_MATCH_ARCSEC

                # exact science identifiers if present
                idx_hit=False
                idx=i(pick(row,"candidate_index","dasch_candidate_index"))
                tile=str(pick(row,"tile_id","dasch_tile_id",default=""))
                if idx is not None and tile:
                    idx_hit=(idx==s["candidate_index"] and tile==s["tile_id"])

                if not (rank_hit or coord_hit or idx_hit):
                    continue

                lowkeys={str(k).lower():v for k,v in row.items()}
                hits.append({
                    "source_file":str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                    "row_number":rn,
                    "rank_hit":rank_hit,
                    "coord_hit":coord_hit,
                    "science_sep_arcsec":sep,
                    "native_identity_hit":idx_hit,
                    "plate_ai43437_present":plate_hit,
                    "querycat_context":"querycat" in p.name.lower() or "querycat" in row_text,
                    "lightcurve_context":"lightcurve" in p.name.lower() or "lightcurve" in row_text,
                    "platephot_context":"platephot" in p.name.lower() or "platephot" in row_text,
                    "flag_fields":{
                        k:v for k,v in row.items()
                        if "flag" in str(k).lower() or str(k).lower() in {"a","b"}
                    },
                    "position_fields":{
                        k:v for k,v in row.items()
                        if any(t in str(k).lower() for t in ("ra","dec","drad","dist","offset"))
                    },
                    "identity_fields":{
                        k:v for k,v in row.items()
                        if any(t in str(k).lower() for t in ("source","atlas","apass","object","ref","id"))
                    },
                })

        querycat=sum(bool(h["querycat_context"]) for h in hits)
        lightcurve=sum(bool(h["lightcurve_context"]) for h in hits)
        platephot=sum(bool(h["platephot_context"]) for h in hits)
        officialish=sum(
            bool(h["querycat_context"] or h["lightcurve_context"] or h["platephot_context"])
            for h in hits
        )
        flag_hits=sum(bool(h["flag_fields"]) for h in hits)

        if platephot:
            next_need="OFFICIAL_PLATEPHOT_EVIDENCE_ALREADY_PRESENT;_ADJUDICATE_ROWS"
        elif querycat or lightcurve:
            next_need="OFFICIAL_MATCHED_DR7_EVIDENCE_PRESENT;_PLATEPHOT_UNMATCHED_QUERY_STILL_DESIRABLE"
        elif officialish:
            next_need="OFFICIAL_DR7_EVIDENCE_PRESENT;_FORMAT_REVIEW_REQUIRED"
        else:
            next_need="NO_PARSEABLE_OFFICIAL_SCIENCE_ROW_FOUND;_TARGETED_DR7_QUERY_REQUIRED"

        results.append({
            **s,
            "evidence_hit_count":len(hits),
            "official_context_hit_count":officialish,
            "querycat_hit_count":querycat,
            "lightcurve_hit_count":lightcurve,
            "platephot_hit_count":platephot,
            "flag_hit_count":flag_hits,
            "next_need":next_need,
            "hits":hits,
        })

    print("\nPer-rank cached-evidence inventory:")
    for r in results:
        print(
            f"  #{r['strict_rank']}: hits={r['evidence_hit_count']} "
            f"querycat={r['querycat_hit_count']} "
            f"lightcurve={r['lightcurve_hit_count']} "
            f"platephot={r['platephot_hit_count']} "
            f"flags={r['flag_hit_count']}"
        )
        print(f"       => {r['next_need']}")

    payload={
        "stage":"ORDER01_DASCH_PRESERVED_ENDPOINT_EVIDENCE_INVENTORY_V028AH",
        "source_closure_stage":closure.get("stage"),
        "preserved_dasch_ranks":RANKS,
        "plate":PLATE,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "two_observatory_branch_already_closed":True,
        },
        "evidence_files":evidence_files,
        "results":results,
        "interpretive_boundary":(
            "This is an evidence inventory only. Presence of a querycat, lightcurve, "
            "or platephot row does not establish that the DASCH endpoint is astrophysical. "
            "The purpose is to identify which official DR7 evidence is already cached "
            "before making any new network query."
        )
    }
    write_json(OUT_JSON,payload)

    flat=[]
    for r in results:
        flat.append({
            k:v for k,v in r.items() if k!="hits"
        })
    write_csv(OUT_CSV,flat,list(flat[0]))
    if evidence_files:
        write_csv(OUT_FILES,evidence_files,list(evidence_files[0]))
    else:
        write_csv(OUT_FILES,[],["path","relative_path","size_bytes","tags","contains_ai43437"])

    md=[
        "# ORDER 01 — Preserved DASCH Endpoint Evidence Inventory v028ah","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No candidate state was changed.",
        "- The Order-01 two-observatory branch is already closed; DASCH endpoints are being treated independently.","",
        "## Preserved DASCH endpoints","",
        "| rank | SNR | polarity | cached hits | querycat | lightcurve | platephot | next need |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        md.append(
            f"| #{r['strict_rank']} | {r['snr']:.3f} | {r['polarity']:+d} | "
            f"{r['evidence_hit_count']} | {r['querycat_hit_count']} | "
            f"{r['lightcurve_hit_count']} | {r['platephot_hit_count']} | "
            f"`{r['next_need']}` |"
        )
    md += [
        "",
        f"Potential cached DASCH/DR7 evidence files found: **{len(evidence_files)}**.",
        "",
        "## Interpretation boundary","",
        payload["interpretive_boundary"],
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_FILES}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
