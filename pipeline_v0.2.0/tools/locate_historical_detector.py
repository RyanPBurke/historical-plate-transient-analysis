from __future__ import annotations

from pathlib import Path
import hashlib
import re


ROOT = Path.cwd()

OUTPUT = (
    ROOT
    / "research"
    / "DETECTOR_IMPLEMENTATION_RECOVERY_2026-08-21.txt"
)

EXCLUDE_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "cache",
    "evidence",
}

SEARCH_EXTENSIONS = {
    ".py",
    ".ps1",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
}

# Strong signatures of the historical detector we actually care about.
SIGNATURES = {
    "gaussian_filter": 8,
    "maximum_filter": 8,
    "median": 2,
    "mad": 5,
    "1.4826": 6,
    "4sigma": 5,
    "sigma8": 4,
    "window7": 3,
    "edge30": 3,
    "absolute_residual": 4,
    "local_maximum": 4,
    "10arcsec": 2,
    "3arcsec": 2,
}

PATTERNS = {
    "gaussian_filter":
        re.compile(r"\bgaussian_filter\b", re.I),

    "maximum_filter":
        re.compile(r"\bmaximum_filter\b", re.I),

    "median":
        re.compile(r"\bmedian\b", re.I),

    "mad":
        re.compile(
            r"\bmad\b|median_absolute_deviation|median absolute deviation",
            re.I,
        ),

    "1.4826":
        re.compile(r"1\.4826(?:0[0-9]*)?"),

    "4sigma":
        re.compile(
            r"(?:threshold|sigma|snr).{0,40}\b4(?:\.0+)?\b"
            r"|\b4(?:\.0+)?\s*\*\s*(?:sigma|noise)"
            r"|\b4\s*[- ]?sigma\b",
            re.I,
        ),

    "sigma8":
        re.compile(
            r"(?:gaussian|sigma).{0,30}\b8(?:\.0+)?\b"
            r"|\b8(?:\.0+)?\b.{0,30}(?:gaussian|sigma)",
            re.I,
        ),

    "window7":
        re.compile(
            r"(?:maximum_filter|window|size).{0,30}\b7\b"
            r"|\b7\b.{0,30}(?:maximum_filter|window|size)",
            re.I,
        ),

    "edge30":
        re.compile(
            r"(?:edge|border|mask).{0,30}\b30\b"
            r"|\b30\b.{0,30}(?:edge|border|mask)",
            re.I,
        ),

    "absolute_residual":
        re.compile(
            r"np\.abs\s*\([^)]*resid"
            r"|abs\s*\([^)]*resid"
            r"|absolute.{0,20}residual",
            re.I,
        ),

    "local_maximum":
        re.compile(
            r"local.{0,15}max"
            r"|maximum_filter",
            re.I,
        ),

    "10arcsec":
        re.compile(
            r"(?:match|radius|arcsec).{0,30}\b10(?:\.0+)?\b"
            r"|\b10(?:\.0+)?\b.{0,30}(?:arcsec|match|radius)",
            re.I,
        ),

    "3arcsec":
        re.compile(
            r"(?:match|radius|arcsec).{0,30}\b3(?:\.0+)?\b"
            r"|\b3(?:\.0+)?\b.{0,30}(?:arcsec|match|radius)",
            re.I,
        ),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def rel(path: Path) -> str:
    return str(
        path.relative_to(ROOT)
    ).replace("\\", "/")


def excluded(path: Path) -> bool:
    try:
        parts = set(
            path.relative_to(ROOT).parts
        )
    except ValueError:
        return True

    return bool(
        parts & EXCLUDE_PARTS
    )


def safe_read(path: Path):
    try:
        # Detector source should not be enormous.
        if path.stat().st_size > 15 * 1024 * 1024:
            return None

        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    except Exception:
        return None


def score_text(text: str):
    hits = {}

    score = 0

    for name, pattern in PATTERNS.items():
        found = bool(
            pattern.search(text)
        )

        hits[name] = found

        if found:
            score += SIGNATURES[name]

    return score, hits


def excerpts(text: str, hits, radius=3):
    lines = text.splitlines()

    interesting = set()

    for n, line in enumerate(
        lines,
        start=1,
    ):
        for name, present in hits.items():
            if not present:
                continue

            if PATTERNS[name].search(line):
                for j in range(
                    max(1, n - radius),
                    min(len(lines), n + radius) + 1,
                ):
                    interesting.add(j)

    # Collapse nearby line numbers into ranges.
    if not interesting:
        return []

    nums = sorted(interesting)
    ranges = []

    start = prev = nums[0]

    for n in nums[1:]:
        if n <= prev + 1:
            prev = n
            continue

        ranges.append(
            (start, prev)
        )

        start = prev = n

    ranges.append(
        (start, prev)
    )

    rendered = []

    for lo, hi in ranges[:12]:
        rendered.append(
            "\n".join(
                f"{n:5d}: {lines[n - 1]}"
                for n in range(lo, hi + 1)
            )
        )

    return rendered


print("=" * 100)
print("HISTORICAL 4-SIGMA DETECTOR IMPLEMENTATION RECOVERY")
print("=" * 100)
print("Read-only. No detector is executed.")

all_files = []

for path in ROOT.rglob("*"):
    if not path.is_file():
        continue

    if excluded(path):
        continue

    # Exact historical filename is interesting regardless of suffix set.
    if (
        path.name.lower() == "pilot_pixel_qa.py"
        or path.suffix.lower() in SEARCH_EXTENSIONS
    ):
        all_files.append(path)


print()
print("Candidate text/source files considered:", len(all_files))


# ----------------------------------------------------------------------
# Exact filename search first.
# ----------------------------------------------------------------------

exact_name = [
    path
    for path in all_files
    if path.name.lower()
    == "pilot_pixel_qa.py"
]

print()
print("=" * 100)
print("EXACT pilot_pixel_qa.py LOCATIONS")
print("=" * 100)

if exact_name:
    for path in exact_name:
        print(rel(path))
        print(" SHA256:", sha256(path))
else:
    print("none")


# ----------------------------------------------------------------------
# Search textual references to the historical filename.
# ----------------------------------------------------------------------

references = []

for path in all_files:
    text = safe_read(path)

    if text is None:
        continue

    if "pilot_pixel_qa" in text.lower():
        references.append(
            (path, text)
        )

print()
print("=" * 100)
print("REFERENCES TO pilot_pixel_qa")
print("=" * 100)

if references:
    for path, text in references:
        print()
        print(rel(path))

        for n, line in enumerate(
            text.splitlines(),
            start=1,
        ):
            if "pilot_pixel_qa" in line.lower():
                print(
                    f" {n:5d}: {line}"
                )
else:
    print("none")


# ----------------------------------------------------------------------
# Score actual detector-like source.
# ----------------------------------------------------------------------

candidates = []

for path in all_files:
    text = safe_read(path)

    if text is None:
        continue

    score, hits = score_text(text)

    if score <= 0:
        continue

    candidates.append(
        {
            "path": path,
            "text": text,
            "score": score,
            "hits": hits,
        }
    )


candidates.sort(
    key=lambda item: (
        -item["score"],
        rel(item["path"]),
    )
)


print()
print("=" * 100)
print("RANKED DETECTOR CANDIDATES")
print("=" * 100)

for rank, item in enumerate(
    candidates[:30],
    start=1,
):
    path = item["path"]
    hits = item["hits"]

    print()
    print(
        f"#{rank:02d} score={item['score']:02d}  {rel(path)}"
    )
    print(
        "SHA256:",
        sha256(path),
    )

    print(
        "signatures:",
        ", ".join(
            name
            for name, present in hits.items()
            if present
        ),
    )


# ----------------------------------------------------------------------
# Print detailed source excerpts for strongest candidates.
# Require enough signal that we don't dump irrelevant files.
# ----------------------------------------------------------------------

strong = [
    item
    for item in candidates
    if (
        item["score"] >= 15
        or (
            item["hits"]["gaussian_filter"]
            and item["hits"]["maximum_filter"]
        )
    )
]


print()
print("=" * 100)
print("STRONG CANDIDATE SOURCE EXCERPTS")
print("=" * 100)

if not strong:
    print(
        "No high-confidence detector implementation was found."
    )

for item in strong[:12]:
    path = item["path"]

    print()
    print("#" * 100)
    print(rel(path))
    print("SHA256:", sha256(path))
    print("score:", item["score"])
    print(
        "signatures:",
        ", ".join(
            name
            for name, present
            in item["hits"].items()
            if present
        ),
    )
    print("#" * 100)

    chunks = excerpts(
        item["text"],
        item["hits"],
    )

    if not chunks:
        print("<no line excerpts>")
        continue

    for chunk in chunks:
        print()
        print(chunk)


# ----------------------------------------------------------------------
# Specifically search code for characteristic SciPy/NumPy constructs,
# even if wording differs from our regex signatures.
# ----------------------------------------------------------------------

construct_hits = []

construct_terms = (
    "scipy.ndimage",
    "gaussian_filter",
    "maximum_filter",
    "median_absolute_deviation",
    "1.4826",
    "np.median",
    "np.abs",
)

for path in all_files:
    if path.suffix.lower() != ".py":
        continue

    text = safe_read(path)

    if text is None:
        continue

    terms = [
        term
        for term in construct_terms
        if term.lower() in text.lower()
    ]

    if len(terms) >= 2:
        construct_hits.append(
            (
                len(terms),
                path,
                terms,
            )
        )


print()
print("=" * 100)
print("PYTHON NUMERIC-CONSTRUCT SEARCH")
print("=" * 100)

for count, path, terms in sorted(
    construct_hits,
    key=lambda x: (
        -x[0],
        rel(x[1]),
    ),
)[:30]:
    print(
        f"{count} constructs | {rel(path)}"
    )
    print(
        " ",
        ", ".join(terms),
    )


# ----------------------------------------------------------------------
# Save the complete ranked summary for provenance.
# ----------------------------------------------------------------------

report_lines = [
    "HISTORICAL 4-SIGMA DETECTOR IMPLEMENTATION RECOVERY",
    "",
    "No detector executed.",
    "",
    "Exact pilot_pixel_qa.py:",
]

report_lines += (
    [
        f"- {rel(path)} | {sha256(path)}"
        for path in exact_name
    ]
    or ["- none"]
)

report_lines += [
    "",
    "Ranked candidates:",
]

for rank, item in enumerate(
    candidates,
    start=1,
):
    report_lines.append(
        f"{rank:03d} | score={item['score']:02d} | "
        f"{rel(item['path'])} | "
        f"{sha256(item['path'])} | "
        + ",".join(
            name
            for name, present
            in item["hits"].items()
            if present
        )
    )


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.write_text(
    "\n".join(report_lines) + "\n",
    encoding="utf-8",
)


print()
print("=" * 100)
print("RECOVERY SEARCH COMPLETE")
print("=" * 100)
print("Report:", OUTPUT)
print("No files other than this report were changed.")
print("No pixels were changed.")
print("No transient detector was run.")

if strong:
    print()
    print(
        "High-confidence candidate implementation(s) found: "
        f"{len(strong)}"
    )
else:
    print()
    print(
        "No high-confidence implementation found. "
        "If so, the next step is to reconstruct and freeze "
        "a new implementation from the already-frozen method specification, "
        "rather than pretending recovered source exists."
    )
