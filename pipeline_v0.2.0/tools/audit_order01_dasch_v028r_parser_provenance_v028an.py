#!/usr/bin/env python3
"""
ORDER 01 — recover exact v028r platephot parser + raw-list schema v028an

Purpose
-------
v028am established that every rank-scoped ai43437 platephot cache is a top-level
JSON list, while generic row/table reconstruction found no coordinate dictionaries.
Because v028r previously extracted official_fit_ra_deg/official_fit_dec_deg from
these same caches, v028an stops guessing and recovers the exact original parser
provenance.

This stage:
  1. finds Python tools/scripts whose names or contents mention v028r and platephot;
  2. extracts source snippets around JSON loading, platephot parsing, RA/Dec,
     aflags/bflags, drad_rms2, flux_iso, and science_nearest_official_sources;
  3. fingerprints each raw ai43437 rank cache:
       - top-level length
       - element types
       - first elements
       - nested element shapes
       - scalar/list widths
       - dict keys if present
  4. searches every top-level/nested value for the exact official-fit coordinates
     already frozen by v028r, locating where those numbers actually occur in the
     raw cache.

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"
TOOLS = ROOT / "tools"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
V028R_JSON = BASE / "order01_official_dasch_platephot_astrometry_v028r.json"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_v028r_parser_provenance_v028an.json"
OUT_TXT = BASE / "ORDER01_DASCH_V028R_PARSER_PROVENANCE_V028AN.txt"
OUT_MD = BASE / "ORDER01_DASCH_V028R_PARSER_PROVENANCE_V028AN.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
KEYWORDS = (
    "platephot","json.load","json.loads","official_fit_ra","official_fit_dec",
    "aflags","bflags","drad_rms2","flux_iso","science_nearest_official_sources",
    "fit_ra","fit_dec","platephot_rows","response"
)


def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def compact_repr(x,limit=1600):
    try:
        s=repr(x)
    except Exception:
        s=f"<unrepr {type(x).__name__}>"
    return s if len(s)<=limit else s[:limit]+" ...<truncated>"


def shape(x,depth=0):
    if depth>4:
        return {"type":type(x).__name__}
    if isinstance(x,dict):
        return {
            "type":"dict",
            "key_count":len(x),
            "keys":list(x.keys())[:40],
            "sample_values":{
                str(k):shape(v,depth+1)
                for k,v in list(x.items())[:8]
            }
        }
    if isinstance(x,list):
        types={}
        for v in x[:100]:
            types[type(v).__name__]=types.get(type(v).__name__,0)+1
        out={
            "type":"list",
            "length":len(x),
            "sample_element_types":types,
        }
        if x:
            out["first_element_shape"]=shape(x[0],depth+1)
            if len(x)>1:
                out["second_element_shape"]=shape(x[1],depth+1)
        return out
    if isinstance(x,(str,int,float,bool)) or x is None:
        return {"type":type(x).__name__,"value":x}
    return {"type":type(x).__name__,"repr":compact_repr(x,500)}


def walk_values(obj,path="$",out=None,depth=0):
    if out is None:
        out=[]
    if depth>12:
        return out
    out.append((path,obj))
    if isinstance(obj,dict):
        for k,v in obj.items():
            walk_values(v,f"{path}.{k}",out,depth+1)
    elif isinstance(obj,list):
        for j,v in enumerate(obj):
            walk_values(v,f"{path}[{j}]",out,depth+1)
    return out


def numeric_match(value,target,tol=5e-7):
    try:
        x=float(value)
        return math.isfinite(x) and abs(x-target)<=tol
    except Exception:
        return False


def source_snippets(path):
    try:
        lines=path.read_text(encoding="utf-8",errors="ignore").splitlines()
    except Exception:
        return []
    hit_lines=set()
    for idx,line in enumerate(lines):
        low=line.lower()
        if any(k.lower() in low for k in KEYWORDS):
            for j in range(max(0,idx-8),min(len(lines),idx+13)):
                hit_lines.add(j)
    if not hit_lines:
        return []
    # merge contiguous ranges
    ranges=[]
    start=prev=None
    for j in sorted(hit_lines):
        if start is None:
            start=prev=j
        elif j==prev+1:
            prev=j
        else:
            ranges.append((start,prev))
            start=prev=j
    ranges.append((start,prev))

    snippets=[]
    for a,b in ranges:
        text="\n".join(f"{n+1:05d}: {lines[n]}" for n in range(a,b+1))
        snippets.append({"start_line":a+1,"end_line":b+1,"text":text})
    return snippets


def main():
    print("="*128)
    print("ORDER 01 — RECOVER EXACT v028r PLATEPHOT PARSER + RAW-LIST SCHEMA v028an")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,V028R_JSON):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    v028r=json.loads(V028R_JSON.read_text(encoding="utf-8"))
    src_rows={
        int(r["strict_rank"]):r
        for r in v028r.get("science_nearest_official_sources",[])
        if int(r.get("strict_rank",-1)) in RANKS
    }

    # Find relevant scripts.
    scripts=[]
    if TOOLS.exists():
        for p in TOOLS.rglob("*.py"):
            try:
                text=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:
                continue
            low=(p.name+"\n"+text).lower()
            score=0
            if "v028r" in low: score+=100
            if "platephot" in low: score+=40
            if "science_nearest_official_sources" in low: score+=40
            if "official_fit_ra" in low or "official_fit_dec" in low: score+=30
            if score:
                scripts.append({
                    "path":p,
                    "relative_path":str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                    "score":score,
                    "snippets":source_snippets(p),
                })
    scripts.sort(key=lambda r:(-r["score"],r["relative_path"]))

    print(f"Relevant parser/tool scripts found: {len(scripts)}")
    for r in scripts[:12]:
        print(f"  score={r['score']:3d}  {r['relative_path']}")

    raw_info={}
    text_parts=[]

    text_parts.append("ORDER 01 — v028r parser provenance / raw list schema v028an\n")
    text_parts.append("=== RELEVANT TOOL SCRIPTS ===\n")

    for r in scripts[:12]:
        text_parts.append(f"\n### {r['relative_path']} score={r['score']}\n")
        for sn in r["snippets"][:12]:
            text_parts.append(
                f"\n--- lines {sn['start_line']}-{sn['end_line']} ---\n{sn['text']}\n"
            )

    text_parts.append("\n\n=== RAW CACHE STRUCTURES ===\n")

    for rank in RANKS:
        p=RAW_DIR/f"{PLATE}_sol0_rank{rank}_apass_platephot.json"
        if not p.is_file():
            raw_info[str(rank)]={"status":"MISSING"}
            print(f"#{rank}: missing raw cache")
            continue
        try:
            obj=json.loads(p.read_text(encoding="utf-8",errors="ignore"))
        except Exception as e:
            raw_info[str(rank)]={"status":f"JSON_PARSE_ERROR:{e}"}
            print(f"#{rank}: JSON parse error {e}")
            continue

        frozen=src_rows.get(rank,{})
        fra=frozen.get("official_fit_ra_deg")
        fdec=frozen.get("official_fit_dec_deg")

        matches_ra=[]
        matches_dec=[]
        for jpath,val in walk_values(obj):
            if fra is not None and numeric_match(val,float(fra)):
                matches_ra.append(jpath)
            if fdec is not None and numeric_match(val,float(fdec)):
                matches_dec.append(jpath)

        info={
            "status":"OK",
            "file":str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            "top_shape":shape(obj),
            "first_5_repr":[compact_repr(x) for x in obj[:5]] if isinstance(obj,list) else [],
            "v028r_official_fit_ra_deg":fra,
            "v028r_official_fit_dec_deg":fdec,
            "exact_ra_value_paths":matches_ra[:50],
            "exact_dec_value_paths":matches_dec[:50],
        }

        # If top-level is list, fingerprint widths/types comprehensively.
        if isinstance(obj,list):
            elem_types={}
            widths={}
            dict_keys={}
            for el in obj:
                elem_types[type(el).__name__]=elem_types.get(type(el).__name__,0)+1
                if isinstance(el,(list,tuple)):
                    widths[len(el)]=widths.get(len(el),0)+1
                elif isinstance(el,dict):
                    sig="|".join(map(str,el.keys()))
                    dict_keys[sig]=dict_keys.get(sig,0)+1
            info["top_element_type_counts"]=elem_types
            info["top_list_width_counts"]=widths
            info["top_dict_key_signatures"]=dict_keys

        raw_info[str(rank)]=info

        print(
            f"#{rank}: top={type(obj).__name__} "
            f"len={len(obj) if isinstance(obj,list) else 'n/a'} "
            f"types={info.get('top_element_type_counts',{})} "
            f"widths={info.get('top_list_width_counts',{})}"
        )
        print(f"    frozen official fit RA/Dec={fra}, {fdec}")
        print(f"    exact raw paths RA={matches_ra[:8] or 'NONE'}")
        print(f"    exact raw paths Dec={matches_dec[:8] or 'NONE'}")
        if isinstance(obj,list):
            for j,x in enumerate(obj[:3]):
                print(f"    raw[{j}] {compact_repr(x,1000)}")

        text_parts.append(f"\n## rank #{rank}\n")
        text_parts.append(json.dumps(info,indent=2,sort_keys=True,default=str))
        text_parts.append("\n")

    payload={
        "stage":"ORDER01_DASCH_V028R_PARSER_PROVENANCE_AND_RAW_LIST_SCHEMA_V028AN",
        "plate":PLATE,
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "generic_parser_guessing_stopped":True,
            "original_v028r_parser_provenance_targeted":True,
        },
        "relevant_scripts":[{
            "relative_path":r["relative_path"],
            "score":r["score"],
            "snippet_count":len(r["snippets"]),
            "snippets":r["snippets"][:12],
        } for r in scripts[:12]],
        "raw_cache_info":raw_info,
        "interpretive_boundary":(
            "v028an is a provenance/schema diagnostic. It does not interpret a "
            "missing parser match as a missing astronomical source. The purpose is "
            "to recover the exact raw-cache representation and the original v028r "
            "logic that generated the frozen fitted-source evidence."
        )
    }

    write_json(OUT_JSON,payload)
    OUT_TXT.write_text("\n".join(text_parts),encoding="utf-8")

    md=[
        "# ORDER 01 — v028r Parser Provenance / Raw-List Schema v028an","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No endpoint state was changed.",
        "- Generic parser guessing is suspended; this stage recovers the original v028r parsing provenance.","",
        f"Relevant parser/tool scripts found: **{len(scripts)}**.","",
        "## Raw cache fingerprint","",
        "| rank | status | top type | length | official-fit RA path hits | official-fit Dec path hits |",
        "|---:|---|---|---:|---:|---:|"
    ]
    for rank in RANKS:
        q=raw_info.get(str(rank),{})
        top=q.get("top_shape",{})
        md.append(
            f"| #{rank} | {q.get('status')} | {top.get('type','—')} | "
            f"{top.get('length','—')} | {len(q.get('exact_ra_value_paths',[]))} | "
            f"{len(q.get('exact_dec_value_paths',[]))} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_TXT}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
