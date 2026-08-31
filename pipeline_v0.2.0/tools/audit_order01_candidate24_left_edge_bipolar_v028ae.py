#!/usr/bin/env python3
"""
ORDER 01 — corrected candidate #24 left-edge bipolar/native-cluster audit v028ae

Prerequisite
------------
v028ad should leave #24 as the sole active unresolved two-observatory pair.

Correction
----------
v028ac's #24 science nearest-positive attribution was invalid because it
identified the science row by candidate_index alone across the whole plate.
candidate_index is tile-local, so (tile_id, candidate_index) must be used.

The v028ac raw edge-control population was also too sparse because the control
rule rejected any nominal blank point within 10 px of ~366k native detections.

v028ae therefore performs a detector-native, tile-aware test.

For candidate #24:
  * resolve the exact native row using (tile_id, candidate_index);
  * find the nearest positive-polarity native detection using global geometry;
  * construct three independent negative-detection control populations:
      A. same LEFT physical edge, edge distance within +/-40 px;
      B. A plus SNR within +/-1.0 of #24;
      C. B plus y within +/-2500 px of #24;
  * exclude all six historical science candidates from every control pool;
  * for each control, measure:
      - nearest positive-polarity native distance;
      - number of other negative detections within 15 px;
  * compare #24's pair distance and local negative clustering empirically.

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No candidate state mutation.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT=Path.cwd()
BASE=ROOT/"results"/"order01_native_full_v028"
WORK=ROOT/"work"/"order01_native_full_v028"

V028AD=BASE/"order01_candidate30_disposition_freeze_v028ad.json"
V028AB=BASE/"order01_candidate_disposition_freeze_v028ab.json"
V028Y=BASE/"order01_poss_science_centered_counterpart_adjudication_v028y.json"
STRICT=BASE/"order01_strict_match_triage_v028.csv"
POSS=BASE/"order01_poss_native_candidates.csv"
TILES=WORK/"poss_tiles"

OUT_JSON=BASE/"order01_candidate24_left_edge_bipolar_audit_v028ae.json"
OUT_CSV=BASE/"order01_candidate24_left_edge_bipolar_audit_v028ae.csv"
OUT_CTRL=BASE/"order01_candidate24_left_edge_bipolar_controls_v028ae.csv"
OUT_MD=BASE/"ORDER01_CANDIDATE24_LEFT_EDGE_BIPOLAR_AUDIT_V028AE.md"

HISTORICAL=[10,24,25,26,29,30]
ACTIVE=[24]
EDGE_TOL=40.0
SNR_TOL=1.0
LOCAL_Y_HALF=2500.0
NEG_CLUSTER_RADIUS=15.0
PAIR_THRESHOLDS=[4.0,4.5,6.0,8.0,10.0]


def read_csv(p):
    with p.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(p,rows,fields):
    tmp=p.with_suffix(p.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
    tmp.replace(p)


def write_json(p,obj):
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    tmp.replace(p)


def f(v,default=None):
    try:
        if v is None or str(v).strip()=="":return default
        x=float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:return default


def i(v,default=None):
    try:
        if v is None or str(v).strip()=="":return default
        return int(float(str(v).strip()))
    except Exception:return default


def pick(row,*names,default=None):
    norm={str(k).lower().replace("_",""):k for k in row}
    for name in names:
        q=str(name).lower().replace("_","")
        if q in norm:return row[norm[q]]
    return default


def plate_bounds():
    cores=[]
    for jp in TILES.glob("*.json"):
        try:o=json.loads(jp.read_text(encoding="utf-8"))
        except Exception:continue
        if o.get("complete") is not True:continue
        c=o.get("core")
        if isinstance(c,list) and len(c)==4:
            cores.append(tuple(map(int,c)))
    if not cores:raise RuntimeError("no completed tile cores")
    return (
        min(c[0] for c in cores),max(c[1] for c in cores),
        min(c[2] for c in cores),max(c[3] for c in cores),
    )


def nearest_index(tree,rows,x,y,exclude_key=None):
    k=min(16,len(rows))
    ds,inds=tree.query([x,y],k=k)
    for d,j in zip(np.atleast_1d(ds),np.atleast_1d(inds)):
        r=rows[int(j)]
        key=(str(r.get("tile_id","")),i(r.get("candidate_index")))
        if exclude_key is not None and key==exclude_key:continue
        return float(d),r
    return None


def empirical_lower(vals,x):
    a=np.asarray(vals,float)
    return float((1+np.count_nonzero(a<=x))/(len(a)+1)) if len(a) else None


def empirical_upper(vals,x):
    a=np.asarray(vals,float)
    return float((1+np.count_nonzero(a>=x))/(len(a)+1)) if len(a) else None


def summarize(rows,science_pair,science_cluster):
    d=[r["nearest_positive_distance_px"] for r in rows]
    c=[r["other_negative_within15px"] for r in rows]
    out={
        "count":len(rows),
        "pair_distance_median_px":None if not d else float(np.median(d)),
        "pair_distance_p05_px":None if not d else float(np.quantile(d,.05)),
        "pair_distance_p95_px":None if not d else float(np.quantile(d,.95)),
        "science_pair_distance_lower_tail":empirical_lower(d,science_pair),
        "cluster_median":None if not c else float(np.median(c)),
        "cluster_p95":None if not c else float(np.quantile(c,.95)),
        "science_cluster_upper_tail":empirical_upper(c,science_cluster),
    }
    for t in PAIR_THRESHOLDS:
        out[f"positive_partner_within_{str(t).replace('.','p')}px_count"]=sum(x<=t for x in d)
        out[f"positive_partner_within_{str(t).replace('.','p')}px_fraction"]=(
            None if not d else sum(x<=t for x in d)/len(d)
        )
    return out


def main():
    print("="*128)
    print("ORDER 01 — CORRECTED CANDIDATE #24 LEFT-EDGE BIPOLAR/NATIVE-CLUSTER AUDIT v028ae")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028AD,V028AB,V028Y,STRICT,POSS):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    ad=json.loads(V028AD.read_text(encoding="utf-8"))
    ab=json.loads(V028AB.read_text(encoding="utf-8"))
    yy=json.loads(V028Y.read_text(encoding="utf-8"))
    if ad.get("new_active_unresolved_two_observatory_set")!=ACTIVE:
        raise RuntimeError("v028ad active-set guard mismatch")
    if yy.get("frozen_active_ranks")!=HISTORICAL:
        raise RuntimeError("v028y frozen-rank guard mismatch")

    strict_rows=read_csv(STRICT);native=read_csv(POSS)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in HISTORICAL}
    if sorted(strict)!=HISTORICAL:raise RuntimeError("strict guard mismatch")

    # Historical science keys, tile-aware.
    sci_keys=set()
    sci_rows={}
    for rank in HISTORICAL:
        tile=str(pick(strict[rank],"poss_tile_id"))
        idx=i(pick(strict[rank],"poss_candidate_index","poss_index","poss_native_candidate_index"))
        q=[r for r in native if str(r.get("tile_id",""))==tile and i(r.get("candidate_index"))==idx]
        if len(q)!=1:
            # sky-coordinate fallback is unnecessary here; fail rather than silently mis-associate.
            raise RuntimeError(f"#{rank}: expected one tile-aware native science row, found {len(q)}")
        sci_rows[rank]=q[0]
        sci_keys.add((tile,idx))

    s=sci_rows[24]
    stid=str(s["tile_id"]);sidx=i(s["candidate_index"])
    sx=f(s["global_x"]);sy=f(s["global_y"]);ssnr=f(s["snr"]);spol=i(s["polarity"])
    if spol!=-1:raise RuntimeError("#24 frozen native polarity is not -1")

    xmin,xmax,ymin,ymax=plate_bounds()
    sedge=sx-xmin
    if sedge<0 or sedge>200:
        raise RuntimeError(f"#24 not near expected LEFT edge: x-edge={sedge}")

    pos=[r for r in native if i(r.get("polarity"))==1]
    neg=[r for r in native if i(r.get("polarity"))==-1]
    ppts=np.asarray([(f(r["global_x"]),f(r["global_y"])) for r in pos],float)
    npts=np.asarray([(f(r["global_x"]),f(r["global_y"])) for r in neg],float)
    ptree=cKDTree(ppts);ntree=cKDTree(npts)

    q=nearest_index(ptree,pos,sx,sy)
    if q is None:raise RuntimeError("no positive native detections")
    spair,spartner=q
    spartner_key=(str(spartner["tile_id"]),i(spartner["candidate_index"]))

    # Count other negative detections within 15 px, excluding science itself.
    neigh=ntree.query_ball_point([sx,sy],NEG_CLUSTER_RADIUS)
    science_cluster=sum(
        1 for j in neigh
        if (str(neg[j]["tile_id"]),i(neg[j]["candidate_index"]))!=(stid,sidx)
    )

    # Build controls from unique native negative rows; exclude all science keys.
    controls=[]
    for r in neg:
        key=(str(r.get("tile_id","")),i(r.get("candidate_index")))
        if key in sci_keys:continue
        x=f(r.get("global_x"));y=f(r.get("global_y"));snr=f(r.get("snr"))
        if None in (x,y,snr):continue
        edge=x-xmin
        if abs(edge-sedge)>EDGE_TOL:continue

        qp=nearest_index(ptree,pos,x,y)
        if qp is None:continue
        pd,pr=qp

        ids=ntree.query_ball_point([x,y],NEG_CLUSTER_RADIUS)
        cluster=sum(
            1 for j in ids
            if (str(neg[j]["tile_id"]),i(neg[j]["candidate_index"]))!=key
        )

        controls.append({
            "tile_id":key[0],
            "candidate_index":key[1],
            "global_x":x,"global_y":y,
            "left_edge_distance_px":edge,
            "snr":snr,
            "nearest_positive_distance_px":pd,
            "nearest_positive_tile_id":str(pr.get("tile_id","")),
            "nearest_positive_candidate_index":i(pr.get("candidate_index")),
            "nearest_positive_snr":f(pr.get("snr")),
            "other_negative_within15px":cluster,
            "in_snr_matched_pool":abs(snr-ssnr)<=SNR_TOL,
            "in_local_y_pool":abs(snr-ssnr)<=SNR_TOL and abs(y-sy)<=LOCAL_Y_HALF,
        })

    poolA=controls
    poolB=[r for r in controls if r["in_snr_matched_pool"]]
    poolC=[r for r in controls if r["in_local_y_pool"]]
    if len(poolA)<20:
        raise RuntimeError(f"too few same-edge controls: {len(poolA)}")

    sums={
        "same_edge":summarize(poolA,spair,science_cluster),
        "same_edge_snr_matched":summarize(poolB,spair,science_cluster),
        "same_edge_snr_and_local_y":summarize(poolC,spair,science_cluster),
    }

    print("Correct tile-aware #24 science geometry:")
    print(f"  science key={stid}::{sidx}")
    print(f"  polarity={spol:+d} SNR={ssnr:.3f}")
    print(f"  LEFT edge distance={sedge:.1f}px")
    print(
        f"  nearest positive native={spair:.3f}px "
        f"key={spartner_key[0]}::{spartner_key[1]} "
        f"SNR={f(spartner.get('snr')):.3f}"
    )
    print(f"  other negative detections within 15px={science_cluster}\n")

    for name,pool in (("same_edge",poolA),("same_edge_snr_matched",poolB),
                      ("same_edge_snr_and_local_y",poolC)):
        su=sums[name]
        print(
            f"{name}: N={su['count']} pair median={su['pair_distance_median_px']:.2f}px "
            f"<=4px={su['positive_partner_within_4p0px_fraction']} "
            f"<=6px={su['positive_partner_within_6p0px_fraction']} "
            f"sciencePairLowerP={su['science_pair_distance_lower_tail']} "
            f"clusterMed={su['cluster_median']} clusterP95={su['cluster_p95']} "
            f"scienceClusterUpperP={su['science_cluster_upper_tail']}"
        )

    # Conservative adjudication:
    # Require that the 4-px opposite-polarity pairing is demonstrably recurrent
    # in BOTH the SNR-matched and local-y subsets. Local clustering can support
    # but is not required.
    recurrentB=(
        len(poolB)>=20 and
        sums["same_edge_snr_matched"]["positive_partner_within_4p5px_count"]>=5
    )
    recurrentC=(
        len(poolC)>=10 and
        sums["same_edge_snr_and_local_y"]["positive_partner_within_4p5px_count"]>=3
    )

    if spair<=4.5 and recurrentB and recurrentC:
        adjudication="LEFT_EDGE_BIPOLAR_NATIVE_DETECTOR_MECHANISM_SUPPORTED"
    elif spair<=4.5 and recurrentB:
        adjudication="BIPOLAR_NATIVE_DETECTOR_MECHANISM_SUPPORTED;_LOCAL_EDGE_CONFIRMATION_LIMITED"
    elif spair<=4.5:
        adjudication="ADJACENT_OPPOSITE_POLARITY_PAIR_CONFIRMED;_POPULATION_SUPPORT_INSUFFICIENT"
    else:
        adjudication="BIPOLAR_EDGE_MECHANISM_NOT_ESTABLISHED"

    print(f"\nADJUDICATION: {adjudication}")

    summary={
        "stage":"ORDER01_CANDIDATE24_LEFT_EDGE_BIPOLAR_AUDIT_V028AE",
        "active_unresolved_input":[24],
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "tile_aware_science_identity":True,
            "historical_science_candidates_excluded_from_controls":True,
        },
        "science":{
            "strict_rank":24,
            "tile_id":stid,
            "candidate_index":sidx,
            "polarity":spol,
            "snr":ssnr,
            "global_x":sx,"global_y":sy,
            "left_edge_distance_px":sedge,
            "nearest_positive_distance_px":spair,
            "nearest_positive_tile_id":spartner_key[0],
            "nearest_positive_candidate_index":spartner_key[1],
            "nearest_positive_snr":f(spartner.get("snr")),
            "other_negative_within15px":science_cluster,
        },
        "control_summaries":sums,
        "adjudication":adjudication,
        "interpretive_boundary":(
            "This stage corrects v028ac by using tile-aware science identity and "
            "tests #24 against other frozen negative native detections at matching "
            "LEFT-edge distance, SNR, and local y. A recurrent adjacent opposite-"
            "polarity pairing supports a detector/plate-structure mechanism but "
            "does not by itself identify the physical emulsion or scanning defect. "
            "No candidate state is changed."
        )
    }
    write_json(OUT_JSON,summary)
    write_csv(OUT_CTRL,controls,sorted({k for r in controls for k in r}))

    flat={
        "strict_rank":24,
        "adjudication":adjudication,
        **summary["science"],
        "same_edge_count":sums["same_edge"]["count"],
        "same_edge_snr_count":sums["same_edge_snr_matched"]["count"],
        "same_edge_snr_local_y_count":sums["same_edge_snr_and_local_y"]["count"],
        "same_edge_snr_fraction_pos_within4p5":
            sums["same_edge_snr_matched"]["positive_partner_within_4p5px_fraction"],
        "same_edge_snr_local_y_fraction_pos_within4p5":
            sums["same_edge_snr_and_local_y"]["positive_partner_within_4p5px_fraction"],
        "same_edge_snr_science_pair_lower_tail":
            sums["same_edge_snr_matched"]["science_pair_distance_lower_tail"],
        "same_edge_snr_science_cluster_upper_tail":
            sums["same_edge_snr_matched"]["science_cluster_upper_tail"],
    }
    write_csv(OUT_CSV,[flat],list(flat))

    md=[
        "# ORDER 01 — Corrected Candidate #24 Left-Edge Bipolar/Native-Cluster Audit v028ae","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- Science identity is `(tile_id, candidate_index)`, correcting v028ac.",
        "- All six historical science candidates are excluded from controls.",
        "- No candidate state was changed.","",
        "## #24 science geometry","",
        f"- Native key: `{stid}::{sidx}`.",
        f"- Polarity/SNR: **{spol:+d} / {ssnr:.3f}**.",
        f"- LEFT-edge distance: **{sedge:.1f} px**.",
        f"- Nearest positive-polarity native detection: **{spair:.3f} px**, "
        f"`{spartner_key[0]}::{spartner_key[1]}`, SNR **{f(spartner.get('snr')):.3f}**.",
        f"- Other negative detections within 15 px: **{science_cluster}**.","",
        "## Control populations",""
    ]
    for name in ("same_edge","same_edge_snr_matched","same_edge_snr_and_local_y"):
        su=sums[name]
        md += [
            f"### {name}",
            f"- N: **{su['count']}**.",
            f"- Nearest-positive distance median: **{su['pair_distance_median_px']:.3f} px**.",
            f"- Fraction with positive partner <=4.5 px: "
            f"**{su['positive_partner_within_4p5px_fraction']}**.",
            f"- Fraction with positive partner <=6 px: "
            f"**{su['positive_partner_within_6p0px_fraction']}**.",
            f"- #24 pair-distance lower-tail diagnostic: **{su['science_pair_distance_lower_tail']}**.",
            f"- #24 local-negative-cluster upper-tail diagnostic: **{su['science_cluster_upper_tail']}**.",
            ""
        ]
    md += ["## Adjudication","",f"`{adjudication}`","",
           "## Interpretation boundary","",summary["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_CTRL}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
