from __future__ import annotations

from pathlib import Path
from datetime import datetime
import hashlib
import shutil


ROOT = Path.cwd()
TARGET = ROOT / "tools" / "run_v028_nine_identity_extension.py"

if not TARGET.is_file():
    raise SystemExit(f"REFUSING: missing target: {TARGET}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


before_sha = sha256(TARGET)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(
    f"{TARGET.stem}.pre_semantic_guard_patch_{stamp}{TARGET.suffix}"
)

shutil.copy2(TARGET, backup)

text = TARGET.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# 1. Add the semantic-equivalence audit path.
# ----------------------------------------------------------------------

old = '''V027_FROZEN_RESULT = (
    V027_FREEZE
    / "inputs"
    / "results"
    / "poss1_identity_preflight.csv"
)

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
'''

new = '''V027_FROZEN_RESULT = (
    V027_FREEZE
    / "inputs"
    / "results"
    / "poss1_identity_preflight.csv"
)

V027_DB_SEMANTIC_AUDIT = (
    ROOT
    / "research"
    / "POSS1_V027_LIVE_VS_FROZEN_SQLITE_SEMANTIC_AUDIT_2026-08-21.json"
)

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
'''

if text.count(old) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one DB-audit insertion point; "
        f"found {text.count(old)}"
    )

text = text.replace(old, new, 1)


# ----------------------------------------------------------------------
# 2. Require the just-produced semantic audit.
# ----------------------------------------------------------------------

old = '''    V027_FROZEN_DB,
    V027_FROZEN_RESULT,
    SKY,
'''

new = '''    V027_FROZEN_DB,
    V027_FROZEN_RESULT,
    V027_DB_SEMANTIC_AUDIT,
    SKY,
'''

if text.count(old) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one required-file insertion point; "
        f"found {text.count(old)}"
    )

text = text.replace(old, new, 1)


# ----------------------------------------------------------------------
# 3. Replace the invalid raw SQLite equality requirement.
#
# The semantic audit itself is accepted only if:
#   - semantic_database_equivalence == True
#   - it refers to the exact current live DB SHA
#   - it refers to the exact frozen DB SHA
#
# Thus we are not weakening provenance; we are changing the comparison
# from physical SQLite page identity to logical database identity.
# ----------------------------------------------------------------------

old = '''if v027_db_before != frozen_db_sha:
    raise SystemExit(
        "REFUSING: live v0.2.7 checkpoint differs from frozen copy."
    )

if v027_result_before != frozen_result_sha:
    raise SystemExit(
        "REFUSING: live v0.2.7 result differs from frozen copy."
    )
'''

new = '''db_semantic_audit = json.loads(
    V027_DB_SEMANTIC_AUDIT.read_text(
        encoding="utf-8",
    )
)

if not db_semantic_audit.get(
    "semantic_database_equivalence",
    False,
):
    raise SystemExit(
        "REFUSING: v0.2.7 SQLite semantic-equivalence audit did not pass."
    )

audit_live_sha = (
    db_semantic_audit.get("live", {})
    .get("file_sha256")
)

audit_frozen_sha = (
    db_semantic_audit.get("frozen", {})
    .get("file_sha256")
)

if audit_live_sha != v027_db_before:
    raise SystemExit(
        "REFUSING: current live v0.2.7 DB is not the DB "
        "covered by the semantic-equivalence audit."
    )

if audit_frozen_sha != frozen_db_sha:
    raise SystemExit(
        "REFUSING: current frozen v0.2.7 DB is not the DB "
        "covered by the semantic-equivalence audit."
    )

print(
    " v0.2.7 SQLite semantic equivalence: PASS "
    "(exact audited live/frozen file versions)"
)

if v027_result_before != frozen_result_sha:
    raise SystemExit(
        "REFUSING: live v0.2.7 result differs from frozen copy."
    )
'''

if text.count(old) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one raw-DB guard block; "
        f"found {text.count(old)}"
    )

text = text.replace(old, new, 1)


TARGET.write_text(
    text,
    encoding="utf-8",
)

after_sha = sha256(TARGET)

print("PATCH APPLIED")
print("Target :", TARGET)
print("Backup :", backup)
print("Before :", before_sha)
print("After  :", after_sha)
print()
print(
    "Changed criterion: frozen-vs-live SQLite comparison "
    "is now semantic rather than byte-for-byte."
)
print(
    "Unchanged criterion: the live v0.2.7 DB must remain "
    "byte-for-byte unchanged throughout the v0.2.8 extension."
)
print("No detector was run by this patch.")
