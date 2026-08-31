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
STAGE = AUTO / "stages" / "inventory_science25_analogue_exposures_v028br.py"
BACKUP = AUTO / "backups" / "pre_v023"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport io\nimport json\nimport math\nimport time\nfrom collections import defaultdict\nfrom pathlib import Path\n\nimport requests\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nWORK = ROOT / "work" / "order01_native_full_v028" / "exposure_inventory_v028br"\n\nAR_JSON = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\n\nOUT_JSON = BASE / "order01_dasch_science25_analogue_exposure_inventory_v028br.json"\nOUT_CSV = BASE / "order01_dasch_science25_analogue_exposure_inventory_v028br.csv"\nOUT_QUEUE = BASE / "order01_dasch_science25_analogue_forced_photometry_opportunities_v028br.csv"\nOUT_MD = BASE / "ORDER01_DASCH_SCIENCE25_ANALOGUE_EXPOSURE_INVENTORY_V028BR.md"\n\nBASE_URL = "https://api.starglass.cfa.harvard.edu/public/"\nQUERYEXPS_PATH = "dasch/dr7/queryexps"\nTIMEOUT = 90\nTARGET_ORDERS = (30, 344)\nSCIENCE_RANK = 25\nDISCOVERY_PLATE = "ai43437"\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef i(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef s(v):\n    if v is None:\n        return None\n    x = str(v).strip()\n    if not x or x.lower() in ("nan", "none", "null", "--", "masked"):\n        return None\n    return x\n\n\ndef first(row, *keys):\n    for k in keys:\n        if k in row:\n            v = row[k]\n            if s(v) is not None:\n                return v\n    return None\n\n\ndef read_csv_file(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef parse_api_csv(obj):\n    if not isinstance(obj, list):\n        raise RuntimeError(f"expected JSON list of CSV strings; got {type(obj).__name__}")\n    if not obj:\n        return []\n    return list(csv.DictReader(io.StringIO("\\n".join(str(x) for x in obj))))\n\n\ndef post_json(path, payload, cache_path):\n    cache_path.parent.mkdir(parents=True, exist_ok=True)\n    if cache_path.is_file():\n        return json.loads(cache_path.read_text(encoding="utf-8")), True\n\n    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")\n    delays = (2, 5, 10)\n    last = None\n    for attempt in range(1, 4):\n        try:\n            r = requests.post(\n                url,\n                json=payload,\n                timeout=TIMEOUT,\n                headers={"accept": "application/json"},\n            )\n            if r.status_code in (408, 425, 429) or 500 <= r.status_code <= 599:\n                raise requests.HTTPError(f"retryable HTTP {r.status_code}", response=r)\n            r.raise_for_status()\n            obj = r.json()\n            tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")\n            tmp.write_text(json.dumps(obj, indent=2) + "\\n", encoding="utf-8")\n            tmp.replace(cache_path)\n            time.sleep(1.0)\n            return obj, False\n        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:\n            last = exc\n            if attempt == 3:\n                break\n            time.sleep(delays[attempt - 1])\n    raise RuntimeError(\n        f"POST {path} failed after 3 attempts: {type(last).__name__}: {last}"\n    )\n\n\ndef plate_id(series, platenum):\n    if series is None or platenum is None:\n        return None\n    return f"{str(series).lower()}{int(platenum):05d}"\n\n\ndef normalize_exposure(row, target):\n    series = s(first(row, "series", "Series"))\n    platenum = i(first(row, "platenum", "plateNum", "plate_num"))\n    mosnum = i(first(row, "mosnum", "mosNum", "mosaicNum"))\n    solnum = i(first(row, "solnum", "solNum", "solutionNumber"))\n    expnum = i(first(row, "expnum", "expNum", "exposureNum"))\n\n    rid_apass = s(first(row, "resultIdApass", "result_id_apass"))\n    rid_atlas = s(first(row, "resultIdAtlas", "result_id_atlas"))\n    nsol_apass = i(first(row, "nSolutionsApass", "n_solutions_apass"), 0) or 0\n    nsol_atlas = i(first(row, "nSolutionsAtlas", "n_solutions_atlas"), 0) or 0\n\n    has_imaging = mosnum is not None and solnum is not None\n    apass_cal = bool(rid_apass) or nsol_apass > 0\n    atlas_cal = bool(rid_atlas) or nsol_atlas > 0\n\n    pid = plate_id(series, platenum)\n    if has_imaging:\n        identity = f"{series}:{platenum}:{mosnum}:{solnum}"\n    else:\n        identity = f"{series}:{platenum}:log:{expnum}"\n\n    return {\n        "target": target,\n        "series": series,\n        "platenum": platenum,\n        "plate_id": pid,\n        "mosnum": mosnum,\n        "solnum": solnum,\n        "expnum": expnum,\n        "exposure_identity": identity,\n        "has_imaging": has_imaging,\n        "has_apass_calibration": apass_cal,\n        "has_atlas_calibration": atlas_cal,\n        "available_refcats": [\n            x for x, ok in (("apass", apass_cal), ("atlas", atlas_cal)) if ok\n        ],\n        "obs_date_raw": s(first(row, "obsDate", "obs_date")),\n        "exptime_min": f(first(row, "exptime", "expTime")),\n        "ra_deg": f(first(row, "raDeg", "ra_deg")),\n        "dec_deg": f(first(row, "decDeg", "dec_deg")),\n        "wcssource": s(first(row, "wcssource", "wcsSource")),\n        "edge_distance_cm": f(first(row, "edgeDistance", "edge_distance")),\n        "center_distance_cm": f(first(row, "centerDistance", "center_distance")),\n        "lim_mag_apass": f(first(row, "limMagApass", "lim_mag_apass")),\n        "lim_mag_atlas": f(first(row, "limMagAtlas", "lim_mag_atlas")),\n        "n_solutions_apass": nsol_apass,\n        "n_solutions_atlas": nsol_atlas,\n        "result_id_apass": rid_apass,\n        "result_id_atlas": rid_atlas,\n        "binflags": i(first(row, "binflags", "binFlags")),\n        "scannum": i(first(row, "scannum", "scanNum")),\n        "class": s(first(row, "class", "plateClass")),\n        "raw": row,\n    }\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — #25 / q0030 / q0344 EXPOSURE INVENTORY v028br")\n    print("=" * 128)\n    print("NETWORK ACCESS: TRUE (3 DASCH DR7 queryexps calls maximum).")\n    print("NO PIXELS ARE READ.")\n    print("NO platephot forced-photometry requests are made in this stage.")\n    print("Frozen transient detector is NOT rerun.")\n    print("No candidate state is changed.\\n")\n\n    for p in (AR_JSON, BJ, NATIVE):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    ar = json.loads(AR_JSON.read_text(encoding="utf-8"))\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    native_rows = read_csv_file(NATIVE)\n\n    science = {int(r["strict_rank"]): r for r in ar.get("science", [])}\n    if SCIENCE_RANK not in science:\n        print("FAIL science #25 missing")\n        return 3\n\n    s25_tile = str(science[25].get("tile_id", ""))\n    s25_idx = i(science[25].get("candidate_index"))\n    smatches = [\n        r for r in native_rows\n        if str(r.get("tile_id", "")) == s25_tile\n        and i(r.get("candidate_index")) == s25_idx\n    ]\n    if len(smatches) != 1:\n        print(\n            f"FAIL #25 native identity resolution: "\n            f"{s25_tile}::{s25_idx} matches={len(smatches)}"\n        )\n        return 3\n    s25_ra = f(smatches[0].get("ra_deg"))\n    s25_dec = f(smatches[0].get("dec_deg"))\n    if s25_ra is None or s25_dec is None:\n        print("FAIL #25 native RA/Dec unavailable")\n        return 3\n\n    success = {\n        int(r["queue_order"]): r\n        for r in bj.get("results", [])\n        if r.get("status") == "SUCCESS"\n    }\n    if any(o not in success for o in TARGET_ORDERS):\n        print("FAIL q0030/q0344 v028bj rows missing")\n        return 3\n\n    targets = [\n        {"target": "science25", "ra_deg": s25_ra, "dec_deg": s25_dec},\n        {\n            "target": "q0030",\n            "ra_deg": float(success[30]["ra_deg"]),\n            "dec_deg": float(success[30]["dec_deg"]),\n        },\n        {\n            "target": "q0344",\n            "ra_deg": float(success[344]["ra_deg"]),\n            "dec_deg": float(success[344]["dec_deg"]),\n        },\n    ]\n\n    by_target = {}\n    flat = []\n\n    for t in targets:\n        name = t["target"]\n        payload = {"ra_deg": t["ra_deg"], "dec_deg": t["dec_deg"]}\n        cache = WORK / f"{name}_queryexps.json"\n        obj, cache_used = post_json(QUERYEXPS_PATH, payload, cache)\n        raw_rows = parse_api_csv(obj)\n        rows = [normalize_exposure(r, name) for r in raw_rows]\n\n        # Require unique identity within each target\'s returned inventory.\n        identities = [r["exposure_identity"] for r in rows]\n        if len(set(identities)) != len(identities):\n            dups = sorted({x for x in identities if identities.count(x) > 1})\n            raise RuntimeError(f"{name}: duplicate exposure identities: {dups[:10]}")\n\n        imaging = [r for r in rows if r["has_imaging"]]\n        calibrated = [\n            r for r in imaging\n            if r["has_apass_calibration"] or r["has_atlas_calibration"]\n        ]\n        discovery = [r for r in rows if r["plate_id"] == DISCOVERY_PLATE]\n\n        by_target[name] = {\n            "query": payload,\n            "cache_used": cache_used,\n            "total_exposures": len(rows),\n            "with_imaging": len(imaging),\n            "with_any_photometric_calibration": len(calibrated),\n            "with_apass_calibration": sum(r["has_apass_calibration"] for r in imaging),\n            "with_atlas_calibration": sum(r["has_atlas_calibration"] for r in imaging),\n            "with_both_calibrations": sum(\n                r["has_apass_calibration"] and r["has_atlas_calibration"]\n                for r in imaging\n            ),\n            "discovery_plate_rows": discovery,\n            "rows": rows,\n        }\n\n        print(\n            f"{name}: total={len(rows)} imaging={len(imaging)} "\n            f"calibrated={len(calibrated)} "\n            f"APASS={by_target[name][\'with_apass_calibration\']} "\n            f"ATLAS={by_target[name][\'with_atlas_calibration\']} "\n            f"both={by_target[name][\'with_both_calibrations\']}"\n        )\n        if discovery:\n            for d in discovery:\n                print(\n                    f"  {DISCOVERY_PLATE}: sol={d[\'solnum\']} exp={d[\'expnum\']} "\n                    f"edge={d[\'edge_distance_cm\']}cm center={d[\'center_distance_cm\']}cm "\n                    f"APASS={d[\'has_apass_calibration\']} ATLAS={d[\'has_atlas_calibration\']}"\n                )\n        else:\n            print(f"  WARN: {DISCOVERY_PLATE} not returned for {name}")\n\n        flat.extend(rows)\n\n    # Imaging exposure intersections across targets.\n    target_sets = {}\n    for name, data in by_target.items():\n        target_sets[name] = {\n            r["exposure_identity"]\n            for r in data["rows"]\n            if r["has_imaging"]\n        }\n\n    names = ["science25", "q0030", "q0344"]\n    shared = {\n        "science25_q0030": sorted(target_sets["science25"] & target_sets["q0030"]),\n        "science25_q0344": sorted(target_sets["science25"] & target_sets["q0344"]),\n        "q0030_q0344": sorted(target_sets["q0030"] & target_sets["q0344"]),\n        "all_three": sorted(\n            target_sets["science25"]\n            & target_sets["q0030"]\n            & target_sets["q0344"]\n        ),\n    }\n\n    # Freeze every eligible forced-photometry opportunity, without yet choosing\n    # a scientific sampling threshold or preferred refcat.\n    queue = []\n    for name in names:\n        for r in by_target[name]["rows"]:\n            if not r["has_imaging"]:\n                continue\n            if not (r["has_apass_calibration"] or r["has_atlas_calibration"]):\n                continue\n            if r["plate_id"] == DISCOVERY_PLATE:\n                continue\n\n            target = next(t for t in targets if t["target"] == name)\n            queue.append({\n                "target": name,\n                "target_ra_deg": target["ra_deg"],\n                "target_dec_deg": target["dec_deg"],\n                "plate_id": r["plate_id"],\n                "series": r["series"],\n                "platenum": r["platenum"],\n                "mosnum": r["mosnum"],\n                "solution_number": r["solnum"],\n                "expnum": r["expnum"],\n                "obs_date_raw": r["obs_date_raw"],\n                "exptime_min": r["exptime_min"],\n                "physical_edge_distance_cm": r["edge_distance_cm"],\n                "physical_center_distance_cm": r["center_distance_cm"],\n                "lim_mag_apass": r["lim_mag_apass"],\n                "lim_mag_atlas": r["lim_mag_atlas"],\n                "apass_available": r["has_apass_calibration"],\n                "atlas_available": r["has_atlas_calibration"],\n                "available_refcats": ";".join(r["available_refcats"]),\n                "exposure_identity": r["exposure_identity"],\n                "shared_with_science25": (\n                    r["exposure_identity"] in target_sets["science25"]\n                    and name != "science25"\n                ),\n                "shared_with_q0030": (\n                    r["exposure_identity"] in target_sets["q0030"]\n                    and name != "q0030"\n                ),\n                "shared_with_q0344": (\n                    r["exposure_identity"] in target_sets["q0344"]\n                    and name != "q0344"\n                ),\n            })\n\n    queue.sort(\n        key=lambda r: (\n            r["target"],\n            r["obs_date_raw"] is None,\n            r["obs_date_raw"] or "",\n            r["plate_id"] or "",\n            r["solution_number"] if r["solution_number"] is not None else -1,\n        )\n    )\n\n    print("\\nSHARED IMAGING EXPOSURES")\n    for k, v in shared.items():\n        print(f"  {k}: {len(v)}")\n\n    print("\\nFORCED-PHOTOMETRY OPPORTUNITY QUEUE (not executed here)")\n    for name in names:\n        n = sum(r["target"] == name for r in queue)\n        print(f"  {name}: {n}")\n    print(f"  total target-exposure opportunities: {len(queue)}")\n\n    # Flatten exposure inventory without raw API blob.\n    exp_rows = []\n    for r in flat:\n        x = {k: v for k, v in r.items() if k not in ("raw", "available_refcats")}\n        x["available_refcats"] = ";".join(r["available_refcats"])\n        exp_rows.append(x)\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = sorted({k for r in exp_rows for k in r})\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(exp_rows)\n\n    with OUT_QUEUE.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(queue[0].keys()) if queue else [\n            "target", "plate_id", "solution_number", "available_refcats"\n        ]\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(queue)\n\n    payload = {\n        "stage": "ORDER01_DASCH_SCIENCE25_ANALOGUE_EXPOSURE_INVENTORY_V028BR",\n        "guards": {\n            "network_access": True,\n            "network_scope": "DASCH DR7 public queryexps only",\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "platephot_requests_made": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "targets": targets,\n        "by_target": by_target,\n        "shared_imaging_exposures": shared,\n        "forced_photometry_opportunity_count": len(queue),\n        "forced_photometry_opportunity_csv": str(OUT_QUEUE.relative_to(ROOT)),\n        "interpretive_boundary": (\n            "This stage inventories all DASCH exposures intersecting the three "\n            "positions and freezes every imaging+photometrically-calibrated "\n            "forced-photometry opportunity except the discovery plate. It does "\n            "not yet select a sampling threshold or issue any platephot request."\n        ),\n        "next_gate": {\n            "forced_photometry_recurrence_plan_may_be_built": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — #25 / q0030 / q0344 Exposure Inventory v028br",\n        "",\n        "| target | total exposures | imaging | calibrated | APASS | ATLAS |",\n        "|---|---:|---:|---:|---:|---:|",\n    ]\n    for name in names:\n        d = by_target[name]\n        md.append(\n            f"| {name} | {d[\'total_exposures\']} | {d[\'with_imaging\']} | "\n            f"{d[\'with_any_photometric_calibration\']} | "\n            f"{d[\'with_apass_calibration\']} | {d[\'with_atlas_calibration\']} |"\n        )\n    md += [\n        "",\n        "## Shared imaging exposures",\n        "",\n        f"- #25 + q0030: **{len(shared[\'science25_q0030\'])}**",\n        f"- #25 + q0344: **{len(shared[\'science25_q0344\'])}**",\n        f"- q0030 + q0344: **{len(shared[\'q0030_q0344\'])}**",\n        f"- all three: **{len(shared[\'all_three\'])}**",\n        "",\n        f"Frozen non-discovery forced-photometry opportunities: **{len(queue)}**.",\n        "",\n        "No platephot calls or pixel reads were performed.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_QUEUE}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_science25_analogue_exposure_inventory_v028br",
        title="Inventory all DR7 exposures intersecting #25, q0030 and q0344",
        script="automation/stages/inventory_science25_analogue_exposures_v028br.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_physical_morphology_v028ar_r1.json",
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_science25_analogue_exposure_inventory_v028br.json",
        ),
        dependencies=("dasch_science25_analogue_catalog_provenance_v028bq",),
        network_access=True,
        notes="Three cached queryexps calls maximum; freezes all imaging+calibrated recurrence opportunities; no platephot/pixels/state mutation.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_science25_analogue_exposure_inventory_v028br"' in text:
        return text, "already registered"

    tree = ast.parse(text)
    container = None
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
            container = value
            break

    if container is None:
        raise RuntimeError("ORDER01_STAGES list/tuple not found")

    lines = text.splitlines(keepends=True)
    lines.insert(container.end_lineno - 1, "\n" + ENTRY.rstrip() + "\n")
    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted before ORDER01_STAGES closing line {container.end_lineno}"


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION UPGRADE v0.2.5 — #25 ANALOGUE EXPOSURE INVENTORY")
    print("=" * 112)
    print("THE UPGRADE ITSELF MAKES NO NETWORK CALLS.")
    print("Registered v028br requires explicit --allow-network.")
    print("NO PIXELS ARE READ.")
    print("No platephot requests are made by v028br.\n")

    for p in (REGISTRY, RUNNER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, INIT):
        if p.is_file():
            dst = BACKUP / p.name
            if not dst.exists():
                shutil.copy2(p, dst)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_CONTENT, encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)
    print(f"Stage validated: {STAGE.relative_to(ROOT)}")

    reg = REGISTRY.read_text(encoding="utf-8")
    reg, note = register_stage(reg)
    REGISTRY.write_text(reg, encoding="utf-8")
    print(f"Registry: {note}")

    runner = RUNNER.read_text(encoding="utf-8")
    runner = re.sub(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.2.5 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    INIT.write_text('__version__ = "0.2.5"\n', encoding="utf-8")

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

    # Critical import/instantiation regression, not syntax-only.
    try:
        sys.path.insert(0, str(ROOT))
        import automation.registry_order01 as regmod

        target = next(
            st for st in regmod.ORDER01_STAGES
            if getattr(st, "stage_id", None)
            == "dasch_science25_analogue_exposure_inventory_v028br"
        )
        if getattr(target, "network_access", None) is not True:
            raise RuntimeError("registered v028br network_access is not True")
        print("\nRegistry import regression: PASS (network_access=True)")
    except Exception as exc:
        print(f"\nRegistry import regression: FAIL: {type(exc).__name__}: {exc}")
        return 5

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_analogue_exposure_inventory_v028br'
    )
    print("\nNo platephot calls occur in v028br; it only inventories opportunities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
