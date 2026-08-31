from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import ast
import shutil
import sys


ROOT = Path.cwd()

TARGET = (
    ROOT
    / "tools"
    / "preflight_exact_poss_plate_cutouts_v028b.py"
)

VI25 = (
    ROOT
    / "research"
    / "poss1_plate_metadata.csv"
)


if not TARGET.is_file():
    raise SystemExit(
        f"REFUSING: missing target script: {TARGET}"
    )

if not VI25.is_file():
    raise SystemExit(
        f"REFUSING: missing VI/25 table: {VI25}"
    )


# ----------------------------------------------------------------------
# Locate the helper structurally rather than by fragile text quoting.
# ----------------------------------------------------------------------

text = TARGET.read_text(
    encoding="utf-8",
)

tree = ast.parse(
    text,
    filename=str(TARGET),
)

matches = [
    node
    for node in tree.body
    if (
        isinstance(node, ast.FunctionDef)
        and node.name == "get_vi25_record"
    )
]

if len(matches) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one "
        f"get_vi25_record(), found {len(matches)}"
    )

node = matches[0]

lines = text.splitlines(
    keepends=True
)

start = node.lineno - 1
end = node.end_lineno


replacement = '''def get_vi25_record(
    recno: int,
):
    key = int(recno)

    if key not in vi25_records:
        raise ValueError(
            f"VI/25 recno {key} absent from loaded mapping"
        )

    record = vi25_records[key]

    if int(record.recno) != key:
        raise ValueError(
            f"VI/25 mapping integrity failure: "
            f"key={key}, record.recno={record.recno}"
        )

    return record
'''


old_block = "".join(
    lines[start:end]
)

if (
    "for r in vi25_records"
    not in old_block
    and "record = vi25_records[key]"
    in old_block
):
    print(
        "PATCH ALREADY PRESENT"
    )

elif (
    "for r in vi25_records"
    not in old_block
):
    raise SystemExit(
        "REFUSING: get_vi25_record() does not "
        "match either known old or patched form."
    )

else:
    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    backup = (
        ROOT
        / "patch_backups"
        / f"pre_vi25_lookup_fix_{stamp}"
        / TARGET.name
    )

    backup.parent.mkdir(
        parents=True,
        exist_ok=False,
    )

    shutil.copy2(
        TARGET,
        backup,
    )

    lines[start:end] = [
        replacement
    ]

    TARGET.write_text(
        "".join(lines),
        encoding="utf-8",
    )

    print(
        "PATCHED:",
        TARGET,
    )

    print(
        "BACKUP: ",
        backup,
    )


# ----------------------------------------------------------------------
# Parse patched script before doing anything else.
# ----------------------------------------------------------------------

patched = TARGET.read_text(
    encoding="utf-8",
)

ast.parse(
    patched,
    filename=str(TARGET),
)

if (
    "record = vi25_records[key]"
    not in patched
):
    raise SystemExit(
        "REFUSING: patched dictionary lookup not found."
    )

print(
    "Patched script syntax: PASS"
)


# ----------------------------------------------------------------------
# Independently verify actual VI/25 runtime data model.
# ----------------------------------------------------------------------

sys.path.insert(
    0,
    str(
        ROOT
        / "src"
    ),
)

from transient_pipeline.poss1 import (
    load_vi25_records,
)


records = load_vi25_records(
    VI25
)

print()
print(
    "VI25 container:",
    type(records).__name__,
)

print(
    "VI25 count:    ",
    len(records),
)

if not isinstance(
    records,
    dict,
):
    raise SystemExit(
        "REFUSING: load_vi25_records() "
        "did not return a dictionary."
    )


wanted = (
    675,
    799,
    637,
    524,
    348,
    404,
    514,
    148,
    521,
    239,
)


for recno in wanted:
    if recno not in records:
        raise SystemExit(
            f"REFUSING: VI/25 recno {recno} absent."
        )

    record = records[
        recno
    ]

    if int(
        record.recno
    ) != recno:
        raise SystemExit(
            f"REFUSING: mapping integrity error "
            f"for recno {recno}."
        )

    print(
        f"  recno {recno}: PASS"
    )


print()
print(
    "EXACT-TEN VI/25 LOOKUP SANITY: PASS"
)

print(
    "Frozen pipeline source unchanged."
)

print(
    "Frozen detector unchanged."
)
