#!/usr/bin/env python3
from pathlib import Path
import ast
import py_compile
import re
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "execute_platewide_morphology_metrics_v028bj.py"
BACKUP = AUTO / "backups" / "pre_v015"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport hashlib\nimport importlib.util\nimport json\nimport math\nimport os\nimport sys\nfrom collections import Counter\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\n\nQUEUE = AUTO / "queues" / "ai43437_platewide_morphology_v028bg.json"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\nSTRICT = BASE / "order01_strict_match_triage_v028.csv"\nCAL = BASE / "order01_dasch_morphology_pixel_calibration_v028bi.json"\nAR = ROOT / "tools" / "audit_order01_dasch_physical_morphology_v028ar_r1.py"\nAS = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\n\nCHECKPOINT = AUTO / "state" / "ai43437_morphology_full_v028bj.json"\nPROGRESS = BASE / "order01_dasch_platewide_morphology_progress_v028bj.json"\nOUT_JSON = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nOUT_CSV = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.csv"\nOUT_MD = BASE / "ORDER01_DASCH_PLATEWIDE_MORPHOLOGY_METRICS_V028BJ.md"\n\nEXPECTED_AR_SHA = "a22d9c511250ab0f0b375e5e483248b9f366482364d8c31eae6d5413d529360a"\nEXPECTED_AS_SHA = "95084cb6e64934ec18686b30021c69b07605a938c5ec9169aadf26629877188f"\nEXPECTED_QUEUE = 2596\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\nPATCH_R = 24\nEXPECTED_PATCH_SHAPE = (49, 49)\nSCIENCE_EXCLUSION_PX = 52.0\nDEFAULT_BATCH = 100\nMAX_BATCH = 500\n\n\ndef sha256(path):\n    h = hashlib.sha256()\n    with path.open("rb") as fh:\n        for chunk in iter(lambda: fh.read(1024 * 1024), b""):\n            h.update(chunk)\n    return h.hexdigest()\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef i(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef write_json(path, obj):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n", encoding="utf-8")\n    tmp.replace(path)\n\n\ndef load_module(path, name):\n    spec = importlib.util.spec_from_file_location(name, path)\n    if spec is None or spec.loader is None:\n        raise RuntimeError(f"cannot import {path}")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef jsonable(x):\n    if isinstance(x, dict):\n        return {str(k): jsonable(v) for k, v in x.items()}\n    if isinstance(x, (list, tuple)):\n        return [jsonable(v) for v in x]\n    if isinstance(x, np.ndarray):\n        return x.tolist()\n    if isinstance(x, np.generic):\n        return x.item()\n    if isinstance(x, Path):\n        return str(x)\n    if isinstance(x, (str, int, float, bool)) or x is None:\n        return x\n    return repr(x)\n\n\ndef tile_and_transform(hit):\n    if hit is None:\n        return None, None\n    if isinstance(hit, dict):\n        if "tile" in hit:\n            return hit.get("tile"), hit.get("transform")\n        return hit, hit.get("transform")\n    if isinstance(hit, (tuple, list)):\n        if len(hit) >= 2:\n            return hit[0], hit[1]\n        if len(hit) == 1:\n            return hit[0], None\n    return hit, None\n\n\ndef transform_from_mapping(transforms, tile, tile_id):\n    if not isinstance(transforms, dict):\n        return None\n\n    candidates = [tile_id]\n    if isinstance(tile, dict):\n        for k in ("tile_id", "id", "path", "file", "name"):\n            if tile.get(k) is not None:\n                candidates.extend([tile.get(k), str(tile.get(k))])\n\n    for key in candidates:\n        if key in transforms:\n            return transforms[key]\n\n    for key, val in transforms.items():\n        if isinstance(val, dict):\n            strings = {str(x) for x in val.values() if isinstance(x, (str, Path))}\n            if tile_id in strings:\n                return val\n        if str(key) == tile_id:\n            return val\n    return None\n\n\ndef patch_from_result(obj):\n    if isinstance(obj, np.ndarray):\n        return obj\n    if isinstance(obj, (tuple, list)):\n        for v in obj:\n            if isinstance(v, np.ndarray):\n                return v\n    if isinstance(obj, dict):\n        for k in ("patch", "array", "data", "pixels"):\n            if isinstance(obj.get(k), np.ndarray):\n                return obj[k]\n    raise RuntimeError(f"extract_patch returned no ndarray ({type(obj).__name__})")\n\n\ndef batch_size():\n    raw = os.environ.get("TRANSIENT_MORPH_BATCH_SIZE", str(DEFAULT_BATCH))\n    try:\n        n = int(raw)\n    except Exception:\n        n = DEFAULT_BATCH\n    return max(1, min(MAX_BATCH, n))\n\n\ndef load_checkpoint():\n    if not CHECKPOINT.is_file():\n        return {\n            "stage": "ORDER01_DASCH_PLATEWIDE_MORPHOLOGY_METRICS_V028BJ",\n            "queue_count": EXPECTED_QUEUE,\n            "results": {},\n        }\n    cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))\n    if int(cp.get("queue_count", -1)) != EXPECTED_QUEUE:\n        raise RuntimeError("checkpoint queue_count mismatch")\n    if not isinstance(cp.get("results"), dict):\n        raise RuntimeError("checkpoint results is not a dict")\n    return cp\n\n\ndef science_distance(gx, gy, science_xy):\n    return min(math.hypot(gx - sx, gy - sy) for sx, sy in science_xy)\n\n\ndef progress_payload(cp, batch_n, eligible_total):\n    counts = Counter(r.get("status") for r in cp["results"].values())\n    terminal = sum(counts.values())\n    success = counts.get("SUCCESS", 0)\n    excluded = counts.get("EXCLUDED_SCIENCE_PATCH_PROXIMITY", 0)\n    unusable = counts.get("UNUSABLE_PATCH_SHAPE", 0)\n    return {\n        "stage": "ORDER01_DASCH_PLATEWIDE_MORPHOLOGY_METRICS_V028BJ",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": True,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "queue_count": EXPECTED_QUEUE,\n        "eligible_after_science_proximity_exclusion": eligible_total,\n        "processed_terminal": terminal,\n        "success_usable": success,\n        "excluded_science_patch_proximity_no_pixel_read": excluded,\n        "unusable_patch_shape_after_non_science_pixel_read": unusable,\n        "remaining": EXPECTED_QUEUE - terminal,\n        "batch_size": batch_n,\n        "status_counts": dict(counts),\n    }\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — FULL RESUMABLE PLATE-WIDE MORPHOLOGY METRICS v028bj")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE READ: TRUE.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (QUEUE, NATIVE, STRICT, CAL, AR, AS):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    if sha256(AR) != EXPECTED_AR_SHA:\n        print("FAIL v028ar_r1 source hash changed")\n        return 3\n    if sha256(AS) != EXPECTED_AS_SHA:\n        print("FAIL v028as source hash changed")\n        return 3\n\n    cal = json.loads(CAL.read_text(encoding="utf-8"))\n    if not cal.get("executor_gate", {}).get("full_2596_control_pixel_executor_may_be_built"):\n        print("FAIL v028bi executor gate is not enabled")\n        return 3\n    if int(cal.get("extract_patch_radius_px", -1)) != PATCH_R:\n        print("FAIL v028bi patch-radius mismatch")\n        return 3\n\n    qobj = json.loads(QUEUE.read_text(encoding="utf-8"))\n    items = list(qobj.get("items", []))\n    if len(items) != EXPECTED_QUEUE:\n        print(f"FAIL expected queue {EXPECTED_QUEUE}, got {len(items)}")\n        return 3\n\n    orders = [int(x["queue_order"]) for x in items]\n    if orders != list(range(1, EXPECTED_QUEUE + 1)):\n        print("FAIL queue_order is not contiguous 1..2596")\n        return 3\n\n    native_rows = read_csv(NATIVE)\n    native_lookup = {\n        (str(r.get("tile_id", "")), i(r.get("candidate_index"))): r\n        for r in native_rows\n    }\n\n    science_keys = set()\n    for r in read_csv(STRICT):\n        rank = i(r.get("strict_rank"))\n        if rank in SCIENCE_RANKS:\n            science_keys.add((str(r.get("dasch_tile_id", "")), i(r.get("dasch_candidate_index"))))\n    if len(science_keys) != 6:\n        print(f"FAIL expected 6 science keys, got {len(science_keys)}")\n        return 3\n\n    science_xy = []\n    for key in science_keys:\n        nr = native_lookup.get(key)\n        if nr is None:\n            print(f"FAIL missing science native row {key}")\n            return 3\n        gx, gy = f(nr.get("global_x")), f(nr.get("global_y"))\n        if gx is None or gy is None:\n            print(f"FAIL science global coordinates missing {key}")\n            return 3\n        science_xy.append((gx, gy))\n\n    # Resolve all queue global coordinates without reading pixels and freeze which\n    # items are eligible for pixel access.\n    resolved = {}\n    excluded_orders = set()\n    for item in items:\n        key = (str(item["tile_id"]), i(item["candidate_index"]))\n        nr = native_lookup.get(key)\n        if nr is None:\n            print(f"FAIL queue native row missing {key}")\n            return 3\n        gx, gy = f(nr.get("global_x")), f(nr.get("global_y"))\n        if gx is None or gy is None:\n            print(f"FAIL queue global coordinates missing {key}")\n            return 3\n        dist = science_distance(gx, gy, science_xy)\n        resolved[int(item["queue_order"])] = (item, nr, gx, gy, dist)\n        if dist <= SCIENCE_EXCLUSION_PX:\n            excluded_orders.add(int(item["queue_order"]))\n\n    eligible_total = EXPECTED_QUEUE - len(excluded_orders)\n\n    cp = load_checkpoint()\n\n    # Any science-proximity item is dispositioned before tile/pixel access.\n    changed = False\n    for order in sorted(excluded_orders):\n        k = str(order)\n        prior = cp["results"].get(k)\n        if prior is None:\n            item, nr, gx, gy, dist = resolved[order]\n            cp["results"][k] = {\n                "queue_order": order,\n                "tile_id": str(item["tile_id"]),\n                "candidate_index": int(item["candidate_index"]),\n                "status": "EXCLUDED_SCIENCE_PATCH_PROXIMITY",\n                "science_nearest_center_distance_px": dist,\n                "pixel_read": False,\n            }\n            changed = True\n        elif prior.get("status") != "EXCLUDED_SCIENCE_PATCH_PROXIMITY":\n            print(f"FAIL checkpoint conflict at science-proximity q{order:04d}")\n            return 4\n\n    if changed:\n        write_json(CHECKPOINT, cp)\n\n    pending = [\n        order for order in orders\n        if str(order) not in cp["results"]\n    ]\n\n    bsize = batch_size()\n    work_orders = pending[:bsize]\n\n    counts_before = Counter(r.get("status") for r in cp["results"].values())\n    print(f"Queue items:                         {EXPECTED_QUEUE}")\n    print(f"Science-proximity excluded:          {len(excluded_orders)}")\n    print(f"Pixel-eligible controls:             {eligible_total}")\n    print(f"Already terminal/checkpointed:       {sum(counts_before.values())}")\n    print(f"Pending before batch:                {len(pending)}")\n    print(f"Batch size:                          {bsize}")\n\n    if work_orders:\n        ar = load_module(AR, "validated_v028ar_r1_full_metrics")\n        ash = load_module(AS, "validated_v028as_full_metrics")\n        tiles = ar.discover_tiles()\n        transforms = ar.infer_tile_transforms(tiles, native_rows)\n\n        expected_metric_keys = tuple(sorted(cal.get("metric_keys", [])))\n        if len(expected_metric_keys) != 24:\n            print(f"FAIL calibrated metric schema expected 24 fields, got {len(expected_metric_keys)}")\n            return 4\n\n        for pos, order in enumerate(work_orders, 1):\n            item, nr, gx, gy, dist = resolved[order]\n            print(\n                f"[{pos:03d}/{len(work_orders):03d}] q{order:04d} "\n                f"tile={item[\'tile_id\']} snr={item.get(\'snr\')}"\n            )\n\n            try:\n                hit = ar.tile_for_global(tiles, transforms, gx, gy)\n                tile, transform = tile_and_transform(hit)\n                if tile is None:\n                    raise RuntimeError("tile_for_global returned no tile")\n                if transform is None:\n                    transform = transform_from_mapping(transforms, tile, str(item["tile_id"]))\n                if transform is None:\n                    raise RuntimeError("could not resolve tile transform")\n\n                local = ar.global_to_local(tile, transform, gx, gy)\n                if not isinstance(local, (tuple, list)) or len(local) < 2:\n                    raise RuntimeError("global_to_local returned invalid coordinates")\n                lx, ly = float(local[0]), float(local[1])\n\n                patch = patch_from_result(ar.extract_patch(tile, lx, ly))\n\n                if tuple(patch.shape) != EXPECTED_PATCH_SHAPE:\n                    result = {\n                        "queue_order": order,\n                        "tile_id": str(item["tile_id"]),\n                        "candidate_index": int(item["candidate_index"]),\n                        "global_x": gx,\n                        "global_y": gy,\n                        "local_x": lx,\n                        "local_y": ly,\n                        "science_nearest_center_distance_px": dist,\n                        "status": "UNUSABLE_PATCH_SHAPE",\n                        "pixel_read": True,\n                        "patch_shape": list(patch.shape),\n                    }\n                    cp["results"][str(order)] = result\n                    write_json(CHECKPOINT, cp)\n                    print(f"    UNUSABLE patch_shape={patch.shape}")\n                    continue\n\n                metrics = ar.raw_metrics(patch, 1)\n                if not isinstance(metrics, dict):\n                    raise RuntimeError("raw_metrics did not return dict")\n                keys = tuple(sorted(metrics.keys()))\n                if keys != expected_metric_keys:\n                    raise RuntimeError(\n                        f"raw_metrics schema drift: got {keys}, expected {expected_metric_keys}"\n                    )\n\n                derived = ash.derived(metrics)\n\n                result = {\n                    "queue_order": order,\n                    "tile_id": str(item["tile_id"]),\n                    "candidate_index": int(item["candidate_index"]),\n                    "ra_deg": float(item["ra_deg"]),\n                    "dec_deg": float(item["dec_deg"]),\n                    "snr": item.get("snr"),\n                    "global_x": gx,\n                    "global_y": gy,\n                    "local_x": lx,\n                    "local_y": ly,\n                    "science_nearest_center_distance_px": dist,\n                    "status": "SUCCESS",\n                    "pixel_read": True,\n                    "patch_shape": list(patch.shape),\n                    "patch_min": float(np.nanmin(patch)),\n                    "patch_max": float(np.nanmax(patch)),\n                    "raw_metrics": jsonable(metrics),\n                    "derived": jsonable(derived),\n                }\n                cp["results"][str(order)] = result\n                write_json(CHECKPOINT, cp)\n                print(\n                    f"    SUCCESS patch=49x49 metrics={len(metrics)} "\n                    f"derivedType={type(derived).__name__}"\n                )\n\n            except KeyboardInterrupt:\n                write_json(CHECKPOINT, cp)\n                write_json(PROGRESS, progress_payload(cp, bsize, eligible_total))\n                print("\\nINTERRUPTED: checkpoint written; rerun to resume.")\n                return 10\n            except Exception as exc:\n                # Transform/schema/helper failures are terminal: preserve everything\n                # already completed rather than silently changing methodology.\n                cp["results"][str(order)] = {\n                    "queue_order": order,\n                    "tile_id": str(item["tile_id"]),\n                    "candidate_index": int(item["candidate_index"]),\n                    "status": "FAILED_TERMINAL",\n                    "pixel_read": False,\n                    "error": f"{type(exc).__name__}: {exc}",\n                }\n                write_json(CHECKPOINT, cp)\n                write_json(PROGRESS, progress_payload(cp, bsize, eligible_total))\n                print(f"    FAILED_TERMINAL {type(exc).__name__}: {exc}")\n                return 5\n\n    prog = progress_payload(cp, bsize, eligible_total)\n    write_json(PROGRESS, prog)\n\n    terminal = len(cp["results"])\n    remaining = EXPECTED_QUEUE - terminal\n    print("\\nBATCH SUMMARY")\n    print(f"  terminal/checkpointed: {terminal}/{EXPECTED_QUEUE}")\n    print(f"  usable successes:      {prog[\'success_usable\']}")\n    print(f"  excluded no-pixel:     {prog[\'excluded_science_patch_proximity_no_pixel_read\']}")\n    print(f"  unusable patch shape:  {prog[\'unusable_patch_shape_after_non_science_pixel_read\']}")\n    print(f"  remaining:             {remaining}")\n\n    if remaining > 0:\n        print("\\nSTAGE STATUS: IN_PROGRESS")\n        return 10\n\n    # Final completion requires no failed terminal items.\n    status_counts = Counter(r.get("status") for r in cp["results"].values())\n    if status_counts.get("FAILED_TERMINAL", 0):\n        print("FAIL terminal failures exist in completed checkpoint")\n        return 5\n\n    ordered_results = [cp["results"][str(order)] for order in orders]\n    successes = [r for r in ordered_results if r.get("status") == "SUCCESS"]\n    excluded = [r for r in ordered_results if r.get("status") == "EXCLUDED_SCIENCE_PATCH_PROXIMITY"]\n    unusable = [r for r in ordered_results if r.get("status") == "UNUSABLE_PATCH_SHAPE"]\n\n    payload = {\n        "stage": "ORDER01_DASCH_PLATEWIDE_MORPHOLOGY_METRICS_V028BJ",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": True,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "source_hashes": {\n            "v028ar_r1": EXPECTED_AR_SHA,\n            "v028as": EXPECTED_AS_SHA,\n        },\n        "queue_count": EXPECTED_QUEUE,\n        "science_patch_exclusion_radius_px": SCIENCE_EXCLUSION_PX,\n        "expected_patch_shape": list(EXPECTED_PATCH_SHAPE),\n        "summary": {\n            "complete": True,\n            "pixel_eligible_after_science_proximity_exclusion": eligible_total,\n            "usable_metric_rows": len(successes),\n            "excluded_science_patch_proximity_no_pixel_read": len(excluded),\n            "unusable_patch_shape_after_non_science_pixel_read": len(unusable),\n            "status_counts": dict(status_counts),\n        },\n        "metric_keys": cal.get("metric_keys", []),\n        "results": ordered_results,\n        "next_gate": {\n            "platewide_stellar_shape_prevalence_classifier_may_run": len(successes) > 0,\n        },\n        "interpretive_boundary": (\n            "This stage acquires the frozen v028ar_r1 raw morphology metrics and "\n            "v028as derived vectors for the plate-wide non-science +1/>10arcsec "\n            "control population. It does not classify controls as stellar-like "\n            "and does not estimate astrophysical-transient prevalence."\n        ),\n    }\n    write_json(OUT_JSON, payload)\n\n    flat = []\n    for r in ordered_results:\n        flat.append({\n            "queue_order": r.get("queue_order"),\n            "tile_id": r.get("tile_id"),\n            "candidate_index": r.get("candidate_index"),\n            "status": r.get("status"),\n            "pixel_read": r.get("pixel_read"),\n            "ra_deg": r.get("ra_deg"),\n            "dec_deg": r.get("dec_deg"),\n            "snr": r.get("snr"),\n            "global_x": r.get("global_x"),\n            "global_y": r.get("global_y"),\n            "local_x": r.get("local_x"),\n            "local_y": r.get("local_y"),\n            "science_nearest_center_distance_px": r.get("science_nearest_center_distance_px"),\n            "patch_shape": json.dumps(r.get("patch_shape")),\n            "raw_metrics_json": json.dumps(r.get("raw_metrics"), sort_keys=True) if r.get("raw_metrics") is not None else None,\n            "derived_json": json.dumps(r.get("derived"), sort_keys=True) if r.get("derived") is not None else None,\n            "error": r.get("error"),\n        })\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(flat[0].keys())\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(flat)\n\n    OUT_MD.write_text(\n        "# ORDER 01 — Plate-wide Morphology Metrics v028bj\\n\\n"\n        f"- Frozen queue: **{EXPECTED_QUEUE}** controls.\\n"\n        f"- Science-proximity exclusions without pixel access: **{len(excluded)}**.\\n"\n        f"- Usable metric rows: **{len(successes)}**.\\n"\n        f"- Unusable patch-shape rows after non-science read: **{len(unusable)}**.\\n"\n        "- Science pixels read: **false**.\\n"\n        "- Non-science pixels read: **true**.\\n"\n        "- Detector rerun: **false**.\\n\\n"\n        "This is a metric-acquisition stage, not a stellar-like prevalence result.\\n",\n        encoding="utf-8",\n    )\n\n    print("\\nFULL MORPHOLOGY METRIC ACQUISITION COMPLETE")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_platewide_morphology_metrics_v028bj",
        title="Full resumable plate-wide DASCH morphology metric acquisition",
        script="automation/stages/execute_platewide_morphology_metrics_v028bj.py",
        requires=(
            "automation/queues/ai43437_platewide_morphology_v028bg.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
            "results/order01_native_full_v028/order01_strict_match_triage_v028.csv",
            "results/order01_native_full_v028/order01_dasch_morphology_pixel_calibration_v028bi.json",
            "tools/audit_order01_dasch_physical_morphology_v028ar_r1.py",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
        ),
        dependencies=("dasch_morphology_pixel_calibration_v028bi",),
        non_science_pixels_read=True,
        retryable=False,
        notes="Checkpointed 2596-control metric acquisition; science-proximity patches excluded before pixel access; return code 10 means progress.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_platewide_morphology_metrics_v028bj"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.5 — FULL PLATE-WIDE MORPHOLOGY METRICS")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("THE UPGRADE ITSELF READS NO PIXELS.")
    print("The registered v028bj stage WILL read non-science control pixels.")
    print("No candidate state is changed.\n")

    for p in (REGISTRY, RUNNER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, AUTO / "__init__.py"):
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
    runner, _ = re.subn(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.1.5 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.1.5"\n', encoding="utf-8")

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

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_platewide_morphology_metrics_v028bj'
    )
    print("\nNo --allow-network is required.")
    print("Default morphology batch size is 100; progress is checkpointed after every item.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
