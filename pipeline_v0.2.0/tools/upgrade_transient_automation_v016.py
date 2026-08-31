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
STAGE = AUTO / "stages" / "extract_stellar_shape_classifier_contract_v028bk.py"
BACKUP = AUTO / "backups" / "pre_v016"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport ast\nimport hashlib\nimport json\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAS = ROOT / "tools" / "audit_order01_dasch_stellar_shape_v028as.py"\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\n\nOUT_JSON = BASE / "order01_dasch_stellar_shape_classifier_contract_v028bk.json"\nOUT_MD = BASE / "ORDER01_DASCH_STELLAR_SHAPE_CLASSIFIER_CONTRACT_V028BK.md"\n\nEXPECTED_AS_SHA = "95084cb6e64934ec18686b30021c69b07605a938c5ec9169aadf26629877188f"\n\nTOKENS = (\n    "CONSISTENT",\n    "INCONSISTENT",\n    "shape",\n    "nearest",\n    "distance",\n    "loo",\n    "leave",\n    "control",\n    "ap5",\n    "amplitude",\n    "percentile",\n    "robust_center_scale",\n    "derived",\n    "p90",\n    "p95",\n    "max",\n)\n\n\ndef sha256(path):\n    h = hashlib.sha256()\n    with path.open("rb") as fh:\n        for chunk in iter(lambda: fh.read(1024 * 1024), b""):\n            h.update(chunk)\n    return h.hexdigest()\n\n\ndef segment(lines, start, end, pad=3):\n    s = max(1, start-pad)\n    e = min(len(lines), end+pad)\n    return {\n        "start_line": s,\n        "end_line": e,\n        "text": "".join(lines[s-1:e]),\n    }\n\n\ndef interesting_assignments(tree, text, lines):\n    out = []\n    for node in ast.walk(tree):\n        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):\n            src = ast.get_source_segment(text, node) or ""\n            low = src.lower()\n            if any(tok.lower() in low for tok in TOKENS):\n                out.append({\n                    "line": node.lineno,\n                    "end_line": node.end_lineno,\n                    "source": src,\n                    "context": segment(lines, node.lineno, node.end_lineno, 3),\n                })\n    return sorted(out, key=lambda x: x["line"])\n\n\ndef interesting_ifs(tree, text, lines):\n    out = []\n    for node in ast.walk(tree):\n        if isinstance(node, ast.If):\n            test = ast.get_source_segment(text, node.test) or ""\n            body = ast.get_source_segment(text, node) or ""\n            low = (test + "\\n" + body).lower()\n            if any(tok.lower() in low for tok in TOKENS):\n                out.append({\n                    "line": node.lineno,\n                    "end_line": node.end_lineno,\n                    "test": test,\n                    "context": segment(lines, node.lineno, node.end_lineno, 4),\n                })\n    return sorted(out, key=lambda x: x["line"])\n\n\ndef interesting_calls(tree, text, lines):\n    out = []\n    for node in ast.walk(tree):\n        if not isinstance(node, ast.Call):\n            continue\n        src = ast.get_source_segment(text, node) or ""\n        low = src.lower()\n        if any(tok.lower() in low for tok in TOKENS):\n            out.append({\n                "line": node.lineno,\n                "end_line": node.end_lineno,\n                "call": src,\n                "context": segment(lines, node.lineno, node.end_lineno, 3),\n            })\n    return sorted(out, key=lambda x: x["line"])\n\n\ndef summarize_json(obj, prefix="$", depth=0, max_depth=7):\n    rows = []\n    if depth > max_depth:\n        return rows\n\n    if isinstance(obj, dict):\n        keys = list(obj.keys())\n        rows.append({\n            "path": prefix,\n            "type": "dict",\n            "size": len(obj),\n            "keys": keys[:80],\n        })\n        for k, v in obj.items():\n            lk = str(k).lower()\n            if (\n                depth <= 2\n                or any(tok.lower() in lk for tok in TOKENS)\n                or isinstance(v, (list, dict))\n            ):\n                rows.extend(summarize_json(v, f"{prefix}.{k}", depth+1, max_depth))\n\n    elif isinstance(obj, list):\n        rows.append({\n            "path": prefix,\n            "type": "list",\n            "size": len(obj),\n            "sample_types": sorted({type(x).__name__ for x in obj[:20]}),\n        })\n        if obj:\n            # Recurse into first representative dict/list, plus a second when schemas differ.\n            reps = []\n            for x in obj[:10]:\n                if isinstance(x, (dict, list)):\n                    sig = tuple(sorted(x.keys())) if isinstance(x, dict) else ("LIST",)\n                    if sig not in [r[0] for r in reps]:\n                        reps.append((sig, x))\n                if len(reps) >= 2:\n                    break\n            for idx, (_, x) in enumerate(reps):\n                rows.extend(summarize_json(x, f"{prefix}[sample{idx}]", depth+1, max_depth))\n    else:\n        val = repr(obj)\n        low = val.lower()\n        if any(tok.lower() in low for tok in TOKENS):\n            rows.append({\n                "path": prefix,\n                "type": type(obj).__name__,\n                "value": obj,\n            })\n    return rows\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — EXACT v028as STELLAR-SHAPE CLASSIFIER CONTRACT v028bk")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (AS, BJ):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    actual_sha = sha256(AS)\n    if actual_sha != EXPECTED_AS_SHA:\n        print(f"FAIL v028as hash changed: {actual_sha}")\n        return 3\n\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    summ = bj.get("summary", {})\n    if not summ.get("complete"):\n        print("FAIL v028bj is not complete")\n        return 3\n    if int(summ.get("usable_metric_rows", -1)) != 2587:\n        print(f"FAIL expected 2587 usable v028bj rows; got {summ.get(\'usable_metric_rows\')}")\n        return 3\n\n    text = AS.read_text(encoding="utf-8")\n    lines = text.splitlines(keepends=True)\n    tree = ast.parse(text)\n\n    assigns = interesting_assignments(tree, text, lines)\n    ifs = interesting_ifs(tree, text, lines)\n    calls = interesting_calls(tree, text, lines)\n\n    # Discover saved v028as artifacts without assuming a filename.\n    artifacts = []\n    for p in sorted(BASE.glob("*v028as*")):\n        if not p.is_file():\n            continue\n        rec = {\n            "path": str(p.relative_to(ROOT)),\n            "suffix": p.suffix.lower(),\n            "size_bytes": p.stat().st_size,\n        }\n        if p.suffix.lower() == ".json":\n            try:\n                obj = json.loads(p.read_text(encoding="utf-8"))\n                rec["json_summary"] = summarize_json(obj)\n                rec["top_level_keys"] = list(obj.keys()) if isinstance(obj, dict) else None\n            except Exception as exc:\n                rec["json_error"] = f"{type(exc).__name__}: {exc}"\n        artifacts.append(rec)\n\n    print(f"v028as SHA256: {actual_sha}")\n    print(f"v028bj usable metric rows: {summ.get(\'usable_metric_rows\')}")\n    print(f"Relevant assignments: {len(assigns)}")\n    print(f"Relevant conditional blocks: {len(ifs)}")\n    print(f"Relevant calls: {len(calls)}")\n    print(f"Existing v028as artifacts discovered: {len(artifacts)}")\n\n    print("\\nCLASSIFIER-RELEVANT ASSIGNMENTS")\n    for x in assigns:\n        print(f"\\n--- lines {x[\'line\']}-{x[\'end_line\']} ---")\n        print(x["source"])\n\n    print("\\nCLASSIFIER-RELEVANT CONDITIONALS")\n    for x in ifs:\n        print(f"\\n--- lines {x[\'line\']}-{x[\'end_line\']} ---")\n        print(x["context"]["text"].rstrip())\n\n    print("\\nCLASSIFIER-RELEVANT CALLS")\n    # Deduplicate identical call+line combinations and cap console noise.\n    seen = set()\n    shown = 0\n    for x in calls:\n        key = (x["line"], x["call"])\n        if key in seen:\n            continue\n        seen.add(key)\n        print(f"  line {x[\'line\']}: {x[\'call\']}")\n        shown += 1\n        if shown >= 80:\n            print("  ... console call list capped at 80; full contract preserved in JSON")\n            break\n\n    print("\\nV028AS ARTIFACTS")\n    for a in artifacts:\n        print(f"  {a[\'path\']} ({a[\'size_bytes\']} bytes)")\n        if a.get("top_level_keys"):\n            print(f"    top-level keys: {a[\'top_level_keys\']}")\n\n    payload = {\n        "stage": "ORDER01_DASCH_STELLAR_SHAPE_CLASSIFIER_CONTRACT_V028BK",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "source": {\n            "path": str(AS.relative_to(ROOT)),\n            "sha256": actual_sha,\n        },\n        "v028bj_usable_metric_rows": 2587,\n        "relevant_assignments": assigns,\n        "relevant_conditionals": ifs,\n        "relevant_calls": calls,\n        "v028as_artifacts": artifacts,\n        "next_gate": {\n            "platewide_stellar_shape_prevalence_classifier_may_be_built": True,\n        },\n        "interpretive_boundary": (\n            "This stage extracts the exact validated v028as classification logic "\n            "and discovers its retained result artifacts. It performs no new "\n            "morphology classification and reads no pixels."\n        ),\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    OUT_MD.write_text(\n        "# ORDER 01 — Exact v028as Stellar-Shape Classifier Contract v028bk\\n\\n"\n        f"- v028as SHA256: `{actual_sha}`\\n"\n        f"- v028bj usable control rows ready: **2587**.\\n"\n        f"- Relevant assignments captured: **{len(assigns)}**.\\n"\n        f"- Relevant conditionals captured: **{len(ifs)}**.\\n"\n        f"- Existing v028as artifacts discovered: **{len(artifacts)}**.\\n\\n"\n        "No network or pixel access occurred.\\n",\n        encoding="utf-8",\n    )\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_stellar_shape_classifier_contract_v028bk",
        title="Extract exact validated v028as stellar-shape classification contract",
        script="automation/stages/extract_stellar_shape_classifier_contract_v028bk.py",
        requires=(
            "tools/audit_order01_dasch_stellar_shape_v028as.py",
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_stellar_shape_classifier_contract_v028bk.json",
        ),
        dependencies=("dasch_platewide_morphology_metrics_v028bj",),
        notes="No network/pixels; exact v028as decision-rule and retained-artifact extraction before plate-wide prevalence classification.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_stellar_shape_classifier_contract_v028bk"' in text:
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
    print("TRANSIENT AUTOMATION UPGRADE v0.1.6 — STELLAR-SHAPE CLASSIFIER CONTRACT")
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
        "Transient automation v0.1.6 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.1.6"\n', encoding="utf-8")

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
        r'verify-stage --stage dasch_stellar_shape_classifier_contract_v028bk'
    )
    print("\nNo network or pixel access is required by v028bk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
