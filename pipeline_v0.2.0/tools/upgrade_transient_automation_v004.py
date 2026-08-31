#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "extract_dasch_request_contract_v028ay.py"
BACKUP = AUTO / "backups" / "pre_v004"

STAGE_CONTENT = '#!/usr/bin/env python3\n"""\nORDER 01 — exact DASCH v028r request-contract extraction v028ay\n\nPurpose\n-------\nBefore executing a 2,911-item prevalence expansion queue, recover the exact\nalready-working DASCH DR7 request contract used by the v028r-era code.\n\nThis is source/provenance inspection only:\n- scans local Python source under tools/ and automation/ for v028r/platephot logic;\n- extracts URL-like constants, requests/httpx call sites, function definitions,\n  payload/query construction snippets, timeout/retry/sleep hints, and cache names;\n- identifies the strongest likely request implementation;\n- writes a machine-readable contract-evidence artifact for the next executor stage.\n\nNO NETWORK ACCESS.\nSCIENCE PIXELS ARE NOT READ.\nNON-SCIENCE PIXELS ARE NOT READ.\nFrozen transient detector is NOT rerun.\nNo candidate state mutation.\n"""\n\nfrom __future__ import annotations\n\nimport ast\nimport json\nimport re\nfrom pathlib import Path\n\nROOT = Path.cwd()\nTOOLS = ROOT / "tools"\nAUTO = ROOT / "automation"\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nOUT_JSON = BASE / "order01_dasch_v028r_request_contract_v028ay.json"\nOUT_TXT = BASE / "ORDER01_DASCH_V028R_REQUEST_CONTRACT_V028AY.txt"\nOUT_MD = BASE / "ORDER01_DASCH_V028R_REQUEST_CONTRACT_V028AY.md"\n\nSEARCH_TERMS = (\n    "v028r",\n    "platephot",\n    "dasch",\n    "api",\n    "requests",\n    "httpx",\n    "url",\n    "timeout",\n    "retry",\n    "sleep",\n    "refcat",\n    "solution",\n    "plate",\n)\n\nURL_RE = re.compile(r\'https?://[^\\s\\\'"]+\')\n\ndef write_json(path, obj):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(\n        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n    tmp.replace(path)\n\ndef candidate_sources():\n    out = []\n    for root in (TOOLS, AUTO):\n        if not root.exists():\n            continue\n        for p in root.rglob("*.py"):\n            low = p.name.lower()\n            try:\n                text = p.read_text(encoding="utf-8", errors="ignore")\n            except Exception:\n                continue\n            body = text.lower()\n            score = 0\n            if "v028r" in low or "v028r" in body:\n                score += 100\n            if "platephot" in low or "platephot" in body:\n                score += 60\n            if "dasch" in low or "dasch" in body:\n                score += 20\n            if "requests." in body or "httpx." in body:\n                score += 20\n            if score:\n                out.append((score, p, text))\n    out.sort(key=lambda x: (-x[0], str(x[1])))\n    return out\n\ndef source_excerpt(lines, linenos, radius=8):\n    chosen = set()\n    for n in linenos:\n        for j in range(max(1, n-radius), min(len(lines), n+radius)+1):\n            chosen.add(j)\n    if not chosen:\n        return []\n    ranges = []\n    start = prev = None\n    for n in sorted(chosen):\n        if start is None:\n            start = prev = n\n        elif n == prev + 1:\n            prev = n\n        else:\n            ranges.append((start, prev))\n            start = prev = n\n    ranges.append((start, prev))\n    return [{\n        "start_line": a,\n        "end_line": b,\n        "text": "\\n".join(f"{j:05d}: {lines[j-1]}" for j in range(a, b+1)),\n    } for a, b in ranges]\n\ndef analyze_source(path, text):\n    lines = text.splitlines()\n    info = {\n        "source_file": str(path.relative_to(ROOT)),\n        "urls": sorted(set(URL_RE.findall(text))),\n        "functions": [],\n        "assignments": [],\n        "http_calls": [],\n        "relevant_excerpts": [],\n    }\n\n    try:\n        tree = ast.parse(text)\n    except SyntaxError as exc:\n        info["parse_error"] = f"{type(exc).__name__}: {exc}"\n        return info\n\n    relevant_lines = set()\n\n    for node in ast.walk(tree):\n        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):\n            seg = ast.get_source_segment(text, node) or ""\n            low = (node.name + " " + seg[:3000]).lower()\n            if any(t in low for t in ("platephot", "dasch", "request", "fetch", "query", "http")):\n                info["functions"].append({\n                    "name": node.name,\n                    "lineno": node.lineno,\n                    "end_lineno": getattr(node, "end_lineno", node.lineno),\n                    "args": [a.arg for a in node.args.args],\n                })\n                relevant_lines.add(node.lineno)\n\n        elif isinstance(node, (ast.Assign, ast.AnnAssign)):\n            targets = node.targets if isinstance(node, ast.Assign) else [node.target]\n            value = node.value\n            for target in targets:\n                if isinstance(target, ast.Name):\n                    name = target.id\n                    seg = ast.get_source_segment(text, value) or ""\n                    low = (name + " " + seg).lower()\n                    if any(t in low for t in SEARCH_TERMS):\n                        info["assignments"].append({\n                            "name": name,\n                            "lineno": node.lineno,\n                            "expression": seg[:3000],\n                        })\n                        relevant_lines.add(node.lineno)\n\n        elif isinstance(node, ast.Call):\n            func = ast.get_source_segment(text, node.func) or ""\n            low = func.lower()\n            if (\n                "requests." in low\n                or "httpx." in low\n                or low.endswith(".get")\n                or low.endswith(".post")\n                or "urlopen" in low\n            ):\n                call = ast.get_source_segment(text, node) or ""\n                info["http_calls"].append({\n                    "lineno": node.lineno,\n                    "function": func,\n                    "call": call[:5000],\n                })\n                relevant_lines.add(node.lineno)\n\n    # Textual hints that AST alone may not capture semantically.\n    for idx, line in enumerate(lines, start=1):\n        low = line.lower()\n        if any(t in low for t in (\n            "platephot", "refcat", "solution", "timeout",\n            "retry", "sleep(", "user-agent", "headers",\n            "status_code", "raise_for_status",\n        )):\n            relevant_lines.add(idx)\n\n    info["relevant_excerpts"] = source_excerpt(lines, relevant_lines, radius=6)\n    return info\n\ndef score_analysis(a):\n    score = 0\n    low = json.dumps(a).lower()\n    if "platephot" in low:\n        score += 50\n    if a.get("http_calls"):\n        score += 40\n    if a.get("urls"):\n        score += 20\n    if "refcat" in low:\n        score += 10\n    if "solution" in low:\n        score += 10\n    if "plate" in low:\n        score += 10\n    return score\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — EXACT DASCH v028r REQUEST-CONTRACT EXTRACTION v028ay")\n    print("=" * 128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    sources = candidate_sources()\n    if not sources:\n        print("FAIL: no v028r/platephot-related Python sources discovered.")\n        return 2\n\n    analyses = []\n    for discovery_score, path, text in sources:\n        a = analyze_source(path, text)\n        a["discovery_score"] = discovery_score\n        a["contract_score"] = score_analysis(a)\n        analyses.append(a)\n\n    analyses.sort(\n        key=lambda a: (-a["contract_score"], -a["discovery_score"], a["source_file"])\n    )\n\n    best = analyses[0]\n    confident = (\n        best["contract_score"] >= 80\n        and bool(best.get("http_calls"))\n        and ("platephot" in json.dumps(best).lower())\n    )\n\n    print(f"Relevant source files discovered: {len(analyses)}")\n    print(f"Best request-contract source: {best[\'source_file\']}")\n    print(f"Contract score: {best[\'contract_score\']}")\n    print(f"HTTP call sites: {len(best.get(\'http_calls\', []))}")\n    print(f"URL constants/literals: {len(best.get(\'urls\', []))}")\n    print(f"Confident exact request implementation recovered: {confident}")\n\n    print("\\nTop source candidates:")\n    for a in analyses[:10]:\n        print(\n            f"  score={a[\'contract_score\']:3d} discovery={a[\'discovery_score\']:3d} "\n            f"http={len(a.get(\'http_calls\', [])):2d} "\n            f"{a[\'source_file\']}"\n        )\n\n    payload = {\n        "stage": "ORDER01_DASCH_V028R_REQUEST_CONTRACT_V028AY",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "summary": {\n            "relevant_source_file_count": len(analyses),\n            "best_source_file": best["source_file"],\n            "best_contract_score": best["contract_score"],\n            "best_http_call_count": len(best.get("http_calls", [])),\n            "best_url_count": len(best.get("urls", [])),\n            "confident_exact_request_implementation_recovered": confident,\n        },\n        "best_source_analysis": best,\n        "source_analyses": analyses,\n        "interpretive_boundary": (\n            "v028ay performs source/provenance extraction only. It authorizes no "\n            "network request. The next network executor should reuse the recovered "\n            "working request implementation or stop if the contract is not "\n            "unambiguous."\n        ),\n    }\n\n    write_json(OUT_JSON, payload)\n\n    txt = []\n    for a in analyses:\n        txt.append("=" * 100)\n        txt.append(a["source_file"])\n        txt.append(\n            f"contract_score={a[\'contract_score\']} "\n            f"discovery_score={a[\'discovery_score\']}"\n        )\n        txt.append("=" * 100)\n        if a["urls"]:\n            txt.append("\\nURLs:")\n            txt.extend("  " + u for u in a["urls"])\n        if a["http_calls"]:\n            txt.append("\\nHTTP CALLS:")\n            for h in a["http_calls"]:\n                txt.append(f"\\nline {h[\'lineno\']}: {h[\'call\']}")\n        txt.append("\\nRELEVANT SOURCE EXCERPTS:")\n        for ex in a["relevant_excerpts"]:\n            txt.append(\n                f"\\n--- lines {ex[\'start_line\']}-{ex[\'end_line\']} ---\\n"\n                + ex["text"]\n            )\n        txt.append("")\n    OUT_TXT.write_text("\\n".join(txt), encoding="utf-8")\n\n    md = [\n        "# ORDER 01 — Exact DASCH v028r Request Contract v028ay",\n        "",\n        "## Guard state",\n        "",\n        "- No network access.",\n        "- Science pixels were not read.",\n        "- Non-science pixels were not read.",\n        "- The frozen detector was not rerun.",\n        "- No candidate state was changed.",\n        "",\n        "## Recovery result",\n        "",\n        f"- Relevant source files: **{len(analyses)}**.",\n        f"- Best source: `{best[\'source_file\']}`.",\n        f"- HTTP call sites: **{len(best.get(\'http_calls\', []))}**.",\n        f"- Exact-contract confidence: **{confident}**.",\n        "",\n        "## Interpretation boundary",\n        "",\n        payload["interpretive_boundary"],\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_TXT}")\n    print(f"  {OUT_MD}")\n    print()\n    print("NO network query was made.")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE NOT READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n\n    # Do not fail solely on confidence; emit artifact for inspection.\n    return 0\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_request_contract_v028ay",
        title="Extract exact working DASCH v028r request contract",
        script="automation/stages/extract_dasch_request_contract_v028ay.py",
        requires=(
            "automation/queues/ai43437_prevalence_v028ax.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_v028r_request_contract_v028ay.json",
        ),
        dependencies=("dasch_prevalence_coverage_plan_v028ax",),
        notes="Source/provenance-only prerequisite to any queued network executor.",
    ),
"""

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.0.4 — NETWORK CONTRACT PREPARATION")
    print("="*112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("No existing science/result artifact is modified.")
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
    if 'stage_id="dasch_request_contract_v028ay"' in reg:
        print("FAIL registry already contains v028ay")
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
    print("Registered: dasch_request_contract_v028ay")

    # Cosmetic but useful: make the status banner report the framework version
    # rather than a stale hard-coded v0.0.2 string.
    runner = RUNNER.read_text(encoding="utf-8")
    runner = runner.replace(
        'print("Transient automation v0.0.2 - Order01 registry status\\n")',
        'print("Transient automation v0.0.4 - Order01 registry status\\n")',
    )
    RUNNER.write_text(runner, encoding="utf-8")

    (AUTO/"__init__.py").write_text(
        '__version__ = "0.0.4"\n',
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
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_request_contract_v028ay')
    print("\nNo network request will be made by v028ay.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
