#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from array import array
import csv
import hashlib
import json
import math
import re

import numpy as np

try:
    from scipy.spatial import cKDTree
except Exception as exc:
    raise RuntimeError(
        "v065 requires scipy.spatial.cKDTree. The project Astropy environment "
        "normally provides SciPy; no network install is attempted."
    ) from exc

try:
    from astropy.time import Time
except Exception as exc:
    raise RuntimeError("v065 requires the already-used project dependency astropy") from exc


ROOT=Path.cwd()

FREEZE_V001=ROOT/"research/prospective_freezes/wide_census_gaia_reference_acquisition_contract_v001.json"
FREEZE_V002=ROOT/"research/prospective_freezes/wide_census_gaia_reference_acquisition_contract_v002.json"

V063=ROOT/"results/wide_census_gaia_registration_preflight_v063/wide_census_gaia_registration_preflight_v063.json"
PAIR_WORK=ROOT/"results/wide_census_gaia_registration_preflight_v063/wide_census_gaia_registration_pair_workload_v063.csv"
GLOBAL_PLAN=ROOT/"results/wide_census_gaia_query_dedup_v063a/wide_census_gaia_unique_ordinary_query_cells_v063a.csv"
GLOBAL_HPM=ROOT/"results/wide_census_gaia_query_dedup_v063a/wide_census_gaia_unique_hpm_queries_v063a.csv"
V064=ROOT/"results/wide_census_gaia_acquisition_v064/wide_census_gaia_acquisition_v064.json"
V064_CACHE=ROOT/"results/wide_census_gaia_acquisition_v064/cache/ordinary"

PAIR_PLAN=ROOT/"results/wide_census_detector_pair_plan_v054.json"
CAND=ROOT/"results/wide_census_detector_candidates_v056.csv"
RAW=ROOT/"results/wide_census_pair_raw_matches_v056.csv"

OUTDIR=ROOT/"results/wide_census_gaia_reference_coverage_audit_v065"
REPORT=OUTDIR/"wide_census_gaia_reference_coverage_audit_v065.json"
PAIR_SUM=OUTDIR/"wide_census_gaia_reference_coverage_pair_summary_v065.csv"
PAIR_CELLS=OUTDIR/"wide_census_gaia_reference_candidate_cells_v065.csv"
SUPP=OUTDIR/"wide_census_gaia_supplemental_query_plan_v065.csv"
HPM_OUT=OUTDIR/"wide_census_gaia_corrected_hpm_pair_queries_v065.csv"

EXPECTED_FREEZE_V001_SHA="7a182349455a814423d68411d49aa7640dacdbe8dd6bafd5a5ec747c64b097fc"
EXPECTED_PAIRS=33
EXPECTED_RAW=512788
EXPECTED_CAND=5083325
EXPECTED_BASE=5418
EXPECTED_HPM=24

BASE_CELL_DEG=0.25
OLD_MARGIN_ARCSEC=120.0
HPM_SPLIT_MASYR=1700.0
REFERENCE_ACQUISITION_ARCSEC=15.0
MAX_REFERENCE_WINDOW_ARCMIN=30.0
OLD_HPM_MARGIN_ARCSEC=900.0
MAXREC=50000
MIN_CELL_DEG=0.03125

# Pure transport rounding: calculate the mathematical requirement, then round UP
# to the next 0.1 arcsec so floating-point representation cannot shrink coverage.
TRANSPORT_MARGIN_ROUND_ARCSEC=0.1

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def read_csv(p):
    with p.open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_json(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    t.replace(p)

def write_csv(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    with t.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    t.replace(p)

def fnum(v):
    try:
        x=float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None

def inum(v):
    x=fnum(v)
    return None if x is None else int(x)

def parse_pairs():
    obj=json.loads(PAIR_PLAN.read_text(encoding="utf-8"))
    pairs=obj.get("pairs")
    if not isinstance(pairs,list) or len(pairs)!=EXPECTED_PAIRS:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_PAIRS} pair-plan rows")
    out={}
    for i,p in enumerate(pairs,1):
        out[i]={
            "pair_index":i,
            "canonical_pair":str(p["canonical_pair"]),
            "endpoint_a":str(p["endpoint_a"]),
            "endpoint_b":str(p["endpoint_b"]),
        }
    return out

def unit_vectors(ra,dec):
    r=np.deg2rad(np.asarray(ra,dtype=np.float64))
    d=np.deg2rad(np.asarray(dec,dtype=np.float64))
    cd=np.cos(d)
    return np.column_stack((cd*np.cos(r),cd*np.sin(r),np.sin(d)))

def midpoint(ra1,dec1,ra2,dec2):
    a=unit_vectors([ra1],[dec1])[0]
    b=unit_vectors([ra2],[dec2])[0]
    v=a+b
    q=float(np.linalg.norm(v))
    if q==0: raise RuntimeError("antipodal raw endpoints")
    v/=q
    return math.degrees(math.atan2(v[1],v[0]))%360.0, math.degrees(math.asin(max(-1,min(1,v[2]))))

def cell_id(ra,dec):
    return (
        int(math.floor((ra%360.0)/BASE_CELL_DEG)),
        int(math.floor((dec+90.0)/BASE_CELL_DEG)),
    )

def angsep_deg(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    return math.degrees(math.acos(max(-1,min(1,c))))

def bounds_for_base(ira,idec):
    return (
        ira*BASE_CELL_DEG,(ira+1)*BASE_CELL_DEG,
        -90+idec*BASE_CELL_DEG,-90+(idec+1)*BASE_CELL_DEG,
    )

def child_bounds(bounds,q):
    r0,r1,d0,d1=bounds
    rm=(r0+r1)/2; dm=(d0+d1)/2
    return {
        0:(r0,rm,d0,dm),1:(rm,r1,d0,dm),
        2:(r0,rm,dm,d1),3:(rm,r1,dm,d1),
    }[q]

def query_geom(bounds,margin_arcsec):
    r0,r1,d0,d1=bounds
    ra=((r0+r1)/2)%360.0
    dec=(d0+d1)/2
    corners=[(r0,d0),(r1,d0),(r0,d1),(r1,d1)]
    far=max(angsep_deg(ra,dec,x%360,y) for x,y in corners)
    return ra,dec,far+margin_arcsec/3600.0

def base_key(ira,idec,depth,path):
    return f"cell_{ira:04d}_{idec:04d}_d{depth}_{path or 'root'}"

def complete_leaves(ira,idec):
    """Return existing v064 COMPLETE leaf geometry without reading Gaia rows."""
    out=[]
    def walk(bounds,path,depth):
        key=base_key(ira,idec,depth,path)
        mp=V064_CACHE/(key+".meta.json")
        if not mp.is_file():
            raise RuntimeError(f"REFUSING: v064 cache metadata missing for acquired base cell {ira},{idec}: {mp}")
        m=json.loads(mp.read_text(encoding="utf-8"))
        st=m.get("status")
        if st=="COMPLETE":
            old_ra=fnum(m.get("query_ra_deg"))
            old_dec=fnum(m.get("query_dec_deg"))
            old_rad=fnum(m.get("query_radius_deg"))
            if None in (old_ra,old_dec,old_rad):
                raise RuntimeError(f"REFUSING: incomplete query geometry in {mp}")
            out.append({
                "key":key,"bounds":bounds,"depth":depth,"path":path or "root",
                "old_ra":old_ra,"old_dec":old_dec,"old_radius_deg":old_rad,
            })
            return
        if st=="SUBDIVIDED":
            for q in range(4):
                walk(child_bounds(bounds,q),path+str(q),depth+1)
            return
        raise RuntimeError(f"REFUSING: unexpected v064 cache state {st!r} for {mp}")
    walk(bounds_for_base(ira,idec),"",0)
    return out

def ceil_step(x,step):
    return math.ceil((x-1e-12)/step)*step

def main():
    print("="*136)
    print("WIDE CENSUS — GAIA REFERENCE-DOMAIN COVERAGE AUDIT v065")
    print("="*136)
    print("NO NETWORK. NO GAIA SOURCE ROWS READ. NO PIXELS. NO DETECTOR. NO REGISTRATION. NO CANDIDATE MUTATION.")
    print("Purpose: prove/correct Gaia transport coverage for the already-frozen 30' target-independent reference construction.\n")

    for p in (FREEZE_V001,V063,PAIR_WORK,GLOBAL_PLAN,GLOBAL_HPM,V064,PAIR_PLAN,CAND,RAW):
        if not p.is_file(): raise RuntimeError(f"REFUSING: missing prerequisite {p}")
    if sha(FREEZE_V001)!=EXPECTED_FREEZE_V001_SHA:
        raise RuntimeError("REFUSING: v001 Gaia acquisition freeze SHA changed")

    v64=json.loads(V064.read_text(encoding="utf-8"))
    if v64.get("status")!="COMPLETE":
        raise RuntimeError("REFUSING: v064 acquisition is not COMPLETE")
    prog=v64.get("progress") or {}
    if int(prog.get("ordinary_base_complete",-1))!=EXPECTED_BASE:
        raise RuntimeError("REFUSING: v064 ordinary acquisition count differs")
    if int(prog.get("hpm_complete",-1))!=EXPECTED_HPM:
        raise RuntimeError("REFUSING: v064 HPM acquisition count differs")

    pairs=parse_pairs()
    pair_work=read_csv(PAIR_WORK)
    if len(pair_work)!=EXPECTED_PAIRS:
        raise RuntimeError("REFUSING: v063 pair workload count differs")

    # Compute exact worst pair epoch displacement to the Gaia DR3 reference epoch,
    # without inspecting any Gaia source outcome.
    gaia_epoch=Time(2016.0,format="jyear").utc.datetime.replace(tzinfo=timezone.utc)
    epoch_by_pair={}
    dt_years={}
    for r in pair_work:
        idx=int(r["pair_index"])
        s=str(r["registration_epoch_utc"]).strip()
        if s.endswith("Z"): s=s[:-1]+"+00:00"
        d=datetime.fromisoformat(s)
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        d=d.astimezone(timezone.utc)
        epoch_by_pair[idx]=d
        dt_years[idx]=abs((gaia_epoch-d).total_seconds())/(365.25*86400.0)

    max_dt=max(dt_years.values())
    mathematical_margin=max_dt*(HPM_SPLIT_MASYR/1000.0)+REFERENCE_ACQUISITION_ARCSEC
    corrected_margin=ceil_step(mathematical_margin,TRANSPORT_MARGIN_ROUND_ARCSEC)
    corrected_hpm_margin=OLD_HPM_MARGIN_ARCSEC+REFERENCE_ACQUISITION_ARCSEC
    candidate_search_arcmin=MAX_REFERENCE_WINDOW_ARCMIN+REFERENCE_ACQUISITION_ARCSEC/60.0

    print(f"Worst |2016.0 - registration epoch|: {max_dt:.6f} yr")
    print(f"Old ordinary margin: {OLD_MARGIN_ARCSEC:.1f}\"")
    print(f"Required ordinary margin (<{HPM_SPLIT_MASYR:.0f} mas/yr + 15\" association): {mathematical_margin:.3f}\"")
    print(f"Corrected transport margin (rounded upward): {corrected_margin:.1f}\"")
    print(f"Frozen reference candidate search radius: {candidate_search_arcmin:.2f}'")
    print(f"Corrected HPM transport margin: {corrected_hpm_margin:.1f}\"\n")

    # Raw target midpoints by pair.
    raw_ra={i:array("d") for i in pairs}; raw_dec={i:array("d") for i in pairs}
    nraw=0
    with RAW.open(newline="",encoding="utf-8-sig") as f:
        rdr=csv.DictReader(f)
        for n,r in enumerate(rdr,1):
            idx=inum(r.get("pair_index"))
            if idx not in pairs: raise RuntimeError(f"REFUSING: raw row {n} bad pair_index={idx}")
            vals=[fnum(r.get(k)) for k in ("a_ra_deg","a_dec_deg","b_ra_deg","b_dec_deg")]
            if any(x is None for x in vals):
                raise RuntimeError(f"REFUSING: raw row {n} missing endpoint coordinate")
            ra,dec=midpoint(*vals)
            raw_ra[idx].append(ra);raw_dec[idx].append(dec);nraw+=1
    if nraw!=EXPECTED_RAW:
        raise RuntimeError(f"REFUSING: raw rows={nraw}, expected={EXPECTED_RAW}")
    print(f"Raw target midpoints loaded: {nraw:,}")

    # Candidate coordinates by endpoint; array('d') avoids millions of Python-float objects.
    eps=sorted({p["endpoint_a"] for p in pairs.values()}|{p["endpoint_b"] for p in pairs.values()})
    cand_ra={e:array("d") for e in eps};cand_dec={e:array("d") for e in eps}
    nc=0
    with CAND.open(newline="",encoding="utf-8-sig") as f:
        rdr=csv.DictReader(f)
        for n,r in enumerate(rdr,1):
            ep=str(r.get("endpoint_key",""))
            if ep not in cand_ra:
                raise RuntimeError(f"REFUSING: candidate row {n} unknown endpoint {ep!r}")
            ra=fnum(r.get("ra_deg"));dec=fnum(r.get("dec_deg"))
            if ra is None or dec is None:
                raise RuntimeError(f"REFUSING: candidate row {n} invalid coordinates")
            cand_ra[ep].append(ra);cand_dec[ep].append(dec);nc+=1
    if nc!=EXPECTED_CAND:
        raise RuntimeError(f"REFUSING: candidate rows={nc}, expected={EXPECTED_CAND}")
    print(f"Frozen detector candidate coordinates loaded: {nc:,}\n")

    old_rows=read_csv(GLOBAL_PLAN)
    if len(old_rows)!=EXPECTED_BASE:
        raise RuntimeError("REFUSING: global v063a plan count differs")
    old_cells={(int(r["cell_ira"]),int(r["cell_idec"])):r for r in old_rows}

    pair_cell_rows=[]
    pair_summary=[]
    all_required_cells=set()
    pair_hpm=[]

    theta=math.radians(candidate_search_arcmin/60.0)
    chord=2.0*math.sin(theta/2.0)

    for idx in range(1,EXPECTED_PAIRS+1):
        p=pairs[idx]
        tra=np.frombuffer(raw_ra[idx],dtype=np.float64)
        tdec=np.frombuffer(raw_dec[idx],dtype=np.float64)
        if len(tra)==0: raise RuntimeError(f"REFUSING: pair {idx} has no raw targets")
        tvec=unit_vectors(tra,tdec)
        tree=cKDTree(tvec)

        required=set()
        eligible_count=0
        hpm_sum=np.zeros(3,dtype=np.float64)
        hpm_coords=[]

        for ep in (p["endpoint_a"],p["endpoint_b"]):
            era=np.frombuffer(cand_ra[ep],dtype=np.float64)
            edec=np.frombuffer(cand_dec[ep],dtype=np.float64)
            # Chunk to keep temporary Nx3 arrays bounded.
            for s in range(0,len(era),250000):
                rr=era[s:s+250000];dd=edec[s:s+250000]
                vv=unit_vectors(rr,dd)
                dist,_=tree.query(vv,k=1,distance_upper_bound=chord,workers=-1)
                mask=np.isfinite(dist)
                if not np.any(mask): continue
                sr=rr[mask];sd=dd[mask];sv=vv[mask]
                eligible_count+=len(sr)
                hpm_sum+=sv.sum(axis=0)
                # Store eligible coords for exact HPM enclosing-cone radius after center is known.
                hpm_coords.append((np.array(sr,copy=True),np.array(sd,copy=True)))
                for ra,dec in zip(sr,sd):
                    required.add(cell_id(float(ra),float(dec)))

        if eligible_count==0:
            raise RuntimeError(f"REFUSING: pair {idx} has zero reference-domain detector candidates")

        q=np.linalg.norm(hpm_sum)
        if not np.isfinite(q) or q==0:
            raise RuntimeError(f"REFUSING: pair {idx} HPM vector center undefined")
        cvec=hpm_sum/q
        cra=math.degrees(math.atan2(cvec[1],cvec[0]))%360.0
        cdec=math.degrees(math.asin(max(-1,min(1,float(cvec[2])))))
        far=0.0
        for rr,dd in hpm_coords:
            for ra,dec in zip(rr,dd):
                far=max(far,angsep_deg(cra,cdec,float(ra),float(dec)))
        hpm_radius=far+corrected_hpm_margin/3600.0

        existing=sum(c in old_cells for c in required)
        new=len(required)-existing
        all_required_cells.update(required)

        for ira,idec in sorted(required):
            pair_cell_rows.append({
                "pair_index":idx,"canonical_pair":p["canonical_pair"],
                "endpoint_a":p["endpoint_a"],"endpoint_b":p["endpoint_b"],
                "cell_ira":ira,"cell_idec":idec,
                "already_acquired_v064":(ira,idec) in old_cells,
            })

        pair_summary.append({
            "pair_index":idx,"canonical_pair":p["canonical_pair"],
            "raw_targets":len(tra),
            "reference_domain_detector_candidates":eligible_count,
            "required_candidate_cells":len(required),
            "cells_already_present_v064":existing,
            "new_full_cells_required":new,
            "registration_epoch_utc":epoch_by_pair[idx].isoformat(),
            "delta_from_gaia2016_years":dt_years[idx],
        })
        pair_hpm.append({
            "pair_index":idx,"canonical_pair":p["canonical_pair"],
            "query_ra_deg":cra,"query_dec_deg":cdec,
            "query_radius_deg":hpm_radius,
            "pm_min_masyr":HPM_SPLIT_MASYR,
            "historical_reference_window_arcmin":MAX_REFERENCE_WINDOW_ARCMIN,
            "candidate_association_arcsec":REFERENCE_ACQUISITION_ARCSEC,
            "j2016_hpm_transport_margin_arcsec":corrected_hpm_margin,
            "registration_epoch_utc":epoch_by_pair[idx].isoformat(),
        })
        print(
            f"pair {idx:2d}/33: targets={len(tra):7d} eligible candidates={eligible_count:8d} "
            f"cells={len(required):5d} existing={existing:5d} new={new:5d}",
            flush=True
        )

    # Build global supplemental plan.
    supplemental=[]
    qidx=0
    existing_required=sorted(c for c in all_required_cells if c in old_cells)
    new_required=sorted(c for c in all_required_cells if c not in old_cells)

    # Existing cells: preserve v064 source rows and acquire only the extra margin
    # around each COMPLETE leaf. This is valid even for MAXREC-subdivided bases.
    if corrected_margin>OLD_MARGIN_ARCSEC:
        for ira,idec in existing_required:
            for leaf in complete_leaves(ira,idec):
                nra,ndec,nrad=query_geom(leaf["bounds"],corrected_margin)
                # Center must be identical; if not, refuse rather than silently create a strange annulus.
                if angsep_deg(nra,ndec,leaf["old_ra"],leaf["old_dec"])>1e-8:
                    raise RuntimeError(f"REFUSING: leaf center changed for {leaf['key']}")
                if nrad<=leaf["old_radius_deg"]+1e-12:
                    continue
                qidx+=1
                supplemental.append({
                    "supplemental_query_index":qidx,
                    "mode":"MARGIN_ANNULUS_EXISTING_LEAF",
                    "base_cell_ira":ira,"base_cell_idec":idec,
                    "leaf_key":leaf["key"],"leaf_depth":leaf["depth"],"leaf_path":leaf["path"],
                    "query_ra_deg":nra,"query_dec_deg":ndec,
                    "inner_radius_deg":leaf["old_radius_deg"],
                    "outer_radius_deg":nrad,
                    "corrected_margin_arcsec":corrected_margin,
                    "maxrec":MAXREC,
                    "if_maxrec_hit":"OPERATIONAL_BLOCKER_DO_NOT_INTERPRET",
                })

    # New candidate-domain cells: full query with corrected margin.
    for ira,idec in new_required:
        ra,dec,rad=query_geom(bounds_for_base(ira,idec),corrected_margin)
        qidx+=1
        supplemental.append({
            "supplemental_query_index":qidx,
            "mode":"FULL_NEW_BASE_CELL",
            "base_cell_ira":ira,"base_cell_idec":idec,
            "leaf_key":"","leaf_depth":0,"leaf_path":"root",
            "query_ra_deg":ra,"query_dec_deg":dec,
            "inner_radius_deg":"",
            "outer_radius_deg":rad,
            "corrected_margin_arcsec":corrected_margin,
            "maxrec":MAXREC,
            "if_maxrec_hit":f"RECURSIVELY_QUARTER_TO_{MIN_CELL_DEG}_DEG_TRANSPORT_ONLY",
        })

    # Corrective prospective contract. This does not replace v001; it documents the
    # pre-registration transport-completeness correction discovered from geometry alone.
    freeze_obj={
        "contract_id":"wide_census_gaia_reference_acquisition_contract_v002",
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "supersedes_transport_coverage_only":"wide_census_gaia_reference_acquisition_contract_v001",
        "v001_sha256":EXPECTED_FREEZE_V001_SHA,
        "reason_for_correction":[
            "v001 occupied ordinary Gaia cells were generated from <=10 arcsec raw-match midpoints, but the frozen reference construction may use detector/Gaia references out to 30 arcmin from every target; sparse target regions therefore need candidate-domain coverage beyond the raw-midpoint cells.",
            "The ordinary J2016 margin must cover the full sub-HPM-threshold displacement from the earliest registration epoch plus the independently frozen 15 arcsec candidate-to-Gaia acquisition radius."
        ],
        "outcome_independence":{
            "gaia_source_rows_read_by_v065":0,
            "registration_runs_before_freeze":0,
            "candidate_dispositions_before_freeze":0,
            "plan_inputs":"frozen detector candidate coordinates, raw-match coordinates, pair epochs, v064 query/cache metadata only"
        },
        "science_parameters_unchanged":{
            "reference_windows_arcmin":[5.0,10.0,20.0,30.0],
            "minimum_common_same_gaia_references":5,
            "reference_acquisition_arcsec":REFERENCE_ACQUISITION_ARCSEC,
            "science_exclusion_arcsec":30.0,
            "primary_fit":"translation-only median; no clipping; no higher-order fit",
            "sparse_minimum_references_per_archive":3,
            "sparse_confidence":"diagnostic_only",
            "hpm_split_masyr":HPM_SPLIT_MASYR,
        },
        "corrected_transport_domain":{
            "reference_candidate_domain":"all frozen detector candidates within 30 arcmin + 15 arcsec of at least one <=10 arcsec raw-match midpoint in that pair",
            "base_cell_deg":BASE_CELL_DEG,
            "gaia_dr3_reference_epoch_jyear":2016.0,
            "worst_epoch_delta_years":max_dt,
            "ordinary_margin_formula":"ceil_up_0.1arcsec(max_epoch_delta_years * 1700masyr / 1000 + 15arcsec)",
            "ordinary_margin_arcsec":corrected_margin,
            "hpm_margin_arcsec":corrected_hpm_margin,
            "existing_v064_complete_leaf_reuse":"retain all v064 source rows; query only thin outer annulus from old leaf radius to corrected leaf radius",
            "new_candidate_cells":"query full corrected base-cell circle; recursively quarter on MAXREC exactly as transport-only recovery",
            "hpm_corrective_query":"one pair-level pm>=1700mas/yr cone enclosing all eligible detector reference candidates plus 915 arcsec; deduplicate source_id downstream",
        },
        "interpretation_boundary":"This is a transport completeness repair before any astrometric registration outcome. It cannot promote, reject, or rank a raw candidate."
    }

    if FREEZE_V002.is_file():
        old=json.loads(FREEZE_V002.read_text(encoding="utf-8"))
        # Ignore timestamp for rerun compatibility but require scientific/transport content.
        a=dict(old);b=dict(freeze_obj)
        a.pop("created_at_utc",None);b.pop("created_at_utc",None)
        if a!=b:
            raise RuntimeError("REFUSING: incompatible v002 corrective freeze already exists")
    else:
        write_json(FREEZE_V002,freeze_obj)

    write_csv(PAIR_SUM,pair_summary,[
        "pair_index","canonical_pair","raw_targets","reference_domain_detector_candidates",
        "required_candidate_cells","cells_already_present_v064","new_full_cells_required",
        "registration_epoch_utc","delta_from_gaia2016_years"
    ])
    write_csv(PAIR_CELLS,pair_cell_rows,[
        "pair_index","canonical_pair","endpoint_a","endpoint_b","cell_ira","cell_idec",
        "already_acquired_v064"
    ])
    write_csv(SUPP,supplemental,[
        "supplemental_query_index","mode","base_cell_ira","base_cell_idec",
        "leaf_key","leaf_depth","leaf_path","query_ra_deg","query_dec_deg",
        "inner_radius_deg","outer_radius_deg","corrected_margin_arcsec","maxrec","if_maxrec_hit"
    ])
    write_csv(HPM_OUT,pair_hpm,[
        "pair_index","canonical_pair","query_ra_deg","query_dec_deg","query_radius_deg",
        "pm_min_masyr","historical_reference_window_arcmin","candidate_association_arcsec",
        "j2016_hpm_transport_margin_arcsec","registration_epoch_utc"
    ])

    ann=sum(r["mode"]=="MARGIN_ANNULUS_EXISTING_LEAF" for r in supplemental)
    full=sum(r["mode"]=="FULL_NEW_BASE_CELL" for r in supplemental)
    rep={
        "status":"COMPLETE",
        "analysis_kind":"wide_census_gaia_reference_domain_coverage_audit_v065",
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),
        "guards":{
            "network_access":False,"gaia_source_rows_read":0,"science_pixels_read":False,
            "transient_detector_rerun":False,"astrometric_registration_run":False,
            "candidate_state_mutation":False,
        },
        "input_sha256":{
            "v001_freeze":sha(FREEZE_V001),"v063":sha(V063),"v064":sha(V064),
            "pair_plan":sha(PAIR_PLAN),"candidate_coordinates":sha(CAND),"raw_matches":sha(RAW),
            "global_query_plan_v063a":sha(GLOBAL_PLAN),
        },
        "verified":{"pairs":EXPECTED_PAIRS,"raw_matches":nraw,"candidate_rows":nc},
        "coverage_correction":{
            "old_ordinary_margin_arcsec":OLD_MARGIN_ARCSEC,
            "corrected_ordinary_margin_arcsec":corrected_margin,
            "worst_epoch_delta_years":max_dt,
            "reference_candidate_domain_radius_arcmin":candidate_search_arcmin,
            "global_required_candidate_cells":len(all_required_cells),
            "global_required_cells_already_acquired_v064":len(existing_required),
            "global_new_full_cells_required":len(new_required),
            "supplemental_existing_leaf_annulus_queries":ann,
            "supplemental_new_full_base_queries":full,
            "total_supplemental_ordinary_queries_before_any_maxrec_subdivision":len(supplemental),
            "corrected_pair_hpm_queries":len(pair_hpm),
        },
        "freeze_v002":{"path":str(FREEZE_V002.relative_to(ROOT)).replace("\\","/"),"sha256":sha(FREEZE_V002)},
        "interpretation_boundary":"No Gaia source row or registration outcome was inspected; this stage only repairs acquisition completeness.",
        "next_stage":"Execute the checkpointed v066 supplemental Gaia acquisition, then begin pair-wise offline deduplication, epoch propagation and frozen primary/sparse registration."
    }
    write_json(REPORT,rep)

    print("\n"+"="*136)
    print("GAIA REFERENCE-DOMAIN COVERAGE AUDIT COMPLETE")
    print("="*136)
    print(f"Global candidate-domain cells required:      {len(all_required_cells):,}")
    print(f"Already represented in v064:                {len(existing_required):,}")
    print(f"New full base cells required:                {len(new_required):,}")
    print(f"Existing-leaf thin-margin annulus queries:   {ann:,}")
    print(f"Total supplemental ordinary query entries:  {len(supplemental):,}")
    print(f"Corrected HPM pair queries:                  {len(pair_hpm)}")
    print(f"Corrected ordinary margin:                   {corrected_margin:.1f}\" (old {OLD_MARGIN_ARCSEC:.1f}\")")
    print("Gaia source rows read:                       0")
    print("Astrometric registrations run:               0")
    print("Candidate dispositions:                      NONE")
    print("Corrective freeze:",FREEZE_V002)
    print("Corrective freeze SHA256:",sha(FREEZE_V002))
    print("STAGE STATUS: PASS")

if __name__=="__main__":
    main()
