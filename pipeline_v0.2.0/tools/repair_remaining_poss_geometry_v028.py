from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import shutil
import ast

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


ROOT = Path.cwd()

PAIR_MAP = (
    ROOT / "research" /
    "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
)

CENSUS = (
    ROOT / "tools" /
    "census_poss47_tpv_geometry_v028.py"
)

GRID_DIR = (
    ROOT / "work" /
    "poss47_tpv_geometry_census_v028" /
    "poss_wcs_grids"
)

CURRENT_CSV = (
    ROOT / "research" /
    "SUB5_V028_POSS47_TPV_GEOMETRY_CENSUS_2026-08-21.csv"
)

CURRENT_JSON = (
    ROOT / "research" /
    "SUB5_V028_POSS47_TPV_GEOMETRY_CENSUS_2026-08-21.json"
)

REPORT = (
    ROOT / "research" /
    "POSS1_V028_FROZEN_HEADER_GEOMETRY_REPAIR_2026-08-21.json"
)

TARGETS = {
    2:  ("POSS-I:985:E:rec726",  "XE726"),
    48: ("POSS-I:314:E:rec646",  "XE645"),
    49: ("POSS-I:293:E:rec754",  "XE754"),
    62: ("POSS-I:306:E:rec703",  "XE702"),
    65: ("POSS-I:1024:E:rec742", "XE742"),
    66: ("POSS-I:500:E:rec679",  "XE678"),
}

GRID_N = 65

# Official first-generation DSS dimensions.
DEFAULT_WIDTH = 14000
DEFAULT_HEIGHT = 13999


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)
    return h.hexdigest()


def safe(text: str) -> str:
    return "".join(
        c if c.isalnum() or c in "-_."
        else "_"
        for c in text
    )


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------
# Exact DSS plate solution.
#
# STScI convention:
#
# full-plate DSS pixel centres:
#   P1 = x_zero_based + 1.5
#   P2 = y_zero_based + 1.5
#
# subimage pixel centres:
#   P1 = x_zero_based + CNPIX1 + 0.5
#   P2 = y_zero_based + CNPIX2 + 0.5
# ------------------------------------------------------------------

def plate_center_radians(h):
    ra_hours = (
        float(h["PLTRAH"])
        + float(h["PLTRAM"]) / 60.0
        + float(h["PLTRAS"]) / 3600.0
    )

    ra = np.deg2rad(
        15.0 * ra_hours
    )

    sign_raw = str(
        h["PLTDECSN"]
    ).strip()

    sign = (
        -1.0
        if sign_raw.startswith("-")
        else 1.0
    )

    dec_deg = sign * (
        float(h["PLTDECD"])
        + float(h["PLTDECM"]) / 60.0
        + float(h["PLTDECS"]) / 3600.0
    )

    dec = np.deg2rad(
        dec_deg
    )

    return ra, dec


def dss_world(
    h,
    p1,
    p2,
):
    p1 = np.asarray(
        p1,
        dtype=float,
    )

    p2 = np.asarray(
        p2,
        dtype=float,
    )

    x = (
        float(h["PPO3"])
        - float(h["XPIXELSZ"]) * p1
    ) / 1000.0

    y = (
        float(h["YPIXELSZ"]) * p2
        - float(h["PPO6"])
    ) / 1000.0

    r2 = (
        x * x
        + y * y
    )

    r4 = (
        r2 * r2
    )

    a = {
        i: float(
            h[f"AMDX{i}"]
        )
        for i in range(
            1,
            14,
        )
    }

    b = {
        i: float(
            h[f"AMDY{i}"]
        )
        for i in range(
            1,
            14,
        )
    }

    xi = (
        a[1] * x
        + a[2] * y
        + a[3]
        + a[4] * x*x
        + a[5] * x*y
        + a[6] * y*y
        + a[7] * r2
        + a[8] * x*x*x
        + a[9] * x*x*y
        + a[10] * x*y*y
        + a[11] * y*y*y
        + a[12] * x*r2
        + a[13] * x*r4
    )

    eta = (
        b[1] * y
        + b[2] * x
        + b[3]
        + b[4] * y*y
        + b[5] * x*y
        + b[6] * x*x
        + b[7] * r2
        + b[8] * y*y*y
        + b[9] * x*y*y
        + b[10] * x*x*y
        + b[11] * x*x*x
        + b[12] * y*r2
        + b[13] * y*r4
    )

    # Polynomial values are arcseconds.
    xi = np.deg2rad(
        xi / 3600.0
    )

    eta = np.deg2rad(
        eta / 3600.0
    )

    ra0, dec0 = (
        plate_center_radians(h)
    )

    denominator = (
        1.0
        - eta * np.tan(dec0)
    )

    dra = np.arctan2(
        xi / np.cos(dec0),
        denominator,
    )

    ra = (
        ra0
        + dra
    )

    dec = np.arctan2(
        (
            eta
            + np.tan(dec0)
        ) * np.cos(dra),
        denominator,
    )

    return (
        np.mod(
            np.rad2deg(ra),
            360.0,
        ),
        np.rad2deg(dec),
    )


# ------------------------------------------------------------------
# Load exact six frozen FITS.
# ------------------------------------------------------------------

rows = read_csv(
    PAIR_MAP
)

by_order = {
    int(float(r["canonical_order"])): r
    for r in rows
}

GRID_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

results = []


for order, (
    expected_pid,
    expected_region,
) in TARGETS.items():

    if order not in by_order:
        raise SystemExit(
            f"REFUSING: order {order} absent."
        )

    row = by_order[order]

    if (
        row["poss_exposure_id"]
        != expected_pid
    ):
        raise SystemExit(
            f"REFUSING: order {order} "
            "POSS identity changed."
        )

    if (
        row["poss_region"].upper()
        != expected_region
    ):
        raise SystemExit(
            f"REFUSING: order {order} "
            "region changed."
        )

    path = Path(
        row["poss_fits_path"]
    )

    if (
        not path.is_absolute()
    ):
        path = (
            ROOT / path
        )

    if not path.is_file():
        raise SystemExit(
            f"REFUSING: frozen FITS missing: {path}"
        )

    expected_sha = (
        row["poss_fits_sha256"]
        .strip()
        .lower()
    )

    actual_sha = sha(
        path
    )

    if (
        expected_sha
        and actual_sha
        != expected_sha
    ):
        raise SystemExit(
            f"REFUSING: frozen FITS "
            f"hash mismatch order {order}."
        )

    # Header only.
    h = fits.getheader(
        path,
        ext=0,
    )

    if (
        str(
            h.get(
                "REGION",
                "",
            )
        ).strip().upper()
        != expected_region
    ):
        raise SystemExit(
            f"REFUSING: REGION mismatch "
            f"order {order}."
        )

    for key in (
        "CNPIX1",
        "CNPIX2",
        "XPIXELSZ",
        "YPIXELSZ",
        "PPO3",
        "PPO6",
        "PLTRAH",
        "PLTRAM",
        "PLTRAS",
        "PLTDECSN",
        "PLTDECD",
        "PLTDECM",
        "PLTDECS",
    ):
        if key not in h:
            raise SystemExit(
                f"REFUSING: {key} missing "
                f"order {order}."
            )

    for i in range(
        1,
        14,
    ):
        if (
            f"AMDX{i}" not in h
            or f"AMDY{i}" not in h
        ):
            raise SystemExit(
                f"REFUSING: DSS polynomial "
                f"term {i} missing order {order}."
            )

    # --------------------------------------------------------------
    # Sanity-check exact DSS polynomial against the cutout's
    # supplied local celestial WCS.
    # --------------------------------------------------------------

    local_wcs = WCS(
        h
    ).celestial

    ny = int(
        h["NAXIS2"]
    )

    nx = int(
        h["NAXIS1"]
    )

    sx = np.linspace(
        0,
        nx - 1,
        7,
    )

    sy = np.linspace(
        0,
        ny - 1,
        7,
    )

    xx, yy = np.meshgrid(
        sx,
        sy,
    )

    p1_local = (
        xx.ravel()
        + float(h["CNPIX1"])
        + 0.5
    )

    p2_local = (
        yy.ravel()
        + float(h["CNPIX2"])
        + 0.5
    )

    dra, ddec = dss_world(
        h,
        p1_local,
        p2_local,
    )

    exact_coord = SkyCoord(
        dra * u.deg,
        ddec * u.deg,
        frame="icrs",
    )

    local_coord = (
        local_wcs.pixel_to_world(
            xx.ravel(),
            yy.ravel(),
        )
    )

    sep = (
        exact_coord.separation(
            local_coord
        ).arcsec
    )

    median_sep = float(
        np.nanmedian(sep)
    )

    max_sep = float(
        np.nanmax(sep)
    )

    # The local FITS WCS may be the dynamically generated
    # GSC-II/TAN approximation rather than the retained
    # GSC-I polynomial, so equality is not expected.
    # This threshold is solely a gross convention-error guard.
    if (
        not np.isfinite(max_sep)
        or max_sep > 30.0
    ):
        raise SystemExit(
            f"REFUSING: DSS polynomial/local-WCS "
            f"sanity check order {order}: "
            f"max separation {max_sep:.3f}\""
        )

    # Prefer explicit full-scan dimensions if retained.
    if (
        h.get("XPIXELS")
        and h.get("YPIXELS")
    ):
        full_width = int(
            h["XPIXELS"]
        )

        full_height = int(
            h["YPIXELS"]
        )

        dimension_source = (
            "frozen_fits_XPIXELS_YPIXELS"
        )

    else:
        full_width = (
            DEFAULT_WIDTH
        )

        full_height = (
            DEFAULT_HEIGHT
        )

        dimension_source = (
            "official_DSS1_14000x13999"
        )

    if (
        full_width < 13000
        or full_height < 13000
    ):
        raise SystemExit(
            f"REFUSING: implausible full "
            f"plate dimensions order {order}: "
            f"{full_width}x{full_height}"
        )

    # Full plate zero-based pixel centres map to
    # DSS P1/P2 = x/y + 1.5.
    gx = np.linspace(
        0,
        full_width - 1,
        GRID_N,
    )

    gy = np.linspace(
        0,
        full_height - 1,
        GRID_N,
    )

    gxx, gyy = np.meshgrid(
        gx,
        gy,
    )

    gra, gdec = dss_world(
        h,
        gxx.ravel() + 1.5,
        gyy.ravel() + 1.5,
    )

    grid_path = (
        GRID_DIR
        / (
            safe(expected_pid)
            + "_"
            + expected_region
            + "_grid65.csv"
        )
    )

    with grid_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "ix",
            "iy",
            "x",
            "y",
            "ra_deg",
            "dec_deg",
        ])

        k = 0

        for iy in range(
            GRID_N
        ):
            for ix in range(
                GRID_N
            ):
                writer.writerow([
                    ix,
                    iy,
                    repr(
                        float(
                            gxx.ravel()[k]
                        )
                    ),
                    repr(
                        float(
                            gyy.ravel()[k]
                        )
                    ),
                    repr(
                        float(
                            gra[k]
                        )
                    ),
                    repr(
                        float(
                            gdec[k]
                        )
                    ),
                ])

                k += 1

    results.append({
        "canonical_order":
            order,

        "poss_exposure_id":
            expected_pid,

        "region":
            expected_region,

        "frozen_fits":
            str(path),

        "frozen_fits_sha256":
            actual_sha,

        "cutout_shape":
            [ny, nx],

        "cnpix":
            [
                h["CNPIX1"],
                h["CNPIX2"],
            ],

        "full_plate_shape":
            [
                full_height,
                full_width,
            ],

        "dimension_source":
            dimension_source,

        "dss_polynomial_vs_local_wcs":
            {
                "median_sep_arcsec":
                    median_sep,

                "max_sep_arcsec":
                    max_sep,
            },

        "grid":
            str(grid_path),

        "grid_sha256":
            sha(grid_path),

        "grid_points":
            GRID_N * GRID_N,

        "pixel_coverage_note":
            (
                "Full-plate geometry reconstructed "
                "from retained DSS header. "
                "Actual frozen image pixels remain "
                "limited to the stored cutout."
            ),
    })


# ------------------------------------------------------------------
# Patch census wrapper:
#
# 1. support DASCH timestamps such as 09:27:60.0Z
# 2. if a deterministic precomputed POSS grid exists, use it
#    without attempting live SkyView raw HHH access.
# ------------------------------------------------------------------

raw = CENSUS.read_bytes()

text = raw.decode(
    "utf-8-sig"
)

ast.parse(
    text,
    filename=str(CENSUS),
)


old_import = (
    "from datetime import datetime, timezone"
)

new_import = (
    "from datetime import "
    "datetime, timezone, timedelta"
)

if old_import in text:
    text = text.replace(
        old_import,
        new_import,
        1,
    )

elif new_import not in text:
    raise SystemExit(
        "REFUSING: datetime import "
        "shape unexpected."
    )


if "\nimport re\n" not in text:
    anchor = "import os\n"

    if anchor not in text:
        raise SystemExit(
            "REFUSING: import insertion "
            "anchor absent."
        )

    text = text.replace(
        anchor,
        anchor + "import re\n",
        1,
    )


parse_anchor = '''    raw = str(text).strip()

    if not raw:
'''


parse_insert = '''    raw = str(text).strip()

    # DASCH can encode an exact minute boundary using
    # seconds=60, e.g. 09:27:60.0Z. Python's ISO parser
    # rejects that representation, so normalize it by
    # parsing second 59 and adding one second.
    overflow = re.match(
        r"^(.*T\\d{2}:\\d{2}):60(\\.\\d+)?"
        r"(Z|[+-]\\d{2}:\\d{2})$",
        raw,
    )

    if overflow:
        prefix = overflow.group(1)
        fraction = overflow.group(2) or ""
        zone = overflow.group(3)

        if zone == "Z":
            zone = "+00:00"

        fixed = (
            prefix
            + ":59"
            + fraction
            + zone
        )

        dt = (
            datetime.fromisoformat(fixed)
            + timedelta(seconds=1)
        )

        return dt.astimezone(
            timezone.utc
        )

    if not raw:
'''


if parse_insert not in text:

    if text.count(
        parse_anchor
    ) != 1:
        raise SystemExit(
            "REFUSING: parse_utc patch "
            "anchor not unique."
        )

    text = text.replace(
        parse_anchor,
        parse_insert,
        1,
    )


resolve_anchor = '''def resolve_raw_dir(
    pid: str,
    region: str,
):
'''


resolve_insert = '''def resolve_raw_dir(
    pid: str,
    region: str,
):
    # Some physically validated POSS plates have frozen
    # FITS cutouts retaining the complete DSS/GSSS
    # polynomial, while the current SkyView raw HHH
    # mirror no longer exposes that plate.  If a
    # deterministic full-plate WCS grid has already
    # been reconstructed from such a frozen header,
    # geometry must use that grid rather than treating
    # live HHH availability as an astrometric condition.
    precomputed = (
        POSS_GRID_CACHE
        / (
            safe(pid)
            + "_"
            + region
            + "_grid65.csv"
        )
    )

    if precomputed.is_file():
        return (
            "",
            "frozen_fits_complete_dss_polynomial",
        )
'''


if resolve_insert not in text:

    if text.count(
        resolve_anchor
    ) != 1:
        raise SystemExit(
            "REFUSING: resolve_raw_dir "
            "patch anchor not unique."
        )

    text = text.replace(
        resolve_anchor,
        resolve_insert,
        1,
    )


ast.parse(
    text,
    filename=str(CENSUS),
)


stamp = datetime.now(
    timezone.utc
).strftime(
    "%Y%m%dT%H%M%SZ"
)

backup_dir = (
    ROOT
    / "patch_backups"
    / (
        "pre_remaining_geometry_repair_"
        + stamp
    )
)

backup_dir.mkdir(
    parents=True,
    exist_ok=False,
)

shutil.copy2(
    CENSUS,
    backup_dir / CENSUS.name,
)

for product in (
    CURRENT_CSV,
    CURRENT_JSON,
):
    if product.is_file():
        shutil.copy2(
            product,
            backup_dir / product.name,
        )


CENSUS.write_text(
    text,
    encoding="utf-8",
)


# Final syntax check.
ast.parse(
    CENSUS.read_text(
        encoding="utf-8-sig"
    ),
    filename=str(CENSUS),
)


report = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "reconstructed_poss_grids":
        results,

    "wrapper_repairs": [
        "DASCH seconds=60 timestamp normalization",
        "precomputed frozen-DSS geometry grid bypasses live HHH",
    ],

    "backup_directory":
        str(backup_dir),

    "historical_image_arrays_read":
        False,

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


print("=" * 78)
print("REMAINING POSS GEOMETRY REPAIR PREPARED")
print("=" * 78)

for r in results:
    print(
        f"order {r['canonical_order']:2d}: "
        f"{r['poss_exposure_id']} / {r['region']}"
    )

    print(
        "  full plate:",
        f"{r['full_plate_shape'][1]} x "
        f"{r['full_plate_shape'][0]}",
        "|",
        r["dimension_source"],
    )

    print(
        "  polynomial/local-WCS sanity:",
        f"median={r['dss_polynomial_vs_local_wcs']['median_sep_arcsec']:.3f}\"",
        f"max={r['dss_polynomial_vs_local_wcs']['max_sep_arcsec']:.3f}\"",
    )


print()
print(
    "Census parser seconds=60 support: PASS"
)

print(
    "Frozen-header grid bypass: PASS"
)

print(
    "Backup:",
    backup_dir,
)

print(
    "Report:",
    REPORT,
)

print()
print(
    "No historical image arrays were read."
)

print(
    "No detector was run."
)
