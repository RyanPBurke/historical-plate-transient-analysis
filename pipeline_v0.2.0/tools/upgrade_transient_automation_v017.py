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
STAGE = AUTO / "stages" / "classify_platewide_stellar_shape_prevalence_v028bl.py"
BACKUP = AUTO / "backups" / "pre_v017"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport importlib.util\nimport json\nimport math\nimport sys\nfrom collections import Counter\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nBK = BASE / "order01_dasch_stellar_shape_classifier_contract_v028bk.json"\nAS_RESULT = BASE / "order01_dasch_stellar_shape_v028as.json"\nAS_SOURCE = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\n\nOUT_JSON = BASE / "order01_dasch_platewide_stellar_shape_prevalence_v028bl.json"\nOUT_CSV = BASE / "order01_dasch_platewide_stellar_shape_prevalence_v028bl.csv"\nOUT_MD = BASE / "ORDER01_DASCH_PLATEWIDE_STELLAR_SHAPE_PREVALENCE_V028BL.md"\n\nEXPECTED_AS_SHA = "95084cb6e64934ec18686b30021c69b07605a938c5ec9169aadf26629877188f"\nEXPECTED_USABLE = 2587\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\nTOL = 1e-9\n\n\ndef sha256(path):\n    import hashlib\n    h = hashlib.sha256()\n    with path.open("rb") as fh:\n        for chunk in iter(lambda: fh.read(1024 * 1024), b""):\n            h.update(chunk)\n    return h.hexdigest()\n\n\ndef load_module(path, name):\n    spec = importlib.util.spec_from_file_location(name, path)\n    if spec is None or spec.loader is None:\n        raise RuntimeError(f"cannot import {path}")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef finite(v):\n    try:\n        x = float(v)\n        return x if math.isfinite(x) else None\n    except Exception:\n        return None\n\n\ndef empirical_percentile(vals, x):\n    vals = [float(v) for v in vals if finite(v) is not None]\n    if not vals or finite(x) is None:\n        return None\n    return sum(v <= float(x) for v in vals) / len(vals)\n\n\ndef locate_v028ar_source_object(asmod):\n    candidates = []\n\n    # Prefer exact Path globals already defined by the frozen v028as script.\n    for name, val in vars(asmod).items():\n        if not isinstance(val, Path):\n            continue\n        p = val if val.is_absolute() else ROOT / val\n        if not p.is_file() or p.suffix.lower() != ".json":\n            continue\n        try:\n            obj = json.loads(p.read_text(encoding="utf-8"))\n        except Exception:\n            continue\n        if isinstance(obj, dict) and "official_controls" in obj and "science" in obj:\n            candidates.append((name, p, obj))\n\n    # Conservative fallback: only v028ar-r1-named JSON artifacts.\n    if not candidates:\n        for p in sorted(BASE.glob("*v028ar*r1*.json")):\n            try:\n                obj = json.loads(p.read_text(encoding="utf-8"))\n            except Exception:\n                continue\n            if isinstance(obj, dict) and "official_controls" in obj and "science" in obj:\n                candidates.append(("GLOB_FALLBACK", p, obj))\n\n    if not candidates:\n        raise RuntimeError("could not locate frozen v028ar-r1 object containing official_controls and science")\n\n    # If more than one resolves to the same path/object family, choose the first\n    # deterministically but require source-stage provenance to look like v028ar.\n    candidates.sort(key=lambda x: (str(x[1]), x[0]))\n    valid = []\n    for name, p, obj in candidates:\n        stage = str(obj.get("stage", "")).lower()\n        if "v028ar" in stage or "physical" in stage or "morphology" in stage:\n            valid.append((name, p, obj))\n    if valid:\n        candidates = valid\n\n    # Multiple distinct candidate files are a provenance ambiguity: stop.\n    unique_paths = sorted({str(x[1].resolve()) for x in candidates})\n    if len(unique_paths) != 1:\n        raise RuntimeError(f"ambiguous v028ar source JSON candidates: {unique_paths}")\n\n    return candidates[0]\n\n\ndef close(a, b, tol=TOL):\n    return abs(float(a) - float(b)) <= tol\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — PLATE-WIDE STELLAR-SHAPE PREVALENCE v028bl")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (BJ, BK, AS_RESULT, AS_SOURCE):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    actual_sha = sha256(AS_SOURCE)\n    if actual_sha != EXPECTED_AS_SHA:\n        print(f"FAIL v028as source hash changed: {actual_sha}")\n        return 3\n\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    bk = json.loads(BK.read_text(encoding="utf-8"))\n    prior = json.loads(AS_RESULT.read_text(encoding="utf-8"))\n\n    if int(bj.get("summary", {}).get("usable_metric_rows", -1)) != EXPECTED_USABLE:\n        print("FAIL v028bj usable metric count changed")\n        return 3\n    if not bk.get("next_gate", {}).get("platewide_stellar_shape_prevalence_classifier_may_be_built"):\n        print("FAIL v028bk classifier gate is not enabled")\n        return 3\n\n    asmod = load_module(AS_SOURCE, "validated_v028as_platewide_prevalence")\n    for name in ("derived", "robust_center_scale", "distance"):\n        if not hasattr(asmod, name):\n            print(f"FAIL v028as missing {name}")\n            return 3\n\n    feature_names = list(getattr(asmod, "FEATURES", []))\n    retained_features = list(prior.get("feature_names", []))\n    if feature_names != retained_features or len(feature_names) != 9:\n        print(f"FAIL feature-vector guard mismatch: source={feature_names} retained={retained_features}")\n        return 3\n\n    src_name, src_path, src = locate_v028ar_source_object(asmod)\n    controls = list(src.get("official_controls", []))\n    science = list(src.get("science", []))\n\n    if len(controls) < 8:\n        print(f"FAIL too few official controls: {len(controls)}")\n        return 3\n    if sorted(int(r["strict_rank"]) for r in science) != SCIENCE_RANKS:\n        print("FAIL v028ar science rank guard mismatch")\n        return 3\n\n    cder = [asmod.derived(r) for r in controls]\n    good_controls = []\n    good_cder = []\n    for r, d in zip(controls, cder):\n        if all(d.get(k) is not None and math.isfinite(float(d[k])) for k in feature_names):\n            good_controls.append(r)\n            good_cder.append(d)\n\n    if len(good_controls) < 8:\n        print(f"FAIL too few complete official controls: {len(good_controls)}")\n        return 3\n\n    X = np.array([[d[k] for k in feature_names] for d in good_cder], float)\n    med, scale = asmod.robust_center_scale(X)\n    Z = (X - med) / scale\n\n    loo_nn = []\n    for j in range(len(Z)):\n        ds = [asmod.distance(Z[j], Z[k]) for k in range(len(Z)) if k != j]\n        loo_nn.append(min(ds))\n\n    loo_p50 = float(np.median(loo_nn))\n    loo_p90 = float(np.quantile(loo_nn, 0.90))\n    loo_p95 = float(np.quantile(loo_nn, 0.95))\n    loo_max = float(np.max(loo_nn))\n\n    ctrl_amp = [\n        float(d["amplitude_ap5"])\n        for d in good_cder\n        if d.get("amplitude_ap5") is not None and math.isfinite(float(d["amplitude_ap5"]))\n    ]\n    amp_min = float(np.min(ctrl_amp))\n    amp_max = float(np.max(ctrl_amp))\n\n    # Strong regression against retained v028as result.\n    retained_loo = prior.get("control_loo_nearest_distance", {})\n    retained_amp = prior.get("control_ap5_range", {})\n    regressions = {\n        "complete_control_count": len(good_controls) == int(prior.get("complete_official_control_count", -1)),\n        "loo_median": close(loo_p50, retained_loo.get("median")),\n        "loo_p90": close(loo_p90, retained_loo.get("p90")),\n        "loo_p95": close(loo_p95, retained_loo.get("p95")),\n        "loo_max": close(loo_max, retained_loo.get("max")),\n        "amp_min": close(amp_min, retained_amp.get("min")),\n        "amp_max": close(amp_max, retained_amp.get("max")),\n    }\n    if not all(regressions.values()):\n        print(f"FAIL retained-v028as regression mismatch: {regressions}")\n        print(f"Computed LOO: median={loo_p50} p90={loo_p90} p95={loo_p95} max={loo_max}")\n        print(f"Computed amp: min={amp_min} max={amp_max}")\n        return 4\n\n    science_summaries = {\n        int(r["strict_rank"]): r for r in prior.get("summaries", [])\n    }\n    if sorted(science_summaries) != SCIENCE_RANKS:\n        print("FAIL retained science-summary ranks mismatch")\n        return 4\n\n    usable = [r for r in bj.get("results", []) if r.get("status") == "SUCCESS"]\n    if len(usable) != EXPECTED_USABLE:\n        print(f"FAIL SUCCESS row count {len(usable)} != {EXPECTED_USABLE}")\n        return 4\n\n    out_rows = []\n    class_counts = Counter()\n    amp_counts = Counter()\n    incomplete = 0\n\n    for r in usable:\n        metrics = r.get("raw_metrics")\n        if not isinstance(metrics, dict):\n            print(f"FAIL q{r.get(\'queue_order\')}: missing raw_metrics")\n            return 5\n\n        d = asmod.derived(metrics)\n        complete = all(\n            d.get(k) is not None and math.isfinite(float(d[k]))\n            for k in feature_names\n        )\n\n        if not complete:\n            incomplete += 1\n            rec = {\n                "queue_order": r.get("queue_order"),\n                "tile_id": r.get("tile_id"),\n                "candidate_index": r.get("candidate_index"),\n                "ra_deg": r.get("ra_deg"),\n                "dec_deg": r.get("dec_deg"),\n                "snr": r.get("snr"),\n                "shape_classification": "INCOMPLETE_SHAPE_VECTOR",\n            }\n            out_rows.append(rec)\n            class_counts["INCOMPLETE_SHAPE_VECTOR"] += 1\n            continue\n\n        x = np.array([d[k] for k in feature_names], float)\n        z = (x - med) / scale\n        ds = [asmod.distance(z, Z[k]) for k in range(len(Z))]\n        nn = float(min(ds))\n        nearest_idx = int(np.argmin(ds))\n        nn_pct = empirical_percentile(loo_nn, nn)\n\n        amp = finite(d.get("amplitude_ap5"))\n        amp_pct = empirical_percentile(ctrl_amp, amp) if amp is not None else None\n        if amp is None:\n            amp_side = "AMPLITUDE_UNAVAILABLE"\n            outside_amp = None\n        elif amp > amp_max:\n            amp_side = "ABOVE_CONTROL_RANGE"\n            outside_amp = True\n        elif amp < amp_min:\n            amp_side = "BELOW_CONTROL_RANGE"\n            outside_amp = True\n        else:\n            amp_side = "WITHIN_CONTROL_RANGE"\n            outside_amp = False\n\n        if nn <= loo_p95:\n            shape_class = "CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD"\n        elif nn <= loo_max:\n            shape_class = "MARGINAL_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"\n        else:\n            shape_class = "STRONG_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"\n\n        cr = good_controls[nearest_idx]\n        rec = {\n            "queue_order": r.get("queue_order"),\n            "tile_id": r.get("tile_id"),\n            "candidate_index": r.get("candidate_index"),\n            "ra_deg": r.get("ra_deg"),\n            "dec_deg": r.get("dec_deg"),\n            "snr": r.get("snr"),\n            "nearest_shape_distance": nn,\n            "nearest_shape_distance_vs_control_loo_percentile": nn_pct,\n            "shape_classification": shape_class,\n            "ap5_amplitude": amp,\n            "ap5_control_percentile": amp_pct,\n            "ap5_control_min": amp_min,\n            "ap5_control_max": amp_max,\n            "amplitude_support_status": amp_side,\n            "amplitude_extrapolation": outside_amp,\n            "nearest_official_control_ref_number": cr.get("ref_number"),\n            "nearest_official_control_ra_deg": cr.get("ra_deg"),\n            "nearest_official_control_dec_deg": cr.get("dec_deg"),\n            "nearest_official_control_tile_id": cr.get("tile_id"),\n        }\n        out_rows.append(rec)\n        class_counts[shape_class] += 1\n        amp_counts[amp_side] += 1\n\n    classifiable = EXPECTED_USABLE - incomplete\n    consistent_n = class_counts["CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD"]\n    marginal_n = class_counts["MARGINAL_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"]\n    strong_n = class_counts["STRONG_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"]\n\n    science_nn = {\n        rank: float(science_summaries[rank]["nearest_shape_distance"])\n        for rank in SCIENCE_RANKS\n    }\n\n    control_nn = [\n        float(r["nearest_shape_distance"])\n        for r in out_rows if r.get("nearest_shape_distance") is not None\n    ]\n\n    science_comparison = {}\n    for rank in SCIENCE_RANKS:\n        s = science_nn[rank]\n        n_closer = sum(v <= s for v in control_nn)\n        science_comparison[str(rank)] = {\n            "science_nearest_shape_distance": s,\n            "platewide_controls_at_least_as_close_to_official_shape_cloud": n_closer,\n            "fraction_of_classifiable_controls": n_closer / classifiable,\n        }\n\n    science_min = min(science_nn.values())\n    science_max = max(science_nn.values())\n    at_least_most_starlike = sum(v <= science_min for v in control_nn)\n    at_least_least_starlike = sum(v <= science_max for v in control_nn)\n    within_science_nn_range = sum(science_min <= v <= science_max for v in control_nn)\n\n    print(f"Official control source: {src_path.relative_to(ROOT)} ({src_name})")\n    print(f"Complete official controls: {len(good_controls)}")\n    print(\n        "Official control LOO NN: "\n        f"median={loo_p50:.6f} p90={loo_p90:.6f} "\n        f"p95={loo_p95:.6f} max={loo_max:.6f}"\n    )\n    print(f"Official ap5 range: {amp_min:.6f} .. {amp_max:.6f}")\n    print(f"Plate-wide usable rows: {EXPECTED_USABLE}")\n    print(f"Classifiable rows: {classifiable}")\n    print(f"Incomplete vectors: {incomplete}")\n    print()\n    print(\n        f"CONSISTENT: {consistent_n}/{classifiable} "\n        f"({100*consistent_n/classifiable:.3f}%)"\n    )\n    print(\n        f"MARGINAL:   {marginal_n}/{classifiable} "\n        f"({100*marginal_n/classifiable:.3f}%)"\n    )\n    print(\n        f"STRONG:     {strong_n}/{classifiable} "\n        f"({100*strong_n/classifiable:.3f}%)"\n    )\n    print("\\nScience-distance comparison:")\n    for rank in SCIENCE_RANKS:\n        x = science_comparison[str(rank)]\n        print(\n            f"  #{rank:02d} NN={x[\'science_nearest_shape_distance\']:.6f}: "\n            f"{x[\'platewide_controls_at_least_as_close_to_official_shape_cloud\']}/"\n            f"{classifiable} ({100*x[\'fraction_of_classifiable_controls\']:.3f}%) "\n            f"controls are at least as close"\n        )\n    print(\n        f"\\nControls at least as close as MOST star-like science endpoint "\n        f"(NN <= {science_min:.6f}): {at_least_most_starlike}/{classifiable} "\n        f"({100*at_least_most_starlike/classifiable:.3f}%)"\n    )\n    print(\n        f"Controls at least as close as LEAST star-like science endpoint "\n        f"(NN <= {science_max:.6f}): {at_least_least_starlike}/{classifiable} "\n        f"({100*at_least_least_starlike/classifiable:.3f}%)"\n    )\n\n    payload = {\n        "stage": "ORDER01_DASCH_PLATEWIDE_STELLAR_SHAPE_PREVALENCE_V028BL",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n            "platewide_metrics_reused_from": "v028bj",\n            "official_control_scaling_reconstructed_from_frozen_v028ar_r1": True,\n            "amplitude_removed_from_shape_distance": True,\n        },\n        "source_hash": actual_sha,\n        "official_control_source": str(src_path.relative_to(ROOT)),\n        "feature_names": feature_names,\n        "official_reference_cloud": {\n            "complete_control_count": len(good_controls),\n            "loo_nearest_distance": {\n                "median": loo_p50,\n                "p90": loo_p90,\n                "p95": loo_p95,\n                "max": loo_max,\n            },\n            "ap5_range": {"min": amp_min, "max": amp_max},\n            "retained_v028as_regression": regressions,\n        },\n        "platewide_population": {\n            "v028bj_usable_rows": EXPECTED_USABLE,\n            "classifiable_rows": classifiable,\n            "incomplete_shape_vectors": incomplete,\n            "shape_class_counts": dict(class_counts),\n            "shape_class_fractions_of_classifiable": {\n                k: v / classifiable\n                for k, v in class_counts.items()\n                if k != "INCOMPLETE_SHAPE_VECTOR"\n            },\n            "amplitude_status_counts": dict(amp_counts),\n        },\n        "science_reference": {\n            "summaries": [science_summaries[r] for r in SCIENCE_RANKS],\n            "control_comparison_by_rank": science_comparison,\n            "science_nearest_shape_distance_min": science_min,\n            "science_nearest_shape_distance_max": science_max,\n            "controls_at_least_as_close_as_most_starlike_science": at_least_most_starlike,\n            "controls_at_least_as_close_as_least_starlike_science": at_least_least_starlike,\n            "controls_within_science_nn_range": within_science_nn_range,\n        },\n        "rows": out_rows,\n        "interpretive_boundary": (\n            "This is a morphology-prevalence result for non-science detector +1 "\n            "native detections lacking an official DR7 source within 10 arcsec. "\n            "Shape consistency with official stellar controls is not evidence of "\n            "astrophysical transience; photographic defects, blends, unresolved "\n            "sources, extraction failures, and other plate phenomena remain viable."\n        ),\n        "next_gate": {\n            "platewide_phenotype_synthesis_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    fields = [\n        "queue_order", "tile_id", "candidate_index", "ra_deg", "dec_deg", "snr",\n        "nearest_shape_distance", "nearest_shape_distance_vs_control_loo_percentile",\n        "shape_classification", "ap5_amplitude", "ap5_control_percentile",\n        "ap5_control_min", "ap5_control_max", "amplitude_support_status",\n        "amplitude_extrapolation", "nearest_official_control_ref_number",\n        "nearest_official_control_ra_deg", "nearest_official_control_dec_deg",\n        "nearest_official_control_tile_id",\n    ]\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(out_rows)\n\n    md = [\n        "# ORDER 01 — Plate-wide Stellar-Shape Prevalence v028bl",\n        "",\n        f"- Classifiable controls: **{classifiable}** / {EXPECTED_USABLE}.",\n        f"- Consistent with official stellar-shape cloud: **{consistent_n}** "\n        f"({100*consistent_n/classifiable:.3f}%).",\n        f"- Marginal shape outliers: **{marginal_n}** "\n        f"({100*marginal_n/classifiable:.3f}%).",\n        f"- Strong shape outliers: **{strong_n}** "\n        f"({100*strong_n/classifiable:.3f}%).",\n        "",\n        "## Science-endpoint comparison",\n        "",\n    ]\n    for rank in SCIENCE_RANKS:\n        x = science_comparison[str(rank)]\n        md.append(\n            f"- #{rank}: NN {x[\'science_nearest_shape_distance\']:.3f}; "\n            f"**{x[\'platewide_controls_at_least_as_close_to_official_shape_cloud\']}** "\n            f"controls ({100*x[\'fraction_of_classifiable_controls\']:.3f}%) "\n            "are at least as close to the official shape cloud."\n        )\n    md += [\n        "",\n        "Overall amplitude is excluded from the shape distance and is reported separately.",\n        "No pixels were read in this stage; v028bj metrics were reused.",\n        "",\n        "A stellar-like single-plate image is not thereby an astrophysical transient.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_platewide_stellar_shape_prevalence_v028bl",
        title="Classify plate-wide non-science morphology against frozen official stellar-shape cloud",
        script="automation/stages/classify_platewide_stellar_shape_prevalence_v028bl.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
            "results/order01_native_full_v028/order01_dasch_stellar_shape_classifier_contract_v028bk.json",
            "results/order01_native_full_v028/order01_dasch_stellar_shape_v028as.json",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_platewide_stellar_shape_prevalence_v028bl.json",
        ),
        dependencies=("dasch_stellar_shape_classifier_contract_v028bk",),
        notes="No network/pixels; exact frozen v028as 9-feature classifier applied to all 2587 v028bj usable controls, with amplitude reported separately.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_platewide_stellar_shape_prevalence_v028bl"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.7 — PLATE-WIDE STELLAR-SHAPE PREVALENCE")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
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
        "Transient automation v0.1.7 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.1.7"\n', encoding="utf-8")

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
        r'verify-stage --stage dasch_platewide_stellar_shape_prevalence_v028bl'
    )
    print("\nNo network or pixel access is required by v028bl.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
