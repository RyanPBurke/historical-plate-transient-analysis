from __future__ import annotations

from pathlib import Path
from collections import Counter
import csv
import hashlib
import json


ROOT = Path.cwd()

IDENTITY_FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
)

IDENTITY_MANIFEST = (
    IDENTITY_FREEZE
    / "freeze_manifest.json"
)

FULL40 = (
    IDENTITY_FREEZE
    / "results"
    / "poss1_identity_full40_v028.csv"
)

DETECTOR_MANIFEST = (
    ROOT
    / "research_snapshots"
    / "detector_freeze_v0.2.8_2026-08-21"
    / "freeze_manifest.json"
)

HANDOFF = (
    ROOT
    / "research"
    / "SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv"
)

PIXEL_MAP = (
    ROOT
    / "research"
    / "POSS1_V028_FROZEN_PIXEL_MAP_2026-08-21.csv"
)

PAIR_MAP = (
    ROOT
    / "research"
    / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
)

REPORT = (
    ROOT
    / "research"
    / "POSS1_V028_FROZEN_PIXEL_MAP_REPORT_2026-08-21.json"
)


EXPECTED_IDENTITY_MANIFEST_SHA = (
    "56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e"
)

EXPECTED_IDENTITY_SNAPSHOT_ID = (
    "8dc070b9df3febaa5db3585408e1fe88e9b3b9d71d436ddba16a71081b066d0e"
)

EXPECTED_DETECTOR_MANIFEST_SHA = (
    "4d66c8f7099ece364053a451f15688ba7d2105c8a3b112d392e8e7a4a6c97c06"
)

EXPECTED_DETECTOR_SNAPSHOT_ID = (
    "e3a9b42eaf58027171bb5449533e8bc413672acae7881d9641884363fb2aef7a"
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


def resolve_stored_path(value: str):
    text = str(value or "").strip()

    if not text:
        return None

    p = Path(text)

    if not p.is_absolute():
        p = ROOT / p

    return p


def partner_plate_id(exposure: str):
    text = str(exposure or "")

    if text.startswith("DASCH:"):
        if "/q/" in text:
            return text.rsplit("/q/", 1)[-1]

        return text.split("/")[-1]

    return ""


for p in (
    IDENTITY_MANIFEST,
    FULL40,
    DETECTOR_MANIFEST,
    HANDOFF,
):
    if not p.is_file():
        raise SystemExit(
            f"REFUSING: missing required file: {p}"
        )


# ----------------------------------------------------------------------
# Immutable upstream guards.
# ----------------------------------------------------------------------

if (
    sha256_file(IDENTITY_MANIFEST)
    != EXPECTED_IDENTITY_MANIFEST_SHA
):
    raise SystemExit(
        "REFUSING: identity freeze manifest changed."
    )

identity_manifest = json.loads(
    IDENTITY_MANIFEST.read_text(
        encoding="utf-8",
    )
)

if (
    identity_manifest.get("snapshot_id")
    != EXPECTED_IDENTITY_SNAPSHOT_ID
):
    raise SystemExit(
        "REFUSING: identity snapshot ID changed."
    )


if (
    sha256_file(DETECTOR_MANIFEST)
    != EXPECTED_DETECTOR_MANIFEST_SHA
):
    raise SystemExit(
        "REFUSING: detector freeze manifest changed."
    )

detector_manifest = json.loads(
    DETECTOR_MANIFEST.read_text(
        encoding="utf-8",
    )
)

if (
    detector_manifest.get("snapshot_id")
    != EXPECTED_DETECTOR_SNAPSHOT_ID
):
    raise SystemExit(
        "REFUSING: detector snapshot ID changed."
    )


# ----------------------------------------------------------------------
# Frozen 40-exposure identity layer.
# ----------------------------------------------------------------------

rows40 = read_csv(FULL40)

if len(rows40) != 40:
    raise SystemExit(
        f"REFUSING: full40 contains {len(rows40)} rows."
    )


pixel_rows = []

for row in rows40:
    pid = str(
        row.get("exposure_id")
        or row.get("job_key")
        or ""
    )

    status = str(
        row.get("identity_status")
        or ""
    )

    expected_sha = str(
        row.get("fits_sha256")
        or ""
    ).strip().lower()

    stored_path = str(
        row.get("fits_path")
        or ""
    ).strip()

    path = resolve_stored_path(
        stored_path
    )

    exists = bool(
        path
        and path.is_file()
    )

    actual_sha = ""

    hash_match = False

    if exists:
        actual_sha = sha256_file(
            path
        ).lower()

        hash_match = bool(
            expected_sha
            and actual_sha == expected_sha
        )


    if status == "catalogue_identified_pixels_unavailable":
        state = "ARCHIVE_UNAVAILABLE_NO_DETECTOR"

        if stored_path or expected_sha:
            raise SystemExit(
                f"REFUSING: unavailable exposure unexpectedly "
                f"contains frozen FITS provenance: {pid}"
            )

    elif status == "validated":
        if not stored_path:
            state = "VALIDATED_BUT_NO_FROZEN_FITS_PATH"

        elif not expected_sha:
            state = "VALIDATED_BUT_NO_FROZEN_FITS_HASH"

        elif not exists:
            state = "FROZEN_FITS_PATH_MISSING_LOCALLY"

        elif not hash_match:
            state = "FROZEN_FITS_HASH_MISMATCH"

        else:
            state = "FROZEN_PIXEL_READY"

    else:
        state = (
            "UNEXPECTED_IDENTITY_STATUS:"
            + status
        )


    pixel_rows.append({
        "exposure_id":
            pid,

        "identity_status":
            status,

        "finder_region":
            row.get(
                "finder_region",
                "",
            ),

        "frozen_fits_path":
            stored_path,

        "resolved_fits_path":
            str(path) if path else "",

        "frozen_fits_sha256":
            expected_sha,

        "actual_fits_sha256":
            actual_sha,

        "fits_exists":
            str(exists),

        "fits_hash_match":
            str(hash_match),

        "pixel_execution_state":
            state,

        "science_publication_cohorts":
            row.get(
                "science_publication_cohorts",
                "",
            ),

        "identity_stage_origin":
            row.get(
                "identity_stage_origin",
                "",
            ),
    })


pixel_by_id = {
    r["exposure_id"]: r
    for r in pixel_rows
}

if len(pixel_by_id) != 40:
    raise SystemExit(
        "REFUSING: duplicate exposure ID in pixel map."
    )


counts = Counter(
    r["pixel_execution_state"]
    for r in pixel_rows
)


# ----------------------------------------------------------------------
# 74 temporal pairs -> 47 POSS pair rows.
# ----------------------------------------------------------------------

handoff = read_csv(
    HANDOFF
)

if len(handoff) != 74:
    raise SystemExit(
        f"REFUSING: handoff has {len(handoff)} rows."
    )


pair_rows = []

for row in handoff:
    pid = str(
        row.get("poss_exposure_id")
        or ""
    ).strip()

    if not pid:
        continue

    if pid not in pixel_by_id:
        raise SystemExit(
            f"REFUSING: pair references POSS ID absent "
            f"from full40: {pid}"
        )

    if (
        float(
            row[
                "recomputed_actual_exposure_overlap_s"
            ]
        )
        <= 0
    ):
        raise SystemExit(
            "REFUSING: non-positive overlap in POSS row "
            + str(row.get("canonical_order"))
        )


    if (
        str(row.get("exposure_a") or "")
        == pid
    ):
        poss_side = "A"

        partner = str(
            row.get("exposure_b")
            or ""
        )

    elif (
        str(row.get("exposure_b") or "")
        == pid
    ):
        poss_side = "B"

        partner = str(
            row.get("exposure_a")
            or ""
        )

    else:
        raise SystemExit(
            f"REFUSING: POSS ID not found on either side "
            f"of canonical order {row.get('canonical_order')}"
        )


    pix = pixel_by_id[pid]

    if (
        pix["pixel_execution_state"]
        == "FROZEN_PIXEL_READY"
    ):
        execution_state = (
            "POSS_PIXEL_READY_"
            "PARTNER_PIXEL_WORK_PENDING"
        )

    elif (
        pix["pixel_execution_state"]
        == "ARCHIVE_UNAVAILABLE_NO_DETECTOR"
    ):
        execution_state = (
            "BLOCKED_POSS_ARCHIVE_UNAVAILABLE_"
            "NOT_A_NONDETECTION"
        )

    else:
        execution_state = (
            "POSS_PIXEL_REPAIR_REQUIRED:"
            + pix["pixel_execution_state"]
        )


    pair_rows.append({
        "canonical_order":
            row.get(
                "canonical_order",
                "",
            ),

        "legacy_rank":
            row.get(
                "legacy_rank",
                "",
            ),

        "pair_key":
            row.get(
                "pair_key",
                "",
            ),

        "publication_cohort":
            row.get(
                "publication_cohort",
                "",
            ),

        "poss_exposure_id":
            pid,

        "poss_side":
            poss_side,

        "poss_region":
            pix["finder_region"],

        "poss_fits_path":
            pix["resolved_fits_path"],

        "poss_fits_sha256":
            pix["actual_fits_sha256"],

        "partner_exposure":
            partner,

        "partner_dasch_plate_id":
            partner_plate_id(
                partner
            ),

        "true_wcs_intersection":
            row.get(
                "true_wcs_intersection",
                "",
            ),

        "true_wcs_overlap_fraction":
            row.get(
                "true_wcs_overlap_fraction",
                "",
            ),

        "overlap_start_utc":
            row[
                "overlap_start_utc"
            ],

        "overlap_end_utc":
            row[
                "overlap_end_utc"
            ],

        "actual_overlap_s":
            row[
                "recomputed_actual_exposure_overlap_s"
            ],

        "pair_execution_state":
            execution_state,
    })


if len(pair_rows) != 47:
    raise SystemExit(
        f"REFUSING: POSS pair map has {len(pair_rows)}, expected 47."
    )


# ----------------------------------------------------------------------
# Write products.
# ----------------------------------------------------------------------

PIXEL_MAP.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with PIXEL_MAP.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            pixel_rows[0]
        ),
    )

    writer.writeheader()
    writer.writerows(
        sorted(
            pixel_rows,
            key=lambda x:
                x["exposure_id"],
        )
    )


with PAIR_MAP.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            pair_rows[0]
        ),
    )

    writer.writeheader()

    writer.writerows(
        sorted(
            pair_rows,
            key=lambda x:
                int(
                    float(
                        x[
                            "canonical_order"
                        ]
                    )
                ),
        )
    )


pair_counts = Counter(
    r["pair_execution_state"]
    for r in pair_rows
)


report = {
    "identity_snapshot_id":
        EXPECTED_IDENTITY_SNAPSHOT_ID,

    "detector_snapshot_id":
        EXPECTED_DETECTOR_SNAPSHOT_ID,

    "physical_poss_exposures":
        40,

    "poss_pair_rows":
        47,

    "pixel_state_counts":
        dict(counts),

    "pair_execution_state_counts":
        dict(pair_counts),

    "pixel_map":
        str(
            PIXEL_MAP.relative_to(ROOT)
        ).replace("\\", "/"),

    "pair_map":
        str(
            PAIR_MAP.relative_to(ROOT)
        ).replace("\\", "/"),

    "archive_requests":
        0,

    "science_detector_runs":
        0,
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


# ----------------------------------------------------------------------
# Compact terminal result.
# ----------------------------------------------------------------------

print("=" * 78)
print("FROZEN POSS PIXEL MAP COMPLETE")
print("=" * 78)

print()
print("Physical exposure states:")

for state, n in sorted(
    counts.items()
):
    print(
        f"  {state}: {n}"
    )

print()
print("47 POSS pair execution states:")

for state, n in sorted(
    pair_counts.items()
):
    print(
        f"  {state}: {n}"
    )


problems = [
    r
    for r in pixel_rows
    if r["pixel_execution_state"]
    not in {
        "FROZEN_PIXEL_READY",
        "ARCHIVE_UNAVAILABLE_NO_DETECTOR",
    }
]

if problems:
    print()
    print(
        "Validated exposures requiring pixel repair:"
    )

    for r in problems:
        print(
            " ",
            r["exposure_id"],
            "=>",
            r["pixel_execution_state"],
            "=>",
            r["frozen_fits_path"],
        )


print()
print("Outputs:")
print(" ", PIXEL_MAP)
print(" ", PAIR_MAP)
print(" ", REPORT)

print()
print("No archive request.")
print("No detector execution.")
