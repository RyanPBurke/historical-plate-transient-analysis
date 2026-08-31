#!/usr/bin/env python3
"""Install the checkpointed Order-01 matched-recurrence phase-2 executor.

This upgrade derives the network caller and response parser from the already
verified v028bt phase-1 executor.  It refuses to proceed unless every expected
source fragment is present exactly once and the caller/parser function bodies
remain byte-identical after derivation.
"""
from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.cwd()
SOURCE = ROOT / "automation" / "stages" / "execute_matched_recurrence_phase1_v028bt.py"
TARGET = ROOT / "automation" / "stages" / "execute_matched_recurrence_phase2_v028bw.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
RUNNER = ROOT / "automation" / "runner.py"
PLAN = ROOT / "results" / "order01_native_full_v028" / "order01_dasch_matched_recurrence_256_plan_v028bv.json"
QUEUE = ROOT / "results" / "order01_native_full_v028" / "order01_dasch_matched_recurrence_phase2_queue_v028bv.csv"
BACKUP = ROOT / "automation" / "backups" / (
    "pre_v026_phase2_executor_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)

STAGE_ID = "dasch_matched_recurrence_phase2_v028bw"
VERSION = "0.3.2"
PRESERVED_FUNCTIONS = (
    "f",
    "first",
    "angular_sep_arcsec",
    "parse_api_csv",
    "read_queue",
    "post_cached",
    "summarize_response",
)


def refuse(message: str) -> None:
    raise SystemExit("REFUSING: " + message)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        refuse(f"{label}: expected exactly one source fragment, found {count}")
    return text.replace(old, new, 1)


def function_sources(text: str) -> dict[str, str]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in PRESERVED_FUNCTIONS:
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            found[node.name] = "".join(lines[start:end])
    missing = sorted(set(PRESERVED_FUNCTIONS) - set(found))
    if missing:
        refuse(f"missing preserved functions: {missing}")
    return found


def validate_inputs() -> None:
    for path in (SOURCE, REGISTRY, INIT, RUNNER, PLAN, QUEUE):
        if not path.is_file():
            refuse(f"required file missing: {path}")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        refuse("v028bv plan is not a JSON object")

    import csv
    with QUEUE.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    expected_columns = {
        "request_seq", "phase", "phase2_exposure_seq",
        "cumulative_selection_rank", "target", "center_ra_deg",
        "center_dec_deg", "exposure_identity", "plate_id",
        "solution_number", "refcat", "obs_date_jd", "obs_date_iso",
    }
    if not rows:
        refuse("phase-2 queue is empty")
    missing = sorted(expected_columns - set(rows[0]))
    if missing:
        refuse(f"phase-2 queue missing columns: {missing}")
    if len(rows) != 576:
        refuse(f"expected 576 phase-2 requests; got {len(rows)}")
    if [int(r["request_seq"]) for r in rows] != list(range(1, 577)):
        refuse("phase-2 request_seq is not exactly 1..576")
    if any(int(r["phase"]) != 2 for r in rows):
        refuse("phase-2 queue contains a non-phase-2 row")

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["exposure_identity"], []).append(row)
    if len(groups) != 192:
        refuse(f"expected 192 unique phase-2 exposures; got {len(groups)}")
    targets = {"science25", "q0030", "q0344"}
    for eid, group in groups.items():
        if len(group) != 3 or {r["target"] for r in group} != targets:
            refuse(f"exposure {eid!r} does not have exactly the three frozen targets")
        invariant = {
            (r["plate_id"], r["solution_number"], r["refcat"],
             r["phase2_exposure_seq"], r["cumulative_selection_rank"])
            for r in group
        }
        if len(invariant) != 1:
            refuse(f"exposure {eid!r} has inconsistent request identity fields")


def derive_stage(source: str) -> str:
    original_functions = function_sources(source)
    text = source
    queue_sha = hashlib.sha256(QUEUE.read_bytes()).hexdigest()
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()

    substitutions = (
        ('WORK = ROOT / "work" / "order01_native_full_v028" / "matched_recurrence_v028bt"',
         'WORK = ROOT / "work" / "order01_native_full_v028" / "matched_recurrence_v028bw_phase2"',
         "work directory"),
        ('PLAN = BASE / "order01_dasch_matched_recurrence_plan_v028bs.json"',
         'PLAN = BASE / "order01_dasch_matched_recurrence_256_plan_v028bv.json"',
         "plan path"),
        ('QUEUE = BASE / "order01_dasch_matched_recurrence_phase1_queue_v028bs.csv"',
         'QUEUE = BASE / "order01_dasch_matched_recurrence_phase2_queue_v028bv.csv"',
         "queue path"),
        ('OUT_JSON = BASE / "order01_dasch_matched_recurrence_phase1_v028bt.json"',
         'OUT_JSON = BASE / "order01_dasch_matched_recurrence_phase2_v028bw.json"',
         "JSON output"),
        ('OUT_CSV = BASE / "order01_dasch_matched_recurrence_phase1_v028bt.csv"',
         'OUT_CSV = BASE / "order01_dasch_matched_recurrence_phase2_v028bw.csv"',
         "CSV output"),
        ('OUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_V028BT.md"',
         'OUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE2_V028BW.md"',
         "Markdown output"),
        ('EXPECTED_REQUESTS = 192',
         'EXPECTED_REQUESTS = 576\n'
         f'EXPECTED_QUEUE_SHA256 = "{queue_sha}"\n'
         f'EXPECTED_PLAN_SHA256 = "{plan_sha}"',
         "request count and frozen input hashes"),
        ('ORDER 01 — MATCHED THREE-POSITION RECURRENCE PHASE 1 v028bt',
         'ORDER 01 — MATCHED THREE-POSITION RECURRENCE PHASE 2 v028bw',
         "console banner"),
        ('if not plan.get("next_gate", {}).get("matched_recurrence_phase1_may_run"):\n'
         '        print("FAIL v028bs phase1 gate not enabled")\n'
         '        return 3',
         'if int(plan.get("cumulative_selected_exposures", 256)) != 256:\n'
         '        print("FAIL v028bv cumulative selection is not 256 exposures")\n'
         '        return 3',
         "plan gate"),
        ('"phase_exposure_seq": int(q["phase_exposure_seq"]),',
         '"phase2_exposure_seq": int(q["phase2_exposure_seq"]),',
         "phase exposure sequence"),
        ('"selection_rank": int(q["selection_rank"]),',
         '"cumulative_selection_rank": int(q["cumulative_selection_rank"]),',
         "cumulative selection rank"),
        ('"This is a 64-exposure matched recurrence calibration pass. A fitted "',
         '"This is the 192-new-exposure phase-2 matched recurrence pass, "\n'
         '            "expanding cumulative coverage from 64 to 256 exposures. A fitted "',
         "interpretive boundary"),
        ('"matched_recurrence_phase1_interpretation_may_run": True,\n'
         '            "matched_recurrence_expansion_plan_may_be_built": True,',
         '"matched_recurrence_phase2_interpretation_may_run": True,',
         "next gate"),
        ('# ORDER 01 — Matched Three-Position Recurrence Phase 1 v028bt',
         '# ORDER 01 — Matched Three-Position Recurrence Phase 2 v028bw',
         "Markdown title"),
    )
    for old, new, label in substitutions:
        text = replace_once(text, old, new, label)

    input_loop = '''    for p in (PLAN, QUEUE):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2
'''
    hashed_input_loop = input_loop + '''
    import hashlib
    if hashlib.sha256(PLAN.read_bytes()).hexdigest() != EXPECTED_PLAN_SHA256:
        print("FAIL frozen v028bv plan SHA256 changed")
        return 3
    if hashlib.sha256(QUEUE.read_bytes()).hexdigest() != EXPECTED_QUEUE_SHA256:
        print("FAIL frozen v028bv phase-2 queue SHA256 changed")
        return 3
'''
    text = replace_once(text, input_loop, hashed_input_loop, "frozen input hash guards")

    # The stage identifier occurs once in the checkpoint and once in the output.
    old_id = '"stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE1_V028BT"'
    new_id = '"stage": "ORDER01_DASCH_MATCHED_RECURRENCE_PHASE2_V028BW"'
    if text.count(old_id) != 2:
        refuse(f"stage identifiers: expected exactly two source fragments, found {text.count(old_id)}")
    text = text.replace(old_id, new_id)

    derived_functions = function_sources(text)
    for name in PRESERVED_FUNCTIONS:
        if original_functions[name] != derived_functions[name]:
            refuse(f"derived stage changed preserved function {name}")

    ast.parse(text)
    return text


def add_registry_stage(text: str) -> str:
    if f'stage_id="{STAGE_ID}"' in text:
        return text
    marker = "\n]\n\ndef by_id():"
    if text.count(marker) != 1:
        refuse("registry closing marker is not unique")
    block = '''

    StageContract(
        stage_id="dasch_matched_recurrence_phase2_v028bw",
        title="Execute 192-new-exposure matched platephot recurrence expansion",
        script="automation/stages/execute_matched_recurrence_phase2_v028bw.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_256_plan_v028bv.json",
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase2_queue_v028bv.csv",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase2_v028bw.json",
        ),
        dependencies=("dasch_matched_recurrence_256_plan_v028bv",),
        network_access=True,
        notes="576 checkpointed DASCH public platephot requests over 192 new matched exposures; no pixels/detector/state mutation.",
    ),
'''
    return text.replace(marker, block + marker, 1)


def backup_inputs() -> None:
    BACKUP.mkdir(parents=True, exist_ok=False)
    for path in (SOURCE, REGISTRY, INIT, RUNNER):
        shutil.copy2(path, BACKUP / path.name)


def compile_and_regress() -> None:
    for path in (TARGET, REGISTRY, INIT, RUNNER):
        py_compile.compile(str(path), doraise=True)
    proc = subprocess.run(
        [sys.executable, "-c",
         "import automation; from automation.registry_order01 import by_id; "
         "assert automation.__version__ == '0.3.2'; "
         "assert 'dasch_matched_recurrence_phase2_v028bw' in by_id()"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        refuse("registry/import regression failed:\n" + proc.stdout + proc.stderr)


def main() -> int:
    print("=" * 112)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.2 — MATCHED RECURRENCE PHASE-2 EXECUTOR")
    print("=" * 112)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. NO SCIENTIFIC OUTPUTS OR CANDIDATE STATE ARE CHANGED.")
    print("Derives the exact v028bt caller/parser and registers a separate 576-request checkpointed stage.\n")

    validate_inputs()
    source_text = SOURCE.read_text(encoding="utf-8")
    target_text = derive_stage(source_text)
    registry_text = add_registry_stage(REGISTRY.read_text(encoding="utf-8"))

    backup_inputs()
    TARGET.write_text(target_text, encoding="utf-8", newline="\n")
    REGISTRY.write_text(registry_text, encoding="utf-8", newline="\n")
    INIT.write_text(f'__version__ = "{VERSION}"\n', encoding="utf-8", newline="\n")

    runner_text = RUNNER.read_text(encoding="utf-8")
    runner_text = re.sub(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        f"Transient automation v{VERSION} - Order01 registry status",
        runner_text,
    )
    RUNNER.write_text(runner_text, encoding="utf-8", newline="\n")

    compile_and_regress()

    manifest = {
        "upgrade": "v0.3.2_matched_recurrence_phase2_executor",
        "installed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "target": str(TARGET.relative_to(ROOT)),
        "target_sha256": hashlib.sha256(target_text.encode("utf-8")).hexdigest(),
        "preserved_function_sha256": {
            k: sha256_text(v) for k, v in function_sources(source_text).items()
        },
        "queue": str(QUEUE.relative_to(ROOT)),
        "expected_requests": 576,
        "expected_new_exposures": 192,
        "guards": {
            "network_access_during_upgrade": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "backup": str(BACKUP.relative_to(ROOT)),
    }
    manifest_path = ROOT / "research" / "TRANSIENT_AUTOMATION_V032_PHASE2_EXECUTOR_UPGRADE.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Queue validation: PASS (576 requests / 192 exposures / three frozen targets)")
    print("Caller/parser preservation: PASS")
    print("Compile/import/registry regression: PASS")
    print(f"Installed stage: {TARGET}")
    print(f"Backup: {BACKUP}")
    print(f"Manifest: {manifest_path}")
    print("\nUPGRADE STATUS: PASS")
    print("\nNext commands:")
    print('  & ".\\.venv\\Scripts\\python.exe" -m automation.runner status')
    print('  & ".\\.venv\\Scripts\\python.exe" -m automation.runner run-next --allow-network')
    print('  & ".\\.venv\\Scripts\\python.exe" -m automation.runner verify-stage --stage dasch_matched_recurrence_phase2_v028bw')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
