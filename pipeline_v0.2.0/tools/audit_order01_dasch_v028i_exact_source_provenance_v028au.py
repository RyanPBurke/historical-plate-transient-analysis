#!/usr/bin/env python3
from __future__ import annotations

import ast
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
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
V028I_JSON = BASE / "order01_historical_closehit_flag_audit_v028i.json"
V028I_CSV = BASE / "order01_historical_closehit_flag_audit_v028i.csv"
V028I_TOOL = TOOLS / "audit_order01_historical_closehit_flags_v028i.py"

OUT_JSON = BASE / "order01_dasch_v028i_exact_source_provenance_v028au.json"
OUT_CSV = BASE / "order01_dasch_v028i_exact_source_provenance_v028au.csv"
OUT_TXT = BASE / "ORDER01_DASCH_V028I_EXACT_SOURCE_PROVENANCE_V028AU.txt"
OUT_MD = BASE / "ORDER01_DASCH_V028I_EXACT_SOURCE_PROVENANCE_V028AU.md"

RANKS = [10,24,25,26,29,30]
KNOWN = {
    10: {"aflags":14336, "bflags":1349386240},
    25: {"aflags":109592576, "bflags":1349386243},
    26: {"aflags":12288, "bflags":1349386240},
    30: {"aflags":268441600, "bflags":1349124096},
}
PROV_TERMS = (
    "plate","series","date","time","jd","mjd","rank","source","catalog","ref",
    "ra","dec","sep","distance","hit","index","file","path","candidate","epoch",
    "aflags","bflags","flag","drad","mag"
)


def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path,rows,fields):
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
        s=str(v).strip()
        if s.lower().startswith("0x"):
            return int(s,16)
        return int(float(s))
    except Exception:
        return default


def norm(s):
    return re.sub(r"[^a-z0-9]+","",str(s).lower())


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
        s=sr[rank]
        tid=str(s["dasch_tile_id"])
        idx=i(s.get("dasch_candidate_index"))
        q=[r for r in native
           if str(r.get("tile_id",""))==tid and i(r.get("candidate_index"))==idx]
        if len(q)!=1:
            raise RuntimeError(f"#{rank}: science resolution failed ({len(q)})")
        r=q[0]
        out[rank]={
            "ra_deg":f(r["ra_deg"]),
            "dec_deg":f(r["dec_deg"]),
            "tile_id":tid,
            "candidate_index":idx,
        }
    return out


def scalar_provenance(d):
    out={}
    for k,v in d.items():
        if isinstance(v,(str,int,float,bool)) or v is None:
            kl=str(k).lower()
            if any(t in kl for t in PROV_TERMS):
                out[str(k)]=v
    return out


def recursive_dicts(obj,path="$",out=None,depth=0):
    if out is None: out=[]
    if depth>14:return out
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
        if "strict_rank" in kl or kl in ("rank","candidate_rank"):
            rv=i(v)
            if rv in RANKS:return rv
    return None


def coord_candidates(d):
    nm={norm(k):k for k in d}
    pairs=(
        ("ra_deg","dec_deg"),
        ("hit_ra_deg","hit_dec_deg"),
        ("historical_ra_deg","historical_dec_deg"),
        ("catalog_ra_deg","catalog_dec_deg"),
        ("fit_ra_deg","fit_dec_deg"),
        ("official_fit_ra_deg","official_fit_dec_deg"),
        ("dasch_ra_deg","dasch_dec_deg"),
        ("ra","dec"),
    )
    out=[]
    for rn,dn in pairs:
        rk,dk=nm.get(norm(rn)),nm.get(norm(dn))
        if rk is None or dk is None:continue
        ra,dec=f(d[rk]),f(d[dk])
        if ra is not None and dec is not None and 0<=ra<360 and -90<=dec<=90:
            out.append((str(rk),str(dk),ra,dec))
    seen=set();q=[]
    for x in out:
        sig=(x[0],x[1],round(x[2],9),round(x[3],9))
        if sig not in seen:
            seen.add(sig);q.append(x)
    return q


def exact_flag_match(d,rank):
    want=KNOWN.get(rank)
    if not want:return False
    avals=[]; bvals=[]
    for k,v in d.items():
        kl=str(k).lower()
        if "aflag" in kl:
            x=i(v)
            if x is not None:avals.append(x)
        if "bflag" in kl:
            x=i(v)
            if x is not None:bvals.append(x)
    return want["aflags"] in avals or want["bflags"] in bvals


def source_blocks(path):
    lines=path.read_text(encoding="utf-8",errors="ignore").splitlines()
    hit=set()
    terms=("v028h","historical","closehit","flag","aflags","bflags","input","read_csv","json")
    for n,line in enumerate(lines):
        low=line.lower()
        if any(t in low for t in terms):
            for j in range(max(0,n-8),min(len(lines),n+14)):
                hit.add(j)
    ranges=[]; start=prev=None
    for j in sorted(hit):
        if start is None:
            start=prev=j
        elif j==prev+1:
            prev=j
        else:
            ranges.append((start,prev));start=prev=j
    if start is not None:ranges.append((start,prev))
    return [{
        "start_line":a+1,"end_line":b+1,
        "text":"\n".join(f"{k+1:05d}: {lines[k]}" for k in range(a,b+1))
    } for a,b in ranges]


def ast_path_constants(path):
    src=path.read_text(encoding="utf-8",errors="ignore")
    tree=ast.parse(src)
    out=[]
    for node in tree.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            if isinstance(node,ast.Assign):
                targets=node.targets; value=node.value
            else:
                targets=[node.target]; value=node.value
            for t in targets:
                if isinstance(t,ast.Name):
                    name=t.id
                    if any(x in name.upper() for x in ("V028","INPUT","HIST","CLOSE","FLAG","BASE","WORK","RESULT")):
                        out.append({
                            "name":name,
                            "lineno":getattr(node,"lineno",None),
                            "expression":ast.get_source_segment(src,value),
                        })
    return out


def upstream_files_from_source(constants):
    names=set()
    pattern = re.compile(r'["\']([^"\']+\.(?:json|csv|tsv|md|txt))["\']', re.I)
    for c in constants:
        expr=c.get("expression") or ""
        for m in pattern.finditer(expr):
            names.add(m.group(1))
    files=[]
    for name in names:
        for root in (BASE,WORK):
            p=root/name
            if p.is_file():
                files.append(p)
    return sorted(set(files))


def fallback_upstream_files():
    files=[]
    for root in (BASE,WORK):
        if not root.exists():continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".json",".csv",".tsv"):
                continue
            low=p.name.lower()
            if ("closehit" in low or "historical" in low) and ("v028h" in low or "v028i" in low):
                files.append(p)
    return sorted(set(files))


def match_record(path,kind,obj_path,d,rank,science):
    cps=coord_candidates(d)
    best=None
    for rk,dk,ra,dec in cps:
        sep=angsep_arcsec(science[rank]["ra_deg"],science[rank]["dec_deg"],ra,dec)
        if best is None or sep<best[-1]:
            best=(rk,dk,ra,dec,sep)
    return {
        "strict_rank":rank,
        "source_file":str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "source_kind":kind,
        "object_path":obj_path,
        "matched_aflags":KNOWN[rank]["aflags"],
        "matched_bflags":KNOWN[rank]["bflags"],
        "coordinate_fields":None if best is None else f"{best[0]}/{best[1]}",
        "object_ra_deg":None if best is None else best[2],
        "object_dec_deg":None if best is None else best[3],
        "science_sep_arcsec":None if best is None else best[4],
        "provenance_json":json.dumps(scalar_provenance(d),sort_keys=True,default=str),
    }


def scan_json(path,science):
    matches=[]
    try:
        obj=json.loads(path.read_text(encoding="utf-8",errors="ignore"))
    except Exception:
        return matches
    for jpath,d in recursive_dicts(obj):
        rh=rank_hint(d)
        ranks=[rh] if rh in RANKS else list(KNOWN)
        for rank in ranks:
            if exact_flag_match(d,rank):
                matches.append(match_record(path,"JSON",jpath,d,rank,science))
    return matches


def scan_csv_file(path,science):
    matches=[]
    try:
        delim="\t" if path.suffix.lower()==".tsv" else ","
        with path.open("r",encoding="utf-8-sig",newline="") as fh:
            rows=list(csv.DictReader(fh,delimiter=delim))
    except Exception:
        return matches
    for idx,d in enumerate(rows):
        rh=rank_hint(d)
        ranks=[rh] if rh in RANKS else list(KNOWN)
        for rank in ranks:
            if exact_flag_match(d,rank):
                matches.append(match_record(path,"CSV_OR_TSV",f"ROW[{idx}]",d,rank,science))
    return matches


def main():
    print("="*128)
    print("ORDER 01 — EXACT v028i HISTORICAL-HIT FLAG SOURCE PROVENANCE v028au")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE,V028I_JSON,V028I_CSV,V028I_TOOL):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    science=resolve_science()
    v028i=json.loads(V028I_JSON.read_text(encoding="utf-8"))

    constants=ast_path_constants(V028I_TOOL)
    blocks=source_blocks(V028I_TOOL)
    upstream=upstream_files_from_source(constants)
    for p in fallback_upstream_files():
        if p not in upstream:
            upstream.append(p)
    upstream=sorted(set(upstream))

    print("Original v028i path/input constants:")
    for c in constants:
        print(f"  line {c['lineno']}: {c['name']} = {c['expression']}")

    print("\nImmediate/pre-v028i historical-closehit artifacts inspected:")
    for p in upstream:
        print("  "+str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p))

    results=v028i.get("results",[])
    print("\nExact v028i result provenance fields:")
    v028i_full=[]
    for idx,r in enumerate(results):
        if not isinstance(r,dict):continue
        rank=rank_hint(r)
        if rank not in RANKS:continue
        prov=scalar_provenance(r)
        v028i_full.append({"strict_rank":rank,"result_index":idx,"provenance":prov})
        print(f"\n  #{rank} result[{idx}]")
        for k,v in prov.items():
            print(f"    {k}={v}")

    matches=[]
    for p in upstream:
        if p.suffix.lower()==".json":
            matches.extend(scan_json(p,science))
        elif p.suffix.lower() in (".csv",".tsv"):
            matches.extend(scan_csv_file(p,science))

    dedup={}
    for m in matches:
        sig=(
            m["strict_rank"],m["source_file"],m["object_path"],
            m["coordinate_fields"],m["object_ra_deg"],m["object_dec_deg"],
            m["provenance_json"],
        )
        dedup[sig]=m
    matches=list(dedup.values())

    print("\nExact upstream flag-value matches:")
    summaries=[]
    for rank in RANKS:
        q=[m for m in matches if m["strict_rank"]==rank]
        q.sort(key=lambda m:(
            m["science_sep_arcsec"] is None,
            float("inf") if m["science_sep_arcsec"] is None else m["science_sep_arcsec"],
            m["source_file"],m["object_path"]
        ))
        print(f"\n  #{rank}: matches={len(q)}")
        for m in q[:20]:
            sep="n/a" if m["science_sep_arcsec"] is None else f"{m['science_sep_arcsec']:.3f}\""
            print(f"    sep={sep} {m['source_file']} @ {m['object_path']}")
            print(f"      {m['provenance_json'][:1800]}")

        coords=[m for m in q if m["science_sep_arcsec"] is not None]
        nearest=min(coords,key=lambda m:m["science_sep_arcsec"]) if coords else None
        summaries.append({
            "strict_rank":rank,
            "known_aflags":KNOWN.get(rank,{}).get("aflags"),
            "known_bflags":KNOWN.get(rank,{}).get("bflags"),
            "exact_upstream_match_count":len(q),
            "coordinate_bearing_match_count":len(coords),
            "nearest_coordinate_bearing_match_sep_arcsec":
                None if nearest is None else nearest["science_sep_arcsec"],
            "nearest_coordinate_bearing_match_file":
                None if nearest is None else nearest["source_file"],
            "nearest_coordinate_bearing_match_path":
                None if nearest is None else nearest["object_path"],
            "nearest_coordinate_bearing_provenance_json":
                None if nearest is None else nearest["provenance_json"],
        })

    payload={
        "stage":"ORDER01_DASCH_V028I_EXACT_HISTORICAL_HIT_SOURCE_PROVENANCE_V028AU",
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "original_v028i_source_followed":True,
            "flag_values_matched_exactly":True,
            "only_pre_or_at_v028i_historical_closehit_artifacts_scanned":True,
        },
        "source_file":str(V028I_TOOL.relative_to(ROOT)),
        "source_path_constants":constants,
        "source_blocks":blocks,
        "upstream_files":[str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p) for p in upstream],
        "v028i_result_provenance":v028i_full,
        "summaries":summaries,
        "exact_upstream_matches":matches,
        "interpretive_boundary":(
            "v028au identifies the exact historical-hit object from which each old "
            "v028i flag set was decoded. Only a coordinate/plate association to the "
            "frozen ai43437 science endpoint would justify treating those flags as "
            "direct quality metadata for that science feature."
        ),
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,summaries,list(summaries[0]))

    txt=["ORDER 01 — exact v028i historical-hit source provenance v028au\n",
         "=== ORIGINAL v028i SOURCE BLOCKS ===\n"]
    for b in blocks:
        txt.append(f"\n--- lines {b['start_line']}-{b['end_line']} ---\n{b['text']}\n")
    txt.append("\n=== FULL v028i RESULT PROVENANCE ===\n")
    txt.append(json.dumps(v028i_full,indent=2,sort_keys=True,default=str))
    txt.append("\n=== EXACT UPSTREAM MATCHES ===\n")
    txt.append(json.dumps(matches,indent=2,sort_keys=True,default=str))
    OUT_TXT.write_text("\n".join(txt),encoding="utf-8")

    md=[
        "# ORDER 01 — Exact v028i Historical-Hit Source Provenance v028au","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No endpoint state was changed.",
        "- The original v028i source and immediate pre-/at-v028i close-hit artifacts were followed.",
        "- Flag numerical values were matched exactly.","",
        "## Per-rank source recovery","",
        "| rank | exact matches | coordinate-bearing matches | nearest recovered source-object separation |",
        "|---:|---:|---:|---:|"
    ]
    for r in summaries:
        sep=r["nearest_coordinate_bearing_match_sep_arcsec"]
        md.append(
            f"| #{r['strict_rank']} | {r['exact_upstream_match_count']} | "
            f"{r['coordinate_bearing_match_count']} | "
            f"{'—' if sep is None else f'{sep:.3f}″'} |"
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
