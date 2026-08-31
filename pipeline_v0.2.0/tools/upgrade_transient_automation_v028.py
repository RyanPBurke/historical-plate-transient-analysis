#!/usr/bin/env python3
"""Install the hash-pinned Order-01 overall evidence synthesis stage."""
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
BASE = ROOT / "results" / "order01_native_full_v028"
CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
PHENOTYPE = BASE / "order01_dasch_platewide_phenotype_synthesis_v028bm.json"
RECURRENCE = BASE / "order01_dasch_matched_recurrence_256_interpretation_v028bx.json"
TARGET = ROOT / "automation" / "stages" / "synthesize_order01_overall_evidence_v028by.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
RUNNER = ROOT / "automation" / "runner.py"
VERSION = "0.3.4"
STAGE_ID = "order01_overall_evidence_synthesis_v028by"
BACKUP = ROOT / "automation" / "backups" / (
    "pre_v028_order01_synthesis_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)


def refuse(message: str) -> None:
    raise SystemExit("REFUSING: " + message)


STAGE = r'''#!/usr/bin/env python3
"""Combine the frozen Order-01 pair closure and later DASCH-only evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "results" / "order01_native_full_v028"
CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
PHENOTYPE = BASE / "order01_dasch_platewide_phenotype_synthesis_v028bm.json"
RECURRENCE = BASE / "order01_dasch_matched_recurrence_256_interpretation_v028bx.json"
OUT_JSON = BASE / "order01_overall_evidence_synthesis_v028by.json"
OUT_MD = BASE / "ORDER01_OVERALL_EVIDENCE_SYNTHESIS_V028BY.md"
EXPECTED = {
    CLOSURE.name: "__CLOSURE_SHA__",
    PHENOTYPE.name: "__PHENOTYPE_SHA__",
    RECURRENCE.name: "__RECURRENCE_SHA__",
}


def main():
    print("=" * 120)
    print("ORDER 01 — OVERALL PAIR-CLOSURE AND PRESERVED DASCH-EVIDENCE SYNTHESIS v028by")
    print("=" * 120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    data = {}
    for path in (CLOSURE, PHENOTYPE, RECURRENCE):
        if not path.is_file():
            raise RuntimeError(f"missing frozen input: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != EXPECTED[path.name]:
            raise RuntimeError(f"REFUSING: frozen input hash changed: {path.name}")
        data[path.name] = json.loads(path.read_text(encoding="utf-8"))
    closure, phenotype, recurrence = data[CLOSURE.name], data[PHENOTYPE.name], data[RECURRENCE.name]

    ranks = [int(x["strict_rank"]) for x in closure["all_retired_pair_dispositions"]]
    if ranks != [10, 24, 25, 26, 29, 30]:
        raise RuntimeError(f"unexpected retired rank ledger: {ranks}")
    if closure["order01_viable_two_observatory_transient_pairs_remaining"] != 0:
        raise RuntimeError("closure no longer records zero viable two-observatory pairs")
    if closure["new_active_unresolved_two_observatory_set"] != []:
        raise RuntimeError("closure active pair set is not empty")
    if any(x["dasch_endpoint_disposition"] != "PRESERVED_UNRESOLVED_SINGLE_PLATE_ENDPOINT"
           for x in closure["all_retired_pair_dispositions"]):
        raise RuntimeError("not all DASCH endpoints remain preserved")

    science = phenotype["science_context"]
    if sorted(map(int, science)) != ranks:
        raise RuntimeError("phenotype ranks do not match closure ranks")
    p25 = science["25"]
    if p25["shape_classification"] != "CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD":
        raise RuntimeError("candidate 25 shape classification changed")
    if p25["amplitude_support_status"] != "ABOVE_CONTROL_RANGE":
        raise RuntimeError("candidate 25 amplitude status changed")
    if recurrence["classification"] != "NO_SCIENCE_LE5_RECURRENCE_LOOSE_RATE_CONSISTENT_WITH_MATCHED_CONTROLS":
        raise RuntimeError("candidate 25 recurrence classification changed")

    result = {
        "stage": "ORDER01_OVERALL_EVIDENCE_SYNTHESIS_V028BY",
        "input_sha256": EXPECTED,
        "scope_correction": {
            "active_two_observatory_candidates": 0,
            "retired_two_observatory_pair_ranks": ranks,
            "preserved_unresolved_dasch_single_plate_endpoints": ranks,
            "statement": "The six ranks are preserved DASCH single-plate endpoints, not active two-observatory candidates.",
        },
        "two_observatory_result": {
            "classification": "NO_VIABLE_TWO_OBSERVATORY_ADDED_LIGHT_TRANSIENT_PAIR_REMAINS_IN_ORDER01",
            "reason": "Every frozen pair was retired because its POSS endpoint was adjudicated as non-astrophysical under the physical-image gates.",
            "candidate24_final_poss_mechanism": closure["candidate24_row"]["poss_endpoint_disposition"],
            "candidate24_evidence_strength": closure["candidate24_row"]["evidence_strength"],
        },
        "preserved_dasch_result": {
            "all_six_shape_classifications": {rank: science[str(rank)]["shape_classification"] for rank in ranks},
            "candidate25": {
                "classification": "UNRESOLVED_SINGLE_PLATE_ENDPOINT_UNUSUAL_AMPLITUDE_WITHOUT_RECURRENCE_EXCESS",
                "shape_classification": p25["shape_classification"],
                "amplitude_support_status": p25["amplitude_support_status"],
                "platewide_fraction_at_least_as_close": p25["platewide_fraction_at_least_as_close"],
                "recurrence": recurrence["classification"],
                "science_within_5arcsec": recurrence["comparison"]["science_le_5arcsec"],
                "science_within_10arcsec": recurrence["comparison"]["science_le_10arcsec"],
                "science_exposures": recurrence["comparison"]["science_n"],
                "control_within_10arcsec": recurrence["comparison"]["control_le_10arcsec"],
                "control_exposures": recurrence["comparison"]["control_n"],
            },
        },
        "overall_classification": "ORDER01_TWO_OBSERVATORY_SEARCH_CLOSED_ZERO_SURVIVORS_DASCH_SINGLE_PLATE_ENDPOINTS_PRESERVED",
        "plain_language_conclusion": "Order 01 contains no surviving two-observatory transient. Six DASCH-only detections remain preserved as single-plate evidence. Candidate 25 is unusual in amplitude but has an ordinary source-like shape and no recurrence excess, so it remains unconfirmed.",
        "next_action": "COMPARE_AND_TRIAGE_THE_SIX_PRESERVED_DASCH_SINGLE_PLATE_ENDPOINTS_WITHOUT_REOPENING_RETIRED_PAIRS",
        "interpretive_boundary": "This synthesis does not erase or disprove the DASCH marks. It says that their matched POSS detections do not support a contemporaneous independent two-observatory event. A preserved DASCH endpoint may still merit single-plate study but cannot be called multi-source evidence.",
        "next_gate": {"order01_preserved_dasch_endpoint_comparison_may_run": True,
                      "order01_two_observatory_pair_search_should_reopen": False},
        "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
    }
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(f"""# ORDER 01 — Overall Evidence Synthesis v028by

## Result

**No viable two-observatory transient pair remains in Order 01.**

- Retired pair ranks: {', '.join(map(str, ranks))}.
- All six DASCH endpoints remain preserved as unresolved single-plate detections.
- Candidate 25 has source-like morphology and unusual amplitude.
- Candidate 25 has 0/256 recurrence matches within 5 arcsec and 2/256 within 10 arcsec.
- Matched controls have 5/512 matches within 10 arcsec.

## Plain-language conclusion

{result['plain_language_conclusion']}

## Boundary

{result['interpretive_boundary']}
""", encoding="utf-8")
    print("Two-observatory pairs remaining: 0")
    print("Preserved DASCH single-plate endpoints: 6")
    print("Candidate 25: unusual amplitude, source-like shape, no recurrence excess")
    print(f"\nClassification: {result['overall_classification']}")
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
        stage_id="order01_overall_evidence_synthesis_v028by",
        title="Synthesize Order-01 pair closure and preserved DASCH evidence",
        script="automation/stages/synthesize_order01_overall_evidence_v028by.py",
        requires=(
            "results/order01_native_full_v028/order01_candidate24_final_disposition_and_closure_v028ag.json",
            "results/order01_native_full_v028/order01_dasch_platewide_phenotype_synthesis_v028bm.json",
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_256_interpretation_v028bx.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_overall_evidence_synthesis_v028by.json",
        ),
        dependencies=("order01_closure_v028ag", "dasch_platewide_phenotype_synthesis_v028bm", "dasch_matched_recurrence_256_interpretation_v028bx"),
        network_access=False,
        notes="Hash-pinned evidence synthesis only; preserves pair closure and DASCH-only endpoint distinction.",
    ),
'''
    return text.replace(marker, block + marker, 1)


def main() -> int:
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.2.8 — ORDER-01 OVERALL EVIDENCE SYNTHESIS")
    print("=" * 120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    for path in (CLOSURE, PHENOTYPE, RECURRENCE, REGISTRY, INIT, RUNNER):
        if not path.is_file(): refuse(f"required file missing: {path}")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (CLOSURE, PHENOTYPE, RECURRENCE)}
    stage = (STAGE.replace("__CLOSURE_SHA__", hashes[CLOSURE.name])
                  .replace("__PHENOTYPE_SHA__", hashes[PHENOTYPE.name])
                  .replace("__RECURRENCE_SHA__", hashes[RECURRENCE.name]))
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
    for name, digest in hashes.items(): print(f"Pinned {name}: {digest}")
    print(f"Backup: {BACKUP}")
    print("\nUPGRADE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
