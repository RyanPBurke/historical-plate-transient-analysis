from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "preflight_wide_heavy_detector_v054.py"
PAYLOAD = ROOT / "tools" / "_preflight_wide_heavy_detector_v054_fileresolutionfix3.payload.py"
CHECKPOINT = ROOT / "results" / "wide_census_heavy_preflight_v054" / "checkpoint_v054.json"
DATALINK_CACHE = ROOT / "results" / "wide_census_heavy_preflight_v054" / "cache" / "datalink"

EXPECTED_OLD_NORMALIZED_SHA = "d5f23234ea2a5af8cabb12875df4199752ec1875052e902e0b60aa8afa3b2c1e"
EXPECTED_NEW_NORMALIZED_SHA = "9e7b8339469a5de160dfc4b151fcbaeb4c80fc2f6a0c2099f41645cd060dd447"


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main():
    print("=" * 132)
    print("HEAVY PREFLIGHT v054 — APPLAUSE DIRECT DR4 FILE RESOLUTION REPAIR 3")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (STAGE, PAYLOAD):
        if not path.is_file():
            raise RuntimeError(f"Missing repair input: {path}")

    current = normalized_sha(STAGE)
    payload = normalized_sha(PAYLOAD)

    print("Installed stage normalized SHA256:", current)

    if current not in (
        EXPECTED_OLD_NORMALIZED_SHA,
        EXPECTED_NEW_NORMALIZED_SHA,
    ):
        raise RuntimeError(
            "REFUSING: installed v054 source differs from expected file-resolution "
            "pre-fix/fixed sources: " + current
        )

    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError(
            "REFUSING: file-resolution-fix payload SHA mismatch: " + payload
        )

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v054_file_resolution_fix3_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)

    if CHECKPOINT.is_file():
        shutil.copy2(CHECKPOINT, backup / CHECKPOINT.name)

    # Preserve the failed HTML-datalink cache for audit before clearing it.
    if DATALINK_CACHE.is_dir():
        shutil.copytree(DATALINK_CACHE, backup / "failed_html_datalink_cache")

    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    if normalized_sha(STAGE) != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("Installed v054 file-resolution-fixed SHA mismatch")

    cleared_attempts = 0
    cleared_terminal = 0

    if CHECKPOINT.is_file():
        cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        attempts = cp.setdefault("attempts", {})
        terminal = cp.setdefault("terminal", {})

        for key in list(attempts):
            if str(key).startswith("datalink:"):
                attempts.pop(key, None)
                cleared_attempts += 1

        for key in list(terminal):
            if str(key).startswith("datalink:"):
                terminal.pop(key, None)
                cleared_terminal += 1

        last_error = cp.get("last_error")
        if isinstance(last_error, dict) and str(last_error.get("key", "")).startswith("datalink:"):
            cp["last_error"] = None

        cp["status"] = "IN_PROGRESS"
        cp["applause_datalink_done"] = 0
        cp["file_resolution_repair_3"] = {
            "reason": (
                "Human HTML datalink pages yielded zero href-parsed FITS links; "
                "DR4 scan.filename_scan is itself the repository-relative scan path."
            ),
            "new_method": (
                "DIRECT /files/<filename_scan> + bounded first FITS-header-block Range probe"
            ),
            "cleared_attempt_keys": cleared_attempts,
            "cleared_terminal_keys": cleared_terminal,
            "failed_cache_preserved_at": str(
                (backup / "failed_html_datalink_cache").relative_to(ROOT)
            ).replace("\\", "/"),
        }
        write_json(CHECKPOINT, cp)

    if DATALINK_CACHE.is_dir():
        shutil.rmtree(DATALINK_CACHE)

    print("\nSource guard: PASS")
    print("Pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("Cleared datalink attempt keys:", cleared_attempts)
    print("Cleared datalink terminal keys:", cleared_terminal)
    print("Old failed datalink cache preserved:", (backup / "failed_html_datalink_cache").is_dir())
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'-m automation.runner run-until-blocked --allow-network'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
