#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "recover_v028r_platephot_caller_v028ba.py"
BACKUP = AUTO / "backups" / "pre_v006"
STAGE_CONTENT = '#!/usr/bin/env python3\n"""\nORDER 01 — v028r platephot caller-contract recovery v028ba\n\nRecover the exact caller-level contract that invokes the generic request_json()\ntransport wrapper in:\n  tools/audit_order01_official_dasch_platephot_astrometry_v028r.py\n\nThis closes the gap left by v028az:\n- identify calls to request_json()\n- resolve literal/assigned method + path arguments\n- capture payload expression and its defining assignment(s)\n- capture enclosing function and call chain\n- specifically locate /dasch/dr7/platephot invocation\n- emit an executor-ready contract only if unambiguous\n\nNO NETWORK ACCESS.\nNO PIXELS READ.\nNO DETECTOR RERUN.\nNO CANDIDATE STATE MUTATION.\n"""\n\nfrom __future__ import annotations\n\nimport ast\nimport json\nfrom pathlib import Path\n\nROOT = Path.cwd()\nSRC = ROOT / "tools" / "audit_order01_official_dasch_platephot_astrometry_v028r.py"\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nOUT_JSON = BASE / "order01_dasch_v028r_platephot_caller_contract_v028ba.json"\nOUT_TXT = BASE / "ORDER01_DASCH_V028R_PLATEPHOT_CALLER_CONTRACT_V028BA.txt"\nOUT_MD = BASE / "ORDER01_DASCH_V028R_PLATEPHOT_CALLER_CONTRACT_V028BA.md"\n\n\ndef write_json(path, obj):\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(\n        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n    tmp.replace(path)\n\n\ndef parent_map(tree):\n    out = {}\n    for node in ast.walk(tree):\n        for child in ast.iter_child_nodes(node):\n            out[child] = node\n    return out\n\n\ndef enclosing_function(node, parents):\n    cur = node\n    while cur in parents:\n        cur = parents[cur]\n        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):\n            return cur\n    return None\n\n\ndef source(src, node):\n    return ast.get_source_segment(src, node) or ""\n\n\ndef fn_local_assignments(fn, src):\n    vals = {}\n    rows = []\n    for node in ast.walk(fn):\n        if isinstance(node, ast.Assign):\n            targets = node.targets\n            val = node.value\n        elif isinstance(node, ast.AnnAssign):\n            targets = [node.target]\n            val = node.value\n        else:\n            continue\n\n        for t in targets:\n            if isinstance(t, ast.Name):\n                expr = source(src, val)\n                vals.setdefault(t.id, []).append(expr)\n                rows.append({\n                    "name": t.id,\n                    "lineno": node.lineno,\n                    "expression": expr,\n                })\n    return vals, rows\n\n\ndef literal_or_expr(node, src, locals_map):\n    if node is None:\n        return None\n    if isinstance(node, ast.Constant):\n        return {\n            "kind": "literal",\n            "value": node.value,\n            "expression": repr(node.value),\n        }\n    if isinstance(node, ast.Name):\n        defs = locals_map.get(node.id, [])\n        return {\n            "kind": "name",\n            "name": node.id,\n            "definitions": defs,\n            "expression": node.id,\n        }\n    return {\n        "kind": "expression",\n        "expression": source(src, node),\n    }\n\n\ndef call_arg(call, pos, keyword):\n    if len(call.args) > pos:\n        return call.args[pos]\n    for kw in call.keywords:\n        if kw.arg == keyword:\n            return kw.value\n    return None\n\n\ndef resolve_string_hint(desc):\n    if not desc:\n        return None\n    if desc.get("kind") == "literal" and isinstance(desc.get("value"), str):\n        return desc["value"]\n    defs = desc.get("definitions") or []\n    if len(defs) == 1:\n        d = defs[0].strip()\n        if len(d) >= 2 and d[0] in ("\'", \'"\') and d[-1] == d[0]:\n            try:\n                return ast.literal_eval(d)\n            except Exception:\n                pass\n    return None\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — v028r PLATEPHOT CALLER-CONTRACT RECOVERY v028ba")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    if not SRC.is_file():\n        print(f"FAIL missing exact source: {SRC}")\n        return 2\n\n    src = SRC.read_text(encoding="utf-8", errors="strict")\n    tree = ast.parse(src)\n    parents = parent_map(tree)\n    lines = src.splitlines()\n\n    request_calls = []\n\n    for node in ast.walk(tree):\n        if not isinstance(node, ast.Call):\n            continue\n\n        func_text = source(src, node.func).strip()\n        if func_text not in ("request_json",):\n            continue\n\n        fn = enclosing_function(node, parents)\n        fn_name = None if fn is None else fn.name\n        locals_map, local_rows = ({}, []) if fn is None else fn_local_assignments(fn, src)\n\n        method_desc = literal_or_expr(call_arg(node, 0, "method"), src, locals_map)\n        path_desc = literal_or_expr(call_arg(node, 1, "path"), src, locals_map)\n        payload_desc = literal_or_expr(call_arg(node, 2, "payload"), src, locals_map)\n        cache_desc = literal_or_expr(call_arg(node, 3, "cache"), src, locals_map)\n\n        method_hint = resolve_string_hint(method_desc)\n        path_hint = resolve_string_hint(path_desc)\n\n        a = max(1, node.lineno - 15)\n        b = min(len(lines), getattr(node, "end_lineno", node.lineno) + 15)\n\n        request_calls.append({\n            "lineno": node.lineno,\n            "end_lineno": getattr(node, "end_lineno", node.lineno),\n            "enclosing_function": fn_name,\n            "enclosing_function_args":\n                [] if fn is None else [a.arg for a in fn.args.args],\n            "call_expression": source(src, node),\n            "method": method_desc,\n            "method_resolved": method_hint,\n            "path": path_desc,\n            "path_resolved": path_hint,\n            "payload": payload_desc,\n            "cache": cache_desc,\n            "local_assignments": local_rows,\n            "source_excerpt": "\\n".join(\n                f"{j:05d}: {lines[j-1]}"\n                for j in range(a, b + 1)\n            ),\n        })\n\n    platephot_calls = []\n\n    for rec in request_calls:\n        blob = json.dumps(rec).lower()\n        score = 0\n        if "/dasch/dr7/platephot" in blob:\n            score += 200\n        elif "platephot" in blob:\n            score += 100\n        if rec.get("method_resolved") == "POST":\n            score += 25\n        if "payload" in blob:\n            score += 10\n        if "refcat" in blob:\n            score += 10\n        if "solution" in blob:\n            score += 10\n        if "plate" in blob:\n            score += 10\n        rec["platephot_score"] = score\n        if score >= 100:\n            platephot_calls.append(rec)\n\n    platephot_calls.sort(key=lambda r: (-r["platephot_score"], r["lineno"]))\n\n    exact = False\n    selected = None\n    ambiguity_reason = None\n\n    if len(platephot_calls) == 1:\n        selected = platephot_calls[0]\n        exact = (\n            selected.get("path_resolved") == "/dasch/dr7/platephot"\n            and selected.get("method_resolved") == "POST"\n        )\n        if not exact:\n            ambiguity_reason = (\n                "Unique platephot caller found, but method/path did not both "\n                "resolve exactly to POST + /dasch/dr7/platephot."\n            )\n    elif len(platephot_calls) > 1:\n        exact_matches = [\n            r for r in platephot_calls\n            if r.get("path_resolved") == "/dasch/dr7/platephot"\n            and r.get("method_resolved") == "POST"\n        ]\n        if len(exact_matches) == 1:\n            selected = exact_matches[0]\n            exact = True\n        else:\n            ambiguity_reason = (\n                f"{len(platephot_calls)} platephot-like callers and "\n                f"{len(exact_matches)} exact POST/path matches."\n            )\n    else:\n        ambiguity_reason = "No request_json caller could be tied to platephot."\n\n    print(f"Exact source: {SRC.relative_to(ROOT)}")\n    print(f"request_json call sites: {len(request_calls)}")\n    print(f"platephot-like callers: {len(platephot_calls)}")\n    print(f"Exact POST /dasch/dr7/platephot caller recovered: {exact}")\n\n    if selected:\n        print("\\nSELECTED CALLER")\n        print(f"  line={selected[\'lineno\']}")\n        print(f"  function={selected[\'enclosing_function\']}")\n        print(f"  method={selected[\'method_resolved\']!r}")\n        print(f"  path={selected[\'path_resolved\']!r}")\n        print(f"  call={selected[\'call_expression\']}")\n\n        print("\\nPAYLOAD")\n        print(json.dumps(selected["payload"], indent=2))\n\n        defs = []\n        payload = selected.get("payload") or {}\n        if payload.get("kind") == "name":\n            pname = payload.get("name")\n            defs = [\n                x for x in selected["local_assignments"]\n                if x["name"] == pname\n            ]\n        if defs:\n            print("\\nPAYLOAD DEFINITIONS")\n            for d in defs:\n                print(f"  line {d[\'lineno\']}: {d[\'name\']} = {d[\'expression\']}")\n\n        print("\\nCALLER SOURCE")\n        print(selected["source_excerpt"])\n\n    if ambiguity_reason:\n        print("\\nAMBIGUITY")\n        print("  " + ambiguity_reason)\n\n    payload = {\n        "stage": "ORDER01_DASCH_V028R_PLATEPHOT_CALLER_CONTRACT_V028BA",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "source_file": str(SRC.relative_to(ROOT)),\n        "summary": {\n            "request_json_call_count": len(request_calls),\n            "platephot_like_caller_count": len(platephot_calls),\n            "exact_post_platephot_caller_recovered": exact,\n            "selected_line": None if selected is None else selected["lineno"],\n            "selected_function":\n                None if selected is None else selected["enclosing_function"],\n            "ambiguity_reason": ambiguity_reason,\n        },\n        "selected_contract": selected,\n        "platephot_callers": platephot_calls,\n        "all_request_json_calls": request_calls,\n        "executor_gate": {\n            "network_executor_may_be_built": exact,\n            "required_method": "POST",\n            "required_path": "/dasch/dr7/platephot",\n        },\n        "interpretive_boundary": (\n            "This stage recovers caller-level source provenance only. "\n            "No request has been sent. A network executor must not proceed "\n            "unless executor_gate.network_executor_may_be_built is true."\n        ),\n    }\n\n    write_json(OUT_JSON, payload)\n\n    txt = [\n        f"SOURCE: {SRC.relative_to(ROOT)}",\n        f"EXACT_POST_PLATEPHOT_CALLER_RECOVERED: {exact}",\n        f"AMBIGUITY: {ambiguity_reason}",\n        "",\n        "=== SELECTED CONTRACT ===",\n        json.dumps(selected, indent=2),\n        "",\n        "=== ALL PLATEPHOT-LIKE CALLERS ===",\n        json.dumps(platephot_calls, indent=2),\n        "",\n        "=== ALL REQUEST_JSON CALLERS ===",\n        json.dumps(request_calls, indent=2),\n    ]\n    OUT_TXT.write_text("\\n".join(txt), encoding="utf-8")\n\n    md = [\n        "# ORDER 01 — v028r Platephot Caller Contract v028ba",\n        "",\n        "## Guard state",\n        "",\n        "- No network access.",\n        "- No pixels were read.",\n        "- Frozen detector not rerun.",\n        "- No endpoint state change.",\n        "",\n        "## Result",\n        "",\n        f"- `request_json` call sites: **{len(request_calls)}**.",\n        f"- Platephot-like callers: **{len(platephot_calls)}**.",\n        f"- Exact POST `/dasch/dr7/platephot` caller recovered: **{exact}**.",\n        "",\n        "## Executor gate",\n        "",\n        f"- Network executor may be built automatically: **{exact}**.",\n        "",\n        payload["interpretive_boundary"],\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_TXT}")\n    print(f"  {OUT_MD}")\n    print()\n    print("NO network query was made.")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE NOT READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_platephot_caller_contract_v028ba",
        title="Recover exact v028r platephot caller-level contract",
        script="automation/stages/recover_v028r_platephot_caller_v028ba.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_exact_v028r_executor_contract_v028az.json",
            "tools/audit_order01_official_dasch_platephot_astrometry_v028r.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_v028r_platephot_caller_contract_v028ba.json",
        ),
        dependencies=("dasch_exact_executor_contract_v028az",),
        notes="Resolves the exact POST /dasch/dr7/platephot caller before any network executor is allowed.",
    ),
"""

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.0.6 — PLATEPHOT CALLER CONTRACT")
    print("="*112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("No science/result artifact is modified.")
    print("No candidate state is changed.\n")

    for p in (REGISTRY, RUNNER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, AUTO/"__init__.py"):
        if p.is_file():
            dst = BACKUP / p.name
            if not dst.exists():
                shutil.copy2(p, dst)

    if STAGE.exists():
        print(f"FAIL stage already exists: {STAGE}")
        return 2

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_CONTENT, encoding="utf-8")
    print(f"Created: {STAGE.relative_to(ROOT)}")

    reg = REGISTRY.read_text(encoding="utf-8")
    if 'stage_id="dasch_platephot_caller_contract_v028ba"' in reg:
        print("FAIL registry already contains v028ba")
        return 2

    marker = "\n]\n\ndef by_id():"
    if marker not in reg:
        print("FAIL registry insertion marker not found.")
        return 3

    reg = reg.replace(
        marker,
        "\n" + REGISTRY_ENTRY.rstrip() + "\n]\n\ndef by_id():",
        1,
    )
    REGISTRY.write_text(reg, encoding="utf-8")
    print("Registered: dasch_platephot_caller_contract_v028ba")

    runner = RUNNER.read_text(encoding="utf-8")
    runner = runner.replace(
        'print("Transient automation v0.0.5 - Order01 registry status\\n")',
        'print("Transient automation v0.0.6 - Order01 registry status\\n")',
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO/"__init__.py").write_text('__version__ = "0.0.6"\n', encoding="utf-8")

    failures=[]
    py_files=sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
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
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_platephot_caller_contract_v028ba')
    print("\nNo network request will be made by v028ba.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
