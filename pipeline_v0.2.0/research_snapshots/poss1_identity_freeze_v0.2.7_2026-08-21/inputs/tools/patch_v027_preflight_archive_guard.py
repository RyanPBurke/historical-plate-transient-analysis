from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import shutil


ROOT = Path.cwd()
WRAPPER = ROOT / "run_poss1_identity_preflight.ps1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


if not WRAPPER.exists():
    raise SystemExit(f"Missing wrapper: {WRAPPER}")

text = WRAPPER.read_text(encoding="utf-8")

old = '''    $allowedException = "POSS-I:449:O:rec198"
    $unexpectedUnavailable = @(
        $archiveUnavailable | Where-Object { $_.exposure_id -ne $allowedException }
    )
    if ($unexpectedUnavailable.Count -gt 0) {
        throw "Unexpected archive-unavailable exposure(s); only the frozen XO197 exception is permitted."
    }
    if ($archiveUnavailable.Count -gt 1) {
        throw "More than one archive-unavailable exposure was produced; inspect before science."
    }
'''

new = '''    # v0.2.7 reviewed archive-availability exceptions.
    #
    # These are exact physical/catalogue identities with distinct validated
    # failure modes.  This is deliberately NOT a count-only allowance:
    # any other unavailable exposure, wrong region, wrong MLP mapping,
    # changed provenance class, or detector eligibility is terminal.
    $expectedArchiveUnavailable = @{
        "POSS-I:449:O:rec198" = @{
            finder_region                  = "XO197"
            vi25_mlp                       = "198"
            identity_source                = "vi25_plus_primary_stsci_failure_and_skyview_gap"
            descriptor_image_count         = "0"
            archive_failure_kind           = ""
            skyview_raw_hhh_url             = ""
        }
        "POSS-I:832:E:rec760" = @{
            finder_region                  = "XE760"
            vi25_mlp                       = "761"
            identity_source                = "vi25_plus_primary_stsci_failure_and_skyview_descriptor_raw_hhh_gap"
            descriptor_image_count         = "1"
            archive_failure_kind           = "skyview_raw_hhh_http_404"
            skyview_raw_hhh_url             = "https://skyview.gsfc.nasa.gov/surveys/dss/xe760/xe760.hhh"
        }
    }

    if ($archiveUnavailable.Count -ne $expectedArchiveUnavailable.Count) {
        throw (
            "Archive-unavailable exposure count mismatch: expected " +
            "$($expectedArchiveUnavailable.Count), got $($archiveUnavailable.Count)."
        )
    }

    foreach ($row in $archiveUnavailable) {
        if (-not $expectedArchiveUnavailable.ContainsKey($row.exposure_id)) {
            throw "Unexpected archive-unavailable exposure: $($row.exposure_id)"
        }

        $expected = $expectedArchiveUnavailable[$row.exposure_id]

        if ($row.finder_region -ne $expected.finder_region) {
            throw (
                "Archive-unavailable region mismatch for $($row.exposure_id): " +
                "$($row.finder_region) != $($expected.finder_region)"
            )
        }

        if ($row.vi25_mlp -ne $expected.vi25_mlp) {
            throw (
                "Archive-unavailable VI/25 MLP mismatch for $($row.exposure_id): " +
                "$($row.vi25_mlp) != $($expected.vi25_mlp)"
            )
        }

        if ($row.identity_source -ne $expected.identity_source) {
            throw (
                "Archive-unavailable identity-source mismatch for $($row.exposure_id): " +
                "$($row.identity_source)"
            )
        }

        if ($row.archive_availability_status -ne "digital_pixels_unavailable") {
            throw (
                "Archive availability status changed for $($row.exposure_id): " +
                "$($row.archive_availability_status)"
            )
        }

        if ($row.eligible_for_science -notmatch "^(False|false|0)$") {
            throw (
                "Archive-unavailable exposure became detector/science eligible: " +
                "$($row.exposure_id)"
            )
        }

        if (
            $row.skyview_descriptor_image_count -ne
            $expected.descriptor_image_count
        ) {
            throw (
                "SkyView descriptor-count mismatch for $($row.exposure_id): " +
                "$($row.skyview_descriptor_image_count) != " +
                "$($expected.descriptor_image_count)"
            )
        }

        if (
            $row.archive_failure_kind -ne
            $expected.archive_failure_kind
        ) {
            throw (
                "Archive failure-kind mismatch for $($row.exposure_id): " +
                "$($row.archive_failure_kind) != " +
                "$($expected.archive_failure_kind)"
            )
        }

        if (
            $row.skyview_raw_hhh_url -ne
            $expected.skyview_raw_hhh_url
        ) {
            throw (
                "Raw-HHH URL mismatch for $($row.exposure_id): " +
                "$($row.skyview_raw_hhh_url)"
            )
        }
    }
'''

count = text.count(old)

if count != 1:
    raise SystemExit(
        "REFUSING: expected exactly one old XO197-only guard; "
        f"found {count}. No file changed."
    )

# Also correct the wrapper's cosmetic revision banner if it is still present.
old_banner = "POSS-I physical-plate identity/availability preflight v0.2.6"
new_banner = "POSS-I physical-plate identity/availability preflight v0.2.7"

banner_count = text.count(old_banner)

if banner_count not in (0, 1):
    raise SystemExit(
        f"REFUSING: unexpected old-banner count: {banner_count}"
    )

patched = text.replace(old, new, 1)

if banner_count == 1:
    patched = patched.replace(old_banner, new_banner, 1)

# Fail closed against the mistaken XE759 narrative.
if "XE759" in patched:
    raise SystemExit(
        "REFUSING: wrapper unexpectedly contains XE759. "
        "Reviewed VI/25 mapping for rec760 is MLP 761 -> XE760."
    )

required = (
    '"POSS-I:449:O:rec198"',
    '"XO197"',
    '"POSS-I:832:E:rec760"',
    '"XE760"',
    'vi25_mlp                       = "761"',
    '"skyview_raw_hhh_http_404"',
    "surveys/dss/xe760/xe760.hhh",
)

for item in required:
    if item not in patched:
        raise SystemExit(f"REFUSING: patched guard missing {item!r}")

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = (
    ROOT
    / "patch_backups"
    / f"pre_v027_wrapper_archive_guard_{stamp}"
    / WRAPPER.name
)

backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(WRAPPER, backup)

before_sha = sha256_file(WRAPPER)

WRAPPER.write_text(patched, encoding="utf-8")

print("=" * 88)
print("v0.2.7 PREFLIGHT WRAPPER ARCHIVE GUARD PATCHED")
print("=" * 88)
print("backup:        ", backup)
print("before SHA256: ", before_sha)
print("after SHA256:  ", sha256_file(WRAPPER))
print()
print("Exact permitted unavailable identities:")
print("  POSS-I:449:O:rec198 -> XO197")
print("  POSS-I:832:E:rec760 -> XE760 (VI/25 MLP 761)")
print()
print("No checkpoint state was changed.")
print("No transient detector was run.")
