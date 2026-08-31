#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "certify_v028r_executor_contract_v028bb.py"
BACKUP = AUTO / "backups" / "pre_v007"
STAGE_CONTENT = '#!/usr/bin/env python3\n"""\nORDER 01 — normalize and certify exact v028r platephot executor contract v028bb\n\nRepairs two extraction semantics from v028ba:\n1. path equivalence: "dasch/dr7/platephot" == "/dasch/dr7/platephot"\n   because request_json() constructs URL with path.lstrip("/");\n2. when the same local variable name is assigned multiple times, the payload\n   feeding a call is the nearest preceding assignment in the same function.\n\nThis stage re-reads the exact local v028r source and emits a certified\nexecutor-ready contract.\n\nNO NETWORK ACCESS.\nNO PIXELS READ.\nNO DETECTOR RERUN.\nNO CANDIDATE STATE MUTATION.\n"""\n\nfrom __future__ import annotations\n\nimport ast\nimport json\nimport re\nfrom pathlib import Path\n\nROOT = Path.cwd()\nSRC = ROOT / "tools" / "audit_order01_official_dasch_platephot_astrometry_v028r.py"\nBASE = ROOT / "results" / "order01_native_full_v028"\nPREV = BASE / "order01_dasch_v028r_platephot_caller_contract_v028ba.json"\n\nOUT_JSON = BASE / "order01_dasch_v028r_executor_contract_certified_v028bb.json"\nOUT_MD = BASE / "ORDER01_DASCH_V028R_EXECUTOR_CONTRACT_CERTIFIED_V028BB.md"\n\nEXPECTED_PATH = "dasch/dr7/platephot"\nEXPECTED_KEYS = {\n    "plate_id",\n    "solution_number",\n    "refcat",\n    "center_ra_deg",\n    "center_dec_deg",\n}\n\n\ndef write_json(path, obj):\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(\n        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n    tmp.replace(path)\n\n\ndef srcseg(src, node):\n    return ast.get_source_segment(src, node) or ""\n\n\ndef normalize_path(path):\n    return str(path or "").strip().lstrip("/")\n\n\ndef parents(tree):\n    out = {}\n    for node in ast.walk(tree):\n        for child in ast.iter_child_nodes(node):\n            out[child] = node\n    return out\n\n\ndef enclosing_function(node, pmap):\n    cur = node\n    while cur in pmap:\n        cur = pmap[cur]\n        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):\n            return cur\n    return None\n\n\ndef call_func_name(node, src):\n    return srcseg(src, node.func).strip()\n\n\ndef arg(call, pos, keyword):\n    if len(call.args) > pos:\n        return call.args[pos]\n    for kw in call.keywords:\n        if kw.arg == keyword:\n            return kw.value\n    return None\n\n\ndef literal(node):\n    if isinstance(node, ast.Constant):\n        return node.value\n    return None\n\n\ndef nearest_preceding_assignment(fn, variable, call_lineno, src):\n    candidates = []\n    for node in ast.walk(fn):\n        if getattr(node, "lineno", 10**12) >= call_lineno:\n            continue\n\n        if isinstance(node, ast.Assign):\n            targets = node.targets\n            value = node.value\n        elif isinstance(node, ast.AnnAssign):\n            targets = [node.target]\n            value = node.value\n        else:\n            continue\n\n        for target in targets:\n            if isinstance(target, ast.Name) and target.id == variable:\n                candidates.append((node.lineno, value, node))\n\n    if not candidates:\n        return None\n\n    lineno, value, node = max(candidates, key=lambda x: x[0])\n    return {\n        "lineno": lineno,\n        "expression": srcseg(src, value),\n        "node": value,\n    }\n\n\ndef dict_keys(node):\n    if not isinstance(node, ast.Dict):\n        return []\n    out = []\n    for k in node.keys:\n        if isinstance(k, ast.Constant) and isinstance(k.value, str):\n            out.append(k.value)\n    return out\n\n\ndef assigned_constant(tree, name):\n    vals = []\n    for node in ast.walk(tree):\n        if isinstance(node, ast.Assign):\n            for target in node.targets:\n                if isinstance(target, ast.Name) and target.id == name:\n                    if isinstance(node.value, ast.Constant):\n                        vals.append(node.value.value)\n    return vals[-1] if vals else None\n\n\ndef request_json_transport(tree, src):\n    pmap = parents(tree)\n    fn = next(\n        (\n            n for n in ast.walk(tree)\n            if isinstance(n, ast.FunctionDef) and n.name == "request_json"\n        ),\n        None,\n    )\n    if fn is None:\n        return None\n\n    post_calls = []\n    for node in ast.walk(fn):\n        if isinstance(node, ast.Call):\n            txt = srcseg(src, node)\n            if "requests.post" in txt:\n                post_calls.append({\n                    "lineno": node.lineno,\n                    "expression": txt,\n                })\n\n    return {\n        "function": "request_json",\n        "source": srcseg(src, fn),\n        "post_calls": post_calls,\n    }\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — CERTIFIED v028r PLATEPHOT EXECUTOR CONTRACT v028bb")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for path in (SRC, PREV):\n        if not path.is_file():\n            print(f"FAIL missing input: {path}")\n            return 2\n\n    src = SRC.read_text(encoding="utf-8", errors="strict")\n    tree = ast.parse(src)\n    pmap = parents(tree)\n\n    exact_calls = []\n\n    for node in ast.walk(tree):\n        if not isinstance(node, ast.Call):\n            continue\n        if call_func_name(node, src) != "request_json":\n            continue\n\n        method = literal(arg(node, 0, "method"))\n        path = literal(arg(node, 1, "path"))\n\n        if method != "POST":\n            continue\n        if normalize_path(path) != EXPECTED_PATH:\n            continue\n\n        fn = enclosing_function(node, pmap)\n        if fn is None:\n            continue\n\n        payload_node = arg(node, 2, "payload")\n        cache_node = arg(node, 3, "cache")\n\n        payload_assignment = None\n        payload_keys = []\n\n        if isinstance(payload_node, ast.Name):\n            payload_assignment = nearest_preceding_assignment(\n                fn, payload_node.id, node.lineno, src\n            )\n            if payload_assignment:\n                payload_keys = dict_keys(payload_assignment["node"])\n                payload_assignment.pop("node", None)\n        elif isinstance(payload_node, ast.Dict):\n            payload_keys = dict_keys(payload_node)\n\n        cache_assignment = None\n        if isinstance(cache_node, ast.Name):\n            cache_assignment = nearest_preceding_assignment(\n                fn, cache_node.id, node.lineno, src\n            )\n            if cache_assignment:\n                cache_assignment.pop("node", None)\n\n        exact_calls.append({\n            "lineno": node.lineno,\n            "enclosing_function": fn.name,\n            "method": method,\n            "path_literal": path,\n            "path_normalized": normalize_path(path),\n            "call_expression": srcseg(src, node),\n            "payload_expression": srcseg(src, payload_node),\n            "payload_assignment": payload_assignment,\n            "payload_keys": payload_keys,\n            "cache_expression": srcseg(src, cache_node),\n            "cache_assignment": cache_assignment,\n        })\n\n    base_url = assigned_constant(tree, "BASE_URL")\n    timeout = assigned_constant(tree, "TIMEOUT")\n    plate_id = assigned_constant(tree, "PLATE_ID")\n    refcat = assigned_constant(tree, "REFCAT")\n\n    transport = request_json_transport(tree, src)\n\n    selected = exact_calls[0] if len(exact_calls) == 1 else None\n    key_set = set(selected["payload_keys"]) if selected else set()\n    payload_exact = key_set == EXPECTED_KEYS\n\n    certified = bool(\n        selected\n        and payload_exact\n        and base_url\n        and transport\n        and transport.get("post_calls")\n    )\n\n    endpoint = None\n    if base_url and selected:\n        endpoint = str(base_url).rstrip("/") + "/" + selected["path_normalized"]\n\n    print(f"Exact POST platephot call count: {len(exact_calls)}")\n    print(f"Selected unique caller: {selected is not None}")\n    if selected:\n        print(f"Caller line: {selected[\'lineno\']}")\n        print(f"Path literal: {selected[\'path_literal\']!r}")\n        print(f"Normalized path: {selected[\'path_normalized\']!r}")\n        print(f"Payload assignment line: {selected[\'payload_assignment\'][\'lineno\'] if selected[\'payload_assignment\'] else None}")\n        print(f"Payload keys: {sorted(selected[\'payload_keys\'])}")\n    print(f"Payload exact five-field contract: {payload_exact}")\n    print(f"BASE_URL: {base_url!r}")\n    print(f"TIMEOUT: {timeout!r}")\n    print(f"PLATE_ID: {plate_id!r}")\n    print(f"REFCAT: {refcat!r}")\n    print(f"Executor contract certified: {certified}")\n\n    payload = {\n        "stage": "ORDER01_DASCH_V028R_EXECUTOR_CONTRACT_CERTIFIED_V028BB",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "source_file": str(SRC.relative_to(ROOT)),\n        "normalization": {\n            "leading_slash_ignored": True,\n            "rationale": "request_json constructs URL with path.lstrip(\'/\')",\n            "payload_definition_rule": "nearest_preceding_assignment_in_same_function",\n        },\n        "summary": {\n            "exact_post_platephot_call_count": len(exact_calls),\n            "unique_caller_selected": selected is not None,\n            "payload_exact_five_field_contract": payload_exact,\n            "executor_contract_certified": certified,\n        },\n        "certified_contract": {\n            "method": None if selected is None else selected["method"],\n            "path": None if selected is None else selected["path_normalized"],\n            "endpoint": endpoint,\n            "base_url": base_url,\n            "timeout": timeout,\n            "plate_id": plate_id,\n            "refcat": refcat,\n            "payload_keys": None if selected is None else selected["payload_keys"],\n            "caller": selected,\n            "transport": transport,\n        },\n        "executor_gate": {\n            "network_executor_may_be_built": certified,\n            "network_executor_may_run_without_explicit_allow_network": False,\n        },\n        "interpretive_boundary": (\n            "This is a source-derived executor contract certification. No network "\n            "request was made. Future execution remains explicitly gated by the "\n            "automation runner\'s --allow-network flag and must use per-item caching "\n            "and checkpointing."\n        ),\n    }\n\n    write_json(OUT_JSON, payload)\n\n    md = [\n        "# ORDER 01 — Certified v028r Platephot Executor Contract v028bb",\n        "",\n        "## Result",\n        "",\n        f"- Exact normalized POST platephot caller count: **{len(exact_calls)}**.",\n        f"- Unique caller selected: **{selected is not None}**.",\n        f"- Exact five-field payload: **{payload_exact}**.",\n        f"- Executor contract certified: **{certified}**.",\n        f"- Endpoint: `{endpoint}`.",\n        f"- Timeout from original source: `{timeout}`.",\n        "",\n        "No network request was made.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_MD}")\n    print()\n    print("NO network query was made.")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE NOT READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_executor_contract_certified_v028bb",
        title="Normalize and certify exact v028r platephot executor contract",
        script="automation/stages/certify_v028r_executor_contract_v028bb.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_v028r_platephot_caller_contract_v028ba.json",
            "tools/audit_order01_official_dasch_platephot_astrometry_v028r.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_v028r_executor_contract_certified_v028bb.json",
        ),
        dependencies=("dasch_platephot_caller_contract_v028ba",),
        notes="Normalizes leading-slash equivalence and nearest payload assignment before network execution.",
    ),
"""

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.0.7 — CERTIFY EXECUTOR CONTRACT")
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
    if 'stage_id="dasch_executor_contract_certified_v028bb"' in reg:
        print("FAIL registry already contains v028bb")
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
    print("Registered: dasch_executor_contract_certified_v028bb")

    runner = RUNNER.read_text(encoding="utf-8")
    runner = runner.replace(
        'print("Transient automation v0.0.6 - Order01 registry status\\n")',
        'print("Transient automation v0.0.7 - Order01 registry status\\n")',
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO/"__init__.py").write_text('__version__ = "0.0.7"\n', encoding="utf-8")

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
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_executor_contract_certified_v028bb')
    print("\nNo network request will be made by v028bb.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
