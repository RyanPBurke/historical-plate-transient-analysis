from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_exact_footprints_v052.py"
PAYLOAD = ROOT / "tools" / "_execute_exact_footprints_v052_parserfix1.payload.py"
CHECKPOINT = ROOT / "results" / "wide_census_exact_footprint_v052" / "checkpoint_v052.json"

EXPECTED_OLD_SHA = "0721adba691dc4292ca9df778244297e4f8f40a127ce85b55d90ae39f2866657"
EXPECTED_NEW_SHA = "0d02dd78a7b2f318e3b30b245ee0578007c0ff531707e04eed0042ac57c29a86"
APPLAUSE_KEY = "applause:solution_batch"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main():
    print("=" * 132)
    print("EXACT FOOTPRINT v052 — APPLAUSE TAP VOTABLE PARSER REPAIR 1")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (STAGE, PAYLOAD):
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {path}")

    current = sha(STAGE)
    if current not in (EXPECTED_OLD_SHA, EXPECTED_NEW_SHA):
        raise RuntimeError(
            "REFUSING: installed v052 stage differs from expected pre-fix/fixed versions: "
            + current
        )

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v052_tap_parserfix1_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    if CHECKPOINT.is_file():
        shutil.copy2(CHECKPOINT, backup / CHECKPOINT.name)

    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    if sha(STAGE) != EXPECTED_NEW_SHA:
        raise RuntimeError("Installed parser-fixed stage hash mismatch")

    reset = False
    if CHECKPOINT.is_file():
        cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        terminal = cp.setdefault("transport_terminal", {})
        attempts = cp.setdefault("attempts", {})

        previous_terminal = terminal.get(APPLAUSE_KEY)
        previous_attempts = attempts.get(APPLAUSE_KEY)

        if previous_terminal is not None or previous_attempts is not None:
            terminal.pop(APPLAUSE_KEY, None)
            attempts.pop(APPLAUSE_KEY, None)
            cp["last_error"] = None
            cp["status"] = "IN_PROGRESS"
            cp["parser_repair_1"] = {
                "reason": "Valid APPLAUSE IVOA VOTable was rejected by CSV-only parser",
                "cleared_transport_key": APPLAUSE_KEY,
                "previous_attempt_count": previous_attempts,
                "previous_terminal_record": previous_terminal,
            }
            write_json(CHECKPOINT, cp)
            reset = True

    print("Stage parser patch: PASS")
    print("Old stage SHA256:", EXPECTED_OLD_SHA)
    print("New stage SHA256:", EXPECTED_NEW_SHA)
    print("APPLAUSE parser checkpoint reset:", reset)
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
