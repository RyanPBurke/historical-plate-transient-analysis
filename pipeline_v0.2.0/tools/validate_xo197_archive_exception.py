from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

TARGET = "POSS-I:449:O:rec198"
REGION = "XO197"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="research/POSS1_ARCHIVE_AVAILABILITY_EXCEPTION_v0.2.5_2026-08-21.json")
    ap.add_argument("--skyview", default="work/poss_preflight/xo197_exception_probe/xo197_exception_probe.json")
    ap.add_argument("--stsci", default="work/poss_preflight/xo197_stsci_poss1_blue_probe/stsci_poss1_blue_probe_report.json")
    ap.add_argument("--out", default="research/POSS1_XO197_ARCHIVE_EXCEPTION_VALIDATION_v0.2.5.json")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    sky_path = Path(args.skyview)
    stsci_path = Path(args.stsci)
    for p in (manifest_path, sky_path, stsci_path):
        if not p.exists():
            raise SystemExit(f"missing required archive-exception evidence: {p}")

    manifest = load(manifest_path)
    ex = manifest.get("exceptions") or []
    if len(ex) != 1 or ex[0].get("exposure_id") != TARGET or ex[0].get("expected_region") != REGION:
        raise SystemExit("archive-exception manifest does not contain exactly the expected XO197 exception")
    if ex[0].get("eligible_for_science") is not False or ex[0].get("retain_in_prospective_denominator") is not True:
        raise SystemExit("archive-exception manifest eligibility/denominator semantics are invalid")

    sky = load(sky_path)
    if sky.get("target") != TARGET or sky.get("expected_region") != REGION:
        raise SystemExit("SkyView probe target/region mismatch")
    if len(sky.get("descriptor_exact_entries") or []) != 0:
        raise SystemExit("SkyView probe unexpectedly contains an XO197 descriptor entry")
    raw = sky.get("raw_header_probes") or []
    xo = [r for r in raw if str(r.get("region_requested", "")).upper() == REGION]
    if len(xo) != 1 or int(xo[0].get("http_status", -1)) != 404:
        raise SystemExit("SkyView probe does not prove the raw XO197 HHH path returned HTTP 404")

    stsci = load(stsci_path)
    target = stsci.get("target") or {}
    request = stsci.get("request") or {}
    params = request.get("params") or {}
    preview = str(stsci.get("response_preview") or "")
    if target.get("exposure_id") != TARGET or target.get("expected_region") != REGION:
        raise SystemExit("STScI direct probe target/region mismatch")
    if str(params.get("V", "")).lower() != "poss1_blue":
        raise SystemExit("STScI direct probe did not explicitly request poss1_blue")
    if int(request.get("http_status", -1)) != 200:
        raise SystemExit("STScI direct probe did not return the preserved HTTP-200 error document")
    required_phrases = (
        "Calibration and image data not available for field data",
        "poss1_blue.v30.lis",
        "Aborting GetImage",
    )
    if not all(p in preview for p in required_phrases):
        raise SystemExit("STScI direct probe response does not contain the required archive-unavailability evidence")

    audit = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "science_analysis_performed": False,
        "exposure_id": TARGET,
        "expected_region": REGION,
        "classification": "catalogue_identified_pixels_unavailable",
        "eligible_for_science": False,
        "retain_in_prospective_denominator": True,
        "validated_evidence": {
            "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "skyview_probe": {
                "path": str(sky_path),
                "sha256": sha256_file(sky_path),
                "descriptor_exact_region_matches": 0,
                "raw_hhh_http_status": 404,
            },
            "stsci_poss1_blue_probe": {
                "path": str(stsci_path),
                "sha256": sha256_file(stsci_path),
                "survey": "poss1_blue",
                "http_status": 200,
                "service_message": "Calibration and image data not available for field data",
            },
        },
        "interpretation": (
            "The VI/25 physical exposure remains part of the frozen prospective denominator. "
            "No digital DSS pixels are currently available from the validated primary/fallback path, "
            "so this exposure is ineligible for detector execution and must not be counted as a scientific zero."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))
    print("XO197 archive-exception validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
