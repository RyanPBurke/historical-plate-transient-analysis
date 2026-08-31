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
STAGE = AUTO / "stages" / "rank_science25_direct_shape_neighbours_v028bo.py"
BACKUP = AUTO / "backups" / "pre_v020"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport importlib.util\nimport json\nimport math\nimport sys\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nAR_JSON = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"\nAS_JSON = BASE / "order01_dasch_stellar_shape_v028as.json"\nAS_SRC = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\nQUEUE = ROOT / "automation" / "queues" / "ai43437_platewide_morphology_v028bg.json"\n\nOUT_JSON = BASE / "order01_dasch_science25_direct_shape_neighbourhood_v028bo.json"\nOUT_CSV = BASE / "order01_dasch_science25_direct_shape_neighbours_v028bo.csv"\nOUT_MD = BASE / "ORDER01_DASCH_SCIENCE25_DIRECT_SHAPE_NEIGHBOURHOOD_V028BO.md"\n\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\nTARGET_RANK = 25\nEXPECTED_CONTROLS = 2587\nTOP_N = 50\n\n\ndef load_module(path, name):\n    spec = importlib.util.spec_from_file_location(name, path)\n    if spec is None or spec.loader is None:\n        raise RuntimeError(f"cannot import {path}")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef finite(v):\n    try:\n        x = float(v)\n        return x if math.isfinite(x) else None\n    except Exception:\n        return None\n\n\ndef empirical_percentile(vals, x):\n    vals = [float(v) for v in vals if finite(v) is not None]\n    if not vals or finite(x) is None:\n        return None\n    return sum(v <= float(x) for v in vals) / len(vals)\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — SCIENCE #25 DIRECT SHAPE NEIGHBOURHOOD v028bo")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (BJ, AR_JSON, AS_JSON, AS_SRC, QUEUE):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    ar = json.loads(AR_JSON.read_text(encoding="utf-8"))\n    old = json.loads(AS_JSON.read_text(encoding="utf-8"))\n    queue = json.loads(QUEUE.read_text(encoding="utf-8"))\n    asmod = load_module(AS_SRC, "validated_v028as_direct25")\n\n    features = list(asmod.FEATURES)\n    if features != list(old.get("feature_names", [])) or len(features) != 9:\n        print("FAIL frozen feature-vector mismatch")\n        return 3\n\n    official_controls = list(ar.get("official_controls", []))\n    science_rows = {int(r["strict_rank"]): r for r in ar.get("science", [])}\n    if sorted(science_rows) != SCIENCE_RANKS:\n        print(f"FAIL science ranks mismatch: {sorted(science_rows)}")\n        return 3\n\n    cder = [asmod.derived(r) for r in official_controls]\n    good_cder = [\n        d for d in cder\n        if all(d.get(k) is not None and math.isfinite(float(d[k])) for k in features)\n    ]\n    if len(good_cder) != int(old.get("complete_official_control_count", -1)):\n        print("FAIL complete official-control count regression")\n        return 3\n\n    X = np.array([[d[k] for k in features] for d in good_cder], float)\n    med, scale = asmod.robust_center_scale(X)\n\n    science_z = {}\n    science_d = {}\n    for rank in SCIENCE_RANKS:\n        d = asmod.derived(science_rows[rank])\n        if not all(d.get(k) is not None and math.isfinite(float(d[k])) for k in features):\n            print(f"FAIL science #{rank}: incomplete feature vector")\n            return 3\n        science_d[rank] = d\n        x = np.array([d[k] for k in features], float)\n        science_z[rank] = (x - med) / scale\n\n    target_z = science_z[TARGET_RANK]\n    target_d = science_d[TARGET_RANK]\n    target_amp = finite(target_d.get("amplitude_ap5"))\n\n    # Queue provenance carries the frozen nearest-official separation.\n    qitems = {int(r["queue_order"]): r for r in queue.get("items", [])}\n\n    controls = []\n    for r in bj.get("results", []):\n        if r.get("status") != "SUCCESS":\n            continue\n        order = int(r["queue_order"])\n        q = qitems.get(order)\n        if q is None:\n            print(f"FAIL q{order}: missing frozen queue provenance")\n            return 4\n\n        metrics = r.get("raw_metrics")\n        if not isinstance(metrics, dict):\n            print(f"FAIL q{order}: missing raw metrics")\n            return 4\n\n        d = asmod.derived(metrics)\n        if not all(d.get(k) is not None and math.isfinite(float(d[k])) for k in features):\n            print(f"FAIL q{order}: incomplete derived vector")\n            return 4\n\n        x = np.array([d[k] for k in features], float)\n        z = (x - med) / scale\n        direct = float(asmod.distance(z, target_z))\n        amp = finite(d.get("amplitude_ap5"))\n\n        if amp is None:\n            amp_status = "AMPLITUDE_UNAVAILABLE"\n        else:\n            amin = float(old["control_ap5_range"]["min"])\n            amax = float(old["control_ap5_range"]["max"])\n            if amp > amax:\n                amp_status = "ABOVE_CONTROL_RANGE"\n            elif amp < amin:\n                amp_status = "BELOW_CONTROL_RANGE"\n            else:\n                amp_status = "WITHIN_CONTROL_RANGE"\n\n        controls.append({\n            "queue_order": order,\n            "tile_id": r.get("tile_id"),\n            "candidate_index": r.get("candidate_index"),\n            "ra_deg": r.get("ra_deg"),\n            "dec_deg": r.get("dec_deg"),\n            "snr": r.get("snr"),\n            "nearest_official_sep_arcsec": finite(q.get("nearest_official_sep_arcsec")),\n            "shape_nn_to_official_cloud": None,  # filled from v028bl-equivalent calculation below\n            "direct_shape_distance_to_science25": direct,\n            "amplitude_ap5": amp,\n            "amplitude_support_status": amp_status,\n            "amplitude_ratio_to_science25":\n                (amp / target_amp) if amp is not None and target_amp not in (None, 0) else None,\n        })\n\n    if len(controls) != EXPECTED_CONTROLS:\n        print(f"FAIL expected {EXPECTED_CONTROLS} controls, got {len(controls)}")\n        return 4\n\n    # Also reconstruct each control\'s nearest distance to official shape cloud\n    # for context only; this is not used to select the direct neighbours.\n    Zoff = (X - med) / scale\n    for rec, r in zip(controls, [r for r in bj.get("results", []) if r.get("status") == "SUCCESS"]):\n        d = asmod.derived(r["raw_metrics"])\n        x = np.array([d[k] for k in features], float)\n        z = (x - med) / scale\n        rec["shape_nn_to_official_cloud"] = float(min(asmod.distance(z, zz) for zz in Zoff))\n\n    controls.sort(key=lambda r: (r["direct_shape_distance_to_science25"], r["queue_order"]))\n    direct_vals = [r["direct_shape_distance_to_science25"] for r in controls]\n\n    top = controls[:TOP_N]\n    nearest = controls[0]\n    above = [r for r in controls if r["amplitude_support_status"] == "ABOVE_CONTROL_RANGE"]\n    nearest_above = above[0] if above else None\n\n    # Science-to-science distances in the exact same normalized 9-D space.\n    science_pair = {}\n    for rank in SCIENCE_RANKS:\n        if rank == TARGET_RANK:\n            continue\n        dist = float(asmod.distance(target_z, science_z[rank]))\n        science_pair[str(rank)] = {\n            "distance_from_science25": dist,\n            "controls_closer_to_science25": sum(v <= dist for v in direct_vals),\n            "fraction_controls_closer_to_science25": sum(v <= dist for v in direct_vals) / len(controls),\n        }\n\n    nearest_other_science_rank = min(\n        (r for r in SCIENCE_RANKS if r != TARGET_RANK),\n        key=lambda rank: science_pair[str(rank)]["distance_from_science25"],\n    )\n    nearest_other_science_dist = science_pair[str(nearest_other_science_rank)]["distance_from_science25"]\n    controls_closer_than_nearest_other_science = sum(v <= nearest_other_science_dist for v in direct_vals)\n\n    # Descriptive direct-distance quantiles.\n    quantiles = {\n        "min": float(np.min(direct_vals)),\n        "p01": float(np.quantile(direct_vals, 0.01)),\n        "p05": float(np.quantile(direct_vals, 0.05)),\n        "p10": float(np.quantile(direct_vals, 0.10)),\n        "median": float(np.median(direct_vals)),\n        "p90": float(np.quantile(direct_vals, 0.90)),\n        "max": float(np.max(direct_vals)),\n    }\n\n    print(f"Comparable controls: {len(controls)}")\n    print(f"#25 AP5 amplitude: {target_amp:.6f}")\n    print("Direct-distance distribution to #25:")\n    for k, v in quantiles.items():\n        print(f"  {k}: {v:.6f}")\n\n    print("\\nNEAREST DIRECT CONTROL TO #25")\n    print(\n        f"  q{nearest[\'queue_order\']:04d} distance={nearest[\'direct_shape_distance_to_science25\']:.6f} "\n        f"amp={nearest[\'amplitude_support_status\']} "\n        f"ampRatio={nearest[\'amplitude_ratio_to_science25\']:.4f} "\n        f"NNofficial={nearest[\'shape_nn_to_official_cloud\']:.6f}"\n    )\n\n    if nearest_above is not None:\n        rank_idx = controls.index(nearest_above) + 1\n        print("\\nNEAREST DIRECT ABOVE-CONTROL-AMPLITUDE CONTROL TO #25")\n        print(\n            f"  q{nearest_above[\'queue_order\']:04d} directRank={rank_idx}/{len(controls)} "\n            f"distance={nearest_above[\'direct_shape_distance_to_science25\']:.6f} "\n            f"ampRatio={nearest_above[\'amplitude_ratio_to_science25\']:.4f} "\n            f"NNofficial={nearest_above[\'shape_nn_to_official_cloud\']:.6f}"\n        )\n\n    print("\\nSCIENCE-TO-SCIENCE DISTANCES FROM #25")\n    for rank in SCIENCE_RANKS:\n        if rank == TARGET_RANK:\n            continue\n        x = science_pair[str(rank)]\n        print(\n            f"  #25 -> #{rank:02d}: {x[\'distance_from_science25\']:.6f}; "\n            f"{x[\'controls_closer_to_science25\']}/{len(controls)} "\n            f"({100*x[\'fraction_controls_closer_to_science25\']:.3f}%) controls are closer"\n        )\n\n    print(\n        f"\\nNearest other science endpoint to #25: #{nearest_other_science_rank} "\n        f"distance={nearest_other_science_dist:.6f}; "\n        f"{controls_closer_than_nearest_other_science}/{len(controls)} controls are closer to #25"\n    )\n\n    print(f"\\nTOP {TOP_N} DIRECT CONTROLS")\n    for pos, r in enumerate(top, 1):\n        print(\n            f"  {pos:02d}. q{r[\'queue_order\']:04d} "\n            f"d25={r[\'direct_shape_distance_to_science25\']:.6f} "\n            f"amp={r[\'amplitude_support_status\']} "\n            f"ampRatio={r[\'amplitude_ratio_to_science25\']:.3f} "\n            f"NNoff={r[\'shape_nn_to_official_cloud\']:.6f} "\n            f"nearestOfficial={r[\'nearest_official_sep_arcsec\']:.1f}\\""\n        )\n\n    payload = {\n        "stage": "ORDER01_DASCH_SCIENCE25_DIRECT_SHAPE_NEIGHBOURHOOD_V028BO",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n            "metrics_reused_from_v028bj": True,\n            "science25_metrics_reused_from_v028ar_r1": True,\n        },\n        "feature_names": features,\n        "science25": {\n            "ap5_amplitude": target_amp,\n            "shape_nn_to_official_cloud": float(\n                old["summaries"][SCIENCE_RANKS.index(TARGET_RANK)]["nearest_shape_distance"]\n            ),\n        },\n        "direct_distance_distribution": quantiles,\n        "nearest_direct_control": nearest,\n        "nearest_direct_above_control_amplitude_control": nearest_above,\n        "science25_to_other_science_distances": science_pair,\n        "nearest_other_science_rank": nearest_other_science_rank,\n        "nearest_other_science_distance": nearest_other_science_dist,\n        "controls_closer_to_science25_than_nearest_other_science":\n            controls_closer_than_nearest_other_science,\n        "top_direct_controls": top,\n        "all_controls": controls,\n        "interpretive_boundary": (\n            "This stage ranks all comparable plate-wide controls by direct distance "\n            "to science #25 in the frozen amplitude-normalized 9-feature v028as space. "\n            "It corrects the earlier use of \'nearest to the official stellar cloud\' "\n            "as a proxy for direct similarity to #25. Direct similarity and amplitude "\n            "status remain descriptive controls, not astrophysical p-values."\n        ),\n        "next_gate": {\n            "science25_direct_analogue_selection_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    fields = list(top[0].keys())\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(top)\n\n    md = [\n        "# ORDER 01 — Science #25 Direct Shape Neighbourhood v028bo",\n        "",\n        f"- Comparable controls: **{len(controls)}**.",\n        f"- Nearest direct control: **q{nearest[\'queue_order\']:04d}**, "\n        f"distance **{nearest[\'direct_shape_distance_to_science25\']:.4f}**.",\n    ]\n    if nearest_above is not None:\n        md.append(\n            f"- Nearest direct `ABOVE_CONTROL_RANGE` amplitude control: "\n            f"**q{nearest_above[\'queue_order\']:04d}**, "\n            f"distance **{nearest_above[\'direct_shape_distance_to_science25\']:.4f}**."\n        )\n    md += [\n        f"- Nearest other science endpoint to #25: **#{nearest_other_science_rank}**, "\n        f"distance **{nearest_other_science_dist:.4f}**.",\n        f"- Controls closer to #25 than that science endpoint: "\n        f"**{controls_closer_than_nearest_other_science}/{len(controls)}**.",\n        "",\n        "No pixels or network were accessed.",\n        "Direct shape similarity is descriptive and does not establish astrophysical transience.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_science25_direct_shape_neighbourhood_v028bo",
        title="Rank all plate-wide controls by direct frozen 9-D morphology distance to science #25",
        script="automation/stages/rank_science25_direct_shape_neighbours_v028bo.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
            "results/order01_native_full_v028/order01_dasch_physical_morphology_v028ar_r1.json",
            "results/order01_native_full_v028/order01_dasch_stellar_shape_v028as.json",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
            "automation/queues/ai43437_platewide_morphology_v028bg.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_science25_direct_shape_neighbourhood_v028bo.json",
        ),
        dependencies=("dasch_science25_targeted_analogue_audit_v028bn",),
        notes="No network/pixels; corrects official-cloud proximity proxy by ranking all 2587 controls by direct 9-D distance to #25.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_science25_direct_shape_neighbourhood_v028bo"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.2.0 — SCIENCE #25 DIRECT SHAPE NEIGHBOURHOOD")
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
        "Transient automation v0.2.0 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")

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
        r'verify-stage --stage dasch_science25_direct_shape_neighbourhood_v028bo'
    )
    print("\nNo network or pixel access is required by v028bo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
