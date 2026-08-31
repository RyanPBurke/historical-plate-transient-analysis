#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "extract_exact_v028r_executor_v028az.py"
BACKUP = AUTO / "backups" / "pre_v005"
STAGE_CONTENT = '#!/usr/bin/env python3\n"""\nORDER 01 — exact v028r platephot executor extraction v028az\n\nThis stage inspects ONLY the exact already-validated local source:\n    tools/audit_order01_official_dasch_platephot_astrometry_v028r.py\n\nIt prints and records the minimal request implementation needed to construct\nthe queued executor:\n- URL/base URL literals and assignments\n- HTTP request call expressions\n- enclosing function source/signature\n- payload/params/json/data assignments in that function\n- timeout/retry/session/sleep/header hints\n- cache-writing expressions\n\nNO NETWORK ACCESS.\nNO PIXELS READ.\nNO DETECTOR RERUN.\nNO CANDIDATE STATE MUTATION.\n"""\n\nfrom __future__ import annotations\n\nimport ast\nimport json\nimport re\nfrom pathlib import Path\n\nROOT = Path.cwd()\nSRC = ROOT / "tools" / "audit_order01_official_dasch_platephot_astrometry_v028r.py"\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nOUT_JSON = BASE / "order01_dasch_exact_v028r_executor_contract_v028az.json"\nOUT_TXT = BASE / "ORDER01_DASCH_EXACT_V028R_EXECUTOR_CONTRACT_V028AZ.txt"\nOUT_MD = BASE / "ORDER01_DASCH_EXACT_V028R_EXECUTOR_CONTRACT_V028AZ.md"\n\nHTTP_NAMES = ("requests", "httpx", "urlopen", "session")\nPAYLOAD_NAMES = (\n    "payload", "params", "query", "body", "json", "data",\n    "headers", "timeout", "url", "endpoint", "base_url",\n)\nCACHE_HINTS = ("write_text", "json.dump", "open(", "cache", "mkdir", "replace")\n\n\ndef write_json(path, obj):\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n",\n                   encoding="utf-8")\n    tmp.replace(path)\n\n\ndef contains_http(call_text):\n    low = call_text.lower()\n    return any(x in low for x in (\n        "requests.get", "requests.post",\n        "session.get", "session.post",\n        "httpx.get", "httpx.post",\n        "urlopen",\n    ))\n\n\ndef parent_map(tree):\n    out = {}\n    for node in ast.walk(tree):\n        for child in ast.iter_child_nodes(node):\n            out[child] = node\n    return out\n\n\ndef enclosing_function(node, parents):\n    cur = node\n    while cur in parents:\n        cur = parents[cur]\n        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):\n            return cur\n    return None\n\n\ndef assignment_records(tree, src):\n    records = []\n    for node in ast.walk(tree):\n        if not isinstance(node, (ast.Assign, ast.AnnAssign)):\n            continue\n\n        targets = node.targets if isinstance(node, ast.Assign) else [node.target]\n        value = node.value\n\n        for target in targets:\n            if isinstance(target, ast.Name):\n                name = target.id\n                expr = ast.get_source_segment(src, value) or ""\n                low = (name + " " + expr).lower()\n                if (\n                    any(k in low for k in PAYLOAD_NAMES)\n                    or "platephot" in low\n                    or "dasch" in low\n                    or "api." in low\n                ):\n                    records.append({\n                        "name": name,\n                        "lineno": node.lineno,\n                        "end_lineno": getattr(node, "end_lineno", node.lineno),\n                        "expression": expr,\n                    })\n    return records\n\n\ndef function_assignments(fn, src):\n    records = []\n    for node in ast.walk(fn):\n        if not isinstance(node, (ast.Assign, ast.AnnAssign)):\n            continue\n\n        targets = node.targets if isinstance(node, ast.Assign) else [node.target]\n        value = node.value\n\n        for target in targets:\n            if isinstance(target, ast.Name):\n                name = target.id\n                expr = ast.get_source_segment(src, value) or ""\n                low = name.lower()\n                if (\n                    low in PAYLOAD_NAMES\n                    or any(k in low for k in PAYLOAD_NAMES)\n                    or isinstance(value, ast.Dict)\n                ):\n                    records.append({\n                        "name": name,\n                        "lineno": node.lineno,\n                        "expression": expr,\n                    })\n    return records\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — EXACT v028r PLATEPHOT EXECUTOR EXTRACTION v028az")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    if not SRC.is_file():\n        print(f"FAIL exact validated v028r source missing: {SRC}")\n        return 2\n\n    src = SRC.read_text(encoding="utf-8", errors="strict")\n    tree = ast.parse(src)\n    parents = parent_map(tree)\n    lines = src.splitlines()\n\n    url_literals = sorted(set(\n        re.findall(r\'https?://[^\\s\\\'"]+\', src)\n    ))\n\n    global_assignments = assignment_records(tree, src)\n\n    calls = []\n    functions = {}\n\n    for node in ast.walk(tree):\n        if not isinstance(node, ast.Call):\n            continue\n\n        call_text = ast.get_source_segment(src, node) or ""\n        if not contains_http(call_text):\n            continue\n\n        fn = enclosing_function(node, parents)\n        fn_name = None if fn is None else fn.name\n\n        rec = {\n            "lineno": node.lineno,\n            "end_lineno": getattr(node, "end_lineno", node.lineno),\n            "call": call_text,\n            "enclosing_function": fn_name,\n        }\n        calls.append(rec)\n\n        if fn is not None and fn_name not in functions:\n            functions[fn_name] = {\n                "name": fn_name,\n                "lineno": fn.lineno,\n                "end_lineno": getattr(fn, "end_lineno", fn.lineno),\n                "args": [a.arg for a in fn.args.args],\n                "source": ast.get_source_segment(src, fn) or "",\n                "assignments": function_assignments(fn, src),\n            }\n\n    # Rank request calls by platephot relevance.\n    for c in calls:\n        blob = c["call"].lower()\n        fn_blob = ""\n        if c["enclosing_function"] in functions:\n            fn_blob = functions[c["enclosing_function"]]["source"].lower()\n\n        score = 0\n        if "platephot" in blob:\n            score += 100\n        if "platephot" in fn_blob:\n            score += 50\n        if "post" in blob:\n            score += 20\n        if "json=" in blob:\n            score += 15\n        if "params=" in blob:\n            score += 15\n        if "timeout" in blob:\n            score += 5\n        c["request_score"] = score\n\n    calls.sort(key=lambda x: (-x["request_score"], x["lineno"]))\n\n    relevant_calls = [c for c in calls if c["request_score"] > 0]\n    best_call = relevant_calls[0] if relevant_calls else None\n    best_fn = None\n    if best_call and best_call["enclosing_function"]:\n        best_fn = functions.get(best_call["enclosing_function"])\n\n    # Extract direct surrounding source for each relevant call.\n    excerpts = []\n    for c in relevant_calls:\n        a = max(1, c["lineno"] - 12)\n        b = min(len(lines), c["end_lineno"] + 12)\n        excerpts.append({\n            "lineno": c["lineno"],\n            "start_line": a,\n            "end_line": b,\n            "text": "\\n".join(\n                f"{j:05d}: {lines[j-1]}"\n                for j in range(a, b + 1)\n            ),\n        })\n\n    # General retry/cache hints.\n    hints = []\n    for idx, line in enumerate(lines, start=1):\n        low = line.lower()\n        if any(x in low for x in (\n            "retry", "retries", "sleep(", "timeout",\n            "status_code", "raise_for_status", "backoff",\n            "user-agent", "headers", "cache",\n            "write_text", "json.dump",\n        )):\n            hints.append({\n                "lineno": idx,\n                "text": line.rstrip(),\n            })\n\n    exact_recovered = bool(\n        best_call\n        and best_fn\n        and (\n            "platephot" in best_call["call"].lower()\n            or "platephot" in best_fn["source"].lower()\n        )\n    )\n\n    print(f"Exact source: {SRC.relative_to(ROOT)}")\n    print(f"HTTP call sites: {len(calls)}")\n    print(f"Platephot-relevant HTTP calls: {len(relevant_calls)}")\n    print(f"URL literals: {len(url_literals)}")\n    print(f"Exact enclosing request function recovered: {exact_recovered}")\n\n    if best_call:\n        print("\\nBEST REQUEST CALL")\n        print(f"  line={best_call[\'lineno\']}")\n        print(f"  function={best_call[\'enclosing_function\']}")\n        print(f"  score={best_call[\'request_score\']}")\n        print("  call:")\n        print(best_call["call"])\n\n    if best_fn:\n        print("\\nENCLOSING FUNCTION SIGNATURE")\n        print(f"  {best_fn[\'name\']}({\', \'.join(best_fn[\'args\'])})")\n        print("\\nPAYLOAD/PARAMETER ASSIGNMENTS IN FUNCTION")\n        for a in best_fn["assignments"]:\n            print(f"  line {a[\'lineno\']}: {a[\'name\']} = {a[\'expression\']}")\n\n    if url_literals:\n        print("\\nURL LITERALS")\n        for u in url_literals:\n            print(f"  {u}")\n\n    payload = {\n        "stage": "ORDER01_DASCH_EXACT_V028R_EXECUTOR_CONTRACT_V028AZ",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "source_file": str(SRC.relative_to(ROOT)),\n        "summary": {\n            "http_call_count": len(calls),\n            "platephot_relevant_http_call_count": len(relevant_calls),\n            "url_literal_count": len(url_literals),\n            "exact_enclosing_request_function_recovered": exact_recovered,\n            "best_request_function":\n                None if best_fn is None else best_fn["name"],\n            "best_request_line":\n                None if best_call is None else best_call["lineno"],\n        },\n        "url_literals": url_literals,\n        "global_request_related_assignments": global_assignments,\n        "http_calls": calls,\n        "functions": functions,\n        "best_request_call": best_call,\n        "best_request_function": best_fn,\n        "request_excerpts": excerpts,\n        "retry_cache_header_hints": hints,\n        "interpretive_boundary": (\n            "v028az extracts the exact validated v028r request implementation "\n            "from local source. It performs no network operation. A queued "\n            "executor must stop rather than guess if this artifact does not "\n            "unambiguously expose the endpoint/method/payload contract."\n        ),\n    }\n    write_json(OUT_JSON, payload)\n\n    txt = [\n        f"SOURCE: {SRC.relative_to(ROOT)}",\n        f"EXACT_RECOVERED: {exact_recovered}",\n        "",\n        "=== URL LITERALS ===",\n        *url_literals,\n        "",\n        "=== GLOBAL REQUEST-RELATED ASSIGNMENTS ===",\n        json.dumps(global_assignments, indent=2),\n        "",\n        "=== HTTP CALLS ===",\n        json.dumps(calls, indent=2),\n        "",\n        "=== BEST REQUEST FUNCTION ===",\n        "" if best_fn is None else best_fn["source"],\n        "",\n        "=== REQUEST EXCERPTS ===",\n    ]\n    for ex in excerpts:\n        txt.append(\n            f"\\n--- lines {ex[\'start_line\']}-{ex[\'end_line\']} ---\\n"\n            + ex["text"]\n        )\n    txt.extend([\n        "",\n        "=== RETRY/CACHE/HEADER HINTS ===",\n        json.dumps(hints, indent=2),\n    ])\n    OUT_TXT.write_text("\\n".join(txt), encoding="utf-8")\n\n    md = [\n        "# ORDER 01 — Exact v028r Platephot Executor Contract v028az",\n        "",\n        "## Guard state",\n        "",\n        "- No network access.",\n        "- No pixels were read.",\n        "- The frozen detector was not rerun.",\n        "- No endpoint state was changed.",\n        "",\n        "## Extraction",\n        "",\n        f"- Exact source: `{SRC.relative_to(ROOT)}`.",\n        f"- HTTP calls: **{len(calls)}**.",\n        f"- Platephot-relevant HTTP calls: **{len(relevant_calls)}**.",\n        f"- Exact enclosing request function recovered: **{exact_recovered}**.",\n        f"- Best request function: **{None if best_fn is None else best_fn[\'name\']}**.",\n        "",\n        "## Boundary",\n        "",\n        payload["interpretive_boundary"],\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_TXT}")\n    print(f"  {OUT_MD}")\n    print()\n    print("NO network query was made.")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE NOT READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n    return 0\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_exact_executor_contract_v028az",
        title="Extract exact v028r platephot executor contract",
        script="automation/stages/extract_exact_v028r_executor_v028az.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_v028r_request_contract_v028ay.json",
            "automation/queues/ai43437_prevalence_v028ax.json",
            "tools/audit_order01_official_dasch_platephot_astrometry_v028r.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_exact_v028r_executor_contract_v028az.json",
        ),
        dependencies=("dasch_request_contract_v028ay",),
        notes="No-network exact-source extraction before queued DR7 execution.",
    ),
"""

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.0.5 — EXACT EXECUTOR CONTRACT")
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
    if 'stage_id="dasch_exact_executor_contract_v028az"' in reg:
        print("FAIL registry already contains v028az")
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
    print("Registered: dasch_exact_executor_contract_v028az")

    runner = RUNNER.read_text(encoding="utf-8")
    runner = runner.replace(
        'print("Transient automation v0.0.4 - Order01 registry status\\n")',
        'print("Transient automation v0.0.5 - Order01 registry status\\n")',
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO/"__init__.py").write_text('__version__ = "0.0.5"\n', encoding="utf-8")

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
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_exact_executor_contract_v028az')
    print("\nNo network request will be made by v028az.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
