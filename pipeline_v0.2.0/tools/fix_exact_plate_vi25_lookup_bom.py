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
        f"REFUSING: target missing: {TARGET}"
    )

if not VI25.is_file():
    raise SystemExit(
        f"REFUSING: VI/25 table missing: {VI25}"
    )


# ------------------------------------------------------------------
# Read source while explicitly consuming an optional UTF-8 BOM.
# ------------------------------------------------------------------

raw = TARGET.read_bytes()

had_bom = raw.startswith(
    b"\xef\xbb\xbf"
)

text = raw.decode(
    "utf-8-sig"
)

print(
    "Target UTF-8 BOM:",
    had_bom,
)


# Must be valid once the BOM is removed from the decoded string.
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
        f"get_vi25_record(); found {len(matches)}"
    )


node = matches[0]

lines = text.splitlines(
    keepends=True
)

start = node.lineno - 1
end = node.end_lineno

old_block = "".join(
    lines[start:end]
)


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


already_patched = (
    "record = vi25_records[key]"
    in old_block
    and "for r in vi25_records"
    not in old_block
)


if already_patched:
    print(
        "Lookup patch already present."
    )

else:
    if (
        "for r in vi25_records"
        not in old_block
        or "r.recno"
        not in old_block
    ):
        print()
        print(
            "Unexpected current function:"
        )
        print(
            old_block
        )

        raise SystemExit(
            "REFUSING: helper does not match "
            "the known faulty implementation."
        )


    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    backup = (
        ROOT
        / "patch_backups"
        / f"pre_vi25_lookup_bom_fix_{stamp}"
        / TARGET.name
    )

    backup.parent.mkdir(
        parents=True,
        exist_ok=False,
    )

    # Preserve original bytes, including BOM.
    backup.write_bytes(
        raw
    )

    lines[start:end] = [
        replacement
    ]

    patched_text = "".join(
        lines
    )

    # Prove resulting source parses before writing it.
    ast.parse(
        patched_text,
        filename=str(TARGET),
    )

    # Deliberately plain UTF-8: no BOM.
    TARGET.write_bytes(
        patched_text.encode(
            "utf-8"
        )
    )

    print(
        "Lookup patch: PASS"
    )

    print(
        "Backup:",
        backup,
    )


# ------------------------------------------------------------------
# Independent reread and structural verification.
# ------------------------------------------------------------------

new_raw = TARGET.read_bytes()

if new_raw.startswith(
    b"\xef\xbb\xbf"
):
    raise SystemExit(
        "REFUSING: target still contains UTF-8 BOM."
    )


new_text = new_raw.decode(
    "utf-8"
)

ast.parse(
    new_text,
    filename=str(TARGET),
)


if (
    "record = vi25_records[key]"
    not in new_text
):
    raise SystemExit(
        "REFUSING: dictionary lookup absent "
        "after patch."
    )

if (
    "for r in vi25_records"
    in ast.get_source_segment(
        new_text,
        next(
            n
            for n in ast.parse(
                new_text
            ).body
            if (
                isinstance(n, ast.FunctionDef)
                and n.name == "get_vi25_record"
            )
        ),
    )
):
    raise SystemExit(
        "REFUSING: faulty iteration remains."
    )


print(
    "Target syntax: PASS"
)

print(
    "Target BOM removed: PASS"
)


# ------------------------------------------------------------------
# Verify the real VI/25 runtime data model and exact ten records.
# ------------------------------------------------------------------

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


if not isinstance(
    records,
    dict,
):
    raise SystemExit(
        "REFUSING: load_vi25_records() "
        f"returned {type(records).__name__}, "
        "expected dict."
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


print()
print(
    "VI/25 runtime type:",
    type(records).__name__,
)

print(
    "VI/25 records:",
    len(records),
)


for recno in wanted:
    if recno not in records:
        raise SystemExit(
            f"REFUSING: recno {recno} missing."
        )

    record = records[
        recno
    ]

    if int(
        record.recno
    ) != recno:
        raise SystemExit(
            f"REFUSING: recno mapping "
            f"integrity failure at {recno}."
        )

    print(
        f"  recno {recno}: PASS"
    )


print()
print(
    "EXACT-TEN VI/25 LOOKUP SANITY: PASS"
)

print(
    "Frozen pipeline source: UNCHANGED"
)

print(
    "Frozen detector source: UNCHANGED"
)
