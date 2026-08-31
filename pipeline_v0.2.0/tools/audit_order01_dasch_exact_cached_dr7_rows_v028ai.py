#!/usr/bin/env python3
"""
ORDER 01 — exact cached official DR7 row extractor v028ai

Purpose
-------
v028ah intentionally performed a broad evidence inventory and therefore
over-counted repeated cached rows and query metadata. v028ai narrows that
inventory to the official DR7 rows that can actually bear on the six preserved
DASCH endpoints.

Rules
-----
* NO network access.
* NO science pixels read.
* Frozen detector is NOT rerun.
* No candidate state mutation.
* Exact physical plate ai43437 is required either from a row field or, when the
  cached artifact itself is explicitly plate-scoped, from the filename/path.
* Candidate matching uses ACTUAL row sky-position fields. Query/input/centre
  coordinates are explicitly rejected as evidence coordinates.
* Repeated rows copied across cached artifacts are deduplicated.
* Results are descriptive evidence extraction only; no astrophysical
  adjudication is made here.

Outputs contain the nearest unique official rows per candidate separately for
querycat, lightcurve, platephot, and other DR7 contexts, plus field/schema
diagnostics so the next stage can adjudicate the exact official evidence.
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
INV_FILES = BASE / "order01_dasch_preserved_endpoint_evidence_files_v028ah.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"

OUT_JSON = BASE / "order01_dasch_exact_cached_dr7_rows_v028ai.json"
OUT_CSV = BASE / "order01_dasch_exact_cached_dr7_rows_v028ai.csv"
OUT_SCHEMA = BASE / "order01_dasch_exact_cached_dr7_schema_v028ai.csv"
OUT_MD = BASE / "ORDER01_DASCH_EXACT_CACHED_DR7_ROWS_V028AI.md"

RANKS = [10,24,25,26,29,30]
PLATE = "ai43437"
MAX_SEP_ARCSEC = 30.0
KEEP_PER_CONTEXT = 12
MAX_FILE_BYTES = 80_000_000

ROW_PLATE_KEYS = {
    "plate","plateid","plate_id","plate_id_str","plateidstr","plate_name",
    "plate_name_id","platenum","plate_num","plate_number","platekey",
    "exposure","exposure_id","exposureid"
}

# Prioritized ACTUAL detection/source position pairs.
POSITION_PAIRS = [
    ("ra_fit","dec_fit"),
    ("fit_ra","fit_dec"),
    ("fitted_ra","fitted_dec"),
    ("ra_fitted","dec_fitted"),
    ("ra_deg","dec_deg"),
    ("ra2000","dec2000"),
    ("ra_j2000","dec_j2000"),
    ("raj2000","dej2000"),
    ("ra","dec"),
    ("RA","DEC"),
]

BAD_COORD_TOKENS = {
    "query","input","target","search","center","centre","cone","requested",
    "request","field_center","fieldcentre","fieldcenter","origin"
}


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
        return int(float(str(v).strip()))
    except Exception:
        return default


def norm(s):
    return re.sub(r"[^a-z0-9]+","",str(s).lower())


def pick(row,*names,default=None):
    nm={norm(k):k for k in row}
    for name in names:
        q=norm(name)
        if q in nm:
            return row[nm[q]]
    return default


def angsep_arcsec(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c=max(-1.0,min(1.0,c))
    return math.degrees(math.acos(c))*3600.0


def parse_rows(path):
    suf=path.suffix.lower()
    try:
        if suf==".csv":
            return read_csv(path)
        if suf==".tsv":
            with path.open("r",encoding="utf-8-sig",newline="") as fh:
                return list(csv.DictReader(fh,delimiter="\t"))
        if suf==".json":
            obj=json.loads(path.read_text(encoding="utf-8",errors="ignore"))
            rows=[]
            def walk(x,depth=0):
                if depth>4:return
                if isinstance(x,list):
                    if x and all(isinstance(z,dict) for z in x):
                        rows.extend(x)
                    else:
                        for z in x: walk(z,depth+1)
                elif isinstance(x,dict):
                    # Treat dict itself as a row only if it looks tabular/source-like.
                    keys={norm(k) for k in x}
                    if any(k in keys for k in ("ra","radeg","rafit","fitra","fittedra")) and \
                       any(k in keys for k in ("dec","decdeg","decfit","fitdec","fitteddec")):
                        rows.append(x)
                    for z in x.values():
                        if isinstance(z,(list,dict)): walk(z,depth+1)
            walk(obj)
            return rows
    except Exception:
        return []
    return []


def context_for(path):
    low=str(path).lower()
    if "querycat" in low:return "querycat"
    if "lightcurve" in low:return "lightcurve"
    if "platephot" in low:return "platephot"
    if any(x in low for x in ("v028u","fitted_position","fitted-position")):
        return "fitted_position"
    return "other_dr7"


def path_plate_scoped(path):
    low=str(path).lower()
    return PLATE in low


def row_plate_value(row):
    for k,v in row.items():
        if norm(k) in {norm(x) for x in ROW_PLATE_KEYS}:
            sv=str(v).strip().lower()
            if sv:
                return sv
    # Also permit exact ai43437 in a clearly plate-like field.
    for k,v in row.items():
        if "plate" in str(k).lower() and PLATE in str(v).lower():
            return str(v).strip().lower()
    return None


def actual_position(row):
    """
    Return (ra,dec,ra_key,dec_key), rejecting query/input/target coordinates.
    """
    # exact pair priority
    keys=list(row.keys())
    kn={norm(k):k for k in keys}
    for ra_name,dec_name in POSITION_PAIRS:
        rk=kn.get(norm(ra_name)); dk=kn.get(norm(dec_name))
        if rk is None or dk is None:
            continue
        lk=(str(rk)+" "+str(dk)).lower()
        if any(tok in lk for tok in BAD_COORD_TOKENS):
            continue
        ra=f(row[rk]); dec=f(row[dk])
        if ra is not None and dec is not None and 0<=ra<360 and -90<=dec<=90:
            return ra,dec,rk,dk

    # fallback: find one RA-like and DEC-like field without bad tokens
    ras=[];decs=[]
    for k,v in row.items():
        kl=str(k).lower()
        if any(tok in kl for tok in BAD_COORD_TOKENS):
            continue
        nk=norm(k)
        val=f(v)
        if val is None:continue
        if (nk=="ra" or nk.startswith("ra") or nk.endswith("ra")) and 0<=val<360:
            ras.append((k,val))
        if (nk=="dec" or nk.startswith("dec") or nk.startswith("de") or nk.endswith("dec")) and -90<=val<=90:
            decs.append((k,val))
    if ras and decs:
        return ras[0][1],decs[0][1],ras[0][0],decs[0][0]
    return None


def source_identity(row):
    preferred=[
        "source_id","sourceid","object_id","objectid","ref_id","refid",
        "atlas_id","atlasid","apass_id","apassid","match_id","matchid",
        "catalog_id","catalogid"
    ]
    vals=[]
    for name in preferred:
        v=pick(row,name)
        if v is not None and str(v).strip()!="":
            vals.append(f"{name}={str(v).strip()}")
    return ";".join(vals[:4])


def flag_summary(row):
    vals=[]
    for k,v in row.items():
        kl=str(k).lower()
        if "flag" in kl or norm(k) in {"a","b","aflag","bflag"}:
            sv=str(v).strip()
            if sv!="":
                vals.append(f"{k}={sv}")
    return ";".join(vals[:12])


def magnitude_summary(row):
    vals=[]
    for k,v in row.items():
        kl=str(k).lower()
        if "mag" in kl and len(vals)<8:
            sv=str(v).strip()
            if sv!="":
                vals.append(f"{k}={sv}")
    return ";".join(vals)


def canonical_key(context,plate,ra,dec,row):
    sid=source_identity(row)
    flags=flag_summary(row)
    mags=magnitude_summary(row)
    # ~0.01 arcsec coordinate rounding; enough to collapse repeated cached copies.
    return (
        context,
        plate or "",
        round(ra,7),
        round(dec,7),
        sid,
        flags,
        mags,
    )


def main():
    print("="*128)
    print("ORDER 01 — EXACT CACHED OFFICIAL DR7 ROW EXTRACTOR v028ai")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,INV_FILES,STRICT,DASCH_NATIVE):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("closure guard mismatch")

    strict_rows=read_csv(STRICT)
    native=read_csv(DASCH_NATIVE)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in RANKS}
    if sorted(strict)!=RANKS:
        raise RuntimeError("strict-rank guard mismatch")

    science={}
    for rank in RANKS:
        sr=strict[rank]
        tile=str(pick(sr,"dasch_tile_id"))
        idx=i(pick(sr,"dasch_candidate_index","dasch_index","dasch_native_candidate_index"))
        q=[r for r in native
           if str(r.get("tile_id",""))==tile and i(r.get("candidate_index"))==idx]
        if len(q)!=1:
            raise RuntimeError(f"#{rank}: science row resolution failed ({len(q)})")
        nr=q[0]
        science[rank]={
            "ra":f(nr["ra_deg"]),"dec":f(nr["dec_deg"]),
            "tile_id":tile,"candidate_index":idx,
            "snr":f(nr["snr"]),"polarity":i(nr["polarity"])
        }

    inv=read_csv(INV_FILES)
    paths=[]
    seen_paths=set()
    for r in inv:
        raw=r.get("path") or r.get("relative_path")
        if not raw:continue
        p=Path(raw)
        if not p.is_absolute():
            p=ROOT/p
        try:
            rp=str(p.resolve())
        except Exception:
            rp=str(p)
        if rp in seen_paths:continue
        seen_paths.add(rp)
        if p.is_file() and p.stat().st_size<=MAX_FILE_BYTES:
            paths.append(p)

    print(f"Cached evidence artifacts to inspect: {len(paths)}")

    unique={}
    schema=defaultdict(lambda: {
        "files":set(),"row_count":0,"position_pairs":defaultdict(int),
        "plate_confirmed_rows":0
    })

    for fi,p in enumerate(paths,1):
        ctx=context_for(p)
        rows=parse_rows(p)
        if not rows:continue
        sc=schema[ctx]
        sc["files"].add(str(p))
        sc["row_count"] += len(rows)

        file_plate=path_plate_scoped(p)

        for rownum,row in enumerate(rows):
            pos=actual_position(row)
            if pos is None:continue
            ra,dec,rak,deck=pos
            sc["position_pairs"][f"{rak}|{deck}"] += 1

            rv=row_plate_value(row)
            row_plate_exact=(rv is not None and PLATE in rv)
            plate_confirmed=row_plate_exact or file_plate
            if not plate_confirmed:
                continue
            sc["plate_confirmed_rows"] += 1

            # Only retain rows close to at least one science endpoint.
            nearest=[]
            for rank,s in science.items():
                sep=angsep_arcsec(s["ra"],s["dec"],ra,dec)
                if sep<=MAX_SEP_ARCSEC:
                    nearest.append((sep,rank))
            if not nearest:
                continue

            plate_value=rv if rv is not None else f"PATH_SCOPED:{PLATE}"
            key=canonical_key(ctx,plate_value,ra,dec,row)

            if key not in unique:
                unique[key]={
                    "context":ctx,
                    "plate_value":plate_value,
                    "row_ra_deg":ra,
                    "row_dec_deg":dec,
                    "ra_field":str(rak),
                    "dec_field":str(deck),
                    "source_identity":source_identity(row),
                    "flags":flag_summary(row),
                    "magnitudes":magnitude_summary(row),
                    "first_source_file":str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                    "first_row_number":rownum,
                    "duplicate_copy_count":1,
                    "nearby_ranks":{},
                    "raw_selected_fields":{},
                }
                # Preserve compact scientifically likely useful fields.
                for k,v in row.items():
                    kl=str(k).lower()
                    if any(tok in kl for tok in (
                        "flag","mag","drad","radius","fwhm","ellip","blend",
                        "defect","neighbor","neighbour","x","y","source","object",
                        "atlas","apass","match","plate"
                    )):
                        if len(unique[key]["raw_selected_fields"])<40:
                            unique[key]["raw_selected_fields"][str(k)]=v
            else:
                unique[key]["duplicate_copy_count"] += 1

            rec=unique[key]
            for sep,rank in nearest:
                old=rec["nearby_ranks"].get(str(rank))
                if old is None or sep<old:
                    rec["nearby_ranks"][str(rank)]=sep

    print(f"Unique plate-confirmed rows within {MAX_SEP_ARCSEC:.0f}\" of any science endpoint: {len(unique)}")

    # Expand rank-context matches.
    expanded=[]
    per_rank={}
    for rank,s in science.items():
        byctx=defaultdict(list)
        for rec in unique.values():
            sep=rec["nearby_ranks"].get(str(rank))
            if sep is None:continue
            rr=dict(rec)
            rr["strict_rank"]=rank
            rr["science_sep_arcsec"]=float(sep)
            rr["science_ra_deg"]=s["ra"]
            rr["science_dec_deg"]=s["dec"]
            byctx[rr["context"]].append(rr)

        summary={}
        for ctx,rows in byctx.items():
            rows.sort(key=lambda r:(r["science_sep_arcsec"],-r["duplicate_copy_count"]))
            keep=rows[:KEEP_PER_CONTEXT]
            summary[ctx]={
                "unique_count_within30arcsec":len(rows),
                "nearest_sep_arcsec":keep[0]["science_sep_arcsec"] if keep else None,
                "nearest_source_identity":keep[0]["source_identity"] if keep else "",
                "nearest_flags":keep[0]["flags"] if keep else "",
                "nearest_magnitudes":keep[0]["magnitudes"] if keep else "",
                "nearest_rows":keep,
            }
            for rr in keep:
                expanded.append({
                    "strict_rank":rank,
                    "context":ctx,
                    "science_sep_arcsec":rr["science_sep_arcsec"],
                    "row_ra_deg":rr["row_ra_deg"],
                    "row_dec_deg":rr["row_dec_deg"],
                    "plate_value":rr["plate_value"],
                    "source_identity":rr["source_identity"],
                    "flags":rr["flags"],
                    "magnitudes":rr["magnitudes"],
                    "duplicate_copy_count":rr["duplicate_copy_count"],
                    "ra_field":rr["ra_field"],
                    "dec_field":rr["dec_field"],
                    "first_source_file":rr["first_source_file"],
                    "first_row_number":rr["first_row_number"],
                    "selected_fields_json":json.dumps(rr["raw_selected_fields"],sort_keys=True,default=str),
                })

        per_rank[rank]=summary

    for rank in RANKS:
        print(f"\n#{rank}:")
        for ctx in ("querycat","lightcurve","platephot","fitted_position","other_dr7"):
            q=per_rank[rank].get(ctx)
            if not q:
                print(f"  {ctx:15s}: none")
                continue
            print(
                f"  {ctx:15s}: uniqueN={q['unique_count_within30arcsec']:3d} "
                f"nearest={q['nearest_sep_arcsec']:.3f}\" "
                f"id={q['nearest_source_identity'] or '-'} "
                f"flags={q['nearest_flags'] or '-'}"
            )

    schema_rows=[]
    for ctx,x in sorted(schema.items()):
        pairs=sorted(x["position_pairs"].items(),key=lambda z:(-z[1],z[0]))
        schema_rows.append({
            "context":ctx,
            "file_count":len(x["files"]),
            "parsed_row_count":x["row_count"],
            "plate_confirmed_position_row_count":x["plate_confirmed_rows"],
            "position_pairs":"; ".join(f"{k}:{n}" for k,n in pairs[:20]),
        })

    payload={
        "stage":"ORDER01_DASCH_EXACT_CACHED_DR7_ROWS_V028AI",
        "plate":PLATE,
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "query_input_coordinates_rejected_as_evidence_positions":True,
            "exact_plate_or_plate_scoped_artifact_required":True,
            "duplicate_cached_rows_deduplicated":True,
        },
        "unique_plate_confirmed_nearby_row_count":len(unique),
        "schema":schema_rows,
        "per_rank":{str(k):v for k,v in per_rank.items()},
        "interpretive_boundary":(
            "v028ai extracts and deduplicates cached official-data rows near each "
            "preserved DASCH endpoint. A close official row is evidence about the "
            "catalogue/plate measurement, not proof that the source is astrophysical. "
            "No endpoint disposition is changed here."
        )
    }
    write_json(OUT_JSON,payload)

    fields=[
        "strict_rank","context","science_sep_arcsec","row_ra_deg","row_dec_deg",
        "plate_value","source_identity","flags","magnitudes","duplicate_copy_count",
        "ra_field","dec_field","first_source_file","first_row_number",
        "selected_fields_json"
    ]
    write_csv(OUT_CSV,expanded,fields)
    write_csv(OUT_SCHEMA,schema_rows,list(schema_rows[0]) if schema_rows else
              ["context","file_count","parsed_row_count","plate_confirmed_position_row_count","position_pairs"])

    md=[
        "# ORDER 01 — Exact Cached Official DR7 Row Extractor v028ai","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- Query/input/centre coordinates are rejected as evidence coordinates.",
        "- Exact ai43437 identity or an explicitly ai43437-scoped cached artifact is required.",
        "- Repeated cached rows are deduplicated.",
        "- No endpoint state was changed.","",
        f"Unique plate-confirmed official rows within {MAX_SEP_ARCSEC:.0f} arcsec of any preserved endpoint: **{len(unique)}**.","",
        "## Nearest unique official rows","",
        "| rank | querycat | lightcurve | platephot | fitted-position |",
        "|---:|---|---|---|---|"
    ]
    for rank in RANKS:
        cells=[]
        for ctx in ("querycat","lightcurve","platephot","fitted_position"):
            q=per_rank[rank].get(ctx)
            cells.append("—" if not q else f"{q['nearest_sep_arcsec']:.3f}″ (N={q['unique_count_within30arcsec']})")
        md.append(f"| #{rank} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_SCHEMA}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
