from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import RemoteDisconnected
import csv
import hashlib
import io
import json
import socket
import time


ROOT = Path.cwd()

INPUT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_V2_2026-08-21.csv"
)

OUT_ROOT = (
    ROOT
    / "cache"
    / "poss1_exact_plate_cutout_retry_v028"
)

OUTPUT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_RETRY_2026-08-21.csv"
)

REPORT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_RETRY_2026-08-21.json"
)

STS_ENDPOINT = (
    "https://archive.stsci.edu/cgi-bin/dss_plate_finder"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        return list(
            csv.DictReader(fh)
        )


def safe(text: str) -> str:
    return "".join(
        c if c.isalnum() or c in "-_."
        else "_"
        for c in text
    )


def write_checkpoint(rows):
    with OUTPUT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as fh:

        writer = csv.DictWriter(
            fh,
            fieldnames=list(
                rows[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(
            rows
        )


def fetch_once(url: str):
    req = Request(
        url,
        headers={
            "User-Agent":
                "historical-transient-pipeline/"
                "0.2.8-exact-plate-retry",

            "Accept":
                "application/fits,"
                "application/octet-stream,*/*",

            "Connection":
                "close",
        },
    )

    with urlopen(
        req,
        timeout=180,
    ) as response:

        return (
            response.read(),
            response.geturl(),
            dict(response.headers),
        )


if not INPUT.is_file():
    raise SystemExit(
        f"REFUSING: input missing: {INPUT}"
    )


from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


rows = read_csv(
    INPUT
)

if len(rows) != 10:
    raise SystemExit(
        f"REFUSING: expected 10 rows, got {len(rows)}."
    )


# ------------------------------------------------------------------
# Guard the identity result before touching the network.
# ------------------------------------------------------------------

for row in rows:
    if (
        row.get("identity_refresh_state")
        != "VALIDATED"
    ):
        raise SystemExit(
            "REFUSING: not all ten identities "
            "are reproduced as VALIDATED."
        )

    if not str(
        row.get("expected_region")
        or ""
    ).strip():
        raise SystemExit(
            "REFUSING: expected_region missing."
        )

    if not str(
        row.get("hhh_plate_id")
        or ""
    ).strip():
        raise SystemExit(
            "REFUSING: HHH PLATEID missing."
        )


ready_initial = [
    row
    for row in rows
    if (
        row.get("extraction_state")
        == "EXACT_PLATE_CUTOUT_READY"
    )
]

retry_rows = [
    row
    for row in rows
    if (
        row.get("extraction_state")
        != "EXACT_PLATE_CUTOUT_READY"
    )
]


if len(ready_initial) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one existing "
        f"successful extraction, got {len(ready_initial)}."
    )

if len(retry_rows) != 9:
    raise SystemExit(
        "REFUSING: expected exactly nine retry targets, "
        f"got {len(retry_rows)}."
    )


# Validate the already-successful artifact rather than assuming it.
existing = ready_initial[0]

existing_path = Path(
    existing["fits_path"]
)

if not existing_path.is_file():
    raise SystemExit(
        "REFUSING: previously successful FITS "
        "is no longer present."
    )

if (
    sha256_file(existing_path)
    != existing["fits_sha256"]
):
    raise SystemExit(
        "REFUSING: previously successful FITS "
        "hash changed."
    )


OUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)


# Add retry bookkeeping without losing original result.
extra_fields = (
    "retry_state",
    "retry_attempts",
    "retry_last_error",
    "retry_request_url",
    "retry_final_url",
    "retry_recorded_at_utc",
)

for row in rows:
    for field in extra_fields:
        row.setdefault(
            field,
            "",
        )


# Existing success remains authoritative.
existing["retry_state"] = (
    "PREEXISTING_EXACT_PLATE_CUTOUT_READY"
)

existing["retry_attempts"] = "0"


write_checkpoint(
    rows
)


print("=" * 82)
print("EXACT-PLATE NETWORK RETRY")
print("=" * 82)

print(
    "Existing validated FITS: 1"
)

print(
    "Network-only retry targets: 9"
)

print(
    "No SkyView identity rerun."
)

print(
    "No transient detector."
)

print()


# ------------------------------------------------------------------
# Retry only the nine network failures.
#
# Four attempts per plate with fixed increasing cooldowns.
# Requests remain serial.
# ------------------------------------------------------------------

retry_order = [
    row
    for row in rows
    if row is not existing
]

cooldowns = (
    15,
    30,
    60,
)


for index, row in enumerate(
    retry_order,
    start=1,
):

    pid = row[
        "exposure_id"
    ]

    region = str(
        row["expected_region"]
    ).strip().upper()

    plate_id = str(
        row["hhh_plate_id"]
    ).strip().upper()

    ra_deg = float(
        row["requested_ra_deg"]
    )

    dec_deg = float(
        row["requested_dec_deg"]
    )


    coord = SkyCoord(
        ra_deg * u.deg,
        dec_deg * u.deg,
        frame="icrs",
    )


    params = {
        "ra":
            coord.ra.to_string(
                unit=u.hour,
                sep=":",
                precision=3,
                pad=True,
            ),

        "dec":
            coord.dec.to_string(
                unit=u.deg,
                sep=":",
                precision=2,
                pad=True,
                alwayssign=True,
            ),

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
        + urlencode(
            params
        )
    )


    row[
        "retry_request_url"
    ] = request_url

    row[
        "retry_state"
    ] = "RETRY_IN_PROGRESS"


    print(
        f"[{index:02d}/09] "
        f"{pid} -> {region} / {plate_id}"
    )


    last_error = ""

    succeeded = False


    for attempt in range(
        1,
        5,
    ):
        row[
            "retry_attempts"
        ] = str(
            attempt
        )

        try:
            raw, final_url, headers = fetch_once(
                request_url
            )


            if not raw.startswith(
                b"SIMPLE"
            ):
                raise ValueError(
                    "response is not FITS"
                )


            with fits.open(
                io.BytesIO(raw),
                memmap=False,
            ) as hdul:

                if not hdul:
                    raise ValueError(
                        "empty FITS HDU list"
                    )

                image = hdul[
                    0
                ].data

                header = hdul[
                    0
                ].header


                if (
                    image is None
                    or image.ndim != 2
                ):
                    raise ValueError(
                        "returned FITS is not 2-D"
                    )


                wcs = WCS(
                    header
                ).celestial

                if not wcs.has_celestial:
                    raise ValueError(
                        "returned FITS has no "
                        "celestial WCS"
                    )


                returned_region = str(
                    header.get(
                        "REGION",
                        "",
                    )
                ).strip().upper()

                returned_plateid = str(
                    header.get(
                        "PLATEID",
                        "",
                    )
                ).strip().upper()


                if (
                    returned_region
                    != region
                ):
                    raise ValueError(
                        f"REGION mismatch: "
                        f"{returned_region!r} "
                        f"!= {region!r}"
                    )


                if (
                    returned_plateid
                    != plate_id
                ):
                    raise ValueError(
                        f"PLATEID mismatch: "
                        f"{returned_plateid!r} "
                        f"!= {plate_id!r}"
                    )


                shape = list(
                    image.shape
                )


            target_dir = (
                OUT_ROOT
                / safe(pid)
            )

            target_dir.mkdir(
                parents=True,
                exist_ok=True,
            )


            fits_path = (
                target_dir
                / (
                    f"{region}_"
                    f"{plate_id}_"
                    "retry.fits"
                )
            )

            fits_path.write_bytes(
                raw
            )


            digest = sha256_bytes(
                raw
            )


            provenance = {
                "artifact_type":
                    "poss1_exact_plate_cutout_retry",

                "recorded_at_utc":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "science_analysis_performed":
                    False,

                "detector_run":
                    False,

                "exposure_id":
                    pid,

                "expected_region":
                    region,

                "hhh_plate_id":
                    plate_id,

                "request_url":
                    request_url,

                "final_url":
                    final_url,

                "returned_region":
                    returned_region,

                "returned_plateid":
                    returned_plateid,

                "fits_sha256":
                    digest,

                "fits_shape":
                    shape,

                "network_attempt":
                    attempt,

                "note":
                    (
                        "Network-only retry of an exact "
                        "plate extraction whose physical "
                        "identity had already reproduced "
                        "successfully. No identity selection "
                        "or detector logic was rerun."
                    ),
            }


            prov_path = (
                fits_path.with_suffix(
                    ".fits.provenance.json"
                )
            )

            prov_path.write_text(
                json.dumps(
                    provenance,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )


            row[
                "extraction_state"
            ] = (
                "EXACT_PLATE_CUTOUT_READY"
            )

            row[
                "returned_region"
            ] = returned_region

            row[
                "returned_plateid"
            ] = returned_plateid

            row[
                "fits_path"
            ] = str(
                fits_path.resolve()
            )

            row[
                "fits_sha256"
            ] = digest

            row[
                "fits_shape"
            ] = json.dumps(
                shape
            )

            row[
                "retry_state"
            ] = "RETRY_SUCCEEDED"

            row[
                "retry_last_error"
            ] = ""

            row[
                "retry_final_url"
            ] = final_url

            row[
                "retry_recorded_at_utc"
            ] = datetime.now(
                timezone.utc
            ).isoformat()


            succeeded = True

            print(
                f"   PASS attempt {attempt}: "
                f"shape={shape}"
            )

            break


        except (
            HTTPError,
            URLError,
            RemoteDisconnected,
            ConnectionResetError,
            TimeoutError,
            socket.timeout,
            ValueError,
        ) as exc:

            last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            row[
                "retry_last_error"
            ] = last_error

            print(
                f"   attempt {attempt} failed: "
                f"{last_error[:125]}"
            )


            # Persist after every failed attempt.
            write_checkpoint(
                rows
            )


            if attempt < 4:
                time.sleep(
                    cooldowns[
                        attempt - 1
                    ]
                )


    if not succeeded:
        row[
            "retry_state"
        ] = (
            "NETWORK_RETRY_EXHAUSTED"
        )

        row[
            "retry_recorded_at_utc"
        ] = datetime.now(
            timezone.utc
        ).isoformat()


    # Durable checkpoint after every physical plate.
    write_checkpoint(
        rows
    )


    # Fixed inter-plate spacing to reduce archive pressure.
    if index < len(
        retry_order
    ):
        time.sleep(
            20
        )


# ------------------------------------------------------------------
# Final accounting.
# ------------------------------------------------------------------

ready = [
    row
    for row in rows
    if (
        row.get(
            "extraction_state"
        )
        == "EXACT_PLATE_CUTOUT_READY"
    )
]

unresolved = [
    row
    for row in rows
    if (
        row.get(
            "extraction_state"
        )
        != "EXACT_PLATE_CUTOUT_READY"
    )
]


states = Counter(
    row.get(
        "retry_state"
    )
    for row in rows
)


write_checkpoint(
    rows
)


report = {
    "operation":
        "v028_exact_plate_network_retry",

    "input_sha256":
        sha256_file(
            INPUT
        ),

    "output_sha256":
        sha256_file(
            OUTPUT
        ),

    "physical_identities":
        10,

    "identity_reruns":
        0,

    "preexisting_exact_fits":
        1,

    "network_retry_targets":
        9,

    "total_exact_fits_ready":
        len(
            ready
        ),

    "remaining_unresolved":
        len(
            unresolved
        ),

    "retry_states":
        dict(
            states
        ),

    "science_detector_runs":
        0,
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
print("NETWORK RETRY COMPLETE")
print("=" * 82)

print(
    "Exact FITS ready:",
    len(ready),
    "/ 10",
)

print(
    "Still unresolved:",
    len(unresolved),
)


if unresolved:
    print()
    print(
        "Network-unresolved exact identities:"
    )

    for row in unresolved:
        print(
            " ",
            row["exposure_id"],
            "->",
            row["expected_region"],
            "/",
            row["hhh_plate_id"],
            "->",
            row["retry_last_error"][:100],
        )


print()
print(
    "Output:",
    OUTPUT,
)

print(
    "Report:",
    REPORT,
)

print()
print(
    "No identity selection was rerun."
)

print(
    "No transient detector was run."
)
