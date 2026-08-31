from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3


ROOT = Path.cwd()

LIVE = ROOT / "state" / "poss1_identity_prospective.sqlite"

FROZEN = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.7_2026-08-21"
    / "inputs"
    / "state"
    / "poss1_identity_prospective.sqlite"
)

OUT = (
    ROOT
    / "research"
    / "POSS1_V027_LIVE_VS_FROZEN_SQLITE_SEMANTIC_AUDIT_2026-08-21.json"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def typed(value):
    if value is None:
        return ["null", None]

    if isinstance(value, bytes):
        return ["blob", value.hex()]

    if isinstance(value, bool):
        return ["bool", bool(value)]

    if isinstance(value, int):
        return ["int", str(value)]

    if isinstance(value, float):
        return ["float", repr(value)]

    return ["text", str(value)]


def canonical_row(row):
    return [
        typed(value)
        for value in row
    ]


def row_blob(row):
    return json.dumps(
        canonical_row(row),
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode("utf-8")


def table_content_fingerprint(con, table):
    quoted = '"' + table.replace('"', '""') + '"'

    cur = con.execute(
        f"SELECT * FROM {quoted}"
    )

    columns = [
        desc[0]
        for desc in cur.description
    ]

    encoded_rows = [
        row_blob(row)
        for row in cur.fetchall()
    ]

    # Row order in a SQLite table is not semantic.
    encoded_rows.sort()

    h = hashlib.sha256()

    h.update(
        json.dumps(
            columns,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    h.update(b"\n")

    for blob in encoded_rows:
        h.update(blob)
        h.update(b"\n")

    return {
        "columns": columns,
        "row_count": len(encoded_rows),
        "content_sha256": h.hexdigest(),
        "rows_canonical": [
            blob.decode("utf-8")
            for blob in encoded_rows
        ],
    }


def inspect(path: Path):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: database missing: {path}"
        )

    con = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro",
        uri=True,
    )

    quick_check = [
        str(row[0])
        for row in con.execute(
            "PRAGMA quick_check"
        ).fetchall()
    ]

    integrity_check = [
        str(row[0])
        for row in con.execute(
            "PRAGMA integrity_check"
        ).fetchall()
    ]

    pragmas = {}

    for name in (
        "application_id",
        "auto_vacuum",
        "encoding",
        "foreign_keys",
        "freelist_count",
        "journal_mode",
        "page_count",
        "page_size",
        "schema_version",
        "user_version",
    ):
        try:
            value = con.execute(
                f"PRAGMA {name}"
            ).fetchone()

            pragmas[name] = (
                value[0]
                if value
                else None
            )

        except sqlite3.Error as exc:
            pragmas[name] = (
                f"<error: {exc}>"
            )

    schema_rows = con.execute(
        """
        SELECT type,name,tbl_name,sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type,name,tbl_name
        """
    ).fetchall()

    schema = [
        {
            "type": row[0],
            "name": row[1],
            "table": row[2],
            "sql": row[3],
        }
        for row in schema_rows
    ]

    tables = [
        row[0]
        for row in con.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]

    table_data = {
        table:
            table_content_fingerprint(
                con,
                table,
            )
        for table in tables
    }

    con.close()

    return {
        "path": str(path),
        "file_sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "quick_check": quick_check,
        "integrity_check": integrity_check,
        "pragmas": pragmas,
        "schema": schema,
        "tables": table_data,
    }


print("=" * 100)
print("v0.2.7 SQLITE LIVE-vs-FROZEN SEMANTIC AUDIT")
print("=" * 100)
print("Read-only. No checkpoint writes are performed.")

live = inspect(LIVE)
frozen = inspect(FROZEN)

print()
print("Raw file identity:")
print("  live SHA256:  ", live["file_sha256"])
print("  frozen SHA256:", frozen["file_sha256"])
print("  live bytes:   ", live["bytes"])
print("  frozen bytes: ", frozen["bytes"])

print()
print("SQLite integrity:")
print("  live quick_check:  ", live["quick_check"])
print("  frozen quick_check:", frozen["quick_check"])
print("  live integrity:    ", live["integrity_check"])
print("  frozen integrity:  ", frozen["integrity_check"])

if live["quick_check"] != ["ok"]:
    raise SystemExit(
        "REFUSING: live database quick_check failed."
    )

if frozen["quick_check"] != ["ok"]:
    raise SystemExit(
        "REFUSING: frozen database quick_check failed."
    )

if live["integrity_check"] != ["ok"]:
    raise SystemExit(
        "REFUSING: live database integrity_check failed."
    )

if frozen["integrity_check"] != ["ok"]:
    raise SystemExit(
        "REFUSING: frozen database integrity_check failed."
    )


print()
print("=" * 100)
print("SCHEMA COMPARISON")
print("=" * 100)

schema_equal = (
    live["schema"]
    == frozen["schema"]
)

print("Schema identical:", schema_equal)

if not schema_equal:
    print()
    print("LIVE SCHEMA:")
    print(json.dumps(
        live["schema"],
        indent=2,
        sort_keys=True,
    ))

    print()
    print("FROZEN SCHEMA:")
    print(json.dumps(
        frozen["schema"],
        indent=2,
        sort_keys=True,
    ))


live_tables = set(
    live["tables"]
)

frozen_tables = set(
    frozen["tables"]
)

print()
print("Live tables:  ", sorted(live_tables))
print("Frozen tables:", sorted(frozen_tables))

table_set_equal = (
    live_tables
    == frozen_tables
)

print("Table set identical:", table_set_equal)


print()
print("=" * 100)
print("TABLE CONTENT COMPARISON")
print("=" * 100)

differences = {}

for table in sorted(
    live_tables | frozen_tables
):
    if (
        table not in live["tables"]
        or table not in frozen["tables"]
    ):
        differences[table] = {
            "reason":
                "table_present_on_one_side_only",
        }

        print()
        print(
            table,
            "TABLE EXISTS ON ONLY ONE SIDE",
        )
        continue

    a = live["tables"][table]
    b = frozen["tables"][table]

    equal = (
        a["columns"] == b["columns"]
        and a["row_count"] == b["row_count"]
        and a["content_sha256"]
            == b["content_sha256"]
    )

    print()
    print(table)
    print(
        "  rows:",
        a["row_count"],
        "/",
        b["row_count"],
    )
    print(
        "  live semantic SHA:  ",
        a["content_sha256"],
    )
    print(
        "  frozen semantic SHA:",
        b["content_sha256"],
    )
    print(
        "  semantically equal:",
        equal,
    )

    if not equal:
        live_rows = set(
            a["rows_canonical"]
        )

        frozen_rows = set(
            b["rows_canonical"]
        )

        only_live = sorted(
            live_rows - frozen_rows
        )

        only_frozen = sorted(
            frozen_rows - live_rows
        )

        differences[table] = {
            "live_row_count":
                a["row_count"],
            "frozen_row_count":
                b["row_count"],
            "live_content_sha256":
                a["content_sha256"],
            "frozen_content_sha256":
                b["content_sha256"],
            "only_live_count":
                len(only_live),
            "only_frozen_count":
                len(only_frozen),
            "only_live_first_20":
                only_live[:20],
            "only_frozen_first_20":
                only_frozen[:20],
        }


# Physical-layout PRAGMAs are deliberately reported separately.
# Differences here do not imply logical database differences.
layout_fields = {
    "freelist_count",
    "page_count",
    "schema_version",
    "journal_mode",
}

semantic_pragma_diffs = {}
layout_pragma_diffs = {}

for key in sorted(
    set(live["pragmas"])
    | set(frozen["pragmas"])
):
    av = live["pragmas"].get(key)
    bv = frozen["pragmas"].get(key)

    if av == bv:
        continue

    target = (
        layout_pragma_diffs
        if key in layout_fields
        else semantic_pragma_diffs
    )

    target[key] = {
        "live": av,
        "frozen": bv,
    }


print()
print("=" * 100)
print("PRAGMA DIFFERENCES")
print("=" * 100)

print("Physical/layout differences:")
print(json.dumps(
    layout_pragma_diffs,
    indent=2,
    sort_keys=True,
))

print()
print("Potentially semantic differences:")
print(json.dumps(
    semantic_pragma_diffs,
    indent=2,
    sort_keys=True,
))


semantic_equal = (
    schema_equal
    and table_set_equal
    and not differences
    and not semantic_pragma_diffs
)

report = {
    "operation":
        "read_only_v027_sqlite_semantic_equivalence_audit",

    "science_analysis_performed":
        False,

    "transient_detector_run":
        False,

    "live":
        {
            key: value
            for key, value in live.items()
            if key != "tables"
        },

    "frozen":
        {
            key: value
            for key, value in frozen.items()
            if key != "tables"
        },

    "table_summary": {
        table: {
            "live_rows":
                live["tables"].get(
                    table, {}
                ).get("row_count"),
            "frozen_rows":
                frozen["tables"].get(
                    table, {}
                ).get("row_count"),
            "live_semantic_sha256":
                live["tables"].get(
                    table, {}
                ).get("content_sha256"),
            "frozen_semantic_sha256":
                frozen["tables"].get(
                    table, {}
                ).get("content_sha256"),
        }
        for table in sorted(
            live_tables | frozen_tables
        )
    },

    "table_differences":
        differences,

    "layout_pragma_differences":
        layout_pragma_diffs,

    "semantic_pragma_differences":
        semantic_pragma_diffs,

    "semantic_database_equivalence":
        semantic_equal,
}

OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

print()
print("=" * 100)

if semantic_equal:
    print(
        "PASS: LIVE AND FROZEN v0.2.7 DATABASES "
        "ARE SEMANTICALLY EQUIVALENT"
    )
else:
    print(
        "STOP: LIVE AND FROZEN v0.2.7 DATABASES "
        "DIFFER SEMANTICALLY"
    )

print("=" * 100)

print("Report:", OUT)
print()
print("Raw SQLite byte identity is NOT used as the scientific criterion.")
print("No database was modified.")
print("No checkpoint state was changed.")
print("No identity job was added.")
print("No transient detector was run.")

if not semantic_equal:
    raise SystemExit(2)
