#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import py_compile
import re
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
AUTO = ROOT / "automation"
PLAN_STAGE = AUTO / "stages" / "plan_matched_recurrence_v028bs.py"
RUNNER = AUTO / "runner.py"
INIT = AUTO / "__init__.py"
REGISTRY = AUTO / "registry_order01.py"
BACKUP = AUTO / "backups" / "pre_v024a_repair"
PLAN_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom datetime import datetime, timezone, timedelta\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nINV = BASE / "order01_dasch_science25_analogue_exposure_inventory_v028br.json"\n\nOUT_JSON = BASE / "order01_dasch_matched_recurrence_plan_v028bs.json"\nOUT_CSV = BASE / "order01_dasch_matched_recurrence_phase1_queue_v028bs.csv"\nOUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_PLAN_V028BS.md"\n\nTARGETS = ("science25", "q0030", "q0344")\nPHASE1_EXPOSURES = 64\nDISCOVERY_PLATE = "ai43437"\nUNIX_EPOCH_JD = 2440587.5\n\n\ndef parse_obs_date(value):\n    """\n    Return (jd, iso_or_none).\n\n    DASCH DR7 exposure-list obs_date is documented as geocentric Julian Date\n    of the exposure midpoint. We also accept ISO values defensively because\n    exported/derived tables may serialize Astropy Time differently.\n    """\n    if value is None:\n        return None, None\n\n    text = str(value).strip()\n    if not text or text.lower() in ("nan", "none", "null", "--", "masked"):\n        return None, None\n\n    # Primary official DR7/raw-API representation: numeric Julian Date.\n    try:\n        jd = float(text)\n        if math.isfinite(jd) and 2000000.0 < jd < 3000000.0:\n            seconds = (jd - UNIX_EPOCH_JD) * 86400.0\n            try:\n                dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)\n                iso = dt.isoformat()\n            except (OverflowError, ValueError):\n                iso = None\n            return jd, iso\n    except Exception:\n        pass\n\n    # Defensive ISO fallback.\n    try:\n        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))\n        if dt.tzinfo is None:\n            dt = dt.replace(tzinfo=timezone.utc)\n        dt = dt.astimezone(timezone.utc)\n        seconds = (dt - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()\n        jd = UNIX_EPOCH_JD + seconds / 86400.0\n        return jd, dt.isoformat()\n    except Exception:\n        return None, None\n\n\ndef farthest_rank_indices(n, k):\n    """Deterministic nested chronological spread over sorted exposure ranks."""\n    if n <= 0 or k <= 0:\n        return []\n    if k >= n:\n        return list(range(n))\n\n    selected = [0]\n    if n > 1 and k > 1:\n        selected.append(n - 1)\n\n    while len(selected) < k:\n        chosen = set(selected)\n        best = None\n        best_key = None\n        for idx in range(n):\n            if idx in chosen:\n                continue\n            d = min(abs(idx - j) for j in selected)\n            key = (d, -idx)  # larger gap first, then earlier rank\n            if best is None or key > best_key:\n                best = idx\n                best_key = key\n        selected.append(best)\n\n    return selected\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MATCHED THREE-POSITION RECURRENCE PLAN v028bs")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("NO PIXELS ARE READ.")\n    print("No platephot requests are made.")\n    print("No candidate state is changed.")\n    print("DASCH obs_date interpreted as geocentric Julian Date midpoint.\\n")\n\n    if not INV.is_file():\n        print(f"FAIL missing input: {INV}")\n        return 2\n\n    inv = json.loads(INV.read_text(encoding="utf-8"))\n    by_target = inv.get("by_target", {})\n    target_coords = {\n        t["target"]: (float(t["ra_deg"]), float(t["dec_deg"]))\n        for t in inv.get("targets", [])\n    }\n\n    if sorted(target_coords) != sorted(TARGETS):\n        print(f"FAIL target coordinate set mismatch: {sorted(target_coords)}")\n        return 3\n\n    maps = {}\n    for target in TARGETS:\n        rows = by_target.get(target, {}).get("rows", [])\n        maps[target] = {\n            r["exposure_identity"]: r\n            for r in rows\n            if r.get("has_imaging")\n        }\n\n    shared_ids = set(maps[TARGETS[0]])\n    for target in TARGETS[1:]:\n        shared_ids &= set(maps[target])\n\n    counters = {\n        "shared_imaging": len(shared_ids),\n        "excluded_discovery_plate": 0,\n        "after_discovery_exclusion": 0,\n        "excluded_no_common_refcat": 0,\n        "after_common_refcat": 0,\n        "excluded_missing_or_unparseable_date": 0,\n        "eligible": 0,\n    }\n\n    eligible = []\n\n    for eid in sorted(shared_ids):\n        rows = {t: maps[t][eid] for t in TARGETS}\n\n        if any(r.get("plate_id") == DISCOVERY_PLATE for r in rows.values()):\n            counters["excluded_discovery_plate"] += 1\n            continue\n        counters["after_discovery_exclusion"] += 1\n\n        common = {"apass", "atlas"}\n        for r in rows.values():\n            common &= set(r.get("available_refcats", []))\n\n        if not common:\n            counters["excluded_no_common_refcat"] += 1\n            continue\n        counters["after_common_refcat"] += 1\n\n        refcat = "apass" if "apass" in common else "atlas"\n\n        plate_ids = {r.get("plate_id") for r in rows.values()}\n        solnums = {r.get("solnum") for r in rows.values()}\n        if len(plate_ids) != 1 or len(solnums) != 1:\n            raise RuntimeError(\n                f"shared exposure identity {eid} disagrees across targets: "\n                f"plates={plate_ids} solnums={solnums}"\n            )\n\n        # Same exposure identity should carry same obs_date. Parse all available\n        # values and require consistency to within one second where >1 are valid.\n        parsed = []\n        raw_dates = {}\n        for target, r in rows.items():\n            raw = r.get("obs_date_raw")\n            raw_dates[target] = raw\n            jd, iso = parse_obs_date(raw)\n            if jd is not None:\n                parsed.append((target, jd, iso))\n\n        if not parsed:\n            counters["excluded_missing_or_unparseable_date"] += 1\n            continue\n\n        jd_values = [x[1] for x in parsed]\n        if max(jd_values) - min(jd_values) > (1.0 / 86400.0):\n            raise RuntimeError(\n                f"shared exposure {eid} has inconsistent obs_date values: {raw_dates}"\n            )\n\n        jd = sum(jd_values) / len(jd_values)\n        _, iso = parse_obs_date(jd)\n\n        eligible.append({\n            "exposure_identity": eid,\n            "plate_id": next(iter(plate_ids)),\n            "solution_number": next(iter(solnums)),\n            "refcat": refcat,\n            "common_refcats": sorted(common),\n            "obs_date_jd": jd,\n            "obs_date_iso": iso,\n            "obs_date_raw_science25": rows["science25"].get("obs_date_raw"),\n            "science25_lim_mag_apass": rows["science25"].get("lim_mag_apass"),\n            "science25_lim_mag_atlas": rows["science25"].get("lim_mag_atlas"),\n            "q0030_lim_mag_apass": rows["q0030"].get("lim_mag_apass"),\n            "q0030_lim_mag_atlas": rows["q0030"].get("lim_mag_atlas"),\n            "q0344_lim_mag_apass": rows["q0344"].get("lim_mag_apass"),\n            "q0344_lim_mag_atlas": rows["q0344"].get("lim_mag_atlas"),\n        })\n\n    counters["eligible"] = len(eligible)\n    eligible.sort(key=lambda r: (r["obs_date_jd"], r["exposure_identity"]))\n\n    print("FILTER FUNNEL")\n    for key, value in counters.items():\n        print(f"  {key}: {value}")\n\n    if len(eligible) < PHASE1_EXPOSURES:\n        print(\n            f"\\nFAIL only {len(eligible)} eligible matched exposures after explicit funnel"\n        )\n        return 4\n\n    idxs = farthest_rank_indices(len(eligible), PHASE1_EXPOSURES)\n    selected_in_algorithm_order = [eligible[idx] for idx in idxs]\n    selection_rank = {\n        r["exposure_identity"]: n + 1\n        for n, r in enumerate(selected_in_algorithm_order)\n    }\n    phase1 = sorted(\n        selected_in_algorithm_order,\n        key=lambda r: (r["obs_date_jd"], r["exposure_identity"]),\n    )\n\n    queue = []\n    for exposure_seq, exp in enumerate(phase1, 1):\n        for target in TARGETS:\n            ra, dec = target_coords[target]\n            queue.append({\n                "request_seq": len(queue) + 1,\n                "phase": 1,\n                "phase_exposure_seq": exposure_seq,\n                "selection_rank": selection_rank[exp["exposure_identity"]],\n                "target": target,\n                "center_ra_deg": ra,\n                "center_dec_deg": dec,\n                "exposure_identity": exp["exposure_identity"],\n                "plate_id": exp["plate_id"],\n                "solution_number": exp["solution_number"],\n                "refcat": exp["refcat"],\n                "obs_date_jd": exp["obs_date_jd"],\n                "obs_date_iso": exp["obs_date_iso"] or "",\n                "obs_date_raw": exp["obs_date_raw_science25"],\n            })\n\n    apass_n = sum(r["refcat"] == "apass" for r in phase1)\n    atlas_n = sum(r["refcat"] == "atlas" for r in phase1)\n\n    print(f"\\nPhase 1 matched exposures: {len(phase1)}")\n    print(f"Phase 1 platephot requests: {len(queue)}")\n    print(f"Phase 1 refcat exposures: APASS={apass_n} ATLAS={atlas_n}")\n    print(\n        f"Phase 1 JD span: {phase1[0][\'obs_date_jd\']:.6f} -> "\n        f"{phase1[-1][\'obs_date_jd\']:.6f}"\n    )\n    if phase1[0]["obs_date_iso"] and phase1[-1]["obs_date_iso"]:\n        print(\n            f"Phase 1 calendar span: {phase1[0][\'obs_date_iso\']} -> "\n            f"{phase1[-1][\'obs_date_iso\']}"\n        )\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(queue[0].keys())\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(queue)\n\n    payload = {\n        "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PLAN_V028BS",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "platephot_requests_made": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "date_semantics": {\n            "source_field": "queryexps obs_date",\n            "official_semantics": "geocentric Julian Date of exposure midpoint",\n            "numeric_jd_primary": True,\n            "iso_fallback": True,\n        },\n        "design": {\n            "targets": list(TARGETS),\n            "matched_same_exposure_required": True,\n            "same_refcat_required_within_exposure": True,\n            "refcat_preference": "APASS if common to all three; otherwise ATLAS",\n            "phase1_exposure_count": PHASE1_EXPOSURES,\n            "phase1_request_count": len(queue),\n            "temporal_selection": (\n                "deterministic farthest-rank sampling over chronologically sorted "\n                "eligible shared exposures; endpoints seeded first"\n            ),\n            "descriptive_recurrence_radii_arcsec": [3.0, 5.0, 10.0],\n            "automatic_candidate_promotion": False,\n        },\n        "filter_funnel": counters,\n        "phase1": {\n            "exposure_count": len(phase1),\n            "request_count": len(queue),\n            "apass_exposures": apass_n,\n            "atlas_exposures": atlas_n,\n            "first_jd": phase1[0]["obs_date_jd"],\n            "last_jd": phase1[-1]["obs_date_jd"],\n            "first_iso": phase1[0]["obs_date_iso"],\n            "last_iso": phase1[-1]["obs_date_iso"],\n            "queue_csv": str(OUT_CSV.relative_to(ROOT)),\n            "exposures": phase1,\n        },\n        "interpretive_boundary": (\n            "Phase 1 is a matched recurrence calibration pass, not a complete "\n            "recurrence census. It tests the same 64 historical exposures at all "\n            "three positions and reports nearest fitted-source separations at "\n            "3/5/10 arcsec without automatic source classification."\n        ),\n        "next_gate": {\n            "matched_recurrence_phase1_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — Matched Three-Position Recurrence Plan v028bs",\n        "",\n        f"- Shared imaging exposures: **{counters[\'shared_imaging\']}**.",\n        f"- Eligible calibrated, dated, non-discovery matched exposures: **{len(eligible)}**.",\n        f"- Phase 1: **{len(phase1)} exposures / {len(queue)} platephot requests**.",\n        f"- Refcat: APASS on **{apass_n}** exposures; ATLAS on **{atlas_n}**.",\n        f"- JD span: **{phase1[0][\'obs_date_jd\']:.6f} → {phase1[-1][\'obs_date_jd\']:.6f}**.",\n        "",\n        "DASCH queryexps obs_date is treated as geocentric Julian Date of the exposure midpoint.",\n        "",\n        "Phase 1 is deliberately matched across #25, q0030, and q0344 and does not "\n        "promote any detection automatically.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'


def load_plan():
    spec = importlib.util.spec_from_file_location("v028bs_repair_test", PLAN_STAGE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import corrected v028bs")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.2.7a — v028bs DASCH JULIAN-DATE PARSER")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
    print("Only the v028bs planner implementation is replaced.\n")

    for p in (PLAN_STAGE, RUNNER, INIT, REGISTRY):
        if not p.is_file():
            print(f"FAIL missing required file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (PLAN_STAGE, RUNNER, INIT, REGISTRY):
        dst = BACKUP / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    PLAN_STAGE.write_text(PLAN_CONTENT, encoding="utf-8")
    try:
        py_compile.compile(str(PLAN_STAGE), doraise=True)
        print("Corrected v028bs compile: PASS")
    except Exception as exc:
        print(f"FAIL corrected v028bs compile: {type(exc).__name__}: {exc}")
        return 3

    try:
        mod = load_plan()

        jd, iso = mod.parse_obs_date("2433976.8125")
        if abs(jd - 2433976.8125) > 1e-12:
            raise RuntimeError(f"JD regression mismatch: {jd}")
        if iso is None or not iso.startswith("1951-"):
            raise RuntimeError(f"JD -> calendar regression unexpected: {iso!r}")

        jd2, iso2 = mod.parse_obs_date("1951-11-05T07:30:00+00:00")
        if jd2 is None or iso2 is None:
            raise RuntimeError("ISO fallback regression failed")

        bad_jd, bad_iso = mod.parse_obs_date("not-a-date")
        if bad_jd is not None or bad_iso is not None:
            raise RuntimeError("invalid-date regression failed")

        idxs = mod.farthest_rank_indices(100, 64)
        if len(idxs) != 64 or len(set(idxs)) != 64:
            raise RuntimeError("64-exposure deterministic selection regression failed")

        print("Date/selection regressions: PASS (numeric JD primary, ISO fallback)")
    except Exception as exc:
        print(f"FAIL date/selection regression: {type(exc).__name__}: {exc}")
        return 4

    runner = RUNNER.read_text(encoding="utf-8")
    runner = re.sub(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.2.8 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    INIT.write_text('__version__ = "0.2.8"\n', encoding="utf-8")

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
        print("\nREPAIR STATUS: FAIL")
        return 5

    try:
        sys.path.insert(0, str(ROOT))
        import automation.registry_order01 as regmod

        plan = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None) == "dasch_matched_recurrence_plan_v028bs"
        )
        exe = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None) == "dasch_matched_recurrence_phase1_v028bt"
        )
        if getattr(plan, "network_access", False):
            raise RuntimeError("v028bs unexpectedly requires network")
        if getattr(exe, "network_access", None) is not True:
            raise RuntimeError("v028bt network gate damaged")
        print("Registry import/StageContract regression: PASS")
    except Exception as exc:
        print(f"Registry import regression: FAIL: {type(exc).__name__}: {exc}")
        return 6

    print("\nREPAIR STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_matched_recurrence_plan_v028bs')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_matched_recurrence_phase1_v028bt')
    print("\nExpected status banner after repair: Transient automation v0.2.8 - Order01 registry status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
