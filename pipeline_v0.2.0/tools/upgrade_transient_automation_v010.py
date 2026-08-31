#!/usr/bin/env python3
from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "execute_platephot_full_queue_v028be.py"
BACKUP = AUTO / "backups" / "pre_v010"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv, importlib.util, io, json, os, sys, time\nfrom pathlib import Path\nimport requests\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\nWORK = ROOT / "work" / "order01_native_full_v028"\n\nQUEUE = AUTO / "queues" / "ai43437_prevalence_v028bc.json"\nCERT = BASE / "order01_dasch_v028r_executor_contract_certified_v028bb.json"\nCALIBRATION = BASE / "order01_dasch_platephot_live_calibration_v028bd.json"\nV028R_SRC = ROOT / "tools" / "audit_order01_official_dasch_platephot_astrometry_v028r.py"\n\nCACHE_DIR = WORK / "automation_platephot_v028bd"\nCHECKPOINT = AUTO / "state" / "ai43437_platephot_full_v028be.json"\nPROGRESS_JSON = BASE / "order01_dasch_platephot_full_progress_v028be.json"\nFINAL_JSON = BASE / "order01_dasch_platephot_full_fetch_v028be.json"\nFINAL_CSV = BASE / "order01_dasch_platephot_full_fetch_v028be.csv"\nFINAL_MD = BASE / "ORDER01_DASCH_PLATEPHOT_FULL_FETCH_V028BE.md"\n\nDEFAULT_BATCH_SIZE = 50\nMAX_BATCH_SIZE = 200\nINTER_REQUEST_SECONDS = 1.0\nLOCAL_ATTEMPTS = 3\nBACKOFF_SECONDS = (2.0, 5.0, 10.0)\nCOORD_COLUMN_ALIASES = (("ra_deg", "dec_deg"), ("raDeg", "decDeg"))\n\n\ndef write_json(path, obj):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n", encoding="utf-8")\n    tmp.replace(path)\n\n\ndef write_csv(path, rows, fields):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    with tmp.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(rows)\n    tmp.replace(path)\n\n\ndef load_v028r():\n    spec = importlib.util.spec_from_file_location("validated_v028r_full", V028R_SRC)\n    if spec is None or spec.loader is None:\n        raise RuntimeError("cannot import validated v028r source")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    return mod\n\n\ndef parse_response(obj):\n    if not isinstance(obj, list):\n        return False, None, [], None, f"top-level type {type(obj).__name__}, expected list"\n    if not obj:\n        return True, 0, [], None, "empty list response"\n    if not all(isinstance(x, str) for x in obj):\n        return False, None, [], None, "list contains non-string elements"\n    try:\n        reader = csv.DictReader(io.StringIO("\\n".join(obj)))\n        rows = list(reader)\n        cols = list(reader.fieldnames or [])\n    except Exception as exc:\n        return False, None, [], None, f"CSV parse failed: {type(exc).__name__}: {exc}"\n    pair = next((p for p in COORD_COLUMN_ALIASES if set(p).issubset(set(cols))), None)\n    if pair is None:\n        return False, len(rows), cols, None, "coordinate columns missing"\n    return True, len(rows), cols, list(pair), "ok"\n\n\ndef batch_size():\n    raw = os.environ.get("TRANSIENT_QUEUE_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))\n    n = int(raw)\n    if n < 1 or n > MAX_BATCH_SIZE:\n        raise RuntimeError(f"TRANSIENT_QUEUE_BATCH_SIZE must be 1..{MAX_BATCH_SIZE}")\n    return n\n\n\ndef classify_exception(exc):\n    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):\n        return "RETRYABLE_NETWORK"\n    if isinstance(exc, requests.HTTPError):\n        status = getattr(getattr(exc, "response", None), "status_code", None)\n        if status in (408, 425, 429) or (status is not None and 500 <= status <= 599):\n            return "RETRYABLE_HTTP"\n        return "TERMINAL_HTTP"\n    text = str(exc).lower()\n    if any(x in text for x in ("timeout", "timed out", "connection", "temporar", "429", "502", "503", "504", "500")):\n        return "RETRYABLE_WRAPPED"\n    return "TERMINAL_EXCEPTION"\n\n\ndef summary(cp, total):\n    rows = list(cp.get("items", {}).values())\n    good = [r for r in rows if r.get("status") == "SUCCESS"]\n    bad_retry = [r for r in rows if str(r.get("status", "")).startswith("FAILED_RETRYABLE")]\n    bad_term = [r for r in rows if str(r.get("status", "")).startswith("FAILED_TERMINAL")]\n    bad_schema = [r for r in rows if r.get("status") == "FAILED_RESPONSE_SCHEMA"]\n    return {\n        "total_queue_items": total,\n        "success_count": len(good),\n        "remaining_count": total - len(good),\n        "retryable_failure_count": len(bad_retry),\n        "terminal_failure_count": len(bad_term),\n        "schema_failure_count": len(bad_schema),\n        "complete": len(good) == total and not bad_retry and not bad_term and not bad_schema,\n        "network_response_count": sum(1 for r in good if str(r.get("request_source", "")).lower() != "cache"),\n        "cache_response_count": sum(1 for r in good if str(r.get("request_source", "")).lower() == "cache"),\n        "response_rows_total": sum(int(r.get("response_row_count") or 0) for r in good),\n    }\n\n\ndef write_progress(cp, total, batch):\n    write_json(PROGRESS_JSON, {\n        "stage": "ORDER01_DASCH_PLATEPHOT_FULL_PROGRESS_V028BE",\n        "guards": {\n            "network_access": True,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "batch_size": batch,\n        "summary": summary(cp, total),\n        "checkpoint_file": str(CHECKPOINT.relative_to(ROOT)),\n        "cache_directory": str(CACHE_DIR.relative_to(ROOT)),\n        "interpretive_boundary": "API acquisition progress only; not a prevalence result.",\n    })\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — FULL RESUMABLE DASCH PLATEPHOT QUEUE EXECUTOR v028be")\n    print("=" * 128)\n    print("NETWORK ACCESS: REQUIRED AND EXPLICITLY RUNNER-GATED.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (QUEUE, CERT, CALIBRATION, V028R_SRC):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 6\n\n    cert = json.loads(CERT.read_text(encoding="utf-8"))\n    cal = json.loads(CALIBRATION.read_text(encoding="utf-8"))\n    if not cert.get("executor_gate", {}).get("network_executor_may_be_built"):\n        print("FAIL v028bb executor gate false")\n        return 6\n    if not cal.get("executor_gate", {}).get("full_queue_executor_may_be_enabled"):\n        print("FAIL v028bd calibration gate false")\n        return 6\n\n    contract = cert.get("certified_contract", {})\n    if contract.get("method") != "POST" or str(contract.get("path", "")).lstrip("/") != "dasch/dr7/platephot":\n        print("FAIL certified contract mismatch")\n        return 6\n\n    qobj = json.loads(QUEUE.read_text(encoding="utf-8"))\n    items = sorted(qobj.get("items", []), key=lambda r: int(r["queue_order"]))\n    if not items:\n        print("FAIL empty queue")\n        return 6\n    if [int(r["queue_order"]) for r in items] != list(range(1, len(items) + 1)):\n        print("FAIL queue_order is not contiguous 1..N")\n        return 6\n\n    batch = batch_size()\n    CACHE_DIR.mkdir(parents=True, exist_ok=True)\n    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)\n\n    if CHECKPOINT.is_file():\n        cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))\n    else:\n        cp = {\n            "stage": "ORDER01_DASCH_PLATEPHOT_FULL_QUEUE_V028BE",\n            "queue_id": qobj.get("queue_id"),\n            "queue_count": len(items),\n            "items": {},\n        }\n\n    if cp.get("queue_id") != qobj.get("queue_id") or int(cp.get("queue_count", -1)) != len(items):\n        print("FAIL checkpoint/queue identity mismatch")\n        return 6\n\n    mod = load_v028r()\n    pending = []\n\n    for item in items:\n        q = int(item["queue_order"])\n        key = str(q)\n        cache = CACHE_DIR / f"ai43437_sol0_q{q:04d}_apass_platephot.json"\n        prior = cp["items"].get(key)\n        if prior and prior.get("status") == "SUCCESS" and cache.is_file():\n            try:\n                obj = json.loads(cache.read_text(encoding="utf-8"))\n                valid, _, _, _, reason = parse_response(obj)\n            except Exception as exc:\n                valid, reason = False, f"{type(exc).__name__}: {exc}"\n            if valid:\n                continue\n            prior["status"] = "FAILED_TERMINAL_CACHE_VALIDATION"\n            prior["response_reason"] = reason\n            write_json(CHECKPOINT, cp)\n            write_progress(cp, len(items), batch)\n            print(f"FAIL q{q:04d}: checkpointed cache invalid")\n            return 6\n        pending.append(item)\n\n    before = summary(cp, len(items))\n    print(f"Queue items:            {len(items)}")\n    print(f"Already successful:     {before[\'success_count\']}")\n    print(f"Pending before batch:   {len(pending)}")\n    print(f"Batch size:             {batch}")\n\n    selected = pending[:batch]\n\n    for pos, item in enumerate(selected, 1):\n        q = int(item["queue_order"])\n        key = str(q)\n        cache = CACHE_DIR / f"ai43437_sol0_q{q:04d}_apass_platephot.json"\n        payload = {\n            "plate_id": str(item["plate_id"]),\n            "solution_number": int(item["solution"]),\n            "refcat": str(item["refcat"]),\n            "center_ra_deg": float(item["center_ra_deg"]),\n            "center_dec_deg": float(item["center_dec_deg"]),\n        }\n\n        print(f"[{pos:03d}/{len(selected):03d}] q{q:04d} center=({payload[\'center_ra_deg\']:.8f},{payload[\'center_dec_deg\']:.8f}) coversNative={item.get(\'native_candidates_covered\')}")\n\n        rec = None\n        for attempt in range(1, LOCAL_ATTEMPTS + 1):\n            started = time.time()\n            try:\n                obj, used = mod.request_json("POST", "dasch/dr7/platephot", payload=payload, cache=cache)\n                elapsed = time.time() - started\n                valid, row_count, cols, coord_cols, reason = parse_response(obj)\n                if not valid:\n                    rec = {\n                        "queue_order": q, "status": "FAILED_RESPONSE_SCHEMA",\n                        "attempt": attempt, "center_ra_deg": payload["center_ra_deg"],\n                        "center_dec_deg": payload["center_dec_deg"],\n                        "native_candidates_covered": int(item.get("native_candidates_covered", 0)),\n                        "cache": str(cache.relative_to(ROOT)), "request_source": used,\n                        "elapsed_seconds": elapsed, "response_valid": False,\n                        "response_reason": reason, "response_row_count": row_count,\n                        "response_columns": cols,\n                    }\n                    break\n\n                rec = {\n                    "queue_order": q, "status": "SUCCESS", "attempt": attempt,\n                    "center_ra_deg": payload["center_ra_deg"],\n                    "center_dec_deg": payload["center_dec_deg"],\n                    "native_candidates_covered": int(item.get("native_candidates_covered", 0)),\n                    "cache": str(cache.relative_to(ROOT)), "request_source": used,\n                    "elapsed_seconds": elapsed, "response_valid": True,\n                    "response_reason": reason, "response_row_count": row_count,\n                    "response_columns": cols, "coordinate_columns": coord_cols,\n                }\n                break\n\n            except KeyboardInterrupt:\n                write_json(CHECKPOINT, cp)\n                write_progress(cp, len(items), batch)\n                print("\\nINTERRUPTED: checkpoint preserved.")\n                raise\n\n            except Exception as exc:\n                elapsed = time.time() - started\n                cls = classify_exception(exc)\n                retryable = cls.startswith("RETRYABLE")\n                rec = {\n                    "queue_order": q,\n                    "status": ("FAILED_RETRYABLE_" + cls if retryable else "FAILED_TERMINAL_" + cls),\n                    "attempt": attempt, "center_ra_deg": payload["center_ra_deg"],\n                    "center_dec_deg": payload["center_dec_deg"],\n                    "native_candidates_covered": int(item.get("native_candidates_covered", 0)),\n                    "cache": str(cache.relative_to(ROOT)),\n                    "request_source": "network_or_cache", "elapsed_seconds": elapsed,\n                    "response_valid": False, "response_reason": f"{type(exc).__name__}: {exc}",\n                    "response_row_count": None, "response_columns": [],\n                }\n                if retryable and attempt < LOCAL_ATTEMPTS:\n                    delay = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]\n                    print(f"    retryable {cls}; attempt {attempt}/{LOCAL_ATTEMPTS}; backoff={delay:.1f}s")\n                    time.sleep(delay)\n                    continue\n                break\n\n        cp["items"][key] = rec\n        write_json(CHECKPOINT, cp)\n        write_progress(cp, len(items), batch)\n\n        if rec["status"] != "SUCCESS":\n            print(f"    STOP status={rec[\'status\']} reason={rec[\'response_reason\']}")\n            return 5 if rec["status"].startswith("FAILED_RETRYABLE") else 6\n\n        print(f"    SUCCESS source={rec[\'request_source\']} rows={rec[\'response_row_count\']} elapsed={rec[\'elapsed_seconds\']:.3f}s")\n        if pos < len(selected):\n            time.sleep(INTER_REQUEST_SECONDS)\n\n    after = summary(cp, len(items))\n    print("\\nBATCH SUMMARY")\n    print(f"  total successes: {after[\'success_count\']}/{len(items)}")\n    print(f"  remaining:       {after[\'remaining_count\']}")\n\n    if not after["complete"]:\n        print("\\nSTAGE STATUS: IN_PROGRESS")\n        return 10\n\n    rows = [cp["items"][str(q)] for q in range(1, len(items) + 1)]\n    final = {\n        "stage": "ORDER01_DASCH_PLATEPHOT_FULL_FETCH_V028BE",\n        "guards": {\n            "network_access": True,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "summary": after,\n        "queue_id": qobj.get("queue_id"),\n        "queue_count": len(items),\n        "checkpoint_file": str(CHECKPOINT.relative_to(ROOT)),\n        "cache_directory": str(CACHE_DIR.relative_to(ROOT)),\n        "items": rows,\n        "next_science_gate": {"platewide_prevalence_analysis_may_run": True},\n        "interpretive_boundary": "Complete official platephot acquisition only; prevalence classification is downstream.",\n    }\n    write_json(FINAL_JSON, final)\n    write_csv(FINAL_CSV, rows, [\n        "queue_order", "status", "center_ra_deg", "center_dec_deg",\n        "native_candidates_covered", "request_source", "attempt",\n        "elapsed_seconds", "response_valid", "response_reason",\n        "response_row_count", "cache",\n    ])\n    FINAL_MD.write_text(\n        "# ORDER 01 — Full DASCH Platephot Fetch v028be\\n\\n"\n        f"- Queue items: **{len(items)}**.\\n"\n        f"- Validated responses: **{after[\'success_count\']}**.\\n"\n        f"- Official response rows: **{after[\'response_rows_total\']}**.\\n\\n"\n        "No pixels were read and no candidate state changed.\\n",\n        encoding="utf-8",\n    )\n\n    print("\\nFULL QUEUE ACQUISITION COMPLETE")\n    print(f"  {FINAL_JSON}")\n    print(f"  {FINAL_CSV}")\n    print(f"  {FINAL_MD}")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_platephot_full_queue_v028be",
        title="Full resumable ai43437 DASCH platephot queue acquisition",
        script="automation/stages/execute_platephot_full_queue_v028be.py",
        requires=(
            "automation/queues/ai43437_prevalence_v028bc.json",
            "results/order01_native_full_v028/order01_dasch_v028r_executor_contract_certified_v028bb.json",
            "results/order01_native_full_v028/order01_dasch_platephot_live_calibration_v028bd.json",
            "tools/audit_order01_official_dasch_platephot_astrometry_v028r.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_platephot_full_fetch_v028be.json",
        ),
        dependencies=("dasch_platephot_live_calibration_v028bd",),
        network_access=True,
        retryable=True,
        notes="Bounded-batch executor; subprocess return code 10 means checkpointed IN_PROGRESS.",
    ),
"""

PROGRESS_PATCH = """
        if proc.returncode == 10:
            STATE.append("stage_progress", {
                "stage_id": stage.stage_id,
                "attempt": attempt,
                "returncode": 10,
                "classification": "IN_PROGRESS_CHECKPOINTED",
            })
            STATE.write_snapshot({
                "last_progress_stage": stage.stage_id,
                "framework_version": "0.1.0",
            })
            print("STAGE EXECUTION STATUS: IN_PROGRESS_CHECKPOINTED")
            return 10

"""

RUN_UNTIL_BLOCKED = """
def cmd_run_until_blocked(args):
    cycles = 0
    max_cycles = max(1, int(args.max_cycles))
    print(
        f"RUN-UNTIL-BLOCKED: max_cycles={max_cycles}; "
        "checkpointed IN_PROGRESS stages continue automatically."
    )

    while cycles < max_cycles:
        stage = _next_stage()
        if stage is None:
            incomplete = [
                s for s in ORDER01_STAGES
                if not stage_status(s)["complete"]
            ]
            if incomplete:
                print("No READY stage remains; blocked incomplete stages:")
                for st in incomplete:
                    print(f"  {st.stage_id}")
                return 2
            print("All currently registered stages are complete.")
            print("RUN-UNTIL-BLOCKED STATUS: COMPLETE")
            return 0

        print(f"\\n[CYCLE {cycles + 1}] selected: {stage.stage_id}")
        rc = execute_stage(stage, args)
        cycles += 1

        if rc == 10:
            continue
        if rc != 0:
            print(
                f"RUN-UNTIL-BLOCKED stopped on return code {rc} "
                f"from {stage.stage_id}"
            )
            return rc
        if not stage_status(stage)["complete"]:
            print(
                "RUN-UNTIL-BLOCKED safety stop: stage returned 0 "
                "but remains incomplete."
            )
            return 7

    print(
        f"RUN-UNTIL-BLOCKED reached max_cycles={max_cycles}; "
        "all progress is checkpointed."
    )
    return 10

"""

PARSER_PATCH = """
    s = sub.add_parser("run-until-blocked")
    add_execution_flags(s)
    s.add_argument(
        "--max-cycles",
        type=int,
        default=1000,
        help="Maximum checkpointed stage cycles before deliberate stop.",
    )
    s.set_defaults(func=cmd_run_until_blocked)

"""


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION UPGRADE v0.1.0 — FULL RESUMABLE QUEUE EXECUTOR")
    print("=" * 112)
    print("NO NETWORK ACCESS IS PERFORMED BY THIS UPGRADE.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("No science/result artifact is modified.")
    print("No candidate state is changed.\\n")

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

    if STAGE.exists():
        print(f"FAIL stage already exists: {STAGE}")
        return 2

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_CONTENT, encoding="utf-8")
    print(f"Created: {STAGE.relative_to(ROOT)}")

    reg = REGISTRY.read_text(encoding="utf-8")
    if 'stage_id="dasch_platephot_full_queue_v028be"' in reg:
        print("FAIL registry already contains v028be")
        return 2
    marker = "\\n]\\n\\ndef by_id():"
    if marker not in reg:
        print("FAIL registry insertion marker not found.")
        return 3
    reg = reg.replace(
        marker,
        "\\n" + REGISTRY_ENTRY.rstrip() + "\\n]\\n\\ndef by_id():",
        1,
    )
    REGISTRY.write_text(reg, encoding="utf-8")
    print("Registered: dasch_platephot_full_queue_v028be")

    runner = RUNNER.read_text(encoding="utf-8")

    progress_marker = (
        "        proc = subprocess.run(cmd, cwd=ROOT)\\n\\n"
        "        if proc.returncode == 0:"
    )
    if progress_marker not in runner:
        print("FAIL runner progress insertion marker not found.")
        return 3
    runner = runner.replace(
        progress_marker,
        "        proc = subprocess.run(cmd, cwd=ROOT)\\n\\n"
        + PROGRESS_PATCH
        + "        if proc.returncode == 0:",
        1,
    )

    command_marker = "\\ndef add_execution_flags(parser):\\n"
    if command_marker not in runner:
        print("FAIL runner command insertion marker not found.")
        return 3
    runner = runner.replace(
        command_marker,
        "\\n" + RUN_UNTIL_BLOCKED.rstrip() + "\\n\\n"
        + "def add_execution_flags(parser):\\n",
        1,
    )

    parser_marker = "    return p\\n\\ndef main():"
    if parser_marker not in runner:
        print("FAIL runner parser insertion marker not found.")
        return 3
    runner = runner.replace(
        parser_marker,
        PARSER_PATCH + "    return p\\n\\ndef main():",
        1,
    )

    runner = runner.replace(
        'print("Transient automation v0.0.9 - Order01 registry status\\\\n")',
        'print("Transient automation v0.1.0 - Order01 registry status\\\\n")',
    )
    RUNNER.write_text(runner, encoding="utf-8")

    (AUTO / "__init__.py").write_text('__version__ = "0.1.0"\\n', encoding="utf-8")

    failures = []
    py_files = sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
    print(f"\\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\\nAUTOMATION UPGRADE STATUS: FAIL")
        return 4

    print("\\nAUTOMATION UPGRADE STATUS: PASS")
    print("\\nNew orchestration:")
    print("  subprocess return code 10 = IN_PROGRESS_CHECKPOINTED")
    print("  run-until-blocked automatically advances checkpointed batches")
    print("  genuine failures stop immediately")
    print("\\nRecommended commands:")
    print(r'  & ".\\.venv\\Scripts\\python.exe" -m automation.runner status')
    print(r'  & ".\\.venv\\Scripts\\python.exe" -m automation.runner run-next')
    print("    (expected: REFUSED without --allow-network)")
    print(r'  & ".\\.venv\\Scripts\\python.exe" -m automation.runner run-until-blocked --allow-network')
    print("\\nDefault batch size: 50 pending queue items per checkpoint cycle.")
    print("No network request was made by this upgrade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
