#!/usr/bin/env python3
"""
ORDER 01 — local prevalence of uncatalogued stellar-like DASCH native detections v028aw

Scientific question
-------------------
The six preserved ai43437 science endpoints are:
  * centered RAW_HIGH features,
  * amplitude-normalized shape-consistent with official same-plate DR7 stars,
  * absent from official DR7 platephot within 10 arcsec,
  * without an accepted independent historical recurrence.

How common is that phenotype among OTHER frozen native DASCH detections in the
same local parts of ai43437?

Scope
-----
This is deliberately a LOCAL prevalence test, not a full-plate DR7 completeness
claim. v028r described its platephot calls as 10-arcmin regions. v028aw uses a
conservative inner radius of 5 arcmin (300 arcsec) around each exact v028r query
centre (the arithmetic midpoint of frozen POSS/DASCH discovery coordinates).

All non-science frozen native detections in the union of those six inner regions
are tested against:
  * the union of exact cached official DR7 platephot rows;
  * the same raw-pixel morphology metrics used by v028ar-r1;
  * the same amplitude-normalized official-star shape cloud used by v028as.

Phenotype
---------
UNCATALOGUED_STELLAR_LIKE_LOCAL_NATIVE:
  nearest official fitted DR7 row > 10 arcsec
  AND RAW_HIGH centre/aperture morphology is positive and locally concentrated
  AND amplitude-normalized shape NN <= official-control leave-one-out p95.

Important
---------
This counts frozen detector candidates, not unique astrophysical objects.
It is a local empirical incompleteness/control test.

NO network access.
SCIENCE PIXELS ARE NOT READ in this stage.
NON-SCIENCE CONTROL PIXELS ARE READ.
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
MORPH = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"
SHAPE = BASE / "order01_dasch_stellar_shape_v028as.json"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_local_uncatalogued_stellar_prevalence_v028aw.json"
OUT_SUMMARY = BASE / "order01_dasch_local_uncatalogued_stellar_prevalence_summary_v028aw.csv"
OUT_CANDIDATES = BASE / "order01_dasch_local_native_controls_v028aw.csv"
OUT_NEAREST = BASE / "order01_dasch_local_science_nearest_phenotype_controls_v028aw.csv"
OUT_MD = BASE / "ORDER01_DASCH_LOCAL_UNCATALOGUED_STELLAR_PREVALENCE_V028AW.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]

LOCAL_RADIUS_ARCSEC = 300.0
OFFICIAL_MATCH_ARCSEC = 10.0
PATCH_RADIUS = 24
ANN_IN = 12.0
ANN_OUT = 20.0
CORE_RADIUS = 7.0
LOCAL_CENTROID_MAX_PIX = 3.0
K_SCIENCE_NEAREST = 10

TILE_RE = re.compile(
    r"(D_x(?P<x0>\d+)-(?P<x1>\d+)_y(?P<y0>\d+)-(?P<y1>\d+))",
    re.I
)

FEATURES = [
    "centroid_offset_pix",
    "moment_radius_pix",
    "quadrant_imbalance",
    "concentration_ap3_ap7",
    "concentration_ap5_ap7",
    "radial0_norm",
    "radial1_norm",
    "radial2_norm",
    "radial3_norm",
]


def read_csv_file(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        x = float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def i(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def angsep_arcsec(ra1, dec1, ra2, dec2):
    r1, r2 = math.radians(ra1), math.radians(ra2)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c))*3600.0


def parse_platephot(path):
    obj = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(obj, list) or not obj or not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{path.name}: expected JSON list[str]")
    return list(csv.DictReader(io.StringIO("\n".join(obj))))


def robust_sigma(vals):
    a = np.asarray(vals, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 8:
        return None
    med = float(np.median(a))
    mad = float(np.median(np.abs(a-med)))
    sig = 1.4826*mad
    if not np.isfinite(sig) or sig <= 0:
        sig = float(np.std(a))
    return sig if np.isfinite(sig) and sig > 0 else None


def parse_tile(path):
    m = TILE_RE.search(path.stem)
    if not m:
        return None
    return {
        "tile_id": m.group(1),
        "x0": int(m.group("x0")),
        "x1": int(m.group("x1")),
        "y0": int(m.group("y0")),
        "y1": int(m.group("y1")),
        "path": path,
    }


def discover_tiles():
    found = {}
    for top in (WORK, BASE, ROOT/"work", ROOT/"results"):
        if not top.exists():
            continue
        for p in top.rglob("*.npy"):
            t = parse_tile(p)
            if t is None:
                continue
            score = 0
            low = str(p).lower()
            if "order01_native_full_v028" in low:
                score += 100
            if "dasch" in low:
                score += 20
            score -= len(p.parts)
            old = found.get(t["tile_id"])
            if old is None or score > old[0]:
                found[t["tile_id"]] = (score, t)
    return {k:v[1] for k,v in found.items()}


ARR_CACHE = {}
def load_array(tile):
    key = str(tile["path"])
    if key not in ARR_CACHE:
        arr = np.load(tile["path"], mmap_mode="r")
        if arr.ndim != 2:
            raise RuntimeError(f"tile not 2-D: {tile['path']} shape={arr.shape}")
        ARR_CACHE[key] = arr
    return ARR_CACHE[key]


def extract_patch(tile, lx, ly, r=PATCH_RADIUS):
    arr = load_array(tile)
    xi = int(round(lx))
    yi = int(round(ly))
    if yi-r < 0 or xi-r < 0 or yi+r >= arr.shape[0] or xi+r >= arr.shape[1]:
        return None
    return np.asarray(arr[yi-r:yi+r+1, xi-r:xi+r+1], dtype=float)


def raw_metrics(patch, polarity):
    n = patch.shape[0]
    c = (n-1)/2.0
    yy, xx = np.indices(patch.shape, dtype=float)
    dx = xx-c
    dy = yy-c
    rr = np.hypot(dx, dy)

    ann = patch[(rr >= ANN_IN) & (rr <= ANN_OUT)]
    bg = float(np.median(ann))
    sig = robust_sigma(ann)
    if sig is None:
        return None

    z = (patch-bg)/sig
    signed = polarity*z

    m3 = (np.abs(dx)<=1) & (np.abs(dy)<=1)
    core = rr <= CORE_RADIUS

    out = {
        "background_median": bg,
        "background_sigma": sig,
        "center3_signed_zmean": float(np.mean(signed[m3])),
        "core_signed_peak_z": float(np.max(signed[core])),
        "core_signed_min_z": float(np.min(signed[core])),
    }

    for rad in (2,3,5,7):
        m = rr <= rad
        out[f"ap{rad}_signed_zsum"] = float(np.sum(signed[m]))
        out[f"ap{rad}_signed_zmean"] = float(np.mean(signed[m]))

    w = np.where(core, np.clip(signed,0,None), 0.0)
    sw = float(np.sum(w))
    if sw > 0:
        cx = float(np.sum(w*dx)/sw)
        cy = float(np.sum(w*dy)/sw)
        out["centroid_dx_pix"] = cx
        out["centroid_dy_pix"] = cy
        out["centroid_offset_pix"] = float(math.hypot(cx,cy))
        out["moment_radius_pix"] = float(math.sqrt(
            max(0.0, np.sum(w*(dx*dx+dy*dy))/sw)
        ))
    else:
        out["centroid_dx_pix"] = None
        out["centroid_dy_pix"] = None
        out["centroid_offset_pix"] = None
        out["moment_radius_pix"] = None

    quads=[]
    for sx,sy in ((1,1),(-1,1),(-1,-1),(1,-1)):
        qm = core & (dx*sx>=0) & (dy*sy>=0)
        quads.append(float(np.sum(signed[qm])))
    qmean = float(np.mean(np.abs(quads)))
    out["quadrant_imbalance"] = float(np.std(quads)/qmean) if qmean>0 else None

    for lo,hi in ((0,1.5),(1.5,3),(3,5),(5,7),(7,10),(10,12)):
        m = (rr>=lo) & (rr<hi)
        out[f"radial_{lo:g}_{hi:g}_signed_zmean"] = float(np.mean(signed[m]))

    return out


def derived_shape(r):
    ap3 = f(r.get("ap3_signed_zsum"))
    ap5 = f(r.get("ap5_signed_zsum"))
    ap7 = f(r.get("ap7_signed_zsum"))
    radial = [
        f(r.get("radial_0_1.5_signed_zmean")),
        f(r.get("radial_1.5_3_signed_zmean")),
        f(r.get("radial_3_5_signed_zmean")),
        f(r.get("radial_5_7_signed_zmean")),
    ]
    if any(x is None for x in radial):
        rn=[None]*4
    else:
        den=sum(abs(x) for x in radial)
        rn=[x/den for x in radial] if den>0 else [None]*4

    return {
        "centroid_offset_pix": f(r.get("centroid_offset_pix")),
        "moment_radius_pix": f(r.get("moment_radius_pix")),
        "quadrant_imbalance": f(r.get("quadrant_imbalance")),
        "concentration_ap3_ap7":
            (ap3/ap7 if ap3 is not None and ap7 not in (None,0) else None),
        "concentration_ap5_ap7":
            (ap5/ap7 if ap5 is not None and ap7 not in (None,0) else None),
        "radial0_norm": rn[0],
        "radial1_norm": rn[1],
        "radial2_norm": rn[2],
        "radial3_norm": rn[3],
    }


def robust_center_scale(X):
    a=np.asarray(X,float)
    med=np.median(a,axis=0)
    mad=np.median(np.abs(a-med),axis=0)
    scale=1.4826*mad
    std=np.std(a,axis=0,ddof=1)
    scale=np.where((~np.isfinite(scale))|(scale<=1e-9),std,scale)
    scale=np.where((~np.isfinite(scale))|(scale<=1e-9),1.0,scale)
    return med,scale


def shape_distance(z1,z2):
    d=np.asarray(z1)-np.asarray(z2)
    return float(np.sqrt(np.mean(d*d)))


def empirical_percentile(vals,x):
    a=np.asarray([v for v in vals if v is not None and np.isfinite(v)],float)
    if x is None or a.size==0:
        return None
    return float((np.sum(a<x)+0.5*np.sum(a==x))/a.size)


def nearest_official_sep(ra,dec,official):
    if not official:
        return None
    vals=[angsep_arcsec(ra,dec,o["ra_deg"],o["dec_deg"]) for o in official]
    return min(vals)


def main():
    print("="*128)
    print("ORDER 01 — LOCAL PREVALENCE OF UNCATALOGUED STELLAR-LIKE DASCH NATIVE DETECTIONS v028aw")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("NON-SCIENCE CONTROL PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,STRICT,DASCH_NATIVE,MORPH,SHAPE):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    strict_rows=read_csv_file(STRICT)
    native=read_csv_file(DASCH_NATIVE)
    morph=json.loads(MORPH.read_text(encoding="utf-8"))
    shape=json.loads(SHAPE.read_text(encoding="utf-8"))

    if morph.get("guards",{}).get("science_pixels_read") is not True:
        raise RuntimeError("v028ar-r1 science pixel provenance guard mismatch")
    if shape.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028as mutation guard mismatch")

    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in RANKS}
    if sorted(strict)!=RANKS:
        raise RuntimeError("strict-rank guard mismatch")

    # Exact v028r query centres.
    centres={}
    science_keys=set()
    for rank in RANKS:
        s=strict[rank]
        pra,pdec=f(s["poss_ra_deg"]),f(s["poss_dec_deg"])
        dra,ddec=f(s["dasch_ra_deg"]),f(s["dasch_dec_deg"])
        centres[rank]={
            "ra_deg":(pra+dra)/2.0,
            "dec_deg":(pdec+ddec)/2.0,
        }
        science_keys.add((str(s["dasch_tile_id"]),i(s.get("dasch_candidate_index"))))

    # Exact union of cached official fitted rows.
    official_by_key={}
    for rank in RANKS:
        p=RAW_DIR/f"{PLATE}_sol0_rank{rank}_apass_platephot.json"
        if not p.is_file():
            raise RuntimeError(f"missing raw platephot cache: {p}")
        for row in parse_platephot(p):
            if str(row.get("series","")).strip()!="ai" or i(row.get("plate_number"))!=43437:
                continue
            ra,dec=f(row.get("ra_deg")),f(row.get("dec_deg"))
            if ra is None or dec is None:
                continue
            key=(str(row.get("ref_number","")),round(ra,8),round(dec,8))
            official_by_key.setdefault(key,{
                "ref_number":row.get("ref_number"),
                "ra_deg":ra,
                "dec_deg":dec,
                "aflags":i(row.get("aflags")),
                "bflags":i(row.get("bflags")),
            })
    official=list(official_by_key.values())

    # Reconstruct official shape cloud exactly as v028as.
    control_rows=morph.get("official_controls",[])
    good_controls=[]
    good_derived=[]
    for r in control_rows:
        d=derived_shape(r)
        if all(d[k] is not None and np.isfinite(d[k]) for k in FEATURES):
            good_controls.append(r)
            good_derived.append(d)
    if len(good_controls)<8:
        raise RuntimeError(f"too few complete official controls: {len(good_controls)}")

    X=np.asarray([[d[k] for k in FEATURES] for d in good_derived],float)
    med,scale=robust_center_scale(X)
    Z=(X-med)/scale

    loo_nn=[]
    for j in range(len(Z)):
        ds=[shape_distance(Z[j],Z[k]) for k in range(len(Z)) if k!=j]
        loo_nn.append(min(ds))
    loo_p95=float(np.quantile(loo_nn,0.95))

    physical = morph.get("empirical_physical_polarity")
    if physical not in ("RAW_HIGH","RAW_LOW"):
        raise RuntimeError("invalid v028ar-r1 physical polarity")
    physical_polarity=1 if physical=="RAW_HIGH" else -1

    # Stored tile transforms from successful v028ar-r1.
    transforms={}
    for r in morph.get("tile_transforms",[]):
        tid=str(r["tile_id"])
        transforms[tid]={
            "offset_x":f(r["offset_x"]),
            "offset_y":f(r["offset_y"]),
            "tile_x0":i(r["tile_x0"]),
            "tile_y0":i(r["tile_y0"]),
        }

    tiles=discover_tiles()
    for tid in transforms:
        if tid not in tiles:
            raise RuntimeError(f"transform tile array missing: {tid}")

    # Select all non-science native detections in union of 5' inner regions.
    local=[]
    region_counts=defaultdict(int)

    for r in native:
        ra,dec=f(r.get("ra_deg")),f(r.get("dec_deg"))
        if ra is None or dec is None:
            continue

        dists=[(angsep_arcsec(ra,dec,centres[rank]["ra_deg"],centres[rank]["dec_deg"]),rank)
               for rank in RANKS]
        dist,rank=min(dists)
        if dist>LOCAL_RADIUS_ARCSEC:
            continue

        tid=str(r.get("tile_id",""))
        idx=i(r.get("candidate_index"))
        is_science=(tid,idx) in science_keys
        if is_science:
            continue

        region_counts[rank]+=1
        local.append((r,rank,dist))

    print(f"Frozen native DASCH detections in local 5' union excluding science: {len(local)}")
    print("Per nearest science-region centre:")
    for rank in RANKS:
        print(f"  #{rank}: {region_counts[rank]}")

    candidate_rows=[]
    usable=0
    edge_skip=0
    transform_skip=0

    for r,rank,dist in local:
        tid=str(r.get("tile_id",""))
        if tid not in transforms or tid not in tiles:
            transform_skip+=1
            continue

        gx,gy=f(r.get("global_x")),f(r.get("global_y"))
        if gx is None or gy is None:
            transform_skip+=1
            continue

        tr=transforms[tid]
        tile=tiles[tid]
        lx=gx-tr["tile_x0"]-tr["offset_x"]
        ly=gy-tr["tile_y0"]-tr["offset_y"]

        patch=extract_patch(tile,lx,ly)
        if patch is None:
            edge_skip+=1
            continue

        m=raw_metrics(patch,physical_polarity)
        if m is None:
            continue
        usable+=1

        d=derived_shape(m)
        shape_complete=all(d[k] is not None and np.isfinite(d[k]) for k in FEATURES)
        if shape_complete:
            x=np.asarray([d[k] for k in FEATURES],float)
            z=(x-med)/scale
            ds=[shape_distance(z,Z[k]) for k in range(len(Z))]
            shape_nn=float(min(ds))
            shape_pct=empirical_percentile(loo_nn,shape_nn)
            shape_consistent=shape_nn<=loo_p95
        else:
            shape_nn=None
            shape_pct=None
            shape_consistent=False

        ra,dec=f(r["ra_deg"]),f(r["dec_deg"])
        offsep=nearest_official_sep(ra,dec,official)
        official_associated=(offsep is not None and offsep<=OFFICIAL_MATCH_ARCSEC)

        star_dir=m["center3_signed_zmean"]>0
        ap_pos=m["ap5_signed_zsum"]>0
        cent=m["centroid_offset_pix"]
        locally_concentrated=(cent is not None and cent<=LOCAL_CENTROID_MAX_PIX)
        basic_stellar=star_dir and ap_pos and locally_concentrated
        phenotype=(not official_associated) and basic_stellar and shape_consistent

        candidate_rows.append({
            "nearest_science_rank":rank,
            "query_center_sep_arcsec":dist,
            "tile_id":tid,
            "candidate_index":i(r.get("candidate_index")),
            "detector_snr":f(r.get("snr")),
            "detector_polarity":i(r.get("polarity")),
            "ra_deg":ra,
            "dec_deg":dec,
            "nearest_official_sep_arcsec":offsep,
            "official_associated_within10arcsec":official_associated,
            "center3_signed_zmean":m["center3_signed_zmean"],
            "ap5_signed_zsum":m["ap5_signed_zsum"],
            "centroid_offset_pix":m["centroid_offset_pix"],
            "moment_radius_pix":m["moment_radius_pix"],
            "shape_nn":shape_nn,
            "shape_nn_control_loo_percentile":shape_pct,
            "shape_consistent_with_official_cloud":shape_consistent,
            "basic_stellar_morphology":basic_stellar,
            "uncatalogued_stellar_like_local_native":phenotype,
        })

    if usable==0:
        raise RuntimeError("no usable local native control patches")

    # Summary counts.
    n=len(candidate_rows)
    npos=sum(r["detector_polarity"]==1 for r in candidate_rows)
    noff=sum(r["official_associated_within10arcsec"] for r in candidate_rows)
    nuncat=n-noff
    nbasic=sum(r["basic_stellar_morphology"] for r in candidate_rows)
    nshape=sum(r["shape_consistent_with_official_cloud"] for r in candidate_rows)
    nphen=sum(r["uncatalogued_stellar_like_local_native"] for r in candidate_rows)
    nphen_pos=sum(
        r["uncatalogued_stellar_like_local_native"] and r["detector_polarity"]==1
        for r in candidate_rows
    )

    uncatalogued=[r for r in candidate_rows if not r["official_associated_within10arcsec"]]
    positive=[r for r in candidate_rows if r["detector_polarity"]==1]
    uncatalogued_positive=[r for r in positive if not r["official_associated_within10arcsec"]]

    summary=[{
        "local_radius_arcsec":LOCAL_RADIUS_ARCSEC,
        "official_match_arcsec":OFFICIAL_MATCH_ARCSEC,
        "native_local_non_science_selected":len(local),
        "usable_pixel_controls":n,
        "edge_skipped":edge_skip,
        "transform_skipped":transform_skip,
        "detector_positive_controls":npos,
        "official_associated_controls":noff,
        "uncatalogued_controls":nuncat,
        "basic_stellar_morphology_controls":nbasic,
        "shape_consistent_controls":nshape,
        "uncatalogued_stellar_like_controls":nphen,
        "uncatalogued_stellar_like_fraction_all_usable":nphen/n if n else None,
        "uncatalogued_stellar_like_fraction_uncatalogued":
            nphen/len(uncatalogued) if uncatalogued else None,
        "uncatalogued_stellar_like_fraction_detector_positive":
            nphen_pos/npos if npos else None,
        "uncatalogued_stellar_like_fraction_uncatalogued_detector_positive":
            nphen_pos/len(uncatalogued_positive) if uncatalogued_positive else None,
        "official_shape_control_count":len(good_controls),
        "official_shape_loo_p95":loo_p95,
        "official_row_union_count":len(official),
    }]

    print("\nLocal phenotype prevalence:")
    print(f"  usable local native controls:                 {n}")
    print(f"  detector polarity +1:                         {npos}")
    print(f"  official-associated <=10\":                    {noff}")
    print(f"  uncatalogued >10\":                            {nuncat}")
    print(f"  basic stellar morphology:                     {nbasic}")
    print(f"  shape-consistent with official-star cloud:    {nshape}")
    print(f"  UNCATALOGUED_STELLAR_LIKE_LOCAL_NATIVE:       {nphen}")
    print(
        f"  fraction all usable:                          "
        f"{nphen/n:.6f}" if n else "  fraction all usable: n/a"
    )
    print(
        f"  fraction among uncatalogued:                  "
        f"{nphen/len(uncatalogued):.6f}" if uncatalogued
        else "  fraction among uncatalogued: n/a"
    )
    print(
        f"  fraction among detector +1:                   "
        f"{nphen_pos/npos:.6f}" if npos
        else "  fraction among detector +1: n/a"
    )

    # Compare each science candidate to the local phenotype population by
    # amplitude and shape NN, and identify nearest local phenotype controls in
    # (shapeNN, ap5) descriptive space.
    science_morph={i(r["strict_rank"]):r for r in morph.get("science",[])}
    science_shape={i(r["strict_rank"]):r for r in shape.get("summaries",[])}

    phen=[r for r in candidate_rows if r["uncatalogued_stellar_like_local_native"]]
    nearest_rows=[]

    if phen:
        phen_shape=[r["shape_nn"] for r in phen if r["shape_nn"] is not None]
        phen_ap5=[r["ap5_signed_zsum"] for r in phen]
        sh_scale=np.std(phen_shape,ddof=1) if len(phen_shape)>1 else 1.0
        ap_scale=np.std(phen_ap5,ddof=1) if len(phen_ap5)>1 else 1.0
        if not np.isfinite(sh_scale) or sh_scale<=0: sh_scale=1.0
        if not np.isfinite(ap_scale) or ap_scale<=0: ap_scale=1.0

        for rank in RANKS:
            sm=science_morph[rank]
            ss=science_shape[rank]
            ssh=f(ss["nearest_shape_distance"])
            sap=f(sm["ap5_signed_zsum"])
            scored=[]
            for r in phen:
                if r["shape_nn"] is None:
                    continue
                dist=math.sqrt(
                    ((r["shape_nn"]-ssh)/sh_scale)**2 +
                    ((r["ap5_signed_zsum"]-sap)/ap_scale)**2
                )
                scored.append((dist,r))
            scored.sort(key=lambda x:x[0])
            for pos,(dist,r) in enumerate(scored[:K_SCIENCE_NEAREST],start=1):
                nearest_rows.append({
                    "strict_rank":rank,
                    "neighbor_rank":pos,
                    "standardized_shape_amplitude_distance":dist,
                    "control_nearest_science_rank":r["nearest_science_rank"],
                    "control_tile_id":r["tile_id"],
                    "control_candidate_index":r["candidate_index"],
                    "control_ra_deg":r["ra_deg"],
                    "control_dec_deg":r["dec_deg"],
                    "control_detector_snr":r["detector_snr"],
                    "control_detector_polarity":r["detector_polarity"],
                    "control_nearest_official_sep_arcsec":r["nearest_official_sep_arcsec"],
                    "control_center3_signed_zmean":r["center3_signed_zmean"],
                    "control_ap5_signed_zsum":r["ap5_signed_zsum"],
                    "control_centroid_offset_pix":r["centroid_offset_pix"],
                    "control_moment_radius_pix":r["moment_radius_pix"],
                    "control_shape_nn":r["shape_nn"],
                    "science_shape_nn":ssh,
                    "science_ap5_signed_zsum":sap,
                })

    payload={
        "stage":"ORDER01_DASCH_LOCAL_UNCATALOGUED_STELLAR_PREVALENCE_V028AW",
        "plate":PLATE,
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "non_science_control_pixels_read":True,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "local_prevalence_not_full_plate_completeness":True,
            "local_inner_radius_arcsec":LOCAL_RADIUS_ARCSEC,
            "official_match_radius_arcsec":OFFICIAL_MATCH_ARCSEC,
            "science_candidates_excluded_from_control_population":True,
            "official_shape_scaling_reconstructed_from_v028ar_controls_only":True,
            "tile_transforms_reused_from_v028ar_r1":True,
        },
        "query_centres":{str(k):v for k,v in centres.items()},
        "summary":summary[0],
        "region_selected_counts":{str(k):region_counts[k] for k in RANKS},
        "candidate_controls":candidate_rows,
        "science_nearest_local_phenotype_controls":nearest_rows,
        "interpretive_boundary":(
            "v028aw measures how often the science phenotype occurs among other "
            "frozen native DASCH detections in conservative 5-arcmin inner regions "
            "around the six v028r science-centred platephot queries. It is not a "
            "full-plate DR7 completeness estimate and counts detector candidates, "
            "not unique astrophysical objects. A common phenotype supports ordinary "
            "DR7 extraction incompleteness; a rare phenotype makes the six science "
            "features more unusual but does not prove astrophysical transience."
        ),
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_SUMMARY,summary,list(summary[0]))
    write_csv(OUT_CANDIDATES,candidate_rows,list(candidate_rows[0]))
    if nearest_rows:
        write_csv(OUT_NEAREST,nearest_rows,list(nearest_rows[0]))
    else:
        write_csv(OUT_NEAREST,[],[
            "strict_rank","neighbor_rank","standardized_shape_amplitude_distance"
        ])

    md=[
        "# ORDER 01 — Local Uncatalogued Stellar-Like DASCH Prevalence v028aw","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- Non-science control pixels were read.",
        "- The frozen detector was not rerun.",
        "- No endpoint state was changed.",
        "- This is a local 5-arcmin-inner-region prevalence test, not full-plate completeness.","",
        "## Local prevalence","",
        f"- Usable non-science frozen native controls: **{n}**.",
        f"- Official-associated within 10″: **{noff}**.",
        f"- Uncatalogued beyond 10″: **{nuncat}**.",
        f"- Uncatalogued + stellar-like phenotype: **{nphen}**.",
        f"- Phenotype fraction of all usable controls: **{(nphen/n if n else float('nan')):.6f}**.",
        f"- Phenotype fraction among uncatalogued controls: **{(nphen/len(uncatalogued) if uncatalogued else float('nan')):.6f}**.","",
        "## Interpretation boundary","",
        payload["interpretive_boundary"]
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_SUMMARY}")
    print(f"  {OUT_CANDIDATES}")
    print(f"  {OUT_NEAREST}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("NON-SCIENCE CONTROL PIXELS WERE READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
