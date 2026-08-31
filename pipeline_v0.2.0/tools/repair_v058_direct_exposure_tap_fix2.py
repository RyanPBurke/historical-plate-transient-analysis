from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "tools" / "analyze_wide_census_applause_holds_v058.py"
PAYLOAD = ROOT / "tools" / "_analyze_wide_census_applause_holds_v058_direct_exposure_tap_fix2.payload.py"

EXPECTED_ORIGINAL_NORMALIZED_SHA = "32ea3856a978dfb3c31926c25641bc611f63205f9702cfb9c4bb35fe6e281171"
EXPECTED_FIX1_NORMALIZED_SHA = "dc23884f92bb87651982fece98dc6f793ea81e3dd811d53c73e2f71dee6d445a"
EXPECTED_NEW_NORMALIZED_SHA = "d02f6eea598f59bd35788decb93a0a841f5ec34d39bc655a9338cbe0377f0642"


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    print("=" * 132)
    print("v058 APPLAUSE DIRECT OFFICIAL-EXPOSURE TAP REPAIR 2")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO SCIENCE STATE MUTATION.\n")

    for p in (TARGET, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(TARGET)
    payload = normalized_sha(PAYLOAD)
    print("Installed v058 normalized SHA256:", current)

    if current not in (
        EXPECTED_ORIGINAL_NORMALIZED_SHA,
        EXPECTED_FIX1_NORMALIZED_SHA,
        EXPECTED_NEW_NORMALIZED_SHA,
    ):
        raise RuntimeError(
            "REFUSING: installed v058 differs from expected original/fix1/fix2 source: "
            + current
        )
    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v058_direct_exposure_tap_fix2_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup / TARGET.name)

    TARGET.write_text(
        PAYLOAD.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    py_compile.compile(str(TARGET), doraise=True)

    if normalized_sha(TARGET) != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("Installed fixed v058 source hash mismatch")

    print("\nSource guard: PASS")
    print("Original normalized SHA256:", EXPECTED_ORIGINAL_NORMALIZED_SHA)
    print("Fix1 normalized SHA256:    ", EXPECTED_FIX1_NORMALIZED_SHA)
    print("Fix2 normalized SHA256:    ", EXPECTED_NEW_NORMALIZED_SHA)
    print("Local applause_exposures_1951_1955.csv dependency removed: True")
    print("Exact exposure IDs will be resolved from official applause_dr4.exposure TAP: True")
    print("\nREPAIR STATUS: PASS")
    print("\nRun v058 again:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'".\tools\analyze_wide_census_applause_holds_v058.py"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
