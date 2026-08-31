from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "tools" / "analyze_wide_census_applause_holds_v058.py"
PAYLOAD = ROOT / "tools" / "_analyze_wide_census_applause_holds_v058_source_data_fix1.payload.py"

EXPECTED_OLD_NORMALIZED_SHA = "32ea3856a978dfb3c31926c25641bc611f63205f9702cfb9c4bb35fe6e281171"
EXPECTED_NEW_NORMALIZED_SHA = "dc23884f92bb87651982fece98dc6f793ea81e3dd811d53c73e2f71dee6d445a"


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    print("=" * 132)
    print("v058 APPLAUSE SOURCE-DATA PATH REPAIR 1")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO SCIENCE STATE MUTATION.\n")

    for p in (TARGET, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(TARGET)
    payload = normalized_sha(PAYLOAD)
    print("Installed v058 normalized SHA256:", current)

    if current not in (EXPECTED_OLD_NORMALIZED_SHA, EXPECTED_NEW_NORMALIZED_SHA):
        raise RuntimeError(
            "REFUSING: installed v058 differs from expected original/fixed source: "
            + current
        )
    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    expected_source = ROOT / "source_data" / "applause_exposures_1951_1955.csv"
    if not expected_source.is_file():
        raise RuntimeError(
            "REFUSING: authoritative APPLAUSE exposure table is not present at "
            + str(expected_source)
        )

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v058_source_data_fix1_{stamp}"
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
    print("Authoritative APPLAUSE table:", expected_source)
    print("Original normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:   ", EXPECTED_NEW_NORMALIZED_SHA)
    print("No v058 network query had been executed before this repair.")
    print("\nREPAIR STATUS: PASS")
    print("\nRun v058 again:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'".\tools\analyze_wide_census_applause_holds_v058.py"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
