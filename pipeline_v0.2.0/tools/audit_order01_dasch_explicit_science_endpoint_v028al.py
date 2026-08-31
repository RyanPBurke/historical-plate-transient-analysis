#!/usr/bin/env python3
"""
ORDER 01 — explicit DASCH science-endpoint vs reference-source audit v028al

Purpose
-------
v028ak isolated the original DASCH/DR7 evidence layer, but its generic coordinate
matcher still reported false 0" matches because nested v028r objects contain both
copied science coordinates and `official_fit_ra_deg/official_fit_dec_deg`.

v028al removes that ambiguity.

For each preserved DASCH endpoint:
  1. Read the v028r `science_nearest_official_sources` row by strict_rank.
  2. Compute the separation using ONLY the explicit
     `official_fit_ra_deg/official_fit_dec_deg` fields.
  3. Parse the raw rank-scoped ai43437 platephot cache directly and recover every
     plausible ACTUAL source/fitted position, rejecting query/input/target/centre
     coordinates.
  4. Deduplicate those raw platephot positions and report the nearest rows to the
     science endpoint.
  5. Inspect v028s/v028t source-consensus/reference rows and classify them as
     REFERENCE_ASTROMETRY_ONLY unless the reference star's own propagated/catalogue
     coordinate is actually near the science endpoint.

No endpoint disposition is changed here.

NO network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
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

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
V028R = BASE / "order01_official_dasch_platephot_astrometry_v028r.json"
V028S = BASE / "order01_official_dasch_catalog_lightcurve_astrometry_v028s.json"
V028T = BASE / "order01_official_dasch_ai43437_row_audit_v028t.json"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_explicit_science_endpoint_audit_v028al.json"
OUT_CSV = BASE / "order01_dasch_explicit_science_endpoint_audit_v028al.csv"
OUT_RAW = BASE / "order01_dasch_raw_platephot_near_science_rows_v028al.csv"
OUT_REF = BASE / "order01_dasch_reference_evidence_classification_v028al.csv"
OUT_MD = BASE / "ORDER01_DASCH_EXPLICIT_SCIENCE_ENDPOINT_AUDIT_V028AL.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
KEEP_RAW_NEAREST = 12
MAX_RAW_NEAR_ARCSEC = 120.0
REFERENCE_NEAR_ARCSEC = 10.0

BAD_COORD_TOKENS = (
    "query","input","target","center","centre","search","requested","cone",
    "science","candidate"
)

ACTUAL_COORD_PAIRS = (
    ("official_fit_ra_deg","official_fit_dec_deg"),
    ("fit_ra_deg","fit_dec_deg"),
    ("ra_fit_deg","dec_fit_deg"),
    ("fitted_ra_deg","fitted_dec_deg"),
    ("ra_fit","dec_fit"),
    ("fit_ra","fit_dec"),
    ("fitted_ra","fitted_dec"),
    ("ra_deg","dec_deg"),
    ("ra","dec"),
)

INTERESTING = (
    "flag","drad","source","atlas","apass","object","catalog","mag","flux",
    "fwhm","ellip","blend","defect","neighbor","neighbour","radial","status",
    "detect","nondetect","image_x","image_y","x_image","y_image","iso"
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


def flatten_scalars(obj,prefix="",depth=0,max_depth=4,out=None):
    if out is None:out={}
    if depth>max_depth:return out
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
            elif isinstance(v,list) and len(v)<=16 and all(
                isinstance(x,(str,int,float,bool)) or x is None for x in v
            ):
                out[key]=v
            elif isinstance(v,(dict,list)):
                flatten_scalars(v,key,depth+1,max_depth,out)
    elif isinstance(obj,list):
        for j,v in enumerate(obj[:32]):
            key=f"{prefix}[{j}]"
            if isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
            elif isinstance(v,(dict,list)):
                flatten_scalars(v,key,depth+1,max_depth,out)
    return out


def recursive_dicts(obj,path="$",out=None,depth=0):
    if out is None:out=[]
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


def actual_positions_from_dict(row):
    """
    Extract plausible source/fitted positions from THIS dict only.
    Do not pair coordinates inherited from parent/child objects.
    """
    kn={norm(k):k for k in row}
    out=[]
    seen=set()

    for ra_name,dec_name in ACTUAL_COORD_PAIRS:
        rk=kn.get(norm(ra_name)); dk=kn.get(norm(dec_name))
        if rk is None or dk is None:continue
        label=(str(rk)+" "+str(dk)).lower()
        if any(t in label for t in BAD_COORD_TOKENS):continue
        ra=f(row[rk]);dec=f(row[dk])
        if ra is None or dec is None or not (0<=ra<360 and -90<=dec<=90):
            continue
        key=(round(ra,10),round(dec,10),str(rk),str(dk))
        if key not in seen:
            seen.add(key)
            out.append((ra,dec,str(rk),str(dk)))

    # Fallback pair only when keys are in the same dictionary.
    ras=[];decs=[]
    for k,v in row.items():
        kl=str(k).lower()
        if any(t in kl for t in BAD_COORD_TOKENS):continue
        val=f(v)
        if val is None:continue
        nk=norm(k)
        if (
            nk=="ra" or nk=="radeg" or nk.endswith("radeg") or
            nk in {"rafit","fitra","fittedra","officialfitradeg"}
        ) and 0<=val<360:
            ras.append((k,val))
        if (
            nk=="dec" or nk=="decdeg" or nk.endswith("decdeg") or
            nk in {"decfit","fitdec","fitteddec","officialfitdecdeg"}
        ) and -90<=val<=90:
            decs.append((k,val))
    for rk,ra in ras:
        for dk,dec in decs:
            key=(round(ra,10),round(dec,10),str(rk),str(dk))
            if key not in seen:
                seen.add(key)
                out.append((ra,dec,str(rk),str(dk)))
    return out


def compact_fields(row):
    out={}
    for k,v in row.items():
        kl=str(k).lower()
        if any(t in kl for t in INTERESTING):
            out[str(k)]=v
        if len(out)>=50:break
    return out


def raw_platephot_candidates(path,science_ra,science_dec):
    try:
        obj=json.loads(path.read_text(encoding="utf-8",errors="ignore"))
    except Exception as e:
        return [],f"JSON_PARSE_ERROR:{e}"

    rows=[]
    for jpath,d in recursive_dicts(obj):
        for ra,dec,rk,dk in actual_positions_from_dict(d):
            sep=angsep_arcsec(science_ra,science_dec,ra,dec)
            if sep>MAX_RAW_NEAR_ARCSEC:
                continue
            rows.append({
                "json_path":jpath,
                "row_ra_deg":ra,
                "row_dec_deg":dec,
                "ra_field":rk,
                "dec_field":dk,
                "science_sep_arcsec":sep,
                "interesting_fields":compact_fields(d),
            })

    # Deduplicate same source coordinates/fields repeated at nested levels.
    dedup={}
    for r in rows:
        sig=(
            round(r["row_ra_deg"],8),round(r["row_dec_deg"],8),
            r["ra_field"],r["dec_field"],
            json.dumps(r["interesting_fields"],sort_keys=True,default=str)
        )
        if sig not in dedup:
            rr=dict(r);rr["duplicate_count"]=1;dedup[sig]=rr
        else:
            dedup[sig]["duplicate_count"]+=1
    q=list(dedup.values())
    q.sort(key=lambda r:r["science_sep_arcsec"])
    return q[:KEEP_RAW_NEAREST],"OK"


def main():
    print("="*128)
    print("ORDER 01 — EXPLICIT DASCH SCIENCE-ENDPOINT VS REFERENCE-SOURCE AUDIT v028al")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE,V028R,V028S,V028T):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

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
        q=[r for r in native if str(r.get("tile_id",""))==tile and i(r.get("candidate_index"))==idx]
        if len(q)!=1:
            raise RuntimeError(f"#{rank}: DASCH science row resolution failed")
        nr=q[0]
        science[rank]={
            "ra":f(nr["ra_deg"]),"dec":f(nr["dec_deg"]),
            "tile_id":tile,"candidate_index":idx,
            "snr":f(nr["snr"]),"polarity":i(nr["polarity"]),
        }

    rj=json.loads(V028R.read_text(encoding="utf-8"))
    sj=json.loads(V028S.read_text(encoding="utf-8"))
    tj=json.loads(V028T.read_text(encoding="utf-8"))

    r_sources={
        i(x.get("strict_rank")):x
        for x in rj.get("science_nearest_official_sources",[])
        if i(x.get("strict_rank")) in RANKS
    }

    # v028s results are reference-source evidence; compute their own epoch
    # coordinate separation from the science endpoint.
    s_results=[
        x for x in sj.get("results",[])
        if i(x.get("strict_rank")) in RANKS
    ]

    # v028t source consensus is reference-source consensus, not automatically
    # a science detection.
    t_consensus=[
        x for x in tj.get("source_consensus",[])
        if i(x.get("strict_rank")) in RANKS
    ]

    summaries=[]
    raw_rows=[]
    ref_rows=[]

    print("Explicit v028r fitted-source distances and raw rank-scoped platephot evidence:\n")

    for rank in RANKS:
        s=science[rank]
        rr=r_sources.get(rank)

        if rr is None:
            fit_ra=fit_dec=fit_sep=None
        else:
            fit_ra=f(rr.get("official_fit_ra_deg"))
            fit_dec=f(rr.get("official_fit_dec_deg"))
            fit_sep=None if None in (fit_ra,fit_dec) else angsep_arcsec(
                s["ra"],s["dec"],fit_ra,fit_dec
            )

        raw_path=RAW_DIR/f"{PLATE}_sol0_rank{rank}_apass_platephot.json"
        if not raw_path.is_file():
            raw_candidates=[]
            raw_status="MISSING_RAW_PLATEPHOT_CACHE"
        else:
            raw_candidates,raw_status=raw_platephot_candidates(
                raw_path,s["ra"],s["dec"]
            )

        raw_nearest=raw_candidates[0]["science_sep_arcsec"] if raw_candidates else None
        raw_within3=sum(r["science_sep_arcsec"]<=3 for r in raw_candidates)
        raw_within5=sum(r["science_sep_arcsec"]<=5 for r in raw_candidates)
        raw_within10=sum(r["science_sep_arcsec"]<=10 for r in raw_candidates)

        for r in raw_candidates:
            raw_rows.append({
                "strict_rank":rank,
                "source_file":str(raw_path.relative_to(ROOT)) if raw_path.is_relative_to(ROOT) else str(raw_path),
                "science_sep_arcsec":r["science_sep_arcsec"],
                "row_ra_deg":r["row_ra_deg"],
                "row_dec_deg":r["row_dec_deg"],
                "ra_field":r["ra_field"],
                "dec_field":r["dec_field"],
                "json_path":r["json_path"],
                "duplicate_count":r["duplicate_count"],
                "interesting_fields_json":json.dumps(r["interesting_fields"],sort_keys=True,default=str),
            })

        # Reference evidence classification.
        rank_refs=[]
        for x in s_results:
            if i(x.get("strict_rank"))!=rank:continue
            gra=f(x.get("gaia_ra_1951_deg"));gdec=f(x.get("gaia_dec_1951_deg"))
            sep=None if None in (gra,gdec) else angsep_arcsec(s["ra"],s["dec"],gra,gdec)
            rec={
                "strict_rank":rank,
                "source_layer":"v028s",
                "source_id":x.get("source_id"),
                "status":x.get("status"),
                "reference_ra_1951_deg":gra,
                "reference_dec_1951_deg":gdec,
                "science_sep_arcsec":sep,
                "classification":
                    "POTENTIAL_SCIENCE_ASSOCIATION" if sep is not None and sep<=REFERENCE_NEAR_ARCSEC
                    else "REFERENCE_ASTROMETRY_ONLY",
                "apass_status":None,
                "atlas_status":None,
            }
            rank_refs.append(rec);ref_rows.append(rec)

        for x in t_consensus:
            if i(x.get("strict_rank"))!=rank:continue
            sid=str(x.get("source_id"))
            # Attach separation from matching v028s source if available.
            match=[r for r in rank_refs if str(r["source_id"])==sid]
            sep=match[0]["science_sep_arcsec"] if match else None
            rec={
                "strict_rank":rank,
                "source_layer":"v028t",
                "source_id":sid,
                "status":"SOURCE_CONSENSUS",
                "reference_ra_1951_deg":None,
                "reference_dec_1951_deg":None,
                "science_sep_arcsec":sep,
                "classification":
                    "POTENTIAL_SCIENCE_ASSOCIATION" if sep is not None and sep<=REFERENCE_NEAR_ARCSEC
                    else "REFERENCE_ASTROMETRY_ONLY",
                "apass_status":x.get("apass_status"),
                "atlas_status":x.get("atlas_status"),
            }
            ref_rows.append(rec)

        summaries.append({
            "strict_rank":rank,
            "science_ra_deg":s["ra"],
            "science_dec_deg":s["dec"],
            "science_snr":s["snr"],
            "science_polarity":s["polarity"],
            "v028r_explicit_official_fit_ra_deg":fit_ra,
            "v028r_explicit_official_fit_dec_deg":fit_dec,
            "v028r_explicit_official_fit_sep_arcsec":fit_sep,
            "v028r_aflags":None if rr is None else rr.get("aflags"),
            "v028r_bflags":None if rr is None else rr.get("bflags"),
            "v028r_drad_rms2":None if rr is None else rr.get("drad_rms2"),
            "v028r_flux_iso":None if rr is None else rr.get("flux_iso"),
            "raw_platephot_cache_status":raw_status,
            "raw_unique_position_rows_retained":len(raw_candidates),
            "raw_nearest_position_sep_arcsec":raw_nearest,
            "raw_position_rows_within3arcsec":raw_within3,
            "raw_position_rows_within5arcsec":raw_within5,
            "raw_position_rows_within10arcsec":raw_within10,
            "reference_rows_classified_science_association":
                sum(r["classification"]=="POTENTIAL_SCIENCE_ASSOCIATION" for r in ref_rows if r["strict_rank"]==rank),
        })

        print(
            f"#{rank}: v028r explicit fit sep="
            f"{'n/a' if fit_sep is None else f'{fit_sep:.3f}\"'}; "
            f"raw platephot nearest="
            f"{'n/a' if raw_nearest is None else f'{raw_nearest:.3f}\"'}; "
            f"within3/5/10={raw_within3}/{raw_within5}/{raw_within10}; "
            f"rawStatus={raw_status}"
        )

    payload={
        "stage":"ORDER01_DASCH_EXPLICIT_SCIENCE_ENDPOINT_VS_REFERENCE_SOURCE_AUDIT_V028AL",
        "plate":PLATE,
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "v028r_parent_coordinate_alias_rejected":True,
            "explicit_official_fit_fields_used":True,
            "raw_rank_scoped_platephot_cache_parsed":True,
            "reference_star_rows_not_treated_as_science_detections":True,
        },
        "summaries":summaries,
        "raw_platephot_near_science_rows":raw_rows,
        "reference_evidence":ref_rows,
        "interpretive_boundary":(
            "v028al distinguishes the preserved DASCH science coordinate from "
            "reference-star calibration evidence. The explicit v028r fitted-source "
            "separation is calculated only from official_fit_ra/dec. Raw rank-scoped "
            "platephot caches are inspected independently for actual source positions. "
            "No absence or presence of a nearby official row is, by itself, sufficient "
            "to classify a DASCH endpoint as astrophysical or artefactual."
        )
    }
    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,summaries,list(summaries[0]))
    write_csv(
        OUT_RAW,raw_rows,
        ["strict_rank","source_file","science_sep_arcsec","row_ra_deg","row_dec_deg",
         "ra_field","dec_field","json_path","duplicate_count","interesting_fields_json"]
    )
    write_csv(
        OUT_REF,ref_rows,
        ["strict_rank","source_layer","source_id","status","reference_ra_1951_deg",
         "reference_dec_1951_deg","science_sep_arcsec","classification",
         "apass_status","atlas_status"]
    )

    md=[
        "# ORDER 01 — Explicit DASCH Science-Endpoint vs Reference-Source Audit v028al","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- v028r copied science coordinates are not used to compute fitted-source separation.",
        "- Only explicit `official_fit_ra_deg/official_fit_dec_deg` fields are used for the v028r distance.",
        "- Raw rank-scoped ai43437 platephot caches are parsed independently.",
        "- v028s/v028t reference-star rows are not automatically treated as science detections.",
        "- No endpoint state was changed.","",
        "## Explicit source-distance results","",
        "| rank | v028r explicit fit sep | raw platephot nearest | <=3″ | <=5″ | <=10″ |",
        "|---:|---:|---:|---:|---:|---:|"
    ]
    for r in summaries:
        a=r["v028r_explicit_official_fit_sep_arcsec"]
        b=r["raw_nearest_position_sep_arcsec"]
        md.append(
            f"| #{r['strict_rank']} | "
            f"{'—' if a is None else f'{a:.3f}″'} | "
            f"{'—' if b is None else f'{b:.3f}″'} | "
            f"{r['raw_position_rows_within3arcsec']} | "
            f"{r['raw_position_rows_within5arcsec']} | "
            f"{r['raw_position_rows_within10arcsec']} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_RAW}")
    print(f"  {OUT_REF}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
