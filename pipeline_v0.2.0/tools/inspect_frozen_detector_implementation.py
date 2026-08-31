from __future__ import annotations

from pathlib import Path
import ast
import hashlib
import json
import re


ROOT = Path.cwd()

PRIMARY = ROOT / "scripts" / "pilot_pixel_qa.py"
CONFIG = ROOT / "config" / "frozen_method.json"

SEARCH_ROOTS = [
    ROOT / "scripts",
    ROOT / "src",
    ROOT / "tests",
]

KEYWORDS = (
    "gaussian_filter",
    "maximum_filter",
    "median",
    "mad",
    "sigma",
    "residual",
    "local_max",
    "threshold",
    "edge",
    "match_radius",
    "arcsec",
)


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for block in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def source_segment(lines, node):
    start = max(
        1,
        getattr(node, "lineno", 1),
    )

    end = min(
        len(lines),
        getattr(node, "end_lineno", start),
    )

    return "\n".join(
        f"{n:5d}: {lines[n - 1]}"
        for n in range(start, end + 1)
    )


print("=" * 100)
print("FROZEN 4-SIGMA DETECTOR IMPLEMENTATION INSPECTION")
print("=" * 100)
print("Read-only. No detector is executed.")

if not PRIMARY.is_file():
    raise SystemExit(
        f"REFUSING: historical detector source not found: {PRIMARY}"
    )

if not CONFIG.is_file():
    raise SystemExit(
        f"REFUSING: frozen method config not found: {CONFIG}"
    )


print()
print("=" * 100)
print("FROZEN METHOD CONFIG")
print("=" * 100)
print("path:", CONFIG)
print("SHA256:", sha256(CONFIG))

try:
    config = json.loads(
        CONFIG.read_text(
            encoding="utf-8",
        )
    )

    print(
        json.dumps(
            config,
            indent=2,
            sort_keys=True,
        )
    )

except Exception:
    print(
        CONFIG.read_text(
            encoding="utf-8",
            errors="replace",
        )
    )


print()
print("=" * 100)
print("PRIMARY HISTORICAL DETECTOR SOURCE")
print("=" * 100)
print("path:", PRIMARY)
print("SHA256:", sha256(PRIMARY))

text = PRIMARY.read_text(
    encoding="utf-8",
    errors="replace",
)

lines = text.splitlines()

tree = ast.parse(
    text,
    filename=str(PRIMARY),
)


# ------------------------------------------------------------------
# Print top-level assignments containing likely detector constants.
# ------------------------------------------------------------------

print()
print("TOP-LEVEL DETECTOR-RELATED ASSIGNMENTS")
print("-" * 100)

for node in tree.body:
    if not isinstance(
        node,
        (ast.Assign, ast.AnnAssign),
    ):
        continue

    segment = ast.get_source_segment(
        text,
        node,
    ) or ""

    lower = segment.lower()

    if any(
        key in lower
        for key in (
            "sigma",
            "threshold",
            "edge",
            "window",
            "match",
            "arcsec",
            "radius",
        )
    ):
        print(
            source_segment(
                lines,
                node,
            )
        )
        print()


# ------------------------------------------------------------------
# Print every function containing detector-signature terms.
# ------------------------------------------------------------------

print()
print("=" * 100)
print("DETECTOR-RELATED FUNCTIONS")
print("=" * 100)

matched_functions = 0

for node in ast.walk(tree):
    if not isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        continue

    segment = ast.get_source_segment(
        text,
        node,
    ) or ""

    lower = segment.lower()

    hits = [
        keyword
        for keyword in KEYWORDS
        if keyword in lower
    ]

    if len(hits) < 2:
        continue

    matched_functions += 1

    print()
    print("-" * 100)
    print(
        f"FUNCTION {node.name} "
        f"[lines {node.lineno}-{node.end_lineno}]"
    )
    print("keyword hits:", ", ".join(hits))
    print("-" * 100)

    print(
        source_segment(
            lines,
            node,
        )
    )


print()
print("Detector-related functions printed:", matched_functions)


# ------------------------------------------------------------------
# Repository-wide search for alternate/current implementations.
# ------------------------------------------------------------------

print()
print("=" * 100)
print("OTHER DETECTOR IMPLEMENTATION REFERENCES")
print("=" * 100)

matches = []

for root in SEARCH_ROOTS:
    if not root.exists():
        continue

    for path in root.rglob("*.py"):
        if path == PRIMARY:
            continue

        try:
            body = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            continue

        lower = body.lower()

        score = sum(
            1
            for keyword in KEYWORDS
            if keyword in lower
        )

        if score < 3:
            continue

        matches.append(
            (
                score,
                path,
                sha256(path),
            )
        )


for score, path, digest in sorted(
    matches,
    key=lambda x: (-x[0], str(x[1])),
):
    print()
    print(
        f"{score:2d} keyword families | "
        f"{path.relative_to(ROOT)}"
    )
    print("SHA256:", digest)

    body = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    body_lines = body.splitlines()

    for n, line in enumerate(
        body_lines,
        start=1,
    ):
        lower = line.lower()

        if any(
            keyword in lower
            for keyword in KEYWORDS
        ):
            lo = max(
                1,
                n - 2,
            )

            hi = min(
                len(body_lines),
                n + 2,
            )

            print(
                f"  around line {n}:"
            )

            for j in range(
                lo,
                hi + 1,
            ):
                print(
                    f"    {j:5d}: "
                    f"{body_lines[j - 1]}"
                )

            print()


# ------------------------------------------------------------------
# Explicit textual checks against the already-agreed method.
# These are clues only; final lock will use actual code semantics.
# ------------------------------------------------------------------

print()
print("=" * 100)
print("AGREED METHOD SIGNATURE CHECK")
print("=" * 100)

agreed = {
    "4_sigma_threshold":
        bool(
            re.search(
                r"\b4(?:\.0+)?\b",
                text,
            )
        ),

    "gaussian_filter_present":
        "gaussian_filter" in text,

    "sigma_8_present":
        bool(
            re.search(
                r"\b8(?:\.0+)?\b",
                text,
            )
        ),

    "maximum_filter_present":
        "maximum_filter" in text,

    "window_7_present":
        bool(
            re.search(
                r"\b7(?:\.0+)?\b",
                text,
            )
        ),

    "edge_30_present":
        bool(
            re.search(
                r"\b30(?:\.0+)?\b",
                text,
            )
        ),

    "absolute_value_present":
        (
            "np.abs" in text
            or "numpy.abs" in text
            or "abs(" in text
        ),

    "median_present":
        "median" in text.lower(),

    "mad_scale_1_4826_present":
        (
            "1.4826" in text
            or "1.482602" in text
        ),

    "10_arcsec_signature_present":
        bool(
            re.search(
                r"\b10(?:\.0+)?\b",
                text,
            )
        ),

    "3_arcsec_signature_present":
        bool(
            re.search(
                r"\b3(?:\.0+)?\b",
                text,
            )
        ),
}

print(
    json.dumps(
        agreed,
        indent=2,
        sort_keys=True,
    )
)


print()
print("=" * 100)
print("INSPECTION COMPLETE")
print("=" * 100)
print("No file was modified.")
print("No pixel product was modified.")
print("No detector was executed.")
print()
print(
    "The next operation will freeze the exact implementation "
    "and then begin the clean 37-exposure detector rerun."
)
