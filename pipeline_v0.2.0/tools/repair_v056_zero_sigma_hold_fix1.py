from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_wide_frozen_detector_v056.py"
PAYLOAD = ROOT / "tools" / "_execute_wide_frozen_detector_v056_zero_sigma_hold_fix1.payload.py"
STATE = ROOT / "results" / "wide_census_detector_execution_v056" / "state_v056.json"
FAILURES = ROOT / "results" / "wide_census_detector_execution_v056" / "terminal_tile_failures_v056.json"

EXPECTED_OLD_NORMALIZED_SHA = "424655edf3eb54981e74468a57325d94a53aec7d962d5bb23e1ccc8f1efed231"
EXPECTED_NEW_NORMALIZED_SHA = "229d8b37f2179937e39b669f0fc8ea89bbd935e8df807ddc3e540eafcc239c3b"


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


def is_zero_sigma_record(rec):
    return (
        isinstance(rec, dict)
        and str(rec.get("error_type", "")) == "RuntimeError"
        and str(rec.get("error", "")).strip() == "invalid robust sigma 0.0"
    )


def main():
    print("=" * 132)
    print("HEAVY DETECTOR v056 — ZERO ROBUST-SIGMA COVERAGE-HOLD REPAIR 1")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (STAGE, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(STAGE)
    payload = normalized_sha(PAYLOAD)

    print("Installed v056 normalized SHA256:", current)

    if current not in (
        EXPECTED_OLD_NORMALIZED_SHA,
        EXPECTED_NEW_NORMALIZED_SHA,
    ):
        raise RuntimeError(
            "REFUSING: installed v056 differs from expected pre-fix/fixed source: "
            + current
        )
    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v056_zero_sigma_hold_fix1_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    if STATE.is_file():
        shutil.copy2(STATE, backup / STATE.name)
    if FAILURES.is_file():
        shutil.copy2(FAILURES, backup / FAILURES.name)

    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    if normalized_sha(STAGE) != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("Installed fixed v056 source hash mismatch")

    cleared_terminal = []
    cleared_attempts = []

    if STATE.is_file():
        state = json.loads(STATE.read_text(encoding="utf-8"))
        terminal = state.setdefault("terminal", {})
        attempts = state.setdefault("attempts", {})

        for key, rec in list(terminal.items()):
            if is_zero_sigma_record(rec):
                terminal.pop(key, None)
                cleared_terminal.append(key)
                if key in attempts:
                    attempts.pop(key, None)
                    cleared_attempts.append(key)

        # Also clear retry history for exact zero-sigma records that had not
        # yet reached terminal state, while leaving all unrelated failures.
        for key in list(attempts):
            if key in cleared_attempts:
                continue
            # The only known terminal report contains the provenance needed to
            # identify the deterministic zero-sigma tile. Do not clear unknown
            # attempt keys without evidence.
            pass

        state["status"] = "IN_PROGRESS"
        state["zero_sigma_hold_repair_1"] = {
            "reason": (
                "Frozen detector returned deterministic 'invalid robust sigma 0.0'. "
                "This is a detector-undefined sensitivity state, not a retryable "
                "network/process failure and not a scientific non-detection."
            ),
            "cleared_terminal_tile_keys": cleared_terminal,
            "cleared_attempt_tile_keys": cleared_attempts,
            "successful_tile_checkpoints_preserved": True,
            "new_state": "UNINFORMATIVE_ZERO_ROBUST_SIGMA",
        }
        write_json(STATE, state)

    # The terminal report is stale after the corresponding state is cleared.
    # It is already backed up above; remove only the live stale copy.
    if FAILURES.is_file():
        FAILURES.unlink()

    print("\nSource guard: PASS")
    print("Pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("Zero-sigma terminal tiles cleared:", len(cleared_terminal))
    for key in cleared_terminal:
        print("  ", key)
    print("Successful tile checkpoints preserved: True")
    print("\nREPAIR STATUS: PASS")
    print("\nResume heavy run:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'-m automation.runner run-until-blocked '
        r'--allow-network --allow-detector-rerun'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
