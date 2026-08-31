from __future__ import annotations

"""Install the Order-11 empirical-background and follow-up-priority stage."""

from pathlib import Path
from datetime import datetime, timezone
import ast
import re
import shutil


ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "analyse_order11_raw_coincidences_v028cm.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"


STAGE_SOURCE = r'''from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import statistics

import numpy as np
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "results" / "order11_native_full_v028"
REPORT = BASE / "order11_whole_pair_report.json"
RAW = BASE / "order11_raw_coincidences.csv"
POSS = BASE / "order11_poss_native_candidates.csv"
DASCH = BASE / "order11_dasch_native_candidates.csv"
OUTDIR = ROOT / "results" / "order11_coincidence_controls_v028cm"
OUTJSON = OUTDIR / "order11_coincidence_background_v028cm.json"
OUTCSV = OUTDIR / "order11_followup_priority_v028cm.csv"

EXPECTED = {
    REPORT: "115522a59d041e2a4f8c1145faa39fe22610490a723184112b5fc8f1a384d7fb",
    RAW: "4498c7a1eaa3ba94049dc1479c68269a77f510cdb997ed1cc9ec4a51386d6456",
    POSS: "40a3931615e6cd2ceb5b7a556b094608a6fdb373454ad5626a5f6a6ebe84ba66",
    DASCH: "ffc5d88ddd36dfab9033fc3f7812a8e750b2559224ddd6df62fb1ac9232cff07",
}
DX = (-120, -90, -60, -45, -30, 30, 45, 60, 90, 120)
DY = (-120, -60, -30, 30, 60, 120)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rows(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def xyz(ra, dec):
    ra = np.deg2rad(np.asarray(ra, dtype=float))
    dec = np.deg2rad(np.asarray(dec, dtype=float))
    c = np.cos(dec)
    return np.c_[c * np.cos(ra), c * np.sin(ra), np.sin(dec)]


def main():
    print("=" * 100)
    print("ORDER 11 — RAW-COINCIDENCE EMPIRICAL BACKGROUND AND FOLLOW-UP QUEUE v028cm")
    print("=" * 100)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"REFUSING: missing or changed frozen input: {path}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    if report.get("status") != "COMPLETE" or report.get("canonical_order") != 11:
        raise RuntimeError("REFUSING: Order-11 complete report identity/status failed")
    raw, poss, dasch = rows(RAW), rows(POSS), rows(DASCH)
    if (len(raw), len(poss), len(dasch)) != (125, 340100, 1471):
        raise RuntimeError("REFUSING: frozen catalogue row counts changed")

    pra = np.array([float(r["ra_deg"]) for r in poss])
    pde = np.array([float(r["dec_deg"]) for r in poss])
    dra = np.array([float(r["ra_deg"]) for r in dasch])
    dde = np.array([float(r["dec_deg"]) for r in dasch])
    tree = cKDTree(xyz(pra, pde))

    def pair_count(ra, dec, arcsec):
        chord = 2 * math.sin(math.radians(arcsec / 3600) / 2)
        return int(sum(map(len, tree.query_ball_point(xyz(ra, dec), chord))))

    observed = {"3": pair_count(dra, dde, 3), "10": pair_count(dra, dde, 10)}
    shifted = {"3": [], "10": []}
    trials = []
    for dx in DX:
        for dy in DY:
            sra = dra + dx / 3600 / np.cos(np.deg2rad(dde))
            sde = dde + dy / 3600
            c3, c10 = pair_count(sra, sde, 3), pair_count(sra, sde, 10)
            shifted["3"].append(c3); shifted["10"].append(c10)
            trials.append({"ra_shift_arcsec": dx, "dec_shift_arcsec": dy,
                           "pairs_le_3arcsec": c3, "pairs_le_10arcsec": c10})

    controls = {}
    for radius in ("3", "10"):
        vals, obs = shifted[radius], observed[radius]
        controls[radius] = {
            "observed_pairs": obs,
            "shift_trial_count": len(vals),
            "shift_mean": statistics.mean(vals),
            "shift_median": statistics.median(vals),
            "shift_min": min(vals), "shift_max": max(vals),
            "shift_population_sd": statistics.pstdev(vals),
            "trials_ge_observed": sum(v >= obs for v in vals),
            "empirical_upper_tail_p_with_pseudocount":
                (1 + sum(v >= obs for v in vals)) / (1 + len(vals)),
        }

    ppos = sum(r["polarity"] == "1" for r in poss) / len(poss)
    dpos = sum(r["polarity"] == "1" for r in dasch) / len(dasch)
    expected_same = ppos * dpos + (1 - ppos) * (1 - dpos)
    observed_same = sum(r["poss_polarity"] == r["dasch_polarity"] for r in raw) / len(raw)

    queue = []
    for r in raw:
        sep = float(r["separation_arcsec"]); ds = float(r["dasch_snr"])
        same = r["poss_polarity"] == r["dasch_polarity"]
        if sep <= 3 and same and ds >= 6: tier = "A"
        elif sep <= 3 and same: tier = "B"
        elif sep <= 3: tier = "C"
        else: tier = "D"
        q = dict(r)
        q.update({"followup_tier": tier, "same_polarity": same,
                  "population_excess_supported": False,
                  "classification": "UNCLASSIFIED_RAW_COINCIDENCE"})
        queue.append(q)
    queue.sort(key=lambda r: (r["followup_tier"], -float(r["dasch_snr"]),
                              -float(r["poss_snr"]), float(r["separation_arcsec"])))
    for i, r in enumerate(queue, 1): r["followup_rank"] = i

    OUTDIR.mkdir(parents=True, exist_ok=True)
    fields = ["followup_rank", "followup_tier"] + list(raw[0].keys()) + [
        "same_polarity", "population_excess_supported", "classification"]
    with OUTCSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(queue)

    tier_counts = {t: sum(r["followup_tier"] == t for r in queue) for t in "ABCD"}
    result = {
        "status": "COMPLETE", "canonical_order": 11,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "guards": {"network_access": False, "science_pixels_read": False,
                   "non_science_pixels_read": False, "transient_detector_rerun": False,
                   "candidate_state_mutation": False},
        "frozen_input_sha256": {str(k.relative_to(ROOT)): v for k, v in EXPECTED.items()},
        "counts": {"raw_pairs": len(raw), "poss_candidates": len(poss),
                   "dasch_candidates": len(dasch), "tiers": tier_counts},
        "shift_design": {"ra_offsets_arcsec": DX, "dec_offsets_arcsec": DY,
                         "trial_count": len(trials), "trials": trials},
        "empirical_controls": controls,
        "polarity_control": {"poss_positive_fraction": ppos,
                             "dasch_positive_fraction": dpos,
                             "expected_same_polarity_fraction": expected_same,
                             "observed_same_polarity_fraction": observed_same},
        "interpretation": {
            "population_level_excess": False,
            "statement": "Observed 3-arcsec and 10-arcsec pair counts do not exceed shifted-coordinate background.",
            "candidate_effect": "No individual raw coincidence is promoted or rejected by this population control.",
            "next_step": "Catalogue, local-registration, morphology and native-cutout controls in follow-up order.",
        },
        "top_priority": queue[0], "queue_csv": str(OUTCSV.relative_to(ROOT)),
    }
    OUTJSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Observed <=3 arcsec: {observed['3']}; shifted mean: {controls['3']['shift_mean']:.3f}")
    print(f"Observed <=10 arcsec: {observed['10']}; shifted mean: {controls['10']['shift_mean']:.3f}")
    print(f"Polarity observed/expected same: {observed_same:.4f}/{expected_same:.4f}")
    print(f"Follow-up tiers: {tier_counts}")
    print(f"Top priority: raw match {queue[0]['match_index']}; DASCH SNR={float(queue[0]['dasch_snr']):.2f}")
    print(f"Outputs: {OUTJSON}, {OUTCSV}")
    print("STAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


CONTRACT = '''    StageContract(
        stage_id="order11_coincidence_background_v028cm",
        title="Order-11 shifted-coordinate background and follow-up priority queue",
        script="automation/stages/analyse_order11_raw_coincidences_v028cm.py",
        requires=(
            "results/order11_native_full_v028/order11_whole_pair_report.json",
            "results/order11_native_full_v028/order11_raw_coincidences.csv",
            "results/order11_native_full_v028/order11_poss_native_candidates.csv",
            "results/order11_native_full_v028/order11_dasch_native_candidates.csv",
        ),
        produces=(
            "results/order11_coincidence_controls_v028cm/order11_coincidence_background_v028cm.json",
            "results/order11_coincidence_controls_v028cm/order11_followup_priority_v028cm.csv",
        ),
        dependencies=("order11_whole_native_execution_v028cl",),
        notes="Metadata-only empirical shifted-coordinate background; ranks but does not classify or mutate candidates.",
    ),
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.4.1 — ORDER-11 COINCIDENCE BACKGROUND")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for p in (REGISTRY, INIT):
        if not p.is_file():
            raise RuntimeError(f"Missing required file: {p}")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    registry = REGISTRY.read_text(encoding="utf-8-sig")
    if "order11_coincidence_background_v028cm" in registry:
        raise RuntimeError("REFUSING: v028cm is already registered")
    marker = "]\n\ndef by_id()"
    if marker not in registry:
        raise RuntimeError("REFUSING: registry insertion marker not found")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v041_order11_background_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    if STAGE.exists(): shutil.copy2(STAGE, backup / STAGE.name)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_SOURCE, encoding="utf-8")
    REGISTRY.write_text(registry.replace(marker, "\n" + CONTRACT + marker, 1), encoding="utf-8")
    init = INIT.read_text(encoding="utf-8-sig")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.4.1"', init, count=1)
    INIT.write_text(init, encoding="utf-8")
    ast.parse(STAGE.read_text(encoding="utf-8"), filename=str(STAGE))
    ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
    print("Installed stage: order11_coincidence_background_v028cm")
    print(f"Backup: {backup}")
    print("\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
