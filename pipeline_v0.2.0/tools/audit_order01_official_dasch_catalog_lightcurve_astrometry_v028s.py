#!/usr/bin/env python3
"""
ORDER 01 — official DASCH catalog/lightcurve astrometric adjudication v028s

Purpose
-------
Resolve the remaining ambiguity from v028r. That stage queried `platephot`
around the six science positions, but the returned rows had null catalog-side
coordinates and therefore yielded zero Gaia↔official catalog matches.

v028s instead follows the DR7 catalog-native API chain for the eight frozen
v028q primary ordinary-star references:

    Gaia control -> /dasch/dr7/querycat -> DASCH catalog source
                 -> /dasch/dr7/lightcurve -> ai43437 solution-0 measurement

The ai43437 lightcurve row supplies:
  - fitted image position (raDeg/decDeg)
  - catalog position precessed to the plate epoch (catalogRa/catalogDec)
  - image/source measurements and flags

We perform the chain independently for both DR7 refcats:
  APASS  : older positional sources; primary historical DR7 calibration catalog
  ATLAS  : positions/proper motions based on Gaia DR2; useful independent check

For each frozen Gaia control, querycat candidates are propagated approximately
to the 1951 plate epoch when proper-motion metadata are available. Only the
best few plausible catalog candidates are sent to the lightcurve endpoint.
The final source identity is chosen solely by the distance between the
lightcurve row's *catalog position at the plate epoch* and Gaia(1951), never by
the fitted plate position. Thus the plate astrometric residual cannot choose
its own reference association.

No science candidate position is used in the reference fit.

Guards
------
NETWORK ACCESS: TRUE (official DASCH DR7 public API)
SCIENCE PIXELS READ: FALSE
Candidate pixels used as reference fit: FALSE
Frozen transient detector rerun: FALSE
No candidate promotion/deletion/state mutation
"""

from __future__ import annotations

import csv
import io
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"
CACHE = WORK / "official_dasch_catalog_lightcurve_v028s"
CACHE.mkdir(parents=True, exist_ok=True)

V028Q_JSON = BASE / "order01_plate_registered_bright_gaia_astrometry_v028q.json"
V028Q_REFS = BASE / "order01_plate_registered_bright_gaia_references_v028q.csv"

OUT_JSON = BASE / "order01_official_dasch_catalog_lightcurve_astrometry_v028s.json"
OUT_SUM = BASE / "order01_official_dasch_catalog_lightcurve_astrometry_v028s.csv"
OUT_REFS = BASE / "order01_official_dasch_catalog_lightcurve_references_v028s.csv"
OUT_MD = BASE / "ORDER01_OFFICIAL_DASCH_CATALOG_LIGHTCURVE_ASTROMETRY_V028S.md"

EXPECTED = [10, 24, 25, 26, 29, 30]
PLATE_SERIES = "ai"
PLATE_NUMBER = 43437
PLATE_ID = "ai43437"
SOLUTION_NUMBER = 0
TARGET_EPOCH_JYEAR = 1951.845  # only for pre-ranking querycat candidates
BASE_URL = "https://api.starglass.cfa.harvard.edu/public/"
TIMEOUT = 90
MAX_RETRIES = 4

REFCATS = ("atlas", "apass")
QUERY_RADIUS_ARCSEC = 90.0
MAX_LIGHTCURVE_CANDIDATES_PER_REFCAT = 4
PRESELECT_PROPAGATED_MAX_ARCSEC = 35.0
FINAL_CATALOG_GAIA_MAX_ARCSEC = 15.0
MIN_COMPLETE_REFERENCES = 5


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).strip())
    except Exception:
        return default


def i(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def b(v):
    return str(v).strip().lower() in {"true","1","yes","y","t"}


def pick(row: dict, *names, default=None):
    norm = {str(k).lower().replace("_",""): k for k in row}
    for name in names:
        key = str(name).lower().replace("_","")
        if key in norm:
            return row[norm[key]]
    return default


def angular_vector(ra1, dec1, ra2, dec2):
    dec0 = 0.5 * (dec1 + dec2)
    east = (ra2-ra1)*3600.0*math.cos(math.radians(dec0))
    north = (dec2-dec1)*3600.0
    sep = math.hypot(east,north)
    pa = math.degrees(math.atan2(east,north)) % 360.0
    return east,north,sep,pa


def propagate_catalog_approx(ra, dec, pmra_masyr, pmdec_masyr, epoch_jyear):
    """
    Approximate linear propagation adequate only for querycat candidate
    pre-ranking. Final identity is decided with catalogRa/catalogDec from the
    actual ai43437 lightcurve row, which DR7 already precesses to plate epoch.
    """
    if None in (ra,dec):
        return ra,dec
    if epoch_jyear is None:
        return ra,dec
    dt = TARGET_EPOCH_JYEAR - epoch_jyear
    out_ra, out_dec = ra, dec
    if pmdec_masyr is not None:
        out_dec = dec + (pmdec_masyr/1000.0)*dt/3600.0
    if pmra_masyr is not None:
        east_arcsec = (pmra_masyr/1000.0)*dt
        c = max(abs(math.cos(math.radians(dec))), 1e-8)
        out_ra = ra + east_arcsec/(3600.0*c)
    return out_ra,out_dec


def api_json(endpoint, payload, cache_path):
    if cache_path.is_file():
        return json.loads(cache_path.read_text(encoding="utf-8")), True
    url = BASE_URL + endpoint.lstrip("/")
    headers = {
        "accept":"application/json",
        "user-agent":"historical-transient-independent-audit-v028s/1.0",
    }
    last = None
    for attempt in range(1,MAX_RETRIES+1):
        try:
            r = requests.post(url,headers=headers,json=payload,timeout=TIMEOUT)
            r.raise_for_status()
            obj = r.json()
            cache_path.write_text(json.dumps(obj,indent=2)+"\n",encoding="utf-8")
            return obj, False
        except Exception as exc:
            last = exc
            if attempt<MAX_RETRIES:
                time.sleep(min(2**attempt,8))
    raise RuntimeError(f"POST {url} failed: {last}")


def table_rows(obj):
    if isinstance(obj,dict):
        for k in ("data","rows","records","result"):
            if isinstance(obj.get(k),list):
                obj=obj[k];break
    if not isinstance(obj,list):
        raise RuntimeError(f"unexpected API table response {type(obj).__name__}")
    if not obj:
        return []
    if all(isinstance(x,str) for x in obj):
        return list(csv.DictReader(io.StringIO("\n".join(obj))))
    if all(isinstance(x,dict) for x in obj):
        return obj
    raise RuntimeError("mixed API table response")


def querycat_candidates(refcat, gra, gdec, cache_tag):
    cp = CACHE / f"{cache_tag}_{refcat}_querycat.json"
    obj,used=api_json(
        "dasch/dr7/querycat",
        {"refcat":refcat,"ra_deg":gra,"dec_deg":gdec,
         "radius_arcsec":QUERY_RADIUS_ARCSEC},
        cp,
    )
    rows=table_rows(obj)
    out=[]
    for rr in rows:
        ra=f(pick(rr,"raDeg","ra_deg","ra"))
        dec=f(pick(rr,"decDeg","dec_deg","dec"))
        pmra=f(pick(rr,"pmRaMasyr","pm_ra_masyr","pmRaCosdec","pm_ra_cosdec"))
        pmdec=f(pick(rr,"pmDecMasyr","pm_dec_masyr","pmDec","pm_dec"))
        epoch=f(pick(rr,"posEpoch","pos_epoch","obstime","refEpoch","ref_epoch"))
        pra,pdec=propagate_catalog_approx(ra,dec,pmra,pmdec,epoch)
        if None in (pra,pdec):
            presep=float("inf")
        else:
            _,_,presep,_=angular_vector(gra,gdec,pra,pdec)
        directdra=f(pick(rr,"dra"))
        directddec=f(pick(rr,"ddec"))
        directsep=(math.hypot(directdra,directddec)
                   if directdra is not None and directddec is not None else None)
        out.append({
            "raw":rr,
            "ref_number":i(pick(rr,"refNumber","ref_number")),
            "gsc_bin_index":i(pick(rr,"gscBinIndex","gsc_bin_index")),
            "ref_text":pick(rr,"refText","ref_text"),
            "stdmag":f(pick(rr,"stdmag")),
            "num_matches":i(pick(rr,"numMatches","num_matches"),0),
            "catalog_ra_canonical_deg":ra,
            "catalog_dec_canonical_deg":dec,
            "pm_ra_masyr":pmra,
            "pm_dec_masyr":pmdec,
            "pos_epoch":epoch,
            "preprop_ra_1951_deg":pra,
            "preprop_dec_1951_deg":pdec,
            "preprop_gaia_sep_arcsec":presep,
            "query_direct_sep_arcsec":directsep,
        })
    out.sort(key=lambda q:(q["preprop_gaia_sep_arcsec"],
                           q["query_direct_sep_arcsec"]
                           if q["query_direct_sep_arcsec"] is not None else 1e30))
    return out,used


def ai43437_rows_for_source(refcat, cand, cache_tag):
    rn=cand["ref_number"]; gb=cand["gsc_bin_index"]
    if rn is None or gb is None:
        return [],False
    cp=CACHE/f"{cache_tag}_{refcat}_ref{rn}_bin{gb}_lightcurve.json"
    obj,used=api_json(
        "dasch/dr7/lightcurve",
        {"refcat":refcat,"ref_number":rn,"gsc_bin_index":gb},
        cp,
    )
    rows=table_rows(obj)
    out=[]
    for rr in rows:
        series=str(pick(rr,"series",default="") or "").lower()
        platenum=i(pick(rr,"platenum","plateNum","plate_number"))
        solnum=i(pick(rr,"solnum","solutionNumber","solution_number"))
        if series!=PLATE_SERIES or platenum!=PLATE_NUMBER or solnum!=SOLUTION_NUMBER:
            continue
        out.append(rr)
    return out,used


def parse_measurement(rr):
    return {
        "fit_ra_deg":f(pick(rr,"raDeg","ra_deg","ra")),
        "fit_dec_deg":f(pick(rr,"decDeg","dec_deg","dec")),
        "catalog_ra_deg":f(pick(rr,"catalogRa","catalog_ra")),
        "catalog_dec_deg":f(pick(rr,"catalogDec","catalog_dec")),
        "image_x":f(pick(rr,"imageX","image_x")),
        "image_y":f(pick(rr,"imageY","image_y")),
        "sxt_number":i(pick(rr,"sxtNumber","sxt_number")),
        "ref_number_row":i(pick(rr,"refNumber","ref_number")),
        "gsc_bin_index_row":i(pick(rr,"gscBinIndex","gsc_bin_index")),
        "drad_rms2":f(pick(rr,"dradRms2","drad_rms2")),
        "fwhm_image":f(pick(rr,"fwhmImage","fwhm_image")),
        "ellipticity":f(pick(rr,"ellipticity")),
        "magcal_magdep":f(pick(rr,"magcalMagdep","magcal_magdep")),
        "limiting_mag_local":f(pick(rr,"limitingMagLocal","limiting_mag_local")),
        "aflags":pick(rr,"aflags"),
        "a2flags":pick(rr,"a2flags"),
        "bflags":pick(rr,"bflags"),
        "b2flags":pick(rr,"b2flags"),
    }


def summary(rows, east_key, north_key):
    if not rows:
        return None
    arr=np.array([[float(r[east_key]),float(r[north_key])] for r in rows],float)
    med=np.median(arr,axis=0)
    rr=np.hypot(arr[:,0]-med[0],arr[:,1]-med[1])
    ang=np.arctan2(arr[:,0],arr[:,1])
    R=math.hypot(float(np.mean(np.sin(ang))),float(np.mean(np.cos(ang))))
    return {
        "count":len(rows),
        "median_east_arcsec":float(med[0]),
        "median_north_arcsec":float(med[1]),
        "median_vector_magnitude_arcsec":float(math.hypot(*med)),
        "residual_median_arcsec":float(np.median(rr)),
        "residual_p95_arcsec":float(np.quantile(rr,.95,method="higher")),
        "circular_R":float(R),
    }


def main():
    print("="*128)
    print("ORDER 01 — OFFICIAL DASCH CATALOG/LIGHTCURVE ASTROMETRIC ADJUDICATION v028s")
    print("="*128)
    print("NETWORK ACCESS: official DASCH DR7 public API.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Only frozen v028q primary ordinary-star controls are queried.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028Q_JSON,V028Q_REFS):
        if not p.is_file():
            print(f"FAIL missing input: {p}"); return 2

    vq=json.loads(V028Q_JSON.read_text(encoding="utf-8"))
    if vq.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("v028q frozen ranks mismatch")
    if vq.get("guards",{}).get("candidate_pixels_used_as_reference_fit") is not False:
        raise RuntimeError("v028q candidate-reference guard mismatch")

    refs=read_csv(V028Q_REFS)
    primary=[r for r in refs if b(r.get("final_primary_reference"))]
    if len(primary)!=8:
        raise RuntimeError(f"expected 8 frozen v028q primary refs, found {len(primary)}")
    ids=[str(r["source_id"]) for r in primary]
    if len(set(ids))!=len(ids):
        raise RuntimeError("duplicate Gaia source IDs in v028q primary set")

    print(f"Frozen v028q primary ordinary-star controls: {len(primary)}")
    print("Guard state: PASS\n")

    results=[]
    query_log=[]

    for idx,g in enumerate(primary,1):
        rank=i(g["strict_rank"])
        sid=str(g["source_id"])
        gra=f(g["ra_target_deg"]); gdec=f(g["dec_target_deg"])
        gmag=f(g["g_mag"])
        tag=f"rank{rank}_gaia{sid}"

        print(f"[{idx:02d}/{len(primary):02d}] rank #{rank} Gaia {sid} G={gmag:.2f}")

        for refcat in REFCATS:
            cats,qcache=querycat_candidates(refcat,gra,gdec,tag)
            plausible=[c for c in cats
                       if c["preprop_gaia_sep_arcsec"]<=PRESELECT_PROPAGATED_MAX_ARCSEC]
            candidates=(plausible if plausible else cats)[:MAX_LIGHTCURVE_CANDIDATES_PER_REFCAT]
            print(f"  {refcat}: querycat={len(cats)} plausible={len(plausible)} "
                  f"lightcurve_try={len(candidates)}")

            best=None
            attempts=[]
            for c in candidates:
                lrows,lcache=ai43437_rows_for_source(refcat,c,tag)
                attempt={
                    "ref_number":c["ref_number"],
                    "gsc_bin_index":c["gsc_bin_index"],
                    "ref_text":c["ref_text"],
                    "preprop_gaia_sep_arcsec":c["preprop_gaia_sep_arcsec"],
                    "ai43437_rows":len(lrows),
                    "lightcurve_cache_used":lcache,
                }
                local_best=None
                for rr in lrows:
                    m=parse_measurement(rr)
                    if None in (m["catalog_ra_deg"],m["catalog_dec_deg"]):
                        continue
                    ce,cn,csep,_=angular_vector(
                        gra,gdec,m["catalog_ra_deg"],m["catalog_dec_deg"])
                    if local_best is None or csep<local_best["catalog_gaia_sep_arcsec"]:
                        local_best={
                            "measurement":m,
                            "catalog_gaia_east_arcsec":ce,
                            "catalog_gaia_north_arcsec":cn,
                            "catalog_gaia_sep_arcsec":csep,
                        }
                if local_best:
                    attempt["best_catalog_gaia_sep_arcsec"]=local_best["catalog_gaia_sep_arcsec"]
                    candidate_record={**c,**local_best}
                    if best is None or local_best["catalog_gaia_sep_arcsec"]<best["catalog_gaia_sep_arcsec"]:
                        best=candidate_record
                attempts.append(attempt)

            query_log.append({
                "strict_rank":rank,"source_id":sid,"refcat":refcat,
                "querycat_rows":len(cats),"plausible_rows":len(plausible),
                "querycat_cache_used":qcache,"attempts":attempts,
            })

            if best is None or best["catalog_gaia_sep_arcsec"]>FINAL_CATALOG_GAIA_MAX_ARCSEC:
                print("    => no accepted ai43437 catalog-linked measurement")
                results.append({
                    "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                    "gaia_ra_1951_deg":gra,"gaia_dec_1951_deg":gdec,
                    "refcat":refcat,
                    "status":"NO_ACCEPTED_AI43437_CATALOG_LINK",
                    "best_catalog_gaia_sep_arcsec":
                        None if best is None else best["catalog_gaia_sep_arcsec"],
                })
                continue

            m=best["measurement"]
            if None in (m["fit_ra_deg"],m["fit_dec_deg"]):
                print(f"    => catalog match {best['catalog_gaia_sep_arcsec']:.3f}\" "
                      "but no fitted source position")
                results.append({
                    "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                    "gaia_ra_1951_deg":gra,"gaia_dec_1951_deg":gdec,
                    "refcat":refcat,
                    "status":"CATALOG_LINK_NO_FITTED_POSITION",
                    "best_catalog_gaia_sep_arcsec":best["catalog_gaia_sep_arcsec"],
                    "ref_number":best["ref_number"],
                    "gsc_bin_index":best["gsc_bin_index"],
                    "ref_text":best["ref_text"],
                })
                continue

            fg_e,fg_n,fg_sep,_=angular_vector(
                gra,gdec,m["fit_ra_deg"],m["fit_dec_deg"])
            fc_e,fc_n,fc_sep,_=angular_vector(
                m["catalog_ra_deg"],m["catalog_dec_deg"],
                m["fit_ra_deg"],m["fit_dec_deg"])
            cg_e,cg_n,cg_sep,_=angular_vector(
                gra,gdec,m["catalog_ra_deg"],m["catalog_dec_deg"])

            row={
                "strict_rank":rank,"source_id":sid,"g_mag":gmag,
                "gaia_ra_1951_deg":gra,"gaia_dec_1951_deg":gdec,
                "refcat":refcat,"status":"SUCCESS",
                "ref_number":best["ref_number"],
                "gsc_bin_index":best["gsc_bin_index"],
                "ref_text":best["ref_text"],
                "stdmag":best["stdmag"],
                "catalog_ra_deg":m["catalog_ra_deg"],
                "catalog_dec_deg":m["catalog_dec_deg"],
                "fit_ra_deg":m["fit_ra_deg"],
                "fit_dec_deg":m["fit_dec_deg"],
                "catalog_minus_gaia_east_arcsec":cg_e,
                "catalog_minus_gaia_north_arcsec":cg_n,
                "catalog_minus_gaia_sep_arcsec":cg_sep,
                "fit_minus_catalog_east_arcsec":fc_e,
                "fit_minus_catalog_north_arcsec":fc_n,
                "fit_minus_catalog_sep_arcsec":fc_sep,
                "fit_minus_gaia_east_arcsec":fg_e,
                "fit_minus_gaia_north_arcsec":fg_n,
                "fit_minus_gaia_sep_arcsec":fg_sep,
                "image_x":m["image_x"],"image_y":m["image_y"],
                "sxt_number":m["sxt_number"],
                "drad_rms2":m["drad_rms2"],
                "fwhm_image":m["fwhm_image"],
                "ellipticity":m["ellipticity"],
                "magcal_magdep":m["magcal_magdep"],
                "limiting_mag_local":m["limiting_mag_local"],
                "aflags":m["aflags"],"a2flags":m["a2flags"],
                "bflags":m["bflags"],"b2flags":m["b2flags"],
            }
            results.append(row)
            print(
                f"    => SUCCESS cat↔Gaia={cg_sep:.3f}\" "
                f"fit−cat=({fc_e:+.2f},{fc_n:+.2f})\"/{fc_sep:.2f}\" "
                f"fit−Gaia=({fg_e:+.2f},{fg_n:+.2f})\"/{fg_sep:.2f}\""
            )
        print()

    summaries={}
    print("="*128)
    print("OFFICIAL ASTROMETRIC SUMMARIES")
    for refcat in REFCATS:
        ok=[r for r in results if r["refcat"]==refcat and r["status"]=="SUCCESS"]
        summaries[refcat]={
            "success_count":len(ok),
            "catalog_minus_gaia":summary(ok,"catalog_minus_gaia_east_arcsec",
                                         "catalog_minus_gaia_north_arcsec"),
            "fit_minus_catalog":summary(ok,"fit_minus_catalog_east_arcsec",
                                         "fit_minus_catalog_north_arcsec"),
            "fit_minus_gaia":summary(ok,"fit_minus_gaia_east_arcsec",
                                      "fit_minus_gaia_north_arcsec"),
        }
        print(f"{refcat.upper()}: N={len(ok)}")
        for label in ("catalog_minus_gaia","fit_minus_catalog","fit_minus_gaia"):
            su=summaries[refcat][label]
            if su is None:
                print(f"  {label}: n/a")
            else:
                print(
                    f"  {label}: median=({su['median_east_arcsec']:+.3f},"
                    f"{su['median_north_arcsec']:+.3f})\" "
                    f"mag={su['median_vector_magnitude_arcsec']:.3f}\" "
                    f"resid p95={su['residual_p95_arcsec']:.3f}\" "
                    f"R={su['circular_R']:.3f}"
                )

    vq_model=vq.get("plate_model",{}).get("selected_model",{})
    vq_vec=(vq_model.get("params") if vq_model.get("kind")=="translation" else None)
    comparisons={}
    if vq_vec:
        print(f"\nv028q translation = ({vq_vec[0]:+.3f},{vq_vec[1]:+.3f})\"")
        for refcat in REFCATS:
            su=summaries[refcat]["fit_minus_gaia"]
            if su:
                diff=math.hypot(su["median_east_arcsec"]-vq_vec[0],
                                su["median_north_arcsec"]-vq_vec[1])
                comparisons[refcat]={
                    "v028q_to_official_fit_minus_gaia_vector_difference_arcsec":diff
                }
                print(f"  {refcat}: v028q↔official median-vector difference={diff:.3f}\"")

    status=(
        "OFFICIAL_CATALOG_LIGHTCURVE_ASTROMETRY_COMPLETE"
        if max(summaries[r]["success_count"] for r in REFCATS)>=MIN_COMPLETE_REFERENCES
        else "INSUFFICIENT_OFFICIAL_CATALOG_LIGHTCURVE_REFERENCES"
    )

    fields=[
        "strict_rank","source_id","g_mag","gaia_ra_1951_deg","gaia_dec_1951_deg",
        "refcat","status","ref_number","gsc_bin_index","ref_text","stdmag",
        "catalog_ra_deg","catalog_dec_deg","fit_ra_deg","fit_dec_deg",
        "best_catalog_gaia_sep_arcsec",
        "catalog_minus_gaia_east_arcsec","catalog_minus_gaia_north_arcsec",
        "catalog_minus_gaia_sep_arcsec",
        "fit_minus_catalog_east_arcsec","fit_minus_catalog_north_arcsec",
        "fit_minus_catalog_sep_arcsec",
        "fit_minus_gaia_east_arcsec","fit_minus_gaia_north_arcsec",
        "fit_minus_gaia_sep_arcsec",
        "image_x","image_y","sxt_number","drad_rms2","fwhm_image",
        "ellipticity","magcal_magdep","limiting_mag_local",
        "aflags","a2flags","bflags","b2flags"
    ]
    write_csv(OUT_REFS,results,fields)

    sumrows=[]
    for refcat in REFCATS:
        for metric in ("catalog_minus_gaia","fit_minus_catalog","fit_minus_gaia"):
            su=summaries[refcat][metric]
            if su:
                sumrows.append({"refcat":refcat,"metric":metric,**su})
    write_csv(
        OUT_SUM,sumrows,
        ["refcat","metric","count","median_east_arcsec","median_north_arcsec",
         "median_vector_magnitude_arcsec","residual_median_arcsec",
         "residual_p95_arcsec","circular_R"]
    )

    payload={
        "stage":"ORDER01_OFFICIAL_DASCH_CATALOG_LIGHTCURVE_ASTROMETRY_V028S",
        "status":status,
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":True,
            "network_endpoint":BASE_URL,
            "science_pixels_read":False,
            "candidate_pixels_used_as_reference_fit":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "frozen_v028q_primary_reference_count":len(primary),
        "plate_id":PLATE_ID,
        "solution_number":SOLUTION_NUMBER,
        "query_radius_arcsec":QUERY_RADIUS_ARCSEC,
        "final_catalog_gaia_acceptance_arcsec":FINAL_CATALOG_GAIA_MAX_ARCSEC,
        "summaries":summaries,
        "comparison_to_v028q":comparisons,
        "query_log":query_log,
        "results":results,
        "interpretive_boundary":(
            "Source identity is determined from the official DASCH catalog "
            "position at the plate epoch versus Gaia(1951), not from the fitted "
            "plate position. The fitted-minus-catalog vector is therefore an "
            "independent DR7 astrometric residual. Agreement of this vector "
            "with v028q would independently validate the coherent raw-pixel "
            "registration offset. Disagreement would weigh against v028q's "
            "centroid/WCS reconstruction. Neither result alone classifies any "
            "science candidate as astrophysical or identifies a specific artifact."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Official DASCH Catalog/Lightcurve Astrometric Adjudication v028s","",
        "## Guard state","",
        "- Official DASCH DR7 `querycat` and `lightcurve` APIs were queried.",
        "- Science pixels were not read.",
        "- Only the eight frozen v028q primary ordinary-star controls were used.",
        "- Candidate positions were not reference-fit inputs.",
        "- The transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.","",
        "## Official ordinary-star astrometry","",
    ]
    for refcat in REFCATS:
        md.append(f"### {refcat.upper()}")
        md.append("")
        md.append(f"- Successful ai43437 catalog-linked controls: **{summaries[refcat]['success_count']}**.")
        for metric in ("catalog_minus_gaia","fit_minus_catalog","fit_minus_gaia"):
            su=summaries[refcat][metric]
            if su:
                md.append(
                    f"- `{metric}`: median east/north "
                    f"**{su['median_east_arcsec']:+.3f}/{su['median_north_arcsec']:+.3f} arcsec**, "
                    f"magnitude **{su['median_vector_magnitude_arcsec']:.3f} arcsec**, "
                    f"residual p95 **{su['residual_p95_arcsec']:.3f} arcsec**, "
                    f"R **{su['circular_R']:.3f}**."
                )
        md.append("")
    md += [
        "## Comparison to v028q","",
        f"- v028q selected translation: `{vq_vec}` arcsec." if vq_vec else "- v028q translation unavailable.",
    ]
    for refcat,c in comparisons.items():
        md.append(
            f"- {refcat.upper()} official fitted-minus-Gaia median differs from "
            f"v028q by **{c['v028q_to_official_fit_minus_gaia_vector_difference_arcsec']:.3f} arcsec**."
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\n"+"="*128)
    print(f"v028s complete: {status}")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_SUM}")
    print(f"  {OUT_REFS}")
    print(f"  {OUT_MD}")
    print()
    print("Official DASCH DR7 network queries WERE made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Candidate positions were NOT reference-fit inputs.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
