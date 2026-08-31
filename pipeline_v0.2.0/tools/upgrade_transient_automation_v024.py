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
PLAN_STAGE = AUTO / "stages" / "plan_matched_recurrence_v028bs.py"
EXEC_STAGE = AUTO / "stages" / "execute_matched_recurrence_phase1_v028bt.py"
BACKUP = AUTO / "backups" / "pre_v024"
PLAN_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport json\nfrom datetime import datetime, timezone\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nINV = BASE / "order01_dasch_science25_analogue_exposure_inventory_v028br.json"\n\nOUT_JSON = BASE / "order01_dasch_matched_recurrence_plan_v028bs.json"\nOUT_CSV = BASE / "order01_dasch_matched_recurrence_phase1_queue_v028bs.csv"\nOUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_PLAN_V028BS.md"\n\nTARGETS = ("science25", "q0030", "q0344")\nPHASE1_EXPOSURES = 64\nDISCOVERY_PLATE = "ai43437"\n\n\ndef parse_dt(x):\n    if x is None:\n        return None\n    s = str(x).strip()\n    if not s:\n        return None\n    s = s.replace("Z", "+00:00")\n    try:\n        dt = datetime.fromisoformat(s)\n        if dt.tzinfo is None:\n            dt = dt.replace(tzinfo=timezone.utc)\n        return dt.astimezone(timezone.utc)\n    except Exception:\n        return None\n\n\ndef farthest_rank_indices(n, k):\n    """Deterministic nested chronological spread over sorted exposure ranks."""\n    if n <= 0 or k <= 0:\n        return []\n    if k >= n:\n        return list(range(n))\n\n    selected = [0]\n    if n > 1 and k > 1:\n        selected.append(n - 1)\n\n    while len(selected) < k:\n        chosen = set(selected)\n        best = None\n        best_key = None\n        for idx in range(n):\n            if idx in chosen:\n                continue\n            d = min(abs(idx - j) for j in selected)\n            # Larger distance first; then earlier chronological rank.\n            key = (d, -idx)\n            if best is None or key > best_key:\n                best = idx\n                best_key = key\n        selected.append(best)\n\n    return selected\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MATCHED THREE-POSITION RECURRENCE PLAN v028bs")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("NO PIXELS ARE READ.")\n    print("No platephot requests are made.")\n    print("No candidate state is changed.\\n")\n\n    if not INV.is_file():\n        print(f"FAIL missing input: {INV}")\n        return 2\n\n    inv = json.loads(INV.read_text(encoding="utf-8"))\n    by_target = inv.get("by_target", {})\n    target_coords = {\n        t["target"]: (float(t["ra_deg"]), float(t["dec_deg"]))\n        for t in inv.get("targets", [])\n    }\n\n    if sorted(target_coords) != sorted(TARGETS):\n        print(f"FAIL target coordinate set mismatch: {sorted(target_coords)}")\n        return 3\n\n    maps = {}\n    for target in TARGETS:\n        rows = by_target.get(target, {}).get("rows", [])\n        maps[target] = {\n            r["exposure_identity"]: r\n            for r in rows\n            if r.get("has_imaging")\n        }\n\n    shared_ids = set(maps[TARGETS[0]])\n    for target in TARGETS[1:]:\n        shared_ids &= set(maps[target])\n\n    eligible = []\n    excluded_no_common_refcat = 0\n    excluded_discovery = 0\n    excluded_missing_date = 0\n\n    for eid in sorted(shared_ids):\n        rows = {t: maps[t][eid] for t in TARGETS}\n        if any(r.get("plate_id") == DISCOVERY_PLATE for r in rows.values()):\n            excluded_discovery += 1\n            continue\n\n        common = set(("apass", "atlas"))\n        for r in rows.values():\n            common &= set(r.get("available_refcats", []))\n\n        if not common:\n            excluded_no_common_refcat += 1\n            continue\n\n        # Preserve methodological continuity with discovery extraction where possible.\n        refcat = "apass" if "apass" in common else "atlas"\n\n        # Exposure identity guarantees same plate/solution. Guard it anyway.\n        plate_ids = {r.get("plate_id") for r in rows.values()}\n        solnums = {r.get("solnum") for r in rows.values()}\n        if len(plate_ids) != 1 or len(solnums) != 1:\n            raise RuntimeError(\n                f"shared exposure identity {eid} disagrees across targets: "\n                f"plates={plate_ids} solnums={solnums}"\n            )\n\n        dates = [parse_dt(r.get("obs_date_raw")) for r in rows.values()]\n        dates = [d for d in dates if d is not None]\n        if not dates:\n            excluded_missing_date += 1\n            continue\n        # Same exposure should have same date; use earliest parsed value and record raw.\n        dt = min(dates)\n\n        eligible.append({\n            "exposure_identity": eid,\n            "plate_id": next(iter(plate_ids)),\n            "solution_number": next(iter(solnums)),\n            "refcat": refcat,\n            "common_refcats": sorted(common),\n            "obs_date_iso": dt.isoformat(),\n            "obs_date_raw": rows["science25"].get("obs_date_raw"),\n            "science25_lim_mag_apass": rows["science25"].get("lim_mag_apass"),\n            "science25_lim_mag_atlas": rows["science25"].get("lim_mag_atlas"),\n            "q0030_lim_mag_apass": rows["q0030"].get("lim_mag_apass"),\n            "q0030_lim_mag_atlas": rows["q0030"].get("lim_mag_atlas"),\n            "q0344_lim_mag_apass": rows["q0344"].get("lim_mag_apass"),\n            "q0344_lim_mag_atlas": rows["q0344"].get("lim_mag_atlas"),\n        })\n\n    eligible.sort(key=lambda r: (r["obs_date_iso"], r["exposure_identity"]))\n\n    if len(eligible) < PHASE1_EXPOSURES:\n        print(f"FAIL only {len(eligible)} eligible matched exposures")\n        return 4\n\n    idxs = farthest_rank_indices(len(eligible), PHASE1_EXPOSURES)\n    phase1 = [eligible[idx] for idx in idxs]\n    # Execution order chronological, while retaining selection rank.\n    rank_by_eid = {r["exposure_identity"]: n + 1 for n, r in enumerate(phase1)}\n    phase1.sort(key=lambda r: (r["obs_date_iso"], r["exposure_identity"]))\n\n    queue = []\n    for exposure_seq, exp in enumerate(phase1, 1):\n        for target in TARGETS:\n            ra, dec = target_coords[target]\n            queue.append({\n                "request_seq": len(queue) + 1,\n                "phase": 1,\n                "phase_exposure_seq": exposure_seq,\n                "selection_rank": rank_by_eid[exp["exposure_identity"]],\n                "target": target,\n                "center_ra_deg": ra,\n                "center_dec_deg": dec,\n                "exposure_identity": exp["exposure_identity"],\n                "plate_id": exp["plate_id"],\n                "solution_number": exp["solution_number"],\n                "refcat": exp["refcat"],\n                "obs_date_iso": exp["obs_date_iso"],\n                "obs_date_raw": exp["obs_date_raw"],\n            })\n\n    apass_n = sum(r["refcat"] == "apass" for r in phase1)\n    atlas_n = sum(r["refcat"] == "atlas" for r in phase1)\n\n    print(f"Shared imaging exposure identities: {len(shared_ids)}")\n    print(f"Eligible matched calibrated + dated non-discovery exposures: {len(eligible)}")\n    print(f"Excluded discovery plate: {excluded_discovery}")\n    print(f"Excluded no common refcat: {excluded_no_common_refcat}")\n    print(f"Excluded missing date: {excluded_missing_date}")\n    print(f"Phase 1 matched exposures: {len(phase1)}")\n    print(f"Phase 1 platephot requests: {len(queue)}")\n    print(f"Phase 1 refcat exposures: APASS={apass_n} ATLAS={atlas_n}")\n    print(\n        f"Phase 1 chronological span: {phase1[0][\'obs_date_iso\']} -> "\n        f"{phase1[-1][\'obs_date_iso\']}"\n    )\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(queue[0].keys())\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(queue)\n\n    payload = {\n        "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PLAN_V028BS",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "platephot_requests_made": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "design": {\n            "targets": list(TARGETS),\n            "matched_same_exposure_required": True,\n            "same_refcat_required_within_exposure": True,\n            "refcat_preference": "APASS if common to all three; otherwise ATLAS",\n            "phase1_exposure_count": PHASE1_EXPOSURES,\n            "phase1_request_count": len(queue),\n            "temporal_selection": (\n                "deterministic farthest-rank sampling over chronologically sorted "\n                "eligible shared exposures; endpoints seeded first"\n            ),\n            "descriptive_recurrence_radii_arcsec": [3.0, 5.0, 10.0],\n            "automatic_candidate_promotion": False,\n        },\n        "inventory": {\n            "shared_imaging_exposure_count": len(shared_ids),\n            "eligible_matched_exposure_count": len(eligible),\n            "excluded_discovery_plate": excluded_discovery,\n            "excluded_no_common_refcat": excluded_no_common_refcat,\n            "excluded_missing_date": excluded_missing_date,\n        },\n        "phase1": {\n            "exposure_count": len(phase1),\n            "request_count": len(queue),\n            "apass_exposures": apass_n,\n            "atlas_exposures": atlas_n,\n            "first_date": phase1[0]["obs_date_iso"],\n            "last_date": phase1[-1]["obs_date_iso"],\n            "queue_csv": str(OUT_CSV.relative_to(ROOT)),\n            "exposures": phase1,\n        },\n        "interpretive_boundary": (\n            "Phase 1 is a matched recurrence calibration pass, not a complete "\n            "recurrence census. It tests the same 64 historical exposures at all "\n            "three positions and reports nearest fitted-source separations at "\n            "3/5/10 arcsec without automatic source classification."\n        ),\n        "next_gate": {\n            "matched_recurrence_phase1_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — Matched Three-Position Recurrence Plan v028bs",\n        "",\n        f"- Shared imaging exposures: **{len(shared_ids)}**.",\n        f"- Eligible calibrated, dated, non-discovery matched exposures: **{len(eligible)}**.",\n        f"- Phase 1: **{len(phase1)} exposures / {len(queue)} platephot requests**.",\n        f"- Refcat: APASS on **{apass_n}** exposures; ATLAS on **{atlas_n}**.",\n        f"- Span: **{phase1[0][\'obs_date_iso\']} → {phase1[-1][\'obs_date_iso\']}**.",\n        "",\n        "Phase 1 is deliberately matched across #25, q0030, and q0344 and does not "\n        "promote any detection automatically.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
EXEC_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport io\nimport json\nimport math\nimport time\nfrom collections import Counter, defaultdict\nfrom pathlib import Path\n\nimport requests\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nWORK = ROOT / "work" / "order01_native_full_v028" / "matched_recurrence_v028bt"\n\nPLAN = BASE / "order01_dasch_matched_recurrence_plan_v028bs.json"\nQUEUE = BASE / "order01_dasch_matched_recurrence_phase1_queue_v028bs.csv"\n\nOUT_JSON = BASE / "order01_dasch_matched_recurrence_phase1_v028bt.json"\nOUT_CSV = BASE / "order01_dasch_matched_recurrence_phase1_v028bt.csv"\nOUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_V028BT.md"\nCHECKPOINT = WORK / "checkpoint.json"\n\nBASE_URL = "https://api.starglass.cfa.harvard.edu/public/"\nPLATEPHOT_PATH = "dasch/dr7/platephot"\nTIMEOUT = 90\nRADII = (3.0, 5.0, 10.0)\nEXPECTED_REQUESTS = 192\nTARGETS = ("science25", "q0030", "q0344")\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef first(row, *keys):\n    for k in keys:\n        if k in row and row[k] not in ("", None):\n            return row[k]\n    return None\n\n\ndef angular_sep_arcsec(ra1, dec1, ra2, dec2):\n    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))\n    sd = math.sin((d2 - d1) / 2.0)\n    sr = math.sin((r2 - r1) / 2.0)\n    a = sd * sd + math.cos(d1) * math.cos(d2) * sr * sr\n    a = min(1.0, max(0.0, a))\n    return math.degrees(2.0 * math.asin(math.sqrt(a))) * 3600.0\n\n\ndef parse_api_csv(obj):\n    if not isinstance(obj, list):\n        raise RuntimeError(f"expected JSON list; got {type(obj).__name__}")\n    if not obj:\n        return []\n    return list(csv.DictReader(io.StringIO("\\n".join(str(x) for x in obj))))\n\n\ndef read_queue(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef post_cached(payload, cache_path):\n    cache_path.parent.mkdir(parents=True, exist_ok=True)\n    if cache_path.is_file():\n        return json.loads(cache_path.read_text(encoding="utf-8")), True\n\n    url = BASE_URL.rstrip("/") + "/" + PLATEPHOT_PATH\n    delays = (2, 5, 10)\n    last = None\n    for attempt in range(1, 4):\n        try:\n            r = requests.post(\n                url,\n                json=payload,\n                timeout=TIMEOUT,\n                headers={"accept": "application/json"},\n            )\n            if r.status_code in (408, 425, 429) or 500 <= r.status_code <= 599:\n                raise requests.HTTPError(f"retryable HTTP {r.status_code}", response=r)\n            r.raise_for_status()\n            obj = r.json()\n            tmp = cache_path.with_suffix(".tmp")\n            tmp.write_text(json.dumps(obj, indent=2) + "\\n", encoding="utf-8")\n            tmp.replace(cache_path)\n            time.sleep(1.0)\n            return obj, False\n        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:\n            last = exc\n            if attempt == 3:\n                break\n            time.sleep(delays[attempt - 1])\n    raise RuntimeError(\n        f"platephot failed after 3 attempts: {type(last).__name__}: {last}"\n    )\n\n\ndef summarize_response(rows, tra, tdec):\n    detections = []\n    for row in rows:\n        ra = f(first(row, "raDeg", "ra_deg", "ra"))\n        dec = f(first(row, "decDeg", "dec_deg", "dec"))\n        if ra is None or dec is None:\n            continue\n        sep = angular_sep_arcsec(tra, tdec, ra, dec)\n        detections.append((sep, row))\n\n    detections.sort(key=lambda x: x[0])\n    nearest = detections[0] if detections else None\n\n    out = {\n        "response_row_count": len(rows),\n        "positioned_row_count": len(detections),\n        "nearest_sep_arcsec": nearest[0] if nearest else None,\n        "nearest_raw_row": nearest[1] if nearest else None,\n    }\n    for radius in RADII:\n        out[f"count_le_{int(radius)}arcsec"] = sum(sep <= radius for sep, _ in detections)\n    return out\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MATCHED THREE-POSITION RECURRENCE PHASE 1 v028bt")\n    print("=" * 128)\n    print("NETWORK ACCESS: TRUE (DASCH DR7 public platephot only).")\n    print("NO PIXELS ARE READ.")\n    print("Frozen transient detector is NOT rerun.")\n    print("No candidate state is changed.\\n")\n\n    for p in (PLAN, QUEUE):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    plan = json.loads(PLAN.read_text(encoding="utf-8"))\n    if not plan.get("next_gate", {}).get("matched_recurrence_phase1_may_run"):\n        print("FAIL v028bs phase1 gate not enabled")\n        return 3\n\n    queue = read_queue(QUEUE)\n    if len(queue) != EXPECTED_REQUESTS:\n        print(f"FAIL expected {EXPECTED_REQUESTS} requests; got {len(queue)}")\n        return 3\n\n    WORK.mkdir(parents=True, exist_ok=True)\n    results = []\n\n    for idx, q in enumerate(queue, 1):\n        req_seq = int(q["request_seq"])\n        target = q["target"]\n        payload = {\n            "plate_id": q["plate_id"],\n            "solution_number": int(q["solution_number"]),\n            "refcat": q["refcat"],\n            "center_ra_deg": float(q["center_ra_deg"]),\n            "center_dec_deg": float(q["center_dec_deg"]),\n        }\n        cache = WORK / "cache" / f"{req_seq:04d}_{target}_{q[\'plate_id\']}_s{q[\'solution_number\']}_{q[\'refcat\']}.json"\n\n        obj, cache_used = post_cached(payload, cache)\n        rows = parse_api_csv(obj)\n        summary = summarize_response(\n            rows,\n            float(q["center_ra_deg"]),\n            float(q["center_dec_deg"]),\n        )\n\n        rec = {\n            **q,\n            "request_seq": req_seq,\n            "phase": int(q["phase"]),\n            "phase_exposure_seq": int(q["phase_exposure_seq"]),\n            "selection_rank": int(q["selection_rank"]),\n            "solution_number": int(q["solution_number"]),\n            "center_ra_deg": float(q["center_ra_deg"]),\n            "center_dec_deg": float(q["center_dec_deg"]),\n            "cache_used": cache_used,\n            **summary,\n        }\n        results.append(rec)\n\n        CHECKPOINT.write_text(\n            json.dumps({\n                "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_V028BT",\n                "completed_requests": len(results),\n                "expected_requests": EXPECTED_REQUESTS,\n                "last_request_seq": req_seq,\n                "last_target": target,\n                "last_plate_id": q["plate_id"],\n            }, indent=2) + "\\n",\n            encoding="utf-8",\n        )\n\n        if idx == 1 or idx % 12 == 0 or idx == len(queue):\n            print(\n                f"progress {idx}/{len(queue)}: "\n                f"{q[\'plate_id\']} {target} "\n                f"rows={summary[\'response_row_count\']} "\n                f"nearest={summary[\'nearest_sep_arcsec\']} "\n                f"cache={cache_used}"\n            )\n\n    by_target = {}\n    for target in TARGETS:\n        rr = [r for r in results if r["target"] == target]\n        by_target[target] = {\n            "requests": len(rr),\n            "with_any_positioned_row": sum(r["positioned_row_count"] > 0 for r in rr),\n            "with_nearest_le_3arcsec": sum(\n                r["nearest_sep_arcsec"] is not None and r["nearest_sep_arcsec"] <= 3.0\n                for r in rr\n            ),\n            "with_nearest_le_5arcsec": sum(\n                r["nearest_sep_arcsec"] is not None and r["nearest_sep_arcsec"] <= 5.0\n                for r in rr\n            ),\n            "with_nearest_le_10arcsec": sum(\n                r["nearest_sep_arcsec"] is not None and r["nearest_sep_arcsec"] <= 10.0\n                for r in rr\n            ),\n            "nearest_sep_arcsec_values": [\n                r["nearest_sep_arcsec"] for r in rr if r["nearest_sep_arcsec"] is not None\n            ],\n        }\n\n    # Same-exposure matched outcomes.\n    exp_groups = defaultdict(dict)\n    for r in results:\n        exp_groups[r["exposure_identity"]][r["target"]] = r\n\n    combo_counts = Counter()\n    combo_examples = defaultdict(list)\n    for eid, group in exp_groups.items():\n        if sorted(group) != sorted(TARGETS):\n            raise RuntimeError(f"matched exposure {eid} missing targets: {sorted(group)}")\n\n        close10 = tuple(\n            t for t in TARGETS\n            if group[t]["nearest_sep_arcsec"] is not None\n            and group[t]["nearest_sep_arcsec"] <= 10.0\n        )\n        key = "+".join(close10) if close10 else "none"\n        combo_counts[key] += 1\n        if len(combo_examples[key]) < 10:\n            combo_examples[key].append({\n                "exposure_identity": eid,\n                "plate_id": group["science25"]["plate_id"],\n                "obs_date_iso": group["science25"]["obs_date_iso"],\n                "science25_nearest": group["science25"]["nearest_sep_arcsec"],\n                "q0030_nearest": group["q0030"]["nearest_sep_arcsec"],\n                "q0344_nearest": group["q0344"]["nearest_sep_arcsec"],\n            })\n\n    print("\\nTARGET SUMMARY")\n    for target in TARGETS:\n        x = by_target[target]\n        print(\n            f"  {target}: n={x[\'requests\']} "\n            f"<=3\\"={x[\'with_nearest_le_3arcsec\']} "\n            f"<=5\\"={x[\'with_nearest_le_5arcsec\']} "\n            f"<=10\\"={x[\'with_nearest_le_10arcsec\']}"\n        )\n\n    print("\\nMATCHED EXPOSURE <=10\\" PATTERNS")\n    for key, count in sorted(combo_counts.items()):\n        print(f"  {key}: {count}")\n\n    # Flatten without huge raw row payload.\n    flat = []\n    for r in results:\n        nearest = r.get("nearest_raw_row") or {}\n        x = {\n            k: v for k, v in r.items()\n            if k != "nearest_raw_row"\n        }\n        for k, v in nearest.items():\n            if isinstance(v, (str, int, float, bool)) or v is None:\n                x[f"nearest_{k}"] = v\n        flat.append(x)\n\n    fields = sorted({k for r in flat for k in r})\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(flat)\n\n    payload = {\n        "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_V028BT",\n        "guards": {\n            "network_access": True,\n            "network_scope": "DASCH DR7 public platephot only",\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "design": plan.get("design"),\n        "completed_requests": len(results),\n        "completed_matched_exposures": len(exp_groups),\n        "by_target": by_target,\n        "matched_exposure_close10_pattern_counts": dict(combo_counts),\n        "matched_exposure_close10_examples": dict(combo_examples),\n        "results": results,\n        "interpretive_boundary": (\n            "This is a 64-exposure matched recurrence calibration pass. A fitted "\n            "source within 3/5/10 arcsec is descriptive evidence only; WCS error, "\n            "blends, source splitting, plate artifacts, and unrelated field sources "\n            "remain possible. No candidate state changes automatically."\n        ),\n        "next_gate": {\n            "matched_recurrence_phase1_interpretation_may_run": True,\n            "matched_recurrence_expansion_plan_may_be_built": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — Matched Three-Position Recurrence Phase 1 v028bt",\n        "",\n        f"- Completed requests: **{len(results)}**.",\n        f"- Matched exposures: **{len(exp_groups)}**.",\n        "",\n        "| target | ≤3″ | ≤5″ | ≤10″ |",\n        "|---|---:|---:|---:|",\n    ]\n    for target in TARGETS:\n        x = by_target[target]\n        md.append(\n            f"| {target} | {x[\'with_nearest_le_3arcsec\']} | "\n            f"{x[\'with_nearest_le_5arcsec\']} | {x[\'with_nearest_le_10arcsec\']} |"\n        )\n    md += [\n        "",\n        "These counts are descriptive and do not automatically classify recurrences.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

PLAN_ENTRY = """
    StageContract(
        stage_id="dasch_matched_recurrence_plan_v028bs",
        title="Plan deterministic matched historical recurrence pass for #25/q0030/q0344",
        script="automation/stages/plan_matched_recurrence_v028bs.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_science25_analogue_exposure_inventory_v028br.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_plan_v028bs.json",
        ),
        dependencies=("dasch_science25_analogue_exposure_inventory_v028br",),
        notes="No network/pixels; freezes 64 matched shared exposures and 192-request phase-1 queue.",
    ),
"""

EXEC_ENTRY = """
    StageContract(
        stage_id="dasch_matched_recurrence_phase1_v028bt",
        title="Execute 64-exposure matched platephot recurrence calibration pass",
        script="automation/stages/execute_matched_recurrence_phase1_v028bt.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_plan_v028bs.json",
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase1_queue_v028bs.csv",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase1_v028bt.json",
        ),
        dependencies=("dasch_matched_recurrence_plan_v028bs",),
        network_access=True,
        notes="192 cached DASCH public platephot requests; no pixels/detector/state mutation.",
    ),
"""


def find_container(text):
    tree = ast.parse(text)
    for node in tree.body:
        value = None
        matched = False
        if isinstance(node, ast.Assign):
            value = node.value
            matched = any(isinstance(t, ast.Name) and t.id == "ORDER01_STAGES" for t in node.targets)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            matched = isinstance(node.target, ast.Name) and node.target.id == "ORDER01_STAGES"
        if matched and isinstance(value, (ast.List, ast.Tuple)):
            return value
    raise RuntimeError("ORDER01_STAGES list/tuple not found")


def insert_entries(text):
    have_plan = 'stage_id="dasch_matched_recurrence_plan_v028bs"' in text
    have_exec = 'stage_id="dasch_matched_recurrence_phase1_v028bt"' in text
    if have_plan and have_exec:
        return text, "already registered"

    container = find_container(text)
    additions = []
    if not have_plan:
        additions.append(PLAN_ENTRY.rstrip())
    if not have_exec:
        additions.append(EXEC_ENTRY.rstrip())

    lines = text.splitlines(keepends=True)
    lines.insert(container.end_lineno - 1, "\n" + "\n".join(additions) + "\n")
    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted {len(additions)} StageContract entries"


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION UPGRADE v0.2.7 — MATCHED RECURRENCE CALIBRATION")
    print("=" * 112)
    print("THE UPGRADE ITSELF MAKES NO NETWORK CALLS.")
    print("v028bs is no-network planning.")
    print("v028bt requires explicit --allow-network and makes 192 cached platephot calls.")
    print("NO PIXELS ARE READ by either stage.\n")

    for p in (REGISTRY, RUNNER, INIT):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, INIT):
        dst = BACKUP / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    PLAN_STAGE.write_text(PLAN_CONTENT, encoding="utf-8")
    EXEC_STAGE.write_text(EXEC_CONTENT, encoding="utf-8")
    py_compile.compile(str(PLAN_STAGE), doraise=True)
    py_compile.compile(str(EXEC_STAGE), doraise=True)
    print("New stage syntax: PASS (v028bs, v028bt)")

    reg = REGISTRY.read_text(encoding="utf-8")
    reg, note = insert_entries(reg)
    REGISTRY.write_text(reg, encoding="utf-8")
    print(f"Registry: {note}")

    runner = RUNNER.read_text(encoding="utf-8")
    runner = re.sub(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.2.7 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    INIT.write_text('__version__ = "0.2.7"\n', encoding="utf-8")

    failures = []
    py_files = sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
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

    try:
        sys.path.insert(0, str(ROOT))
        import automation.registry_order01 as regmod
        plan = next(s for s in regmod.ORDER01_STAGES if getattr(s, "stage_id", None) == "dasch_matched_recurrence_plan_v028bs")
        exe = next(s for s in regmod.ORDER01_STAGES if getattr(s, "stage_id", None) == "dasch_matched_recurrence_phase1_v028bt")
        if getattr(plan, "network_access", False):
            raise RuntimeError("v028bs unexpectedly requires network")
        if getattr(exe, "network_access", None) is not True:
            raise RuntimeError("v028bt network_access is not True")
        print("\nRegistry import/StageContract regression: PASS")
    except Exception as exc:
        print(f"\nRegistry import regression: FAIL: {type(exc).__name__}: {exc}")
        return 5

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_matched_recurrence_plan_v028bs')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_matched_recurrence_phase1_v028bt')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
