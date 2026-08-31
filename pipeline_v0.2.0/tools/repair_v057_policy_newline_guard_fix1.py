from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import py_compile
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "tools" / "freeze_wide_census_postdetector_contract_v057.py"
PAYLOAD = ROOT / "tools" / "_freeze_wide_census_postdetector_contract_v057_policy_newline_fix1.payload.py"

EXPECTED_ORIGINAL_NORMALIZED_SHA = "e625011b47e77b34d826780d11c796d756ea71119ce938bd38b229c4076b086a"
EXPECTED_FIXED_NORMALIZED_SHA = "d7a82a05225aa873e8d0b0e861c550c2a1102a9420b6092081fea814395993cb"


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    print("=" * 132)
    print("v057 PROSPECTIVE-FREEZE POLICY NEWLINE-GUARD REPAIR 1")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO SCIENCE STATE MUTATION.\n")

    for p in (TARGET, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(TARGET)
    payload = normalized_sha(PAYLOAD)
    print("Installed v057 normalized SHA256:", current)

    if current not in (
        EXPECTED_ORIGINAL_NORMALIZED_SHA,
        EXPECTED_FIXED_NORMALIZED_SHA,
    ):
        raise RuntimeError(
            "REFUSING: installed v057 freeze script differs from expected "
            "original/fixed source: " + current
        )
    if payload != EXPECTED_FIXED_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v057_policy_newline_fix1_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup / TARGET.name)

    TARGET.write_text(
        PAYLOAD.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    py_compile.compile(str(TARGET), doraise=True)

    installed = normalized_sha(TARGET)
    if installed != EXPECTED_FIXED_NORMALIZED_SHA:
        raise RuntimeError("Installed fixed v057 source hash mismatch")

    print("\nSource guard: PASS")
    print("Original normalized SHA256:", EXPECTED_ORIGINAL_NORMALIZED_SHA)
    print("Fixed normalized SHA256:   ", EXPECTED_FIXED_NORMALIZED_SHA)
    print("No prospective contract existed/was altered by this repair.")
    print("\nREPAIR STATUS: PASS")
    print("\nRun the prospective freeze again:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'".\tools\freeze_wide_census_postdetector_contract_v057.py"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
