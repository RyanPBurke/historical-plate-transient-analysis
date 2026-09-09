#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse, csv, hashlib, json, math, os, re

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research" / "prospective_freezes" / "v094u_source_free_site_reference_coverage_preflight_contract.json"
EXPECTED_CONTRACT_SHA = "cf1ae0b5b986bebbd3867ade7cfcc7cdd29e07fcb6031ea963a120a4767150d3"
V094T = ROOT / "results" / "applause_dr4_source_free_opportunity_population_repair_v094t"
V094T_CSV = V094T / "applause_dr4_source_free_cross_site_opportunities_v094t.csv"
V094T_REPORT = V094T / "applause_dr4_source_free_opportunity_population_repair_v094t.json"
V094T_MANIFEST = V094T / "v094t_output_manifest.sha256"
V094S_PROV = ROOT / "research" / "prospective_freezes" / "v094s_source_free_opportunity_population_parent_provenance.json"
RESULT = ROOT / "results" / "applause_dr4_v094u_site_reference_coverage_preflight"

R3B_REL = Path("pipeline_v0.2.0/research/prospective_freezes/v094r3b_historical_geometry_validation")
R3B_PLATE_REL = R3B_REL / "inputs/acquisition/applause_relevant_plate_geometry.csv"
C01_REL = R3B_REL / "inputs/acquisition/references/EOP_C01_IAU2000_1846-now.txt"
DT_REL = R3B_REL / "inputs/acquisition/references/historic_deltat.data"
R3B_PLATE_SHA = "ccd5e42cf04e5c72a767a38a2b6b7d1b36f6efaecdf10c4005af04bc777400cb"
C01_SHA = "846cb53ae1055de1cd80ab78e065b05ad0bc3b224bf8eafe27f428eb12da3ffb"
DT_SHA = "9f43514119060601a00624a5d9287a91b0b1f5e12bec5209bbabda90b392b70b"
EPS_DEG = 1e-9

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        yield from csv.DictReader(f)

def parse_dt(v):
    s=str(v or "").strip().replace("Z","+00:00")
    if not s:return None
    try:d=datetime.fromisoformat(s)
    except:return None
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def inum(v):
    try:
        x=float(str(v).strip())
        if not math.isfinite(x):return None
        q=int(round(x));return q if abs(x-q)<1e-9 else None
    except:return None

def fnum(v):
    try:
        x=float(str(v).strip())
        return x if math.isfinite(x) else None
    except:return None

def manifest_check(manifest,base):
    seen={}
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2:continue
        digest,name=q[0].lower(),q[1].strip()
        p=Path(base)/name
        if not p.is_file() or sha(p)!=digest:
            raise SystemExit(f"v094t manifest HOLD: {name}")
        seen[name]=digest
    required={V094T_CSV.name,V094T_REPORT.name}
    if not required.issubset(seen):
        raise SystemExit(f"v094t manifest HOLD: missing entries {sorted(required-set(seen))}")
    return seen

def mjd(d):
    epoch=datetime(1970,1,1,tzinfo=timezone.utc)
    return 40587.0+(d-epoch).total_seconds()/86400.0

def decimal_year(d):
    a=datetime(d.year,1,1,tzinfo=timezone.utc);b=datetime(d.year+1,1,1,tzinfo=timezone.utc)
    return d.year+(d-a).total_seconds()/(b-a).total_seconds()

def c01_domain(p):
    vals=[]
    for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
        q=line.split()
        if not q:continue
        try:x=float(q[0])
        except:continue
        if math.isfinite(x):vals.append(x)
    if len(vals)<1000:raise SystemExit(f"C01 parse HOLD: only {len(vals)} numeric records")
    return min(vals),max(vals),len(vals)

def deltat_domain(p):
    vals=[]
    for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
        q=line.split()
        if not q:continue
        try:x=float(q[0])
        except:continue
        if math.isfinite(x):vals.append(x)
    if len(vals)<500:raise SystemExit(f"historic DeltaT parse HOLD: only {len(vals)} numeric records")
    return min(vals),max(vals),len(vals)

def self_test():
    t=parse_dt("1955-01-01T00:00:00Z")
    assert t and abs(mjd(t)-35108.0)<1e-6
    assert abs(decimal_year(datetime(1955,7,2,tzinfo=timezone.utc))-1955.4986301369863)<0.002
    assert inum("42.0")==42 and inum("42.2") is None
    assert fnum("1.25")==1.25 and fnum("nan") is None
    print("v094u site/reference coverage preflight self-test PASS")
    return 0

def run(repo_root):
    repo_root=Path(repo_root).resolve()
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise SystemExit("v094u contract SHA mismatch")
    for p in (V094T_CSV,V094T_REPORT,V094T_MANIFEST,V094S_PROV):
        if not p.is_file():raise SystemExit(f"Missing required parent artifact: {p}")
    manifest_check(V094T_MANIFEST,V094T)
    rep=json.loads(V094T_REPORT.read_text(encoding="utf-8"))
    if rep.get("status")!="COMPLETE":raise SystemExit("v094t report is not COMPLETE")
    if int(rep.get("distinct_site_temporal_pairs_le15min",-1))!=13177:
        raise SystemExit("v094t report pair-count replay HOLD")
    if int((rep.get("exclusive_timing_bins_all") or {}).get("OVERLAP",-1))!=8807:
        raise SystemExit("v094t report OVERLAP-count replay HOLD")

    prov=json.loads(V094S_PROV.read_text(encoding="utf-8"))
    cache_rec=(prov.get("inputs") or {}).get("plate_site_cache")
    if not cache_rec:raise SystemExit("v094s provenance missing plate_site_cache")
    plate_cache=ROOT/cache_rec["path"]
    if not plate_cache.is_file() or sha(plate_cache)!=str(cache_rec["sha256"]).lower():
        raise SystemExit("Frozen v094s plate-site cache hash HOLD")

    r3b_plate=repo_root/R3B_PLATE_REL
    c01=repo_root/C01_REL
    dt=repo_root/DT_REL
    for p,expect,label in ((r3b_plate,R3B_PLATE_SHA,"r3b plate geometry"),
                           (c01,C01_SHA,"IERS C01"),
                           (dt,DT_SHA,"historic DeltaT")):
        if not p.is_file() or sha(p)!=expect:
            raise SystemExit(f"Frozen reference hash HOLD: {label}")

    # Frozen plate cache.
    cache={}
    duplicate_cache=0
    for r in rows(plate_cache):
        pid=inum(r.get("plate_id"))
        if pid is None:continue
        rec=(str(r.get("site_name") or "").strip(),fnum(r.get("site_longitude")),fnum(r.get("site_latitude")))
        if pid in cache and cache[pid]!=rec:duplicate_cache+=1
        cache[pid]=rec
    if duplicate_cache:
        raise SystemExit(f"Plate cache duplicate-conflict HOLD: {duplicate_cache}")

    # Frozen r3b site/elevation basis.
    r3b_by_plate={}
    r3b_by_site=defaultdict(set)
    r3b_rows=0
    for r in rows(r3b_plate):
        r3b_rows+=1
        pid=inum(r.get("plate_id"));site=str(r.get("site_name") or "").strip()
        lon=fnum(r.get("site_longitude"));lat=fnum(r.get("site_latitude"));elev=fnum(r.get("site_elevation"))
        if None in (pid,lon,lat,elev) or not site:
            raise SystemExit(f"r3b geometry structural HOLD at row {r3b_rows}")
        tup=(lon,lat,elev)
        if pid in r3b_by_plate and r3b_by_plate[pid]!=(site,tup):
            raise SystemExit(f"r3b duplicate plate conflict: {pid}")
        r3b_by_plate[pid]=(site,tup);r3b_by_site[site].add(tup)
    if r3b_rows!=1289:raise SystemExit(f"r3b plate geometry row replay HOLD: {r3b_rows}")

    # v094t population and overlap integrity.
    total=0;overlap=0;pair_ids=set();dups=0
    required_plates=defaultdict(set)
    side_occ=Counter();site_pairs=Counter()
    plate_expected_site={}
    overlap_min=None;overlap_max=None;overlap_intervals=0
    bad_overlap_json=0;nonpositive_overlap_intervals=0;side_site_conflicts=0
    direct_r3b_pair_sides=0;all_pair_sides=0
    for r in rows(V094T_CSV):
        total+=1
        pair_id=str(r.get("pair_id") or "")
        if pair_id in pair_ids:dups+=1
        pair_ids.add(pair_id)
        if str(r.get("timing_bin") or "")!="OVERLAP":continue
        overlap+=1
        a,b=inum(r.get("plate_a")),inum(r.get("plate_b"))
        sa,sb=str(r.get("site_a") or "").strip(),str(r.get("site_b") or "").strip()
        if None in (a,b) or not sa or not sb:raise SystemExit(f"OVERLAP structural HOLD: {pair_id}")
        for pid,site in ((a,sa),(b,sb)):
            all_pair_sides+=1;required_plates[site].add(pid);side_occ[site]+=1
            if pid in r3b_by_plate:direct_r3b_pair_sides+=1
            if pid in plate_expected_site and plate_expected_site[pid]!=site:side_site_conflicts+=1
            plate_expected_site[pid]=site
        site_pairs[" | ".join(sorted((sa,sb)))]+=1
        try:ivs=json.loads(str(r.get("fragment_overlap_intervals_json") or "[]"))
        except:
            bad_overlap_json+=1;continue
        if not isinstance(ivs,list) or not ivs:
            bad_overlap_json+=1;continue
        for x in ivs:
            s=parse_dt(x.get("start_utc"));e=parse_dt(x.get("end_utc"))
            dur=fnum(x.get("duration_seconds"))
            if s is None or e is None or e<=s or dur is None or dur<=0:
                nonpositive_overlap_intervals+=1;continue
            # Require serialized duration to agree with endpoints closely enough for a preflight.
            if abs((e-s).total_seconds()-dur)>0.001:
                nonpositive_overlap_intervals+=1;continue
            overlap_intervals+=1
            overlap_min=s if overlap_min is None or s<overlap_min else overlap_min
            overlap_max=e if overlap_max is None or e>overlap_max else overlap_max

    if total!=13177 or len(pair_ids)!=13177 or dups:
        raise SystemExit(f"v094t CSV replay HOLD: rows={total} unique={len(pair_ids)} dup={dups}")
    if overlap!=8807:
        raise SystemExit(f"v094t OVERLAP replay HOLD: {overlap}")
    if bad_overlap_json or nonpositive_overlap_intervals or side_site_conflicts:
        raise SystemExit(
            f"v094t overlap integrity HOLD: bad_json={bad_overlap_json} "
            f"bad_interval={nonpositive_overlap_intervals} side_site_conflicts={side_site_conflicts}"
        )
    if overlap_min is None or overlap_max is None:
        raise SystemExit("No valid OVERLAP interval span")

    required_plate_ids=set(plate_expected_site)
    missing_cache=[];site_name_mismatch=[];lonlat_mismatch=[]
    site_rows=[]
    missing_ambiguous_sites=[]
    inherited_plates=0;direct_plates=0
    for site in sorted(required_plates):
        pids=required_plates[site]
        tuples=sorted(r3b_by_site.get(site,set()))
        status="READY_SITE_METADATA_REUSE"
        reason=""
        chosen=None
        if len(tuples)!=1:
            status="SITE_METADATA_ACQUISITION_REQUIRED"
            reason=("SITE_ABSENT_FROM_R3B" if len(tuples)==0 else "R3B_SITE_METADATA_AMBIGUOUS")
        else:
            chosen=tuples[0]
        direct=sum(1 for pid in pids if pid in r3b_by_plate)
        direct_plates+=direct
        cache_ok=0
        site_mis=0
        ll_mis=0
        for pid in sorted(pids):
            c=cache.get(pid)
            if c is None:
                missing_cache.append(pid);continue
            csite,clon,clat=c
            if csite!=site:
                site_name_mismatch.append((pid,site,csite));site_mis+=1;continue
            if chosen is not None:
                lon,lat,elev=chosen
                if clon is None or clat is None or abs(clon-lon)>EPS_DEG or abs(clat-lat)>EPS_DEG:
                    lonlat_mismatch.append((pid,site,clon,clat,lon,lat));ll_mis+=1;continue
            cache_ok+=1
        if chosen is None or cache_ok!=len(pids):
            status="SITE_OR_PLATE_METADATA_ACQUISITION_REQUIRED"
            if not reason:reason="PLATE_CACHE_SITE_OR_LONLAT_MISMATCH"
        else:
            inherited_plates+=len(pids)-direct
        if status!="READY_SITE_METADATA_REUSE":
            missing_ambiguous_sites.append(site)
        lon=lat=elev=""
        if chosen is not None:lon,lat,elev=chosen
        site_rows.append({
            "site_name":site,
            "overlap_pair_side_occurrences":side_occ[site],
            "unique_required_plates":len(pids),
            "direct_r3b_plate_rows":direct,
            "site_level_inherited_new_plate_count":max(0,len(pids)-direct) if status=="READY_SITE_METADATA_REUSE" else 0,
            "plate_cache_rows_matching_site_lonlat":cache_ok,
            "r3b_unique_site_tuple_count":len(tuples),
            "site_longitude":lon,"site_latitude":lat,"site_elevation_m":elev,
            "coverage_status":status,"reason":reason
        })

    cmin,cmax,cn=c01_domain(c01)
    dmin,dmax,dn=deltat_domain(dt)
    omin_mjd,omax_mjd=mjd(overlap_min),mjd(overlap_max)
    omin_y,omax_y=decimal_year(overlap_min),decimal_year(overlap_max)
    c01_ok=(cmin<=omin_mjd and omax_mjd<=cmax)
    dt_ok=(dmin<=omin_y and omax_y<=dmax)

    failures={
        "missing_required_plates_from_plate_cache":len(set(missing_cache)),
        "v094t_side_vs_plate_cache_site_name_mismatches":len(site_name_mismatch),
        "site_lonlat_mismatches_against_r3b":len(lonlat_mismatch),
        "site_metadata_missing_or_ambiguous":len(missing_ambiguous_sites),
        "reference_coverage_failures":int(not c01_ok)+int(not dt_ok)
    }
    ready=all(v==0 for v in failures.values())
    outcome="READY_TO_FREEZE_FINITE_DISTANCE_GEOMETRY" if ready else "SITE_OR_REFERENCE_ACQUISITION_REQUIRED"

    if RESULT.exists():
        raise SystemExit(f"Publication HOLD: final v094u result already exists: {RESULT}")
    stage=RESULT.parent/(RESULT.name+".__staging__."+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"."+str(os.getpid()))
    stage.mkdir(parents=True,exist_ok=False)

    site_csv=stage/"v094u_site_reference_coverage_by_site.csv"
    fields=["site_name","overlap_pair_side_occurrences","unique_required_plates","direct_r3b_plate_rows",
            "site_level_inherited_new_plate_count","plate_cache_rows_matching_site_lonlat",
            "r3b_unique_site_tuple_count","site_longitude","site_latitude","site_elevation_m",
            "coverage_status","reason"]
    with site_csv.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(site_rows)

    issues_csv=stage/"v094u_site_reference_coverage_issues.csv"
    with issues_csv.open("w",encoding="utf-8",newline="") as f:
        fields2=["issue_type","plate_id","expected_site","observed_site","observed_lon","observed_lat","reference_lon","reference_lat"]
        w=csv.DictWriter(f,fieldnames=fields2);w.writeheader()
        for pid in sorted(set(missing_cache)):
            w.writerow({"issue_type":"PLATE_MISSING_FROM_FROZEN_CACHE","plate_id":pid})
        for pid,es,os_ in site_name_mismatch:
            w.writerow({"issue_type":"PLATE_CACHE_SITE_NAME_MISMATCH","plate_id":pid,"expected_site":es,"observed_site":os_})
        for pid,site,clon,clat,lon,lat in lonlat_mismatch:
            w.writerow({"issue_type":"PLATE_CACHE_LONLAT_MISMATCH_R3B_SITE","plate_id":pid,"expected_site":site,
                        "observed_lon":clon,"observed_lat":clat,"reference_lon":lon,"reference_lat":lat})

    report={
      "status":"COMPLETE",
      "analysis_kind":"v094u_source_free_site_reference_coverage_preflight",
      "outcome":outcome,
      "contract_sha256":EXPECTED_CONTRACT_SHA,
      "parent_v094t":{
        "rows":total,"unique_pair_ids":len(pair_ids),"overlap_rows":overlap,
        "positive_duration_overlap_intervals":overlap_intervals,
        "overlap_utc_min":overlap_min.isoformat(),"overlap_utc_max":overlap_max.isoformat()
      },
      "population":{
        "unique_overlap_plate_ids":len(required_plate_ids),
        "unique_overlap_sites":len(required_plates),
        "site_pairs":dict(site_pairs),
        "overlap_pair_side_occurrences":all_pair_sides,
        "pair_side_occurrences_with_direct_r3b_plate_row":direct_r3b_pair_sides,
        "unique_required_plates_with_direct_r3b_row":direct_plates,
        "unique_required_plates_reusing_site_level_elevation":inherited_plates
      },
      "r3b_site_foundation":{
        "rows":r3b_rows,"unique_sites":len(r3b_by_site),
        "plate_geometry_sha256":sha(r3b_plate),
        "sites_with_multiple_metadata_tuples":sorted([s for s,v in r3b_by_site.items() if len(v)!=1])
      },
      "reference_coverage":{
        "iers_c01":{"sha256":sha(c01),"records":cn,"mjd_min":cmin,"mjd_max":cmax,
                    "required_mjd_min":omin_mjd,"required_mjd_max":omax_mjd,"covers_required_span":c01_ok},
        "historic_deltat":{"sha256":sha(dt),"records":dn,"decimal_year_min":dmin,"decimal_year_max":dmax,
                           "required_decimal_year_min":omin_y,"required_decimal_year_max":omax_y,"covers_required_span":dt_ok}
      },
      "acceptance_failures":failures,
      "missing_or_ambiguous_sites":sorted(missing_ambiguous_sites),
      "guards":{"source_catalog_reads":0,"candidate_identity_inspection":0,"private_candidate_map_reads":0,
                "pixels":0,"registration":0,"network":0,"real_source_pairing":0,
                "finite_distance_geometry":0,"distance_grid_evaluation":0,"threshold_retuning":0},
      "next_stage":(
        "Freeze finite-distance topocentric geometry and synthetic recoverability over the v094t OVERLAP population."
        if ready else
        "Freeze an acquisition-only repair for missing/ambiguous site or reference metadata before finite-distance geometry."
      )
    }
    report_path=stage/"v094u_site_reference_coverage_preflight.json"
    report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    manifest=stage/"v094u_output_manifest.sha256"
    manifest.write_text(
        f"{sha(site_csv)}  {site_csv.name}\n{sha(issues_csv)}  {issues_csv.name}\n{sha(report_path)}  {report_path.name}\n",
        encoding="utf-8"
    )
    if RESULT.exists():
        raise SystemExit(f"Publication HOLD: final v094u result appeared before publish; staging preserved at {stage}")
    os.replace(stage,RESULT)

    print("\n"+"="*108)
    print("v094u SOURCE-FREE SITE / REFERENCE COVERAGE PREFLIGHT COMPLETE")
    print("="*108)
    print(f"Outcome:                                      {outcome}")
    print(f"v094t rows / OVERLAP rows:                   {total:,} / {overlap:,}")
    print(f"Positive-duration overlap intervals:         {overlap_intervals:,}")
    print(f"Unique OVERLAP plates / sites:               {len(required_plate_ids):,} / {len(required_plates):,}")
    print(f"Direct r3b plate coverage:                   {direct_plates:,}/{len(required_plate_ids):,}")
    print(f"New plate IDs covered by validated site:     {inherited_plates:,}")
    print(f"Missing/ambiguous required sites:            {len(missing_ambiguous_sites)}")
    print(f"Plate-cache missing/site/lonlat failures:    {failures['missing_required_plates_from_plate_cache']} / {failures['v094t_side_vs_plate_cache_site_name_mismatches']} / {failures['site_lonlat_mismatches_against_r3b']}")
    print(f"IERS C01 covers complete overlap span:       {c01_ok}")
    print(f"Historic DeltaT covers complete span:        {dt_ok}")
    print("Source catalogues / identities / network:    0 / 0 / 0")
    print("Finite-distance geometry evaluations:        0")
    print("STOP: interpret this preflight before freezing the geometry solver.")
    return 0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--repo-root")
    a=ap.parse_args()
    if a.self_test:return self_test()
    if not a.repo_root:raise SystemExit("--repo-root is required")
    return run(a.repo_root)

if __name__=="__main__":
    raise SystemExit(main())
