#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
import csv, hashlib, importlib.util, json, math, os, re, sys

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_whole_population_short_lag_census_contract_v092.json"
)
EXPECTED_CONTRACT_SHA = "97e7fd6270203099a072fe2cf0f089400cbc2045cbd983723cd24ec8f5d8fc17"

V077_DIR = ROOT / "results" / "pair17_applause_independent_plate_opportunity_census_v077a"
OPPS = V077_DIR / "pair17_candidate_plate_opportunities_v077a.csv"
TAP_MANIFEST = V077_DIR / "pair17_tap_query_manifest_v077a.csv"
V077_BANK = V077_DIR / "pair17_v077a_bank_manifest.json"

V078_DIR = ROOT / "results" / "pair17_applause_catalog_recurrence_screen_v078"
NEAREST = V078_DIR / "pair17_catalog_recurrence_plate_nearest_v078.csv"
CAND_SUM = V078_DIR / "pair17_catalog_recurrence_candidate_summary_v078.csv"
V078_BANK = V078_DIR / "pair17_v078a_bank_manifest.json"

V081A_RUNNER = ROOT / "tools" / "run_pair17_temporal_bracketing_census_v081a.py"
EXPECTED_V081A_RUNNER_SHA = "818e9b14fac1ee3d7d1ccf3f422157e832cb83e874a42f3dedd5eab7f608736e"

OUT = ROOT / "results" / "pair17_whole_population_short_lag_census_v092"
OUT_OPP = OUT / "pair17_short_lag_opportunities_v092.csv"
OUT_SUM = OUT / "pair17_short_lag_candidate_summary_v092.csv"
OUT_QUEUE = OUT / "pair17_short_lag_pixel_validation_queue_v092.csv"
OUT_TIMING = OUT / "pair17_timing_recovery_manifest_v092.json"
OUT_JSON = OUT / "pair17_whole_population_short_lag_census_v092.json"

SCI_START = datetime.fromisoformat("1953-12-02T20:46:29+00:00")
SCI_END   = datetime.fromisoformat("1953-12-02T20:51:28+00:00")

TIERS = [
    ("A_LE30MIN", 0.0, 1800.0, True, True),
    ("B_GT30_LE60MIN", 1800.0, 3600.0, False, True),
    ("C_GT60_LE120MIN", 3600.0, 7200.0, False, True),
]

ID_ALIASES = {
    "exposure_id","exposureid","exposure_id_applause","id_exposure",
    "exposure","exposureid_fk"
}
START_ALIASES = {
    "exposure_start","exposure_start_utc","start_utc","start_time","start",
    "date_obs","date-obs","dateobs","obs_start","datetime_start","time_start"
}
END_ALIASES = {
    "exposure_end","exposure_end_utc","end_utc","end_time","end",
    "date_end","date-end","dateend","obs_end","datetime_end","time_end"
}
DUR_ALIASES = {
    "duration_seconds","exposure_duration_seconds","exposure_time_seconds",
    "exptime_seconds","duration_s","exposure_duration_s","exptime_s",
    "exposure_time","exptime","duration"
}


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def rcsv(p):
    with Path(p).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def stream_csv(p):
    f = Path(p).open("r", encoding="utf-8-sig", newline="")
    return f, csv.DictReader(f)


def wcsv(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with p.open("w", encoding="utf-8", newline="") as f:
        if not fields:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def norm(v):
    return str(v or "").strip()


def boolish(v):
    return norm(v).lower() in {"1","true","t","yes","y"}


def fnum(v):
    try:
        x = float(norm(v))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x=fnum(v)
    return None if x is None else int(round(x))


def split_ids(v):
    out=[]
    for s in re.split(r"[;,|]+", norm(v)):
        s=s.strip()
        if not s:
            continue
        try:
            out.append(int(float(s)))
        except Exception:
            pass
    return out


def parse_dt(v):
    s=norm(v)
    if not s:
        return None
    s=s.replace("Z","+00:00")
    # Normalize common space separator.
    try:
        d=datetime.fromisoformat(s)
    except Exception:
        # Trim fractional timezone oddities and retry common forms.
        fmts=[
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]
        d=None
        for fmt in fmts:
            try:
                d=datetime.strptime(s,fmt)
                break
            except Exception:
                pass
        if d is None:
            return None
    if d.tzinfo is None:
        d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def choose_col(fields, aliases):
    exact={str(f).strip().lower():f for f in fields}
    hits=[exact[a] for a in aliases if a in exact]
    if len(hits)==1:
        return hits[0]
    # Prefer names containing exposure and semantic term if exact aliases miss.
    return None


def tier_for(gap):
    for name,lo,hi,lo_inc,hi_inc in TIERS:
        left = gap >= lo if lo_inc else gap > lo
        right = gap <= hi if hi_inc else gap < hi
        if left and right:
            return name
    return ""


def interval_gap(start,end):
    if end < SCI_START:
        return (SCI_START-end).total_seconds(), "PRECEDING"
    if start > SCI_END:
        return (start-SCI_END).total_seconds(), "FOLLOWING"
    return 0.0, "OVERLAPS_SCIENCE_INTERVAL"


def recurrence_bucket(raw_class, sep):
    c=norm(raw_class).upper()
    s=fnum(sep)
    if c:
        if "STRICT" in c or (s is not None and s <= 3.0):
            return "STRICT_RECURRENCE"
        if "DIAGNOSTIC" in c or (s is not None and s <= 5.0):
            return "DIAGNOSTIC_3TO5"
        if "WIDE" in c or (s is not None and s <= 15.0):
            return "WIDE_5TO15"
        return "OTHER_CATALOG_CONTEXT"
    return "NO_CATALOG_SOURCE_WITHIN_ACQUISITION"


def load_v081a_banked_timing():
    """
    v092a operational repair.

    Reuse the exact v081a banked exposure-cache implementation that previously
    recovered 10,182 exposure rows from 153 cryptographically bound v077a raw
    VOTables. This changes only timing provenance discovery; the frozen v092
    science-overlap interval, A/B/C tiers, interval-gap definition, recurrence
    triage rules, and all scientific guards remain unchanged.
    """
    if not V081A_RUNNER.is_file():
        raise RuntimeError(f"Required frozen v081a runner missing: {V081A_RUNNER}")

    actual = sha(V081A_RUNNER)
    if actual != EXPECTED_V081A_RUNNER_SHA:
        raise RuntimeError(
            "v081a timing-recovery runner SHA mismatch:\n"
            f"expected {EXPECTED_V081A_RUNNER_SHA}\nactual   {actual}"
        )

    spec = importlib.util.spec_from_file_location(
        "pair17_v081a_timing_recovery_frozen",
        V081A_RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not import frozen v081a timing-recovery runner")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    required = (
        "load_banked_exposure_cache",
        "intervals_from_banked_cache",
    )
    missing = [name for name in required if not hasattr(mod, name)]
    if missing:
        raise RuntimeError(
            f"Frozen v081a runner missing required timing functions: {missing}"
        )

    exposure_cache, exposure_cache_files = mod.load_banked_exposure_cache()

    if not exposure_cache or not exposure_cache_files:
        raise RuntimeError(
            "Frozen v081a timing recovery returned no exposure cache/files"
        )

    return mod, exposure_cache, exposure_cache_files


def main():
    print("="*120)
    print("PAIR 17 — WHOLE-POPULATION SHORT-LAG CENSUS v092a")
    print("="*120)
    print("Operational repair: reuse exact frozen v081a banked timing recovery")
    print("Scientific contract changed: NO")
    print("Science overlap:",SCI_START.isoformat(),"to",SCI_END.isoformat(),"(299 s)")
    print("Tiers: A <=30 min; B >30-60 min; C >60-120 min")
    print("Gap metric: actual exposure interval gap; midpoint substitution prohibited")
    print("Catalogue absence: triage only, NOT a qualified negative")
    print("Network calls: 0")
    print("FITS reads: 0")
    print("Detector reruns: 0")
    print("Disposition changes: NONE")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v092 contract SHA mismatch")

    for p in (OPPS,TAP_MANIFEST,NEAREST,CAND_SUM,V077_BANK,V078_BANK,V081A_RUNNER):
        if not p.is_file():
            raise RuntimeError(f"Required frozen input missing: {p}")

    print("Input hashes:")
    for p in (OPPS,TAP_MANIFEST,NEAREST,CAND_SUM,V077_BANK,V078_BANK,V081A_RUNNER):
        print(f"  {p.relative_to(ROOT)} = {sha(p)}")

    # Pass 1: collect all exposure ids from eligible independent comparison rows.
    wanted_ids=set()
    eligible_rows=0
    with OPPS.open("r",encoding="utf-8-sig",newline="") as f:
        rdr=csv.DictReader(f)
        for r in rdr:
            if not boolish(r.get("eligible_independent_comparison")):
                continue
            if not boolish(r.get("independent_physical_plate")):
                continue
            eligible_rows+=1
            wanted_ids.update(split_ids(r.get("physical_plate_exposure_ids")))

    print()
    print("Eligible v077a candidate×plate rows:",eligible_rows)
    print("Distinct exposure IDs needing timing:",len(wanted_ids))

    timing_mod, exposure_cache, exposure_cache_files = load_v081a_banked_timing()

    wanted_present = wanted_ids & set(exposure_cache.keys())
    wanted_missing = sorted(wanted_ids - set(exposure_cache.keys()))

    print("Frozen v081a exposure rows recovered:",len(exposure_cache))
    print("Frozen v081a raw VOTables verified:",len(exposure_cache_files))
    print("Wanted exposure IDs present in frozen cache:",len(wanted_present))
    print("Wanted exposure IDs absent from frozen cache:",len(wanted_missing))

    # v078 nearest row per candidate×plate: retain smallest separation if duplicates.
    nearest={}
    with NEAREST.open("r",encoding="utf-8-sig",newline="") as f:
        rdr=csv.DictReader(f)
        for r in rdr:
            key=(norm(r.get("raw_match_row")),inum(r.get("eligible_physical_plate_id")))
            if key[1] is None:
                continue
            sep=fnum(r.get("separation_arcsec"))
            old=nearest.get(key)
            if old is None or (
                sep is not None and
                (fnum(old.get("separation_arcsec")) is None or sep < fnum(old.get("separation_arcsec")))
            ):
                nearest[key]=r

    cand_summary_meta={}
    with CAND_SUM.open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            cand_summary_meta[norm(r.get("raw_match_row"))]=r

    out_rows=[]
    unresolved_candidate_plate_rows=0
    unresolved_reasons=Counter()
    resolved_exposure_ids=set()

    # Pass 2: calculate exact actual interval gaps using the frozen v081a route.
    with OPPS.open("r",encoding="utf-8-sig",newline="") as f:
        rdr=csv.DictReader(f)
        for r in rdr:
            if not boolish(r.get("eligible_independent_comparison")):
                continue
            if not boolish(r.get("independent_physical_plate")):
                continue

            rid=norm(r.get("raw_match_row"))
            pop=norm(r.get("population"))
            plate=inum(r.get("physical_opportunity_plate_id") or r.get("plate_id"))
            eids=split_ids(r.get("physical_plate_exposure_ids"))

            intervals, timing_status = timing_mod.intervals_from_banked_cache(
                r, exposure_cache
            )

            if not intervals:
                unresolved_candidate_plate_rows += 1
                unresolved_reasons[str(timing_status)] += 1
                continue

            if len(intervals) != len(eids):
                unresolved_candidate_plate_rows += 1
                unresolved_reasons[
                    f"INTERVAL_COUNT_MISMATCH_{len(intervals)}_{len(eids)}"
                ] += 1
                continue

            resolved=[]
            for item in intervals:
                idx,start,end,source = item
                if idx < 1 or idx > len(eids):
                    raise RuntimeError(
                        f"v081a interval index out of range: idx={idx} eids={eids}"
                    )
                eid=eids[idx-1]
                gap,relation=interval_gap(start,end)
                resolved.append((
                    eid,
                    {
                        "start":start,
                        "end":end,
                        "source":source,
                        "path":"FROZEN_V081A_BANKED_V077A_EXPOSURE_CACHE",
                    },
                    gap,
                    relation,
                ))
                resolved_exposure_ids.add(eid)

            best=min(resolved,key=lambda x:x[2])
            eid,tr,gap,relation=best
            tier=tier_for(gap)
            if not tier:
                continue

            nr=nearest.get((rid,plate))
            raw_class=norm(nr.get("plate_recurrence_class")) if nr else ""
            sep=fnum(nr.get("separation_arcsec")) if nr else None
            bucket=recurrence_bucket(raw_class,sep)

            interval_text=";".join(
                f"{x[0]}|{x[1]['start'].isoformat()}|{x[1]['end'].isoformat()}|"
                f"{x[2]:.3f}|{x[3]}|{x[1]['source']}"
                for x in sorted(resolved,key=lambda z:z[0])
            )

            out_rows.append({
                "raw_match_row":rid,
                "population":pop,
                "locus_ra_deg":norm(r.get("locus_ra_deg")),
                "locus_dec_deg":norm(r.get("locus_dec_deg")),
                "physical_plate_id":plate,
                "scan_id":norm(r.get("scan_id")),
                "filename_scan":norm(r.get("filename_scan")),
                "archive_names":norm(r.get("archive_names")),
                "institutes":norm(r.get("institutes")),
                "coverage_class":norm(r.get("coverage_class")),
                "edge_distance_arcsec":norm(r.get("edge_distance_arcsec")),
                "physical_plate_exposure_row_count":norm(r.get("physical_plate_exposure_row_count")),
                "physical_plate_exposure_ids":norm(r.get("physical_plate_exposure_ids")),
                "resolved_exposure_intervals":interval_text,
                "best_exposure_id":eid,
                "best_comparison_start_utc":tr["start"].isoformat(),
                "best_comparison_end_utc":tr["end"].isoformat(),
                "best_timing_source":tr["source"],
                "actual_interval_gap_seconds":f"{gap:.3f}",
                "actual_interval_gap_minutes":f"{gap/60.0:.6f}",
                "temporal_relation":relation,
                "short_lag_tier":tier,
                "multi_exposure_plate":len(eids)>1,
                "resolved_exposure_count":len(resolved),
                "all_plate_exposures_resolved":len(resolved)==len(eids),
                "v078_plate_recurrence_class":raw_class,
                "v078_best_separation_arcsec":"" if sep is None else f"{sep:.9f}",
                "catalogue_recurrence_bucket":bucket,
                "pixel_validation_required":bucket!="STRICT_RECURRENCE",
                "qualified_negative_claimed":False,
            })

    out_rows.sort(key=lambda r:(
        {"A_LE30MIN":0,"B_GT30_LE60MIN":1,"C_GT60_LE120MIN":2}[r["short_lag_tier"]],
        float(r["actual_interval_gap_seconds"]),
        0 if r["population"].upper()=="PRIMARY" else 1,
        int(r["raw_match_row"]),
        int(r["physical_plate_id"]),
    ))
    wcsv(OUT_OPP,out_rows)

    # Timing-recovery manifest is written after row-level resolution.
    timing_manifest={
        "status":"COMPLETE",
        "operational_repair":
            "v092a reuse exact frozen v081a banked v077a exposure timing recovery",
        "scientific_contract_changed":False,
        "v081a_runner_sha256":EXPECTED_V081A_RUNNER_SHA,
        "wanted_exposure_ids":len(wanted_ids),
        "wanted_exposure_ids_present_in_frozen_cache":len(wanted_present),
        "wanted_exposure_ids_absent_from_frozen_cache":len(wanted_missing),
        "frozen_v081a_exposure_cache_rows":len(exposure_cache),
        "frozen_v081a_raw_votables_verified":len(exposure_cache_files),
        "unique_exposure_ids_resolved_on_eligible_rows":len(resolved_exposure_ids),
        "eligible_candidate_plate_rows_without_exact_intervals":
            unresolved_candidate_plate_rows,
        "unresolved_reason_counts":dict(unresolved_reasons),
        "first_200_wanted_exposure_ids_absent_from_cache":wanted_missing[:200],
        "source_files_used":[
            str(x).replace("\\","/") for x in exposure_cache_files
        ],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    OUT_TIMING.write_text(
        json.dumps(timing_manifest,indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    # Candidate-level summary.
    bycand=defaultdict(list)
    for r in out_rows:
        bycand[r["raw_match_row"]].append(r)

    summaries=[]
    for rid,rr in sorted(bycand.items(),key=lambda x:int(x[0])):
        meta=cand_summary_meta.get(rid,{})
        counts=Counter(x["short_lag_tier"] for x in rr)
        buckets=Counter(x["catalogue_recurrence_bucket"] for x in rr)
        nonstrict=[x for x in rr if x["catalogue_recurrence_bucket"]!="STRICT_RECURRENCE"]
        best=min(rr,key=lambda x:float(x["actual_interval_gap_seconds"]))
        best_non=min(nonstrict,key=lambda x:float(x["actual_interval_gap_seconds"])) if nonstrict else None
        summaries.append({
            "raw_match_row":rid,
            "population":rr[0]["population"],
            "target_ra_deg":norm(meta.get("target_ra_deg") or rr[0]["locus_ra_deg"]),
            "target_dec_deg":norm(meta.get("target_dec_deg") or rr[0]["locus_dec_deg"]),
            "catalog_recurrence_class":norm(meta.get("catalog_recurrence_class")),
            "tier_A_plate_count":counts["A_LE30MIN"],
            "tier_B_plate_count":counts["B_GT30_LE60MIN"],
            "tier_C_plate_count":counts["C_GT60_LE120MIN"],
            "strict_recurrence_plate_count_in_short_lag":buckets["STRICT_RECURRENCE"],
            "nonstrict_plate_count_requiring_pixel_validation":len(nonstrict),
            "best_any_short_lag_minutes":f"{float(best['actual_interval_gap_seconds'])/60.0:.6f}",
            "best_any_short_lag_tier":best["short_lag_tier"],
            "best_nonstrict_short_lag_minutes":(
                "" if best_non is None else
                f"{float(best_non['actual_interval_gap_seconds'])/60.0:.6f}"
            ),
            "best_nonstrict_short_lag_tier":"" if best_non is None else best_non["short_lag_tier"],
            "has_pixel_validation_queue":bool(nonstrict),
            "candidate_disposition_changed":False,
        })
    wcsv(OUT_SUM,summaries)

    queue=[
        r for r in out_rows
        if r["catalogue_recurrence_bucket"]!="STRICT_RECURRENCE"
    ]
    wcsv(OUT_QUEUE,queue)

    tier_counts=Counter(r["short_lag_tier"] for r in out_rows)
    tier_primary=Counter(
        r["short_lag_tier"] for r in out_rows if r["population"].upper()=="PRIMARY"
    )
    tier_diag=Counter(
        r["short_lag_tier"] for r in out_rows if r["population"].upper()=="DIAGNOSTIC"
    )
    q_tier=Counter(r["short_lag_tier"] for r in queue)
    q_cands=Counter(r["population"].upper() for r in queue)

    report={
        "status":"COMPLETE",
        "analysis_kind":"pair17_whole_population_short_lag_census_v092a",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "operational_repair":
            "reuse exact frozen v081a banked v077a exposure timing recovery",
        "scientific_contract_changed_by_v092a":False,
        "v081a_runner_sha256":EXPECTED_V081A_RUNNER_SHA,
        "science_overlap":{
            "start_utc":SCI_START.isoformat(),
            "end_utc":SCI_END.isoformat(),
            "duration_seconds":299,
        },
        "input_hashes":{
            str(p.relative_to(ROOT)).replace("\\","/"):sha(p)
            for p in (OPPS,TAP_MANIFEST,NEAREST,CAND_SUM,V077_BANK,V078_BANK,V081A_RUNNER)
        },
        "timing_recovery":{
            "wanted_exposure_ids":len(wanted_ids),
            "wanted_exposure_ids_present_in_frozen_cache":len(wanted_present),
            "wanted_exposure_ids_absent_from_frozen_cache":len(wanted_missing),
            "frozen_v081a_exposure_cache_rows":len(exposure_cache),
            "frozen_v081a_raw_votables_verified":len(exposure_cache_files),
            "unique_exposure_ids_resolved_on_eligible_rows":len(resolved_exposure_ids),
            "eligible_candidate_plate_rows_without_any_resolved_interval":
                unresolved_candidate_plate_rows,
            "unresolved_reason_counts":dict(unresolved_reasons),
        },
        "short_lag_candidate_plate_rows":len(out_rows),
        "short_lag_unique_candidates":len(bycand),
        "tier_counts_all":dict(tier_counts),
        "tier_counts_primary":dict(tier_primary),
        "tier_counts_diagnostic":dict(tier_diag),
        "pixel_validation_queue_rows":len(queue),
        "pixel_validation_queue_unique_candidates":len(set(r["raw_match_row"] for r in queue)),
        "pixel_validation_queue_tier_counts":dict(q_tier),
        "pixel_validation_queue_population_counts":dict(q_cands),
        "catalogue_absence_promoted_to_qualified_negative":False,
        "candidate_disposition_changes":False,
        "guards":{
            "network_calls":0,
            "fits_reads":0,
            "detector_reruns":0,
            "new_pixel_measurements":0,
            "manual_scores_modified":False,
            "threshold_retuning":False,
            "candidate_disposition_changes":False,
        },
        "output_hashes":{
            "opportunities_csv":sha(OUT_OPP),
            "candidate_summary_csv":sha(OUT_SUM),
            "pixel_validation_queue_csv":sha(OUT_QUEUE),
            "timing_recovery_manifest":sha(OUT_TIMING),
        }
    }
    OUT_JSON.write_text(
        json.dumps(report,indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    print()
    print("="*120)
    print("v092a SHORT-LAG CENSUS COMPLETE")
    print("="*120)
    print("Short-lag candidate×plate rows:",len(out_rows))
    print("Unique candidates:",len(bycand))
    print("Tier counts all:",dict(tier_counts))
    print("Tier counts PRIMARY:",dict(tier_primary))
    print("Tier counts DIAGNOSTIC:",dict(tier_diag))
    print("Pixel-validation queue rows:",len(queue))
    print("Pixel-validation queue unique candidates:",len(set(r["raw_match_row"] for r in queue)))
    print("Pixel-validation queue tiers:",dict(q_tier))
    print()
    print("TOP NON-STRICT SHORT-LAG OPPORTUNITIES")
    for r in queue[:30]:
        print(
            f'{r["raw_match_row"]} {r["population"]:10s} '
            f'{r["short_lag_tier"]:18s} gap={r["actual_interval_gap_minutes"]:>10s} min '
            f'plate={r["physical_plate_id"]} scan={r["scan_id"]} '
            f'catalog={r["catalogue_recurrence_bucket"]} '
            f'{r["archive_names"]}'
        )
    print("STAGE STATUS: COMPLETE")




if __name__=="__main__":
    main()
