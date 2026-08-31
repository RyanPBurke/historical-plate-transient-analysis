from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_wide_frozen_detector_v056.py"
PAYLOAD = ROOT / "tools" / "_execute_wide_frozen_detector_v056_zero_sigma_hold_fix2.payload.py"
STATE = ROOT / "results" / "wide_census_detector_execution_v056" / "state_v056.json"
FAILURES = ROOT / "results" / "wide_census_detector_execution_v056" / "terminal_tile_failures_v056.json"

EXPECTED_OLD_NORMALIZED_SHA = "229d8b37f2179937e39b669f0fc8ea89bbd935e8df807ddc3e540eafcc239c3b"
EXPECTED_NEW_NORMALIZED_SHA = "1fb6ea46167a8a04014a11143b01daa78023ff873b3cf1a40fe332267f70ccf3"
ZERO_SIGMA_TEXT = "invalid robust sigma 0.0"


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
    if not isinstance(rec, dict):
        return False
    return (
        str(rec.get("error", "")).strip() == ZERO_SIGMA_TEXT
        and str(rec.get("error_type", "")) in {"ValueError", "RuntimeError"}
    )


def main():
    print("=" * 132)
    print("HEAVY DETECTOR v056 — ZERO ROBUST-SIGMA COVERAGE-HOLD REPAIR 2")
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
            "REFUSING: installed v056 differs from expected fix1/fix2 source: "
            + current
        )
    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v056_zero_sigma_hold_fix2_{stamp}"
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

        # Clear every terminal record positively identified as the exact
        # deterministic zero-sigma detector condition.
        for key, rec in list(terminal.items()):
            if is_zero_sigma_record(rec):
                terminal.pop(key, None)
                cleared_terminal.append(key)
                if key in attempts:
                    attempts.pop(key, None)
                    cleared_attempts.append(key)

        # Also use the saved last-cycle failure evidence. This covers the
        # state shape seen after fix1 where the terminal record was absent
        # but the attempt counter remained at 6/7.
        for rec in state.get("last_cycle_failures", []) or []:
            if not is_zero_sigma_record(rec):
                continue
            key = str(rec.get("tile_key", ""))
            if key and key in attempts:
                attempts.pop(key, None)
                if key not in cleared_attempts:
                    cleared_attempts.append(key)
            if key and key in terminal:
                terminal.pop(key, None)
                if key not in cleared_terminal:
                    cleared_terminal.append(key)

        # Finally, inspect the live terminal-failure report if present.
        if FAILURES.is_file():
            try:
                report = json.loads(FAILURES.read_text(encoding="utf-8"))
                for key, rec in (report.get("terminal") or {}).items():
                    if not is_zero_sigma_record(rec):
                        continue
                    if key in attempts:
                        attempts.pop(key, None)
                        if key not in cleared_attempts:
                            cleared_attempts.append(key)
                    if key in terminal:
                        terminal.pop(key, None)
                        if key not in cleared_terminal:
                            cleared_terminal.append(key)
            except Exception:
                pass

        state["status"] = "IN_PROGRESS"
        state["zero_sigma_hold_repair_2"] = {
            "reason": (
                "Frozen detector raises ValueError, not RuntimeError, for exact "
                "'invalid robust sigma 0.0'. Fix2 catches the actual detector "
                "exception and clears only positively identified zero-sigma retry state."
            ),
            "cleared_terminal_tile_keys": sorted(cleared_terminal),
            "cleared_attempt_tile_keys": sorted(cleared_attempts),
            "successful_tile_checkpoints_preserved": True,
            "new_state": "UNINFORMATIVE_ZERO_ROBUST_SIGMA",
        }
        write_json(STATE, state)

    # Backed up above. Remove stale live failure report only if all remaining
    # terminal records (if any) have been cleared from state.
    if FAILURES.is_file():
        state_now = (
            json.loads(STATE.read_text(encoding="utf-8"))
            if STATE.is_file()
            else {}
        )
        if not (state_now.get("terminal") or {}):
            FAILURES.unlink()

    print("\nSource guard: PASS")
    print("Pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("Zero-sigma terminal tiles cleared:", len(cleared_terminal))
    print("Zero-sigma attempt counters cleared:", len(cleared_attempts))
    for key in sorted(set(cleared_terminal + cleared_attempts)):
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
