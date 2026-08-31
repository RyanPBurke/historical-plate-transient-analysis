#!/usr/bin/env python3
"""
ORDER 01 — exact raw DASCH platephot CSV-line audit v028ao

Purpose
-------
v028an established the exact cache representation:

    JSON top-level list[str]
    element 0 = CSV header
    elements 1..N = CSV data rows

This stage parses that representation directly with csv.DictReader and audits
EVERY official ai43437 platephot row in each rank-scoped cache against the
preserved DASCH science coordinate.

For each rank:
  * parse all raw rows exactly;
  * verify series=ai, plate_number=43437, solution_number=0;
  * compute separation using observed/fitted `ra_deg,dec_deg`;
  * separately compute separation using `ra_cat_corrected,dec_cat_corrected`;
  * rank every row by science separation;
  * report counts within 3", 5", 10", 30", 60";
  * verify whether the v028r frozen `official_fit_ra_deg/dec_deg` row is present;
  * preserve flags and morphology/photometry fields for the nearest rows.

Interpretation boundary
-----------------------
A nearby official platephot row is an official DR7 source measurement on the
same physical plate; it is not, by itself, proof of an astrophysical transient.
Conversely, absence of a close platephot row is evidence that the native
pipeline detection is not represented as a close official DR7 fitted source,
but does not by itself identify the physical defect mechanism.

NO network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
V028R = BASE / "order01_official_dasch_platephot_astrometry_v028r.json"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_exact_raw_platephot_audit_v028ao.json"
OUT_SUMMARY = BASE / "order01_dasch_exact_raw_platephot_summary_v028ao.csv"
OUT_ROWS = BASE / "order01_dasch_exact_raw_platephot_rows_v028ao.csv"
OUT_MD = BASE / "ORDER01_DASCH_EXACT_RAW_PLATEPHOT_AUDIT_V028AO.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
KEEP_NEAREST = 20

THRESHOLDS = (3.0,5.0,10.0,30.0,60.0)


def read_csv_file(path):
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
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
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


def angsep_arcsec(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c=max(-1.0,min(1.0,c))
    return math.degrees(math.acos(c))*3600.0


def parse_json_list_csv(path):
    obj=json.loads(path.read_text(encoding="utf-8",errors="strict"))
    if not isinstance(obj,list) or not obj:
        raise RuntimeError(f"{path.name}: expected non-empty JSON list")
    if not all(isinstance(x,str) for x in obj):
        raise RuntimeError(f"{path.name}: expected list[str], got mixed types")
    reader=csv.DictReader(io.StringIO("\n".join(obj)))
    rows=list(reader)
    if not rows:
        return [],reader.fieldnames or []
    return rows,reader.fieldnames or []


def science_rows():
    strict=read_csv_file(STRICT)
    native=read_csv_file(DASCH_NATIVE)
    sr={i(r["strict_rank"]):r for r in strict if i(r["strict_rank"]) in RANKS}
    out={}
    for rank in RANKS:
        r=sr[rank]
        tile=str(r["dasch_tile_id"])
        idx=i(r.get("dasch_candidate_index"))
        q=[x for x in native
           if str(x.get("tile_id",""))==tile and i(x.get("candidate_index"))==idx]
        if len(q)!=1:
            raise RuntimeError(f"#{rank}: science native resolution failed: {len(q)}")
        x=q[0]
        out[rank]={
            "ra_deg":f(x["ra_deg"]),
            "dec_deg":f(x["dec_deg"]),
            "snr":f(x["snr"]),
            "polarity":i(x["polarity"]),
            "tile_id":tile,
            "candidate_index":idx,
        }
    return out


def main():
    print("="*128)
    print("ORDER 01 — EXACT RAW DASCH PLATEPHOT CSV-LINE AUDIT v028ao")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE,V028R):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    sci=science_rows()
    v028r=json.loads(V028R.read_text(encoding="utf-8"))
    vrows={i(x.get("strict_rank")):x
           for x in v028r.get("science_nearest_official_sources",[])
           if i(x.get("strict_rank")) in RANKS}

    summaries=[]
    all_nearest=[]

    for rank in RANKS:
        p=RAW_DIR/f"{PLATE}_sol0_rank{rank}_apass_platephot.json"
        if not p.is_file():
            raise RuntimeError(f"missing raw cache: {p}")

        rows,fields=parse_json_list_csv(p)
        s=sci[rank]

        enriched=[]
        bad_plate=0
        for ridx,row in enumerate(rows, start=1):
            series=str(row.get("series","")).strip()
            plate=i(row.get("plate_number"))
            sol=i(row.get("solution_number"))
            if not (series=="ai" and plate==43437 and sol==0):
                bad_plate+=1

            ra=f(row.get("ra_deg"));dec=f(row.get("dec_deg"))
            cra=f(row.get("ra_cat_corrected"));cdec=f(row.get("dec_cat_corrected"))

            sep=None if None in (ra,dec) else angsep_arcsec(
                s["ra_deg"],s["dec_deg"],ra,dec
            )
            csep=None if None in (cra,cdec) else angsep_arcsec(
                s["ra_deg"],s["dec_deg"],cra,cdec
            )

            rec={
                "strict_rank":rank,
                "raw_row_number":ridx,
                "date_jd":f(row.get("date_jd")),
                "series":series,
                "plate_number":plate,
                "solution_number":sol,
                "ref_number":row.get("ref_number"),
                "sextractor_number":row.get("sextractor_number"),
                "catalog_number":row.get("catalog_number"),
                "x_image":f(row.get("x_image")),
                "y_image":f(row.get("y_image")),
                "ra_deg":ra,
                "dec_deg":dec,
                "science_sep_arcsec":sep,
                "ra_cat_corrected":cra,
                "dec_cat_corrected":cdec,
                "science_cat_corrected_sep_arcsec":csep,
                "limiting_mag_local":f(row.get("limiting_mag_local")),
                "mag_iso":f(row.get("mag_iso")),
                "flux_iso":f(row.get("flux_iso")),
                "mag_aper":f(row.get("mag_aper")),
                "mag_auto":f(row.get("mag_auto")),
                "kron_radius":f(row.get("kron_radius")),
                "background":f(row.get("background")),
                "flux_max_adu":f(row.get("flux_max_adu")),
                "theta_j2000":f(row.get("theta_j2000")),
                "ellipticity":f(row.get("ellipticity")),
                "iso_area_sqdeg":f(row.get("iso_area_sqdeg")),
                "fwhm_pix":f(row.get("fwhm_pix")),
                "fwhm_deg":f(row.get("fwhm_deg")),
                "plate_center_dist_deg":f(row.get("plate_center_dist_deg")),
                "blended_mag":f(row.get("blended_mag")),
                "drad_rms2":f(row.get("drad_rms2")),
                "magcal_iso":f(row.get("magcal_iso")),
                "magcal_iso_rms":f(row.get("magcal_iso_rms")),
                "magcal_local":f(row.get("magcal_local")),
                "magcal_local_rms":f(row.get("magcal_local_rms")),
                "magcal_local_error":f(row.get("magcal_local_error")),
                "pm_ra_masyr":f(row.get("pm_ra_masyr")),
                "pm_dec_masyr":f(row.get("pm_dec_masyr")),
                "aflags":i(row.get("aflags")),
                "a2flags":i(row.get("a2flags")),
                "bflags":i(row.get("bflags")),
                "b2flags":i(row.get("b2flags")),
                "reject_flag":i(row.get("reject_flag")),
                "pass_bits":i(row.get("pass_bits")),
                "npoints_local":i(row.get("npoints_local")),
            }
            enriched.append(rec)

        valid=[r for r in enriched if r["science_sep_arcsec"] is not None]
        valid.sort(key=lambda r:r["science_sep_arcsec"])
        cvalid=[r for r in enriched if r["science_cat_corrected_sep_arcsec"] is not None]
        cvalid.sort(key=lambda r:r["science_cat_corrected_sep_arcsec"])

        nearest=valid[0] if valid else None
        cnearest=cvalid[0] if cvalid else None

        counts={t:sum(r["science_sep_arcsec"]<=t for r in valid) for t in THRESHOLDS}
        ccounts={t:sum(r["science_cat_corrected_sep_arcsec"]<=t for r in cvalid) for t in THRESHOLDS}

        frozen=vrows.get(rank,{})
        fra=f(frozen.get("official_fit_ra_deg"))
        fdec=f(frozen.get("official_fit_dec_deg"))

        matching=[]
        if fra is not None and fdec is not None:
            for r in valid:
                if abs(r["ra_deg"]-fra)<=5e-7 and abs(r["dec_deg"]-fdec)<=5e-7:
                    matching.append(r)

        if len(matching)>1:
            raise RuntimeError(f"#{rank}: multiple raw rows match frozen v028r fit")
        frozen_match=matching[0] if matching else None

        summary={
            "strict_rank":rank,
            "science_ra_deg":s["ra_deg"],
            "science_dec_deg":s["dec_deg"],
            "science_snr":s["snr"],
            "science_polarity":s["polarity"],
            "raw_cache_row_count":len(rows),
            "field_count":len(fields),
            "plate_identity_fail_count":bad_plate,
            "nearest_raw_row_number":None if nearest is None else nearest["raw_row_number"],
            "nearest_ra_deg":None if nearest is None else nearest["ra_deg"],
            "nearest_dec_deg":None if nearest is None else nearest["dec_deg"],
            "nearest_sep_arcsec":None if nearest is None else nearest["science_sep_arcsec"],
            "nearest_aflags":None if nearest is None else nearest["aflags"],
            "nearest_bflags":None if nearest is None else nearest["bflags"],
            "nearest_drad_rms2":None if nearest is None else nearest["drad_rms2"],
            "nearest_flux_iso":None if nearest is None else nearest["flux_iso"],
            "nearest_fwhm_pix":None if nearest is None else nearest["fwhm_pix"],
            "nearest_ellipticity":None if nearest is None else nearest["ellipticity"],
            "nearest_cat_corrected_sep_arcsec":None if cnearest is None else cnearest["science_cat_corrected_sep_arcsec"],
            "within3":counts[3.0],
            "within5":counts[5.0],
            "within10":counts[10.0],
            "within30":counts[30.0],
            "within60":counts[60.0],
            "cat_corrected_within3":ccounts[3.0],
            "cat_corrected_within5":ccounts[5.0],
            "cat_corrected_within10":ccounts[10.0],
            "cat_corrected_within30":ccounts[30.0],
            "cat_corrected_within60":ccounts[60.0],
            "v028r_frozen_fit_row_found":frozen_match is not None,
            "v028r_frozen_fit_sep_arcsec":
                None if frozen_match is None else frozen_match["science_sep_arcsec"],
            "v028r_frozen_fit_raw_row_number":
                None if frozen_match is None else frozen_match["raw_row_number"],
        }
        summaries.append(summary)

        for r in valid[:KEEP_NEAREST]:
            all_nearest.append(r)

        print(
            f"#{rank}: rows={len(rows)} plateGuardBad={bad_plate} "
            f"nearest={summary['nearest_sep_arcsec']:.3f}\" "
            f"within3/5/10/30/60="
            f"{summary['within3']}/{summary['within5']}/{summary['within10']}/"
            f"{summary['within30']}/{summary['within60']} "
            f"catCorrNearest={summary['nearest_cat_corrected_sep_arcsec']:.3f}\" "
            f"v028rRowFound={summary['v028r_frozen_fit_row_found']}"
        )

        for r in valid[:5]:
            print(
                f"    raw[{r['raw_row_number']}] sep={r['science_sep_arcsec']:.3f}\" "
                f"RA={r['ra_deg']:.8f} Dec={r['dec_deg']:.8f} "
                f"aflags={r['aflags']} bflags={r['bflags']} "
                f"drad={r['drad_rms2']} flux_iso={r['flux_iso']} "
                f"fwhm_pix={r['fwhm_pix']} ellip={r['ellipticity']}"
            )
        print()

    payload={
        "stage":"ORDER01_DASCH_EXACT_RAW_PLATEPHOT_CSV_LINE_AUDIT_V028AO",
        "plate":PLATE,
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "raw_cache_representation":"JSON_LIST_OF_CSV_LINES",
            "header_is_element_0":True,
            "all_data_rows_parsed":True,
            "plate_identity_checked":True,
        },
        "summaries":summaries,
        "nearest_rows":all_nearest,
        "interpretive_boundary":(
            "v028ao is the first exact parser of the raw rank-scoped platephot cache "
            "representation established by v028an. It measures official DR7 row "
            "proximity to each preserved DASCH endpoint but does not itself classify "
            "any endpoint as astrophysical or artefactual."
        )
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_SUMMARY,summaries,list(summaries[0]))
    row_fields=list(all_nearest[0]) if all_nearest else [
        "strict_rank","raw_row_number","science_sep_arcsec"
    ]
    write_csv(OUT_ROWS,all_nearest,row_fields)

    md=[
        "# ORDER 01 — Exact Raw DASCH Platephot Audit v028ao","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- Raw caches are parsed exactly as JSON lists of CSV lines.",
        "- Element 0 is the CSV header; all later elements are data rows.",
        "- Plate identity is checked on every row.",
        "- No endpoint state was changed.","",
        "## Exact raw platephot proximity","",
        "| rank | rows | nearest fitted row | <=3″ | <=5″ | <=10″ | <=30″ | <=60″ | corrected nearest | v028r row found |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"
    ]
    for r in summaries:
        md.append(
            f"| #{r['strict_rank']} | {r['raw_cache_row_count']} | "
            f"{r['nearest_sep_arcsec']:.3f}″ | {r['within3']} | {r['within5']} | "
            f"{r['within10']} | {r['within30']} | {r['within60']} | "
            f"{r['nearest_cat_corrected_sep_arcsec']:.3f}″ | "
            f"{r['v028r_frozen_fit_row_found']} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_SUMMARY}")
    print(f"  {OUT_ROWS}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
