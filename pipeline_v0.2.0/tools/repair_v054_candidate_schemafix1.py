from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "preflight_wide_heavy_detector_v054.py"
PAYLOAD = ROOT / "tools" / "_preflight_wide_heavy_detector_v054_schemafix1.payload.py"

EXPECTED_OLD_NORMALIZED_SHA = "d6d81a667416efc9e24935cf720bb60561613239cd72d60027ebe7f1afe38fba"
EXPECTED_NEW_NORMALIZED_SHA = "e7b9de075cd56f87e88ae55250a76b4109d1b3d3e618c783c20719e408a0ea80"


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def raw_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=" * 132)
    print("HEAVY PREFLIGHT v054 — FROZEN FOOTPRINT CANDIDATE SCHEMA REPAIR 1")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (STAGE, PAYLOAD):
        if not path.is_file():
            raise RuntimeError(f"Missing repair input: {path}")

    current_raw = raw_sha(STAGE)
    current_norm = normalized_sha(STAGE)
    payload_norm = normalized_sha(PAYLOAD)

    print("Installed stage raw SHA256:", current_raw)
    print("Installed stage normalized SHA256:", current_norm)

    if current_norm not in (
        EXPECTED_OLD_NORMALIZED_SHA,
        EXPECTED_NEW_NORMALIZED_SHA,
    ):
        raise RuntimeError(
            "REFUSING: installed v054 source differs from both expected "
            "pre-fix and schema-fixed source: " + current_norm
        )

    if payload_norm != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError(
            "REFUSING: repair payload normalized SHA mismatch: " + payload_norm
        )

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v054_schemafix1_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)

    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    installed = normalized_sha(STAGE)
    if installed != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError(
            "Installed v054 schema-fixed source hash mismatch: " + installed
        )

    print("\nSource guard: PASS")
    print("Pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("Installed fixed normalized SHA256:", installed)
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'-m automation.runner run-until-blocked --allow-network'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
