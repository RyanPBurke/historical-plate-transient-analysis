from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import re


ROOT = Path.cwd()

CONTROL = (
    ROOT / "research" /
    "POSS1_V028_XE520_NATIVE_PIXEL_CONTROL_2026-08-21.json"
)

HANDOFF = (
    ROOT / "research" /
    "SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv"
)

CANONICAL = (
    ROOT / "research" /
    "canonical_sub5_pairs_74.csv"
)

OUT_JSON = (
    ROOT / "research" /
    "SUB5_V028_TRUE_WCS_GEOMETRY_RECOVERY_2026-08-21.json"
)

OUT_TXT = (
    ROOT / "research" /
    "SUB5_V028_TRUE_WCS_GEOMETRY_RECOVERY_2026-08-21.txt"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


for p in (
    CONTROL,
    HANDOFF,
    CANONICAL,
):
    if not p.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {p}"
        )


# ------------------------------------------------------------------
# 1. Assert the native-pixel control really passed.
# ------------------------------------------------------------------

control = json.loads(
    CONTROL.read_text(
        encoding="utf-8"
    )
)

best = control.get(
    "best_alignment"
) or {}


required_control = {
    "orientation":
        "rot0",

    "exact_value_fraction":
        1.0,

    "rounded_value_fraction":
        1.0,
}


for key, expected in required_control.items():
    actual = best.get(key)

    if actual != expected:
        raise SystemExit(
            f"REFUSING: XE520 control changed: "
            f"{key}={actual!r}, expected {expected!r}"
        )


if abs(
    float(
        best.get(
            "linear_slope_native_from_fits"
        )
    ) - 1.0
) > 1e-10:
    raise SystemExit(
        "REFUSING: XE520 native/STScI slope "
        "is no longer unity."
    )


if abs(
    float(
        best.get(
            "linear_intercept_native_from_fits"
        )
    )
) > 1e-8:
    raise SystemExit(
        "REFUSING: XE520 native/STScI "
        "intercept is non-zero."
    )


if float(
    control.get(
        "wcs_roundtrip_sep_arcsec"
    )
) > 1e-6:
    raise SystemExit(
        "REFUSING: XE520 WCS roundtrip changed."
    )


# ------------------------------------------------------------------
# 2. Inspect current 74-row handoff and identify POSS rows.
# ------------------------------------------------------------------

handoff = read_csv(
    HANDOFF
)

canonical = read_csv(
    CANONICAL
)


if len(handoff) != 74:
    raise SystemExit(
        f"REFUSING: handoff row count is {len(handoff)}, expected 74."
    )

if len(canonical) != 74:
    raise SystemExit(
        f"REFUSING: canonical row count is {len(canonical)}, expected 74."
    )


columns = list(
    handoff[0].keys()
)


geometry_columns = [
    c
    for c in columns
    if any(
        token in c.lower()
        for token in (
            "wcs",
            "overlap",
            "footprint",
            "polygon",
            "corner",
            "bounds",
            "intersection",
        )
    )
]


poss_rows = []

for r in handoff:
    combined = " ".join(
        str(v or "")
        for v in r.values()
    )

    if "POSS-I:" in combined:
        poss_rows.append(
            r
        )


if len(poss_rows) != 47:
    raise SystemExit(
        f"REFUSING: POSS pair-row count is "
        f"{len(poss_rows)}, expected 47."
    )


# ------------------------------------------------------------------
# 3. Search the repository for the code/path that created the
#    true-WCS intersection fields.
# ------------------------------------------------------------------

SEARCH_ROOTS = (
    ROOT / "src",
    ROOT / "tools",
    ROOT / "research",
    ROOT / "work",
)

TEXT_SUFFIXES = {
    ".py",
    ".ps1",
    ".md",
    ".txt",
    ".json",
}


patterns = [
    re.compile(
        r"true_wcs_intersection",
        re.I,
    ),

    re.compile(
        r"true_wcs_overlap_fraction",
        re.I,
    ),

    re.compile(
        r"calc_footprint",
        re.I,
    ),

    re.compile(
        r"footprint",
        re.I,
    ),

    re.compile(
        r"polygon",
        re.I,
    ),

    re.compile(
        r"intersection",
        re.I,
    ),

    re.compile(
        r"overlap_fraction",
        re.I,
    ),

    re.compile(
        r"pixel_to_world",
        re.I,
    ),

    re.compile(
        r"world_to_pixel",
        re.I,
    ),

    re.compile(
        r"all_pix2world",
        re.I,
    ),

    re.compile(
        r"all_world2pix",
        re.I,
    ),

    re.compile(
        r"spherical_geometry",
        re.I,
    ),

    re.compile(
        r"shapely",
        re.I,
    ),
]


ignore_parts = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "evidence",
}


hits = []


for base in SEARCH_ROOTS:
    if not base.exists():
        continue

    for path in base.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        if any(
            part in ignore_parts
            for part in path.parts
        ):
            continue

        # Avoid recursively auditing the report being created.
        if path in (
            OUT_JSON,
            OUT_TXT,
        ):
            continue

        try:
            text = path.read_text(
                encoding="utf-8-sig",
                errors="replace",
            )
        except Exception:
            continue

        lines = text.splitlines()

        matched_lines = []

        for n, line in enumerate(
            lines,
            start=1,
        ):
            matched = [
                p.pattern
                for p in patterns
                if p.search(line)
            ]

            if not matched:
                continue

            lo = max(
                1,
                n - 4,
            )

            hi = min(
                len(lines),
                n + 4,
            )

            context = [
                {
                    "line":
                        k,

                    "text":
                        lines[
                            k - 1
                        ],
                }
                for k in range(
                    lo,
                    hi + 1,
                )
            ]

            matched_lines.append({
                "line":
                    n,

                "matched_patterns":
                    matched,

                "context":
                    context,
            })

        if matched_lines:
            hits.append({
                "path":
                    str(
                        path.relative_to(ROOT)
                    ),

                "sha256":
                    sha256_file(path),

                "matches":
                    matched_lines,
            })


# ------------------------------------------------------------------
# 4. Search CSV headers across research/results/work for any hidden
#    footprint/polygon products without dumping their contents.
# ------------------------------------------------------------------

csv_inventory = []


for base in (
    ROOT / "research",
    ROOT / "results",
    ROOT / "work",
):
    if not base.exists():
        continue

    for path in base.rglob(
        "*.csv"
    ):
        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as fh:
                reader = csv.reader(
                    fh
                )

                header = next(
                    reader,
                    [],
                )
        except Exception:
            continue

        relevant = [
            c
            for c in header
            if any(
                token in c.lower()
                for token in (
                    "wcs",
                    "overlap",
                    "footprint",
                    "polygon",
                    "corner",
                    "bounds",
                    "intersection",
                )
            )
        ]

        if relevant:
            csv_inventory.append({
                "path":
                    str(
                        path.relative_to(ROOT)
                    ),

                "sha256":
                    sha256_file(path),

                "relevant_columns":
                    relevant,
            })


# ------------------------------------------------------------------
# 5. Compact per-POSS-row geometry state.
# ------------------------------------------------------------------

poss_geometry = []


for r in poss_rows:
    entry = {}

    for key in (
        "canonical_order",
        "legacy_rank",
        "source_id",
        "partner_source_id",
        "plate_a",
        "plate_b",
        "poss_exposure_id",
        "true_wcs_intersection",
        "true_wcs_overlap_fraction",
        "actual_overlap_s",
        "overlap_start_utc",
        "overlap_end_utc",
    ):
        if key in r:
            entry[
                key
            ] = r.get(
                key,
                "",
            )

    for key in geometry_columns:
        if (
            key not in entry
            and str(
                r.get(
                    key,
                    ""
                )
            ).strip()
        ):
            entry[
                key
            ] = r[
                key
            ]

    poss_geometry.append(
        entry
    )


report = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "operation":
        "recover_true_wcs_geometry_v028",

    "inputs": {
        "xe520_control":
            {
                "path":
                    str(CONTROL),

                "sha256":
                    sha256_file(
                        CONTROL
                    ),
            },

        "handoff":
            {
                "path":
                    str(HANDOFF),

                "sha256":
                    sha256_file(
                        HANDOFF
                    ),
            },

        "canonical":
            {
                "path":
                    str(CANONICAL),

                "sha256":
                    sha256_file(
                        CANONICAL
                    ),
            },
    },

    "xe520_native_control_passed":
        True,

    "handoff_rows":
        len(handoff),

    "poss_pair_rows":
        len(poss_rows),

    "handoff_geometry_columns":
        geometry_columns,

    "source_hits":
        hits,

    "csv_geometry_inventory":
        csv_inventory,

    "poss_geometry":
        poss_geometry,

    "science_pixels_processed":
        False,

    "detector_run":
        False,
}


OUT_JSON.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


# ------------------------------------------------------------------
# Human-readable condensed report.
# ------------------------------------------------------------------

out = []

out.append(
    "SUB-5 TRUE-WCS GEOMETRY RECOVERY"
)

out.append(
    "=" * 78
)

out.append(
    f"Handoff rows: {len(handoff)}"
)

out.append(
    f"POSS pair rows: {len(poss_rows)}"
)

out.append(
    "XE520 native pixel control: PASS"
)

out.append("")

out.append(
    "HANDOFF GEOMETRY COLUMNS"
)

for c in geometry_columns:
    out.append(
        f"  {c}"
    )


out.append("")
out.append(
    "FILES CONTAINING GEOMETRY/WCS LOGIC"
)


for item in hits:
    out.append("")
    out.append(
        item["path"]
    )

    out.append(
        f"  sha256: {item['sha256']}"
    )

    for match in item[
        "matches"
    ][:12]:

        out.append(
            "  "
            + f"line {match['line']}: "
            + ", ".join(
                match[
                    "matched_patterns"
                ]
            )
        )

        for ctx in match[
            "context"
        ]:
            out.append(
                f"    {ctx['line']:6d}: "
                f"{ctx['text']}"
            )


out.append("")
out.append(
    "CSV GEOMETRY INVENTORY"
)


for item in csv_inventory:
    out.append(
        "  "
        + item["path"]
        + " :: "
        + ", ".join(
            item[
                "relevant_columns"
            ]
        )
    )


out.append("")
out.append(
    "No historical science pixel was read."
)

out.append(
    "No transient detector was run."
)


OUT_TXT.write_text(
    "\n".join(
        out
    ) + "\n",
    encoding="utf-8",
)


print("=" * 78)
print("TRUE-WCS GEOMETRY RECOVERY COMPLETE")
print("=" * 78)

print(
    "POSS pair rows:",
    len(poss_rows),
    "/ 47",
)

print(
    "Handoff geometry columns:",
    len(geometry_columns),
)

for c in geometry_columns:
    print(
        " ",
        c,
    )

print()

print(
    "Source/code files with geometry logic:",
    len(hits),
)

for item in hits[:12]:
    print(
        " ",
        item["path"],
    )

print()

print(
    "CSV products with geometry fields:",
    len(csv_inventory),
)

for item in csv_inventory[:12]:
    print(
        " ",
        item["path"],
        "=>",
        ", ".join(
            item[
                "relevant_columns"
            ]
        ),
    )

print()

print(
    "Report:",
    OUT_JSON,
)

print(
    "Readable audit:",
    OUT_TXT,
)

print()

print(
    "No historical science pixel was read."
)

print(
    "No transient detector was run."
)
