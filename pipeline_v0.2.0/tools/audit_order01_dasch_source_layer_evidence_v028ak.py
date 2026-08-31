#!/usr/bin/env python3
"""
ORDER 01 — source-layer DASCH/DR7 evidence isolation v028ak

Purpose
-------
v028aj proved that ai43437 evidence is cached, but its per-rank ranking was
polluted by downstream synthesis products (for example v028e) that simply copy
science coordinates/ranks into later evidence records.

v028ak isolates the ORIGINAL / EARLIEST DASCH evidence layer.

Included source classes
-----------------------
A file is eligible if its path/name explicitly indicates one of:
  * v028r
  * v028s
  * v028t
  * v028u
  * querycat
  * lightcurve
  * platephot

Excluded source classes
-----------------------
All downstream candidate synthesis/adjudication products are excluded, including
v028v onward and generic "candidate_evidence", "disposition", "freeze",
"inventory", "forensic", etc., unless the filename itself is an exact raw
querycat/lightcurve/platephot cache.

This stage:
  1. lists every source-layer artifact containing ai43437;
  2. extracts ai43437 line windows from text/MD/log;
  3. recursively extracts ai43437-scoped JSON fragments;
  4. extracts CSV/TSV ai43437 rows;
  5. identifies per-rank evidence using explicit rank fields OR actual source/
     fitted coordinates near preserved DASCH positions;
  6. prints compact evidence fields and source filenames.

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen detector is NOT rerun.
No endpoint state changes.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"

OUT_JSON = BASE / "order01_dasch_source_layer_evidence_v028ak.json"
OUT_CSV = BASE / "order01_dasch_source_layer_evidence_v028ak.csv"
OUT_FILES = BASE / "order01_dasch_source_layer_files_v028ak.csv"
OUT_TEXT = BASE / "ORDER01_DASCH_SOURCE_LAYER_TEXT_WINDOWS_V028AK.txt"
OUT_MD = BASE / "ORDER01_DASCH_SOURCE_LAYER_EVIDENCE_V028AK.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
MAX_FILE_BYTES = 100_000_000
MAX_SEP_ARCSEC = 30.0
TEXT_SUFFIXES = {".json",".csv",".tsv",".md",".txt",".log"}

SOURCE_TOKENS = (
    "v028r","v028s","v028t","v028u",
    "querycat","lightcurve","platephot"
)

DERIVED_TOKENS = (
    "candidate_evidence","reduced","disposition","freeze","inventory","forensic",
    "v028v","v028w","v028x","v028y","v028z","v028aa","v028ab","v028ac",
    "v028ad","v028ae","v028af","v028ag","v028ah","v028ai","v028aj"
)

# Exact raw cache names override derived-token exclusions.
RAW_CACHE_TOKENS = ("querycat","lightcurve","platephot")

INTERESTING = (
    "rank","plate","ra","dec","flag","drad","fit","source","atlas","apass",
    "object","catalog","mag","detect","nondetect","blend","defect","neighbor",
    "neighbour","radial","smooth","iso","sxt","match","status","distance"
)


def read_csv(path, delim=","):
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh,delimiter=delim))


def write_csv(path,rows,fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
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


def norm(s):
    return re.sub(r"[^a-z0-9]+","",str(s).lower())


def pick(row,*names,default=None):
    nm={norm(k):k for k in row}
    for name in names:
        q=norm(name)
        if q in nm:return row[nm[q]]
    return default


def angsep_arcsec(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c=max(-1.0,min(1.0,c))
    return math.degrees(math.acos(c))*3600.0


def eligible_source_file(p):
    low=str(p).lower()
    base=p.name.lower()
    has_source=any(t in low for t in SOURCE_TOKENS)
    if not has_source:
        return False
    raw_cache=any(t in base for t in RAW_CACHE_TOKENS)
    if raw_cache:
        return True
    if any(t in low for t in DERIVED_TOKENS):
        # v028r/s/t/u are explicitly source-layer and allowed.
        if any(t in low for t in ("v028r","v028s","v028t","v028u")):
            return True
        return False
    return True


def source_class(p):
    low=str(p).lower()
    for t in ("v028r","v028s","v028t","v028u"):
        if t in low:return t
    for t in ("querycat","lightcurve","platephot"):
        if t in low:return t
    return "other"


def flatten_scalars(obj,prefix="",depth=0,max_depth=5,out=None):
    if out is None:out={}
    if depth>max_depth:return out
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
            elif isinstance(v,list) and len(v)<=20 and all(
                isinstance(x,(str,int,float,bool)) or x is None for x in v
            ):
                out[key]=v
            elif isinstance(v,(dict,list)):
                flatten_scalars(v,key,depth+1,max_depth,out)
    elif isinstance(obj,list):
        for j,v in enumerate(obj[:30]):
            key=f"{prefix}[{j}]"
            if isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
            elif isinstance(v,(dict,list)):
                flatten_scalars(v,key,depth+1,max_depth,out)
    return out


def subtree_has_plate(obj):
    try:return PLATE in json.dumps(obj,default=str).lower()
    except Exception:return PLATE in str(obj).lower()


def recover_json_fragments(obj,path="$",plate_scope=False,out=None,depth=0):
    if out is None:out=[]
    if depth>14:return out
    if isinstance(obj,dict):
        local_plate=subtree_has_plate(obj)
        scope=plate_scope or local_plate
        scal=flatten_scalars(obj,max_depth=2)
        if scope and any(any(t in str(k).lower() for t in INTERESTING) for k in scal):
            out.append((path,scal,plate_scope and not local_plate))
        for k,v in obj.items():
            if isinstance(v,(dict,list)):
                recover_json_fragments(v,f"{path}.{k}",scope,out,depth+1)
    elif isinstance(obj,list):
        for j,v in enumerate(obj):
            if isinstance(v,(dict,list)):
                recover_json_fragments(v,f"{path}[{j}]",plate_scope,out,depth+1)
    return out


def explicit_rank(sc):
    for k,v in sc.items():
        kl=str(k).lower()
        if "strict_rank" in kl or kl.endswith(".rank") or kl=="rank":
            rv=i(v)
            if rv in RANKS:return rv
    return None


def actual_coord_candidates(sc):
    """
    Return plausible actual/fitted source coordinate pairs, rejecting obvious
    query/input/target/center pairs.
    """
    bad=("query","input","target","center","centre","search","requested","cone")
    vals=[]
    items=list(sc.items())
    ras=[];decs=[]
    for k,v in items:
        kl=str(k).lower()
        if any(t in kl for t in bad):continue
        x=f(v)
        if x is None:continue
        nk=norm(k)
        # Keep permissive naming but avoid x/y pixel fields.
        if (
            nk in {"ra","radeg","raj2000","rafit","fitra","fittedra","rafitted"} or
            nk.endswith("radeg") or nk.endswith("rafit") or
            "fittedra" in nk
        ) and 0<=x<360:
            ras.append((k,x))
        if (
            nk in {"dec","decdeg","dej2000","decfit","fitdec","fitteddec","decfitted"} or
            nk.endswith("decdeg") or nk.endswith("decfit") or
            "fitteddec" in nk
        ) and -90<=x<=90:
            decs.append((k,x))
    for rk,ra in ras:
        for dk,dec in decs:
            # Prefer same parent path.
            rp=str(rk).rsplit(".",1)[0]
            dp=str(dk).rsplit(".",1)[0]
            vals.append((0 if rp==dp else 1,rk,dk,ra,dec))
    vals.sort(key=lambda z:z[0])
    return vals


def best_science_match(sc,science):
    best=None
    for _,rk,dk,ra,dec in actual_coord_candidates(sc):
        for rank,s in science.items():
            sep=angsep_arcsec(s["ra"],s["dec"],ra,dec)
            rec=(sep,rank,rk,dk,ra,dec)
            if best is None or rec[0]<best[0]:
                best=rec
    return best


def compact_interesting(sc):
    out={}
    # Prefer shallow/important fields.
    ordered=sorted(sc.items(),key=lambda kv:(
        0 if any(t in str(kv[0]).lower() for t in ("rank","plate","flag","drad","fit","detect","source","atlas","apass")) else 1,
        len(str(kv[0])),
        str(kv[0])
    ))
    for k,v in ordered:
        kl=str(k).lower()
        if PLATE in str(v).lower() or any(t in kl for t in INTERESTING):
            out[k]=v
        if len(out)>=80:break
    return out


def signature(r):
    core={
        "source_class":r["source_class"],
        "rank_hint":r["rank_hint"],
        "coord_rank":r["coord_rank"],
        "sep":None if r["science_sep_arcsec"] is None else round(r["science_sep_arcsec"],4),
        "fields":r["interesting_fields"],
    }
    return json.dumps(core,sort_keys=True,default=str)


def main():
    print("="*128)
    print("ORDER 01 — SOURCE-LAYER DASCH/DR7 EVIDENCE ISOLATION v028ak")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("closure guard mismatch")

    strict_rows=read_csv(STRICT)
    native=read_csv(DASCH_NATIVE)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in RANKS}
    if sorted(strict)!=RANKS:
        raise RuntimeError("strict guard mismatch")

    science={}
    for rank in RANKS:
        sr=strict[rank]
        tile=str(pick(sr,"dasch_tile_id"))
        idx=i(pick(sr,"dasch_candidate_index","dasch_index","dasch_native_candidate_index"))
        q=[r for r in native if str(r.get("tile_id",""))==tile and i(r.get("candidate_index"))==idx]
        if len(q)!=1:raise RuntimeError(f"#{rank}: DASCH science row resolution failed")
        nr=q[0]
        science[rank]={"ra":f(nr["ra_deg"]),"dec":f(nr["dec_deg"])}

    files=[]
    for top in (ROOT/"results",ROOT/"work",ROOT/"tools"):
        if not top.exists():continue
        for p in top.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:continue
            if not eligible_source_file(p):continue
            try:
                if p.stat().st_size>MAX_FILE_BYTES:continue
                txt=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:continue
            if PLATE not in txt.lower() and PLATE not in p.name.lower():
                continue
            files.append({
                "path":p,
                "relative_path":str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                "source_class":source_class(p),
                "size_bytes":p.stat().st_size,
                "plate_occurrences":txt.lower().count(PLATE),
            })
    files.sort(key=lambda r:(SOURCE_TOKENS.index(r["source_class"]) if r["source_class"] in SOURCE_TOKENS else 99,r["relative_path"]))

    print(f"Eligible source-layer artifacts containing ai43437: {len(files)}")
    for r in files:
        print(f"  [{r['source_class']}] {r['relative_path']} ({r['plate_occurrences']} plate mentions)")

    records=[]
    text_windows=[]

    for fr in files:
        p=fr["path"]; cls=fr["source_class"]; suf=p.suffix.lower()

        if suf==".json":
            try:obj=json.loads(p.read_text(encoding="utf-8",errors="ignore"))
            except Exception:continue
            for jpath,sc,inh in recover_json_fragments(obj):
                rh=explicit_rank(sc)
                bm=best_science_match(sc,science)
                sep=rank=None;rk=dk=ra=dec=None
                if bm is not None:
                    sep,rank,rk,dk,ra,dec=bm
                # Keep if explicit rank OR actual coordinate within 30".
                if rh not in RANKS and (sep is None or sep>MAX_SEP_ARCSEC):
                    continue
                records.append({
                    "source_file":fr["relative_path"],
                    "source_class":cls,
                    "location":jpath,
                    "rank_hint":rh,
                    "coord_rank":rank,
                    "science_sep_arcsec":sep,
                    "row_ra_deg":ra,"row_dec_deg":dec,
                    "ra_field":rk,"dec_field":dk,
                    "plate_inherited":inh,
                    "interesting_fields":compact_interesting(sc),
                })

        elif suf in (".csv",".tsv"):
            try:rows=read_csv(p,"\t" if suf==".tsv" else ",")
            except Exception:rows=[]
            plate_file=PLATE in p.name.lower()
            for rn,row in enumerate(rows):
                low=json.dumps(row,default=str).lower()
                if PLATE not in low and not plate_file:continue
                rh=explicit_rank(row)
                bm=best_science_match(row,science)
                sep=rank=None;rk=dk=ra=dec=None
                if bm is not None:
                    sep,rank,rk,dk,ra,dec=bm
                if rh not in RANKS and (sep is None or sep>MAX_SEP_ARCSEC):
                    continue
                records.append({
                    "source_file":fr["relative_path"],
                    "source_class":cls,
                    "location":f"ROW[{rn}]",
                    "rank_hint":rh,
                    "coord_rank":rank,
                    "science_sep_arcsec":sep,
                    "row_ra_deg":ra,"row_dec_deg":dec,
                    "ra_field":rk,"dec_field":dk,
                    "plate_inherited":plate_file and PLATE not in low,
                    "interesting_fields":compact_interesting(row),
                })

        else:
            lines=p.read_text(encoding="utf-8",errors="ignore").splitlines()
            for ln,line in enumerate(lines):
                low=line.lower()
                if PLATE not in low and not any(f"#{r}" in line or f" {r} " in line for r in RANKS):
                    continue
                a=max(0,ln-4);b=min(len(lines),ln+5)
                text_windows.append({
                    "source_file":fr["relative_path"],
                    "source_class":cls,
                    "line_start":a+1,
                    "line_end":b,
                    "window":"\n".join(lines[a:b])[:10000],
                })

    # Dedup source-layer records.
    dedup={}
    for r in records:
        sig=signature(r)
        if sig not in dedup:
            rr=dict(r);rr["duplicate_count"]=1;rr["source_copies"]=[r["source_file"]]
            dedup[sig]=rr
        else:
            dedup[sig]["duplicate_count"]+=1
            if r["source_file"] not in dedup[sig]["source_copies"]:
                dedup[sig]["source_copies"].append(r["source_file"])
    unique=list(dedup.values())

    per_rank={}
    for rank in RANKS:
        hits=[]
        for r in unique:
            explicit=(r["rank_hint"]==rank)
            coord=(r["coord_rank"]==rank and r["science_sep_arcsec"] is not None and r["science_sep_arcsec"]<=MAX_SEP_ARCSEC)
            if explicit or coord:hits.append(r)
        hits.sort(key=lambda r:(
            0 if r["rank_hint"]==rank else 1,
            999999 if r["science_sep_arcsec"] is None else r["science_sep_arcsec"],
            ("v028u","v028t","v028s","v028r","querycat","lightcurve","platephot").index(r["source_class"])
            if r["source_class"] in ("v028u","v028t","v028s","v028r","querycat","lightcurve","platephot") else 99,
            r["source_file"]
        ))
        per_rank[rank]=hits

    print(f"\nUnique source-layer structured records: {len(unique)}")
    print(f"Source-layer text windows: {len(text_windows)}")

    print("\nPer-rank ORIGINAL evidence:")
    for rank in RANKS:
        hits=per_rank[rank]
        print(f"\n  #{rank}: N={len(hits)}")
        for h in hits[:8]:
            sep="n/a" if h["science_sep_arcsec"] is None else f"{h['science_sep_arcsec']:.3f}\""
            fields=h["interesting_fields"]
            # compact one-line field preview
            preview=[]
            for k,v in list(fields.items())[:12]:
                preview.append(f"{k}={v}")
            print(
                f"    [{h['source_class']}] rankHint={h['rank_hint']} "
                f"coordRank={h['coord_rank']} sep={sep}"
            )
            print(f"       file={h['source_file']} @ {h['location']}")
            if preview:
                print("       " + " | ".join(preview)[:1400])

    flat=[]
    for rank in RANKS:
        for h in per_rank[rank]:
            flat.append({
                "strict_rank":rank,
                "source_file":h["source_file"],
                "source_class":h["source_class"],
                "location":h["location"],
                "rank_hint":h["rank_hint"],
                "coord_rank":h["coord_rank"],
                "science_sep_arcsec":h["science_sep_arcsec"],
                "row_ra_deg":h["row_ra_deg"],
                "row_dec_deg":h["row_dec_deg"],
                "ra_field":h["ra_field"],
                "dec_field":h["dec_field"],
                "plate_inherited":h["plate_inherited"],
                "duplicate_count":h["duplicate_count"],
                "source_copies":";".join(h["source_copies"]),
                "interesting_fields_json":json.dumps(h["interesting_fields"],sort_keys=True,default=str),
            })

    payload={
        "stage":"ORDER01_DASCH_SOURCE_LAYER_EVIDENCE_V028AK",
        "plate":PLATE,
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "downstream_synthesis_files_excluded":True,
            "source_layer_only":True,
        },
        "eligible_source_files":[{
            k:v for k,v in r.items() if k!="path"
        } for r in files],
        "unique_source_layer_structured_record_count":len(unique),
        "text_windows":text_windows,
        "per_rank":{str(k):v for k,v in per_rank.items()},
        "interpretive_boundary":(
            "v028ak isolates source-layer cached DR7 evidence from downstream "
            "candidate summaries. A recovered official row remains a catalogue/plate "
            "measurement requiring scientific adjudication; no DASCH endpoint state "
            "is changed here."
        )
    }
    write_json(OUT_JSON,payload)
    fields=[
        "strict_rank","source_file","source_class","location","rank_hint","coord_rank",
        "science_sep_arcsec","row_ra_deg","row_dec_deg","ra_field","dec_field",
        "plate_inherited","duplicate_count","source_copies","interesting_fields_json"
    ]
    write_csv(OUT_CSV,flat,fields)
    write_csv(OUT_FILES,[{k:v for k,v in r.items() if k!="path"} for r in files],
              ["relative_path","source_class","size_bytes","plate_occurrences"])
    OUT_TEXT.write_text(
        "\n\n".join(
            f"=== {w['source_file']} [{w['source_class']}] lines {w['line_start']}-{w['line_end']} ===\n{w['window']}"
            for w in text_windows
        )+"\n",encoding="utf-8"
    )

    md=[
        "# ORDER 01 — Source-Layer DASCH/DR7 Evidence Isolation v028ak","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- Downstream synthesis/adjudication products were excluded.",
        "- Only v028r/s/t/u and raw querycat/lightcurve/platephot source layers are eligible.",
        "- No endpoint state was changed.","",
        f"Eligible source-layer artifacts containing `{PLATE}`: **{len(files)}**.",
        f"Unique structured source-layer records: **{len(unique)}**.","",
        "## Per-rank source evidence","",
        "| rank | unique relevant source-layer records |",
        "|---:|---:|"
    ]
    for rank in RANKS:
        md.append(f"| #{rank} | {len(per_rank[rank])} |")
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_FILES}")
    print(f"  {OUT_TEXT}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
