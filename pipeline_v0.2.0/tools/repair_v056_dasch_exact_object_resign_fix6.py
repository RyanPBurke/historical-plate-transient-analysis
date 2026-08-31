from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_wide_frozen_detector_v056.py"
PAYLOAD = ROOT / "tools" / "_execute_wide_frozen_detector_v056_exact_object_resign_fix6.payload.py"
STATE = ROOT / "results" / "wide_census_detector_execution_v056" / "state_v056.json"
FAILURES = ROOT / "results" / "wide_census_detector_execution_v056" / "terminal_tile_failures_v056.json"

EXPECTED_FIX5_SHA = "35ec94ce73ba828185d2a295ff50691c5fbf70dcb9cb534f7a2515d2639ee1ef"
EXPECTED_FIX6_SHA = "21d581bfe86ec2dd343254c17e6b4e62db789cd8965947383c23d03222f2b48b"

def norm_text(s):
    return s.replace("\r\n", "\n").replace("\r", "\n")

def normalized_sha(path):
    return hashlib.sha256(norm_text(path.read_text(encoding="utf-8")).encode()).hexdigest()

def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)

def stale_transport_record(rec):
    if not isinstance(rec, dict):
        return False
    if not str(rec.get("endpoint_key", "")).startswith("DASCH:"):
        return False
    s = f"{rec.get('error_type','')}: {rec.get('error','')}".lower()
    return any(x in s for x in (
        "cached dasch signed url at expiry boundary",
        "mosaic_package refresh failed",
        "near-expiry signed url",
        "403", "forbidden", "request has expired", "requestexpired",
        "expiredtoken", "signaturedoesnotmatch", "dasch-prod-user.s3",
    ))

def main():
    print("=" * 132)
    print("HEAVY DETECTOR v056 — DASCH EXACT-FROZEN-OBJECT RE-SIGN REPAIR 6")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (STAGE, PAYLOAD):
        if not p.is_file():
            raise RuntimeError(f"Missing repair input: {p}")

    current = normalized_sha(STAGE)
    payload = normalized_sha(PAYLOAD)
    print("Installed v056 normalized SHA256:", current)
    if current not in (EXPECTED_FIX5_SHA, EXPECTED_FIX6_SHA):
        raise RuntimeError(
            "REFUSING: installed v056 differs from expected fix5/fix6 source: " + current
        )
    if payload != EXPECTED_FIX6_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v056_exact_object_resign_fix6_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    if STATE.is_file():
        shutil.copy2(STATE, backup / STATE.name)
    if FAILURES.is_file():
        shutil.copy2(FAILURES, backup / FAILURES.name)

    STAGE.write_text(
        PAYLOAD.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    py_compile.compile(str(STAGE), doraise=True)
    if normalized_sha(STAGE) != EXPECTED_FIX6_SHA:
        raise RuntimeError("Installed fixed v056 source hash mismatch")

    cleared_terminal = []
    cleared_attempts = []
    completed_before = None
    if STATE.is_file():
        state = json.loads(STATE.read_text(encoding="utf-8"))
        completed_before = state.get("completed_tiles")
        terminal = state.setdefault("terminal", {})
        attempts = state.setdefault("attempts", {})

        evidence = dict(terminal)
        for rec in state.get("last_cycle_failures", []) or []:
            key = str(rec.get("tile_key", ""))
            if key:
                evidence.setdefault(key, rec)
        if FAILURES.is_file():
            try:
                rep = json.loads(FAILURES.read_text(encoding="utf-8"))
                for key, rec in (rep.get("terminal") or {}).items():
                    evidence.setdefault(key, rec)
            except Exception:
                pass

        for key, rec in evidence.items():
            if not stale_transport_record(rec):
                continue
            if key in terminal:
                terminal.pop(key, None)
                cleared_terminal.append(key)
            if key in attempts:
                attempts.pop(key, None)
                cleared_attempts.append(key)

        state["status"] = "IN_PROGRESS"
        state["dasch_exact_frozen_object_resign_repair_6"] = {
            "reason": (
                "The public mosaic_package endpoint continued serving one cached "
                "expired presigned URL indefinitely for j04686. Waiting for cache "
                "rollover cannot refresh a credential that the endpoint never replaces."
            ),
            "transport_change_only": True,
            "new_credential_source": (
                "GET /public/plates/p/{plate}/mosaic?bin_factor=01"
            ),
            "science_identity_guards": [
                "returned plate_id exact",
                "returned bin_factor == 01",
                "object_size == frozen v052 baseFitsSize",
                "query-stripped presigned object URL == query-stripped frozen v052 baseFitsUrl",
                "frozen v052 WCS/rotation/geometry remains authoritative",
            ],
            "cleared_terminal_tile_keys": sorted(cleared_terminal),
            "cleared_attempt_tile_keys": sorted(cleared_attempts),
            "successful_tile_checkpoints_preserved": True,
            "completed_tiles_before_repair": completed_before,
            "detector_or_science_threshold_change": False,
        }
        write_json(STATE, state)

    if FAILURES.is_file() and STATE.is_file():
        st = json.loads(STATE.read_text(encoding="utf-8"))
        if not (st.get("terminal") or {}):
            FAILURES.unlink()

    print("\nSource guard: PASS")
    print("Fix5 normalized SHA256:", EXPECTED_FIX5_SHA)
    print("Fix6 normalized SHA256:", EXPECTED_FIX6_SHA)
    print("Stale DASCH transport terminal tiles cleared:", len(cleared_terminal))
    print("Stale DASCH transport attempt counters cleared:", len(cleared_attempts))
    print("Completed-tile checkpoint before repair:", completed_before)
    print("Successful checkpoints preserved: True")
    print("Frozen v052 DASCH WCS/rotation/geometry authoritative: True")
    print("Exact frozen base-mosaic object identity guard: True")
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network --allow-detector-rerun')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
