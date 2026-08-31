#!/usr/bin/env python3
from __future__ import annotations

import ast
import py_compile
import re
import shutil
from pathlib import Path

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
INIT = AUTO / "__init__.py"
BACKUP = AUTO / "backups" / "pre_v022a_repair"

REFERENCE_STAGE = "dasch_platephot_live_calibration_v028bd"
TARGET_STAGE = "dasch_science25_analogue_catalog_provenance_v028bq"


def stage_calls(text):
    tree = ast.parse(text)
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        fn = node.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name != "StageContract":
            continue

        stage_id = None
        for kw in node.keywords:
            if kw.arg == "stage_id" and isinstance(kw.value, ast.Constant):
                stage_id = kw.value.value
                break
        if stage_id:
            found[str(stage_id)] = node
    return found


def keyword_source(text, node, keyword_name):
    for kw in node.keywords:
        if kw.arg == keyword_name:
            return ast.get_source_segment(text, kw)
    return None


def network_keyword_from_reference(text, node):
    hits = []
    for kw in node.keywords:
        if kw.arg and "network" in kw.arg.lower():
            src = ast.get_source_segment(text, kw)
            hits.append((kw.arg, src))
    if len(hits) != 1:
        raise RuntimeError(
            f"Expected exactly one network-related StageContract keyword on "
            f"{REFERENCE_STAGE}; found {hits}"
        )
    return hits[0]


def replace_target_network_keyword(text, target_node, good_kw_name, good_kw_src):
    # Work only inside the exact target StageContract source range.
    lines = text.splitlines(keepends=True)
    start = target_node.lineno - 1
    end = target_node.end_lineno
    block = "".join(lines[start:end])

    if "network_required=True" not in block:
        # If an earlier repair partially succeeded, accept the exact good keyword.
        if re.search(rf"\b{re.escape(good_kw_name)}\s*=", block):
            return text, "target already uses the reference network keyword"
        raise RuntimeError(
            "Target StageContract block does not contain network_required=True "
            "and does not already contain the reference network keyword."
        )

    # Preserve indentation from the bad line while copying the exact keyword/value.
    bad_pat = re.compile(
        r"(?m)^(?P<indent>\s*)network_required\s*=\s*True\s*,\s*$"
    )
    m = bad_pat.search(block)
    if not m:
        raise RuntimeError("Could not locate network_required=True line in target block")

    replacement = f"{m.group('indent')}{good_kw_src},"
    new_block = bad_pat.sub(replacement, block, count=1)

    out = "".join(lines[:start]) + new_block + "".join(lines[end:])
    ast.parse(out)
    return out, f"replaced network_required=True with {good_kw_src}"


def main():
    print("=" * 112)
    print("TRANSIENT AUTOMATION REPAIR v0.2.2a — RESTORE STAGECONTRACT NETWORK GATE")
    print("=" * 112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ.")
    print("No scientific outputs or candidate state are changed.\n")

    if not REGISTRY.is_file():
        print(f"FAIL missing registry: {REGISTRY}")
        return 2
    if not RUNNER.is_file():
        print(f"FAIL missing runner: {RUNNER}")
        return 2

    text = REGISTRY.read_text(encoding="utf-8")
    calls = stage_calls(text)

    if REFERENCE_STAGE not in calls:
        print(f"FAIL reference network stage not found: {REFERENCE_STAGE}")
        return 3
    if TARGET_STAGE not in calls:
        print(f"FAIL target stage not found: {TARGET_STAGE}")
        return 3

    good_name, good_src = network_keyword_from_reference(
        text, calls[REFERENCE_STAGE]
    )
    print(
        f"Reference network contract from {REFERENCE_STAGE}: "
        f"{good_src}"
    )

    # Show the target's currently declared keywords before mutation.
    target_keywords = [kw.arg for kw in calls[TARGET_STAGE].keywords]
    print(f"Target keywords before repair: {target_keywords}")

    BACKUP.mkdir(parents=True, exist_ok=True)
    backup_registry = BACKUP / "registry_order01.py"
    if not backup_registry.exists():
        shutil.copy2(REGISTRY, backup_registry)
    if INIT.is_file() and not (BACKUP / "__init__.py").exists():
        shutil.copy2(INIT, BACKUP / "__init__.py")
    if not (BACKUP / "runner.py").exists():
        shutil.copy2(RUNNER, BACKUP / "runner.py")

    repaired, note = replace_target_network_keyword(
        text, calls[TARGET_STAGE], good_name, good_src
    )
    REGISTRY.write_text(repaired, encoding="utf-8")
    print(f"Registry repair: {note}")

    # Structural reparse and exact target validation.
    reparsed = REGISTRY.read_text(encoding="utf-8")
    calls2 = stage_calls(reparsed)
    target2 = calls2[TARGET_STAGE]
    kw_names = [kw.arg for kw in target2.keywords]

    if "network_required" in kw_names:
        print("FAIL unsupported network_required keyword still present")
        return 4
    if good_name not in kw_names:
        print(f"FAIL reference network keyword {good_name!r} missing after repair")
        return 4

    print(f"Target keywords after repair: {kw_names}")

    # Update visible automation version only after registry is structurally sound.
    runner = RUNNER.read_text(encoding="utf-8")
    runner = re.sub(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.2.3 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    INIT.write_text('__version__ = "0.2.3"\n', encoding="utf-8")

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
        print("\nREPAIR STATUS: FAIL")
        return 5

    # Import test is the critical regression for the exact failure the user hit.
    try:
        import importlib.util
        import sys

        # Add root so package-relative imports work.
        sys.path.insert(0, str(ROOT))
        import automation.registry_order01 as reg
        import automation.contracts as contracts

        target = next(
            s for s in reg.ORDER01_STAGES
            if getattr(s, "stage_id", None) == TARGET_STAGE
        )
        reference = next(
            s for s in reg.ORDER01_STAGES
            if getattr(s, "stage_id", None) == REFERENCE_STAGE
        )

        ref_value = getattr(reference, good_name)
        target_value = getattr(target, good_name)
        if target_value != ref_value:
            raise RuntimeError(
                f"network-gate value mismatch: reference={ref_value!r} "
                f"target={target_value!r}"
            )

        print(
            f"\nRegistry import regression: PASS "
            f"({good_name}={target_value!r})"
        )
    except Exception as exc:
        print(f"\nRegistry import regression: FAIL: {type(exc).__name__}: {exc}")
        return 6

    print("\nREPAIR STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_analogue_catalog_provenance_v028bq'
    )
    print("\nDo not rerun upgrade_transient_automation_v022.py after this repair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
