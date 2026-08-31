from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json

ROOT = Path.cwd()
PREFLIGHT = ROOT / "results" / "wide_census_gaia_registration_preflight_v063" / "wide_census_gaia_registration_preflight_v063.json"
QUERY = ROOT / "results" / "wide_census_gaia_registration_preflight_v063" / "wide_census_gaia_ordinary_query_cells_v063.csv"
HPM = ROOT / "results" / "wide_census_gaia_registration_preflight_v063" / "wide_census_gaia_hpm_pair_queries_v063.csv"
FREEZE = ROOT / "research" / "prospective_freezes" / "wide_census_gaia_reference_acquisition_contract_v001.json"

OUTDIR = ROOT / "results" / "wide_census_gaia_query_dedup_v063a"
OUT_JSON = OUTDIR / "wide_census_gaia_query_dedup_v063a.json"
OUT_QUERY = OUTDIR / "wide_census_gaia_unique_ordinary_query_cells_v063a.csv"
OUT_HPM = OUTDIR / "wide_census_gaia_unique_hpm_queries_v063a.csv"

EXPECTED_FREEZE_SHA = "7a182349455a814423d68411d49aa7640dacdbe8dd6bafd5a5ec747c64b097fc"
EXPECTED_BASE_ROWS = 9191
EXPECTED_HPM_ROWS = 33
EXPECTED_PAIRS = 33


def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def read_csv(p):
    with p.open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(p, rows, fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    with t.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    t.replace(p)


def write_json(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    t.replace(p)


def fkey(r):
    # Exact transport identity. Pair and epoch are intentionally absent because
    # Gaia DR3 J2016 source rows are reusable; propagation remains pair-specific later.
    return (
        int(r["cell_ira"]),
        int(r["cell_idec"]),
        round(float(r["cell_size_deg"]),12),
        round(float(r["query_ra_deg"]),12),
        round(float(r["query_dec_deg"]),12),
        round(float(r["query_radius_deg"]),12),
        round(float(r["ordinary_j2016_margin_arcsec"]),6),
        int(r["maxrec"]),
    )


def hkey(r):
    return (
        round(float(r["query_ra_deg"]),12),
        round(float(r["query_dec_deg"]),12),
        round(float(r["query_radius_deg"]),12),
        round(float(r["pm_min_masyr"]),6),
        round(float(r["j2016_margin_arcsec"]),6),
    )


def main():
    print("="*128)
    print("WIDE CENSUS — GAIA QUERY GLOBAL-CACHE DEDUP AUDIT v063a")
    print("="*128)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO GAIA OUTCOMES. NO CANDIDATE STATE MUTATION.\n")

    for p in (PREFLIGHT,QUERY,HPM,FREEZE):
        if not p.is_file(): raise RuntimeError(f"missing prerequisite: {p}")
    if sha(FREEZE)!=EXPECTED_FREEZE_SHA:
        raise RuntimeError("REFUSING: v063 Gaia acquisition freeze SHA changed")

    pre=json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("status")!="COMPLETE":
        raise RuntimeError("REFUSING: v063 preflight incomplete")
    if (pre.get("guards") or {}).get("gaia_outcomes_read") is not False:
        raise RuntimeError("REFUSING: v063 no-outcome guard not preserved")

    qrows=read_csv(QUERY)
    hrows=read_csv(HPM)
    if len(qrows)!=EXPECTED_BASE_ROWS or len(hrows)!=EXPECTED_HPM_ROWS:
        raise RuntimeError(f"REFUSING row counts q={len(qrows)} hpm={len(hrows)}")

    grouped={}
    for r in qrows:
        k=fkey(r)
        grouped.setdefault(k,[]).append(r)

    out=[]
    for qi,(k,rows) in enumerate(sorted(grouped.items()),1):
        # All rows in an exact transport cell must agree on geometry.
        if any(fkey(r)!=k for r in rows):
            raise RuntimeError("internal transport-key disagreement")
        consumers=sorted({int(r["pair_index"]) for r in rows})
        out.append({
            "global_query_index":qi,
            "cell_ira":k[0],
            "cell_idec":k[1],
            "cell_size_deg":k[2],
            "query_ra_deg":k[3],
            "query_dec_deg":k[4],
            "query_radius_deg":k[5],
            "ordinary_j2016_margin_arcsec":k[6],
            "maxrec":k[7],
            "consumer_pair_count":len(consumers),
            "consumer_pair_indices":";".join(map(str,consumers)),
            "source_v063_row_count":len(rows),
        })

    hgroup={}
    for r in hrows:
        k=hkey(r); hgroup.setdefault(k,[]).append(r)
    hout=[]
    for qi,(k,rows) in enumerate(sorted(hgroup.items()),1):
        consumers=sorted({int(r["pair_index"]) for r in rows})
        hout.append({
            "global_hpm_query_index":qi,
            "query_ra_deg":k[0],
            "query_dec_deg":k[1],
            "query_radius_deg":k[2],
            "pm_min_masyr":k[3],
            "j2016_margin_arcsec":k[4],
            "consumer_pair_count":len(consumers),
            "consumer_pair_indices":";".join(map(str,consumers)),
            "source_v063_row_count":len(rows),
        })

    write_csv(OUT_QUERY,out,[
        "global_query_index","cell_ira","cell_idec","cell_size_deg",
        "query_ra_deg","query_dec_deg","query_radius_deg",
        "ordinary_j2016_margin_arcsec","maxrec",
        "consumer_pair_count","consumer_pair_indices","source_v063_row_count"
    ])
    write_csv(OUT_HPM,hout,[
        "global_hpm_query_index","query_ra_deg","query_dec_deg","query_radius_deg",
        "pm_min_masyr","j2016_margin_arcsec","consumer_pair_count",
        "consumer_pair_indices","source_v063_row_count"
    ])

    shared=sum(int(r["consumer_pair_count"])>1 for r in out)
    maxcons=max(int(r["consumer_pair_count"]) for r in out) if out else 0
    saved=len(qrows)-len(out)
    hsaved=len(hrows)-len(hout)

    rep={
        "status":"COMPLETE",
        "analysis_kind":"wide_census_gaia_query_global_cache_dedup_v063a",
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "gaia_outcomes_read":False,
            "candidate_state_mutation":False,
            "science_policy_changed":False,
        },
        "input_sha256":{
            "v063_preflight":sha(PREFLIGHT),
            "v063_query_plan":sha(QUERY),
            "v063_hpm_plan":sha(HPM),
            "v063_freeze":sha(FREEZE),
        },
        "ordinary":{
            "source_pair_scoped_query_rows":len(qrows),
            "global_unique_transport_queries":len(out),
            "exact_duplicate_requests_eliminated":saved,
            "shared_cells_consumed_by_multiple_pairs":shared,
            "maximum_consumer_pairs_for_one_cell":maxcons,
            "request_reduction_fraction":saved/len(qrows),
        },
        "hpm":{
            "source_pair_scoped_query_rows":len(hrows),
            "global_unique_transport_queries":len(hout),
            "exact_duplicate_requests_eliminated":hsaved,
        },
        "interpretation_boundary":(
            "Only byte-identical Gaia J2016 transport queries are deduplicated. "
            "Pair-specific epoch propagation, target exclusion, reference matching, "
            "window selection and astrometric registration remain unchanged and unrun."
        ),
        "next_stage":"Run v064 cached Gaia DR3 acquisition on the globally deduplicated transport plan."
    }
    write_json(OUT_JSON,rep)

    print("Pair-scoped ordinary requests:",len(qrows))
    print("Global unique ordinary requests:",len(out))
    print("Exact duplicate requests eliminated:",saved)
    print(f"Request reduction: {100*saved/len(qrows):.2f}%")
    print("Shared cells used by >1 pair:",shared)
    print("Maximum pair consumers for one cell:",maxcons)
    print("Pair-scoped HPM requests:",len(hrows))
    print("Global unique HPM requests:",len(hout))
    print("Gaia outcomes read: 0")
    print("STAGE STATUS: PASS")


if __name__=="__main__":
    main()
