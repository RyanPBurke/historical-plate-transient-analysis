#!/usr/bin/env python3
"""
ORDER 01 — v028r platephot query-geometry / semantics provenance audit v028ap

Purpose
-------
v028ao exactly parsed the cached raw platephot responses and established that no
official fitted row lies within 10 arcsec of any preserved DASCH native science
endpoint.

Before interpreting that as evidence against the DASCH endpoints, we must verify
the provenance of those raw queries. The cache names contain "apass_platephot",
so this stage asks:

  * What coordinate was each v028r platephot request centred on?
  * What query radius/window was used?
  * Was the preserved science endpoint actually inside the queried footprint?
  * Was the query centred on an APASS/reference star rather than the science
    candidate?
  * What did the original v028r code intend the platephot call to measure?

This stage reads the original v028r tool and v028r result JSON only. It performs
NO network request and NO candidate mutation.

Outputs include source-code excerpts and recursively recovered query metadata.

NO NETWORK ACCESS.
SCIENCE PIXELS ARE NOT READ.
Frozen detector is NOT rerun.
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
TOOLS = ROOT / "tools"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
V028R_JSON = BASE / "order01_official_dasch_platephot_astrometry_v028r.json"
V028R_TOOL = TOOLS / "audit_order01_official_dasch_platephot_astrometry_v028r.py"

OUT_JSON = BASE / "order01_dasch_v028r_platephot_query_geometry_v028ap.json"
OUT_CSV = BASE / "order01_dasch_v028r_platephot_query_geometry_v028ap.csv"
OUT_TXT = BASE / "ORDER01_DASCH_V028R_PLATEPHOT_QUERY_PROVENANCE_V028AP.txt"
OUT_MD = BASE / "ORDER01_DASCH_V028R_PLATEPHOT_QUERY_GEOMETRY_V028AP.md"

RANKS = [10,24,25,26,29,30]

CODE_TERMS = (
    "platephot","apass","query","radius","cone","arcsec","arcmin","degrees",
    "ra_deg","dec_deg","requests","url","params","cache","official_fit",
    "reference","source_id"
)

QUERY_KEY_TERMS = (
    "query","center","centre","radius","cone","search","apass","atlas",
    "reference","source","ra","dec","url","endpoint","param","cache"
)


def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


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


def resolve_science():
    strict=read_csv(STRICT)
    native=read_csv(DASCH_NATIVE)
    sr={i(r["strict_rank"]):r for r in strict if i(r["strict_rank"]) in RANKS}
    out={}
    for rank in RANKS:
        r=sr[rank]
        tile=str(pick(r,"dasch_tile_id"))
        idx=i(pick(r,"dasch_candidate_index","dasch_index","dasch_native_candidate_index"))
        q=[x for x in native
           if str(x.get("tile_id",""))==tile and i(x.get("candidate_index"))==idx]
        if len(q)!=1:
            raise RuntimeError(f"#{rank}: science resolution failed ({len(q)})")
        x=q[0]
        out[rank]={"ra_deg":f(x["ra_deg"]),"dec_deg":f(x["dec_deg"])}
    return out


def code_snippets(path):
    lines=path.read_text(encoding="utf-8",errors="ignore").splitlines()
    hit=set()
    for n,line in enumerate(lines):
        low=line.lower()
        if any(t in low for t in CODE_TERMS):
            for j in range(max(0,n-6),min(len(lines),n+10)):
                hit.add(j)

    ranges=[]
    start=prev=None
    for j in sorted(hit):
        if start is None:
            start=prev=j
        elif j==prev+1:
            prev=j
        else:
            ranges.append((start,prev));start=prev=j
    if start is not None:ranges.append((start,prev))

    return [{
        "start_line":a+1,
        "end_line":b+1,
        "text":"\n".join(f"{k+1:05d}: {lines[k]}" for k in range(a,b+1))
    } for a,b in ranges]


def flatten(obj,prefix="",depth=0,max_depth=8,out=None):
    if out is None:out={}
    if depth>max_depth:return out
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
            elif isinstance(v,list) and len(v)<=12 and all(
                isinstance(x,(str,int,float,bool)) or x is None for x in v
            ):
                out[key]=v
            elif isinstance(v,(dict,list)):
                flatten(v,key,depth+1,max_depth,out)
    elif isinstance(obj,list):
        for j,v in enumerate(obj):
            key=f"{prefix}[{j}]"
            if isinstance(v,(dict,list)):
                flatten(v,key,depth+1,max_depth,out)
            elif isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
    return out


def recursive_dicts(obj,path="$",out=None,depth=0):
    if out is None:out=[]
    if depth>12:return out
    if isinstance(obj,dict):
        out.append((path,obj))
        for k,v in obj.items():
            if isinstance(v,(dict,list)):
                recursive_dicts(v,f"{path}.{k}",out,depth+1)
    elif isinstance(obj,list):
        for j,v in enumerate(obj):
            if isinstance(v,(dict,list)):
                recursive_dicts(v,f"{path}[{j}]",out,depth+1)
    return out


def rank_hint(d):
    for k,v in d.items():
        kl=str(k).lower()
        if "strict_rank" in kl or kl=="rank":
            rv=i(v)
            if rv in RANKS:return rv
    return None


def candidate_query_coords(d):
    """
    Recover likely query-centre coordinates from a single dict.
    This stage is provenance-oriented, so query/center/reference fields are
    desired rather than rejected.
    """
    nm={norm(k):k for k in d}
    pairs=[]

    explicit_pairs=[
        ("query_ra_deg","query_dec_deg"),
        ("center_ra_deg","center_dec_deg"),
        ("centre_ra_deg","centre_dec_deg"),
        ("apass_ra_deg","apass_dec_deg"),
        ("reference_ra_deg","reference_dec_deg"),
        ("source_ra_deg","source_dec_deg"),
        ("gaia_ra_1951_deg","gaia_dec_1951_deg"),
        ("ra_deg","dec_deg"),
        ("ra","dec"),
    ]
    for rn,dn in explicit_pairs:
        rk=nm.get(norm(rn));dk=nm.get(norm(dn))
        if rk is None or dk is None:continue
        ra=f(d[rk]);dec=f(d[dk])
        if ra is not None and dec is not None and 0<=ra<360 and -90<=dec<=90:
            pairs.append({
                "ra_deg":ra,"dec_deg":dec,
                "ra_field":str(rk),"dec_field":str(dk),
                "label":rn.replace("_ra_deg","").replace("_ra","")
            })

    # permissive query/reference pair scan
    ras=[];decs=[]
    for k,v in d.items():
        kl=str(k).lower();x=f(v)
        if x is None:continue
        if "ra" in kl and any(t in kl for t in ("query","center","centre","apass","reference","source","gaia")) and 0<=x<360:
            ras.append((k,x))
        if "dec" in kl and any(t in kl for t in ("query","center","centre","apass","reference","source","gaia")) and -90<=x<=90:
            decs.append((k,x))
    for rk,ra in ras:
        for dk,dec in decs:
            pairs.append({
                "ra_deg":ra,"dec_deg":dec,
                "ra_field":str(rk),"dec_field":str(dk),
                "label":"permissive"
            })

    # dedup
    seen=set();out=[]
    for p in pairs:
        sig=(round(p["ra_deg"],9),round(p["dec_deg"],9),p["ra_field"],p["dec_field"])
        if sig not in seen:
            seen.add(sig);out.append(p)
    return out


def radius_candidates(d):
    out=[]
    for k,v in d.items():
        kl=str(k).lower()
        if any(t in kl for t in ("radius","cone","search_radius","window")):
            x=f(v)
            if x is not None:
                out.append({"field":str(k),"value":x})
    return out


def interesting_metadata(d):
    out={}
    for k,v in d.items():
        kl=str(k).lower()
        if any(t in kl for t in QUERY_KEY_TERMS):
            out[str(k)]=v
        if len(out)>=60:break
    return out


def main():
    print("="*128)
    print("ORDER 01 — v028r PLATEPHOT QUERY-GEOMETRY / SEMANTICS PROVENANCE AUDIT v028ap")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE,V028R_JSON,V028R_TOOL):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    science=resolve_science()
    obj=json.loads(V028R_JSON.read_text(encoding="utf-8"))
    snippets=code_snippets(V028R_TOOL)

    print(f"v028r source snippets recovered: {len(snippets)}")

    # Find rank-bearing query/reference dicts in v028r JSON.
    per_rank={r:[] for r in RANKS}
    unranked=[]

    for jpath,d in recursive_dicts(obj):
        rh=rank_hint(d)
        qcoords=candidate_query_coords(d)
        radii=radius_candidates(d)
        meta=interesting_metadata(d)
        if not qcoords and not radii and not meta:
            continue

        rec={
            "json_path":jpath,
            "rank_hint":rh,
            "query_coords":qcoords,
            "radius_candidates":radii,
            "metadata":meta,
        }

        if rh in RANKS:
            per_rank[rh].append(rec)
        else:
            # Keep only obviously request/query-related unranked structures.
            low=(jpath+" "+json.dumps(meta,default=str)).lower()
            if any(t in low for t in ("query","platephot","radius","endpoint","url","apass")):
                unranked.append(rec)

    summaries=[]
    print("\nPer-rank recovered query/reference geometry:")
    for rank in RANKS:
        s=science[rank]
        flattened=[]
        for rec in per_rank[rank]:
            for qc in rec["query_coords"]:
                q=dict(qc)
                q["json_path"]=rec["json_path"]
                q["science_to_query_arcsec"]=angsep_arcsec(
                    s["ra_deg"],s["dec_deg"],q["ra_deg"],q["dec_deg"]
                )
                q["radius_candidates"]=rec["radius_candidates"]
                q["metadata"]=rec["metadata"]
                flattened.append(q)

        # dedup coordinate pairs
        dedup={}
        for q in flattened:
            sig=(round(q["ra_deg"],8),round(q["dec_deg"],8),q["ra_field"],q["dec_field"])
            if sig not in dedup:
                dedup[sig]=q
        vals=list(dedup.values())
        vals.sort(key=lambda q:q["science_to_query_arcsec"])

        print(f"\n  #{rank}: query/reference coordinate candidates={len(vals)}")
        for q in vals[:12]:
            print(
                f"    {q['science_to_query_arcsec']:.3f}\" from science "
                f"{q['ra_field']}/{q['dec_field']} "
                f"RA={q['ra_deg']:.8f} Dec={q['dec_deg']:.8f}"
            )
            if q["radius_candidates"]:
                print(f"       radii={q['radius_candidates']}")
            md=q["metadata"]
            if md:
                preview=" | ".join(f"{k}={v}" for k,v in list(md.items())[:12])
                print(f"       {preview[:1400]}")

        nearest=vals[0] if vals else None
        summaries.append({
            "strict_rank":rank,
            "science_ra_deg":s["ra_deg"],
            "science_dec_deg":s["dec_deg"],
            "query_coordinate_candidate_count":len(vals),
            "nearest_query_or_reference_sep_arcsec":
                None if nearest is None else nearest["science_to_query_arcsec"],
            "nearest_query_ra_deg":None if nearest is None else nearest["ra_deg"],
            "nearest_query_dec_deg":None if nearest is None else nearest["dec_deg"],
            "nearest_query_ra_field":None if nearest is None else nearest["ra_field"],
            "nearest_query_dec_field":None if nearest is None else nearest["dec_field"],
            "nearest_query_radius_candidates_json":
                None if nearest is None else json.dumps(nearest["radius_candidates"],sort_keys=True),
            "all_query_candidates_json":json.dumps(vals,sort_keys=True,default=str),
        })

    txt=[]
    txt.append("ORDER 01 — v028r platephot query provenance v028ap\n")
    txt.append("=== ORIGINAL v028r SOURCE EXCERPTS ===\n")
    for sn in snippets:
        txt.append(f"\n--- lines {sn['start_line']}-{sn['end_line']} ---\n{sn['text']}\n")

    txt.append("\n=== PER-RANK QUERY/REFERENCE METADATA ===\n")
    for rank in RANKS:
        txt.append(f"\n## rank #{rank}\n")
        txt.append(json.dumps(per_rank[rank],indent=2,sort_keys=True,default=str))
        txt.append("\n")

    txt.append("\n=== UNRANKED QUERY/ENDPOINT METADATA ===\n")
    txt.append(json.dumps(unranked[:100],indent=2,sort_keys=True,default=str))

    payload={
        "stage":"ORDER01_DASCH_V028R_PLATEPHOT_QUERY_GEOMETRY_PROVENANCE_V028AP",
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "v028ao_absence_not_interpreted_without_query_geometry":True,
            "original_v028r_source_inspected":True,
        },
        "v028r_source_file":str(V028R_TOOL.relative_to(ROOT)),
        "source_snippets":snippets,
        "summaries":summaries,
        "per_rank_metadata":{str(k):v for k,v in per_rank.items()},
        "unranked_query_metadata":unranked[:100],
        "interpretive_boundary":(
            "v028ap determines whether the raw v028r platephot caches actually "
            "sampled the preserved DASCH science coordinate. A lack of nearby "
            "platephot rows is only strong negative official-source evidence if "
            "the science coordinate lay inside the relevant query footprint and "
            "the endpoint semantics permit such a source to be returned."
        )
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,summaries,list(summaries[0]))
    OUT_TXT.write_text("\n".join(txt),encoding="utf-8")

    md=[
        "# ORDER 01 — v028r Platephot Query-Geometry Provenance v028ap","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No endpoint state was changed.",
        "- v028ao's lack of nearby rows is not interpreted until query coverage is verified.","",
        "## Per-rank nearest recovered query/reference coordinate","",
        "| rank | candidate coordinates found | nearest to science | coordinate fields |",
        "|---:|---:|---:|---|"
    ]
    for r in summaries:
        sep=r["nearest_query_or_reference_sep_arcsec"]
        md.append(
            f"| #{r['strict_rank']} | {r['query_coordinate_candidate_count']} | "
            f"{'—' if sep is None else f'{sep:.3f}″'} | "
            f"{r['nearest_query_ra_field'] or '—'} / {r['nearest_query_dec_field'] or '—'} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
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
