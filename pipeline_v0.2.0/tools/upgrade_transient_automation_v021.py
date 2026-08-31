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
STAGE = AUTO / "stages" / "audit_science25_direct_visual_analogues_v028bp.py"
BACKUP = AUTO / "backups" / "pre_v021"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport importlib.util\nimport json\nimport math\nimport struct\nimport sys\nimport zlib\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nBO = BASE / "order01_dasch_science25_direct_shape_neighbourhood_v028bo.json"\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nAR_JSON = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\nAR_SRC = ROOT / "tools" / "audit_order01_dasch_physical_morphology_v028ar_r1.py"\nAS_SRC = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\n\nOUT_JSON = BASE / "order01_dasch_science25_direct_visual_analogue_audit_v028bp.json"\nOUT_CSV = BASE / "order01_dasch_science25_direct_visual_analogue_features_v028bp.csv"\nOUT_MD = BASE / "ORDER01_DASCH_SCIENCE25_DIRECT_VISUAL_ANALOGUE_AUDIT_V028BP.md"\nOUT_PNG = BASE / "order01_dasch_science25_q0030_q0344_normalized_patches_v028bp.png"\n\nSCIENCE_RANK = 25\nCONTROL_ORDERS = [30, 344]\nEXPECTED_PATCH = (49, 49)\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef i(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef load_module(path, name):\n    spec = importlib.util.spec_from_file_location(name, path)\n    if spec is None or spec.loader is None:\n        raise RuntimeError(f"cannot import {path}")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef tile_and_transform(hit):\n    if hit is None:\n        return None, None\n    if isinstance(hit, dict):\n        if "tile" in hit:\n            return hit.get("tile"), hit.get("transform")\n        return hit, hit.get("transform")\n    if isinstance(hit, (tuple, list)):\n        if len(hit) >= 2:\n            return hit[0], hit[1]\n        if len(hit) == 1:\n            return hit[0], None\n    return hit, None\n\n\ndef transform_from_mapping(transforms, tile, tile_id):\n    if not isinstance(transforms, dict):\n        return None\n    candidates = [tile_id]\n    if isinstance(tile, dict):\n        for k in ("tile_id", "id", "path", "file", "name"):\n            if tile.get(k) is not None:\n                candidates.extend([tile.get(k), str(tile.get(k))])\n    for key in candidates:\n        if key in transforms:\n            return transforms[key]\n    for key, val in transforms.items():\n        if isinstance(val, dict):\n            strings = {str(x) for x in val.values() if isinstance(x, (str, Path))}\n            if tile_id in strings:\n                return val\n        if str(key) == tile_id:\n            return val\n    return None\n\n\ndef patch_from_result(obj):\n    if isinstance(obj, np.ndarray):\n        return obj\n    if isinstance(obj, (tuple, list)):\n        for v in obj:\n            if isinstance(v, np.ndarray):\n                return v\n    if isinstance(obj, dict):\n        for k in ("patch", "array", "data", "pixels"):\n            if isinstance(obj.get(k), np.ndarray):\n                return obj[k]\n    raise RuntimeError("extract_patch returned no ndarray")\n\n\ndef raw_metric_regression(observed, frozen, label):\n    deltas = {}\n    missing = []\n    for k, ov in observed.items():\n        if k not in frozen:\n            missing.append(k)\n            continue\n        a, b = f(ov), f(frozen.get(k))\n        if a is None and b is None:\n            deltas[k] = 0.0\n        elif a is None or b is None:\n            raise RuntimeError(f"{label}: null mismatch for {k}")\n        else:\n            deltas[k] = abs(a - b)\n    if missing:\n        raise RuntimeError(f"{label}: frozen row lacks metric keys {missing}")\n    max_delta = max(deltas.values(), default=0.0)\n    if max_delta > 1e-9:\n        raise RuntimeError(f"{label}: metric regression max delta {max_delta}")\n    return max_delta\n\n\ndef standardize_patch(patch, metrics):\n    med = float(metrics["background_median"])\n    sig = float(metrics["background_sigma"])\n    if not math.isfinite(sig) or sig <= 0:\n        raise RuntimeError("invalid background_sigma")\n    return (np.asarray(patch, float) - med) / sig\n\n\ndef corr(a, b):\n    aa = np.asarray(a, float).ravel()\n    bb = np.asarray(b, float).ravel()\n    good = np.isfinite(aa) & np.isfinite(bb)\n    aa, bb = aa[good], bb[good]\n    if len(aa) < 3 or np.std(aa) == 0 or np.std(bb) == 0:\n        return None\n    return float(np.corrcoef(aa, bb)[0, 1])\n\n\ndef png_chunk(tag, data):\n    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)\n\n\ndef write_gray_png(path, arr):\n    img = np.asarray(arr, dtype=np.uint8)\n    if img.ndim != 2:\n        raise ValueError("grayscale PNG requires 2-D array")\n    h, w = img.shape\n    raw = b"".join(b"\\x00" + img[y].tobytes() for y in range(h))\n    data = (\n        b"\\x89PNG\\r\\n\\x1a\\n"\n        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))\n        + png_chunk(b"IDAT", zlib.compress(raw, 9))\n        + png_chunk(b"IEND", b"")\n    )\n    path.write_bytes(data)\n\n\ndef visual_strip(named_zpatches):\n    # Same fixed z-scale for every panel: -3 sigma -> black, +12 sigma -> white.\n    panels = []\n    sep = np.full((49, 4), 128, dtype=np.uint8)\n    for _, z in named_zpatches:\n        scaled = np.clip((z + 3.0) / 15.0, 0.0, 1.0)\n        panel = np.round(255.0 * scaled).astype(np.uint8)\n        panels.append(panel)\n    out = panels[0]\n    for panel in panels[1:]:\n        out = np.concatenate([out, sep, panel], axis=1)\n    # Upscale 5x nearest-neighbour for convenient inspection.\n    return np.repeat(np.repeat(out, 5, axis=0), 5, axis=1)\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — SCIENCE #25 DIRECT VISUAL ANALOGUE AUDIT v028bp")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE READ: TRUE (#25 ONLY).")\n    print("NON-SCIENCE PIXELS ARE READ: TRUE (q0030 AND q0344 ONLY).")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (BO, BJ, AR_JSON, NATIVE, AR_SRC, AS_SRC):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    bo = json.loads(BO.read_text(encoding="utf-8"))\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    ar_obj = json.loads(AR_JSON.read_text(encoding="utf-8"))\n\n    nearest = bo.get("nearest_direct_control", {})\n    nearest_above = bo.get("nearest_direct_above_control_amplitude_control", {})\n    if int(nearest.get("queue_order", -1)) != 344:\n        print(f"FAIL expected nearest direct control q0344, got {nearest.get(\'queue_order\')}")\n        return 3\n    if int(nearest_above.get("queue_order", -1)) != 30:\n        print(f"FAIL expected nearest above-control amplitude direct control q0030, got {nearest_above.get(\'queue_order\')}")\n        return 3\n\n    ar = load_module(AR_SRC, "validated_v028ar_r1_direct_visual")\n    ash = load_module(AS_SRC, "validated_v028as_direct_visual")\n\n    native_raw = read_csv(NATIVE)\n    native_lookup = {}\n    for r in native_raw:\n        key = (str(r.get("tile_id", "")), i(r.get("candidate_index")))\n        native_lookup[key] = r\n\n    science_rows = {int(r["strict_rank"]): r for r in ar_obj.get("science", [])}\n    official_controls = list(ar_obj.get("official_controls", []))\n    if SCIENCE_RANK not in science_rows:\n        print("FAIL frozen science #25 row missing")\n        return 3\n    srow = science_rows[SCIENCE_RANK]\n\n    # Recover exact science native identity from frozen v028ar row.\n    skey = (str(srow.get("tile_id", "")), i(srow.get("candidate_index")))\n    snative = native_lookup.get(skey)\n    if snative is None:\n        print(f"FAIL science #25 native identity not found: {skey}")\n        return 3\n\n    bj_success = {\n        int(r["queue_order"]): r\n        for r in bj.get("results", [])\n        if r.get("status") == "SUCCESS"\n    }\n    for order in CONTROL_ORDERS:\n        if order not in bj_success:\n            print(f"FAIL q{order:04d}: missing v028bj success row")\n            return 3\n\n    tiles = ar.discover_tiles()\n    transforms = ar.infer_tile_transforms(tiles, native_raw)\n\n    def read_one(tile_id, candidate_index, frozen_metrics, label):\n        nr = native_lookup.get((tile_id, candidate_index))\n        if nr is None:\n            raise RuntimeError(f"{label}: native row missing")\n        gx, gy = f(nr.get("global_x")), f(nr.get("global_y"))\n        hit = ar.tile_for_global(tiles, transforms, gx, gy)\n        tile, transform = tile_and_transform(hit)\n        if tile is None:\n            raise RuntimeError(f"{label}: no tile")\n        if transform is None:\n            transform = transform_from_mapping(transforms, tile, tile_id)\n        if transform is None:\n            raise RuntimeError(f"{label}: no transform")\n        local = ar.global_to_local(tile, transform, gx, gy)\n        patch = patch_from_result(ar.extract_patch(tile, float(local[0]), float(local[1])))\n        if tuple(patch.shape) != EXPECTED_PATCH:\n            raise RuntimeError(f"{label}: patch shape {patch.shape}")\n        metrics = ar.raw_metrics(patch, 1)\n        delta = raw_metric_regression(metrics, frozen_metrics, label)\n        derived = ash.derived(metrics)\n        zpatch = standardize_patch(patch, metrics)\n        return {\n            "label": label,\n            "tile_id": tile_id,\n            "candidate_index": candidate_index,\n            "global_x": gx,\n            "global_y": gy,\n            "local_x": float(local[0]),\n            "local_y": float(local[1]),\n            "patch": patch,\n            "zpatch": zpatch,\n            "metrics": metrics,\n            "derived": derived,\n            "regression_max_abs_delta": delta,\n        }\n\n    science = read_one(\n        skey[0], skey[1],\n        {k: srow[k] for k in srow if k in {\n            "ap2_signed_zmean","ap2_signed_zsum","ap3_signed_zmean","ap3_signed_zsum",\n            "ap5_signed_zmean","ap5_signed_zsum","ap7_signed_zmean","ap7_signed_zsum",\n            "background_median","background_sigma","center3_signed_zmean",\n            "centroid_dx_pix","centroid_dy_pix","centroid_offset_pix",\n            "core_signed_min_z","core_signed_peak_z","moment_radius_pix",\n            "quadrant_imbalance","radial_0_1.5_signed_zmean","radial_1.5_3_signed_zmean",\n            "radial_10_12_signed_zmean","radial_3_5_signed_zmean",\n            "radial_5_7_signed_zmean","radial_7_10_signed_zmean"\n        }},\n        "science#25",\n    )\n\n    controls = []\n    for order in CONTROL_ORDERS:\n        fr = bj_success[order]\n        controls.append(\n            read_one(\n                str(fr["tile_id"]),\n                int(fr["candidate_index"]),\n                fr["raw_metrics"],\n                f"q{order:04d}",\n            )\n        )\n\n    # Exact frozen official-control scaling.\n    cder = [ash.derived(r) for r in official_controls]\n    good = [\n        d for d in cder\n        if all(d.get(k) is not None and math.isfinite(float(d[k])) for k in ash.FEATURES)\n    ]\n    X = np.array([[d[k] for k in ash.FEATURES] for d in good], float)\n    med, scale = ash.robust_center_scale(X)\n\n    def zvec(rec):\n        d = rec["derived"]\n        return (np.array([float(d[k]) for k in ash.FEATURES]) - med) / scale\n\n    sz = zvec(science)\n\n    results = []\n    for c in controls:\n        cz = zvec(c)\n        feature_delta = {}\n        for idx, name in enumerate(ash.FEATURES):\n            feature_delta[name] = {\n                "science25_value": float(science["derived"][name]),\n                "control_value": float(c["derived"][name]),\n                "standardized_delta_control_minus_science25": float(cz[idx] - sz[idx]),\n                "abs_standardized_delta": float(abs(cz[idx] - sz[idx])),\n            }\n\n        center = slice(17, 32)  # 15x15 central region\n        direct = float(ash.distance(cz, sz))\n        full_corr = corr(science["zpatch"], c["zpatch"])\n        central_corr = corr(science["zpatch"][center, center], c["zpatch"][center, center])\n\n        results.append({\n            "label": c["label"],\n            "queue_order": int(c["label"][1:]),\n            "tile_id": c["tile_id"],\n            "candidate_index": c["candidate_index"],\n            "direct_shape_distance_to_science25": direct,\n            "ap5_science25": f(science["derived"].get("amplitude_ap5")),\n            "ap5_control": f(c["derived"].get("amplitude_ap5")),\n            "ap5_ratio_control_to_science25":\n                f(c["derived"].get("amplitude_ap5")) / f(science["derived"].get("amplitude_ap5")),\n            "normalized_patch_full_pearson_r": full_corr,\n            "normalized_patch_central15_pearson_r": central_corr,\n            "feature_deltas": feature_delta,\n            "metric_regression_max_abs_delta": c["regression_max_abs_delta"],\n        })\n\n    strip = visual_strip([\n        ("science#25", science["zpatch"]),\n        ("q0030", controls[0]["zpatch"]),\n        ("q0344", controls[1]["zpatch"]),\n    ])\n    write_gray_png(OUT_PNG, strip)\n\n    print("Regression:")\n    print(f"  science #25 max metric delta vs frozen v028ar-r1: {science[\'regression_max_abs_delta\']:.3e}")\n    for c in controls:\n        print(f"  {c[\'label\']} max metric delta vs v028bj: {c[\'regression_max_abs_delta\']:.3e}")\n\n    print("\\nDIRECT COMPARISON TO #25")\n    for r in results:\n        print(\n            f"  {r[\'label\']}: d25={r[\'direct_shape_distance_to_science25\']:.6f} "\n            f"ampRatio={r[\'ap5_ratio_control_to_science25\']:.6f} "\n            f"patchCorrFull={r[\'normalized_patch_full_pearson_r\']:.4f} "\n            f"patchCorrCentral15={r[\'normalized_patch_central15_pearson_r\']:.4f}"\n        )\n        topdiff = sorted(\n            r["feature_deltas"].items(),\n            key=lambda kv: kv[1]["abs_standardized_delta"],\n            reverse=True,\n        )[:3]\n        print("    largest standardized feature differences:")\n        for name, d in topdiff:\n            print(\n                f"      {name}: delta={d[\'standardized_delta_control_minus_science25\']:+.4f}"\n            )\n\n    payload = {\n        "stage": "ORDER01_DASCH_SCIENCE25_DIRECT_VISUAL_ANALOGUE_AUDIT_V028BP",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": True,\n            "science_pixel_targets": ["strict_rank_25"],\n            "non_science_pixels_read": True,\n            "non_science_pixel_targets": ["q0030", "q0344"],\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "science25": {\n            "tile_id": science["tile_id"],\n            "candidate_index": science["candidate_index"],\n            "raw_metrics": science["metrics"],\n            "derived": science["derived"],\n            "metric_regression_max_abs_delta_vs_v028ar_r1":\n                science["regression_max_abs_delta"],\n        },\n        "comparisons": results,\n        "review_image": {\n            "path": str(OUT_PNG.relative_to(ROOT)),\n            "panel_order": ["science#25", "q0030", "q0344"],\n            "normalization": "(raw-background_median)/background_sigma; fixed display clip -3..+12 sigma",\n            "upsampling": "5x nearest-neighbour",\n            "interpretation": "visual aid only; no classification threshold derives from image correlation",\n        },\n        "interpretive_boundary": (\n            "This stage directly compares #25 with q0030 and q0344 using the exact "\n            "frozen 9-feature morphology space and normalized native pixel patches. "\n            "Pixel correlations are exploratory descriptive aids and are not part of "\n            "the frozen v028as classifier. Similarity does not identify physical cause "\n            "and does not establish or refute astrophysical transience."\n        ),\n        "next_gate": {\n            "science25_analogue_evidence_synthesis_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    flat = []\n    for r in results:\n        for name, d in r["feature_deltas"].items():\n            flat.append({\n                "control": r["label"],\n                "queue_order": r["queue_order"],\n                "direct_shape_distance_to_science25": r["direct_shape_distance_to_science25"],\n                "ap5_ratio_control_to_science25": r["ap5_ratio_control_to_science25"],\n                "normalized_patch_full_pearson_r": r["normalized_patch_full_pearson_r"],\n                "normalized_patch_central15_pearson_r": r["normalized_patch_central15_pearson_r"],\n                "feature": name,\n                "science25_value": d["science25_value"],\n                "control_value": d["control_value"],\n                "standardized_delta_control_minus_science25":\n                    d["standardized_delta_control_minus_science25"],\n                "abs_standardized_delta": d["abs_standardized_delta"],\n            })\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(flat[0].keys())\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(flat)\n\n    md = [\n        "# ORDER 01 — Science #25 Direct Visual Analogue Audit v028bp",\n        "",\n        "- Science pixels read: **true (#25 only)**.",\n        "- Non-science pixels read: **true (q0030 and q0344 only)**.",\n        "- Frozen detector rerun: **false**.",\n        "- Candidate state mutation: **false**.",\n        "",\n        "| control | direct 9-D distance | AP5 ratio vs #25 | full patch r | central 15x15 r |",\n        "|---|---:|---:|---:|---:|",\n    ]\n    for r in results:\n        md.append(\n            f"| {r[\'label\']} | {r[\'direct_shape_distance_to_science25\']:.4f} | "\n            f"{r[\'ap5_ratio_control_to_science25\']:.4f} | "\n            f"{r[\'normalized_patch_full_pearson_r\']:.4f} | "\n            f"{r[\'normalized_patch_central15_pearson_r\']:.4f} |"\n        )\n    md += [\n        "",\n        f"Review image: `{OUT_PNG.name}` (panel order #25, q0030, q0344).",\n        "",\n        "Pixel correlation is exploratory and not part of the frozen classifier.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print(f"  {OUT_PNG}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_science25_direct_visual_analogue_audit_v028bp",
        title="Direct native-pixel and frozen 9-D comparison of #25 with q0030/q0344",
        script="automation/stages/audit_science25_direct_visual_analogues_v028bp.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_science25_direct_shape_neighbourhood_v028bo.json",
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
            "results/order01_native_full_v028/order01_dasch_physical_morphology_v028ar_r1.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
            "tools/audit_order01_dasch_physical_morphology_v028ar_r1.py",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_science25_direct_visual_analogue_audit_v028bp.json",
        ),
        dependencies=("dasch_science25_direct_shape_neighbourhood_v028bo",),
        science_pixels_read=True,
        non_science_pixels_read=True,
        notes="Explicitly rereads #25 plus q0030/q0344 only; regression-checks frozen metrics and writes dependency-free grayscale PNG.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_science25_direct_visual_analogue_audit_v028bp"' in text:
        return text, "already registered"
    tree = ast.parse(text)
    container = None
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
    print("TRANSIENT AUTOMATION UPGRADE v0.2.1 — SCIENCE #25 DIRECT VISUAL ANALOGUE AUDIT")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("THE UPGRADE ITSELF READS NO PIXELS.")
    print("Registered v028bp explicitly reads #25, q0030 and q0344 pixels.")
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
        "Transient automation v0.2.1 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.2.1"\n', encoding="utf-8")

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
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_direct_visual_analogue_audit_v028bp'
    )
    print("\nNo network access is required.")
    print("v028bp will truthfully record science_pixels_read=True.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
