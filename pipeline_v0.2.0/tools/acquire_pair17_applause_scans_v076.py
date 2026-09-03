#!/usr/bin/env python3
"""
Acquire the two exact APPLAUSE DR4 physical scans required by frozen v076.
Transport/provenance only: does not inspect science pixels or morphology outcomes.
"""

from pathlib import Path
import csv
import hashlib
import json
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research" / "prospective_freezes" / "pair17_matched_peer_morphology_contract_v076.json"
EXPECTED_CONTRACT_SHA = "02f3d9d0b5bbc7a89a44c270d59537c878ec9d52fb7a70d0d97930aeb5420c2f"

WORK = ROOT / "work" / "pair17_morphology_v076"
SCAN_DIR = WORK / "scans"
MANIFEST_JSON = WORK / "pair17_morphology_scan_acquisition_v076.json"
MANIFEST_CSV = WORK / "pair17_morphology_scan_acquisition_v076.csv"

SCANS = [
    {
        "endpoint": "APPLAUSE:14120",
        "plate_id": "7685",
        "filename": "LA08164_y.fits",
        "url": "https://www.plate-archive.org/files/DR4/scans/HAM-LA/LA08164_y.fits",
        "expected_bytes": 426124800,
    },
    {
        "endpoint": "APPLAUSE:132654",
        "plate_id": "89580",
        "filename": "012673_1953_h.fits",
        "url": "https://www.plate-archive.org/files/DR4/scans/Bamberg-North/012673_1953_h.fits",
        "expected_bytes": 174888000,
    },
]

CHUNK = 8 * 1024 * 1024
UA = "historical-transient-pipeline/pair17-v076-scan-acquisition"


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def atomic_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fields = [
        "endpoint", "plate_id", "filename", "url", "expected_bytes",
        "actual_bytes", "sha256", "status"
    ]
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def download_resume(item):
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    dst = SCAN_DIR / item["filename"]
    expected = int(item["expected_bytes"])

    if dst.is_file() and dst.stat().st_size == expected:
        print(f"{item['filename']}: already complete; hashing ...", flush=True)
        return dst

    offset = dst.stat().st_size if dst.is_file() else 0
    if offset > expected:
        raise RuntimeError(
            f"{item['filename']}: local file larger than expected "
            f"({offset} > {expected}); refusing"
        )

    headers = {"User-Agent": UA}
    if offset:
        headers["Range"] = f"bytes={offset}-"

    req = urllib.request.Request(item["url"], headers=headers, method="GET")

    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{item['filename']}: HTTP {e.code}") from e

    status = getattr(resp, "status", None)
    content_range = resp.headers.get("Content-Range")

    if offset and status != 206:
        # Server ignored Range; restart from byte zero rather than append duplicate data.
        resp.close()
        print(f"{item['filename']}: server did not honor resume; restarting", flush=True)
        offset = 0
        headers = {"User-Agent": UA}
        req = urllib.request.Request(item["url"], headers=headers, method="GET")
        resp = urllib.request.urlopen(req, timeout=120)
        status = getattr(resp, "status", None)

    mode = "ab" if offset else "wb"
    downloaded = offset
    started = time.time()
    last_report = started

    with resp, dst.open(mode) as f:
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            f.write(block)
            downloaded += len(block)

            now = time.time()
            if now - last_report >= 5:
                pct = 100.0 * downloaded / expected
                mib = downloaded / (1024 * 1024)
                total = expected / (1024 * 1024)
                print(
                    f"{item['filename']}: {mib:,.1f}/{total:,.1f} MiB "
                    f"({pct:.1f}%)",
                    flush=True,
                )
                last_report = now

    actual = dst.stat().st_size
    if actual != expected:
        raise RuntimeError(
            f"{item['filename']}: incomplete/changed transport size "
            f"{actual} != expected {expected}"
        )

    return dst


def main():
    print("=" * 120)
    print("PAIR 17 v076 APPLAUSE SCAN ACQUISITION")
    print("=" * 120)
    print("Transport/provenance only. NO morphology measurements. NO detector rerun.")
    print()

    if not CONTRACT.is_file():
        raise RuntimeError(f"Missing frozen v076 contract: {CONTRACT}")

    actual_contract_sha = sha256(CONTRACT)
    if actual_contract_sha != EXPECTED_CONTRACT_SHA:
        raise RuntimeError(
            "REFUSING: v076 contract SHA mismatch\n"
            f"expected {EXPECTED_CONTRACT_SHA}\n"
            f"actual   {actual_contract_sha}"
        )

    rows = []

    for item in SCANS:
        path = download_resume(item)
        digest = sha256(path)
        actual = path.stat().st_size
        print(f"{item['filename']}: COMPLETE")
        print(f"  bytes  {actual}")
        print(f"  sha256 {digest}")

        rows.append({
            **item,
            "actual_bytes": actual,
            "sha256": digest,
            "status": "COMPLETE",
        })

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_v076_applause_scan_acquisition",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "guards": {
            "morphology_measurements": 0,
            "detector_rerun": False,
            "registration_rerun": False,
            "candidate_disposition_changes": False,
        },
        "scans": rows,
        "next_stage": (
            "Freeze/execute v076 native-pixel morphology implementation against these "
            "exact recorded scan bytes."
        ),
    }

    atomic_csv(MANIFEST_CSV, rows)
    atomic_json(MANIFEST_JSON, report)

    print()
    print("SCAN ACQUISITION COMPLETE")
    print("Morphology measurements performed: 0")
    print("Candidate dispositions changed:    NONE")


if __name__ == "__main__":
    main()
