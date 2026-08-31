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
STAGE = AUTO / "stages" / "extract_morphology_executor_contract_v028bh.py"
BACKUP = AUTO / "backups" / "pre_v013"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport ast\nimport hashlib\nimport json\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nAR = ROOT / "tools" / "audit_order01_dasch_physical_morphology_v028ar_r1.py"\nAS = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\n\nOUT_JSON = BASE / "order01_dasch_morphology_executor_contract_v028bh.json"\nOUT_MD = BASE / "ORDER01_DASCH_MORPHOLOGY_EXECUTOR_CONTRACT_V028BH.md"\n\nTARGET_STRINGS = (\n    "RAW_FEATURE_STAR_DIRECTION_AND_LOCALLY_CONCENTRATED",\n    "CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD",\n    "shape",\n    "moment",\n    "centroid",\n    "ap5",\n    "offset",\n    "tile",\n    "np.load",\n    "numpy.load",\n    "gaussian_filter",\n    "median",\n    "percentile",\n    "nearest",\n)\n\n\ndef sha256(path):\n    h = hashlib.sha256()\n    with path.open("rb") as fh:\n        for chunk in iter(lambda: fh.read(1024 * 1024), b""):\n            h.update(chunk)\n    return h.hexdigest()\n\n\ndef signature(node):\n    args = [a.arg for a in node.args.args]\n    defaults = len(node.args.defaults)\n    if defaults:\n        split = len(args) - defaults\n        parts = args[:split] + [a + "=..." for a in args[split:]]\n    else:\n        parts = args\n    if node.args.vararg:\n        parts.append("*" + node.args.vararg.arg)\n    if node.args.kwarg:\n        parts.append("**" + node.args.kwarg.arg)\n    return f"{node.name}({\', \'.join(parts)})"\n\n\ndef source_segment(lines, start, end, pad=0):\n    s = max(1, start - pad)\n    e = min(len(lines), end + pad)\n    return {\n        "start_line": s,\n        "end_line": e,\n        "text": "".join(lines[s-1:e]),\n    }\n\n\ndef analyse(path):\n    text = path.read_text(encoding="utf-8")\n    lines = text.splitlines(keepends=True)\n    tree = ast.parse(text)\n\n    funcs = []\n    assignments = []\n    imports = []\n    string_hits = []\n    call_hits = []\n\n    for node in tree.body:\n        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):\n            funcs.append({\n                "name": node.name,\n                "signature": signature(node),\n                "start_line": node.lineno,\n                "end_line": node.end_lineno,\n                "source": source_segment(lines, node.lineno, node.end_lineno),\n            })\n        elif isinstance(node, (ast.Assign, ast.AnnAssign)):\n            try:\n                seg = ast.get_source_segment(text, node)\n            except Exception:\n                seg = None\n            assignments.append({\n                "start_line": node.lineno,\n                "end_line": node.end_lineno,\n                "source": seg,\n            })\n        elif isinstance(node, (ast.Import, ast.ImportFrom)):\n            imports.append(ast.get_source_segment(text, node))\n\n    for node in ast.walk(tree):\n        if isinstance(node, ast.Constant) and isinstance(node.value, str):\n            val = node.value\n            for token in TARGET_STRINGS:\n                if token.lower() in val.lower():\n                    string_hits.append({\n                        "token": token,\n                        "value": val,\n                        "line": node.lineno,\n                        "context": source_segment(lines, node.lineno, node.lineno, pad=4),\n                    })\n\n        if isinstance(node, ast.Call):\n            name = None\n            if isinstance(node.func, ast.Name):\n                name = node.func.id\n            elif isinstance(node.func, ast.Attribute):\n                parts = []\n                cur = node.func\n                while isinstance(cur, ast.Attribute):\n                    parts.append(cur.attr)\n                    cur = cur.value\n                if isinstance(cur, ast.Name):\n                    parts.append(cur.id)\n                name = ".".join(reversed(parts))\n            if name and any(t.lower() in name.lower() for t in TARGET_STRINGS):\n                call_hits.append({\n                    "call": name,\n                    "line": node.lineno,\n                    "context": source_segment(lines, node.lineno, node.end_lineno, pad=4),\n                })\n\n    # Function relevance score based on science/morphology vocabulary in source.\n    scored = []\n    keywords = (\n        "pixel", "tile", "offset", "centroid", "moment", "ap5",\n        "shape", "stamp", "cutout", "transform", "local_", "global_",\n        "official", "nearest", "normalize", "profile",\n    )\n    for f in funcs:\n        src = f["source"]["text"].lower()\n        score = sum(src.count(k) for k in keywords)\n        x = dict(f)\n        x["relevance_score"] = score\n        scored.append(x)\n\n    scored.sort(key=lambda x: (-x["relevance_score"], x["start_line"]))\n\n    return {\n        "path": str(path.relative_to(ROOT)),\n        "sha256": sha256(path),\n        "line_count": len(lines),\n        "imports": imports,\n        "top_level_assignments": assignments,\n        "functions": funcs,\n        "functions_ranked_for_reuse": scored,\n        "string_hits": string_hits,\n        "call_hits": call_hits,\n    }\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — MORPHOLOGY EXECUTOR CONTRACT EXTRACTION v028bh")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (AR, AS):\n        if not p.is_file():\n            print(f"FAIL missing validated source: {p}")\n            return 2\n\n    ar = analyse(AR)\n    ash = analyse(AS)\n\n    print(f"v028ar_r1 source: {ar[\'path\']}")\n    print(f"  sha256: {ar[\'sha256\']}")\n    print(f"  functions: {len(ar[\'functions\'])}")\n    print("  highest-relevance functions:")\n    for f in ar["functions_ranked_for_reuse"][:12]:\n        print(\n            f"    score={f[\'relevance_score\']:3d} "\n            f"lines={f[\'start_line\']:04d}-{f[\'end_line\']:04d} "\n            f"{f[\'signature\']}"\n        )\n\n    print(f"\\nv028as source: {ash[\'path\']}")\n    print(f"  sha256: {ash[\'sha256\']}")\n    print(f"  functions: {len(ash[\'functions\'])}")\n    print("  highest-relevance functions:")\n    for f in ash["functions_ranked_for_reuse"][:12]:\n        print(\n            f"    score={f[\'relevance_score\']:3d} "\n            f"lines={f[\'start_line\']:04d}-{f[\'end_line\']:04d} "\n            f"{f[\'signature\']}"\n        )\n\n    payload = {\n        "stage": "ORDER01_DASCH_MORPHOLOGY_EXECUTOR_CONTRACT_V028BH",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "sources": {\n            "v028ar_r1": ar,\n            "v028as": ash,\n        },\n        "executor_requirement": {\n            "must_reuse_exact_validated_source_hashes": True,\n            "must_not_rerun_transient_detector": True,\n            "next_population":\n                "NONSCIENCE_DETECTOR_PLUS1_UNASSOCIATED_GT10ARCSEC",\n            "next_population_count": 2596,\n            "checkpointed_pixel_execution_required": True,\n            "science_pixels_should_not_be_reread": True,\n        },\n        "interpretive_boundary": (\n            "This stage only freezes the implementation contract of the "\n            "previously validated v028ar_r1 physical-morphology and v028as "\n            "stellar-shape analyses. It performs no morphology measurement."\n        ),\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True) + "\\n",\n        encoding="utf-8",\n    )\n\n    md = [\n        "# ORDER 01 — Morphology Executor Contract v028bh",\n        "",\n        f"- v028ar_r1 SHA256: `{ar[\'sha256\']}`",\n        f"- v028as SHA256: `{ash[\'sha256\']}`",\n        "",\n        "## v028ar_r1 highest-relevance functions",\n        "",\n    ]\n    for x in ar["functions_ranked_for_reuse"][:20]:\n        md.append(\n            f"- score {x[\'relevance_score\']}: "\n            f"`{x[\'signature\']}` lines {x[\'start_line\']}-{x[\'end_line\']}"\n        )\n    md += ["", "## v028as highest-relevance functions", ""]\n    for x in ash["functions_ranked_for_reuse"][:20]:\n        md.append(\n            f"- score {x[\'relevance_score\']}: "\n            f"`{x[\'signature\']}` lines {x[\'start_line\']}-{x[\'end_line\']}"\n        )\n    md += [\n        "",\n        "No network or pixel access occurred.",\n        "This contract is intended to drive the checkpointed 2,596-control "\n        "morphology executor without changing the frozen methodology.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_morphology_executor_contract_v028bh",
        title="Freeze validated DASCH morphology executor contract",
        script="automation/stages/extract_morphology_executor_contract_v028bh.py",
        requires=(
            "tools/audit_order01_dasch_physical_morphology_v028ar_r1.py",
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
            "automation/queues/ai43437_platewide_morphology_v028bg.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_morphology_executor_contract_v028bh.json",
        ),
        dependencies=("dasch_census_freeze_morphology_queue_v028bg",),
        notes="No network/pixels; AST/source contract for exact v028ar_r1/v028as reuse before 2596-control pixel execution.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_morphology_executor_contract_v028bh"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.3 — MORPHOLOGY EXECUTOR CONTRACT")
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
        "Transient automation v0.1.3 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text(
        '__version__ = "0.1.3"\n',
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
        r'verify-stage --stage dasch_morphology_executor_contract_v028bh'
    )
    print("\nNo network or pixel access is required by v028bh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
