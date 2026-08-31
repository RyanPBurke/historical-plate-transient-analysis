from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math
import warnings
from datetime import timedelta

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.time import Time
from astropy.utils import iers
from scipy.optimize import minimize_scalar
from scipy.spatial import cKDTree

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

PREV_WORKER = ROOT / "tools" / "run_order61_branch_c_parallax_preflight_v028.py"
PREV_REPORT = BASE / "order61_branch_c_parallax_preflight_v028.json"
PREV_MATCHES = BASE / "order61_branch_c_parallax_nearest_matches_v028.csv"
STRICT = BASE / "order61_strict_match_triage.csv"
DASCH_CAND = BASE / "order61_dasch_native_candidates.csv"

OUT_REPORT = BASE / "order61_branch_c_refined_controls_v028.json"
OUT_HITS = BASE / "order61_branch_c_refined_unique_hits_v028.csv"
OUT_CTRL = BASE / "order61_branch_c_shifted_locus_controls_v028.csv"

ACTIVE_RANKS = [11, 14, 20]
NEAR_EARTH_BIN_NAMES = {
    "0.5-2k_LEO_like",
    "2-30k_MEO_like",
    "30-50k_GEO_focus",
    "50-100k",
    "100-500k_high_lunar",
}
DISCOVERY_HIT_ARCSEC = 10.0
STRICT_ARCSEC = 3.0

CONTROL_RADII_DEG = [0.25, 0.50, 1.00, 2.00]
CONTROL_POSITION_ANGLES_DEG = [15.0*i for i in range(24)]
CONTROL_COUNT_PER_RANK = len(CONTROL_RADII_DEG) * len(CONTROL_POSITION_ANGLES_DEG)

iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"

HIT_FIELDS = [
    "strict_rank","coarse_range_bin","dasch_tile_id","dasch_candidate_index",
    "dasch_ra_deg","dasch_dec_deg","dasch_snr","dasch_polarity",
    "coarse_nearest_sep_arcsec","coarse_event_time_utc","coarse_palomar_range_km",
    "refined_best_time_utc","refined_best_time_offset_s",
    "refined_palomar_range_km","refined_dona_ana_range_km",
    "refined_ray_gap_km","refined_predicted_b_sep_arcsec",
    "refined_both_rays_forward","refined_range_within_0p5_to_500k",
    "is_existing_strict_counterpart",
]
CTRL_FIELDS = [
    "strict_rank","control_index","shift_radius_deg","shift_pa_deg",
    "shifted_ra_deg","shifted_dec_deg","best_near_earth_sep_arcsec",
    "best_range_bin","best_event_time_utc","best_palomar_range_km",
    "best_dasch_tile_id","best_dasch_candidate_index","best_dasch_snr",
    "best_dasch_polarity","within_10arcsec","within_3arcsec",
]

def read_csv(path):
    with path.open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
    tmp.replace(path)

def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    tmp.replace(path)

def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def unit_from_coord(c):
    return np.array([
        math.cos(c.dec.radian)*math.cos(c.ra.radian),
        math.cos(c.dec.radian)*math.sin(c.ra.radian),
        math.sin(c.dec.radian),
    ],float)

def plain_icrs(ra,dec):
    return SkyCoord(float(ra)*u.deg,float(dec)*u.deg,frame="icrs")

def build_times(prev,m):
    start=m.parse_iso_utc(prev["fixed_grid"]["event_time_interval"][0])
    end=m.parse_iso_utc(prev["fixed_grid"]["event_time_interval"][1])
    step=int(prev["fixed_grid"]["event_time_step_seconds"])
    total=(end-start).total_seconds()
    n=int(math.floor(total/step))
    dts=[start+timedelta(seconds=i*step) for i in range(n+1)]
    if dts[-1]<end:dts.append(end)
    return start,end,step,dts

def observer_at_seconds(location,start,seconds):
    dt=start+timedelta(seconds=float(seconds))
    t=Time(dt,scale="utc")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g=location.get_gcrs(t)
    return np.array([
        g.cartesian.x.to_value(u.km),
        g.cartesian.y.to_value(u.km),
        g.cartesian.z.to_value(u.km),
    ],float),dt

def predicted_b_sep_for_pair(m,pal_loc,da_loc,start,seconds,uA,uB):
    rA,dt=observer_at_seconds(pal_loc,start,seconds)
    rB,_=observer_at_seconds(da_loc,start,seconds)
    q=m.line_closest_approach(rA,uA,rB,uB)
    if q is None:return float("inf"),None
    sA,sB,gap=q
    obj=rA+sA*uA
    vd=obj-rB
    if np.linalg.norm(vd)<=0:return float("inf"),None
    pred=vd/np.linalg.norm(vd)
    sep=m.angle_arcsec(pred,uB)
    return sep,(dt,sA,sB,gap)

def refine_pair(m,pal_loc,da_loc,start,end,uA,uB):
    total=(end-start).total_seconds()
    xs=np.arange(0.0,total+0.001,5.0)
    vals=[]
    for x in xs:
        v,_=predicted_b_sep_for_pair(m,pal_loc,da_loc,start,float(x),uA,uB)
        vals.append(v)
    vals=np.asarray(vals,float)
    i=int(np.argmin(vals));x0=float(xs[i])
    lo=max(0.0,x0-10.0);hi=min(total,x0+10.0)
    def objective(x):
        v,_=predicted_b_sep_for_pair(m,pal_loc,da_loc,start,float(x),uA,uB)
        return v
    opt=minimize_scalar(objective,bounds=(lo,hi),method="bounded",options={"xatol":1e-4,"maxiter":200})
    bx=float(opt.x) if opt.success else x0
    sep,q=predicted_b_sep_for_pair(m,pal_loc,da_loc,start,bx,uA,uB)
    if q is None:raise RuntimeError("refined triangulation failed")
    dt,sA,sB,gap=q
    return {
        "time_utc":dt.isoformat(),
        "time_offset_s":bx,
        "palomar_range_km":float(sA),
        "dona_ana_range_km":float(sB),
        "ray_gap_km":float(gap),
        "predicted_b_sep_arcsec":float(sep),
        "both_forward":bool(sA>0 and sB>0),
        "near_earth_range":bool(sA>=500 and sA<=500000 and sB>=0),
    }

def shifted_coord(base,radius_deg,pa_deg):
    return base.directional_offset_by(float(pa_deg)*u.deg,float(radius_deg)*u.deg).icrs

def bulk_discovery_minimum(m,uA,rP,rD,dts,tree,dcand,near_bins):
    best=None
    for bin_name,lo,hi,n in near_bins:
        ranges=m.make_range_grid(lo,hi,n)
        for ti,dt in enumerate(dts):
            obj=rP[ti][None,:]+ranges[:,None]*uA[None,:]
            vecD=obj-rD[ti][None,:]
            vecD/=np.linalg.norm(vecD,axis=1)[:,None]
            chord,idx=tree.query(vecD,k=1)
            chord=np.clip(np.asarray(chord,float),0,2)
            sep=np.degrees(2*np.arcsin(chord/2))*3600
            ri=int(np.argmin(sep));s=float(sep[ri])
            if best is None or s<best["sep"]:
                cr=dcand[int(idx[ri])]
                best={
                    "sep":s,"range_bin":bin_name,"time":dt.isoformat(),
                    "range_km":float(ranges[ri]),"tile_id":cr["tile_id"],
                    "candidate_index":int(cr["candidate_index"]),
                    "snr":float(cr["snr"]),"polarity":int(cr["polarity"]),
                }
    if best is None:raise RuntimeError("shift control produced no result")
    return best

def main():
    print("="*112)
    print("ORDER 61 — BRANCH C UNIQUE-HIT REFINEMENT + SHIFTED-LOCUS CONTROLS v028")
    print("="*112)
    print("Refine every unique coarse <=10\" near-Earth locus hit; repeat full 0.5-500k km discovery statistic on 96 shifted sightlines/rank.")
    print("No detector, no new image pixels, no threshold change.")
    print()

    for p in (PREV_WORKER,PREV_REPORT,PREV_MATCHES,STRICT,DASCH_CAND):
        if not p.is_file():raise RuntimeError(f"Missing input: {p}")

    m=load_module(PREV_WORKER,"branch_c_preflight_v028")
    prev=json.loads(PREV_REPORT.read_text(encoding="utf-8"))
    guards={
        "previous_complete":prev.get("status")=="COMPLETE",
        "previous_kind":prev.get("analysis_kind")=="order61_branch_c_topocentric_parallax_locus_preflight_v028",
        "previous_no_detector":prev.get("detector_rerun") is False,
        "previous_no_pixels":prev.get("science_pixels_read") is False,
        "previous_no_promotion":prev.get("candidate_promoted") is False,
        "dona_ana_verified_geometry_present":"Whipple 1954" in prev.get("site_geometry",{}).get("dona_ana",{}).get("source",""),
    }
    if not all(guards.values()):raise RuntimeError("REFUSING: guard failure "+repr(guards))

    strict={int(r["strict_rank"]):r for r in read_csv(STRICT)}
    matches=read_csv(PREV_MATCHES)
    dcand=read_csv(DASCH_CAND)
    if len(dcand)!=4109:raise RuntimeError(f"expected 4109 DASCH detections, got {len(dcand)}")
    cby={(r["tile_id"],int(r["candidate_index"])):r for r in dcand}

    raw_selected=[
        r for r in matches
        if r["range_bin"] in NEAR_EARTH_BIN_NAMES
        and float(r["nearest_dasch_sep_arcsec"])<=DISCOVERY_HIT_ARCSEC
    ]
    dedup={}
    for r in raw_selected:
        key=(int(r["strict_rank"]),r["nearest_dasch_tile_id"],int(r["nearest_dasch_candidate_index"]))
        if key not in dedup or float(r["nearest_dasch_sep_arcsec"])<float(dedup[key]["nearest_dasch_sep_arcsec"]):
            dedup[key]=r
    selected=sorted(dedup.values(),key=lambda r:(int(r["strict_rank"]),float(r["nearest_dasch_sep_arcsec"])))

    print("Completed-stage guards: PASS")
    print(f"Coarse near-Earth <=10\" rows={len(raw_selected)}; unique rank+DASCH hits={len(selected)}")

    start,end,step,dts=build_times(prev,m)
    times=Time(dts,scale="utc")
    pal=prev["site_geometry"]["palomar"];da=prev["site_geometry"]["dona_ana"]
    pal_loc=EarthLocation.from_geodetic(float(pal["lon_deg_east"])*u.deg,float(pal["lat_deg"])*u.deg,float(pal["height_m"])*u.m)
    da_loc=EarthLocation.from_geodetic(float(da["lon_deg_east"])*u.deg,float(da["lat_deg"])*u.deg,float(da["height_m"])*u.m)
    rP=m.observer_xyz_km(pal_loc,times);rD=m.observer_xyz_km(da_loc,times)
    cand_vec=np.stack([m.unit_from_radec(float(r["ra_deg"]),float(r["dec_deg"])) for r in dcand])
    tree=cKDTree(cand_vec)
    near_bins=[tuple(x) for x in m.RANGE_BINS_KM if x[0] in NEAR_EARTH_BIN_NAMES]

    hit_rows=[];per_rank_hits={r:[] for r in ACTIVE_RANKS}
    print();print("UNIQUE HIT REFINEMENT");print("-"*112)
    for q in selected:
        rank=int(q["strict_rank"]);sr=strict[rank]
        ckey=(q["nearest_dasch_tile_id"],int(q["nearest_dasch_candidate_index"]))
        cr=cby[ckey]
        uA=m.unit_from_radec(float(sr["poss_ra_deg"]),float(sr["poss_dec_deg"]))
        uB=m.unit_from_radec(float(cr["ra_deg"]),float(cr["dec_deg"]))
        rr=refine_pair(m,pal_loc,da_loc,start,end,uA,uB)
        out={
            "strict_rank":rank,"coarse_range_bin":q["range_bin"],
            "dasch_tile_id":cr["tile_id"],"dasch_candidate_index":int(cr["candidate_index"]),
            "dasch_ra_deg":float(cr["ra_deg"]),"dasch_dec_deg":float(cr["dec_deg"]),
            "dasch_snr":float(cr["snr"]),"dasch_polarity":int(cr["polarity"]),
            "coarse_nearest_sep_arcsec":float(q["nearest_dasch_sep_arcsec"]),
            "coarse_event_time_utc":q["event_time_utc"],
            "coarse_palomar_range_km":float(q["palomar_range_km"]),
            "refined_best_time_utc":rr["time_utc"],
            "refined_best_time_offset_s":rr["time_offset_s"],
            "refined_palomar_range_km":rr["palomar_range_km"],
            "refined_dona_ana_range_km":rr["dona_ana_range_km"],
            "refined_ray_gap_km":rr["ray_gap_km"],
            "refined_predicted_b_sep_arcsec":rr["predicted_b_sep_arcsec"],
            "refined_both_rays_forward":rr["both_forward"],
            "refined_range_within_0p5_to_500k":rr["near_earth_range"],
            "is_existing_strict_counterpart":(
                cr["tile_id"]==sr["dasch_tile_id"] and int(cr["candidate_index"])==int(sr["dasch_candidate_index"])
            ),
        }
        hit_rows.append(out);per_rank_hits[rank].append(out)
        print(
            f"strict #{rank:02d} DASCH {cr['tile_id']}#{int(cr['candidate_index'])}: "
            f"coarse={out['coarse_nearest_sep_arcsec']:.2f}\" ({out['coarse_range_bin']}, {out['coarse_palomar_range_km']:.0f} km) "
            f"-> refined={out['refined_predicted_b_sep_arcsec']:.4f}\" range={out['refined_palomar_range_km']:.0f} km "
            f"time={out['refined_best_time_utc'][11:19]} gap={out['refined_ray_gap_km']:.3f} km"
        )
    write_csv(OUT_HITS,hit_rows,HIT_FIELDS)

    print();print("SHIFTED-LOCUS LOOK-ELSEWHERE CONTROLS");print("-"*112)
    print(f"Per rank: {CONTROL_COUNT_PER_RANK} controls = 4 radii x 24 position angles.")

    control_rows=[];rank_summary={}
    for rank in ACTIVE_RANKS:
        sr=strict[rank];base=plain_icrs(sr["poss_ra_deg"],sr["poss_dec_deg"])
        observed_best=min(
            float(r["nearest_dasch_sep_arcsec"]) for r in matches
            if int(r["strict_rank"])==rank and r["range_bin"] in NEAR_EARTH_BIN_NAMES
        )
        n_le_obs=n_le_3=n_le_10=0;vals=[];ci=0
        for radius in CONTROL_RADII_DEG:
            for pa in CONTROL_POSITION_ANGLES_DEG:
                ci+=1;sc=shifted_coord(base,radius,pa);uA=unit_from_coord(sc)
                b=bulk_discovery_minimum(m,uA,rP,rD,dts,tree,dcand,near_bins)
                vals.append(float(b["sep"]))
                n_le_obs+=int(b["sep"]<=observed_best)
                n_le_3+=int(b["sep"]<=STRICT_ARCSEC)
                n_le_10+=int(b["sep"]<=DISCOVERY_HIT_ARCSEC)
                control_rows.append({
                    "strict_rank":rank,"control_index":ci,"shift_radius_deg":radius,"shift_pa_deg":pa,
                    "shifted_ra_deg":float(sc.ra.deg),"shifted_dec_deg":float(sc.dec.deg),
                    "best_near_earth_sep_arcsec":b["sep"],"best_range_bin":b["range_bin"],
                    "best_event_time_utc":b["time"],"best_palomar_range_km":b["range_km"],
                    "best_dasch_tile_id":b["tile_id"],"best_dasch_candidate_index":b["candidate_index"],
                    "best_dasch_snr":b["snr"],"best_dasch_polarity":b["polarity"],
                    "within_10arcsec":b["sep"]<=DISCOVERY_HIT_ARCSEC,"within_3arcsec":b["sep"]<=STRICT_ARCSEC,
                })
        arr=np.asarray(vals,float);ep=(1+n_le_obs)/(1+len(arr))
        rank_summary[str(rank)]={
            "observed_coarse_best_near_earth_sep_arcsec":observed_best,
            "control_count":len(arr),"controls_best_sep_min_arcsec":float(np.min(arr)),
            "controls_best_sep_median_arcsec":float(np.median(arr)),
            "controls_best_sep_p10_arcsec":float(np.percentile(arr,10)),
            "controls_best_sep_p90_arcsec":float(np.percentile(arr,90)),
            "controls_at_least_as_close_as_observed":n_le_obs,
            "finite_sample_empirical_p":ep,"controls_within_3arcsec":n_le_3,
            "controls_within_10arcsec":n_le_10,
            "fraction_controls_within_3arcsec":n_le_3/len(arr),
            "fraction_controls_within_10arcsec":n_le_10/len(arr),
            "unique_refined_hits_from_observed_locus":len(per_rank_hits[rank]),
        }
        print(
            f"strict #{rank:02d}: observed coarse min={observed_best:.2f}\" | "
            f"controls min/median={np.min(arr):.2f}/{np.median(arr):.2f}\" | "
            f"<=observed {n_le_obs}/{len(arr)} => empirical p={ep:.4f} | controls <=3\"={n_le_3}, <=10\"={n_le_10}"
        )
    write_csv(OUT_CTRL,control_rows,CTRL_FIELDS)

    report={
        "status":"COMPLETE",
        "analysis_kind":"order61_branch_c_unique_hit_refinement_shifted_controls_v028",
        "guards":guards,
        "selection_contract":{
            "coarse_hit_definition":"near-Earth discovery bin (0.5-500k km) with nearest frozen DASCH detection <=10 arcsec",
            "dedupe":"strict_rank + DASCH tile_id + candidate_index, keep closest coarse row",
            "refinement":"two observed ICRS sightlines; 5-second overlap scan then bounded scalar refinement; range from closest ray-ray geometry",
            "no_new_hit_threshold":True,
        },
        "shifted_control_contract":{
            "purpose":"estimate local geometry/candidate-density look-elsewhere behavior; not an astrophysical false-positive probability",
            "radii_deg":CONTROL_RADII_DEG,
            "position_angles_deg":CONTROL_POSITION_ANGLES_DEG,
            "controls_per_rank":CONTROL_COUNT_PER_RANK,
            "each_control_repeats":"entire original coarse 0.5-500,000 km discovery statistic against all 4109 frozen DASCH detections",
            "observed_statistic":"minimum coarse nearest-DASCH separation over all five near-Earth bins",
            "finite_sample_p":"(1 + controls <= observed)/(1 + Ncontrols)",
            "candidate_polarity_not_used":True,"candidate_snr_not_used":True,"detector_rerun":False,
        },
        "per_rank_control_summary":rank_summary,
        "refined_unique_hits":hit_rows,
        "detector_rerun":False,"science_image_pixels_read":False,
        "candidate_deleted":False,"candidate_promoted":False,
        "next_stage":"Only for locus hits that remain geometrically valid and are uncommon under shifted-locus controls: perform Gaia/PS1/static rejection, matched-peer native morphology, shifted/time-scrambled controls, and solar illumination/Earth-shadow geometry.",
        "outputs":{"refined_hits_csv":str(OUT_HITS),"shifted_controls_csv":str(OUT_CTRL)},
    }
    write_json(OUT_REPORT,report)

    print();print("="*112);print("BRANCH C REFINEMENT + SHIFTED CONTROLS COMPLETE");print("="*112)
    print("Outputs:");print(" ",OUT_REPORT);print(" ",OUT_HITS);print(" ",OUT_CTRL)
    print();print("No detector was rerun.");print("No science image pixel was read.");print("No candidate was deleted or promoted.")

if __name__=="__main__":
    main()
