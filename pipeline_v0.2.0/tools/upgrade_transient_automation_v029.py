#!/usr/bin/env python3
"""Install the hash-pinned project accounting freeze stage."""
from __future__ import annotations

import hashlib
import py_compile
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
R = ROOT / "results"
O1 = R / "order01_native_full_v028"
O61 = R / "order61_native_full_v028"
INPUTS = (
    O1 / "order01_whole_pair_report.json",
    O1 / "order01_overall_evidence_synthesis_v028by.json",
    O61 / "order61_whole_pair_report.json",
    O61 / "order61_branch_c_candidate462_validation_v028.json",
    O61 / "order61_branch_c_candidate462_recurrence256_v028.json",
    O61 / "order61_branch_c_candidate462_footprint_directional_controls_v028.json",
    O61 / "order61_branch_c_candidate462_physical_dynamics_v028d.json",
    R / "PAIR13623_BI05607_REVALIDATED_CLOSURE_2026-08-20.md",
)
TARGET = ROOT / "automation" / "stages" / "freeze_project_accounting_v028bz.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
RUNNER = ROOT / "automation" / "runner.py"
VERSION = "0.3.5"
STAGE_ID = "project_accounting_freeze_v028bz"
BACKUP = ROOT / "automation" / "backups" / (
    "pre_v029_project_accounting_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)


def refuse(message: str) -> None:
    raise SystemExit("REFUSING: " + message)


STAGE = r'''#!/usr/bin/env python3
"""Freeze project-wide accounting without changing scientific evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "results"
O1 = R / "order01_native_full_v028"
O61 = R / "order61_native_full_v028"
FILES = (
    O1 / "order01_whole_pair_report.json",
    O1 / "order01_overall_evidence_synthesis_v028by.json",
    O61 / "order61_whole_pair_report.json",
    O61 / "order61_branch_c_candidate462_validation_v028.json",
    O61 / "order61_branch_c_candidate462_recurrence256_v028.json",
    O61 / "order61_branch_c_candidate462_footprint_directional_controls_v028.json",
    O61 / "order61_branch_c_candidate462_physical_dynamics_v028d.json",
    R / "PAIR13623_BI05607_REVALIDATED_CLOSURE_2026-08-20.md",
)
EXPECTED = __EXPECTED_HASHES__
OUT_JSON = R / "project_accounting_freeze_v028bz.json"
OUT_MD = R / "PROJECT_ACCOUNTING_FREEZE_V028BZ.md"


def main():
    print("=" * 120)
    print("PROJECT ACCOUNTING FREEZE v028bz")
    print("=" * 120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    loaded = {}
    for path in FILES:
        if not path.is_file():
            raise RuntimeError(f"missing frozen input: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != EXPECTED[path.name]:
            raise RuntimeError(f"REFUSING: frozen input hash changed: {path.name}")
        if path.suffix.lower() == ".json":
            loaded[path.name] = json.loads(path.read_text(encoding="utf-8"))

    o1_pair = loaded["order01_whole_pair_report.json"]
    o1_final = loaded["order01_overall_evidence_synthesis_v028by.json"]
    o61_pair = loaded["order61_whole_pair_report.json"]
    validation = loaded["order61_branch_c_candidate462_validation_v028.json"]
    recurrence = loaded["order61_branch_c_candidate462_recurrence256_v028.json"]
    directional = loaded["order61_branch_c_candidate462_footprint_directional_controls_v028.json"]
    dynamics = loaded["order61_branch_c_candidate462_physical_dynamics_v028d.json"]

    if o1_pair["raw_le_3arcsec"] != 38 or o61_pair["raw_le_3arcsec"] != 23:
        raise RuntimeError("direct raw-match counts changed")
    if o1_final["scope_correction"]["active_two_observatory_candidates"] != 0:
        raise RuntimeError("Order-01 closure changed")
    if validation["disposition"] != "BRANCH_C_20_NEW_COUNTERPART_SURVIVES_STATIC_AND_MATCHED_PEER_MORPHOLOGY":
        raise RuntimeError("candidate-462 validation changed")
    if recurrence["summary"]["disposition"] != "NO_RECURRENCE_IN_256_BLIND_INDEPENDENT_PLATES":
        raise RuntimeError("candidate-462 recurrence changed")
    if directional["full_grid"]["common_support_empirical_p"] != 3/97:
        raise RuntimeError("candidate-462 directional full-grid control changed")
    if dynamics["candidate_promoted"] or dynamics["candidate_deleted"]:
        raise RuntimeError("candidate-462 state changed")

    result = {
        "stage": "PROJECT_ACCOUNTING_FREEZE_V028BZ",
        "input_sha256": EXPECTED,
        "completed_pair_investigations": [
            {"label": "Order 01", "sources": ["Palomar POSS-I", "Harvard DASCH"],
             "overlap_minutes": 58.0, "raw_direct_matches_le_3arcsec": 38,
             "confirmed_direct_two_observatory_survivors": 0},
            {"label": "Order 61", "sources": ["Palomar POSS-I", "Harvard DASCH"],
             "overlap_minutes": 45.0, "raw_direct_matches_le_3arcsec": 23,
             "confirmed_direct_two_observatory_survivors_documented": 0},
            {"label": "APPLAUSE 13623 / DASCH bi05607", "sources": ["Hamburg APPLAUSE", "Harvard DASCH"],
             "overlap_minutes": 40.0, "hamburg_targets_verified": 311,
             "confirmed_direct_two_observatory_survivors": 0},
        ],
        "direct_match_accounting": {
            "poss_dasch_raw_matches_le_3arcsec": 61,
            "confirmed_direct_two_observatory_transients": 0,
            "hamburg_dasch_targets_verified": 311,
            "hamburg_dasch_strict_matches": 0,
            "warning": "The 311 Hamburg targets and 61 raw POSS-DASCH matches are different denominators and must not be added as equivalent candidates.",
        },
        "candidate462": {
            "category": "EXPLORATORY_MOVING_OBJECT_GEOMETRY_HYPOTHESIS_NOT_A_DIRECT_POSITIONAL_MATCH",
            "state": "PRESERVED_NOT_PROMOTED_NOT_DELETED",
            "static_and_morphology_gate": "SURVIVED",
            "recurrence_5arcsec": "ZERO_OF_256",
            "directional_full_grid_empirical_p": directional["full_grid"]["common_support_empirical_p"],
            "directional_annulus_empirical_p": directional["candidate_specific_annulus"]["finite_sample_empirical_directional_p"],
            "formal_discovery_probability": False,
            "same_time_flash_assumption_required": True,
            "unique_orbit_established": False,
            "best_bound_nonimpacting_time_to_3arcsec_s": dynamics["best_bound_state"]["shorter_time_to_3arcsec_s"],
            "ideal_single_flat_facet_same_instant_supported": dynamics["illumination_reflection_geometry"]["ideal_single_flat_facet_same_instant_can_cover_both_observers_with_reflected_solar_disk"],
            "classification": "INTERESTING_EXPLORATORY_LEAD_NOT_CONFIRMED_MULTI_SOURCE_TRANSIENT",
        },
        "overall_classification": "ZERO_CONFIRMED_DIRECT_TWO_OBSERVATORY_TRANSIENTS_CANDIDATE462_RETAINED_AS_EXPLORATORY_TRAJECTORY_LEAD",
        "next_action": "INVENTORY_AND_PROCESS_ALREADY_IDENTIFIED_UNANALYSED_PAIRS_BEFORE_ADDING_OBSERVATORY_SOURCES",
        "scope_boundary": "This freezes only the three completed pair investigations represented by the pinned inputs. It does not claim that every identified pair in the wider candidate manifest has been processed or that all public plate archives have been searched.",
        "next_gate": {"existing_identified_pair_inventory_may_run": True,
                      "additional_observatory_pair_expansion_may_run_before_inventory": False},
        "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
    }
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(f"""# Project Accounting Freeze v028bz

## Frozen result

- Completed pair investigations: 3.
- Raw direct POSS-DASCH matches within 3 arcsec: 61.
- Confirmed direct two-observatory transients: 0.
- Hamburg targets checked against Harvard: 311; strict matches: 0.
- Candidate 462 remains an exploratory moving-object lead, not a confirmed multi-source transient.

## Next action

Inventory and analyse already identified unprocessed pairs before adding further observatory sources.

## Boundary

{result['scope_boundary']}
""", encoding="utf-8")
    print("Completed pair investigations: 3")
    print("Confirmed direct two-observatory transients: 0")
    print("Candidate 462: retained exploratory trajectory lead")
    print("Next: inventory existing identified pairs")
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def add_registry(text: str) -> str:
    if f'stage_id="{STAGE_ID}"' in text:
        return text
    marker = "\n]\n\ndef by_id():"
    if text.count(marker) != 1:
        refuse("registry closing marker is not unique")
    block = r'''

    StageContract(
        stage_id="project_accounting_freeze_v028bz",
        title="Freeze project-wide completed-pair accounting",
        script="automation/stages/freeze_project_accounting_v028bz.py",
        requires=(
            "results/order01_native_full_v028/order01_whole_pair_report.json",
            "results/order01_native_full_v028/order01_overall_evidence_synthesis_v028by.json",
            "results/order61_native_full_v028/order61_whole_pair_report.json",
            "results/order61_native_full_v028/order61_branch_c_candidate462_validation_v028.json",
            "results/order61_native_full_v028/order61_branch_c_candidate462_recurrence256_v028.json",
            "results/order61_native_full_v028/order61_branch_c_candidate462_footprint_directional_controls_v028.json",
            "results/order61_native_full_v028/order61_branch_c_candidate462_physical_dynamics_v028d.json",
            "results/PAIR13623_BI05607_REVALIDATED_CLOSURE_2026-08-20.md",
        ),
        produces=("results/project_accounting_freeze_v028bz.json",),
        dependencies=("order01_overall_evidence_synthesis_v028by",),
        network_access=False,
        notes="Hash-pinned completed-pair accounting; no evidence or candidate-state mutation.",
    ),
'''
    return text.replace(marker, block + marker, 1)


def main() -> int:
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.2.9 — PROJECT ACCOUNTING FREEZE")
    print("=" * 120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    for path in (*INPUTS, REGISTRY, INIT, RUNNER):
        if not path.is_file(): refuse(f"required file missing: {path}")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS}
    stage = STAGE.replace("__EXPECTED_HASHES__", repr(hashes))
    compile(stage, str(TARGET), "exec")
    BACKUP.mkdir(parents=True, exist_ok=False)
    for path in (REGISTRY, INIT, RUNNER): shutil.copy2(path, BACKUP / path.name)
    TARGET.write_text(stage, encoding="utf-8")
    REGISTRY.write_text(add_registry(REGISTRY.read_text(encoding="utf-8")), encoding="utf-8")
    INIT.write_text(f'__version__ = "{VERSION}"\n', encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    runner, count = re.subn(r"Transient automation v\d+\.\d+\.\d+", f"Transient automation v{VERSION}", runner)
    if count == 0: refuse("runner version banner not found")
    RUNNER.write_text(runner, encoding="utf-8")
    for path in (TARGET, REGISTRY, INIT, RUNNER): py_compile.compile(str(path), doraise=True)
    subprocess.run([sys.executable, "-c", "import automation; from automation.registry_order01 import by_id; "
                    f"assert automation.__version__ == '{VERSION}'; assert '{STAGE_ID}' in by_id()"], cwd=ROOT, check=True)
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {BACKUP}")
    print("\nUPGRADE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
