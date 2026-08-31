from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_wide_frozen_detector_v056.py"
PAYLOAD = ROOT / "tools" / "_execute_wide_frozen_detector_v056_dasch_ephemeral_url_fix3.payload.py"
STATE = ROOT / "results" / "wide_census_detector_execution_v056" / "state_v056.json"
FAILURES = ROOT / "results" / "wide_census_detector_execution_v056" / "terminal_tile_failures_v056.json"

EXPECTED_OLD_NORMALIZED_SHA = "1fb6ea46167a8a04014a11143b01daa78023ff873b3cf1a40fe332267f70ccf3"
EXPECTED_NEW_NORMALIZED_SHA = "ae6fb3ce427237b1fc4d62995a0d7a18e7503e2af4ccc2798224cd4a642c4e02"


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


def is_stale_dasch_transport_record(rec):
    if not isinstance(rec, dict):
        return False
    endpoint = str(rec.get("endpoint_key", ""))
    if not endpoint.startswith("DASCH:"):
        return False
    err = str(rec.get("error", ""))
    err_type = str(rec.get("error_type", ""))
    markers = (
        "URL contains glob characters",
        "X-Amz-",
        "Request has expired",
        "RequestExpired",
        "ExpiredToken",
        "SignatureDoesNotMatch",
        "403",
        "Forbidden",
    )
    return (
        err_type in {"FileNotFoundError", "PermissionError", "ClientResponseError", "RuntimeError"}
        and any(m in err for m in markers)
    )


def main():
    print("=" * 132)
    print("HEAVY DETECTOR v056 — DASCH EPHEMERAL SIGNED-URL TRANSPORT REPAIR 3")
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
            "REFUSING: installed v056 differs from expected fix2/fix3 source: "
            + current
        )
    if payload != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError("REFUSING: repair payload hash mismatch: " + payload)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v056_dasch_ephemeral_url_fix3_{stamp}"
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

        evidence = {}
        for key, rec in terminal.items():
            evidence[key] = rec
        for rec in state.get("last_cycle_failures", []) or []:
            key = str(rec.get("tile_key", ""))
            if key:
                evidence.setdefault(key, rec)

        if FAILURES.is_file():
            try:
                report = json.loads(FAILURES.read_text(encoding="utf-8"))
                for key, rec in (report.get("terminal") or {}).items():
                    evidence.setdefault(key, rec)
            except Exception:
                pass

        for key, rec in evidence.items():
            if not is_stale_dasch_transport_record(rec):
                continue
            if key in terminal:
                terminal.pop(key, None)
                cleared_terminal.append(key)
            if key in attempts:
                attempts.pop(key, None)
                cleared_attempts.append(key)

        state["status"] = "IN_PROGRESS"
        state["dasch_ephemeral_url_transport_repair_3"] = {
            "reason": (
                "DASCH mosaic_package baseFitsUrl is an AWS pre-signed transport URL "
                "with X-Amz-Expires=900; v056 had reused the expired URL from v054. "
                "The fsspec convenience layer then masked the underlying HTTP failure "
                "as a glob-character FileNotFoundError because the URL contains '?'."
            ),
            "new_transport": (
                "Refresh mosaic_package immediately before each DASCH endpoint open; "
                "require exact frozen geometry signature and baseFitsSize; then open "
                "the fresh signed URL directly through HTTPFileSystem."
            ),
            "cleared_terminal_tile_keys": sorted(cleared_terminal),
            "cleared_attempt_tile_keys": sorted(cleared_attempts),
            "successful_tile_checkpoints_preserved": True,
            "detector_or_threshold_change": False,
        }
        write_json(STATE, state)

    if FAILURES.is_file():
        current_state = (
            json.loads(STATE.read_text(encoding="utf-8"))
            if STATE.is_file()
            else {}
        )
        if not (current_state.get("terminal") or {}):
            FAILURES.unlink()

    print("\nSource guard: PASS")
    print("Pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("Stale DASCH terminal tiles cleared:", len(cleared_terminal))
    print("Stale DASCH attempt counters cleared:", len(cleared_attempts))
    for key in sorted(set(cleared_terminal + cleared_attempts)):
        print("  ", key)
    print("Successful tile checkpoints preserved: True")
    print("Frozen DASCH geometry/WCS remains authoritative: True")
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
