from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_wide_frozen_detector_v056.py"
PAYLOAD = ROOT / "tools" / "_execute_wide_frozen_detector_v056_cached_credential_rollover_fix5.payload.py"
STATE = ROOT / "results" / "wide_census_detector_execution_v056" / "state_v056.json"
FAILURES = ROOT / "results" / "wide_census_detector_execution_v056" / "terminal_tile_failures_v056.json"

EXPECTED_OLD_NORMALIZED_SHA = "f4c8a9a1d6d07b9dc394de5ab9e44ce94af76661b174d13c5ae1c6dcbb2f1993"
EXPECTED_NEW_NORMALIZED_SHA = "35ec94ce73ba828185d2a295ff50691c5fbf70dcb9cb534f7a2515d2639ee1ef"

def normalize_text(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")

def normalized_sha(path):
    return hashlib.sha256(normalize_text(path.read_text(encoding="utf-8")).encode()).hexdigest()

def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)

def is_transport_record(rec):
    if not isinstance(rec, dict):
        return False
    if not str(rec.get("endpoint_key", "")).startswith("DASCH:"):
        return False
    s = f"{rec.get('error_type','')}: {rec.get('error','')}".lower()
    return any(x in s for x in (
        "403", "forbidden", "request has expired", "requestexpired",
        "expiredtoken", "signaturedoesnotmatch", "dasch-prod-user.s3",
        "filenotfounderror", "near-expiry signed url",
        "cached dasch signed url at expiry boundary",
        "mosaic_package refresh failed",
    ))

def main():
    print("="*132)
    print("HEAVY DETECTOR v056 — DASCH CACHED-CREDENTIAL ROLLOVER REPAIR 5")
    print("="*132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (STAGE, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(STAGE)
    payload = normalized_sha(PAYLOAD)
    print("Installed v056 normalized SHA256:", current)
    if current not in (EXPECTED_OLD_NORMALIZED_SHA, EXPECTED_NEW_NORMALIZED_SHA):
        raise RuntimeError("REFUSING: installed v056 differs from expected fix4/fix5 source: " + current)
    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v056_cached_credential_fix5_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    if STATE.is_file(): shutil.copy2(STATE, backup / STATE.name)
    if FAILURES.is_file(): shutil.copy2(FAILURES, backup / FAILURES.name)

    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)
    if normalized_sha(STAGE) != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("Installed fixed v056 source hash mismatch")

    cleared_terminal, cleared_attempts = [], []
    if STATE.is_file():
        state = json.loads(STATE.read_text(encoding="utf-8"))
        terminal = state.setdefault("terminal", {})
        attempts = state.setdefault("attempts", {})
        evidence = dict(terminal)
        for rec in state.get("last_cycle_failures", []) or []:
            key = str(rec.get("tile_key", ""))
            if key: evidence.setdefault(key, rec)
        if FAILURES.is_file():
            try:
                rep = json.loads(FAILURES.read_text(encoding="utf-8"))
                for key, rec in (rep.get("terminal") or {}).items():
                    evidence.setdefault(key, rec)
            except Exception:
                pass

        for key, rec in evidence.items():
            if not is_transport_record(rec):
                continue
            if key in terminal:
                terminal.pop(key, None); cleared_terminal.append(key)
            if key in attempts:
                attempts.pop(key, None); cleared_attempts.append(key)

        state["status"] = "IN_PROGRESS"
        state["dasch_cached_credential_rollover_repair_5"] = {
            "reason": ("Fix4's 720-second admission threshold was too conservative for a 900-second credential. StarGlass can return a cached but still-valid URL with only a few minutes remaining; v056 should use it and rely on inline refresh if it later expires."),
            "new_controls": [
                "accept signed URL when >=45 seconds remain",
                "if <45 seconds remain, wait through credential/cache rollover and retry locally up to 24 times",
                "retain inline 403/expiry refresh without consuming persistent science-tile retry budget",
                "preserve exact frozen v052 geometry/WCS and baseFitsSize guards",
            ],
            "cleared_terminal_tile_keys": sorted(cleared_terminal),
            "cleared_attempt_tile_keys": sorted(cleared_attempts),
            "successful_tile_checkpoints_preserved": True,
            "detector_or_science_threshold_change": False,
        }
        write_json(STATE, state)

    if FAILURES.is_file():
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}
        if not (st.get("terminal") or {}):
            FAILURES.unlink()

    print("\nSource guard: PASS")
    print("Pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("DASCH transport terminal tiles cleared:", len(cleared_terminal))
    print("DASCH transport attempt counters cleared:", len(cleared_attempts))
    print("Successful tile checkpoints preserved: True")
    print("Frozen DASCH geometry/WCS remains authoritative: True")
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network --allow-detector-rerun')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
