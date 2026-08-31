#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
STAGE = AUTO / "stages" / "plan_ai43437_prevalence_v028ax.py"
BACKUP = AUTO / "backups" / "pre_v003"

STAGE_CONTENT = '#!/usr/bin/env python3\n"""\nORDER 01 — ai43437 prevalence coverage planner v028ax\n\nPurpose\n-------\nExpand v028aw from its tiny six-query local control sample into a deterministic\nplate-wide query plan WITHOUT making any network requests yet.\n\nThis stage:\n- reads the frozen DASCH native candidate catalogue;\n- reconstructs the six existing science-centred v028r query centres;\n- treats a conservative 300" radius around each as definitely covered;\n- identifies non-science native detections outside that covered union;\n- builds a deterministic greedy set-cover queue of additional 300" query centres;\n- writes both a science result artifact and an automation queue manifest.\n\nIt does NOT claim those future regions are already covered by DR7.\nIt does NOT classify uncatalogued prevalence beyond the existing cached regions.\n\nNO NETWORK ACCESS.\nSCIENCE PIXELS ARE NOT READ.\nNON-SCIENCE PIXELS ARE NOT READ.\nFrozen transient detector is NOT rerun.\nNo candidate state mutation.\n"""\n\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom collections import defaultdict\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\nQUEUES = AUTO / "queues"\n\nSTRICT = BASE / "order01_strict_match_triage_v028.csv"\nDASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"\nCLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"\nLOCAL = BASE / "order01_dasch_local_uncatalogued_stellar_prevalence_v028aw.json"\n\nOUT_JSON = BASE / "order01_dasch_ai43437_prevalence_coverage_plan_v028ax.json"\nOUT_CSV = BASE / "order01_dasch_ai43437_prevalence_query_queue_v028ax.csv"\nQUEUE_JSON = QUEUES / "ai43437_prevalence_v028ax.json"\nOUT_MD = BASE / "ORDER01_DASCH_AI43437_PREVALENCE_COVERAGE_PLAN_V028AX.md"\n\nRANKS = [10, 24, 25, 26, 29, 30]\nPLATE_ID = "ai43437"\nSAFE_RADIUS_ARCSEC = 300.0\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef f(v, default=None):\n    try:\n        if v is None or str(v).strip() == "":\n            return default\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef i(v, default=None):\n    try:\n        if v is None or str(v).strip() == "":\n            return default\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef angsep_arcsec(ra1, dec1, ra2, dec2):\n    r1, r2 = math.radians(ra1), math.radians(ra2)\n    d1, d2 = math.radians(dec1), math.radians(dec2)\n    c = (\n        math.sin(d1) * math.sin(d2)\n        + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)\n    )\n    c = max(-1.0, min(1.0, c))\n    return math.degrees(math.acos(c)) * 3600.0\n\n\ndef write_json(path, obj):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(\n        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n    tmp.replace(path)\n\n\ndef write_csv(path, rows, fields):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    with tmp.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(rows)\n    tmp.replace(path)\n\n\ndef tangent_xy(ra, dec, ra0, dec0):\n    # Accurate enough for local coverage indexing; final membership uses exact\n    # spherical angular separation.\n    x = (ra - ra0) * math.cos(math.radians(dec0)) * 3600.0\n    y = (dec - dec0) * 3600.0\n    return x, y\n\n\ndef build_neighbor_sets(rows, radius_arcsec):\n    if not rows:\n        return {}\n\n    ra0 = sum(r["ra_deg"] for r in rows) / len(rows)\n    dec0 = sum(r["dec_deg"] for r in rows) / len(rows)\n    cell = radius_arcsec\n\n    xy = {}\n    buckets = defaultdict(list)\n\n    for idx, r in enumerate(rows):\n        x, y = tangent_xy(r["ra_deg"], r["dec_deg"], ra0, dec0)\n        xy[idx] = (x, y)\n        key = (math.floor(x / cell), math.floor(y / cell))\n        buckets[key].append(idx)\n\n    neighbors = {}\n\n    for idx, r in enumerate(rows):\n        x, y = xy[idx]\n        cx, cy = math.floor(x / cell), math.floor(y / cell)\n        cand = []\n\n        for dx in (-1, 0, 1):\n            for dy in (-1, 0, 1):\n                cand.extend(buckets.get((cx + dx, cy + dy), []))\n\n        s = set()\n        for j in cand:\n            q = rows[j]\n            if angsep_arcsec(\n                r["ra_deg"], r["dec_deg"],\n                q["ra_deg"], q["dec_deg"]\n            ) <= radius_arcsec:\n                s.add(j)\n\n        neighbors[idx] = s\n\n    return neighbors\n\n\ndef greedy_cover(rows, radius_arcsec):\n    """\n    Deterministic greedy set cover using candidate positions themselves as\n    query centres. Tie-break order:\n      1. most currently-uncovered candidates covered\n      2. higher detector SNR\n      3. lower candidate index\n      4. lower row index\n    """\n    if not rows:\n        return []\n\n    neighbors = build_neighbor_sets(rows, radius_arcsec)\n    uncovered = set(range(len(rows)))\n    plan = []\n\n    while uncovered:\n        best_idx = None\n        best_cover = set()\n        best_key = None\n\n        for idx in sorted(uncovered):\n            covered = neighbors[idx] & uncovered\n            r = rows[idx]\n            key = (\n                len(covered),\n                f(r.get("snr"), -1e99),\n                -(i(r.get("candidate_index"), 10**12)),\n                -idx,\n            )\n\n            if best_key is None or key > best_key:\n                best_key = key\n                best_idx = idx\n                best_cover = covered\n\n        if best_idx is None or not best_cover:\n            raise RuntimeError("greedy coverage planner made no progress")\n\n        center = rows[best_idx]\n        plan.append({\n            "queue_order": len(plan) + 1,\n            "center_ra_deg": center["ra_deg"],\n            "center_dec_deg": center["dec_deg"],\n            "center_tile_id": center["tile_id"],\n            "center_candidate_index": center["candidate_index"],\n            "center_detector_snr": center["snr"],\n            "planned_safe_radius_arcsec": radius_arcsec,\n            "native_candidates_covered": len(best_cover),\n            "covered_row_indices": sorted(best_cover),\n        })\n\n        uncovered -= best_cover\n\n    return plan\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — ai43437 PREVALENCE COVERAGE PLANNER v028ax")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (STRICT, DASCH_NATIVE, CLOSURE, LOCAL):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))\n    if closure.get("new_active_unresolved_two_observatory_set") != []:\n        raise RuntimeError("Order01 closure guard mismatch")\n\n    strict_rows = read_csv(STRICT)\n    native_rows = read_csv(DASCH_NATIVE)\n\n    strict = {\n        i(r["strict_rank"]): r\n        for r in strict_rows\n        if i(r.get("strict_rank")) in RANKS\n    }\n    if sorted(strict) != RANKS:\n        raise RuntimeError("strict-rank set mismatch")\n\n    science_keys = set()\n    existing_centres = []\n\n    for rank in RANKS:\n        r = strict[rank]\n        pra, pdec = f(r.get("poss_ra_deg")), f(r.get("poss_dec_deg"))\n        dra, ddec = f(r.get("dasch_ra_deg")), f(r.get("dasch_dec_deg"))\n\n        if None in (pra, pdec, dra, ddec):\n            raise RuntimeError(f"#{rank}: missing frozen discovery coordinate")\n\n        existing_centres.append({\n            "rank": rank,\n            "ra_deg": (pra + dra) / 2.0,\n            "dec_deg": (pdec + ddec) / 2.0,\n            "safe_radius_arcsec": SAFE_RADIUS_ARCSEC,\n            "provenance": "existing_v028r_science_centred_query",\n        })\n\n        science_keys.add((\n            str(r.get("dasch_tile_id", "")),\n            i(r.get("dasch_candidate_index"))\n        ))\n\n    usable = []\n    skipped_bad_coord = 0\n\n    for r in native_rows:\n        ra, dec = f(r.get("ra_deg")), f(r.get("dec_deg"))\n        if ra is None or dec is None:\n            skipped_bad_coord += 1\n            continue\n\n        key = (\n            str(r.get("tile_id", "")),\n            i(r.get("candidate_index"))\n        )\n        is_science = key in science_keys\n\n        existing_sep = min(\n            angsep_arcsec(ra, dec, c["ra_deg"], c["dec_deg"])\n            for c in existing_centres\n        )\n        covered = existing_sep <= SAFE_RADIUS_ARCSEC\n\n        usable.append({\n            "tile_id": str(r.get("tile_id", "")),\n            "candidate_index": i(r.get("candidate_index")),\n            "ra_deg": ra,\n            "dec_deg": dec,\n            "snr": f(r.get("snr")),\n            "polarity": i(r.get("polarity")),\n            "is_science": is_science,\n            "existing_query_nearest_sep_arcsec": existing_sep,\n            "existing_query_covered": covered,\n        })\n\n    non_science = [r for r in usable if not r["is_science"]]\n    existing_covered = [r for r in non_science if r["existing_query_covered"]]\n    uncovered = [r for r in non_science if not r["existing_query_covered"]]\n\n    print(f"Frozen native DASCH rows with valid coordinates: {len(usable)}")\n    print(f"Non-science native rows:                       {len(non_science)}")\n    print(f"Already covered by six conservative 5\' discs: {len(existing_covered)}")\n    print(f"Outside existing conservative coverage:        {len(uncovered)}")\n\n    plan = greedy_cover(uncovered, SAFE_RADIUS_ARCSEC)\n\n    queue_rows = []\n    covered_total = 0\n    for item in plan:\n        covered_total += item["native_candidates_covered"]\n        queue_rows.append({\n            "queue_order": item["queue_order"],\n            "plate_id": PLATE_ID,\n            "solution": 0,\n            "refcat": "apass",\n            "center_ra_deg": item["center_ra_deg"],\n            "center_dec_deg": item["center_dec_deg"],\n            "safe_radius_arcsec": SAFE_RADIUS_ARCSEC,\n            "native_candidates_covered": item["native_candidates_covered"],\n            "cumulative_native_candidates_covered": covered_total,\n            "center_tile_id": item["center_tile_id"],\n            "center_candidate_index": item["center_candidate_index"],\n            "center_detector_snr": item["center_detector_snr"],\n            "network_status": "NOT_REQUESTED",\n            "science_status": "PLANNED_ONLY",\n        })\n\n    if covered_total != len(uncovered):\n        raise RuntimeError(\n            f"coverage accounting mismatch: plan covers {covered_total}, "\n            f"expected {len(uncovered)}"\n        )\n\n    print(f"Additional conservative query centres planned: {len(queue_rows)}")\n    if queue_rows:\n        counts = [r["native_candidates_covered"] for r in queue_rows]\n        print(\n            "Native detections per planned centre: "\n            f"median={sorted(counts)[len(counts)//2]} "\n            f"max={max(counts)}"\n        )\n\n    payload = {\n        "stage": "ORDER01_DASCH_AI43437_PREVALENCE_COVERAGE_PLAN_V028AX",\n        "plate_id": PLATE_ID,\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "coverage_model": {\n            "existing_query_count": len(existing_centres),\n            "safe_radial_coverage_arcsec": SAFE_RADIUS_ARCSEC,\n            "existing_queries_are_v028r_science_centred": True,\n            "full_cached_query_footprint_not_assumed": True,\n            "planned_centres_use_native_candidate_positions": True,\n            "greedy_set_cover": True,\n        },\n        "summary": {\n            "native_rows_total": len(native_rows),\n            "native_rows_valid_coordinate": len(usable),\n            "native_rows_bad_coordinate": skipped_bad_coord,\n            "science_rows_excluded": sum(r["is_science"] for r in usable),\n            "non_science_native_rows": len(non_science),\n            "already_conservatively_covered_non_science_rows": len(existing_covered),\n            "outside_existing_conservative_coverage_rows": len(uncovered),\n            "additional_query_centres_planned": len(queue_rows),\n            "planned_rows_covered": covered_total,\n        },\n        "existing_query_centres": existing_centres,\n        "planned_query_queue": queue_rows,\n        "interpretive_boundary": (\n            "v028ax is a coverage planner only. It does not make DR7 requests, "\n            "does not read pixels, and does not classify any newly planned region "\n            "as catalogued or uncatalogued. Its purpose is to convert the current "\n            "small cached prevalence sample into a deterministic expansion queue."\n        ),\n    }\n\n    queue_payload = {\n        "queue_id": "AI43437_PREVALENCE_V028AX",\n        "queue_version": 1,\n        "plate_id": PLATE_ID,\n        "status": "PLANNED_NOT_FETCHED",\n        "safe_radius_arcsec": SAFE_RADIUS_ARCSEC,\n        "items": queue_rows,\n        "guards": {\n            "created_without_network": True,\n            "candidate_state_mutation": False,\n        },\n    }\n\n    write_json(OUT_JSON, payload)\n    write_json(QUEUE_JSON, queue_payload)\n\n    fields = [\n        "queue_order", "plate_id", "solution", "refcat",\n        "center_ra_deg", "center_dec_deg", "safe_radius_arcsec",\n        "native_candidates_covered",\n        "cumulative_native_candidates_covered",\n        "center_tile_id", "center_candidate_index",\n        "center_detector_snr", "network_status", "science_status",\n    ]\n    write_csv(OUT_CSV, queue_rows, fields)\n\n    md = [\n        "# ORDER 01 — ai43437 Prevalence Coverage Plan v028ax",\n        "",\n        "## Guard state",\n        "",\n        "- No network access.",\n        "- Science pixels were not read.",\n        "- Non-science pixels were not read.",\n        "- The frozen detector was not rerun.",\n        "- No candidate state was changed.",\n        "",\n        "## Coverage summary",\n        "",\n        f"- Valid-coordinate frozen native rows: **{len(usable)}**.",\n        f"- Non-science rows: **{len(non_science)}**.",\n        f"- Already inside conservative existing 5′ coverage: **{len(existing_covered)}**.",\n        f"- Outside existing conservative coverage: **{len(uncovered)}**.",\n        f"- Additional planned query centres: **{len(queue_rows)}**.",\n        "",\n        "## Interpretation boundary",\n        "",\n        payload["interpretive_boundary"],\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {QUEUE_JSON}")\n    print(f"  {OUT_MD}")\n    print()\n    print("NO network query was made.")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE NOT READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_prevalence_coverage_plan_v028ax",
        title="ai43437 prevalence coverage expansion planner",
        script="automation/stages/plan_ai43437_prevalence_v028ax.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_local_uncatalogued_stellar_prevalence_v028aw.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
            "results/order01_native_full_v028/order01_strict_match_triage_v028.csv",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_ai43437_prevalence_coverage_plan_v028ax.json",
            "automation/queues/ai43437_prevalence_v028ax.json",
        ),
        dependencies=("dasch_local_prevalence_v028aw",),
        notes="Planning-only stage; expands cached prevalence coverage without network or pixel reads.",
    ),
"""

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.0.3 — FIRST NEW SCIENCE WORKLOAD")
    print("="*112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("No existing science/result artifact is modified.")
    print("No candidate state is changed.\n")

    if not REGISTRY.is_file():
        print(f"FAIL missing registry: {REGISTRY}")
        return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    reg_backup = BACKUP / "registry_order01.py"
    if not reg_backup.exists():
        shutil.copy2(REGISTRY, reg_backup)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    if STAGE.exists():
        print(f"FAIL stage already exists: {STAGE}")
        return 2
    STAGE.write_text(STAGE_CONTENT, encoding="utf-8")
    print(f"Created: {STAGE.relative_to(ROOT)}")

    reg = REGISTRY.read_text(encoding="utf-8")
    if 'stage_id="dasch_prevalence_coverage_plan_v028ax"' in reg:
        print("FAIL registry already contains v028ax")
        return 2

    marker = "\n]\n\ndef by_id():"
    if marker not in reg:
        print("FAIL registry insertion marker not found; refusing broad edit.")
        return 3

    reg = reg.replace(
        marker,
        "\n" + REGISTRY_ENTRY.rstrip() + "\n]\n\ndef by_id():",
        1,
    )
    REGISTRY.write_text(reg, encoding="utf-8")
    print("Registered: dasch_prevalence_coverage_plan_v028ax")

    init = AUTO / "__init__.py"
    init.write_text('__version__ = "0.0.3"\n', encoding="utf-8")

    failures = []
    py_files = sorted(
        p for p in AUTO.rglob("*.py")
        if "backups" not in p.parts
    )

    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\nAUTOMATION UPGRADE STATUS: FAIL")
        return 4

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_prevalence_coverage_plan_v028ax')
    print("\nThe first run-next should now execute v028ax automatically.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
