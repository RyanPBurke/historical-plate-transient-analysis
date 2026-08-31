from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "tools" / "analyze_wide_census_applause_holds_v058.py"
PAYLOAD = ROOT / "tools" / "_analyze_wide_census_applause_holds_v058_simple_tap_fix3.payload.py"

EXPECTED_FIX2_NORMALIZED_SHA = "d02f6eea598f59bd35788decb93a0a841f5ec34d39bc655a9338cbe0377f0642"
EXPECTED_FIX3_NORMALIZED_SHA = "7e92fb8404be857aacdb02dcc583c5581163ac8f99bad51862861e4956326e8c"


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    print("=" * 132)
    print("v058 APPLAUSE SIMPLE-TAP QUERY REPAIR 3")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO SCIENCE STATE MUTATION.\n")

    for p in (TARGET, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(TARGET)
    payload = normalized_sha(PAYLOAD)
    print("Installed v058 normalized SHA256:", current)

    if current not in (EXPECTED_FIX2_NORMALIZED_SHA, EXPECTED_FIX3_NORMALIZED_SHA):
        raise RuntimeError(
            "REFUSING: installed v058 differs from expected fix2/fix3 source: "
            + current
        )
    if payload != EXPECTED_FIX3_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v058_simple_tap_fix3_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup / TARGET.name)

    TARGET.write_text(
        PAYLOAD.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    py_compile.compile(str(TARGET), doraise=True)

    if normalized_sha(TARGET) != EXPECTED_FIX3_NORMALIZED_SHA:
        raise RuntimeError("Installed fixed v058 source hash mismatch")

    print("\nSource guard: PASS")
    print("Fix2 normalized SHA256:", EXPECTED_FIX2_NORMALIZED_SHA)
    print("Fix3 normalized SHA256:", EXPECTED_FIX3_NORMALIZED_SHA)
    print("IN predicates removed: True")
    print("Server-side table joins removed: True")
    print("Solution↔scan join now exact/local by official scan_id: True")
    print("HTTP 4xx TAP response body now preserved for diagnostics: True")
    print("\nREPAIR STATUS: PASS")
    print("\nRun v058 again:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'".\tools\analyze_wide_census_applause_holds_v058.py"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
