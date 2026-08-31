from __future__ import annotations

from pathlib import Path
import hashlib
import inspect
import sqlite3

import transient_pipeline
import transient_pipeline.poss1 as poss1
import transient_pipeline.poss1_skyview as skyview


def sha256_file(path):
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


print("=" * 88)
print("v0.2.7 RUNTIME / FOUR-TERMINAL DIAGNOSTIC")
print("=" * 88)

print()
print("PACKAGE / MODULE RUNTIME PATHS")
print("-" * 88)
print("transient_pipeline version:", getattr(transient_pipeline, "__version__", "<none>"))
print("transient_pipeline:", Path(transient_pipeline.__file__).resolve())
print("poss1:             ", Path(poss1.__file__).resolve())
print("poss1_skyview:     ", Path(skyview.__file__).resolve())

runtime_src = Path(skyview.__file__).resolve()
working_src = Path("src/transient_pipeline/poss1_skyview.py").resolve()

print()
print("SOURCE HASH COMPARISON")
print("-" * 88)
print("runtime source :", runtime_src)
print("runtime SHA256 :", sha256_file(runtime_src))
print("working source :", working_src)
print("working SHA256 :", sha256_file(working_src))
print("same file      :", runtime_src == working_src)
print("same SHA256    :", sha256_file(runtime_src) == sha256_file(working_src))

needle = "SkyView descriptor/HHH center disagreement"
gate = (
    "if descriptor_hhh_center_sep > "
    "descriptor_hhh_center_tolerance_arcsec:"
)

runtime_text = runtime_src.read_text(encoding="utf-8")

print()
print("RUNTIME CENTRE-GATE CHECK")
print("-" * 88)
print("old error string present:", needle in runtime_text)
print("old hard condition present:", gate in runtime_text)
print(
    "v0.2.7 diagnostic policy present:",
    "diagnostic_only_v0.2.7" in runtime_text
)

print()
print("FUNCTIONS CONTAINING HHH FALLBACK")
print("-" * 88)

found = 0
for name, obj in vars(skyview).items():
    if not inspect.isfunction(obj):
        continue
    try:
        src = inspect.getsource(obj)
    except Exception:
        continue

    if 'hhh_url = f"{raw_dir}/{wanted}.hhh"' in src:
        found += 1
        print("function:", name)
        print("  old error string:", needle in src)
        print("  old hard condition:", gate in src)
        print(
            "  diagnostic comment:",
            "diagnostic provenance" in src
        )

print("matching functions:", found)

print()
print("CURRENT CHECKPOINT FAILURES")
print("-" * 88)

db = sqlite3.connect("state/poss1_identity_prospective.sqlite")
db.row_factory = sqlite3.Row

rows = db.execute(
    """
    SELECT job_key,status,attempts,last_error,updated_at
    FROM jobs
    WHERE stage='poss1-identity:prospective_production'
      AND status != 'succeeded'
    ORDER BY job_key
    """
).fetchall()

print("non-succeeded rows:", len(rows))

for r in rows:
    print()
    print(r["job_key"])
    print(" status:   ", r["status"])
    print(" attempts: ", r["attempts"])
    print(" updated:  ", r["updated_at"])
    print(" error:    ", r["last_error"])

print()
print("FAILED JOB RESULT/PAYLOAD DETAILS")
print("-" * 88)

# First inspect schema so we don't assume optional columns.
cols = [
    r[1]
    for r in db.execute("PRAGMA table_info(jobs)").fetchall()
]

print("jobs columns:", ", ".join(cols))

wanted_cols = [
    c for c in
    ("job_key", "status", "attempts", "payload", "result", "last_error")
    if c in cols
]

sql = (
    "SELECT " + ",".join(wanted_cols) +
    " FROM jobs "
    "WHERE stage=? AND status!='succeeded' ORDER BY job_key"
)

for r in db.execute(
    sql,
    ("poss1-identity:prospective_production",)
).fetchall():
    print()
    for c in wanted_cols:
        value = r[c]
        if value is not None and len(str(value)) > 3000:
            value = str(value)[:3000] + "...<truncated>"
        print(f"{c}: {value}")

db.close()

print()
print("No checkpoint state was changed.")
print("No transient detector was run.")
