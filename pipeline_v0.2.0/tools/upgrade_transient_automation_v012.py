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
STAGE = AUTO / "stages" / "freeze_census_and_plan_morphology_v028bg.py"
BACKUP = AUTO / "backups" / "pre_v012"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport json\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\n\nCENSUS_JSON = BASE / "order01_dasch_platewide_official_association_census_v028bf.json"\nCENSUS_CSV = BASE / "order01_dasch_platewide_native_official_associations_v028bf.csv"\n\nOUT_JSON = BASE / "order01_dasch_platewide_census_interpretation_and_morphology_queue_v028bg.json"\nOUT_QUEUE_CSV = BASE / "order01_dasch_platewide_morphology_queue_v028bg.csv"\nOUT_QUEUE_JSON = AUTO / "queues" / "ai43437_platewide_morphology_v028bg.json"\nOUT_MD = BASE / "ORDER01_DASCH_PLATEWIDE_CENSUS_INTERPRETATION_AND_MORPHOLOGY_QUEUE_V028BG.md"\n\nEXPECTED_NONSCIENCE = 3980\nEXPECTED_PLUS_UNASSOCIATED = 2596\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\n\n# Frozen exact science-centred v028ao nearest-official separations.\n# These values are retained only to prevent accidental interpretation of the\n# incomplete science-neighbour pool in v028bf.\nFROZEN_V028AO_NEAREST_ARCSEC = {\n    10: 52.291,\n    24: 34.299,\n    25: 31.204,\n    26: 24.294,\n    29: 65.406,\n    30: 41.450,\n}\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef as_bool(v):\n    return str(v).strip().lower() in ("1", "true", "yes", "y")\n\n\ndef as_int(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef write_json(path, obj):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\\n", encoding="utf-8")\n    tmp.replace(path)\n\n\ndef write_csv(path, rows, fields):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    with tmp.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(rows)\n    tmp.replace(path)\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — v028bf INTERPRETATION FREEZE + PLATE-WIDE MORPHOLOGY QUEUE v028bg")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (CENSUS_JSON, CENSUS_CSV):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    census = json.loads(CENSUS_JSON.read_text(encoding="utf-8"))\n    rows = read_csv(CENSUS_CSV)\n\n    summary = census.get("summary", {})\n    if int(summary.get("non_science_rows", -1)) != EXPECTED_NONSCIENCE:\n        print("FAIL non-science count does not match frozen v028bf result")\n        return 3\n\n    if not summary.get(\n        "science_endpoint_regression_guard_no_official_within_10arcsec"\n    ):\n        print("FAIL v028bf science <=10 arcsec regression guard is false")\n        return 3\n\n    # v028bf is valid for the non-science association census because every\n    # non-science native position was covered by the 1693 prevalence queries.\n    # Its science nearest-neighbour *distances* are not valid for interpretation\n    # because those 1693 extra-query caches did not include all six original\n    # science-centred platephot caches.\n    science_rows = [r for r in rows if as_bool(r.get("is_science"))]\n    non_science = [r for r in rows if not as_bool(r.get("is_science"))]\n\n    if len(science_rows) != 6 or len(non_science) != EXPECTED_NONSCIENCE:\n        print(\n            f"FAIL census row partition mismatch science={len(science_rows)} "\n            f"nonScience={len(non_science)}"\n        )\n        return 3\n\n    plus_unassociated = [\n        r for r in non_science\n        if as_int(r.get("polarity")) == 1\n        and not as_bool(r.get("official_associated_le_10arcsec"))\n    ]\n\n    if len(plus_unassociated) != EXPECTED_PLUS_UNASSOCIATED:\n        print(\n            f"FAIL expected {EXPECTED_PLUS_UNASSOCIATED} +1/>10arcsec controls; "\n            f"got {len(plus_unassociated)}"\n        )\n        return 3\n\n    # Deterministic queue: highest SNR first, then tile/candidate identity.\n    def snr_key(r):\n        try:\n            return -float(r.get("snr") or 0.0)\n        except Exception:\n            return 0.0\n\n    plus_unassociated.sort(\n        key=lambda r: (\n            snr_key(r),\n            str(r.get("tile_id", "")),\n            as_int(r.get("candidate_index"), -1),\n        )\n    )\n\n    queue_rows = []\n    for qorder, r in enumerate(plus_unassociated, start=1):\n        queue_rows.append({\n            "queue_order": qorder,\n            "tile_id": r.get("tile_id"),\n            "candidate_index": as_int(r.get("candidate_index")),\n            "ra_deg": float(r.get("ra_deg")),\n            "dec_deg": float(r.get("dec_deg")),\n            "snr": float(r.get("snr")) if str(r.get("snr", "")).strip() else None,\n            "polarity": 1,\n            "nearest_official_sep_arcsec": float(\n                r.get("nearest_official_sep_arcsec")\n            ),\n            "official_associated_le_10arcsec": False,\n            "population": "NONSCIENCE_DETECTOR_PLUS1_UNASSOCIATED_GT10ARCSEC",\n        })\n\n    c10 = summary.get("counts_by_radius", {}).get("10", {})\n    plus_summary = summary.get("detector_polarity_plus1", {})\n    minus_summary = summary.get("detector_polarity_minus1", {})\n\n    payload = {\n        "stage": "ORDER01_DASCH_PLATEWIDE_CENSUS_INTERPRETATION_AND_MORPHOLOGY_QUEUE_V028BG",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "v028bf_valid_interpretation": {\n            "non_science_association_census_valid": True,\n            "non_science_rows": EXPECTED_NONSCIENCE,\n            "official_associated_le_10arcsec": int(\n                c10.get("associated_count", -1)\n            ),\n            "official_unassociated_gt_10arcsec": int(\n                c10.get("unassociated_count", -1)\n            ),\n            "official_associated_fraction": c10.get("associated_fraction"),\n            "detector_plus1": plus_summary,\n            "detector_minus1": minus_summary,\n            "all_six_science_unassociated_gt10arcsec": True,\n        },\n        "v028bf_science_distance_correction": {\n            "status": "SUPERSEDED_FOR_SCIENCE_NEAREST_DISTANCE_INTERPRETATION",\n            "reason": (\n                "v028bf pooled the 1693 additional non-science prevalence-query "\n                "caches, not the complete set of six original science-centred "\n                "platephot caches. Its <=10 arcsec science regression is valid, "\n                "but some larger nearest-neighbour distances are incomplete."\n            ),\n            "frozen_exact_v028ao_nearest_official_arcsec":\n                FROZEN_V028AO_NEAREST_ARCSEC,\n            "do_not_use_v028bf_science_empirical_nearest_sep_percentiles": True,\n        },\n        "morphology_queue": {\n            "queue_id": "AI43437_PLATEWIDE_MORPHOLOGY_V028BG",\n            "population": "NONSCIENCE_DETECTOR_PLUS1_UNASSOCIATED_GT10ARCSEC",\n            "count": len(queue_rows),\n            "ordering": "SNR_DESC_THEN_TILE_ID_THEN_CANDIDATE_INDEX",\n            "science_candidates_excluded": True,\n            "requires_pixel_read_in_next_stage": True,\n            "transient_detector_rerun_required": False,\n        },\n        "next_gate": {\n            "platewide_morphology_executor_may_be_built": True,\n        },\n        "interpretive_boundary": (\n            "The v028bf result shows that absence of an official DR7 source "\n            "within 10 arcsec is common among native detections and therefore "\n            "is not discriminating evidence by itself. The morphology queue "\n            "restricts the next control population to non-science detector +1 "\n            "detections with no official source within 10 arcsec, matching the "\n            "relevant direction/population of the six preserved science images."\n        ),\n    }\n\n    write_json(OUT_JSON, payload)\n    write_csv(\n        OUT_QUEUE_CSV,\n        queue_rows,\n        [\n            "queue_order", "tile_id", "candidate_index", "ra_deg", "dec_deg",\n            "snr", "polarity", "nearest_official_sep_arcsec",\n            "official_associated_le_10arcsec", "population",\n        ],\n    )\n\n    write_json(\n        OUT_QUEUE_JSON,\n        {\n            "queue_id": "AI43437_PLATEWIDE_MORPHOLOGY_V028BG",\n            "source_stage": "v028bg",\n            "count": len(queue_rows),\n            "items": queue_rows,\n        },\n    )\n\n    OUT_MD.write_text(\n        "# ORDER 01 — v028bf Interpretation Freeze + Morphology Queue v028bg\\n\\n"\n        f"- Non-science native detections: **{EXPECTED_NONSCIENCE}**.\\n"\n        f"- Official-associated within 10 arcsec: **{c10.get(\'associated_count\')}**.\\n"\n        f"- Detector +1 and >10 arcsec unassociated morphology controls: "\n        f"**{len(queue_rows)}**.\\n"\n        "- v028bf science nearest-distance/percentile fields are superseded for "\n        "interpretation; frozen exact v028ao distances remain authoritative.\\n"\n        "- The <=10 arcsec science regression remains valid for all six.\\n\\n"\n        "No pixels were read and no candidate state changed.\\n",\n        encoding="utf-8",\n    )\n\n    print(f"Non-science census rows:                         {len(non_science)}")\n    print(\n        f"Official-associated <=10 arcsec:                "\n        f"{c10.get(\'associated_count\')}/{EXPECTED_NONSCIENCE}"\n    )\n    print(\n        f"Detector +1 unassociated >10 arcsec queue:       "\n        f"{len(queue_rows)}"\n    )\n    print("Science nearest-distance interpretation:          SUPERSEDED in v028bf")\n    print("Frozen exact v028ao science distances retained:")\n    for rank in SCIENCE_RANKS:\n        print(\n            f"  #{rank:02d}: "\n            f"{FROZEN_V028AO_NEAREST_ARCSEC[rank]:.3f} arcsec"\n        )\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_QUEUE_CSV}")\n    print(f"  {OUT_QUEUE_JSON}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_census_freeze_morphology_queue_v028bg",
        title="Freeze v028bf interpretation and plan +1 unassociated morphology controls",
        script="automation/stages/freeze_census_and_plan_morphology_v028bg.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_platewide_official_association_census_v028bf.json",
            "results/order01_native_full_v028/order01_dasch_platewide_native_official_associations_v028bf.csv",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_platewide_census_interpretation_and_morphology_queue_v028bg.json",
            "automation/queues/ai43437_platewide_morphology_v028bg.json",
        ),
        dependencies=("dasch_platewide_official_association_v028bf",),
        notes="No network/pixels; supersedes incomplete v028bf science nearest-distance interpretation and creates 2596-item +1/>10arcsec morphology queue.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_census_freeze_morphology_queue_v028bg"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.2 — CENSUS FREEZE + MORPHOLOGY QUEUE")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ BY THE UPGRADE.")
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
        "Transient automation v0.1.2 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text(
        '__version__ = "0.1.2"\n',
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
        r'verify-stage --stage dasch_census_freeze_morphology_queue_v028bg'
    )
    print("\nNo network or pixel access is required by v028bg.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
