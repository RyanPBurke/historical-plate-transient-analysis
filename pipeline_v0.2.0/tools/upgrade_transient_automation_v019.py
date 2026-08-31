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
STAGE = AUTO / "stages" / "audit_science25_targeted_analogues_v028bn.py"
BACKUP = AUTO / "backups" / "pre_v019"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport importlib.util\nimport json\nimport math\nimport re\nimport sys\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nBM = BASE / "order01_dasch_platewide_phenotype_synthesis_v028bm.json"\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nAR_JSON = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\nAR_SRC = ROOT / "tools" / "audit_order01_dasch_physical_morphology_v028ar_r1.py"\nAS_SRC = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\n\nOUT_JSON = BASE / "order01_dasch_science25_targeted_analogue_artifact_audit_v028bn.json"\nOUT_CSV = BASE / "order01_dasch_science25_targeted_analogue_artifact_audit_v028bn.csv"\nOUT_MD = BASE / "ORDER01_DASCH_SCIENCE25_TARGETED_ANALOGUE_ARTIFACT_AUDIT_V028BN.md"\nOUT_PNG = BASE / "order01_dasch_science25_shape_analogue_control_patches_v028bn.png"\n\nSCIENCE_RANK = 25\nEXPECTED_ANALOGUES = 4\nEXPECTED_ANALOGUE_ORDERS = {144, 186, 192, 1088}\nRADII_PX = [25.0, 50.0, 100.0, 250.0]\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef i(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef load_module(path, name):\n    spec = importlib.util.spec_from_file_location(name, path)\n    if spec is None or spec.loader is None:\n        raise RuntimeError(f"cannot import {path}")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef tile_and_transform(hit):\n    if hit is None:\n        return None, None\n    if isinstance(hit, dict):\n        if "tile" in hit:\n            return hit.get("tile"), hit.get("transform")\n        return hit, hit.get("transform")\n    if isinstance(hit, (tuple, list)):\n        if len(hit) >= 2:\n            return hit[0], hit[1]\n        if len(hit) == 1:\n            return hit[0], None\n    return hit, None\n\n\ndef transform_from_mapping(transforms, tile, tile_id):\n    if not isinstance(transforms, dict):\n        return None\n    candidates = [tile_id]\n    if isinstance(tile, dict):\n        for k in ("tile_id", "id", "path", "file", "name"):\n            if tile.get(k) is not None:\n                candidates.extend([tile.get(k), str(tile.get(k))])\n    for key in candidates:\n        if key in transforms:\n            return transforms[key]\n    for key, val in transforms.items():\n        if isinstance(val, dict):\n            strings = {str(x) for x in val.values() if isinstance(x, (str, Path))}\n            if tile_id in strings:\n                return val\n        if str(key) == tile_id:\n            return val\n    return None\n\n\ndef patch_from_result(obj):\n    if isinstance(obj, np.ndarray):\n        return obj\n    if isinstance(obj, (tuple, list)):\n        for v in obj:\n            if isinstance(v, np.ndarray):\n                return v\n    if isinstance(obj, dict):\n        for k in ("patch", "array", "data", "pixels"):\n            if isinstance(obj.get(k), np.ndarray):\n                return obj[k]\n    raise RuntimeError("extract_patch returned no ndarray")\n\n\ndef parse_tile_bounds(tile_id):\n    m = re.search(r"x(\\d+)-(\\d+)_y(\\d+)-(\\d+)", tile_id)\n    if not m:\n        return None\n    x0, x1, y0, y1 = map(float, m.groups())\n    return x0, x1, y0, y1\n\n\ndef edge_distance(tile_id, gx, gy):\n    b = parse_tile_bounds(tile_id)\n    if b is None:\n        return None\n    x0, x1, y0, y1 = b\n    return min(gx - x0, x1 - gx, gy - y0, y1 - gy)\n\n\ndef neighbour_stats(native, gx, gy, self_key):\n    rows = []\n    for r in native:\n        key = (r["tile_id"], r["candidate_index"])\n        if key == self_key:\n            continue\n        dx = r["global_x"] - gx\n        dy = r["global_y"] - gy\n        d = math.hypot(dx, dy)\n        rows.append((d, r))\n    rows.sort(key=lambda x: x[0])\n\n    out = {\n        "nearest_any_distance_px": rows[0][0] if rows else None,\n        "nearest_any_polarity": rows[0][1]["polarity"] if rows else None,\n        "nearest_any_snr": rows[0][1]["snr"] if rows else None,\n    }\n\n    for pol in (1, -1):\n        rr = [(d, r) for d, r in rows if r["polarity"] == pol]\n        out[f"nearest_polarity_{pol}_distance_px"] = rr[0][0] if rr else None\n        out[f"nearest_polarity_{pol}_snr"] = rr[0][1]["snr"] if rr else None\n\n    for radius in RADII_PX:\n        rr = [(d, r) for d, r in rows if d <= radius]\n        out[f"neighbors_le_{int(radius)}px"] = len(rr)\n        out[f"neighbors_plus1_le_{int(radius)}px"] = sum(r["polarity"] == 1 for _, r in rr)\n        out[f"neighbors_minus1_le_{int(radius)}px"] = sum(r["polarity"] == -1 for _, r in rr)\n        out[f"neighbor_max_snr_le_{int(radius)}px"] = max(\n            [r["snr"] for _, r in rr if r["snr"] is not None],\n            default=None,\n        )\n    return out\n\n\ndef feature_vector(asmod, metrics):\n    d = asmod.derived(metrics)\n    feats = list(asmod.FEATURES)\n    if not all(d.get(k) is not None and math.isfinite(float(d[k])) for k in feats):\n        raise RuntimeError("incomplete derived feature vector")\n    return d, np.array([float(d[k]) for k in feats], float)\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — SCIENCE #25 TARGETED ANALOGUE ARTIFACT AUDIT v028bn")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE READ: TRUE (4 TARGETED ANALOGUES ONLY).")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (BM, BJ, AR_JSON, NATIVE, AR_SRC, AS_SRC):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    bm = json.loads(BM.read_text(encoding="utf-8"))\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    ar_obj = json.loads(AR_JSON.read_text(encoding="utf-8"))\n\n    analogues = list(bm.get("top_controls_at_least_as_starlike_as_science_25", []))\n    orders = {int(r["queue_order"]) for r in analogues}\n    if len(analogues) != EXPECTED_ANALOGUES or orders != EXPECTED_ANALOGUE_ORDERS:\n        print(f"FAIL #25 analogue guard mismatch: count={len(analogues)} orders={sorted(orders)}")\n        return 3\n\n    science_rows = {\n        int(r["strict_rank"]): r\n        for r in ar_obj.get("science", [])\n    }\n    if SCIENCE_RANK not in science_rows:\n        print("FAIL frozen v028ar science #25 missing")\n        return 3\n\n    official_controls = list(ar_obj.get("official_controls", []))\n    if len(official_controls) < 8:\n        print("FAIL too few frozen official controls")\n        return 3\n\n    ar = load_module(AR_SRC, "validated_v028ar_r1_targeted_analogue")\n    ash = load_module(AS_SRC, "validated_v028as_targeted_analogue")\n\n    native_raw = read_csv(NATIVE)\n    native = []\n    native_lookup = {}\n    for r in native_raw:\n        row = {\n            "tile_id": str(r.get("tile_id", "")),\n            "candidate_index": i(r.get("candidate_index")),\n            "global_x": f(r.get("global_x")),\n            "global_y": f(r.get("global_y")),\n            "ra_deg": f(r.get("ra_deg")),\n            "dec_deg": f(r.get("dec_deg")),\n            "snr": f(r.get("snr")),\n            "polarity": i(r.get("polarity")),\n        }\n        if row["global_x"] is None or row["global_y"] is None:\n            continue\n        native.append(row)\n        native_lookup[(row["tile_id"], row["candidate_index"])] = row\n\n    bj_by_order = {\n        int(r["queue_order"]): r\n        for r in bj.get("results", [])\n        if r.get("status") == "SUCCESS"\n    }\n\n    tiles = ar.discover_tiles()\n    transforms = ar.infer_tile_transforms(tiles, native_raw)\n\n    # Reconstruct official control scaling exactly as v028as.\n    cder = [ash.derived(r) for r in official_controls]\n    good_cder = [\n        d for d in cder\n        if all(d.get(k) is not None and math.isfinite(float(d[k])) for k in ash.FEATURES)\n    ]\n    X = np.array([[d[k] for k in ash.FEATURES] for d in good_cder], float)\n    med, scale = ash.robust_center_scale(X)\n\n    science25 = science_rows[SCIENCE_RANK]\n    s25_derived, s25_x = feature_vector(ash, science25)\n    s25_z = (s25_x - med) / scale\n    s25_amp = f(s25_derived.get("amplitude_ap5"))\n    s25_tile = str(science25.get("tile_id", ""))\n    s25_key = (s25_tile, i(science25.get("candidate_index")))\n    s25_native = native_lookup.get(s25_key)\n    if s25_native is None:\n        # Fallback by nearest RA/Dec, without science pixel access.\n        sra, sdec = f(science25.get("ra_deg")), f(science25.get("dec_deg"))\n        candidates = []\n        if sra is not None and sdec is not None:\n            for r in native:\n                if r["ra_deg"] is not None and r["dec_deg"] is not None:\n                    d2 = (r["ra_deg"]-sra)**2 + (r["dec_deg"]-sdec)**2\n                    candidates.append((d2, r))\n        if candidates:\n            candidates.sort(key=lambda x: x[0])\n            s25_native = candidates[0][1]\n            s25_key = (s25_native["tile_id"], s25_native["candidate_index"])\n    if s25_native is None:\n        print("FAIL could not recover #25 native position")\n        return 4\n\n    science_context = {\n        "rank": 25,\n        "tile_id": s25_native["tile_id"],\n        "candidate_index": s25_native["candidate_index"],\n        "global_x": s25_native["global_x"],\n        "global_y": s25_native["global_y"],\n        "snr": s25_native["snr"],\n        "polarity": s25_native["polarity"],\n        "tile_edge_distance_px": edge_distance(\n            s25_native["tile_id"], s25_native["global_x"], s25_native["global_y"]\n        ),\n        "neighbor_context": neighbour_stats(\n            native, s25_native["global_x"], s25_native["global_y"], s25_key\n        ),\n        "raw_metrics_reused_from_v028ar_r1": science25,\n        "derived_features_reused": s25_derived,\n        "ap5_amplitude": s25_amp,\n        "science_pixels_read_this_stage": False,\n    }\n\n    results = []\n    patches = []\n\n    for r in sorted(analogues, key=lambda x: int(x["queue_order"])):\n        order = int(r["queue_order"])\n        bjr = bj_by_order.get(order)\n        if bjr is None:\n            print(f"FAIL q{order:04d}: missing v028bj success row")\n            return 4\n\n        key = (str(r["tile_id"]), int(r["candidate_index"]))\n        nr = native_lookup.get(key)\n        if nr is None:\n            print(f"FAIL q{order:04d}: native row missing")\n            return 4\n\n        gx, gy = nr["global_x"], nr["global_y"]\n        hit = ar.tile_for_global(tiles, transforms, gx, gy)\n        tile, transform = tile_and_transform(hit)\n        if tile is None:\n            print(f"FAIL q{order:04d}: no tile")\n            return 4\n        if transform is None:\n            transform = transform_from_mapping(transforms, tile, nr["tile_id"])\n        if transform is None:\n            print(f"FAIL q{order:04d}: no transform")\n            return 4\n\n        local = ar.global_to_local(tile, transform, gx, gy)\n        lx, ly = float(local[0]), float(local[1])\n        patch = patch_from_result(ar.extract_patch(tile, lx, ly))\n        if tuple(patch.shape) != (49, 49):\n            print(f"FAIL q{order:04d}: patch shape {patch.shape}")\n            return 4\n\n        metrics = ar.raw_metrics(patch, 1)\n        derived, x = feature_vector(ash, metrics)\n        z = (x - med) / scale\n        direct_shape_distance_to_science25 = float(ash.distance(z, s25_z))\n\n        # Regression against frozen v028bj metrics.\n        frozen = bjr.get("raw_metrics", {})\n        keys = sorted(metrics)\n        if sorted(frozen) != keys:\n            print(f"FAIL q{order:04d}: metric schema mismatch vs v028bj")\n            return 4\n        max_abs_delta = 0.0\n        for k in keys:\n            a, b = f(metrics.get(k)), f(frozen.get(k))\n            if a is None and b is None:\n                continue\n            if a is None or b is None:\n                print(f"FAIL q{order:04d}: metric null mismatch {k}")\n                return 4\n            max_abs_delta = max(max_abs_delta, abs(a-b))\n        if max_abs_delta > 1e-9:\n            print(f"FAIL q{order:04d}: metric regression delta {max_abs_delta}")\n            return 4\n\n        rec = {\n            "queue_order": order,\n            "tile_id": nr["tile_id"],\n            "candidate_index": nr["candidate_index"],\n            "global_x": gx,\n            "global_y": gy,\n            "ra_deg": nr["ra_deg"],\n            "dec_deg": nr["dec_deg"],\n            "snr": nr["snr"],\n            "polarity": nr["polarity"],\n            "tile_edge_distance_px": edge_distance(nr["tile_id"], gx, gy),\n            "nearest_official_sep_arcsec": f(r.get("nearest_official_sep_arcsec")),\n            "shape_nn_to_official_cloud": f(r.get("nearest_shape_distance")),\n            "direct_shape_distance_to_science25": direct_shape_distance_to_science25,\n            "amplitude_support_status": r.get("amplitude_support_status"),\n            "ap5_amplitude": f(r.get("ap5_amplitude")),\n            "ap5_amplitude_ratio_to_science25":\n                (f(r.get("ap5_amplitude")) / s25_amp) if s25_amp not in (None, 0) else None,\n            "neighbor_context": neighbour_stats(native, gx, gy, key),\n            "raw_metrics": metrics,\n            "derived_features": derived,\n            "metric_regression_max_abs_delta_vs_v028bj": max_abs_delta,\n        }\n        results.append(rec)\n        patches.append((order, patch.copy()))\n\n        print(\n            f"q{order:04d}: NNofficial={rec[\'shape_nn_to_official_cloud\']:.6f} "\n            f"directTo#25={direct_shape_distance_to_science25:.6f} "\n            f"amp={rec[\'amplitude_support_status\']} "\n            f"edge={rec[\'tile_edge_distance_px\']:.2f}px "\n            f"near50={rec[\'neighbor_context\'][\'neighbors_le_50px\']}"\n        )\n\n    # Optional review image: controls only, never science #25.\n    png_written = False\n    try:\n        import matplotlib.pyplot as plt\n        fig, axes = plt.subplots(1, 4, figsize=(12, 3.2))\n        for ax, (order, patch) in zip(axes, patches):\n            lo, hi = np.percentile(patch[np.isfinite(patch)], [5, 99])\n            ax.imshow(patch, origin="lower", cmap="gray", vmin=lo, vmax=hi)\n            ax.axhline(24, linewidth=0.5)\n            ax.axvline(24, linewidth=0.5)\n            ax.set_title(f"q{order:04d}")\n            ax.set_xticks([])\n            ax.set_yticks([])\n        fig.suptitle("Science #25 plate-wide shape analogues — control patches only")\n        fig.tight_layout()\n        fig.savefig(OUT_PNG, dpi=180, bbox_inches="tight")\n        plt.close(fig)\n        png_written = True\n    except Exception as exc:\n        print(f"WARN review PNG not written: {type(exc).__name__}: {exc}")\n\n    # Identify the same-amplitude-status analogue and closest direct morphology analogue.\n    same_amp = [r for r in results if r["amplitude_support_status"] == "ABOVE_CONTROL_RANGE"]\n    closest_direct = min(results, key=lambda r: r["direct_shape_distance_to_science25"])\n\n    payload = {\n        "stage": "ORDER01_DASCH_SCIENCE25_TARGETED_ANALOGUE_ARTIFACT_AUDIT_V028BN",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": True,\n            "non_science_pixel_targets": sorted(EXPECTED_ANALOGUE_ORDERS),\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "science25_context": science_context,\n        "analogue_controls": results,\n        "summary": {\n            "analogue_count": len(results),\n            "same_above_control_amplitude_status_count": len(same_amp),\n            "same_above_control_amplitude_status_orders":\n                [r["queue_order"] for r in same_amp],\n            "closest_direct_shape_analogue_order": closest_direct["queue_order"],\n            "closest_direct_shape_distance": closest_direct["direct_shape_distance_to_science25"],\n            "control_review_png_written": png_written,\n            "control_review_png": str(OUT_PNG.relative_to(ROOT)) if png_written else None,\n        },\n        "interpretive_boundary": (\n            "This targeted audit compares #25 with the four plate-wide controls "\n            "that are at least as close to the official stellar-shape cloud. "\n            "Only control pixels are read; #25 science pixels and metrics are reused "\n            "from frozen v028ar/v028as outputs. Similarity or rarity on these axes "\n            "does not establish astrophysical transience."\n        ),\n        "next_gate": {\n            "science25_targeted_interpretation_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    flat = []\n    for r in results:\n        x = {k: v for k, v in r.items() if k not in ("neighbor_context", "raw_metrics", "derived_features")}\n        for k, v in r["neighbor_context"].items():\n            x[f"neighbor_{k}"] = v\n        for k, v in r["raw_metrics"].items():\n            x[f"metric_{k}"] = v\n        for k, v in r["derived_features"].items():\n            if isinstance(v, (str, int, float, bool)) or v is None:\n                x[f"derived_{k}"] = v\n        flat.append(x)\n\n    fields = sorted({k for r in flat for k in r})\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(flat)\n\n    md = [\n        "# ORDER 01 — Science #25 Targeted Analogue Artifact Audit v028bn",\n        "",\n        "- Science #25 pixels were **not reread**.",\n        "- Four non-science analogue patches were read and regression-checked against v028bj.",\n        f"- Same above-control amplitude-status analogues: **{[r[\'queue_order\'] for r in same_amp]}**.",\n        f"- Closest direct morphology analogue to #25: **q{closest_direct[\'queue_order\']:04d}** "\n        f"(distance {closest_direct[\'direct_shape_distance_to_science25\']:.4f}).",\n        "",\n        "| q | tile | shape NN to official | direct distance to #25 | amplitude status | edge px | neighbours <=50 px | nearest official arcsec |",\n        "|---:|---|---:|---:|---|---:|---:|---:|",\n    ]\n    for r in results:\n        md.append(\n            f"| {r[\'queue_order\']} | {r[\'tile_id\']} | {r[\'shape_nn_to_official_cloud\']:.4f} | "\n            f"{r[\'direct_shape_distance_to_science25\']:.4f} | {r[\'amplitude_support_status\']} | "\n            f"{r[\'tile_edge_distance_px\']:.1f} | {r[\'neighbor_context\'][\'neighbors_le_50px\']} | "\n            f"{r[\'nearest_official_sep_arcsec\']:.1f} |"\n        )\n    md += [\n        "",\n        "This is a targeted artifact/analogue context audit, not a promotion test.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nSummary:")\n    print(f"  same above-control amplitude status: {[r[\'queue_order\'] for r in same_amp]}")\n    print(\n        f"  closest direct shape analogue to #25: q{closest_direct[\'queue_order\']:04d} "\n        f"distance={closest_direct[\'direct_shape_distance_to_science25\']:.6f}"\n    )\n    print(f"  review PNG written: {png_written}")\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    if png_written:\n        print(f"  {OUT_PNG}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_science25_targeted_analogue_audit_v028bn",
        title="Targeted artifact/context audit of the four plate-wide #25 shape analogues",
        script="automation/stages/audit_science25_targeted_analogues_v028bn.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_platewide_phenotype_synthesis_v028bm.json",
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
            "results/order01_native_full_v028/order01_dasch_physical_morphology_v028ar_r1.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
            "tools/audit_order01_dasch_physical_morphology_v028ar_r1.py",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_science25_targeted_analogue_artifact_audit_v028bn.json",
        ),
        dependencies=("dasch_platewide_phenotype_synthesis_v028bm",),
        non_science_pixels_read=True,
        notes="Reads only four non-science analogue patches (q0144,q0186,q0192,q1088); #25 science pixels are not reread.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_science25_targeted_analogue_audit_v028bn"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.9 — SCIENCE #25 TARGETED ANALOGUE AUDIT")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("THE UPGRADE ITSELF READS NO PIXELS.")
    print("Registered v028bn reads only four non-science control patches.")
    print("Science #25 pixels are not reread.\n")

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
        "Transient automation v0.1.9 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.1.9"\n', encoding="utf-8")

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
        r'verify-stage --stage dasch_science25_targeted_analogue_audit_v028bn'
    )
    print("\nNo network access is required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
