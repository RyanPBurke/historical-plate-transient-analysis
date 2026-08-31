from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import shutil

ROOT = Path.cwd()
STAGE = ROOT / "automation" / "stages" / "census_remaining_pair_physical_timing_v028cg.py"

OLD = '''def parse_time(value):
    value = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)
'''

NEW = '''def parse_time(value):
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        # Historical plate headers can contain overflow notation such as
        # HH:60 or 24:MM. Normalise by adding the fields as timedeltas to
        # midnight rather than silently clipping or discarding the record.
        match = re.fullmatch(
            r"(\\d{4})-(\\d{2})-(\\d{2})[T ](\\d+):(\\d+):(\\d+(?:\\.\\d+)?)([+-]\\d{2}:\\d{2})?",
            text,
        )
        if not match:
            raise
        year, month, day, hour, minute = map(int, match.groups()[:5])
        second = float(match.group(6))
        offset = match.group(7)
        if offset:
            sign = 1 if offset[0] == "+" else -1
            oh, om = map(int, offset[1:].split(":"))
            zone = dt.timezone(sign * dt.timedelta(hours=oh, minutes=om))
        else:
            zone = dt.timezone.utc
        parsed = dt.datetime(year, month, day, tzinfo=zone) + dt.timedelta(
            hours=hour, minutes=minute, seconds=second
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)
'''


def main():
    print("=" * 116)
    print("TRANSIENT AUTOMATION REPAIR v0.3.5b — LEGACY PLATE-TIME OVERFLOW NORMALISATION")
    print("=" * 116)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    if not STAGE.is_file():
        raise RuntimeError(f"Missing installed census stage: {STAGE}")
    text = STAGE.read_text(encoding="utf-8")
    if NEW in text and OLD not in text:
        ast.parse(text, filename=str(STAGE))
        print("Overflow-aware parser already installed.")
        print("REPAIR STATUS: PASS (NO CHANGE REQUIRED)")
        return
    if text.count(OLD) != 1:
        raise RuntimeError(f"REFUSING: expected one original parse_time block; found {text.count(OLD)}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v035b_time_parser_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(STAGE, backup / STAGE.name)
    patched = text.replace(OLD, NEW, 1)
    ast.parse(patched, filename=str(STAGE))
    STAGE.write_text(patched, encoding="utf-8", newline="\n")
    print(f"Patched stage: {STAGE}")
    print("Policy: normalise hour/minute/second overflow using timedeltas; never clip values")
    print(f"Backup: {backup}\n\nREPAIR STATUS: PASS")


if __name__ == "__main__":
    main()
