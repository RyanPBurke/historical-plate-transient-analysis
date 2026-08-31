from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import math
import re

import astropy.units as u
from astropy.coordinates import SkyCoord

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_branch_c_candidate462_recurrence_v028"
CHECKPOINT = WORK / "plate_summaries"
for d in (WORK, CHECKPOINT):
    d.mkdir(parents=True, exist_ok=True)

VALIDATION = BASE / "order61_branch_c_candidate462_validation_v028.json"
PP_MODULE = ROOT / "tools" / "preflight_order61_platephot_recurrence_v028b.py"

OUT_REPORT = BASE / "order61_branch_c_candidate462_recurrence256_v028.json"
OUT_POLICY = BASE / "order61_branch_c_candidate462_recurrence256_policy_v028.json"
OUT_MANIFEST = BASE / "order61_branch_c_candidate462_recurrence256_manifest_v028.csv"
OUT_DETAIL = BASE / "order61_branch_c_candidate462_recurrence256_detail_v028.csv"
OUT_DISCOVERY = BASE / "order61_branch_c_candidate462_ai44092_platephot_context_v028.csv"

TARGET_RA = 333.721056004192
TARGET_DEC = 11.318959906276355
TARGET_LABEL = "order61_branchc20_dasch_candidate462"
DISCOVERY_PLATE = "ai44092"
SYNTH_RANK = 4620

# Prospectively fixed before any recurrence platephot result is inspected.
PREFIX = 256
SELECTION_SALT = "order61-branchc20-c462-recurrence-v028-sha256-blind"
STRONG_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
LOCAL_DENSITY_ARCSEC = 60.0
MIN_INDEPENDENT_PLATES_FOR_RECURRENCE = 2

MANIFEST_FIELDS = [
    "prefix", "selection_hash", "plate_id", "solution_number", "refcat",
    "target_ra_deg", "target_dec_deg",
]
DETAIL_FIELDS = [
    "prefix", "plate_id", "solution_number", "refcat", "status",
    "source_rows", "sources_within_60arcsec", "sources_within_5arcsec",
    "sources_within_3arcsec", "nearest_source_arcsec",
    "nearest_source_ra_deg", "nearest_source_dec_deg",
]
DISCOVERY_FIELDS = [
    "plate_id", "solution_number", "refcat", "status", "source_rows",
    "sources_within_60arcsec", "sources_within_5arcsec",
    "sources_within_3arcsec", "nearest_source_arcsec",
]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(path)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    return sha256_bytes(path.read_bytes())


def normkey(x):
    return re.sub(r"[^a-z0-9]", "", str(x).strip().lower())


def ffloat(v):
    if v is None:
        return None
    try:
        x = float(str(v).strip())
    except Exception:
        return None
    return x if math.isfinite(x) else None


def pick_numeric(row, aliases):
    nr = {normkey(k): v for k, v in row.items()}
    for a in aliases:
        x = ffloat(nr.get(normkey(a)))
        if x is not None:
            return x
    return None


def summarize_platephot(rows):
    target = SkyCoord(TARGET_RA*u.deg, TARGET_DEC*u.deg, frame="icrs")
    sources = []
    for r in rows:
        ra = pick_numeric(r, ["radeg", "ra", "ra_deg"])
        dec = pick_numeric(r, ["decdeg", "dec", "dec_deg"])
        if ra is None or dec is None:
            continue
        c = SkyCoord(ra*u.deg, dec*u.deg, frame="icrs")
        sep = float(c.separation(target).arcsec)
        sources.append((sep, ra, dec))

    sources.sort(key=lambda q: q[0])
    n60 = sum(s <= LOCAL_DENSITY_ARCSEC for s, _, _ in sources)
    n5 = sum(s <= DIAGNOSTIC_ARCSEC for s, _, _ in sources)
    n3 = sum(s <= STRONG_ARCSEC for s, _, _ in sources)
    nearest = sources[0] if sources else None
    return {
        "source_rows": len(sources),
        "sources_within_60arcsec": n60,
        "sources_within_5arcsec": n5,
        "sources_within_3arcsec": n3,
        "nearest_source_arcsec": None if nearest is None else nearest[0],
        "nearest_source_ra_deg": None if nearest is None else nearest[1],
        "nearest_source_dec_deg": None if nearest is None else nearest[2],
    }


def selection_hash(plate_id, solnum, refcat):
    s = f"{SELECTION_SALT}|{TARGET_LABEL}|{plate_id}|{int(solnum)}|{refcat}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def checkpoint_path(prefix, plate_id, solnum, refcat):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{prefix:04d}_{plate_id}_s{solnum}_{refcat}")
    return CHECKPOINT / f"{safe}.json"


def main():
    print("="*108)
    print("ORDER 61 — BRANCH C #20 / CANDIDATE 462 INDEPENDENT-PLATE RECURRENCE 256 v028")
    print("="*108)
    print("256 blind SHA256-selected physical DASCH plates; ai44092 excluded from recurrence evidence.")
    print("No detector. No science image pixels. Spatial gates remain 3/5 arcsec; local density 60 arcsec.")
    print()

    for p in (VALIDATION, PP_MODULE):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    guards = {
        "validation_complete": validation.get("status") == "COMPLETE",
        "validation_disposition": validation.get("disposition") == "BRANCH_C_20_NEW_COUNTERPART_SURVIVES_STATIC_AND_MATCHED_PEER_MORPHOLOGY",
        "validation_no_detector": validation.get("detector_rerun") is False,
        "target_index": int(validation.get("new_dasch_counterpart",{}).get("candidate_index",-1)) == 462,
        "target_ra": abs(float(validation.get("new_dasch_counterpart",{}).get("ra_deg",0))-TARGET_RA) < 1e-10,
        "target_dec": abs(float(validation.get("new_dasch_counterpart",{}).get("dec_deg",0))-TARGET_DEC) < 1e-10,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: "+repr(guards))

    pp = load_module(PP_MODULE, "order61_platephot_preflight_v028b")

    print("Completed-stage guards: PASS")
    print("[1/4] Enumerating official DASCH exposure list at candidate-462 sky locus ...", flush=True)
    raw_exps, exp_header, exp_status = pp.queryexps(SYNTH_RANK, TARGET_RA, TARGET_DEC)
    parsed = [pp.parse_exposure(SYNTH_RANK, TARGET_RA, TARGET_DEC, r) for r in raw_exps]

    eligible = [
        e for e in parsed
        if bool(e.get("eligible_independent_platephot"))
        and str(e.get("plate_id") or "").strip()
        and str(e.get("plate_id") or "").lower() != DISCOVERY_PLATE
        and e.get("selected_refcat_for_platephot") is not None
    ]

    # One exposure/calibration per physical plate, chosen deterministically and
    # without dates, limiting magnitude, morphology, source density, or outcomes.
    per_plate = {}
    for e in eligible:
        plate = str(e["plate_id"])
        cand = (
            int(e["solnum"]),
            str(e["selected_refcat_for_platephot"]),
            e,
        )
        if plate not in per_plate or cand[:2] < per_plate[plate][:2]:
            per_plate[plate] = cand

    unique = []
    for plate, (solnum, refcat, e) in per_plate.items():
        unique.append({
            "plate_id": plate,
            "solution_number": solnum,
            "refcat": refcat,
            "selection_hash": selection_hash(plate, solnum, refcat),
        })
    unique.sort(key=lambda r: (r["selection_hash"], r["plate_id"], r["solution_number"], r["refcat"]))

    if len(unique) < PREFIX:
        raise RuntimeError(f"REFUSING: only {len(unique)} eligible independent physical plates; need {PREFIX}")

    manifest = []
    for i, r in enumerate(unique[:PREFIX], 1):
        manifest.append({
            "prefix": i,
            **r,
            "target_ra_deg": TARGET_RA,
            "target_dec_deg": TARGET_DEC,
        })

    # Freeze manifest and policy before any discovery-plate context or recurrence API request.
    write_csv(OUT_MANIFEST, manifest, MANIFEST_FIELDS)
    manifest_sha = sha256_file(OUT_MANIFEST)
    policy = {
        "analysis_kind": "order61_branch_c_candidate462_recurrence256_fixed_v028",
        "target_label": TARGET_LABEL,
        "target_ra_deg": TARGET_RA,
        "target_dec_deg": TARGET_DEC,
        "discovery_plate_excluded": DISCOVERY_PLATE,
        "plates_selected": PREFIX,
        "selection_salt": SELECTION_SALT,
        "selection_rule": "one eligible exposure per physical plate by lexicographic (solnum,refcat), then ascending SHA256(salt|target|plate|solnum|refcat); prefix 256",
        "selection_uses_exposure_date": False,
        "selection_uses_limiting_magnitude": False,
        "selection_uses_morphology": False,
        "selection_uses_source_density": False,
        "selection_uses_candidate_outcomes": False,
        "strong_arcsec": STRONG_ARCSEC,
        "diagnostic_arcsec": DIAGNOSTIC_ARCSEC,
        "local_density_radius_arcsec": LOCAL_DENSITY_ARCSEC,
        "minimum_independent_recurrence_plates": MIN_INDEPENDENT_PLATES_FOR_RECURRENCE,
        "manifest_sha256": manifest_sha,
        "transport": "preflight_order61_platephot_recurrence_v028b helper / verified HTTPS",
        "detector_rerun": False,
    }
    write_json(OUT_POLICY, policy)
    policy_sha = sha256_file(OUT_POLICY)

    print(f"  queryexps status={exp_status} total={len(parsed)} eligible exposures={len(eligible)} unique physical plates={len(unique)}")
    print(f"  manifest frozen: {PREFIX} rows SHA={manifest_sha}")
    print(f"  policy SHA:      {policy_sha}")
    print("  Manifest/policy frozen before first platephot request: PASS")
    print()

    # Discovery-plate conventional extractor context, explicitly excluded from recurrence.
    print("[2/4] Auditing ai44092 conventional platephot context at candidate 462 ...", flush=True)
    pair_exps = [e for e in parsed if str(e.get("plate_id") or "").lower() == DISCOVERY_PLATE and bool(e.get("has_imaging"))]
    discovery_rows = []
    seen = set()
    for e in pair_exps:
        refcats = []
        if int(e.get("nSolutionsApass") or 0) > 0 or str(e.get("resultIdApass") or "").strip():
            refcats.append("apass")
        if int(e.get("nSolutionsAtlas") or 0) > 0 or str(e.get("resultIdAtlas") or "").strip():
            refcats.append("atlas")
        for refcat in refcats:
            key = (int(e["solnum"]), refcat)
            if key in seen:
                continue
            seen.add(key)
            rows, header, status = pp.platephot(SYNTH_RANK, DISCOVERY_PLATE, int(e["solnum"]), refcat, TARGET_RA, TARGET_DEC)
            sm = summarize_platephot(rows)
            discovery_rows.append({
                "plate_id": DISCOVERY_PLATE,
                "solution_number": int(e["solnum"]),
                "refcat": refcat,
                "status": status,
                **sm,
            })
            print(f"  ai44092 sol={int(e['solnum'])} {refcat}: n60={sm['sources_within_60arcsec']} <=5={sm['sources_within_5arcsec']} <=3={sm['sources_within_3arcsec']} nearest={sm['nearest_source_arcsec']}")
    write_csv(OUT_DISCOVERY, discovery_rows, DISCOVERY_FIELDS)
    print()

    print("[3/4] Running frozen 256-plate recurrence sample ...", flush=True)
    detail = []
    failures = []
    for i, mr in enumerate(manifest, 1):
        plate = mr["plate_id"]
        solnum = int(mr["solution_number"])
        refcat = mr["refcat"]
        cp = checkpoint_path(i, plate, solnum, refcat)

        if cp.is_file():
            obj = json.loads(cp.read_text(encoding="utf-8"))
            if (
                obj.get("manifest_sha256") == manifest_sha
                and obj.get("plate_id") == plate
                and int(obj.get("solution_number", -1)) == solnum
                and obj.get("refcat") == refcat
            ):
                row = obj["summary"]
                status_word = "CACHED"
                detail.append(row)
                near = row["nearest_source_arcsec"]
                ntxt = "None" if near is None else f"{near:.2f}\""
                print(f"  [{i:03d}/{PREFIX}] {plate:10s} {status_word:6s} n60={row['sources_within_60arcsec']:3d} <=5={row['sources_within_5arcsec']} <=3={row['sources_within_3arcsec']} nearest={ntxt}", flush=True)
                continue

        try:
            rows, header, api_status = pp.platephot(SYNTH_RANK, plate, solnum, refcat, TARGET_RA, TARGET_DEC)
            sm = summarize_platephot(rows)
            row = {
                "prefix": i,
                "plate_id": plate,
                "solution_number": solnum,
                "refcat": refcat,
                "status": api_status,
                **sm,
            }
            write_json(cp, {
                "manifest_sha256": manifest_sha,
                "policy_sha256": policy_sha,
                "plate_id": plate,
                "solution_number": solnum,
                "refcat": refcat,
                "summary": row,
            })
            detail.append(row)
            status_word = str(api_status).upper()[:6]
            near = row["nearest_source_arcsec"]
            ntxt = "None" if near is None else f"{near:.2f}\""
            print(f"  [{i:03d}/{PREFIX}] {plate:10s} {status_word:6s} n60={row['sources_within_60arcsec']:3d} <=5={row['sources_within_5arcsec']} <=3={row['sources_within_3arcsec']} nearest={ntxt}", flush=True)
        except Exception as exc:
            failures.append({"prefix":i,"plate_id":plate,"solution_number":solnum,"refcat":refcat,"error":repr(exc)})
            print(f"  [{i:03d}/{PREFIX}] {plate:10s} FAILED {exc}", flush=True)

    write_csv(OUT_DETAIL, detail, DETAIL_FIELDS)

    print()
    print("[4/4] Recurrence summary ...")
    completed = len(detail)
    plates3 = sum(int(r["sources_within_3arcsec"]) > 0 for r in detail)
    plates5 = sum(int(r["sources_within_5arcsec"]) > 0 for r in detail)
    src3 = sum(int(r["sources_within_3arcsec"]) for r in detail)
    src5 = sum(int(r["sources_within_5arcsec"]) for r in detail)
    src60 = sum(int(r["sources_within_60arcsec"]) for r in detail)

    expected3 = src60 * (STRONG_ARCSEC/LOCAL_DENSITY_ARCSEC)**2
    expected5 = src60 * (DIAGNOSTIC_ARCSEC/LOCAL_DENSITY_ARCSEC)**2

    recurrent3 = plates3 >= MIN_INDEPENDENT_PLATES_FOR_RECURRENCE
    recurrent5 = plates5 >= MIN_INDEPENDENT_PLATES_FOR_RECURRENCE

    if failures:
        disposition = "INCOMPLETE_RECURRENCE_SAMPLE_FAILURES_PRESENT"
    elif recurrent5:
        disposition = "HISTORICAL_RECURRENCE_STATIC_CONTAMINATION_AT_PREDECLARED_5ARCSEC_GATE"
    elif plates5 == 1:
        disposition = "SINGLE_INDEPENDENT_PLATE_5ARCSEC_MATCH_RECURRENCE_NOT_ESTABLISHED"
    else:
        disposition = "NO_RECURRENCE_IN_256_BLIND_INDEPENDENT_PLATES"

    upper95 = 1.0 - 0.05**(1.0/completed) if completed > 0 and plates5 == 0 else None

    print(f"  selected/completed/failed: {PREFIX}/{completed}/{len(failures)}")
    print(f"  sources within 60\": {src60}")
    print(f"  <=3\": sources={src3} plates={plates3} expected chance~{expected3:.4f} recurrent={recurrent3}")
    print(f"  <=5\": sources={src5} plates={plates5} expected chance~{expected5:.4f} recurrent={recurrent5}")
    if upper95 is not None:
        print(f"  contextual 0/{completed} one-sided 95% upper recurrence probability: {upper95:.5f}")
    print("  disposition:", disposition)

    report = {
        "status": "COMPLETE" if not failures and completed == PREFIX else "INCOMPLETE",
        "analysis_kind": "order61_branch_c_candidate462_recurrence256_v028",
        "guards": guards,
        "target": {"ra_deg":TARGET_RA,"dec_deg":TARGET_DEC,"candidate_index":462,"discovery_plate":DISCOVERY_PLATE},
        "queryexps": {"status":exp_status,"total_exposures":len(parsed),"eligible_exposures":len(eligible),"unique_independent_physical_plates":len(unique)},
        "fixed_policy": policy,
        "policy_sha256": policy_sha,
        "manifest_sha256": manifest_sha,
        "discovery_plate_context": discovery_rows,
        "summary": {
            "selected_plates": PREFIX,
            "completed_plates": completed,
            "failed_plates": len(failures),
            "total_sources_within_60arcsec": src60,
            "observed_sources_within_3arcsec": src3,
            "observed_sources_within_5arcsec": src5,
            "plates_with_source_within_3arcsec": plates3,
            "plates_with_source_within_5arcsec": plates5,
            "expected_chance_within_3_from_local60": expected3,
            "expected_chance_within_5_from_local60": expected5,
            "multi_independent_plate_recurrence_3arcsec": recurrent3,
            "multi_independent_plate_recurrence_5arcsec": recurrent5,
            "contextual_zero_recurrence_one_sided_95_upper": upper95,
            "disposition": disposition,
        },
        "failures": failures,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "If recurrence/static contamination is established, retire candidate 462 as the Branch-C counterpart. "
            "If 256 independent plates remain recurrence-clean, run a footprint-conditioned independent geometry-control family before any escalation to 1024 recurrence plates or orbital interpretation."
        ),
        "outputs": {
            "policy_json": str(OUT_POLICY),
            "manifest_csv": str(OUT_MANIFEST),
            "detail_csv": str(OUT_DETAIL),
            "discovery_plate_context_csv": str(OUT_DISCOVERY),
        },
    }
    write_json(OUT_REPORT, report)

    print()
    print("="*108)
    print("CANDIDATE 462 RECURRENCE-256 COMPLETE" if report["status"] == "COMPLETE" else "CANDIDATE 462 RECURRENCE-256 INCOMPLETE")
    print("="*108)
    print("Output:", OUT_REPORT)
    print("Manifest:", OUT_MANIFEST)
    print("Detail:  ", OUT_DETAIL)
    print("Discovery plate context:", OUT_DISCOVERY)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
