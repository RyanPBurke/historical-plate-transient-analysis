from pathlib import Path
import json
import subprocess
import sys


def test_xo197_archive_exception_validator_accepts_expected_evidence(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "exceptions": [{
            "exposure_id": "POSS-I:449:O:rec198",
            "expected_region": "XO197",
            "eligible_for_science": False,
            "retain_in_prospective_denominator": True,
        }]
    }), encoding="utf-8")

    sky = tmp_path / "sky.json"
    sky.write_text(json.dumps({
        "target": "POSS-I:449:O:rec198",
        "expected_region": "XO197",
        "descriptor_exact_entries": [],
        "raw_header_probes": [
            {"region_requested": "XO197", "http_status": 404}
        ],
    }), encoding="utf-8")

    stsci = tmp_path / "stsci.json"
    stsci.write_text(json.dumps({
        "target": {
            "exposure_id": "POSS-I:449:O:rec198",
            "expected_region": "XO197",
        },
        "request": {
            "params": {"V": "poss1_blue"},
            "http_status": 200,
        },
        "response_preview": (
            "Calibration and image data not available for field data...\n"
            "Reading plate list: /dss/headers/poss1_blue.v30.lis...\n"
            "Aborting GetImage..."
        ),
    }), encoding="utf-8")

    out = tmp_path / "validation.json"
    cp = subprocess.run([
        sys.executable,
        "tools/validate_xo197_archive_exception.py",
        "--manifest", str(manifest),
        "--skyview", str(sky),
        "--stsci", str(stsci),
        "--out", str(out),
    ], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["classification"] == "catalogue_identified_pixels_unavailable"
    assert data["eligible_for_science"] is False
    assert data["retain_in_prospective_denominator"] is True
