from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import subprocess
import sys

ROOT = Path.cwd()

PRODUCTION = ROOT / "research" / "production_sub5_queue_2026-08-20.csv"
VI25 = ROOT / "research" / "poss1_plate_metadata.csv"

FULL40 = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
    / "results"
    / "poss1_identity_full40_v028.csv"
)

IDENTITY_MANIFEST = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
    / "freeze_manifest.json"
)

DETECTOR_MANIFEST = (
    ROOT
    / "research_snapshots"
    / "detector_freeze_v0.2.8_2026-08-21"
    / "freeze_manifest.json"
)

POSS1 = ROOT / "src" / "transient_pipeline" / "poss1.py"
SKYVIEW = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"

QUEUE = (
    ROOT
    / "research"
    / "poss1_pixel_repair_v028_queue.csv"
)

DB = (
    ROOT
    / "state"
    / "poss1_pixel_repair_v028.sqlite"
)

CACHE = (
    ROOT
    / "cache"
    / "poss1_pixel_repair_v028"
)

RESULT = (
    ROOT
    / "results"
    / "poss1_pixel_repair_v028.csv"
)

PIXEL_RESULT = (
    ROOT
    / "research"
    / "POSS1_V028_PIXEL_REPAIR_RESOLUTION_2026-08-21.csv"
)

REPORT = (
    ROOT
    / "research"
    / "POSS1_V028_PIXEL_REPAIR_REPORT_2026-08-21.json"
)

CLI = (
    ROOT
    / ".venv"
    / "Scripts"
    / "transient-pipeline.exe"
)

EXPECTED_PRODUCTION_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_VI25_SHA = (
    "41b5732086f5a1d17e6f6d85c99f97a48a0985f19db1ad496cd3e3a2387830c1"
)

EXPECTED_IDENTITY_MANIFEST_SHA = (
    "56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e"
)

EXPECTED_DETECTOR_MANIFEST_SHA = (
    "4d66c8f7099ece364053a451f15688ba7d2105c8a3b112d392e8e7a4a6c97c06"
)

EXPECTED_POSS1_SHA = (
    "6161a74d5ce76f70235c66a748077b3517f7d2d7946e9f48998927c331374ac7"
)

EXPECTED_SKYVIEW_SHA = (
    "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e"
)

TARGET_IDS = {
    "POSS-I:1023:O:rec675",
    "POSS-I:1023:O:rec799",
    "POSS-I:305:E:rec637",
    "POSS-I:318:E:rec524",
    "POSS-I:606:E:rec348",
    "POSS-I:779:E:rec404",
    "POSS-I:782:E:rec514",
    "POSS-I:872:O:rec148",
    "POSS-I:875:E:rec521",
    "POSS-I:876:E:rec239",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


def poss_ids(row):
    return {
        value
        for value in (
            str(row.get("exposure_a") or ""),
            str(row.get("exposure_b") or ""),
        )
        if value.startswith("POSS-I:")
    }


def safe_key(pid: str) -> str:
    return "".join(
        c if c.isalnum() or c in "-_." else "_"
        for c in pid
    )


def fits_info(path: Path):
    try:
        raw = path.read_bytes()

        if not raw.startswith(b"SIMPLE"):
            return None

        from astropy.io import fits
        from astropy.wcs import WCS

        with fits.open(
            path,
            memmap=False,
        ) as hdul:
            if not hdul:
                return None

            data = hdul[0].data

            if data is None or getattr(data, "ndim", None) != 2:
                return None

            hdr = hdul[0].header
            wcs = WCS(hdr).celestial

            if not wcs.has_celestial:
                return None

            return {
                "region":
                    str(hdr.get("REGION", "")).strip(),

                "plateid":
                    str(hdr.get("PLATEID", "")).strip(),

                "pltlabel":
                    str(hdr.get("PLTLABEL", "")).strip(),

                "shape":
                    list(data.shape),

                "sha256":
                    sha256_file(path),
            }

    except Exception:
        return None


# ----------------------------------------------------------------------
# Hard guards.
# ----------------------------------------------------------------------

required = (
    PRODUCTION,
    VI25,
    FULL40,
    IDENTITY_MANIFEST,
    DETECTOR_MANIFEST,
    POSS1,
    SKYVIEW,
    CLI,
)

for path in required:
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: missing required file: {path}"
        )


guards = {
    "production":
        (
            sha256_file(PRODUCTION),
            EXPECTED_PRODUCTION_SHA,
        ),

    "VI25":
        (
            sha256_file(VI25),
            EXPECTED_VI25_SHA,
        ),

    "identity manifest":
        (
            sha256_file(IDENTITY_MANIFEST),
            EXPECTED_IDENTITY_MANIFEST_SHA,
        ),

    "detector manifest":
        (
            sha256_file(DETECTOR_MANIFEST),
            EXPECTED_DETECTOR_MANIFEST_SHA,
        ),

    "poss1.py":
        (
            sha256_file(POSS1),
            EXPECTED_POSS1_SHA,
        ),

    "poss1_skyview.py":
        (
            sha256_file(SKYVIEW),
            EXPECTED_SKYVIEW_SHA,
        ),
}

for label, (actual, expected) in guards.items():
    if actual != expected:
        raise SystemExit(
            f"REFUSING: {label} hash changed.\n"
            f"expected={expected}\n"
            f"actual={actual}"
        )


# ----------------------------------------------------------------------
# Frozen physical identities for the exact ten.
# ----------------------------------------------------------------------

frozen_rows = read_csv(
    FULL40
)

frozen = {
    str(
        row.get("exposure_id")
        or row.get("job_key")
        or ""
    ):
        row
    for row in frozen_rows
}

if not TARGET_IDS <= set(frozen):
    raise SystemExit(
        "REFUSING: one or more repair IDs absent "
        "from the frozen full40 table."
    )


expected_regions = {}

for pid in sorted(TARGET_IDS):
    row = frozen[pid]

    if row.get("identity_status") != "validated":
        raise SystemExit(
            f"REFUSING: repair target is not frozen "
            f"validated: {pid}"
        )

    region = str(
        row.get("finder_region")
        or ""
    ).strip()

    if not region:
        raise SystemExit(
            f"REFUSING: frozen finder region absent: {pid}"
        )

    expected_regions[pid] = region


# ----------------------------------------------------------------------
# Derive a repair-only queue from the authoritative production queue.
#
# There are 11 pair rows because one repaired physical exposure is
# represented in more than one temporal-pair row. queue_poss_jobs()
# will deduplicate these to exactly 10 physical identity jobs.
# ----------------------------------------------------------------------

prod = read_csv(
    PRODUCTION
)

selected = [
    dict(row)
    for row in prod
    if poss_ids(row) & TARGET_IDS
]

seen = set()

for row in selected:
    seen |= poss_ids(row) & TARGET_IDS

if seen != TARGET_IDS:
    raise SystemExit(
        "REFUSING: repair queue does not cover exact target set.\n"
        f"missing={sorted(TARGET_IDS-seen)}"
    )


fieldnames = list(
    selected[0].keys()
)

for extra in (
    "identity_repair_original_publication_cohort",
):
    if extra not in fieldnames:
        fieldnames.append(extra)


for row in selected:
    row[
        "identity_repair_original_publication_cohort"
    ] = row.get(
        "publication_cohort",
        "",
    )

    row["publication_cohort"] = (
        "identity_repair_v028"
    )


QUEUE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with QUEUE.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=fieldnames,
    )

    writer.writeheader()

    for row in selected:
        writer.writerow({
            key:
                row.get(key, "")
            for key in fieldnames
        })


print("=" * 78)
print("v0.2.8 EXACT-TEN POSS PIXEL REPAIR")
print("=" * 78)
print(
    f"Repair queue pair rows: {len(selected)}"
)
print(
    f"Unique physical exposures: {len(TARGET_IDS)}"
)
print()
print("This operation MAY make archive requests.")
print("No transient detector will be executed.")


# ----------------------------------------------------------------------
# Run reviewed identity resolver, resumably.
#
# Up to four passes are permitted only to clear transient archive
# failures. Completed jobs remain checkpointed.
# ----------------------------------------------------------------------

CACHE.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

for attempt in range(1, 5):
    print()
    print(
        f"Identity/pixel repair pass {attempt}/4"
    )

    cmd = [
        str(CLI),
        "--db",
        str(DB),
        "poss1-preflight",
        "--queue",
        str(QUEUE),
        "--vi25",
        str(VI25),
        "--cohort",
        "identity_repair_v028",
        "--cache-dir",
        str(CACHE),
        "--export",
        str(RESULT),
    ]

    completed = subprocess.run(
        cmd,
        cwd=ROOT,
    )

    if completed.returncode != 0:
        raise SystemExit(
            f"REFUSING: repair resolver exited "
            f"{completed.returncode}"
        )

    if not RESULT.is_file():
        continue

    current = read_csv(
        RESULT
    )

    by_id = {
        str(
            row.get("exposure_id")
            or row.get("job_key")
            or ""
        ):
            row
        for row in current
    }

    succeeded = {
        pid
        for pid, row in by_id.items()
        if row.get("status") == "succeeded"
    }

    if TARGET_IDS <= succeeded:
        break


if not RESULT.is_file():
    raise SystemExit(
        "REFUSING: repair result was not produced."
    )


result_rows = read_csv(
    RESULT
)

by_id = {
    str(
        row.get("exposure_id")
        or row.get("job_key")
        or ""
    ):
        row
    for row in result_rows
}


# ----------------------------------------------------------------------
# Exact identity assertions.
# ----------------------------------------------------------------------

identity_errors = []

for pid in sorted(TARGET_IDS):
    row = by_id.get(pid)

    if not row:
        identity_errors.append(
            f"{pid}: no result row"
        )
        continue

    if row.get("status") != "succeeded":
        identity_errors.append(
            f"{pid}: status={row.get('status')}"
        )
        continue

    if row.get("identity_status") != "validated":
        identity_errors.append(
            f"{pid}: identity_status="
            f"{row.get('identity_status')}"
        )
        continue

    actual_region = str(
        row.get("finder_region")
        or ""
    ).strip()

    if actual_region != expected_regions[pid]:
        identity_errors.append(
            f"{pid}: frozen region "
            f"{expected_regions[pid]} became "
            f"{actual_region}"
        )


if identity_errors:
    raise SystemExit(
        "REFUSING: physical identity changed during "
        "pixel repair:\n"
        + "\n".join(identity_errors)
    )


# ----------------------------------------------------------------------
# Locate actual FITS produced by the repair run.
#
# First use explicit path-valued result fields. Then inspect only the
# exact per-exposure repair cache directory. A candidate must be a
# 2-D celestial-WCS FITS, and REGION must agree where present.
# ----------------------------------------------------------------------

resolution = []


for pid in sorted(TARGET_IDS):
    row = by_id[pid]
    expected_region = expected_regions[pid]

    candidates = []

    # Explicit path-like result fields.
    for key, value in row.items():
        lk = key.lower()

        if not value:
            continue

        if not (
            lk.endswith("_path")
            or "image_path" in lk
            or lk == "fits_path"
        ):
            continue

        p = Path(
            str(value)
        )

        if not p.is_absolute():
            p = ROOT / p

        if p.is_file():
            candidates.append(
                (
                    f"result_field:{key}",
                    p,
                )
            )


    # Exact repair-cache namespace for this physical exposure.
    exposure_dir = (
        CACHE
        / safe_key(pid)
    )

    if exposure_dir.exists():
        for p in sorted(
            exposure_dir.rglob("*")
        ):
            if p.is_file():
                candidates.append(
                    (
                        "repair_cache",
                        p,
                    )
                )


    # Deduplicate paths.
    unique = {}

    for reason, path in candidates:
        unique.setdefault(
            str(path.resolve()).lower(),
            (
                reason,
                path,
            ),
        )


    valid = []

    for reason, path in unique.values():
        info = fits_info(path)

        if not info:
            continue

        header_region = info["region"]

        if (
            header_region
            and header_region != expected_region
        ):
            continue

        valid.append(
            (
                reason,
                path,
                info,
            )
        )


    # Prefer explicit result path; otherwise deterministic pathname.
    valid.sort(
        key=lambda item: (
            0
            if item[0].startswith(
                "result_field:fits_path"
            )
            else 1,
            str(item[1]),
        )
    )


    if valid:
        reason, path, info = valid[0]

        state = "REPAIR_PIXEL_READY"

        resolution.append({
            "exposure_id":
                pid,

            "expected_region":
                expected_region,

            "identity_status":
                row["identity_status"],

            "pixel_state":
                state,

            "pixel_path":
                str(
                    path.resolve()
                ),

            "pixel_sha256":
                info["sha256"],

            "header_region":
                info["region"],

            "header_plateid":
                info["plateid"],

            "header_pltlabel":
                info["pltlabel"],

            "shape_json":
                json.dumps(
                    info["shape"]
                ),

            "resolution_source":
                reason,
        })

    else:
        resolution.append({
            "exposure_id":
                pid,

            "expected_region":
                expected_region,

            "identity_status":
                row["identity_status"],

            "pixel_state":
                "VALIDATED_BUT_NO_USABLE_FITS_AFTER_REPAIR",

            "pixel_path":
                "",

            "pixel_sha256":
                "",

            "header_region":
                "",

            "header_plateid":
                "",

            "header_pltlabel":
                "",

            "shape_json":
                "",

            "resolution_source":
                "",
        })


# ----------------------------------------------------------------------
# Save compact publication-facing repair result.
# ----------------------------------------------------------------------

PIXEL_RESULT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with PIXEL_RESULT.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            resolution[0].keys()
        ),
    )

    writer.writeheader()
    writer.writerows(
        resolution
    )


states = Counter(
    row["pixel_state"]
    for row in resolution
)


report = {
    "operation":
        "v028_exact_ten_poss_pixel_repair",

    "target_exposures":
        sorted(TARGET_IDS),

    "expected_regions":
        expected_regions,

    "repair_queue_pair_rows":
        len(selected),

    "physical_identity_jobs":
        10,

    "repair_states":
        dict(states),

    "identity_errors":
        identity_errors,

    "queue_sha256":
        sha256_file(QUEUE),

    "result_sha256":
        sha256_file(RESULT),

    "pixel_resolution_sha256":
        sha256_file(PIXEL_RESULT),

    "archive_requests_permitted":
        True,

    "detector_run":
        False,
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


print()
print("=" * 78)
print("EXACT-TEN PIXEL REPAIR COMPLETE")
print("=" * 78)

print()
print("Physical identity:")
print("  frozen identities preserved: 10/10")

print()
print("Pixel results:")

for state, n in sorted(
    states.items()
):
    print(
        f"  {state}: {n}"
    )


unresolved = [
    row
    for row in resolution
    if (
        row["pixel_state"]
        != "REPAIR_PIXEL_READY"
    )
]

if unresolved:
    print()
    print(
        "Still without a usable FITS product:"
    )

    for row in unresolved:
        print(
            " ",
            row["exposure_id"],
            "->",
            row["expected_region"],
        )

print()
print("Outputs:")
print(" ", QUEUE)
print(" ", RESULT)
print(" ", PIXEL_RESULT)
print(" ", REPORT)

print()
print("No transient detector was run.")

if not unresolved:
    print()
    print(
        "MILESTONE: all 37 detector-eligible POSS "
        "physical exposures now have locally resolved FITS pixels."
    )
else:
    print()
    print(
        "NEXT: source-specific acquisition only for the "
        f"{len(unresolved)} unresolved exact identities."
    )
