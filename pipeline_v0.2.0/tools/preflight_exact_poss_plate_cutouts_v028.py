from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import csv
import hashlib
import json
import time

ROOT = Path.cwd()

REPAIR = (
    ROOT
    / "results"
    / "poss1_pixel_repair_v028.csv"
)

IDENTITY_MANIFEST = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
    / "freeze_manifest.json"
)

SKYVIEW_SRC = (
    ROOT
    / "src"
    / "transient_pipeline"
    / "poss1_skyview.py"
)

OUT_ROOT = (
    ROOT
    / "cache"
    / "poss1_exact_plate_cutout_preflight_v028"
)

RESULT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_2026-08-21.csv"
)

REPORT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_2026-08-21.json"
)

EXPECTED_IDENTITY_MANIFEST_SHA = (
    "56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e"
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

STS_ENDPOINT = (
    "https://archive.stsci.edu/cgi-bin/dss_plate_finder"
)


def sha256_file(path: Path):
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for block in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def sha256_bytes(data: bytes):
    return hashlib.sha256(data).hexdigest()


def safe(pid: str):
    return "".join(
        c if c.isalnum() or c in "-_."
        else "_"
        for c in pid
    )


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


def fetch(url, attempts=3):
    last = None

    for attempt in range(1, attempts + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent":
                        "historical-transient-pipeline-v0.2.8"
                },
            )

            with urlopen(
                req,
                timeout=90,
            ) as response:
                return (
                    response.read(),
                    dict(response.headers),
                    response.geturl(),
                )

        except (
            HTTPError,
            URLError,
            TimeoutError,
        ) as exc:
            last = exc

            if attempt < attempts:
                time.sleep(
                    2 ** (attempt - 1)
                )

    raise last


for path in (
    REPAIR,
    IDENTITY_MANIFEST,
    SKYVIEW_SRC,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )


if (
    sha256_file(IDENTITY_MANIFEST)
    != EXPECTED_IDENTITY_MANIFEST_SHA
):
    raise SystemExit(
        "REFUSING: identity freeze manifest changed."
    )

if (
    sha256_file(SKYVIEW_SRC)
    != EXPECTED_SKYVIEW_SHA
):
    raise SystemExit(
        "REFUSING: poss1_skyview.py changed."
    )


# Import the already-reviewed HHH parser.
import sys

sys.path.insert(
    0,
    str(ROOT / "src"),
)

from transient_pipeline.poss1_skyview import hhh_identity

from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u
import io


rows = read_csv(REPAIR)

by_id = {
    str(
        row.get("exposure_id")
        or row.get("job_key")
        or ""
    ):
        row
    for row in rows
}


if not TARGET_IDS <= set(by_id):
    raise SystemExit(
        "REFUSING: repair CSV does not contain exact target set."
    )


OUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

results = []


print("=" * 82)
print("EXACT POSS-I PLATE FITS EXTRACTION PREFLIGHT")
print("=" * 82)
print("Targets:", len(TARGET_IDS))
print("Cutout size: 5 x 5 arcmin")
print("No transient detector will run.")
print()


for index, pid in enumerate(
    sorted(TARGET_IDS),
    start=1,
):
    row = by_id[pid]

    expected_region = str(
        row.get("finder_region")
        or ""
    ).strip()

    if (
        row.get("identity_status")
        != "validated"
        or not expected_region
    ):
        raise SystemExit(
            f"REFUSING: invalid frozen repair state: {pid}"
        )


    # --------------------------------------------------------------
    # Recover exact HHH URL.
    # --------------------------------------------------------------

    hhh_url = str(
        row.get("skyview_raw_hhh_url")
        or ""
    ).strip()

    if not hhh_url:
        region_lower = (
            expected_region.lower()
        )

        hhh_url = (
            "https://skyview.gsfc.nasa.gov/"
            f"surveys/dss/{region_lower}/"
            f"{region_lower}.hhh"
        )


    target_dir = (
        OUT_ROOT
        / safe(pid)
    )

    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    print(
        f"[{index:02d}/10] {pid} -> {expected_region}"
    )


    # --------------------------------------------------------------
    # Exact SkyView HHH header.
    # --------------------------------------------------------------

    hhh_bytes, hhh_headers, final_hhh_url = fetch(
        hhh_url
    )

    ident = hhh_identity(
        hhh_bytes
    )

    hhh_region = str(
        ident.get("region")
        or ""
    ).strip()

    plate_id = str(
        ident.get("plate_id")
        or ""
    ).strip()

    ra_deg = ident.get(
        "plate_ra_deg"
    )

    dec_deg = ident.get(
        "plate_dec_deg"
    )


    if hhh_region != expected_region:
        raise SystemExit(
            f"REFUSING: HHH REGION changed for {pid}: "
            f"{hhh_region!r} != {expected_region!r}"
        )

    if not plate_id:
        raise SystemExit(
            f"REFUSING: HHH has no PLATEID for {pid}"
        )

    if (
        ra_deg is None
        or dec_deg is None
    ):
        raise SystemExit(
            f"REFUSING: HHH plate centre absent for {pid}"
        )


    hhh_path = (
        target_dir
        / f"{expected_region}.hhh"
    )

    hhh_path.write_bytes(
        hhh_bytes
    )


    # --------------------------------------------------------------
    # Convert plate centre to explicit sexagesimal J2000 query.
    # --------------------------------------------------------------

    coord = SkyCoord(
        float(ra_deg) * u.deg,
        float(dec_deg) * u.deg,
        frame="icrs",
    )

    ra_text = coord.ra.to_string(
        unit=u.hour,
        sep=":",
        precision=3,
        pad=True,
    )

    dec_text = coord.dec.to_string(
        unit=u.deg,
        sep=":",
        precision=2,
        pad=True,
        alwayssign=True,
    )


    params = {
        "ra":
            ra_text,

        "dec":
            dec_text,

        "equinox":
            "J2000",

        "height":
            "5.0",

        "width":
            "5.0",

        "format":
            "FITS",

        "plate_id":
            plate_id,

        "action":
            "Extract",
    }


    request_url = (
        STS_ENDPOINT
        + "?"
        + urlencode(params)
    )


    # --------------------------------------------------------------
    # Exact STScI plate extraction.
    # --------------------------------------------------------------

    try:
        raw, response_headers, final_url = fetch(
            request_url
        )

    except Exception as exc:
        results.append({
            "exposure_id":
                pid,

            "expected_region":
                expected_region,

            "hhh_plate_id":
                plate_id,

            "hhh_sha256":
                sha256_bytes(
                    hhh_bytes
                ),

            "requested_ra_deg":
                ra_deg,

            "requested_dec_deg":
                dec_deg,

            "state":
                "EXACT_PLATE_EXTRACTION_FAILED",

            "error":
                f"{type(exc).__name__}: {exc}",

            "fits_path":
                "",

            "fits_sha256":
                "",

            "returned_region":
                "",

            "returned_plateid":
                "",
        })

        print(
            "   FAILED:",
            type(exc).__name__,
            str(exc)[:120],
        )

        continue


    if not raw.startswith(b"SIMPLE"):
        diagnostic = (
            target_dir
            / "stsci_response_nonfits.bin"
        )

        diagnostic.write_bytes(
            raw
        )

        results.append({
            "exposure_id":
                pid,

            "expected_region":
                expected_region,

            "hhh_plate_id":
                plate_id,

            "hhh_sha256":
                sha256_bytes(
                    hhh_bytes
                ),

            "requested_ra_deg":
                ra_deg,

            "requested_dec_deg":
                dec_deg,

            "state":
                "STS_RESPONSE_NOT_FITS",

            "error":
                (
                    "response did not begin with SIMPLE; "
                    f"saved {diagnostic}"
                ),

            "fits_path":
                "",

            "fits_sha256":
                "",

            "returned_region":
                "",

            "returned_plateid":
                "",
        })

        print(
            "   FAILED: non-FITS response"
        )

        continue


    # --------------------------------------------------------------
    # FITS/WCS/physical identity validation.
    # --------------------------------------------------------------

    try:
        with fits.open(
            io.BytesIO(raw),
            memmap=False,
        ) as hdul:

            image = hdul[0].data
            header = hdul[0].header

            if (
                image is None
                or image.ndim != 2
            ):
                raise ValueError(
                    "returned FITS is not a 2-D image"
                )

            wcs = WCS(
                header
            ).celestial

            if not wcs.has_celestial:
                raise ValueError(
                    "returned FITS lacks celestial WCS"
                )


            returned_region = str(
                header.get(
                    "REGION",
                    "",
                )
            ).strip()

            returned_plateid = str(
                header.get(
                    "PLATEID",
                    "",
                )
            ).strip()


            if (
                returned_region
                != expected_region
            ):
                raise ValueError(
                    "REGION mismatch: "
                    f"{returned_region!r} != "
                    f"{expected_region!r}"
                )


            if (
                returned_plateid
                != plate_id
            ):
                raise ValueError(
                    "PLATEID mismatch: "
                    f"{returned_plateid!r} != "
                    f"{plate_id!r}"
                )


            shape = list(
                image.shape
            )


    except Exception as exc:
        bad = (
            target_dir
            / "stsci_identity_mismatch.fits"
        )

        bad.write_bytes(
            raw
        )

        raise SystemExit(
            f"REFUSING: exact-plate FITS validation "
            f"failed for {pid}: {exc}"
        )


    fits_path = (
        target_dir
        / f"{expected_region}_{plate_id}_preflight.fits"
    )

    fits_path.write_bytes(
        raw
    )

    digest = sha256_bytes(
        raw
    )


    sidecar = {
        "artifact_type":
            "poss1_exact_plate_preflight_cutout",

        "recorded_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "science_analysis_performed":
            False,

        "exposure_id":
            pid,

        "frozen_region":
            expected_region,

        "hhh_url":
            final_hhh_url,

        "hhh_sha256":
            sha256_bytes(
                hhh_bytes
            ),

        "hhh_plate_id":
            plate_id,

        "request_url":
            request_url,

        "final_response_url":
            final_url,

        "request":
            params,

        "returned_region":
            returned_region,

        "returned_plateid":
            returned_plateid,

        "fits_sha256":
            digest,

        "fits_bytes":
            len(raw),

        "fits_shape":
            shape,

        "interpretation":
            (
                "Exact STScI DSS plate extraction was requested "
                "with explicit PLATE_ID derived from the already-"
                "validated SkyView HHH record. REGION and PLATEID "
                "were independently required to match before this "
                "cutout was accepted. This is an acquisition "
                "preflight only; no transient detector was run."
            ),
    }


    sidecar_path = (
        fits_path.with_suffix(
            ".fits.provenance.json"
        )
    )

    sidecar_path.write_text(
        json.dumps(
            sidecar,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


    results.append({
        "exposure_id":
            pid,

        "expected_region":
            expected_region,

        "hhh_plate_id":
            plate_id,

        "hhh_sha256":
            sha256_bytes(
                hhh_bytes
            ),

        "requested_ra_deg":
            ra_deg,

        "requested_dec_deg":
            dec_deg,

        "state":
            "EXACT_PLATE_CUTOUT_READY",

        "error":
            "",

        "fits_path":
            str(
                fits_path.resolve()
            ),

        "fits_sha256":
            digest,

        "returned_region":
            returned_region,

        "returned_plateid":
            returned_plateid,
    })


    print(
        "   PASS:",
        plate_id,
        returned_region,
        shape,
    )


# ----------------------------------------------------------------------
# Output.
# ----------------------------------------------------------------------

RESULT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with RESULT.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            results[0].keys()
        ),
    )

    writer.writeheader()
    writer.writerows(
        results
    )


passed = [
    r
    for r in results
    if r["state"]
    == "EXACT_PLATE_CUTOUT_READY"
]

failed = [
    r
    for r in results
    if r["state"]
    != "EXACT_PLATE_CUTOUT_READY"
]


report = {
    "operation":
        "v028_exact_plate_cutout_preflight",

    "targets":
        10,

    "exact_plate_cutout_ready":
        len(passed),

    "failed":
        len(failed),

    "result_sha256":
        sha256_file(
            RESULT
        ),

    "science_detector_runs":
        0,

    "cutout_arcmin":
        5.0,
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print()
print("=" * 82)
print("EXACT-PLATE CUTOUT PREFLIGHT COMPLETE")
print("=" * 82)
print(
    "PASS:",
    len(passed),
    "/ 10",
)
print(
    "FAIL:",
    len(failed),
)

if failed:
    print()
    print("Failures:")

    for r in failed:
        print(
            " ",
            r["exposure_id"],
            "=>",
            r["state"],
            r["error"],
        )

print()
print("Result:", RESULT)
print("Report:", REPORT)
print()
print("No transient detector was run.")

if len(passed) == 10:
    print()
    print(
        "MILESTONE: exact plate-specific FITS extraction "
        "is now available for all ten SkyView-fallback identities."
    )
