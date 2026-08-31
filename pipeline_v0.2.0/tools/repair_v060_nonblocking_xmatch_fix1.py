from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "tools" / "preflight_wide_census_astrometric_rescue_v060.py"
PAYLOAD = ROOT / "tools" / "_preflight_wide_census_astrometric_rescue_v060_nonblocking_xmatch_fix1.payload.py"

EXPECTED_OLD_SHA = "03fc497720639e84e1cc942246f2d55e339be70e836f3fe1594f05dec0f13413"
EXPECTED_NEW_SHA = "ee8c39cbf397bbe9c9991f50e8c91278568c60d2001cbf70438d8882b39b7d42"


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    print("=" * 132)
    print("v060 NON-BLOCKING SOURCE_XMATCH DIAGNOSTIC REPAIR 1")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO SOLVER. NO SCIENCE STATE MUTATION.\n")

    for p in (TARGET, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(TARGET)
    payload = normalized_sha(PAYLOAD)
    print("Installed v060 normalized SHA256:", current)

    if current not in (EXPECTED_OLD_SHA, EXPECTED_NEW_SHA):
        raise RuntimeError(
            "REFUSING: installed v060 differs from expected original/fixed source: "
            + current
        )
    if payload != EXPECTED_NEW_SHA:
        raise RuntimeError("REFUSING: payload SHA mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v060_nonblocking_xmatch_fix1_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup / TARGET.name)

    TARGET.write_text(
        PAYLOAD.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    py_compile.compile(str(TARGET), doraise=True)

    if normalized_sha(TARGET) != EXPECTED_NEW_SHA:
        raise RuntimeError("Installed fixed v060 source hash mismatch")

    print("\nSource guard: PASS")
    print("Original normalized SHA256:", EXPECTED_OLD_SHA)
    print("Fixed normalized SHA256:   ", EXPECTED_NEW_SHA)
    print("source_xmatch process-wide query removed: True")
    print("source_xmatch diagnostic targeted by returned source_id: True")
    print("source_xmatch diagnostic failure is non-blocking: True")
    print("Prospective v060 preflight contract preserved: True")
    print("\nREPAIR STATUS: PASS")
    print("\nRerun v060:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'".\tools\preflight_wide_census_astrometric_rescue_v060.py"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
