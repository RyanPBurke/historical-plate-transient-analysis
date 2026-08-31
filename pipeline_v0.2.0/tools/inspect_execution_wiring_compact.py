from __future__ import annotations

from pathlib import Path
import ast
import csv
import hashlib
import re


ROOT = Path.cwd()

HANDOFF = (
    ROOT
    / "research"
    / "SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv"
)

RUNNER = (
    ROOT
    / "src"
    / "transient_pipeline"
    / "runner.py"
)

CLI = (
    ROOT
    / "src"
    / "transient_pipeline"
    / "cli.py"
)

DETECTOR_MANIFEST = (
    ROOT
    / "research_snapshots"
    / "detector_freeze_v0.2.8_2026-08-21"
    / "freeze_manifest.json"
)

OUT = (
    ROOT
    / "research"
    / "EXECUTION_WIRING_COMPACT_2026-08-21.txt"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)
    return h.hexdigest()


def require(path: Path):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )


for path in (
    HANDOFF,
    RUNNER,
    CLI,
    DETECTOR_MANIFEST,
):
    require(path)


with HANDOFF.open(
    "r",
    encoding="utf-8-sig",
    newline="",
) as fh:
    rows = list(csv.DictReader(fh))


if len(rows) != 74:
    raise SystemExit(
        f"REFUSING: handoff rows={len(rows)}, expected 74"
    )


columns = list(rows[0].keys())

poss_rows = [
    r
    for r in rows
    if str(
        r.get("poss_exposure_id")
        or ""
    ).startswith("POSS-I:")
]

if len(poss_rows) != 47:
    raise SystemExit(
        f"REFUSING: POSS rows={len(poss_rows)}, expected 47"
    )


# ----------------------------------------------------------------------
# Find every plausible coordinate/target field.
# ----------------------------------------------------------------------

coord_terms = (
    "ra",
    "dec",
    "target",
    "coord",
    "centre",
    "center",
)

coord_fields = [
    c
    for c in columns
    if any(
        term in c.lower()
        for term in coord_terms
    )
]

coord_counts = {
    c: sum(
        bool(str(r.get(c) or "").strip())
        for r in poss_rows
    )
    for c in coord_fields
}


# Likely numeric RA/Dec columns.
ra_fields = [
    c
    for c in coord_fields
    if re.search(
        r"(^|_)ra($|_|deg)",
        c.lower(),
    )
]

dec_fields = [
    c
    for c in coord_fields
    if re.search(
        r"(^|_)dec($|_|deg)",
        c.lower(),
    )
]


def numeric_count(field):
    n = 0

    for row in poss_rows:
        value = str(
            row.get(field)
            or ""
        ).strip()

        if not value:
            continue

        try:
            float(value)
            n += 1
        except ValueError:
            pass

    return n


# ----------------------------------------------------------------------
# Extract only relevant runner functions.
# ----------------------------------------------------------------------

runner_text = RUNNER.read_text(
    encoding="utf-8",
)

runner_tree = ast.parse(
    runner_text,
    filename=str(RUNNER),
)

runner_functions = []

for node in runner_tree.body:
    if not isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):
        continue

    segment = (
        ast.get_source_segment(
            runner_text,
            node,
        )
        or ""
    )

    if (
        "starglass" in node.name.lower()
        or "manifest" in node.name.lower()
        or "analyze_fits_bytes" in segment
        or "ra_deg" in segment
        or "dec_deg" in segment
    ):
        runner_functions.append(
            (
                node.name,
                node.lineno,
                node.end_lineno,
                segment,
            )
        )


# ----------------------------------------------------------------------
# Extract compact CLI context around starglass only.
# ----------------------------------------------------------------------

cli_lines = CLI.read_text(
    encoding="utf-8",
).splitlines()

cli_interesting = set()

for i, line in enumerate(
    cli_lines,
    start=1,
):
    if "starglass" not in line.lower():
        continue

    for n in range(
        max(1, i - 6),
        min(len(cli_lines), i + 18) + 1,
    ):
        cli_interesting.add(n)


# ----------------------------------------------------------------------
# Existing manifest-like CSV headers, without dumping contents.
# ----------------------------------------------------------------------

manifest_headers = []

for root_name in (
    "examples",
    "research",
    "results",
):
    base = ROOT / root_name

    if not base.exists():
        continue

    for path in base.rglob("*.csv"):
        name = path.name.lower()

        if not any(
            term in name
            for term in (
                "manifest",
                "starglass",
                "detector",
                "pixel",
            )
        ):
            continue

        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
        except Exception as exc:
            header = [
                f"<ERROR {type(exc).__name__}: {exc}>"
            ]

        manifest_headers.append(
            (
                str(
                    path.relative_to(ROOT)
                ).replace("\\", "/"),
                header,
            )
        )


# ----------------------------------------------------------------------
# Write detailed report to disk.
# ----------------------------------------------------------------------

out = []

out.append(
    "v0.2.8 EXECUTION WIRING — COMPACT RECOVERY"
)
out.append("=" * 100)
out.append("")
out.append(
    f"Handoff: {HANDOFF.relative_to(ROOT)}"
)
out.append(
    f"Handoff SHA256: {sha256(HANDOFF)}"
)
out.append("Rows: 74")
out.append("POSS-involving rows: 47")
out.append("")

out.append("HANDOFF COLUMNS")
out.append("-" * 100)

for n, column in enumerate(
    columns,
    start=1,
):
    out.append(
        f"{n:3d}. {column}"
    )


out.append("")
out.append("COORDINATE/TARGET FIELDS")
out.append("-" * 100)

if coord_fields:
    for field in coord_fields:
        out.append(
            f"{field}: "
            f"nonblank={coord_counts[field]}/47, "
            f"numeric={numeric_count(field)}/47"
        )
else:
    out.append("<NONE>")


out.append("")
out.append("RA-LIKE FIELDS")
out.append("-" * 100)
out.extend(
    ra_fields
    or ["<NONE>"]
)

out.append("")
out.append("DEC-LIKE FIELDS")
out.append("-" * 100)
out.extend(
    dec_fields
    or ["<NONE>"]
)


out.append("")
out.append("FIRST 8 POSS PAIR/TARGET ROWS")
out.append("-" * 100)

display_fields = [
    c
    for c in (
        "canonical_order",
        "legacy_rank",
        "pair_key",
        "exposure_a",
        "exposure_b",
        "poss_exposure_id",
        "true_wcs_intersection",
        "overlap_start_utc",
        "overlap_end_utc",
        "recomputed_actual_exposure_overlap_s",
    )
    if c in columns
]

for field in coord_fields:
    if field not in display_fields:
        display_fields.append(field)


for row in poss_rows[:8]:
    out.append("")

    for field in display_fields:
        value = str(
            row.get(field)
            or ""
        ).strip()

        if value:
            out.append(
                f"{field}: {value}"
            )


out.append("")
out.append("RELEVANT runner.py FUNCTIONS")
out.append("-" * 100)

if runner_functions:
    for (
        name,
        lo,
        hi,
        segment,
    ) in runner_functions:
        out.append("")
        out.append(
            f"### {name} lines {lo}-{hi}"
        )
        out.append(segment)
else:
    out.append("<NONE FOUND>")


out.append("")
out.append("RELEVANT cli.py STARGLASS CONTEXT")
out.append("-" * 100)

for n in sorted(
    cli_interesting
):
    out.append(
        f"{n:5d}: {cli_lines[n - 1]}"
    )


out.append("")
out.append("EXISTING MANIFEST-LIKE CSV HEADERS")
out.append("-" * 100)

if manifest_headers:
    for path, header in manifest_headers:
        out.append("")
        out.append(path)
        out.append(
            ",".join(header)
        )
else:
    out.append("<NONE>")


out.append("")
out.append("NO ARCHIVE REQUEST WAS MADE.")
out.append("NO HISTORICAL PIXEL WAS ANALYSED.")
out.append("NO DETECTOR JOB WAS EXECUTED.")


OUT.write_text(
    "\n".join(out) + "\n",
    encoding="utf-8",
)


# ----------------------------------------------------------------------
# Intentionally short terminal output.
# ----------------------------------------------------------------------

print("=" * 72)
print("EXECUTION-WIRING RECOVERY COMPLETE")
print("=" * 72)
print("74-row handoff: PASS")
print("POSS rows:      47")
print()
print("Coordinate/target fields:")

if not coord_fields:
    print("  NONE")
else:
    for field in coord_fields:
        print(
            f"  {field}: "
            f"{coord_counts[field]}/47 nonblank, "
            f"{numeric_count(field)}/47 numeric"
        )

print()
print("Relevant runner functions:")
if runner_functions:
    for name, lo, hi, _ in runner_functions:
        print(
            f"  {name} ({lo}-{hi})"
        )
else:
    print("  NONE")

print()
print(
    "Manifest-like CSVs found:",
    len(manifest_headers),
)

print()
print("Detailed report:")
print(" ", OUT)
print()
print("No archive request.")
print("No historical detector execution.")
