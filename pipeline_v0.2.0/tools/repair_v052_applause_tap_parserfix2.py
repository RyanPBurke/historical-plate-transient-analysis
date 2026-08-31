from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import py_compile
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "execute_exact_footprints_v052.py"
PAYLOAD = ROOT / "tools" / "_execute_exact_footprints_v052_parserfix2.payload.py"
CHECKPOINT = ROOT / "results" / "wide_census_exact_footprint_v052" / "checkpoint_v052.json"

EXPECTED_OLD_NORMALIZED_SHA = "0721adba691dc4292ca9df778244297e4f8f40a127ce85b55d90ae39f2866657"
EXPECTED_NEW_NORMALIZED_SHA = "0d02dd78a7b2f318e3b30b245ee0578007c0ff531707e04eed0042ac57c29a86"
APPLAUSE_KEY = "applause:solution_batch"


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalized_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def raw_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main():
    print("=" * 132)
    print("EXACT FOOTPRINT v052 — APPLAUSE TAP VOTABLE PARSER REPAIR 2")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("Guard compares newline-normalized source, so LF/CRLF differences are not treated as code changes.\n")

    for path in (STAGE, PAYLOAD):
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {path}")

    current_raw = raw_sha(STAGE)
    current_norm = normalized_sha(STAGE)

    print("Installed stage raw SHA256:", current_raw)
    print("Installed stage normalized SHA256:", current_norm)

    if current_norm not in (
        EXPECTED_OLD_NORMALIZED_SHA,
        EXPECTED_NEW_NORMALIZED_SHA,
    ):
        raise RuntimeError(
            "REFUSING: installed v052 source differs semantically from both "
            "the expected pre-fix and fixed source after newline normalization: "
            + current_norm
        )

    payload_norm = normalized_sha(PAYLOAD)
    if payload_norm != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError(
            "REFUSING: parser-fix payload normalized SHA mismatch: "
            + payload_norm
        )

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v052_tap_parserfix2_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    if CHECKPOINT.is_file():
        shutil.copy2(CHECKPOINT, backup / CHECKPOINT.name)

    # Preserve the platform's normal text-line convention. Verification below
    # is normalized, so the scientific/source identity is stable cross-platform.
    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    installed_norm = normalized_sha(STAGE)
    if installed_norm != EXPECTED_NEW_NORMALIZED_SHA:
        raise RuntimeError(
            "Installed parser-fixed stage normalized SHA mismatch: "
            + installed_norm
        )

    reset = False
    previous_attempts = None
    if CHECKPOINT.is_file():
        cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        terminal = cp.setdefault("transport_terminal", {})
        attempts = cp.setdefault("attempts", {})

        previous_terminal = terminal.get(APPLAUSE_KEY)
        previous_attempts = attempts.get(APPLAUSE_KEY)

        if previous_terminal is not None or previous_attempts is not None:
            terminal.pop(APPLAUSE_KEY, None)
            attempts.pop(APPLAUSE_KEY, None)

            last_error = cp.get("last_error")
            if isinstance(last_error, dict) and last_error.get("key") == APPLAUSE_KEY:
                cp["last_error"] = None

            cp["status"] = "IN_PROGRESS"
            cp["parser_repair_2"] = {
                "reason": (
                    "Pre-fix worker received a valid APPLAUSE IVOA VOTable but "
                    "accepted CSV only; raw line-ending differences are separately "
                    "normalized by this installer guard."
                ),
                "cleared_transport_key": APPLAUSE_KEY,
                "previous_attempt_count": previous_attempts,
                "previous_terminal_record": previous_terminal,
                "pre_patch_raw_sha256": current_raw,
                "pre_patch_normalized_sha256": current_norm,
                "post_patch_normalized_sha256": installed_norm,
            }
            write_json(CHECKPOINT, cp)
            reset = True

    print("\nSource guard: PASS")
    print("Expected pre-fix normalized SHA256:", EXPECTED_OLD_NORMALIZED_SHA)
    print("Fixed normalized SHA256:", EXPECTED_NEW_NORMALIZED_SHA)
    print("Installed fixed normalized SHA256:", installed_norm)
    print("APPLAUSE parser checkpoint reset:", reset)
    print("Previous APPLAUSE attempt count:", previous_attempts)
    print("\nREPAIR STATUS: PASS")
    print("\nResume:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
