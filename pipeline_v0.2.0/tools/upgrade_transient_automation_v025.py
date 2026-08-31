#!/usr/bin/env python3
from __future__ import annotations

import ast
import py_compile
import re
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
INIT = AUTO / "__init__.py"
BU = AUTO / "stages" / "interpret_matched_recurrence_phase1_v028bu.py"
BV = AUTO / "stages" / "plan_matched_recurrence_256_v028bv.py"
BACKUP = AUTO / "backups" / "pre_v025"
BU_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom collections import defaultdict\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nBT = BASE / "order01_dasch_matched_recurrence_phase1_v028bt.json"\n\nOUT_JSON = BASE / "order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json"\nOUT_CSV = BASE / "order01_dasch_matched_recurrence_phase1_close_hits_v028bu.csv"\nOUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_INTERPRETATION_V028BU.md"\n\nTARGETS = ("science25", "q0030", "q0344")\nRADII = (3.0, 5.0, 10.0)\nEXPECTED_REQUESTS = 192\nEXPECTED_EXPOSURES = 64\n\n\ndef f(v, default=None):\n    try:\n        x = float(v)\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef scalarize_raw(raw):\n    if not isinstance(raw, dict):\n        return {}\n    out = {}\n    for k, v in raw.items():\n        if isinstance(v, (str, int, float, bool)) or v is None:\n            out[str(k)] = v\n    return out\n\n\ndef first(raw, *keys):\n    for k in keys:\n        if k in raw and raw[k] not in ("", None):\n            return raw[k]\n    return None\n\n\ndef bucket(sep):\n    if sep is None:\n        return "NO_POSITIONED_ROW"\n    if sep <= 3.0:\n        return "LE_3_ARCSEC"\n    if sep <= 5.0:\n        return "GT3_LE5_ARCSEC"\n    if sep <= 10.0:\n        return "GT5_LE10_ARCSEC"\n    return "GT10_ARCSEC"\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MATCHED RECURRENCE PHASE 1 INTERPRETATION v028bu")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("NO PIXELS ARE READ.")\n    print("Frozen transient detector is NOT rerun.")\n    print("No candidate state is changed.\\n")\n\n    if not BT.is_file():\n        print(f"FAIL missing input: {BT}")\n        return 2\n\n    bt = json.loads(BT.read_text(encoding="utf-8"))\n    results = bt.get("results", [])\n    if len(results) != EXPECTED_REQUESTS:\n        print(f"FAIL expected {EXPECTED_REQUESTS} results, got {len(results)}")\n        return 3\n    if int(bt.get("completed_matched_exposures", -1)) != EXPECTED_EXPOSURES:\n        print(\n            f"FAIL expected {EXPECTED_EXPOSURES} matched exposures, "\n            f"got {bt.get(\'completed_matched_exposures\')}"\n        )\n        return 3\n\n    by_eid = defaultdict(dict)\n    for r in results:\n        by_eid[r["exposure_identity"]][r["target"]] = r\n\n    for eid, group in by_eid.items():\n        if set(group) != set(TARGETS):\n            print(f"FAIL matched group {eid} target set={sorted(group)}")\n            return 3\n\n    target_summary = {}\n    close_hits = []\n    for target in TARGETS:\n        rr = [r for r in results if r["target"] == target]\n        bins = {\n            "LE_3_ARCSEC": 0,\n            "GT3_LE5_ARCSEC": 0,\n            "GT5_LE10_ARCSEC": 0,\n            "GT10_ARCSEC": 0,\n            "NO_POSITIONED_ROW": 0,\n        }\n        for r in rr:\n            sep = f(r.get("nearest_sep_arcsec"))\n            b = bucket(sep)\n            bins[b] += 1\n            if sep is not None and sep <= 10.0:\n                raw = scalarize_raw(r.get("nearest_raw_row"))\n                matched = by_eid[r["exposure_identity"]]\n                rec = {\n                    "target": target,\n                    "bucket": b,\n                    "nearest_sep_arcsec": sep,\n                    "plate_id": r.get("plate_id"),\n                    "solution_number": r.get("solution_number"),\n                    "refcat": r.get("refcat"),\n                    "exposure_identity": r.get("exposure_identity"),\n                    "obs_date_jd": f(r.get("obs_date_jd")),\n                    "obs_date_iso": r.get("obs_date_iso"),\n                    "response_row_count": r.get("response_row_count"),\n                    "science25_same_exposure_nearest_arcsec": f(\n                        matched["science25"].get("nearest_sep_arcsec")\n                    ),\n                    "q0030_same_exposure_nearest_arcsec": f(\n                        matched["q0030"].get("nearest_sep_arcsec")\n                    ),\n                    "q0344_same_exposure_nearest_arcsec": f(\n                        matched["q0344"].get("nearest_sep_arcsec")\n                    ),\n                    "nearest_mag": first(\n                        raw,\n                        "magcalMagdep", "magcal_magdep",\n                        "magcalLocal", "magcal_local",\n                        "mag", "magnitude",\n                    ),\n                    "nearest_limiting_mag": first(\n                        raw, "limitingMagLocal", "limiting_mag_local"\n                    ),\n                    "nearest_aflags": first(raw, "aflags", "aFlags"),\n                    "nearest_bflags": first(raw, "bflags", "bFlags"),\n                    "nearest_series": first(raw, "series", "Series"),\n                    "nearest_platenum": first(raw, "platenum", "plateNum", "plate_num"),\n                    "nearest_solnum": first(raw, "solnum", "solNum"),\n                    "nearest_expnum": first(raw, "expnum", "expNum"),\n                    "nearest_ra_deg": f(first(raw, "raDeg", "ra_deg", "ra")),\n                    "nearest_dec_deg": f(first(raw, "decDeg", "dec_deg", "dec")),\n                    "nearest_raw_row": raw,\n                }\n                close_hits.append(rec)\n\n        target_summary[target] = {\n            "requests": len(rr),\n            "bins": bins,\n            "le_3_arcsec": bins["LE_3_ARCSEC"],\n            "le_5_arcsec": bins["LE_3_ARCSEC"] + bins["GT3_LE5_ARCSEC"],\n            "le_10_arcsec": (\n                bins["LE_3_ARCSEC"]\n                + bins["GT3_LE5_ARCSEC"]\n                + bins["GT5_LE10_ARCSEC"]\n            ),\n        }\n\n    close_hits.sort(\n        key=lambda r: (\n            r["nearest_sep_arcsec"],\n            r["target"],\n            r["exposure_identity"],\n        )\n    )\n\n    clean_recurrences = [r for r in close_hits if r["nearest_sep_arcsec"] <= 5.0]\n    loose_hits = [\n        r for r in close_hits if 5.0 < r["nearest_sep_arcsec"] <= 10.0\n    ]\n\n    # Regression against the observed phase-1 summary; this intentionally\n    # fails loudly if a future overwritten bt JSON differs.\n    if target_summary["science25"]["le_3_arcsec"] != 0:\n        print("FAIL regression: science25 <=3 count changed")\n        return 4\n    if target_summary["science25"]["le_5_arcsec"] != 0:\n        print("FAIL regression: science25 <=5 count changed")\n        return 4\n    if target_summary["science25"]["le_10_arcsec"] != 1:\n        print("FAIL regression: science25 <=10 count changed")\n        return 4\n    if target_summary["q0030"]["le_10_arcsec"] != 0:\n        print("FAIL regression: q0030 <=10 count changed")\n        return 4\n    if target_summary["q0344"]["le_10_arcsec"] != 0:\n        print("FAIL regression: q0344 <=10 count changed")\n        return 4\n\n    print("PHASE 1 RECURRENCE BINS")\n    for target in TARGETS:\n        s = target_summary[target]\n        print(\n            f"  {target}: n={s[\'requests\']} "\n            f"<=3\\"={s[\'le_3_arcsec\']} "\n            f"<=5\\"={s[\'le_5_arcsec\']} "\n            f"<=10\\"={s[\'le_10_arcsec\']}"\n        )\n\n    print(f"\\nClean <=5\\" recurrence hits: {len(clean_recurrences)}")\n    print(f"Loose 5-10\\" hits: {len(loose_hits)}")\n\n    for idx, hit in enumerate(close_hits, 1):\n        print(f"\\nCLOSE HIT {idx}/{len(close_hits)}")\n        print(\n            f"  target={hit[\'target\']} bucket={hit[\'bucket\']} "\n            f"sep={hit[\'nearest_sep_arcsec\']:.6f}\\""\n        )\n        print(\n            f"  plate={hit[\'plate_id\']} sol={hit[\'solution_number\']} "\n            f"refcat={hit[\'refcat\']} date={hit[\'obs_date_iso\'] or hit[\'obs_date_jd\']}"\n        )\n        print(\n            "  same exposure nearest: "\n            f"#25={hit[\'science25_same_exposure_nearest_arcsec\']}\\" "\n            f"q0030={hit[\'q0030_same_exposure_nearest_arcsec\']}\\" "\n            f"q0344={hit[\'q0344_same_exposure_nearest_arcsec\']}\\""\n        )\n        print(\n            f"  fitted mag={hit[\'nearest_mag\']} "\n            f"limMag={hit[\'nearest_limiting_mag\']} "\n            f"aflags={hit[\'nearest_aflags\']} bflags={hit[\'nearest_bflags\']}"\n        )\n        print(\n            f"  raw nearest-row keys={sorted(hit[\'nearest_raw_row\'].keys())}"\n        )\n\n    if clean_recurrences:\n        classification = "AT_LEAST_ONE_CLEAN_LE5_MATCH_REQUIRES_ADJUDICATION"\n    elif loose_hits:\n        classification = (\n            "NO_CLEAN_LE5_RECURRENCE_SINGLE_LOOSE_5_TO_10_ARCSEC_SCIENCE_HIT"\n        )\n    else:\n        classification = "NO_LE10_MATCHED_RECURRENCE_IN_PHASE1"\n\n    print(f"\\nPHASE 1 INTERPRETATION CLASS: {classification}")\n\n    flat = []\n    for h in close_hits:\n        x = {k: v for k, v in h.items() if k != "nearest_raw_row"}\n        for k, v in h["nearest_raw_row"].items():\n            x[f"raw_{k}"] = v\n        flat.append(x)\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = sorted({k for r in flat for k in r}) if flat else [\n            "target", "nearest_sep_arcsec", "plate_id"\n        ]\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(flat)\n\n    payload = {\n        "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_INTERPRETATION_V028BU",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "target_summary": target_summary,\n        "close_hits_le_10arcsec": close_hits,\n        "clean_hits_le_5arcsec": clean_recurrences,\n        "loose_hits_gt5_le10arcsec": loose_hits,\n        "phase1_interpretation_class": classification,\n        "interpretive_boundary": (\n            "A 5-10 arcsec fitted-source association is a loose historical match, "\n            "not a clean accepted recurrence. No accepted recurrence is created "\n            "without separate astrometric/source-quality adjudication. Phase 1 "\n            "is only 64 matched exposures and is not a complete recurrence census."\n        ),\n        "next_gate": {\n            "matched_recurrence_expansion_to_256_may_be_planned": True,\n        },\n    }\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — Matched Recurrence Phase 1 Interpretation v028bu",\n        "",\n        f"**Classification:** `{classification}`",\n        "",\n        "| target | ≤3″ | ≤5″ | ≤10″ |",\n        "|---|---:|---:|---:|",\n    ]\n    for target in TARGETS:\n        s = target_summary[target]\n        md.append(\n            f"| {target} | {s[\'le_3_arcsec\']} | "\n            f"{s[\'le_5_arcsec\']} | {s[\'le_10_arcsec\']} |"\n        )\n    md += [\n        "",\n        f"- Clean ≤5″ hits: **{len(clean_recurrences)}**.",\n        f"- Loose 5–10″ hits: **{len(loose_hits)}**.",\n        "",\n        "The 5–10″ bucket is not treated as an accepted recurrence.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
BV_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport json\nfrom pathlib import Path\n\nfrom automation.stages.plan_matched_recurrence_v028bs import (\n    TARGETS,\n    DISCOVERY_PLATE,\n    parse_obs_date,\n    farthest_rank_indices,\n)\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nINV = BASE / "order01_dasch_science25_analogue_exposure_inventory_v028br.json"\nBS = BASE / "order01_dasch_matched_recurrence_plan_v028bs.json"\nBU = BASE / "order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json"\n\nOUT_JSON = BASE / "order01_dasch_matched_recurrence_256_plan_v028bv.json"\nOUT_CSV = BASE / "order01_dasch_matched_recurrence_phase2_queue_v028bv.csv"\nOUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_256_PLAN_V028BV.md"\n\nCUMULATIVE_EXPOSURES = 256\nPHASE1_EXPOSURES = 64\nNEW_EXPOSURES = CUMULATIVE_EXPOSURES - PHASE1_EXPOSURES\nEXPECTED_NEW_REQUESTS = NEW_EXPOSURES * len(TARGETS)\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MATCHED RECURRENCE 256-EXPOSURE EXPANSION PLAN v028bv")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("NO PIXELS ARE READ.")\n    print("No platephot requests are made.")\n    print("No candidate state is changed.\\n")\n\n    for p in (INV, BS, BU):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    inv = json.loads(INV.read_text(encoding="utf-8"))\n    bs = json.loads(BS.read_text(encoding="utf-8"))\n    bu = json.loads(BU.read_text(encoding="utf-8"))\n\n    if not bu.get("next_gate", {}).get(\n        "matched_recurrence_expansion_to_256_may_be_planned"\n    ):\n        print("FAIL v028bu expansion gate not enabled")\n        return 3\n\n    by_target = inv["by_target"]\n    coords = {\n        t["target"]: (float(t["ra_deg"]), float(t["dec_deg"]))\n        for t in inv["targets"]\n    }\n    maps = {\n        target: {\n            r["exposure_identity"]: r\n            for r in by_target[target]["rows"]\n            if r.get("has_imaging")\n        }\n        for target in TARGETS\n    }\n\n    shared = set(maps[TARGETS[0]])\n    for target in TARGETS[1:]:\n        shared &= set(maps[target])\n\n    eligible = []\n    for eid in sorted(shared):\n        rows = {t: maps[t][eid] for t in TARGETS}\n        if any(r.get("plate_id") == DISCOVERY_PLATE for r in rows.values()):\n            continue\n\n        common = {"apass", "atlas"}\n        for r in rows.values():\n            common &= set(r.get("available_refcats", []))\n        if not common:\n            continue\n        refcat = "apass" if "apass" in common else "atlas"\n\n        plate_ids = {r.get("plate_id") for r in rows.values()}\n        solnums = {r.get("solnum") for r in rows.values()}\n        if len(plate_ids) != 1 or len(solnums) != 1:\n            raise RuntimeError(f"identity disagreement for {eid}")\n\n        parsed = []\n        for r in rows.values():\n            jd, iso = parse_obs_date(r.get("obs_date_raw"))\n            if jd is not None:\n                parsed.append((jd, iso))\n        if not parsed:\n            continue\n\n        jds = [x[0] for x in parsed]\n        if max(jds) - min(jds) > (1.0 / 86400.0):\n            raise RuntimeError(f"date disagreement for {eid}: {jds}")\n        jd = sum(jds) / len(jds)\n        _, iso = parse_obs_date(jd)\n\n        eligible.append({\n            "exposure_identity": eid,\n            "plate_id": next(iter(plate_ids)),\n            "solution_number": next(iter(solnums)),\n            "refcat": refcat,\n            "obs_date_jd": jd,\n            "obs_date_iso": iso,\n        })\n\n    eligible.sort(key=lambda r: (r["obs_date_jd"], r["exposure_identity"]))\n    if len(eligible) < CUMULATIVE_EXPOSURES:\n        print(f"FAIL only {len(eligible)} eligible exposures")\n        return 4\n\n    idxs256 = farthest_rank_indices(len(eligible), CUMULATIVE_EXPOSURES)\n    selected256_algorithm = [eligible[i] for i in idxs256]\n\n    phase1_ids = {\n        r["exposure_identity"]\n        for r in bs.get("phase1", {}).get("exposures", [])\n    }\n    first64_ids = {\n        r["exposure_identity"] for r in selected256_algorithm[:PHASE1_EXPOSURES]\n    }\n    if phase1_ids != first64_ids:\n        print("FAIL nested-selection regression: phase1 != first 64 of cumulative 256")\n        print(f"  phase1_only={sorted(phase1_ids - first64_ids)[:5]}")\n        print(f"  recalculated_only={sorted(first64_ids - phase1_ids)[:5]}")\n        return 5\n\n    new = [\n        r for r in selected256_algorithm\n        if r["exposure_identity"] not in phase1_ids\n    ]\n    if len(new) != NEW_EXPOSURES:\n        print(f"FAIL expected {NEW_EXPOSURES} new exposures, got {len(new)}")\n        return 5\n\n    # Execute new exposures chronologically; retain deterministic selection rank.\n    rank = {\n        r["exposure_identity"]: n + 1\n        for n, r in enumerate(selected256_algorithm)\n    }\n    new.sort(key=lambda r: (r["obs_date_jd"], r["exposure_identity"]))\n\n    queue = []\n    for exposure_seq, exp in enumerate(new, 1):\n        for target in TARGETS:\n            ra, dec = coords[target]\n            queue.append({\n                "request_seq": len(queue) + 1,\n                "phase": 2,\n                "phase2_exposure_seq": exposure_seq,\n                "cumulative_selection_rank": rank[exp["exposure_identity"]],\n                "target": target,\n                "center_ra_deg": ra,\n                "center_dec_deg": dec,\n                "exposure_identity": exp["exposure_identity"],\n                "plate_id": exp["plate_id"],\n                "solution_number": exp["solution_number"],\n                "refcat": exp["refcat"],\n                "obs_date_jd": exp["obs_date_jd"],\n                "obs_date_iso": exp["obs_date_iso"] or "",\n            })\n\n    if len(queue) != EXPECTED_NEW_REQUESTS:\n        print(\n            f"FAIL expected {EXPECTED_NEW_REQUESTS} requests, got {len(queue)}"\n        )\n        return 5\n\n    apass_n = sum(r["refcat"] == "apass" for r in new)\n    atlas_n = sum(r["refcat"] == "atlas" for r in new)\n\n    print(f"Eligible matched exposures: {len(eligible)}")\n    print(f"Cumulative selected exposures: {CUMULATIVE_EXPOSURES}")\n    print(f"Phase 1 retained exposures: {len(phase1_ids)}")\n    print(f"New Phase 2 exposures: {len(new)}")\n    print(f"New Phase 2 requests: {len(queue)}")\n    print(f"Phase 2 refcat exposures: APASS={apass_n} ATLAS={atlas_n}")\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(queue[0].keys())\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(queue)\n\n    payload = {\n        "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_256_PLAN_V028BV",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "platephot_requests_made": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "selection": {\n            "eligible_matched_exposures": len(eligible),\n            "cumulative_target_exposures": CUMULATIVE_EXPOSURES,\n            "phase1_exposures_reused": len(phase1_ids),\n            "phase2_new_exposures": len(new),\n            "phase2_new_requests": len(queue),\n            "nested_selection_verified": True,\n            "refcat_preference": "APASS if common to all three; otherwise ATLAS",\n            "phase2_apass_exposures": apass_n,\n            "phase2_atlas_exposures": atlas_n,\n        },\n        "phase2_queue_csv": str(OUT_CSV.relative_to(ROOT)),\n        "phase2_exposures": new,\n        "interpretive_boundary": (\n            "This expands the same deterministic matched-exposure design from "\n            "64 to 256 cumulative exposures. The first 64 are exactly preserved; "\n            "only 192 new exposures / 576 new target requests are queued."\n        ),\n        "next_gate": {\n            "matched_recurrence_phase2_may_run": True,\n        },\n    }\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — Matched Recurrence 256-Exposure Expansion Plan v028bv",\n        "",\n        f"- Eligible matched exposures: **{len(eligible)}**.",\n        f"- Cumulative target: **{CUMULATIVE_EXPOSURES} exposures**.",\n        f"- Phase 1 preserved: **{len(phase1_ids)} exposures**.",\n        f"- Phase 2 new: **{len(new)} exposures / {len(queue)} requests**.",\n        f"- Phase 2 refcat: APASS **{apass_n}**, ATLAS **{atlas_n}**.",\n        "",\n        "Nested deterministic selection was verified exactly.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

BU_ENTRY = """
    StageContract(
        stage_id="dasch_matched_recurrence_phase1_interpretation_v028bu",
        title="Interpret exact phase-1 close matches and same-exposure controls",
        script="automation/stages/interpret_matched_recurrence_phase1_v028bu.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase1_v028bt.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json",
        ),
        dependencies=("dasch_matched_recurrence_phase1_v028bt",),
        notes="No network/pixels; separates clean <=5 arcsec recurrence from loose 5-10 arcsec matches.",
    ),
"""

BV_ENTRY = """
    StageContract(
        stage_id="dasch_matched_recurrence_256_plan_v028bv",
        title="Plan nested matched recurrence expansion from 64 to 256 exposures",
        script="automation/stages/plan_matched_recurrence_256_v028bv.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_science25_analogue_exposure_inventory_v028br.json",
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_plan_v028bs.json",
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_256_plan_v028bv.json",
        ),
        dependencies=("dasch_matched_recurrence_phase1_interpretation_v028bu",),
        notes="No network/pixels; verifies nested deterministic selection and queues 192 new exposures / 576 requests.",
    ),
"""


def find_container(text):
    tree = ast.parse(text)
    for node in tree.body:
        value = None
        matched = False
        if isinstance(node, ast.Assign):
            value = node.value
            matched = any(
                isinstance(t, ast.Name) and t.id == "ORDER01_STAGES"
                for t in node.targets
            )
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            matched = (
                isinstance(node.target, ast.Name)
                and node.target.id == "ORDER01_STAGES"
            )
        if matched and isinstance(value, (ast.List, ast.Tuple)):
            return value
    raise RuntimeError("ORDER01_STAGES list/tuple not found")


def add_entries(text):
    need = []
    if 'stage_id="dasch_matched_recurrence_phase1_interpretation_v028bu"' not in text:
        need.append(BU_ENTRY.rstrip())
    if 'stage_id="dasch_matched_recurrence_256_plan_v028bv"' not in text:
        need.append(BV_ENTRY.rstrip())
    if not need:
        return text, "already registered"

    container = find_container(text)
    lines = text.splitlines(keepends=True)
    lines.insert(container.end_lineno - 1, "\n" + "\n".join(need) + "\n")
    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted {len(need)} StageContract entries"


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.0 — PHASE-1 INTERPRETATION + 256 PLAN")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
    print("Adds only local interpretation/planning stages.\n")

    for p in (REGISTRY, RUNNER, INIT):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, INIT):
        dst = BACKUP / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    BU.write_text(BU_CONTENT, encoding="utf-8")
    BV.write_text(BV_CONTENT, encoding="utf-8")
    py_compile.compile(str(BU), doraise=True)
    py_compile.compile(str(BV), doraise=True)
    print("New stage syntax: PASS (v028bu, v028bv)")

    reg = REGISTRY.read_text(encoding="utf-8")
    reg, note = add_entries(reg)
    REGISTRY.write_text(reg, encoding="utf-8")
    print(f"Registry: {note}")

    runner = RUNNER.read_text(encoding="utf-8")
    runner, n = re.subn(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.3.0 - Order01 registry status",
        runner,
        count=1,
    )
    if n != 1:
        print("FAIL runner banner not found")
        return 3
    RUNNER.write_text(runner, encoding="utf-8")
    INIT.write_bytes(b'__version__ = "0.3.0"\n')

    failures = []
    py_files = sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            ast.parse(p.read_text(encoding="utf-8"))
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {type(exc).__name__}: {exc}")

    if failures:
        print("\nAUTOMATION UPGRADE STATUS: FAIL")
        return 4

    try:
        sys.path.insert(0, str(ROOT))
        import automation
        import automation.registry_order01 as regmod

        if automation.__version__ != "0.3.0":
            raise RuntimeError(f"bad automation version {automation.__version__!r}")

        bu = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_matched_recurrence_phase1_interpretation_v028bu"
        )
        bv = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_matched_recurrence_256_plan_v028bv"
        )
        if getattr(bu, "network_access", False):
            raise RuntimeError("v028bu unexpectedly requires network")
        if getattr(bv, "network_access", False):
            raise RuntimeError("v028bv unexpectedly requires network")
        print("\nRuntime package/registry import regression: PASS")
    except Exception as exc:
        print(f"\nRuntime import regression: FAIL: {type(exc).__name__}: {exc}")
        return 5

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_matched_recurrence_phase1_interpretation_v028bu'
    )
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_matched_recurrence_256_plan_v028bv'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
