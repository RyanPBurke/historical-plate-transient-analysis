#!/usr/bin/env python3
"""
ORDER 01 — inspect cached official DASCH ai43437 lightcurve rows v028t

Purpose
-------
v028s found an essentially exact DASCH catalog source for each of the eight
frozen v028q primary Gaia controls, and the official DR7 lightcurve endpoint
returned one ai43437/solution-0 row for each attempted exact catalog source.
However, v028s could not form an astrometric reference because the ai43437 rows
did not expose the fitted/catalog position fields it expected.

DASCH DR7 documentation states that fitted image astrometry and catalog-match
astrometry are unavailable for nondetection lightcurve rows. v028t therefore
does no new querying and directly audits the cached lightcurve rows produced
by v028s.

For each of the eight frozen v028q primary Gaia controls and each refcat
(ATLAS/APASS), v028t:
  1. identifies the querycat candidate with the smallest propagated
     catalog-to-Gaia(1951) separation;
  2. opens the cached official DR7 lightcurve response for that exact source;
  3. selects ai43437 / solnum 0;
  4. records whether fitted sky coordinates, catalog coordinates,
     SExtractor source ID, image centroid, calibrated magnitude, and
     limiting magnitude are present;
  5. classifies the official row conservatively as:
       OFFICIAL_DETECTION
       OFFICIAL_NONDETECTION
       OFFICIAL_ROW_AMBIGUOUS
       NO_AI43437_ROW

No network access. No science pixels. No detector rerun. No state mutation.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"
CACHE = WORK / "official_dasch_catalog_lightcurve_v028s"

V028S_JSON = BASE / "order01_official_dasch_catalog_lightcurve_astrometry_v028s.json"
V028Q_REFS = BASE / "order01_plate_registered_bright_gaia_references_v028q.csv"

OUT_JSON = BASE / "order01_official_dasch_ai43437_row_audit_v028t.json"
OUT_CSV = BASE / "order01_official_dasch_ai43437_row_audit_v028t.csv"
OUT_MD = BASE / "ORDER01_OFFICIAL_DASCH_AI43437_ROW_AUDIT_V028T.md"

EXPECTED = [10,24,25,26,29,30]
REFCATS = ("atlas","apass")
PLATE_SERIES = "ai"
PLATE_NUMBER = 43437
SOLUTION_NUMBER = 0


def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
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


def i(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def f(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        x=float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def b(v):
    return str(v).strip().lower() in {"true","1","yes","y","t"}


def pick(row,*names,default=None):
    norm={str(k).lower().replace("_",""):k for k in row}
    for name in names:
        n=str(name).lower().replace("_","")
        if n in norm:
            return row[norm[n]]
    return default


def table_rows(obj):
    if isinstance(obj,dict):
        for k in ("data","rows","records","result"):
            if isinstance(obj.get(k),list):
                obj=obj[k];break
    if not isinstance(obj,list):
        raise RuntimeError(f"unexpected table response {type(obj).__name__}")
    if not obj:
        return []
    if all(isinstance(x,str) for x in obj):
        return list(csv.DictReader(io.StringIO("\n".join(obj))))
    if all(isinstance(x,dict) for x in obj):
        return obj
    raise RuntimeError("mixed table response")


def cache_path(rank,sid,refcat,refnum,gbin):
    tag=f"rank{rank}_gaia{sid}"
    return CACHE/f"{tag}_{refcat}_ref{refnum}_bin{gbin}_lightcurve.json"


def classify(rr):
    fit_ra=f(pick(rr,"raDeg","ra_deg","ra"))
    fit_dec=f(pick(rr,"decDeg","dec_deg","dec"))
    cat_ra=f(pick(rr,"catalogRa","catalog_ra"))
    cat_dec=f(pick(rr,"catalogDec","catalog_dec"))
    image_x=f(pick(rr,"imageX","image_x"))
    image_y=f(pick(rr,"imageY","image_y"))
    sxt=i(pick(rr,"sxtNumber","sxt_number"))
    mag=f(pick(rr,"magcalMagdep","magcal_magdep"))
    lim=f(pick(rr,"limitingMagLocal","limiting_mag_local"))
    flux=f(pick(rr,"fluxIso","flux_iso"))
    fwhm=f(pick(rr,"fwhmImage","fwhm_image"))

    has_fit=(fit_ra is not None and fit_dec is not None)
    has_cat=(cat_ra is not None and cat_dec is not None)
    has_img=(image_x is not None and image_y is not None)
    has_sxt=(sxt is not None)
    has_mag=(mag is not None)
    has_source_measurement=any((has_fit,has_img,has_sxt,has_mag,flux is not None,fwhm is not None))

    # Conservative classification. A genuine matched detection should expose
    # at least one image/source measurement. A row with none of those but a
    # limiting magnitude is the canonical DR7 nondetection pattern.
    if has_source_measurement:
        status="OFFICIAL_DETECTION"
    elif lim is not None:
        status="OFFICIAL_NONDETECTION"
    else:
        status="OFFICIAL_ROW_AMBIGUOUS"

    return {
        "classification":status,
        "has_fit_position":has_fit,
        "has_catalog_position":has_cat,
        "has_image_centroid":has_img,
        "has_sxt_number":has_sxt,
        "has_calibrated_mag":has_mag,
        "fit_ra_deg":fit_ra,"fit_dec_deg":fit_dec,
        "catalog_ra_deg":cat_ra,"catalog_dec_deg":cat_dec,
        "image_x":image_x,"image_y":image_y,
        "sxt_number":sxt,
        "magcal_magdep":mag,
        "limiting_mag_local":lim,
        "flux_iso":flux,
        "fwhm_image":fwhm,
        "drad_rms2":f(pick(rr,"dradRms2","drad_rms2")),
        "aflags":pick(rr,"aflags"),
        "a2flags":pick(rr,"a2flags"),
        "bflags":pick(rr,"bflags"),
        "b2flags":pick(rr,"b2flags"),
    }


def main():
    print("="*128)
    print("ORDER 01 — OFFICIAL DASCH ai43437 LIGHTCURVE-ROW AUDIT v028t")
    print("="*128)
    print("NO NETWORK ACCESS. Reads only v028s cached official API responses.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028S_JSON,V028Q_REFS):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2
    if not CACHE.is_dir():
        print(f"FAIL missing v028s cache directory: {CACHE}");return 2

    vs=json.loads(V028S_JSON.read_text(encoding="utf-8"))
    if vs.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("v028s frozen ranks mismatch")
    if vs.get("guards",{}).get("candidate_pixels_used_as_reference_fit") is not False:
        raise RuntimeError("v028s guard mismatch")

    qrefs=read_csv(V028Q_REFS)
    primary=[r for r in qrefs if b(r.get("final_primary_reference"))]
    if len(primary)!=8:
        raise RuntimeError(f"expected 8 v028q primary refs, found {len(primary)}")

    # Use v028s query log as the frozen record of which catalog candidates were
    # tried. For each source/refcat take the smallest preprop separation.
    bykey={}
    for q in vs.get("query_log",[]):
        key=(i(q.get("strict_rank")),str(q.get("source_id")),str(q.get("refcat")))
        attempts=q.get("attempts") or []
        if attempts:
            best=min(attempts,key=lambda a:float(a.get("preprop_gaia_sep_arcsec",1e99)))
            bykey[key]=best

    out=[]
    print(f"Frozen ordinary-star controls: {len(primary)}")
    print()

    for idx,g in enumerate(primary,1):
        rank=i(g["strict_rank"]);sid=str(g["source_id"]);gmag=f(g["g_mag"])
        print(f"[{idx:02d}/08] rank #{rank} Gaia {sid} G={gmag:.2f}")
        for refcat in REFCATS:
            a=bykey.get((rank,sid,refcat))
            if not a:
                row={
                    "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                    "refcat":refcat,"classification":"NO_QUERY_ATTEMPT"
                }
                out.append(row)
                print(f"  {refcat}: NO_QUERY_ATTEMPT")
                continue

            rn=i(a.get("ref_number"));gb=i(a.get("gsc_bin_index"))
            cp=cache_path(rank,sid,refcat,rn,gb)
            if not cp.is_file():
                row={
                    "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                    "refcat":refcat,"ref_number":rn,"gsc_bin_index":gb,
                    "ref_text":a.get("ref_text"),
                    "preprop_gaia_sep_arcsec":f(a.get("preprop_gaia_sep_arcsec")),
                    "classification":"MISSING_LIGHTCURVE_CACHE",
                    "cache_path":str(cp),
                }
                out.append(row)
                print(f"  {refcat}: MISSING cache {cp.name}")
                continue

            raw=json.loads(cp.read_text(encoding="utf-8"))
            rows=table_rows(raw)
            airows=[]
            for rr in rows:
                series=str(pick(rr,"series",default="") or "").lower()
                platenum=i(pick(rr,"platenum","plateNum","plate_number"))
                solnum=i(pick(rr,"solnum","solutionNumber","solution_number"))
                if series==PLATE_SERIES and platenum==PLATE_NUMBER and solnum==SOLUTION_NUMBER:
                    airows.append(rr)

            if not airows:
                row={
                    "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                    "refcat":refcat,"ref_number":rn,"gsc_bin_index":gb,
                    "ref_text":a.get("ref_text"),
                    "preprop_gaia_sep_arcsec":f(a.get("preprop_gaia_sep_arcsec")),
                    "classification":"NO_AI43437_ROW",
                    "cache_path":str(cp),
                }
                out.append(row)
                print(f"  {refcat}: NO_AI43437_ROW")
                continue

            # One exposure/solution is expected, but retain an explicit count.
            rr=airows[0]
            cl=classify(rr)
            row={
                "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                "refcat":refcat,"ref_number":rn,"gsc_bin_index":gb,
                "ref_text":a.get("ref_text"),
                "preprop_gaia_sep_arcsec":f(a.get("preprop_gaia_sep_arcsec")),
                "ai43437_row_count":len(airows),
                "cache_path":str(cp),
                **cl,
            }
            out.append(row)

            print(
                f"  {refcat}: {cl['classification']} "
                f"presep={row['preprop_gaia_sep_arcsec']:.4f}\" "
                f"fit={cl['has_fit_position']} cat={cl['has_catalog_position']} "
                f"xy={cl['has_image_centroid']} sxt={cl['has_sxt_number']} "
                f"mag={cl['has_calibrated_mag']} "
                f"lim={cl['limiting_mag_local']}"
            )
        print()

    counts={}
    for r in out:
        counts[r["classification"]]=counts.get(r["classification"],0)+1

    # Source-level consensus across ATLAS/APASS.
    source_consensus=[]
    for g in primary:
        rank=i(g["strict_rank"]);sid=str(g["source_id"])
        rr=[x for x in out if x["strict_rank"]==rank and x["source_id"]==sid]
        sts={x["refcat"]:x["classification"] for x in rr}
        if sts.get("atlas")=="OFFICIAL_NONDETECTION" and sts.get("apass")=="OFFICIAL_NONDETECTION":
            consensus="NONDETECTION_IN_BOTH_REFCATS"
        elif "OFFICIAL_DETECTION" in sts.values():
            consensus="DETECTION_IN_AT_LEAST_ONE_REFCAT"
        else:
            consensus="MIXED_OR_AMBIGUOUS"
        source_consensus.append({
            "strict_rank":rank,"source_id":sid,"g_mag":f(g["g_mag"]),
            "atlas_status":sts.get("atlas"),
            "apass_status":sts.get("apass"),
            "consensus":consensus,
        })

    print("="*128)
    print("CLASSIFICATION SUMMARY")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")
    print()
    print("SOURCE-LEVEL CONSENSUS")
    for r in source_consensus:
        print(f"  rank #{r['strict_rank']} {r['source_id']}: {r['consensus']}")

    fields=[
        "strict_rank","source_id","g_mag","refcat","ref_number","gsc_bin_index",
        "ref_text","preprop_gaia_sep_arcsec","ai43437_row_count","classification",
        "has_fit_position","has_catalog_position","has_image_centroid",
        "has_sxt_number","has_calibrated_mag","fit_ra_deg","fit_dec_deg",
        "catalog_ra_deg","catalog_dec_deg","image_x","image_y","sxt_number",
        "magcal_magdep","limiting_mag_local","flux_iso","fwhm_image",
        "drad_rms2","aflags","a2flags","bflags","b2flags","cache_path",
    ]
    write_csv(OUT_CSV,out,fields)

    payload={
        "stage":"ORDER01_OFFICIAL_DASCH_AI43437_ROW_AUDIT_V028T",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "candidate_pixels_used_as_reference_fit":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "classification_counts":counts,
        "source_consensus":source_consensus,
        "rows":out,
        "interpretive_boundary":(
            "This stage only classifies the official DR7 ai43437 lightcurve row "
            "for each frozen ordinary-star catalog source as a detection, "
            "nondetection, or ambiguous row based on whether image/source "
            "measurement fields are present. It does not infer why a source "
            "was undetected, and it does not classify any science candidate."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Official DASCH ai43437 Lightcurve-Row Audit v028t","",
        "## Guard state","",
        "- No network access; only cached official DR7 responses from v028s were read.",
        "- Science pixels were not read.",
        "- The transient detector was not rerun.",
        "- No candidate state was changed.","",
        "## Classification counts","",
    ]
    for k in sorted(counts):
        md.append(f"- `{k}`: **{counts[k]}**")
    md += ["","## Source-level consensus","",
           "| rank | Gaia source | G | ATLAS | APASS | consensus |",
           "|---:|---|---:|---|---|---|"]
    for r in source_consensus:
        md.append(
            f"| #{r['strict_rank']} | `{r['source_id']}` | {r['g_mag']:.2f} | "
            f"`{r['atlas_status']}` | `{r['apass_status']}` | `{r['consensus']}` |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
