
from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import shutil

ROOT = Path.cwd()

PREFLIGHT = ROOT / "results" / "wide_census_heavy_preflight_v054.json"
ENDPOINTS = ROOT / "results" / "wide_census_detector_endpoint_plan_v054.csv"
PAIRS = ROOT / "results" / "wide_census_detector_pair_plan_v054.json"
TILES = ROOT / "results" / "wide_census_detector_tile_plan_v054.csv"
DETECTOR = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD = ROOT / "config" / "frozen_method.json"
NATIVE_POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"

OUT_JSON = ROOT / "results" / "wide_census_disk_bounded_execution_contract_v055.json"

EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_OPPS = 33
EXPECTED_ENDPOINTS = 53
EXPECTED_TILES = 6293

PER_TILE_CANDIDATE_META_ALLOWANCE = 2 * 1024**2
FIXED_RESULT_ALLOWANCE = 2 * 1024**3
SAFETY_RESERVE = 8 * 1024**3


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main():
    print("=" * 132)
    print("WIDE CENSUS — DISK-BOUNDED HEAVY EXECUTION CONTRACT v055")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (PREFLIGHT, ENDPOINTS, PAIRS, TILES, DETECTOR, METHOD, NATIVE_POLICY):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing input {p}")

    if sha(DETECTOR) != EXPECTED_DETECTOR_SHA:
        raise RuntimeError("REFUSING: frozen detector changed")
    if sha(METHOD) != EXPECTED_METHOD_SHA:
        raise RuntimeError("REFUSING: frozen method changed")

    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: v054 is not complete")
    if int(pre.get("opportunity_count", -1)) != EXPECTED_OPPS:
        raise RuntimeError("REFUSING: opportunity count changed")
    if int(pre.get("endpoint_count", -1)) != EXPECTED_ENDPOINTS:
        raise RuntimeError("REFUSING: endpoint count changed")
    if int(pre.get("unique_tile_count", -1)) != EXPECTED_TILES:
        raise RuntimeError("REFUSING: tile count changed")

    endpoints = read_csv(ENDPOINTS)
    tiles = read_csv(TILES)
    pairs = json.loads(PAIRS.read_text(encoding="utf-8")).get("pairs", [])

    if len(endpoints) != EXPECTED_ENDPOINTS:
        raise RuntimeError(f"REFUSING: endpoint rows={len(endpoints)}")
    if len(tiles) != EXPECTED_TILES:
        raise RuntimeError(f"REFUSING: tile rows={len(tiles)}")
    if len(pairs) != EXPECTED_OPPS:
        raise RuntimeError(f"REFUSING: pair rows={len(pairs)}")

    # The original v054 capacity floor assumed every native extracted tile
    # would also be persisted as a local pixel array. That is not a frozen
    # scientific requirement: detector execution is in-memory on the native
    # section. Persist candidate CSV + audit metadata + content SHA instead.
    result_allowance = (
        len(tiles) * PER_TILE_CANDIDATE_META_ALLOWANCE
        + FIXED_RESULT_ALLOWANCE
    )
    required_floor = result_allowance + SAFETY_RESERVE
    disk = shutil.disk_usage(ROOT)

    max_tile_pixels = max(
        int(float(x["extended_pixels"]))
        for x in tiles
    )
    max_tile_memory_bytes_i32 = max_tile_pixels * 4

    policy = {
        "policy_id": "wide_census_disk_bounded_native_execution_v055",
        "inherits_science_policy": "native_tile_execution_v028",
        "scientific_execution_unchanged": True,
        "detector_unit": "native archive pixel tile",
        "core_px": int(pre["core_px"]),
        "halo_px": int(pre["halo_px"]),
        "no_resampling": True,
        "candidate_acceptance": "non-overlapping core only",
        "persistent_science_pixel_tile_files": False,
        "tile_lifecycle": (
            "Remote/native section -> in-memory ndarray -> SHA256 -> frozen detect_array "
            "-> candidate CSV + tile audit JSON -> ndarray released."
        ),
        "persistent_tile_audit": [
            "source URL",
            "endpoint identity",
            "WCS identity",
            "extended/core bounds",
            "shape and dtype",
            "native pixel content SHA256",
            "detector/method/policy SHA256",
            "robust sigma and median residual",
            "candidate CSV SHA256",
        ],
        "checkpoint_validity": (
            "Tile audit JSON complete and candidate CSV present with matching SHA256; "
            "pixel-array persistence is not required."
        ),
        "reproducibility": (
            "A completed tile can be independently reproduced by re-reading the frozen "
            "remote source section with the recorded endpoint/WCS/bounds and comparing "
            "the native pixel content SHA256 before re-running the frozen detector."
        ),
        "free_disk_abort_floor_bytes": SAFETY_RESERVE,
        "per_tile_candidate_meta_allowance_bytes": PER_TILE_CANDIDATE_META_ALLOWANCE,
        "fixed_result_allowance_bytes": FIXED_RESULT_ALLOWANCE,
    }

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_disk_bounded_execution_contract_v055",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "input_sha256": {
            "preflight_v054": sha(PREFLIGHT),
            "endpoints_v054": sha(ENDPOINTS),
            "pairs_v054": sha(PAIRS),
            "tiles_v054": sha(TILES),
            "detector": sha(DETECTOR),
            "method": sha(METHOD),
            "native_policy": sha(NATIVE_POLICY),
        },
        "opportunity_count": len(pairs),
        "endpoint_count": len(endpoints),
        "tile_count": len(tiles),
        "v054_persistent_pixel_capacity_pass": bool(pre.get("capacity_pass")),
        "v054_persistent_pixel_floor_bytes": int(
            pre.get("streaming_working_free_space_floor_bytes", 0)
        ),
        "disk_bounded_result_allowance_bytes": result_allowance,
        "disk_bounded_required_floor_bytes": required_floor,
        "free_disk_bytes": disk.free,
        "disk_bounded_capacity_pass": disk.free >= required_floor,
        "max_one_tile_i32_memory_bytes": max_tile_memory_bytes_i32,
        "execution_policy": policy,
        "interpretation_boundary": (
            "This changes only persistence/storage architecture. The science pixels "
            "read for each detector unit, native coordinate system, tile core/halo, "
            "frozen detector and acceptance rule are unchanged."
        ),
        "next_stage": (
            "Run resumable disk-bounded frozen detector over all 6293 v054 tiles."
        ),
    }

    tmp = OUT_JSON.with_suffix(OUT_JSON.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUT_JSON)

    print(f"Opportunities: {len(pairs)}")
    print(f"Endpoints: {len(endpoints)}")
    print(f"Tiles: {len(tiles)}")
    print(
        "v054 persistent-pixel floor: "
        f"{int(pre.get('streaming_working_free_space_floor_bytes',0))/1024**3:.2f} GiB "
        f"({'PASS' if pre.get('capacity_pass') else 'FAIL'})"
    )
    print(
        "Disk-bounded result+reserve floor: "
        f"{required_floor/1024**3:.2f} GiB"
    )
    print(f"Current free disk: {disk.free/1024**3:.2f} GiB")
    print(
        "DISK-BOUNDED CAPACITY: "
        f"{'PASS' if disk.free >= required_floor else 'FAIL'}"
    )
    print(
        "Maximum one-tile i32 pixel buffer: "
        f"{max_tile_memory_bytes_i32/1024**2:.2f} MiB"
    )
    print("SCIENCE PIXELS READ: 0")
    print("DETECTOR RUNS: 0")
    print(f"Output: {OUT_JSON}")
    print("\nSTAGE STATUS: PASS")

    if disk.free < required_floor:
        raise RuntimeError(
            "REFUSING: insufficient disk even for disk-bounded execution contract"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
