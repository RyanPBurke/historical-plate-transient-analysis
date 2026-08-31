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
STAGE = AUTO / "stages" / "synthesize_platewide_phenotype_v028bm.py"
BACKUP = AUTO / "backups" / "pre_v018"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom collections import Counter, defaultdict\nfrom pathlib import Path\n\nimport numpy as np\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\n\nBL = BASE / "order01_dasch_platewide_stellar_shape_prevalence_v028bl.json"\nAS = BASE / "order01_dasch_stellar_shape_v028as.json"\nBG = BASE / "order01_dasch_platewide_census_interpretation_and_morphology_queue_v028bg.json"\nQUEUE = AUTO / "queues" / "ai43437_platewide_morphology_v028bg.json"\n\nOUT_JSON = BASE / "order01_dasch_platewide_phenotype_synthesis_v028bm.json"\nOUT_CSV = BASE / "order01_dasch_platewide_science_analogue_controls_v028bm.csv"\nOUT_MD = BASE / "ORDER01_DASCH_PLATEWIDE_PHENOTYPE_SYNTHESIS_V028BM.md"\n\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\nEXPECTED_CONTROLS = 2587\n\n\ndef f(v, default=None):\n    try:\n        x = float(v)\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef pct(vals, x):\n    vals = [float(v) for v in vals if f(v) is not None]\n    if not vals or f(x) is None:\n        return None\n    return sum(v <= float(x) for v in vals) / len(vals)\n\n\ndef qstats(vals):\n    vals = np.asarray([float(v) for v in vals if f(v) is not None], float)\n    if not len(vals):\n        return {}\n    return {\n        "min": float(np.min(vals)),\n        "p10": float(np.quantile(vals, 0.10)),\n        "p25": float(np.quantile(vals, 0.25)),\n        "median": float(np.median(vals)),\n        "p75": float(np.quantile(vals, 0.75)),\n        "p90": float(np.quantile(vals, 0.90)),\n        "max": float(np.max(vals)),\n    }\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — PLATE-WIDE PHENOTYPE SYNTHESIS v028bm")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (BL, AS, BG, QUEUE):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    bl = json.loads(BL.read_text(encoding="utf-8"))\n    old = json.loads(AS.read_text(encoding="utf-8"))\n    bg = json.loads(BG.read_text(encoding="utf-8"))\n    queue = json.loads(QUEUE.read_text(encoding="utf-8"))\n\n    rows = list(bl.get("rows", []))\n    rows = [r for r in rows if r.get("shape_classification") != "INCOMPLETE_SHAPE_VECTOR"]\n    if len(rows) != EXPECTED_CONTROLS:\n        print(f"FAIL expected {EXPECTED_CONTROLS} classifiable controls; got {len(rows)}")\n        return 3\n\n    science = {int(r["strict_rank"]): r for r in old.get("summaries", [])}\n    if sorted(science) != SCIENCE_RANKS:\n        print(f"FAIL science summaries mismatch: {sorted(science)}")\n        return 3\n\n    qitems = {\n        int(r["queue_order"]): r\n        for r in queue.get("items", [])\n    }\n    if len(qitems) != 2596:\n        print(f"FAIL frozen morphology queue count changed: {len(qitems)}")\n        return 3\n\n    # Enrich classifiable rows with the frozen >10" nearest-official separation.\n    enriched = []\n    for r in rows:\n        order = int(r["queue_order"])\n        qi = qitems.get(order)\n        if qi is None:\n            print(f"FAIL q{order}: queue provenance missing")\n            return 3\n        x = dict(r)\n        x["nearest_official_sep_arcsec"] = f(qi.get("nearest_official_sep_arcsec"))\n        enriched.append(x)\n\n    class_counts = Counter(r["shape_classification"] for r in enriched)\n    amp_counts = Counter(r["amplitude_support_status"] for r in enriched)\n    tile_counts = Counter(r["tile_id"] for r in enriched)\n\n    tile_summary = {}\n    for tile in sorted(tile_counts):\n        rr = [r for r in enriched if r["tile_id"] == tile]\n        cc = Counter(r["shape_classification"] for r in rr)\n        tile_summary[tile] = {\n            "count": len(rr),\n            "consistent": cc["CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD"],\n            "marginal": cc["MARGINAL_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"],\n            "strong": cc["STRONG_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"],\n            "consistent_fraction": cc["CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD"] / len(rr),\n            "shape_nn": qstats([r["nearest_shape_distance"] for r in rr]),\n            "snr": qstats([r["snr"] for r in rr]),\n            "nearest_official_sep_arcsec": qstats([r["nearest_official_sep_arcsec"] for r in rr]),\n        }\n\n    # Descriptive SNR quartiles; boundaries are data-derived rather than methodological thresholds.\n    snrs = np.asarray([float(r["snr"]) for r in enriched], float)\n    q25, q50, q75 = [float(np.quantile(snrs, q)) for q in (0.25, 0.50, 0.75)]\n\n    def snr_bin(s):\n        s = float(s)\n        if s <= q25:\n            return "Q1_LOWEST"\n        if s <= q50:\n            return "Q2"\n        if s <= q75:\n            return "Q3"\n        return "Q4_HIGHEST"\n\n    snr_groups = defaultdict(list)\n    for r in enriched:\n        snr_groups[snr_bin(r["snr"])].append(r)\n\n    snr_summary = {}\n    for name in ("Q1_LOWEST", "Q2", "Q3", "Q4_HIGHEST"):\n        rr = snr_groups[name]\n        cc = Counter(r["shape_classification"] for r in rr)\n        snr_summary[name] = {\n            "count": len(rr),\n            "snr": qstats([r["snr"] for r in rr]),\n            "shape_nn": qstats([r["nearest_shape_distance"] for r in rr]),\n            "consistent_fraction": cc["CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD"] / len(rr),\n            "marginal_fraction": cc["MARGINAL_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"] / len(rr),\n            "strong_fraction": cc["STRONG_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"] / len(rr),\n        }\n\n    # Per-science descriptive analogue sets.\n    science_context = {}\n    analogue_rows = []\n    for rank in SCIENCE_RANKS:\n        s = science[rank]\n        snn = float(s["nearest_shape_distance"])\n        samp_status = s["amplitude_support_status"]\n        samp = f(s.get("ap5_amplitude"))\n\n        as_close = [r for r in enriched if float(r["nearest_shape_distance"]) <= snn]\n        same_amp_status = [\n            r for r in as_close\n            if r.get("amplitude_support_status") == samp_status\n        ]\n\n        # SNR-nearest comparison: deterministic 10% of controls (259) by |SNR-science SNR|.\n        # This is descriptive only and does not alter the frozen shape classifier.\n        # Science SNR is reconstructed from the frozen known endpoints if available in summaries;\n        # if absent, omit this diagnostic rather than invent it.\n        science_snr = f(s.get("snr"))\n        snr_near = []\n        snr_near_as_close = None\n        if science_snr is not None:\n            k = max(1, int(round(0.10 * len(enriched))))\n            snr_near = sorted(\n                enriched,\n                key=lambda r: (\n                    abs(float(r["snr"]) - science_snr),\n                    int(r["queue_order"]),\n                )\n            )[:k]\n            snr_near_as_close = sum(\n                float(r["nearest_shape_distance"]) <= snn for r in snr_near\n            )\n\n        science_context[str(rank)] = {\n            "nearest_shape_distance": snn,\n            "shape_classification": s["shape_classification"],\n            "platewide_controls_at_least_as_close": len(as_close),\n            "platewide_fraction_at_least_as_close": len(as_close) / len(enriched),\n            "amplitude_support_status": samp_status,\n            "ap5_amplitude": samp,\n            "controls_at_least_as_close_and_same_amplitude_status": len(same_amp_status),\n            "fraction_at_least_as_close_and_same_amplitude_status": len(same_amp_status) / len(enriched),\n            "science_snr_if_retained": science_snr,\n            "snr_nearest_control_count_if_available": len(snr_near),\n            "snr_nearest_controls_at_least_as_close_if_available": snr_near_as_close,\n        }\n\n        # Retain up to 25 closest analogues for each endpoint; duplicates across ranks are okay in CSV\n        # because science_rank is part of the key and comparison context.\n        analogues = sorted(\n            as_close,\n            key=lambda r: (\n                float(r["nearest_shape_distance"]),\n                int(r["queue_order"]),\n            )\n        )[:25]\n        for pos, r in enumerate(analogues, 1):\n            analogue_rows.append({\n                "science_rank": rank,\n                "analogue_rank_within_science_threshold": pos,\n                "science_shape_nn": snn,\n                "science_amplitude_support_status": samp_status,\n                "queue_order": r["queue_order"],\n                "tile_id": r["tile_id"],\n                "candidate_index": r["candidate_index"],\n                "ra_deg": r["ra_deg"],\n                "dec_deg": r["dec_deg"],\n                "snr": r["snr"],\n                "shape_nn": r["nearest_shape_distance"],\n                "shape_classification": r["shape_classification"],\n                "amplitude_support_status": r["amplitude_support_status"],\n                "ap5_amplitude": r["ap5_amplitude"],\n                "nearest_official_sep_arcsec": r["nearest_official_sep_arcsec"],\n                "same_amplitude_support_status_as_science":\n                    r["amplitude_support_status"] == samp_status,\n            })\n\n    # The controls at least as star-like as #25 are especially useful targeted analogues.\n    s25 = science[25]\n    threshold25 = float(s25["nearest_shape_distance"])\n    top25_like = sorted(\n        [r for r in enriched if float(r["nearest_shape_distance"]) <= threshold25],\n        key=lambda r: (float(r["nearest_shape_distance"]), int(r["queue_order"]))\n    )\n\n    print(f"Classifiable comparable controls: {len(enriched)}")\n    print(\n        "Shape classes: "\n        f"consistent={class_counts[\'CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD\']} "\n        f"marginal={class_counts[\'MARGINAL_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS\']} "\n        f"strong={class_counts[\'STRONG_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS\']}"\n    )\n    print(f"SNR quartile boundaries: {q25:.6f}, {q50:.6f}, {q75:.6f}")\n    print("\\nSCIENCE PHENOTYPE CONTEXT")\n    for rank in SCIENCE_RANKS:\n        x = science_context[str(rank)]\n        print(\n            f"  #{rank:02d}: NN={x[\'nearest_shape_distance\']:.6f}; "\n            f"asClose={x[\'platewide_controls_at_least_as_close\']}/{len(enriched)} "\n            f"({100*x[\'platewide_fraction_at_least_as_close\']:.3f}%); "\n            f"amp={x[\'amplitude_support_status\']}; "\n            f"asClose+sameAmp={x[\'controls_at_least_as_close_and_same_amplitude_status\']} "\n            f"({100*x[\'fraction_at_least_as_close_and_same_amplitude_status\']:.3f}%)"\n        )\n\n    print("\\n#25-LIKE CONTROLS (shape NN <= #25)")\n    for r in top25_like:\n        print(\n            f"  q{int(r[\'queue_order\']):04d} tile={r[\'tile_id\']} "\n            f"NN={float(r[\'nearest_shape_distance\']):.6f} "\n            f"SNR={float(r[\'snr\']):.3f} "\n            f"amp={r[\'amplitude_support_status\']} "\n            f"nearestOfficial={float(r[\'nearest_official_sep_arcsec\']):.3f}\\""\n        )\n\n    frozen_correction = bg.get("v028bf_science_distance_correction", {})\n    payload = {\n        "stage": "ORDER01_DASCH_PLATEWIDE_PHENOTYPE_SYNTHESIS_V028BM",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "population": {\n            "classifiable_comparable_controls": len(enriched),\n            "shape_class_counts": dict(class_counts),\n            "amplitude_status_counts": dict(amp_counts),\n            "snr_quartile_boundaries": {\n                "q25": q25, "q50": q50, "q75": q75\n            },\n        },\n        "science_context": science_context,\n        "top_controls_at_least_as_starlike_as_science_25": top25_like,\n        "tile_summary": tile_summary,\n        "snr_quartile_summary": snr_summary,\n        "retained_science_official_distance_correction": frozen_correction,\n        "interpretive_boundary": (\n            "This synthesis contextualizes the six preserved single-plate DASCH images "\n            "within the comparable non-science +1/>10arcsec population. Rarity on any "\n            "single morphology or amplitude axis does not establish astrophysical reality. "\n            "The next use of the analogue list is targeted artifact/spatial inspection, "\n            "not automatic candidate promotion."\n        ),\n        "next_gate": {\n            "targeted_analogue_artifact_audit_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    fields = list(analogue_rows[0].keys())\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields)\n        w.writeheader()\n        w.writerows(analogue_rows)\n\n    md = [\n        "# ORDER 01 — Plate-wide Phenotype Synthesis v028bm",\n        "",\n        f"- Comparable classifiable controls: **{len(enriched)}**.",\n        f"- Stellar-shape consistent controls: **{class_counts[\'CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD\']}** "\n        f"({100*class_counts[\'CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD\']/len(enriched):.3f}%).",\n        "",\n        "## Science endpoints",\n        "",\n        "| rank | shape NN | controls at least as close | amplitude support | as-close + same amplitude status |",\n        "|---:|---:|---:|---|---:|",\n    ]\n    for rank in SCIENCE_RANKS:\n        x = science_context[str(rank)]\n        md.append(\n            f"| #{rank} | {x[\'nearest_shape_distance\']:.3f} | "\n            f"{x[\'platewide_controls_at_least_as_close\']} "\n            f"({100*x[\'platewide_fraction_at_least_as_close\']:.3f}%) | "\n            f"{x[\'amplitude_support_status\']} | "\n            f"{x[\'controls_at_least_as_close_and_same_amplitude_status\']} "\n            f"({100*x[\'fraction_at_least_as_close_and_same_amplitude_status\']:.3f}%) |"\n        )\n    md += [\n        "",\n        f"Controls at least as star-like as #25: **{len(top25_like)}**.",\n        "",\n        "No pixels or network were accessed. This is descriptive context, not an astrophysical classification.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_platewide_phenotype_synthesis_v028bm",
        title="Synthesize plate-wide morphology/amplitude context and targeted analogue controls",
        script="automation/stages/synthesize_platewide_phenotype_v028bm.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_platewide_stellar_shape_prevalence_v028bl.json",
            "results/order01_native_full_v028/order01_dasch_stellar_shape_v028as.json",
            "results/order01_native_full_v028/order01_dasch_platewide_census_interpretation_and_morphology_queue_v028bg.json",
            "automation/queues/ai43437_platewide_morphology_v028bg.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_platewide_phenotype_synthesis_v028bm.json",
        ),
        dependencies=("dasch_platewide_stellar_shape_prevalence_v028bl",),
        notes="No network/pixels; per-science shape/amplitude context, tile/SNR diagnostics, and targeted analogue list without promotion.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_platewide_phenotype_synthesis_v028bm"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.8 — PLATE-WIDE PHENOTYPE SYNTHESIS")
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
        "Transient automation v0.1.8 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.1.8"\n', encoding="utf-8")

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
        r'verify-stage --stage dasch_platewide_phenotype_synthesis_v028bm'
    )
    print("\nNo network or pixel access is required by v028bm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
