from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import gzip
import hashlib
import json
import re
import shutil


ROOT = Path.cwd()

FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
)

MANIFEST = FREEZE / "freeze_manifest.json"

FULL40 = (
    FREEZE
    / "results"
    / "poss1_identity_full40_v028.csv"
)

PRODUCTION = (
    ROOT
    / "research"
    / "production_sub5_queue_2026-08-20.csv"
)

INVENTORY_CSV = (
    ROOT
    / "research"
    / "POSS1_V028_PIXEL_FITS_INVENTORY_2026-08-21.csv"
)

HANDOFF_CSV = (
    ROOT
    / "research"
    / "SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv"
)

REPORT_JSON = (
    ROOT
    / "research"
    / "POSS1_V028_PIXEL_PROVENANCE_RECONCILIATION_2026-08-21.json"
)

REPORT_MD = (
    ROOT
    / "research"
    / "POSS1_V028_PIXEL_PROVENANCE_RECONCILIATION_2026-08-21.md"
)

EXPECTED_MANIFEST_SHA = (
    "56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e"
)

EXPECTED_SNAPSHOT_ID = (
    "8dc070b9df3febaa5db3585408e1fe88e9b3b9d71d436ddba16a71081b066d0e"
)

EXPECTED_PRODUCTION_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_UNAVAILABLE = {
    "POSS-I:449:O:rec198": "XO197",
    "POSS-I:832:E:rec760": "XE760",
    "POSS-I:988:O:rec207": "XO206",
}

PIXEL_SUFFIXES = (
    ".fits",
    ".fit",
    ".fts",
    ".fits.gz",
    ".fit.gz",
    ".fts.gz",
    ".fz",
    ".npy",
    ".npz",
)

TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".md",
    ".txt",
    ".log",
}

REFERENCE_KEYWORDS = (
    "pilot",
    "candidate",
    "transient",
    "pixel",
    "cutout",
    "detect",
    "sigma",
    "morph",
    "def-",
    "match",
    "qa",
)

SCAN_ROOT_NAMES = (
    "cache",
    "results",
    "research",
    "evidence",
    "data",
    "outputs",
)

EXCLUDED_COMPONENTS = {
    ".venv",
    "__pycache__",
    ".git",
    "research_snapshots",
}

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


def parse_utc(value: str) -> datetime:
    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        raise ValueError(
            f"naive timestamp: {value!r}"
        )

    return dt.astimezone(timezone.utc)


def norm(value: str) -> str:
    return re.sub(
        r"[^A-Z0-9]+",
        "",
        str(value).upper(),
    )


def exposure_id_from_queue(row):
    ids = [
        str(row.get("exposure_a") or ""),
        str(row.get("exposure_b") or ""),
    ]

    ids = [
        x
        for x in ids
        if x.startswith("POSS-I:")
    ]

    if len(ids) > 1:
        raise SystemExit(
            "REFUSING: queue row contains >1 POSS exposure: "
            f"{row.get('canonical_order')}"
        )

    return ids[0] if ids else ""


def is_pixel_file(path: Path) -> bool:
    name = path.name.lower()

    return any(
        name.endswith(suffix)
        for suffix in PIXEL_SUFFIXES
    )


def origin_class(path: Path) -> str:
    text = str(path).lower()

    if "poss1_identity" in text:
        return "identity_cache"

    if "evidence" in path.parts:
        return "evidence_store"

    return "legacy_or_other"


def safe_relative(path: Path) -> str:
    try:
        return str(
            path.relative_to(ROOT)
        ).replace("\\", "/")

    except ValueError:
        return str(path).replace("\\", "/")


def parse_manual_fits_header(path: Path):
    opener = (
        gzip.open
        if path.name.lower().endswith(".gz")
        else open
    )

    values = {}

    wanted = {
        "REGION",
        "PLATEID",
        "PLTLABEL",
        "PLATE",
        "OBJECT",
        "SURVEY",
        "DATE-OBS",
        "DATEOBS",
        "NAXIS",
        "NAXIS1",
        "NAXIS2",
        "CRVAL1",
        "CRVAL2",
        "CTYPE1",
        "CTYPE2",
    }

    try:
        with opener(path, "rb") as fh:
            blocks = 0

            while blocks < 100:
                block = fh.read(2880)

                if not block:
                    break

                blocks += 1

                for offset in range(
                    0,
                    len(block),
                    80,
                ):
                    raw = block[offset:offset + 80]

                    if len(raw) < 80:
                        continue

                    try:
                        card = raw.decode(
                            "ascii",
                            errors="replace",
                        )
                    except Exception:
                        continue

                    key = card[:8].strip()

                    if key == "END":
                        return values

                    if key not in wanted:
                        continue

                    if card[8:10] == "= ":
                        value = card[10:].split(
                            "/",
                            1,
                        )[0].strip()

                        if (
                            len(value) >= 2
                            and value[0] == "'"
                            and "'" in value[1:]
                        ):
                            value = value[
                                1:value[1:].rfind("'") + 1
                            ].strip()

                        values[key] = value

            return values

    except Exception as exc:
        return {
            "_HEADER_ERROR":
                f"{type(exc).__name__}: {exc}"
        }


try:
    from astropy.io import fits as astro_fits
except Exception:
    astro_fits = None


def fits_header(path: Path):
    lower = path.name.lower()

    if not (
        lower.endswith(".fits")
        or lower.endswith(".fit")
        or lower.endswith(".fts")
        or lower.endswith(".fits.gz")
        or lower.endswith(".fit.gz")
        or lower.endswith(".fts.gz")
        or lower.endswith(".fz")
    ):
        return {}

    if astro_fits is not None:
        try:
            hdr = astro_fits.getheader(
                path,
                0,
            )

            keys = (
                "REGION",
                "PLATEID",
                "PLTLABEL",
                "PLATE",
                "OBJECT",
                "SURVEY",
                "DATE-OBS",
                "DATEOBS",
                "NAXIS",
                "NAXIS1",
                "NAXIS2",
                "CRVAL1",
                "CRVAL2",
                "CTYPE1",
                "CTYPE2",
            )

            return {
                key: str(hdr.get(key, ""))
                for key in keys
                if hdr.get(key) is not None
            }

        except Exception as exc:
            fallback = parse_manual_fits_header(
                path
            )

            fallback["_ASTROPY_ERROR"] = (
                f"{type(exc).__name__}: {exc}"
            )

            return fallback

    return parse_manual_fits_header(path)


def output_backup(path: Path):
    if not path.exists():
        return

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup = path.with_name(
        f"{path.stem}.pre_reconcile_{stamp}{path.suffix}"
    )

    shutil.copy2(
        path,
        backup,
    )


print("=" * 100)
print("v0.2.8 PIXEL/FITS PROVENANCE RECONCILIATION")
print("=" * 100)
print(
    "This is the post-identity gate. "
    "No transient detector is executed."
)


# ======================================================================
# 1. Freeze / queue guards
# ======================================================================

for path in (
    MANIFEST,
    FULL40,
    PRODUCTION,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )

if sha256_file(MANIFEST) != EXPECTED_MANIFEST_SHA:
    raise SystemExit(
        "REFUSING: v0.2.8 freeze manifest hash changed."
    )

if sha256_file(PRODUCTION) != EXPECTED_PRODUCTION_SHA:
    raise SystemExit(
        "REFUSING: authoritative production queue changed."
    )

manifest = json.loads(
    MANIFEST.read_text(
        encoding="utf-8",
    )
)

if manifest.get("snapshot_id") != EXPECTED_SNAPSHOT_ID:
    raise SystemExit(
        "REFUSING: v0.2.8 snapshot ID changed."
    )

if manifest.get("detector_run") is not False:
    raise SystemExit(
        "REFUSING: identity freeze does not state detector_run=False."
    )

manifest_files = {
    item["snapshot_path"]:
        item
    for item in manifest.get("files", [])
}

full40_rel = (
    "results/poss1_identity_full40_v028.csv"
)

if full40_rel not in manifest_files:
    raise SystemExit(
        "REFUSING: full40 CSV absent from freeze manifest."
    )

if (
    sha256_file(FULL40)
    != manifest_files[full40_rel]["sha256"]
):
    raise SystemExit(
        "REFUSING: frozen full40 CSV hash does not match manifest."
    )


# ======================================================================
# 2. Frozen identities
# ======================================================================

frozen_rows = load_csv(FULL40)

if len(frozen_rows) != 40:
    raise SystemExit(
        f"REFUSING: full40 row count={len(frozen_rows)}"
    )

frozen = {}

for row in frozen_rows:
    pid = str(
        row.get("exposure_id")
        or row.get("job_key")
        or ""
    )

    if not pid:
        raise SystemExit(
            "REFUSING: blank frozen exposure ID."
        )

    if pid in frozen:
        raise SystemExit(
            f"REFUSING: duplicate frozen exposure: {pid}"
        )

    frozen[pid] = row


status_counts = Counter(
    str(r.get("identity_status") or "")
    for r in frozen_rows
)

if status_counts != Counter({
    "validated": 37,
    "catalogue_identified_pixels_unavailable": 3,
}):
    raise SystemExit(
        "REFUSING: frozen identity accounting changed: "
        f"{dict(status_counts)}"
    )

actual_unavailable = {
    pid:
        str(row.get("finder_region") or "")
    for pid, row in frozen.items()
    if (
        row.get("identity_status")
        == "catalogue_identified_pixels_unavailable"
    )
}

if actual_unavailable != EXPECTED_UNAVAILABLE:
    raise SystemExit(
        "REFUSING: frozen unavailable set changed."
    )


# ======================================================================
# 3. Build conservative identity aliases.
#
# Only aliases resolving uniquely to one physical exposure are used.
# Bare POSS plate numbers are deliberately NOT used.
# ======================================================================

alias_to_ids = defaultdict(set)
pid_name_aliases = defaultdict(set)
expected_region = {}
frozen_direct_hashes = defaultdict(set)


for pid, row in frozen.items():
    region = str(
        row.get("finder_region")
        or ""
    ).strip()

    expected_region[pid] = region

    candidates = set()

    candidates.add(pid)

    # Safe composite variants for filenames.
    candidates.add(
        pid.replace(":", "_")
    )
    candidates.add(
        pid.replace(":", "-")
    )
    candidates.add(
        pid.replace("POSS-I:", "")
        .replace(":", "_")
    )

    if region:
        candidates.add(region)

    # Harvest physically meaningful plate identifiers if
    # they are present in the frozen result schema.
    for key, value in row.items():
        lk = key.lower()

        if not value:
            continue

        if (
            "region" in lk
            or "plateid" in lk
            or "pltlabel" in lk
        ):
            text = str(value).strip()

            if (
                len(text) >= 3
                and not text.isdigit()
            ):
                candidates.add(text)

        if "fits_sha256" in lk:
            text = str(value).strip()

            if HEX64.match(text):
                frozen_direct_hashes[pid].add(
                    text.lower()
                )

    for alias in candidates:
        na = norm(alias)

        if len(na) < 4:
            continue

        alias_to_ids[na].add(pid)

    # Filename-only aliases should identify recno as well
    # as the plate/band where practical.
    parts = pid.split(":")

    if len(parts) == 4:
        _, poss, band, rec = parts

        for value in (
            f"{poss}_{band}_{rec}",
            f"{poss}-{band}-{rec}",
            f"{band}_{poss}_{rec}",
            f"{band}-{poss}-{rec}",
            f"POSS_I_{poss}_{band}_{rec}",
        ):
            pid_name_aliases[pid].add(
                norm(value)
            )


unique_aliases = {
    alias:
        next(iter(ids))
    for alias, ids in alias_to_ids.items()
    if len(ids) == 1
}


# ======================================================================
# 4. Scan existing pixel/FITS products.
# ======================================================================

scan_roots = [
    ROOT / name
    for name in SCAN_ROOT_NAMES
    if (ROOT / name).exists()
]

pixel_paths = []

for scan_root in scan_roots:
    for path in scan_root.rglob("*"):
        if not path.is_file():
            continue

        relative_parts = set(
            path.relative_to(ROOT).parts
        )

        if relative_parts & EXCLUDED_COMPONENTS:
            continue

        if is_pixel_file(path):
            pixel_paths.append(path)

pixel_paths = sorted(
    set(pixel_paths)
)

print()
print("Pixel/FITS-like files discovered:", len(pixel_paths))


artifact_rows = []

artifacts_by_pid = defaultdict(list)
known_bad_rank15 = []


for index, path in enumerate(
    pixel_paths,
    start=1,
):
    rel = safe_relative(path)
    sha = sha256_file(path).lower()

    header = fits_header(path)

    path_norm = norm(rel)

    header_text = " ".join(
        f"{k}={v}"
        for k, v in header.items()
    )

    header_norm = norm(
        header_text
    )

    region = str(
        header.get("REGION")
        or ""
    ).strip()

    pltlabel = str(
        header.get("PLTLABEL")
        or ""
    ).strip()

    plateid = str(
        header.get("PLATEID")
        or ""
    ).strip()

    linked = set()
    link_reasons = []

    # Direct exact frozen hash is strongest.
    for pid, hashes in frozen_direct_hashes.items():
        if sha in hashes:
            linked.add(pid)
            link_reasons.append(
                f"exact_frozen_fits_sha:{pid}"
            )

    # Exact frozen REGION header.
    if region:
        nr = norm(region)

        if nr in unique_aliases:
            pid = unique_aliases[nr]

            if (
                expected_region.get(pid)
                and norm(expected_region[pid]) == nr
            ):
                linked.add(pid)
                link_reasons.append(
                    f"header_region:{region}"
                )

    # Other physically meaningful unique aliases.
    for alias, pid in unique_aliases.items():
        if alias in header_norm:
            linked.add(pid)
            link_reasons.append(
                f"unique_header_alias:{alias}"
            )

    # Safe filename composite identifiers.
    for pid, aliases in pid_name_aliases.items():
        if any(
            alias in path_norm
            for alias in aliases
        ):
            linked.add(pid)
            link_reasons.append(
                f"composite_filename_identity:{pid}"
            )

    # Known rank-15 wrong-DSS signatures.
    rank15_bad = (
        norm(region) == norm("XE348")
        or norm(pltlabel) == norm("E205")
        or norm(plateid) == norm("070J")
    )

    if rank15_bad:
        known_bad_rank15.append(rel)

    header_region_matches = []

    if region:
        for pid, exp_region in expected_region.items():
            if (
                exp_region
                and norm(region) == norm(exp_region)
            ):
                header_region_matches.append(pid)

    category = "UNLINKED_PIXEL_ARTIFACT"
    action = "HOLD_UNTIL_PROVENANCE_LINKED"

    exact_pid = None

    for pid, hashes in frozen_direct_hashes.items():
        if sha in hashes:
            exact_pid = pid
            break

    if exact_pid:
        category = "EXACT_FROZEN_PIXEL_HASH_MATCH"
        action = (
            "PIXEL_REUSE_CANDIDATE_"
            "DETECTOR_RESULT_STILL_NEEDS_METHOD_PROVENANCE"
        )

    elif rank15_bad:
        category = (
            "KNOWN_WRONG_RANK15_DSS_SIGNATURE"
        )
        action = "FORCE_CLEAN_RERUN_DO_NOT_REUSE"

    elif len(linked) == 1:
        pid = next(iter(linked))
        exp_region = expected_region.get(pid, "")

        if (
            region
            and exp_region
            and norm(region) != norm(exp_region)
        ):
            category = (
                "PHYSICAL_IDENTITY_MISMATCH"
            )
            action = (
                "FORCE_CLEAN_RERUN_DO_NOT_REUSE"
            )

        elif (
            frozen[pid].get("identity_status")
            == "catalogue_identified_pixels_unavailable"
        ):
            category = (
                "FROZEN_EXPOSURE_PIXELS_UNAVAILABLE"
            )
            action = (
                "DO_NOT_DETECT_DO_NOT_TREAT_AS_NEGATIVE"
            )

        else:
            category = (
                "PHYSICAL_IDENTITY_MATCH_HASH_NOT_FROZEN"
            )
            action = (
                "RERUN_DETECTOR_FROM_FROZEN_"
                "ACQUISITION_PROVENANCE"
            )

    elif len(linked) > 1:
        category = "AMBIGUOUS_MULTI_IDENTITY_LINK"
        action = "HOLD_FOR_MANUAL_PROVENANCE_RESOLUTION"

    linked_list = sorted(linked)

    row = {
        "artifact_path":
            rel,
        "origin_class":
            origin_class(path),
        "bytes":
            path.stat().st_size,
        "sha256":
            sha,
        "linked_exposure_ids":
            ";".join(linked_list),
        "link_reasons":
            ";".join(sorted(set(link_reasons))),
        "category":
            category,
        "recommended_action":
            action,
        "header_REGION":
            region,
        "header_PLTLABEL":
            pltlabel,
        "header_PLATEID":
            plateid,
        "header_DATE_OBS":
            str(
                header.get("DATE-OBS")
                or header.get("DATEOBS")
                or ""
            ),
        "header_OBJECT":
            str(header.get("OBJECT") or ""),
        "header_CRVAL1":
            str(header.get("CRVAL1") or ""),
        "header_CRVAL2":
            str(header.get("CRVAL2") or ""),
        "header_error":
            str(
                header.get("_HEADER_ERROR")
                or header.get("_ASTROPY_ERROR")
                or ""
            ),
    }

    artifact_rows.append(row)

    for pid in linked:
        artifacts_by_pid[pid].append(row)

    if (
        index % 25 == 0
        or index == len(pixel_paths)
    ):
        print(
            f"  scanned {index}/{len(pixel_paths)}"
        )


# ======================================================================
# 5. Search legacy detector/result references.
#
# These references cannot by themselves prove pixel reuse. They tell us
# where old detector/morphology outputs exist and therefore what must be
# reconciled after pixel identity is established.
# ======================================================================

reference_files = []
def011_files = []

for root_name in (
    "results",
    "research",
):
    scan_root = ROOT / root_name

    if not scan_root.exists():
        continue

    for path in scan_root.rglob("*"):
        if not path.is_file():
            continue

        if "research_snapshots" in path.parts:
            continue

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        if path.stat().st_size > 20 * 1024 * 1024:
            continue

        name_lower = path.name.lower()

        if not any(
            keyword in name_lower
            for keyword in REFERENCE_KEYWORDS
        ):
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            continue

        found_ids = set()

        ntext = norm(text)

        for alias, pid in unique_aliases.items():
            if alias in ntext:
                found_ids.add(pid)

        if "DEF-011" in text.upper():
            def011_files.append(
                safe_relative(path)
            )

        if found_ids:
            reference_files.append({
                "path":
                    safe_relative(path),
                "exposure_ids":
                    sorted(found_ids),
            })


refs_by_pid = defaultdict(list)

for item in reference_files:
    for pid in item["exposure_ids"]:
        refs_by_pid[pid].append(
            item["path"]
        )


# ======================================================================
# 6. Per-exposure pixel-provenance disposition.
# ======================================================================

exposure_summary = []

for pid in sorted(frozen):
    row = frozen[pid]
    status = row["identity_status"]
    region = row.get(
        "finder_region",
        "",
    )

    artifacts = artifacts_by_pid.get(
        pid,
        [],
    )

    legacy = [
        a
        for a in artifacts
        if a["origin_class"]
        == "legacy_or_other"
    ]

    identity_cache = [
        a
        for a in artifacts
        if a["origin_class"]
        == "identity_cache"
    ]

    exact_legacy = [
        a
        for a in legacy
        if a["category"]
        == "EXACT_FROZEN_PIXEL_HASH_MATCH"
    ]

    matching_legacy = [
        a
        for a in legacy
        if a["category"]
        in {
            "EXACT_FROZEN_PIXEL_HASH_MATCH",
            "PHYSICAL_IDENTITY_MATCH_HASH_NOT_FROZEN",
        }
    ]

    mismatched_legacy = [
        a
        for a in legacy
        if a["category"]
        in {
            "PHYSICAL_IDENTITY_MISMATCH",
            "KNOWN_WRONG_RANK15_DSS_SIGNATURE",
        }
    ]

    if status == (
        "catalogue_identified_pixels_unavailable"
    ):
        disposition = (
            "UNAVAILABLE_NO_DETECTOR"
        )

        next_action = (
            "retain_in_denominator_as_archive_unavailable;"
            "never_score_as_non_detection"
        )

    elif mismatched_legacy:
        disposition = (
            "LEGACY_PIXEL_IDENTITY_CONFLICT"
        )

        next_action = (
            "force_clean_pixel_acquisition_and_detector_rerun"
        )

    elif exact_legacy:
        disposition = (
            "EXACT_LEGACY_PIXEL_HASH_MATCH_CANDIDATE"
        )

        next_action = (
            "audit_deterministic_cutout_and_detector_method_"
            "provenance_before_reusing_old_disposition"
        )

    elif matching_legacy:
        disposition = (
            "LEGACY_PHYSICAL_IDENTITY_MATCH_HASH_NOT_FROZEN"
        )

        next_action = (
            "rerun_from_frozen_identity;"
            "do_not_reuse_old_detector_disposition"
        )

    elif identity_cache:
        disposition = (
            "FROZEN_IDENTITY_PIXEL_AVAILABLE_NO_PROVEN_LEGACY_MATCH"
        )

        next_action = (
            "generate_clean_deterministic_cutout_and_run_"
            "frozen_detector"
        )

    else:
        disposition = (
            "NO_REUSABLE_PIXEL_PRODUCT_LOCATED"
        )

        next_action = (
            "clean_reacquisition_then_frozen_detector"
        )

    exposure_summary.append({
        "exposure_id":
            pid,
        "identity_status":
            status,
        "finder_region":
            region,
        "pixel_disposition":
            disposition,
        "next_action":
            next_action,
        "all_linked_pixel_artifacts":
            len(artifacts),
        "legacy_linked_pixel_artifacts":
            len(legacy),
        "exact_legacy_hash_matches":
            len(exact_legacy),
        "legacy_identity_conflicts":
            len(mismatched_legacy),
        "identity_cache_artifacts":
            len(identity_cache),
        "legacy_detector_reference_files":
            len(refs_by_pid.get(pid, [])),
        "legacy_detector_reference_paths":
            " || ".join(
                sorted(
                    refs_by_pid.get(pid, [])
                )
            ),
    })


summary_by_pid = {
    row["exposure_id"]:
        row
    for row in exposure_summary
}


# ======================================================================
# 7. Build publication-facing 74-row post-identity handoff.
#
# Explicit overlap interval is recorded for every pair here.
# ======================================================================

production_rows = load_csv(
    PRODUCTION
)

if len(production_rows) != 74:
    raise SystemExit(
        "REFUSING: authoritative queue is no longer 74 rows."
    )

handoff_rows = []

overlap_mismatches = []

for row in sorted(
    production_rows,
    key=lambda r:
        int(float(r["canonical_order"])),
):
    a0 = parse_utc(row["start_a_utc"])
    a1 = parse_utc(row["end_a_utc"])
    b0 = parse_utc(row["start_b_utc"])
    b1 = parse_utc(row["end_b_utc"])

    overlap_start = max(
        a0,
        b0,
    )

    overlap_end = min(
        a1,
        b1,
    )

    overlap_s = max(
        0.0,
        (
            overlap_end
            - overlap_start
        ).total_seconds(),
    )

    if overlap_s <= 0:
        raise SystemExit(
            "REFUSING: non-positive actual overlap in "
            f"canonical order {row['canonical_order']}"
        )

    stored = float(
        row["actual_exposure_overlap_s"]
    )

    delta = abs(
        stored
        - overlap_s
    )

    if delta > 0.01:
        overlap_mismatches.append({
            "canonical_order":
                row["canonical_order"],
            "stored_overlap_s":
                stored,
            "recomputed_overlap_s":
                overlap_s,
            "abs_delta_s":
                delta,
        })

    pid = exposure_id_from_queue(
        row
    )

    output = dict(row)

    output[
        "overlap_start_utc"
    ] = overlap_start.isoformat()

    output[
        "overlap_end_utc"
    ] = overlap_end.isoformat()

    output[
        "recomputed_actual_exposure_overlap_s"
    ] = f"{overlap_s:.9f}"

    output[
        "overlap_recomputed_matches_stored"
    ] = str(delta <= 0.01)

    output[
        "poss_exposure_id"
    ] = pid

    if pid:
        identity = frozen[pid]
        prov = summary_by_pid[pid]

        output[
            "poss_identity_status"
        ] = identity["identity_status"]

        output[
            "poss_finder_region"
        ] = identity.get(
            "finder_region",
            "",
        )

        output[
            "poss_pixel_provenance_disposition"
        ] = prov[
            "pixel_disposition"
        ]

        output[
            "poss_pixel_next_action"
        ] = prov[
            "next_action"
        ]

    else:
        output[
            "poss_identity_status"
        ] = "not_applicable_non_POSS_pair"

        output[
            "poss_finder_region"
        ] = ""

        output[
            "poss_pixel_provenance_disposition"
        ] = "not_applicable_non_POSS_pair"

        output[
            "poss_pixel_next_action"
        ] = (
            "audit_non_POSS_archive_and_pixel_provenance_separately"
        )

    handoff_rows.append(
        output
    )


if overlap_mismatches:
    raise SystemExit(
        "REFUSING: overlap recomputation mismatch >0.01 s:\n"
        + json.dumps(
            overlap_mismatches,
            indent=2,
        )
    )


# ======================================================================
# 8. Write inventory + handoff.
# ======================================================================

for path in (
    INVENTORY_CSV,
    HANDOFF_CSV,
    REPORT_JSON,
    REPORT_MD,
):
    output_backup(path)


inventory_columns = [
    "artifact_path",
    "origin_class",
    "bytes",
    "sha256",
    "linked_exposure_ids",
    "link_reasons",
    "category",
    "recommended_action",
    "header_REGION",
    "header_PLTLABEL",
    "header_PLATEID",
    "header_DATE_OBS",
    "header_OBJECT",
    "header_CRVAL1",
    "header_CRVAL2",
    "header_error",
]

with INVENTORY_CSV.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=inventory_columns,
        extrasaction="raise",
    )

    writer.writeheader()
    writer.writerows(
        artifact_rows
    )


handoff_columns = []

for row in handoff_rows:
    for key in row:
        if key not in handoff_columns:
            handoff_columns.append(
                key
            )

with HANDOFF_CSV.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=handoff_columns,
        extrasaction="raise",
    )

    writer.writeheader()

    for row in handoff_rows:
        writer.writerow({
            key:
                row.get(key, "")
            for key in handoff_columns
        })


# ======================================================================
# 9. Scientific/accounting summary.
# ======================================================================

pixel_category_counts = Counter(
    row["category"]
    for row in artifact_rows
)

exposure_disposition_counts = Counter(
    row["pixel_disposition"]
    for row in exposure_summary
)

poss_pair_rows = [
    r
    for r in handoff_rows
    if r["poss_exposure_id"]
]

nonposs_pair_rows = [
    r
    for r in handoff_rows
    if not r["poss_exposure_id"]
]

unavailable_pair_rows = [
    r
    for r in poss_pair_rows
    if r["poss_identity_status"]
    == "catalogue_identified_pixels_unavailable"
]

report = {
    "created_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "operation":
        "v028_pixel_fits_provenance_reconciliation",

    "identity_snapshot": {
        "snapshot_id":
            EXPECTED_SNAPSHOT_ID,
        "manifest_sha256":
            EXPECTED_MANIFEST_SHA,
        "unique_poss_exposures":
            40,
        "validated_detector_eligible":
            37,
        "pixels_unavailable":
            EXPECTED_UNAVAILABLE,
    },

    "authoritative_pair_denominator": {
        "rows":
            len(handoff_rows),
        "poss_involving_rows":
            len(poss_pair_rows),
        "non_poss_rows":
            len(nonposs_pair_rows),
        "positive_actual_overlap_rows":
            sum(
                1
                for r in handoff_rows
                if float(
                    r[
                        "recomputed_actual_exposure_overlap_s"
                    ]
                ) > 0
            ),
        "explicit_overlap_intervals_written":
            len(handoff_rows),
        "poss_rows_blocked_by_pixel_unavailability":
            len(unavailable_pair_rows),
    },

    "pixel_artifact_inventory": {
        "files_scanned":
            len(artifact_rows),
        "category_counts":
            dict(
                pixel_category_counts
            ),
        "known_bad_rank15_E205_XE348_070J_paths":
            sorted(
                set(known_bad_rank15)
            ),
    },

    "exposure_dispositions": {
        "counts":
            dict(
                exposure_disposition_counts
            ),
        "rows":
            exposure_summary,
    },

    "legacy_detector_reference_files":
        reference_files,

    "DEF_011_reference_paths":
        sorted(
            set(def011_files)
        ),

    "outputs": {
        "inventory_csv":
            safe_relative(
                INVENTORY_CSV
            ),
        "handoff_csv":
            safe_relative(
                HANDOFF_CSV
            ),
    },

    "detector_run":
        False,

    "policy": {
        "archive_unavailability_is_scientific_negative":
            False,
        "old_detector_disposition_auto_promoted":
            False,
        "exact_pixel_hash_match_still_requires_detector_method_audit":
            True,
    },
}

REPORT_JSON.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


md = [
    "# v0.2.8 POSS-I pixel/FITS provenance reconciliation",
    "",
    f"Snapshot ID: `{EXPECTED_SNAPSHOT_ID}`",
    "",
    "## Frozen identity boundary",
    "",
    "- unique POSS physical exposures: **40**",
    "- validated / detector-eligible: **37**",
    "- pixels unavailable: **3**",
    "- identity failures: **0**",
    "",
    "## Pair handoff",
    "",
    f"- temporal pairs: **{len(handoff_rows)}**",
    f"- POSS-involving rows: **{len(poss_pair_rows)}**",
    f"- non-POSS rows: **{len(nonposs_pair_rows)}**",
    f"- rows with positive actual exposure overlap: **{len(handoff_rows)}**",
    "- explicit overlap_start_utc/end_utc recorded: **74/74**",
    "",
    "## Pixel inventory",
    "",
    f"- pixel/FITS-like files scanned: **{len(artifact_rows)}**",
]

for key, value in sorted(
    pixel_category_counts.items()
):
    md.append(
        f"- `{key}`: **{value}**"
    )

md += [
    "",
    "## Exposure dispositions",
    "",
]

for key, value in sorted(
    exposure_disposition_counts.items()
):
    md.append(
        f"- `{key}`: **{value}**"
    )

md += [
    "",
    "## Frozen unavailable exposures",
    "",
]

for pid, region in EXPECTED_UNAVAILABLE.items():
    md.append(
        f"- `{pid}` -> `{region}`"
    )

md += [
    "",
    "Archive/pixel unavailability remains part of the denominator "
    "and is not a scientific zero/non-detection.",
    "",
    "No old detector disposition was automatically promoted.",
    "",
    "Even an exact legacy pixel hash match remains only a reuse "
    "candidate until deterministic cutout and frozen-detector "
    "method provenance are verified.",
    "",
    "No transient detector was run.",
    "",
]

REPORT_MD.write_text(
    "\n".join(md),
    encoding="utf-8",
)


# ======================================================================
# 10. Terminal milestone report.
# ======================================================================

print()
print("=" * 100)
print("PIXEL/FITS PROVENANCE RECONCILIATION COMPLETE")
print("=" * 100)

print()
print("Frozen identity boundary:")
print("  unique POSS exposures:                 40")
print("  validated / detector-eligible:         37")
print("  pixels unavailable:                     3")

print()
print("74-row science handoff:")
print("  rows:                                  ", len(handoff_rows))
print("  POSS-involving rows:                   ", len(poss_pair_rows))
print("  non-POSS rows:                         ", len(nonposs_pair_rows))
print("  explicit overlap intervals:            ", len(handoff_rows))
print("  positive-overlap rows:                 ", len(handoff_rows))
print(
    "  POSS pair rows blocked by unavailable pixels:",
    len(unavailable_pair_rows),
)

print()
print("Pixel/FITS artifacts scanned:", len(artifact_rows))

for key, value in sorted(
    pixel_category_counts.items()
):
    print(
        f"  {key:50s} {value}"
    )

print()
print("Per-exposure dispositions:")

for key, value in sorted(
    exposure_disposition_counts.items()
):
    print(
        f"  {key:55s} {value}"
    )

print()
print("Known E779 wrong-DSS signatures found:")
if known_bad_rank15:
    for path in sorted(
        set(known_bad_rank15)
    ):
        print(" ", path)
else:
    print("  none found in scanned pixel files")

print()
print("Files containing DEF-011:")
if def011_files:
    for path in sorted(
        set(def011_files)
    ):
        print(" ", path)
else:
    print("  none found in scanned detector/reference files")

print()
print("Outputs:")
print(" ", INVENTORY_CSV)
print(" ", HANDOFF_CSV)
print(" ", REPORT_JSON)
print(" ", REPORT_MD)

print()
print(
    "No old detector result has been automatically accepted."
)
print(
    "No transient detector was run."
)
print()
print(
    "NEXT GATE: freeze/preflight the actual 4-sigma detector "
    "implementation, then clean-rerun every exposure/pair whose "
    "old pixel+method provenance is not exact."
)
