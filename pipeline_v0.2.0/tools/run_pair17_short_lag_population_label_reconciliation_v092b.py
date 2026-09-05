#!/usr/bin/env python3
from pathlib import Path
from collections import Counter, defaultdict
import csv, hashlib, json

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_short_lag_population_label_reconciliation_contract_v092b.json"
)
EXPECTED_CONTRACT_SHA = "6a683fc9e72876e3adbd920b62762da7814a1c80610a0ccc1d2315e31946c992"

V092 = ROOT / "results" / "pair17_whole_population_short_lag_census_v092"
BANK = V092 / "pair17_v092a_bank_manifest.json"
EXPECTED_BANK_SHA = "9ac0dcc474ab4eda7e9d1fee9bfd8dc67dcf8c47ffebda786ee69be7de4c1a59"

OUT = ROOT / "results" / "pair17_short_lag_population_label_reconciliation_v092b"
REPORT = OUT / "pair17_short_lag_population_label_reconciliation_v092b.json"


def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def rcsv(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))


def norm(v):
    return str(v or "").strip()


def pop_family(v):
    s=norm(v).upper()
    if s.startswith("PRIMARY"):
        return "PRIMARY"
    if s.startswith("DIAGNOSTIC"):
        return "DIAGNOSTIC"
    return s or "UNKNOWN"


def verify_banked_file(bank, suffix):
    matches=[
        rec for rec in bank.get("files",[])
        if str(rec.get("path","")).endswith(suffix)
    ]
    if len(matches)!=1:
        raise RuntimeError(f"Expected one banked file ending {suffix!r}; found {len(matches)}")
    rec=matches[0]
    p=ROOT / rec["path"]
    if not p.is_file():
        raise RuntimeError(f"Banked file missing: {p}")
    actual=sha(p)
    if actual != rec["sha256"]:
        raise RuntimeError(
            f"Banked file SHA mismatch: {p}\nexpected {rec['sha256']}\nactual   {actual}"
        )
    return p


def main():
    print("="*120)
    print("PAIR 17 — SHORT-LAG POPULATION-LABEL RECONCILIATION v092b")
    print("="*120)
    print("Operational reporting reconciliation only")
    print("v092a banked products modified: NO")
    print("Science thresholds / intervals / recurrence policy changed: NO")
    print()

    if sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v092b contract SHA mismatch")
    if sha(BANK)!=EXPECTED_BANK_SHA:
        raise RuntimeError("v092a bank manifest SHA mismatch")

    bank=json.loads(BANK.read_text(encoding="utf-8"))

    opp=verify_banked_file(bank,"pair17_short_lag_opportunities_v092.csv")
    queue=verify_banked_file(bank,"pair17_short_lag_pixel_validation_queue_v092.csv")
    report_v092a=verify_banked_file(bank,"pair17_whole_population_short_lag_census_v092.json")

    rows=rcsv(opp)
    qrows=rcsv(queue)
    old=json.loads(report_v092a.read_text(encoding="utf-8"))

    exact_pop=Counter(norm(r.get("population")) for r in rows)
    fam_pop=Counter(pop_family(r.get("population")) for r in rows)

    exact_tier=defaultdict(Counter)
    fam_tier=defaultdict(Counter)
    for r in rows:
        tier=norm(r.get("short_lag_tier"))
        exact_tier[norm(r.get("population"))][tier]+=1
        fam_tier[pop_family(r.get("population"))][tier]+=1

    q_exact=Counter(norm(r.get("population")) for r in qrows)
    q_fam=Counter(pop_family(r.get("population")) for r in qrows)
    q_fam_tier=defaultdict(Counter)
    for r in qrows:
        q_fam_tier[pop_family(r.get("population"))][norm(r.get("short_lag_tier"))]+=1

    tier_counts=Counter(norm(r.get("short_lag_tier")) for r in rows)
    plates=Counter(norm(r.get("physical_plate_id")) for r in rows)
    scans=Counter(norm(r.get("scan_id")) for r in rows)
    gaps=Counter(norm(r.get("actual_interval_gap_minutes")) for r in rows)
    relations=Counter(norm(r.get("temporal_relation")) for r in rows)
    archives=Counter(norm(r.get("archive_names")) for r in rows)

    tier_a=sum(1 for r in rows if norm(r.get("short_lag_tier"))=="A_LE30MIN")
    tier_b=sum(1 for r in rows if norm(r.get("short_lag_tier"))=="B_GT30_LE60MIN")

    reconciliation = {
        "status":"COMPLETE",
        "analysis_kind":"pair17_short_lag_population_label_reconciliation_v092b",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "v092a_bank_manifest_sha256":EXPECTED_BANK_SHA,
        "cause_of_v092a_reporting_error":{
            "banked_population_values":sorted(exact_pop.keys()),
            "v092a_summary_filter_expected_exact_values":["PRIMARY","DIAGNOSTIC"],
            "effect":
                "tier_counts_primary and tier_counts_diagnostic in the v092a JSON were empty "
                "because labels are PRIMARY_424 and DIAGNOSTIC_179; row-level census/tier assignment was unaffected."
        },
        "row_count":len(rows),
        "unique_candidates":len(set(norm(r.get("raw_match_row")) for r in rows)),
        "tier_counts_all":dict(tier_counts),
        "population_counts_exact":dict(exact_pop),
        "population_counts_normalized":dict(fam_pop),
        "tier_counts_by_exact_population":{
            k:dict(v) for k,v in exact_tier.items()
        },
        "tier_counts_by_normalized_population":{
            k:dict(v) for k,v in fam_tier.items()
        },
        "tier_A_rows":tier_a,
        "tier_B_rows":tier_b,
        "has_any_le60min_opportunity":bool(tier_a or tier_b),
        "pixel_validation_queue":{
            "rows":len(qrows),
            "unique_candidates":len(set(norm(r.get("raw_match_row")) for r in qrows)),
            "population_counts_exact":dict(q_exact),
            "population_counts_normalized":dict(q_fam),
            "tier_counts_by_normalized_population":{
                k:dict(v) for k,v in q_fam_tier.items()
            }
        },
        "distinct_comparison_plates":dict(plates),
        "distinct_scans":dict(scans),
        "distinct_actual_gap_minutes":dict(gaps),
        "temporal_relations":dict(relations),
        "archives":dict(archives),
        "v092a_reported_tier_counts_primary":old.get("tier_counts_primary"),
        "v092a_reported_tier_counts_diagnostic":old.get("tier_counts_diagnostic"),
        "v092a_products_modified":False,
        "candidate_disposition_changes":False,
        "guards":{
            "network_calls":0,
            "fits_reads":0,
            "detector_reruns":0,
            "new_pixel_measurements":0,
            "candidate_disposition_changes":False,
            "v092a_products_modified":False
        }
    }

    OUT.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(
        json.dumps(reconciliation,indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    print("Rows:",len(rows))
    print("Unique candidates:",reconciliation["unique_candidates"])
    print("All tiers:",dict(tier_counts))
    print("Exact populations:",dict(exact_pop))
    print("Corrected normalized tier counts:")
    for k in sorted(fam_tier):
        print(" ",k,dict(fam_tier[k]))
    print("Tier A rows:",tier_a)
    print("Tier B rows:",tier_b)
    print("Any <=60 min opportunity:",bool(tier_a or tier_b))
    print("Pixel queue populations:",dict(q_fam))
    print("Distinct comparison plates:",dict(plates))
    print("Distinct scans:",dict(scans))
    print("Distinct actual gaps (min):",dict(gaps))
    print("Temporal relations:",dict(relations))
    print()
    print("REPORT SHA256:",sha(REPORT))
    print("STAGE STATUS: COMPLETE")


if __name__=="__main__":
    main()
