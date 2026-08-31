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
STAGE = AUTO / "stages" / "calibrate_morphology_pixels_v028bi.py"
BACKUP = AUTO / "backups" / "pre_v014"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport hashlib\nimport importlib.util\nimport inspect\nimport json\nimport math\nimport sys\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\n\nQUEUE = AUTO / "queues" / "ai43437_platewide_morphology_v028bg.json"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\nSTRICT = BASE / "order01_strict_match_triage_v028.csv"\nCONTRACT = BASE / "order01_dasch_morphology_executor_contract_v028bh.json"\nAR = ROOT / "tools" / "audit_order01_dasch_physical_morphology_v028ar_r1.py"\nAS = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\n\nOUT_JSON = BASE / "order01_dasch_morphology_pixel_calibration_v028bi.json"\nOUT_CSV = BASE / "order01_dasch_morphology_pixel_calibration_v028bi.csv"\nOUT_MD = BASE / "ORDER01_DASCH_MORPHOLOGY_PIXEL_CALIBRATION_V028BI.md"\n\nEXPECTED_AR_SHA = "a22d9c511250ab0f0b375e5e483248b9f366482364d8c31eae6d5413d529360a"\nEXPECTED_AS_SHA = "95084cb6e64934ec18686b30021c69b07605a938c5ec9169aadf26629877188f"\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\nSAMPLE_N = 24\n\n\ndef sha256(path):\n    h = hashlib.sha256()\n    with path.open("rb") as fh:\n        for chunk in iter(lambda: fh.read(1024 * 1024), b""):\n            h.update(chunk)\n    return h.hexdigest()\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef i(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef load_module(path, name):\n    spec = importlib.util.spec_from_file_location(name, path)\n    if spec is None or spec.loader is None:\n        raise RuntimeError(f"cannot import {path}")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef jsonable(x):\n    if isinstance(x, dict):\n        return {str(k): jsonable(v) for k, v in x.items()}\n    if isinstance(x, (list, tuple)):\n        return [jsonable(v) for v in x]\n    if isinstance(x, np.ndarray):\n        return x.tolist()\n    if isinstance(x, np.generic):\n        return x.item()\n    if isinstance(x, Path):\n        return str(x)\n    if isinstance(x, (str, int, float, bool)) or x is None:\n        return x\n    return repr(x)\n\n\ndef tile_and_transform(hit):\n    if hit is None:\n        return None, None\n\n    if isinstance(hit, dict):\n        if "tile" in hit:\n            return hit.get("tile"), hit.get("transform")\n        return hit, hit.get("transform")\n\n    if isinstance(hit, (tuple, list)):\n        if len(hit) >= 2:\n            return hit[0], hit[1]\n        if len(hit) == 1:\n            return hit[0], None\n\n    return hit, None\n\n\ndef patch_from_result(obj):\n    if isinstance(obj, np.ndarray):\n        return obj\n    if isinstance(obj, (tuple, list)):\n        for v in obj:\n            if isinstance(v, np.ndarray):\n                return v\n    if isinstance(obj, dict):\n        for k in ("patch", "array", "data", "pixels"):\n            if isinstance(obj.get(k), np.ndarray):\n                return obj[k]\n    raise RuntimeError(\n        f"extract_patch return did not contain ndarray: {type(obj).__name__}"\n    )\n\n\ndef transform_from_mapping(transforms, tile, tile_id):\n    if not isinstance(transforms, dict):\n        return None\n\n    candidates = [tile_id]\n    if isinstance(tile, dict):\n        for k in ("tile_id", "id", "path", "file", "name"):\n            if tile.get(k) is not None:\n                candidates.extend([tile.get(k), str(tile.get(k))])\n\n    for key in candidates:\n        if key in transforms:\n            return transforms[key]\n\n    # Last resort: a transform value may itself identify the tile.\n    for key, val in transforms.items():\n        if isinstance(val, dict):\n            strings = {str(x) for x in val.values() if isinstance(x, (str, Path))}\n            if tile_id in strings:\n                return val\n        if str(key) == tile_id:\n            return val\n    return None\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MORPHOLOGY PIXEL CALIBRATION v028bi")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE READ: TRUE.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (QUEUE, NATIVE, STRICT, CONTRACT, AR, AS):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    if sha256(AR) != EXPECTED_AR_SHA:\n        print("FAIL v028ar_r1 source hash changed")\n        return 3\n    if sha256(AS) != EXPECTED_AS_SHA:\n        print("FAIL v028as source hash changed")\n        return 3\n\n    ar = load_module(AR, "validated_v028ar_r1_pixel_cal")\n    ash = load_module(AS, "validated_v028as_pixel_cal")\n\n    required_ar = (\n        "discover_tiles", "infer_tile_transforms", "tile_for_global",\n        "global_to_local", "extract_patch", "raw_metrics",\n    )\n    required_as = ("derived", "robust_center_scale", "distance")\n    for name in required_ar:\n        if not hasattr(ar, name):\n            print(f"FAIL v028ar_r1 missing {name}")\n            return 3\n    for name in required_as:\n        if not hasattr(ash, name):\n            print(f"FAIL v028as missing {name}")\n            return 3\n\n    sig = inspect.signature(ar.extract_patch)\n    if "r" not in sig.parameters:\n        print("FAIL extract_patch has no frozen r parameter")\n        return 3\n    r_default = sig.parameters["r"].default\n    if r_default is inspect._empty:\n        print("FAIL extract_patch r has no default")\n        return 3\n    patch_r = int(r_default)\n\n    queue_obj = json.loads(QUEUE.read_text(encoding="utf-8"))\n    items = list(queue_obj.get("items", []))\n    if len(items) != 2596:\n        print(f"FAIL expected 2596 morphology controls, got {len(items)}")\n        return 3\n\n    native_rows = read_csv(NATIVE)\n    native_lookup = {\n        (str(r.get("tile_id", "")), i(r.get("candidate_index"))): r\n        for r in native_rows\n    }\n\n    science_keys = set()\n    for r in read_csv(STRICT):\n        rank = i(r.get("strict_rank"))\n        if rank in SCIENCE_RANKS:\n            science_keys.add(\n                (str(r.get("dasch_tile_id", "")), i(r.get("dasch_candidate_index")))\n            )\n    if len(science_keys) != 6:\n        print(f"FAIL expected 6 science keys, got {len(science_keys)}")\n        return 3\n\n    science_xy = []\n    for key in science_keys:\n        nr = native_lookup.get(key)\n        if nr is None:\n            print(f"FAIL science native row missing: {key}")\n            return 3\n        science_xy.append((f(nr.get("global_x")), f(nr.get("global_y"))))\n\n    # Deterministic amplitude/queue-spread sample; exclude controls whose extracted\n    # patch could overlap a science patch.\n    positions = np.linspace(0, len(items) - 1, SAMPLE_N * 4, dtype=int)\n    selected = []\n    min_sep_px = 2 * patch_r + 4\n\n    for pos in positions:\n        item = items[int(pos)]\n        key = (str(item["tile_id"]), i(item["candidate_index"]))\n        nr = native_lookup.get(key)\n        if nr is None:\n            continue\n        gx, gy = f(nr.get("global_x")), f(nr.get("global_y"))\n        if gx is None or gy is None:\n            continue\n        if any(\n            sx is not None and sy is not None\n            and math.hypot(gx - sx, gy - sy) <= min_sep_px\n            for sx, sy in science_xy\n        ):\n            continue\n        selected.append((item, nr))\n        if len(selected) == SAMPLE_N:\n            break\n\n    if len(selected) != SAMPLE_N:\n        print(f"FAIL could only select {len(selected)} safe calibration controls")\n        return 3\n\n    print(f"Frozen extract_patch radius: {patch_r} px")\n    print(f"Science-patch exclusion distance: >{min_sep_px} px")\n    print(f"Calibration controls selected: {len(selected)}")\n\n    tiles = ar.discover_tiles()\n    transforms = ar.infer_tile_transforms(tiles, native_rows)\n    print(f"discover_tiles returned: {len(tiles)}")\n    print(f"infer_tile_transforms returned: {len(transforms)}")\n\n    results = []\n    metric_keys = None\n\n    for n, (item, nr) in enumerate(selected, 1):\n        gx, gy = f(nr.get("global_x")), f(nr.get("global_y"))\n        hit = ar.tile_for_global(tiles, transforms, gx, gy)\n        tile, transform = tile_and_transform(hit)\n\n        if tile is None:\n            print(f"FAIL q{item[\'queue_order\']:04d}: tile_for_global returned no tile")\n            return 4\n\n        if transform is None:\n            transform = transform_from_mapping(\n                transforms, tile, str(item["tile_id"])\n            )\n        if transform is None:\n            print(\n                f"FAIL q{item[\'queue_order\']:04d}: could not resolve transform; "\n                f"tile_for_global type={type(hit).__name__}"\n            )\n            return 4\n\n        local = ar.global_to_local(tile, transform, gx, gy)\n        if not isinstance(local, (tuple, list)) or len(local) < 2:\n            print(\n                f"FAIL q{item[\'queue_order\']:04d}: global_to_local returned "\n                f"{type(local).__name__}"\n            )\n            return 4\n        lx, ly = float(local[0]), float(local[1])\n\n        patch_obj = ar.extract_patch(tile, lx, ly)\n        patch = patch_from_result(patch_obj)\n        metrics = ar.raw_metrics(patch, 1)\n\n        if not isinstance(metrics, dict):\n            print(\n                f"FAIL q{item[\'queue_order\']:04d}: raw_metrics returned "\n                f"{type(metrics).__name__}"\n            )\n            return 4\n\n        keys = tuple(sorted(metrics.keys()))\n        if metric_keys is None:\n            metric_keys = keys\n        elif keys != metric_keys:\n            print(\n                f"FAIL q{item[\'queue_order\']:04d}: raw_metrics schema drift"\n            )\n            return 4\n\n        derived = ash.derived(metrics)\n\n        row = {\n            "sample_order": n,\n            "queue_order": int(item["queue_order"]),\n            "tile_id": str(item["tile_id"]),\n            "candidate_index": int(item["candidate_index"]),\n            "global_x": gx,\n            "global_y": gy,\n            "local_x": lx,\n            "local_y": ly,\n            "patch_shape": "x".join(str(x) for x in patch.shape),\n            "patch_min": float(np.nanmin(patch)),\n            "patch_max": float(np.nanmax(patch)),\n            "raw_metrics": jsonable(metrics),\n            "derived": jsonable(derived),\n        }\n        results.append(row)\n\n        print(\n            f"[{n:02d}/{SAMPLE_N}] q{int(item[\'queue_order\']):04d} "\n            f"tile={item[\'tile_id\']} patch={row[\'patch_shape\']} "\n            f"metrics={len(metric_keys)} derivedType={type(derived).__name__}"\n        )\n\n    payload = {\n        "stage": "ORDER01_DASCH_MORPHOLOGY_PIXEL_CALIBRATION_V028BI",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": True,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "source_hashes": {\n            "v028ar_r1": EXPECTED_AR_SHA,\n            "v028as": EXPECTED_AS_SHA,\n        },\n        "extract_patch_radius_px": patch_r,\n        "science_patch_exclusion_distance_px": min_sep_px,\n        "sample_count": len(results),\n        "metric_keys": list(metric_keys or []),\n        "samples": results,\n        "executor_gate": {\n            "full_2596_control_pixel_executor_may_be_built": True,\n        },\n        "interpretive_boundary": (\n            "This calibration validates exact helper reuse, transforms, patch "\n            "extraction, raw-metric schema, and v028as derived-vector execution "\n            "on a deterministic non-science sample. It does not estimate "\n            "plate-wide morphology prevalence."\n        ),\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True) + "\\n",\n        encoding="utf-8",\n    )\n\n    flat = []\n    for r in results:\n        flat.append({\n            "sample_order": r["sample_order"],\n            "queue_order": r["queue_order"],\n            "tile_id": r["tile_id"],\n            "candidate_index": r["candidate_index"],\n            "global_x": r["global_x"],\n            "global_y": r["global_y"],\n            "local_x": r["local_x"],\n            "local_y": r["local_y"],\n            "patch_shape": r["patch_shape"],\n            "patch_min": r["patch_min"],\n            "patch_max": r["patch_max"],\n            "raw_metrics_json": json.dumps(r["raw_metrics"], sort_keys=True),\n            "derived_json": json.dumps(r["derived"], sort_keys=True),\n        })\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(flat[0].keys())\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(flat)\n\n    OUT_MD.write_text(\n        "# ORDER 01 — Morphology Pixel Calibration v028bi\\n\\n"\n        f"- Controls processed: **{len(results)}**.\\n"\n        f"- Frozen patch radius: **{patch_r} px**.\\n"\n        f"- Raw metric fields: **{len(metric_keys or [])}**.\\n"\n        "- Non-science pixels read: **true**.\\n"\n        "- Science pixels read: **false**.\\n"\n        "- Detector rerun: **false**.\\n\\n"\n        "This calibration does not estimate prevalence.\\n",\n        encoding="utf-8",\n    )\n\n    print("\\nRaw metric keys:")\n    for k in metric_keys or []:\n        print(f"  {k}")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nPIXEL CALIBRATION COMPLETE: True")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_morphology_pixel_calibration_v028bi",
        title="Calibrate exact v028ar/v028as morphology helpers on non-science pixels",
        script="automation/stages/calibrate_morphology_pixels_v028bi.py",
        requires=(
            "automation/queues/ai43437_platewide_morphology_v028bg.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
            "results/order01_native_full_v028/order01_strict_match_triage_v028.csv",
            "results/order01_native_full_v028/order01_dasch_morphology_executor_contract_v028bh.json",
            "tools/audit_order01_dasch_physical_morphology_v028ar_r1.py",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_morphology_pixel_calibration_v028bi.json",
        ),
        dependencies=("dasch_morphology_executor_contract_v028bh",),
        non_science_pixels_read=True,
        notes="24-control deterministic pixel calibration using exact validated source hashes; no detector rerun or candidate mutation.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_morphology_pixel_calibration_v028bi"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.4 — MORPHOLOGY PIXEL CALIBRATION")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("THE UPGRADE ITSELF READS NO PIXELS.")
    print("The registered v028bi stage WILL read non-science pixels.")
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
        "Transient automation v0.1.4 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text(
        '__version__ = "0.1.4"\n',
        encoding="utf-8",
    )

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
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_morphology_pixel_calibration_v028bi'
    )
    print("\nv028bi reads 24 deterministic NON-SCIENCE control patches.")
    print("It does not rerun the transient detector or alter candidate state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
