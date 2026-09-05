#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
import csv, hashlib, json, math, os, re, sys

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


def candidate_source_files():
    """
    Resolve already-local timing products. First use paths explicitly present in
    the frozen v077a TAP manifest. Then add narrowly-scoped APPLAUSE/TAP/exposure
    cache files under work/ if their names suggest exposure metadata.
    """
    found=set()

    if TAP_MANIFEST.is_file():
        try:
            rows=rcsv(TAP_MANIFEST)
            for r in rows:
                for v in r.values():
                    s=norm(v).strip('"')
                    if not s:
                        continue
                    # Extract Windows/relative path-like tokens.
                    candidates=[s]
                    for token in re.split(r"\s+",s):
                        if any(token.lower().endswith(ext) for ext in (
                            ".xml",".vot",".votable",".csv",".json",".ecsv"
                        )):
                            candidates.append(token)
                    for q in candidates:
                        q=q.strip().strip('"').strip("'")
                        if not any(q.lower().endswith(ext) for ext in (
                            ".xml",".vot",".votable",".csv",".json",".ecsv"
                        )):
                            continue
                        p=Path(q)
                        if not p.is_absolute():
                            p=ROOT/p
                        if p.is_file():
                            found.add(p.resolve())
        except Exception:
            pass

    # v077a directory itself may contain banked raw query products.
    for base in [V077_DIR, ROOT/"work"]:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".xml",".vot",".votable",".csv",".ecsv",".json"}:
                continue
            name=p.name.lower()
            if base == ROOT/"work" and not any(t in name for t in (
                "exposure","tap","applause","v077","plate"
            )):
                continue
            if p.stat().st_size > 250_000_000:
                continue
            found.add(p.resolve())

    # Exclude known derived products that cannot provide authoritative exposure ends.
    exclude={OPPS.resolve(), NEAREST.resolve(), CAND_SUM.resolve()}
    return sorted(p for p in found if p not in exclude)


def parse_csv_timing_file(path, wanted_ids):
    records=[]
    try:
        with path.open("r",encoding="utf-8-sig",newline="") as f:
            rdr=csv.DictReader(f)
            fields=rdr.fieldnames or []
            idc=choose_col(fields,ID_ALIASES)
            stc=choose_col(fields,START_ALIASES)
            enc=choose_col(fields,END_ALIASES)
            duc=choose_col(fields,DUR_ALIASES)
            if not idc or not stc or (not enc and not duc):
                return [], None

            # Generic duration fields in CSV are only accepted as seconds when
            # their name explicitly says seconds/_s. Otherwise exact end is required.
            dur_seconds_allowed = bool(
                duc and (
                    "second" in duc.lower()
                    or duc.lower().endswith("_s")
                )
            )

            matched=0
            for row in rdr:
                eid=inum(row.get(idc))
                if eid not in wanted_ids:
                    continue
                st=parse_dt(row.get(stc))
                en=parse_dt(row.get(enc)) if enc else None
                source="EXACT_START_END"
                if st and not en and duc and dur_seconds_allowed:
                    dur=fnum(row.get(duc))
                    if dur is not None and dur >= 0:
                        en=st+timedelta(seconds=dur)
                        source=f"START_PLUS_{duc}_SECONDS"
                if st and en and en >= st:
                    records.append((eid,st,en,source))
                    matched+=1

            meta={
                "path":str(path),
                "sha256":sha(path),
                "format":"CSV",
                "id_column":idc,
                "start_column":stc,
                "end_column":enc or "",
                "duration_column":duc or "",
                "duration_seconds_accepted":dur_seconds_allowed,
                "matched_exact_intervals":matched,
            }
            return records,meta
    except Exception:
        return [],None


def parse_table_timing_file(path,wanted_ids):
    """
    VOTable/ECSV reader with Astropy. Duration is accepted only when its declared
    unit converts to seconds, or the column name explicitly encodes seconds.
    """
    try:
        from astropy.table import Table
        import astropy.units as u
    except Exception:
        return [],None

    try:
        t=Table.read(path)
    except Exception:
        return [],None

    fields=list(t.colnames)
    idc=choose_col(fields,ID_ALIASES)
    stc=choose_col(fields,START_ALIASES)
    enc=choose_col(fields,END_ALIASES)
    duc=choose_col(fields,DUR_ALIASES)
    if not idc or not stc or (not enc and not duc):
        return [],None

    dur_unit_seconds=False
    dur_unit=""
    if duc:
        unit=getattr(t[duc],"unit",None)
        dur_unit=str(unit or "")
        if unit is not None:
            try:
                (1*unit).to(u.s)
                dur_unit_seconds=True
            except Exception:
                pass
        if "second" in duc.lower() or duc.lower().endswith("_s"):
            dur_unit_seconds=True

    records=[]
    matched=0
    for row in t:
        eid=inum(row[idc])
        if eid not in wanted_ids:
            continue
        st=parse_dt(row[stc])
        en=parse_dt(row[enc]) if enc else None
        source="EXACT_START_END"
        if st and not en and duc and dur_unit_seconds:
            dur=fnum(row[duc])
            if dur is not None and dur >= 0:
                if getattr(t[duc],"unit",None) is not None:
                    try:
                        import astropy.units as u
                        dur=float((dur*t[duc].unit).to_value(u.s))
                    except Exception:
                        dur=None
                if dur is not None:
                    en=st+timedelta(seconds=dur)
                    source=f"START_PLUS_{duc}_DECLARED_SECONDS"
        if st and en and en >= st:
            records.append((eid,st,en,source))
            matched+=1

    meta={
        "path":str(path),
        "sha256":sha(path),
        "format":"ASTROPY_TABLE",
        "id_column":idc,
        "start_column":stc,
        "end_column":enc or "",
        "duration_column":duc or "",
        "duration_unit":dur_unit,
        "duration_seconds_accepted":dur_unit_seconds,
        "matched_exact_intervals":matched,
    }
    return records,meta


def recover_timing(wanted_ids):
    by_id=defaultdict(list)
    sources=[]

    for p in candidate_source_files():
        if p.suffix.lower()==".csv":
            recs,meta=parse_csv_timing_file(p,wanted_ids)
        else:
            recs,meta=parse_table_timing_file(p,wanted_ids)
        if meta and recs:
            sources.append(meta)
            for eid,st,en,source in recs:
                by_id[eid].append({
                    "start":st,
                    "end":en,
                    "source":source,
                    "path":str(p),
                })

    # De-duplicate identical intervals; preserve conflicting alternatives.
    clean={}
    conflicts={}
    for eid,rr in by_id.items():
        uniq={}
        for r in rr:
            k=(r["start"],r["end"])
            uniq.setdefault(k,r)
        vals=list(uniq.values())
        clean[eid]=vals
        if len(vals)>1:
            conflicts[eid]=[
                {
                    "start":r["start"].isoformat(),
                    "end":r["end"].isoformat(),
                    "path":r["path"],
                    "source":r["source"],
                } for r in vals
            ]

    return clean,sources,conflicts


def main():
    print("="*120)
    print("PAIR 17 — WHOLE-POPULATION SHORT-LAG CENSUS v092")
    print("="*120)
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

    for p in (OPPS,TAP_MANIFEST,NEAREST,CAND_SUM,V077_BANK,V078_BANK):
        if not p.is_file():
            raise RuntimeError(f"Required frozen input missing: {p}")

    print("Input hashes:")
    for p in (OPPS,TAP_MANIFEST,NEAREST,CAND_SUM,V077_BANK,V078_BANK):
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

    timing,sources,conflicts=recover_timing(wanted_ids)

    exact_ids={eid for eid,vals in timing.items() if len(vals)==1}
    unresolved_ids=sorted(wanted_ids-exact_ids)

    print("Exact unique exposure intervals recovered:",len(exact_ids))
    print("Timing conflicts:",len(conflicts))
    print("Timing unresolved:",len(unresolved_ids))

    timing_manifest={
        "status":"COMPLETE" if exact_ids else "HOLD_NO_EXACT_TIMING",
        "wanted_exposure_ids":len(wanted_ids),
        "exact_unique_exposure_ids":len(exact_ids),
        "conflicting_exposure_ids":len(conflicts),
        "unresolved_exposure_ids":len(unresolved_ids),
        "source_files_used":sources,
        "conflicts":conflicts,
        "first_200_unresolved_exposure_ids":unresolved_ids[:200],
    }

    OUT.mkdir(parents=True,exist_ok=True)
    OUT_TIMING.write_text(
        json.dumps(timing_manifest,indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    if not exact_ids:
        raise RuntimeError(
            "PROVENANCE HOLD: no exact exposure intervals recovered from local/banked timing products"
        )

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

    # Pass 2: calculate actual interval gaps.
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
            resolved=[]
            for eid in eids:
                vals=timing.get(eid,[])
                if len(vals)!=1:
                    continue
                tr=vals[0]
                gap,relation=interval_gap(tr["start"],tr["end"])
                resolved.append((eid,tr,gap,relation))

            if not resolved:
                unresolved_candidate_plate_rows+=1
                continue

            # Tier is based on the closest actual exposure interval on this physical plate.
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
                f"{x[2]:.3f}|{x[3]}"
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

    # Descriptive counts.
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
        "analysis_kind":"pair17_whole_population_short_lag_census_v092",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "science_overlap":{
            "start_utc":SCI_START.isoformat(),
            "end_utc":SCI_END.isoformat(),
            "duration_seconds":299,
        },
        "input_hashes":{
            str(p.relative_to(ROOT)).replace("\\","/"):sha(p)
            for p in (OPPS,TAP_MANIFEST,NEAREST,CAND_SUM,V077_BANK,V078_BANK)
        },
        "timing_recovery":{
            "wanted_exposure_ids":len(wanted_ids),
            "exact_unique_exposure_ids":len(exact_ids),
            "conflicting_exposure_ids":len(conflicts),
            "unresolved_exposure_ids":len(unresolved_ids),
            "eligible_candidate_plate_rows_without_any_resolved_interval":
                unresolved_candidate_plate_rows,
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
    print("v092 SHORT-LAG CENSUS COMPLETE")
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
