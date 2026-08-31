#!/usr/bin/env python3
"""Install the read-only cumulative 256-exposure recurrence interpretation."""
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
P1 = BASE / "order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json"
P2 = BASE / "order01_dasch_matched_recurrence_phase2_v028bw.json"
TARGET = ROOT / "automation" / "stages" / "interpret_matched_recurrence_256_v028bx.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
RUNNER = ROOT / "automation" / "runner.py"
VERSION = "0.3.3"
STAGE_ID = "dasch_matched_recurrence_256_interpretation_v028bx"
BACKUP = ROOT / "automation" / "backups" / (
    "pre_v027_recurrence_interpretation_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)


def refuse(message: str) -> None:
    raise SystemExit("REFUSING: " + message)


STAGE = r'''#!/usr/bin/env python3
"""Interpret the cumulative 256 matched-exposure recurrence experiment."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "results" / "order01_native_full_v028"
P1 = BASE / "order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json"
P2 = BASE / "order01_dasch_matched_recurrence_phase2_v028bw.json"
OUT_JSON = BASE / "order01_dasch_matched_recurrence_256_interpretation_v028bx.json"
OUT_CSV = BASE / "order01_dasch_matched_recurrence_256_close_hits_v028bx.csv"
OUT_MD = BASE / "ORDER01_DASCH_MATCHED_RECURRENCE_256_INTERPRETATION_V028BX.md"
P1_SHA = "__P1_SHA__"
P2_SHA = "__P2_SHA__"
TARGETS = ("science25", "q0030", "q0344")


def fisher_two_sided(a, b, c, d):
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2
    lo, hi = max(0, k - n2), min(n1, k)
    den = math.comb(n, k)
    def probability(x):
        return math.comb(n1, x) * math.comb(n2, k - x) / den
    observed = probability(a)
    return min(1.0, sum(probability(x) for x in range(lo, hi + 1)
                        if probability(x) <= observed + 1e-15))


def first(mapping, *keys, default=None):
    for key in keys:
        if isinstance(mapping, dict) and key in mapping:
            return mapping[key]
    return default


def main():
    print("=" * 128)
    print("ORDER 01 — CUMULATIVE 256-EXPOSURE MATCHED RECURRENCE INTERPRETATION v028bx")
    print("=" * 128)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    for path, expected in ((P1, P1_SHA), (P2, P2_SHA)):
        if not path.is_file():
            raise RuntimeError(f"missing frozen input: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"REFUSING: frozen input hash changed: {path.name}")
    p1 = json.loads(P1.read_text(encoding="utf-8"))
    p2 = json.loads(P2.read_text(encoding="utf-8"))
    p1_summary = p1.get("target_summary", {})
    p2_summary = p2.get("by_target", p2.get("target_summary", {}))
    cumulative = {}
    for target in TARGETS:
        x, y = p1_summary.get(target, {}), p2_summary.get(target, {})
        n1 = int(first(x, "n", "requests", default=64))
        n2 = int(first(y, "n", "requests", default=192))
        le5 = int(first(x, "le_5_arcsec", "le_5arcsec", "within_5_arcsec", default=0)) + int(first(y, "with_nearest_le_5arcsec", "le_5_arcsec", "le_5arcsec", default=0))
        le10 = int(first(x, "le_10_arcsec", "le_10arcsec", "within_10_arcsec", default=0)) + int(first(y, "with_nearest_le_10arcsec", "le_10_arcsec", "le_10arcsec", default=0))
        if n1 != 64 or n2 != 192:
            raise RuntimeError(f"unexpected sample counts for {target}: {n1}+{n2}")
        cumulative[target] = {"n": n1 + n2, "le_5arcsec": le5, "le_10arcsec": le10,
                              "rate_le_5arcsec": le5/(n1+n2), "rate_le_10arcsec": le10/(n1+n2)}
    if cumulative != {
        "science25": {"n": 256, "le_5arcsec": 0, "le_10arcsec": 2, "rate_le_5arcsec": 0.0, "rate_le_10arcsec": 2/256},
        "q0030": {"n": 256, "le_5arcsec": 1, "le_10arcsec": 3, "rate_le_5arcsec": 1/256, "rate_le_10arcsec": 3/256},
        "q0344": {"n": 256, "le_5arcsec": 0, "le_10arcsec": 2, "rate_le_5arcsec": 0.0, "rate_le_10arcsec": 2/256},
    }:
        raise RuntimeError(f"cumulative frozen counts differ from expected: {cumulative}")

    p1_hits = list(p1.get("close_hits_le_10arcsec", []))
    p2_rows = list(p2.get("results", p2.get("rows", [])))
    p2_hits = [r for r in p2_rows if first(r, "nearest_sep_arcsec") is not None and float(first(r, "nearest_sep_arcsec")) <= 10]
    hits = []
    for phase, rows in ((1, p1_hits), (2, p2_hits)):
        for row in rows:
            raw = row.get("nearest_raw_row") or {}
            hits.append({"phase": phase, "target": first(row, "target"), "plate_id": first(row, "plate_id"),
                         "exposure_identity": first(row, "exposure_identity"), "obs_date_iso": first(row, "obs_date_iso"),
                         "nearest_sep_arcsec": first(row, "nearest_sep_arcsec"),
                         "nearest_magcal_iso": first(row, "nearest_magcal_iso", "nearest_mag", default=raw.get("magcal_iso")),
                         "nearest_limiting_mag_local": first(row, "nearest_limiting_mag_local", "nearest_limiting_mag", default=raw.get("limiting_mag_local")),
                         "nearest_aflags": first(row, "nearest_aflags", default=raw.get("aflags")), "nearest_bflags": first(row, "nearest_bflags", default=raw.get("bflags")),
                         "nearest_reject_flag": first(row, "nearest_reject_flag", default=raw.get("reject_flag")), "nearest_pass_bits": first(row, "nearest_pass_bits", default=raw.get("pass_bits")),
                         "nearest_ellipticity": first(row, "nearest_ellipticity", default=raw.get("ellipticity")), "nearest_fwhm_pix": first(row, "nearest_fwhm_pix", default=raw.get("fwhm_pix"))})
    if len(hits) != 7:
        raise RuntimeError(f"expected seven cumulative <=10 arcsec rows; got {len(hits)}")

    science = cumulative["science25"]
    control_n = cumulative["q0030"]["n"] + cumulative["q0344"]["n"]
    control5 = cumulative["q0030"]["le_5arcsec"] + cumulative["q0344"]["le_5arcsec"]
    control10 = cumulative["q0030"]["le_10arcsec"] + cumulative["q0344"]["le_10arcsec"]
    result = {
        "stage": "ORDER01_DASCH_MATCHED_RECURRENCE_256_INTERPRETATION_V028BX",
        "input_sha256": {P1.name: P1_SHA, P2.name: P2_SHA},
        "cumulative_target_summary": cumulative,
        "close_hits_le_10arcsec": hits,
        "comparison": {
            "science_n": 256, "control_n": control_n,
            "science_le_5arcsec": science["le_5arcsec"], "control_le_5arcsec": control5,
            "science_le_10arcsec": science["le_10arcsec"], "control_le_10arcsec": control10,
            "fisher_two_sided_le_5arcsec": fisher_two_sided(0, 256, control5, control_n-control5),
            "fisher_two_sided_le_10arcsec": fisher_two_sided(2, 254, control10, control_n-control10),
            "control_rate_expected_science_le_10arcsec": control10/control_n*256,
            "zero_event_science_le_5arcsec_95pct_upper_per_exposure": 1 - 0.05**(1/256),
        },
        "quality_observations": [
            "Both science-position <=10 arcsec rows are loose (>8.5 arcsec); one has a nonzero reject_flag.",
            "Four of the six phase-2 <=10 arcsec rows have nonzero reject_flag values.",
            "The sole <=5 arcsec row is a control-position row with ellipticity 0.61 and FWHM 31.39 pixels.",
            "aflags and bflags are retained but not decoded without an authoritative bit-definition table.",
        ],
        "classification": "NO_SCIENCE_LE5_RECURRENCE_LOOSE_RATE_CONSISTENT_WITH_MATCHED_CONTROLS",
        "expansion_recommendation": "OPTIONAL_PUBLICATION_GRADE_BOUND_TIGHTENING_NOT_SIGNAL_FOLLOWUP",
        "interpretive_boundary": "The plates vary in sensitivity, passband and quality, and detections are not independent identically distributed Bernoulli trials. The upper bound is descriptive; this stage does not classify the original transient.",
        "next_gate": {"matched_recurrence_expansion_to_1024_may_be_planned": True,
                      "expansion_is_required_by_current_signal": False},
        "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
    }
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    fields = list(hits[0])
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields); writer.writeheader(); writer.writerows(hits)
    c = result["comparison"]
    OUT_MD.write_text(f"""# ORDER 01 — Cumulative 256-Exposure Matched Recurrence Interpretation v028bx

## Result

**{result["classification"]}**

- Science position: 0/256 within 5 arcsec; 2/256 within 10 arcsec.
- Matched controls: {control5}/{control_n} within 5 arcsec; {control10}/{control_n} within 10 arcsec.
- Fisher exact two-sided p-values: <=5 arcsec {c["fisher_two_sided_le_5arcsec"]:.6g}; <=10 arcsec {c["fisher_two_sided_le_10arcsec"]:.6g}.
- Zero-event descriptive 95% upper bound at <=5 arcsec: {100*c["zero_event_science_le_5arcsec_95pct_upper_per_exposure"]:.3f}% per eligible exposure.

## Decision

Expansion to 1024 is optional for publication-grade bound tightening, not indicated as signal follow-up.

## Boundary

{result["interpretive_boundary"]}
""", encoding="utf-8")
    print("CUMULATIVE SUMMARY")
    for target in TARGETS:
        x = cumulative[target]; print(f"  {target}: n={x['n']} <=5\"={x['le_5arcsec']} <=10\"={x['le_10arcsec']}")
    print(f"\nClassification: {result['classification']}")
    print(f"Expansion: {result['expansion_recommendation']}")
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
        stage_id="dasch_matched_recurrence_256_interpretation_v028bx",
        title="Interpret cumulative 256-exposure matched recurrence evidence",
        script="automation/stages/interpret_matched_recurrence_256_v028bx.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase1_interpretation_v028bu.json",
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_phase2_v028bw.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_matched_recurrence_256_interpretation_v028bx.json",
        ),
        dependencies=("dasch_matched_recurrence_phase2_v028bw",),
        network_access=False,
        notes="Hash-pinned cumulative inference only; no network, pixels, detector rerun, or candidate-state mutation.",
    ),
'''
    return text.replace(marker, block + marker, 1)


def main() -> int:
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.2.7 — CUMULATIVE RECURRENCE INTERPRETATION")
    print("=" * 120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    for path in (P1, P2, REGISTRY, INIT, RUNNER):
        if not path.is_file(): refuse(f"required file missing: {path}")
    p1_sha, p2_sha = hashlib.sha256(P1.read_bytes()).hexdigest(), hashlib.sha256(P2.read_bytes()).hexdigest()
    stage = STAGE.replace("__P1_SHA__", p1_sha).replace("__P2_SHA__", p2_sha)
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
    print(f"Pinned phase-1 SHA256: {p1_sha}")
    print(f"Pinned phase-2 SHA256: {p2_sha}")
    print(f"Backup: {BACKUP}")
    print("\nUPGRADE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
