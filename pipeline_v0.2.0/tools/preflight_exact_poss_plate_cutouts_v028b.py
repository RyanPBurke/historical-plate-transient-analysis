from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from collections import Counter
import csv
import hashlib
import inspect
import io
import json
import sys
import time


ROOT = Path.cwd()

REPAIR = (
    ROOT
    / "results"
    / "poss1_pixel_repair_v028.csv"
)

VI25 = (
    ROOT
    / "research"
    / "poss1_plate_metadata.csv"
)

IDENTITY_MANIFEST = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
    / "freeze_manifest.json"
)

POSS1_SRC = (
    ROOT
    / "src"
    / "transient_pipeline"
    / "poss1.py"
)

SKYVIEW_SRC = (
    ROOT
    / "src"
    / "transient_pipeline"
    / "poss1_skyview.py"
)

IDENTITY_CACHE = (
    ROOT
    / "cache"
    / "poss1_exact_plate_identity_refresh_v028"
)

OUT_ROOT = (
    ROOT
    / "cache"
    / "poss1_exact_plate_cutout_preflight_v028b"
)

RESULT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_V2_2026-08-21.csv"
)

REPORT = (
    ROOT
    / "research"
    / "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_V2_2026-08-21.json"
)


EXPECTED_IDENTITY_MANIFEST_SHA = (
    "56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e"
)

EXPECTED_POSS1_SHA = (
    "6161a74d5ce76f70235c66a748077b3517f7d2d7946e9f48998927c331374ac7"
)

EXPECTED_SKYVIEW_SHA = (
    "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e"
)

EXPECTED_VI25_SHA = (
    "41b5732086f5a1d17e6f6d85c99f97a48a0985f19db1ad496cd3e3a2387830c1"
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(
        data
    ).hexdigest()


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(
            csv.DictReader(fh)
        )


def safe(pid: str) -> str:
    return "".join(
        c
        if c.isalnum() or c in "-_."
        else "_"
        for c in pid
    )


def fetch(url: str, attempts: int = 3):
    last = None

    for n in range(
        1,
        attempts + 1,
    ):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent":
                        "historical-transient-pipeline/"
                        "0.2.8-exact-plate-extraction"
                },
            )

            with urlopen(
                req,
                timeout=120,
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

            if n < attempts:
                time.sleep(
                    2 ** (n - 1)
                )

    raise last


def recursive_first(
    obj,
    key: str,
):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]

        for value in obj.values():
            found = recursive_first(
                value,
                key,
            )

            if found not in (
                None,
                "",
            ):
                return found

    elif isinstance(obj, list):
        for value in obj:
            found = recursive_first(
                value,
                key,
            )

            if found not in (
                None,
                "",
            ):
                return found

    return None


for path in (
    REPAIR,
    VI25,
    IDENTITY_MANIFEST,
    POSS1_SRC,
    SKYVIEW_SRC,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: missing required file: {path}"
        )


guards = {
    "identity_manifest":
        (
            sha256_file(
                IDENTITY_MANIFEST
            ),
            EXPECTED_IDENTITY_MANIFEST_SHA,
        ),

    "poss1.py":
        (
            sha256_file(
                POSS1_SRC
            ),
            EXPECTED_POSS1_SHA,
        ),

    "poss1_skyview.py":
        (
            sha256_file(
                SKYVIEW_SRC
            ),
            EXPECTED_SKYVIEW_SHA,
        ),

    "VI25":
        (
            sha256_file(
                VI25
            ),
            EXPECTED_VI25_SHA,
        ),
}


for label, (
    actual,
    expected,
) in guards.items():

    if actual != expected:
        raise SystemExit(
            f"REFUSING: {label} hash changed.\n"
            f"expected={expected}\n"
            f"actual={actual}"
        )


# ----------------------------------------------------------------------
# Import the exact reviewed resolver.
# ----------------------------------------------------------------------

sys.path.insert(
    0,
    str(ROOT / "src"),
)

from transient_pipeline.poss1 import (
    load_vi25_records,
    vi25_start_utc,
)

from transient_pipeline.poss1_skyview import (
    fallback_identity,
)

from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


# ----------------------------------------------------------------------
# Inputs.
# ----------------------------------------------------------------------

repair_rows = read_csv(
    REPAIR
)

repair_by_id = {
    str(
        r.get("exposure_id")
        or r.get("job_key")
        or ""
    ):
        r
    for r in repair_rows
}


if not TARGET_IDS <= set(
    repair_by_id
):
    raise SystemExit(
        "REFUSING: repair result does not contain exact ten."
    )


vi25_records = load_vi25_records(
    VI25
)


def get_vi25_record(
    recno: int,
):
    key = int(recno)

    if key not in vi25_records:
        raise ValueError(
            f"VI/25 recno {key} absent from loaded mapping"
        )

    record = vi25_records[key]

    if int(record.recno) != key:
        raise ValueError(
            f"VI/25 mapping integrity failure: "
            f"key={key}, record.recno={record.recno}"
        )

    return record


fallback_params = set(
    inspect.signature(
        fallback_identity
    ).parameters
)


IDENTITY_CACHE.mkdir(
    parents=True,
    exist_ok=True,
)

OUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT.parent.mkdir(
    parents=True,
    exist_ok=True,
)


results = []


print("=" * 84)
print("CORRECTED EXACT POSS-I PLATE EXTRACTION PREFLIGHT")
print("=" * 84)
print("Targets: 10")
print(
    "SkyView identity path: reviewed "
    "descriptor -> raw_plate_directory() -> HHH"
)
print(
    "STScI extraction: explicit HHH-derived PLATE_ID"
)
print("Cutout: 5 x 5 arcmin")
print("No transient detector will run.")
print()


for index, pid in enumerate(
    sorted(TARGET_IDS),
    start=1,
):
    row = repair_by_id[
        pid
    ]

    expected_region = str(
        row.get("finder_region")
        or ""
    ).strip().upper()

    recno = int(
        row["recno"]
    )

    band = str(
        row["band"]
    ).strip().upper()

    print(
        f"[{index:02d}/10] "
        f"{pid} -> {expected_region}"
    )


    result = {
        "exposure_id":
            pid,

        "recno":
            recno,

        "band":
            band,

        "expected_region":
            expected_region,

        "identity_refresh_state":
            "",

        "hhh_plate_id":
            "",

        "fallback_hhh_url":
            "",

        "requested_ra_deg":
            "",

        "requested_dec_deg":
            "",

        "extraction_state":
            "",

        "returned_region":
            "",

        "returned_plateid":
            "",

        "fits_path":
            "",

        "fits_sha256":
            "",

        "fits_shape":
            "",

        "error":
            "",
    }


    # ==============================================================
    # 1. Run the exact reviewed SkyView fallback.
    #
    # This is the same identity code already frozen/reviewed.
    # We do NOT construct a raw HHH URL ourselves.
    # ==============================================================

    try:
        record = get_vi25_record(
            recno
        )

        kwargs = {
            "record":
                record,

            "band":
                band,

            "stage":
                "poss1-exact-cutout-preflight-v028b",

            "job_key":
                pid,

            "attempt":
                1,

            "cache_dir":
                IDENTITY_CACHE,

            "evidence":
                None,

            "primary_failure":
                str(
                    row.get(
                        "primary_archive_failure"
                    )
                    or
                    "exact_plate_pixel_materialization"
                ),

            "expected_region":
                expected_region,
        }


        # Current frozen source accepts authoritative normalized
        # VI/25 start time.  Preserve compatibility if a historical
        # signature is encountered, but do not duplicate timing logic.
        if (
            "expected_start_utc"
            in fallback_params
        ):
            kwargs[
                "expected_start_utc"
            ] = vi25_start_utc(
                record,
                band,
            )


        fb = fallback_identity(
            **kwargs
        )


        fb_status = str(
            fb.get(
                "identity_status"
            )
            or ""
        )

        fb_region = str(
            fb.get(
                "finder_region"
            )
            or ""
        ).strip().upper()


        if (
            fb_status != "validated"
            or fb_region != expected_region
        ):
            raise ValueError(
                "reviewed fallback did not reproduce "
                f"frozen identity: "
                f"status={fb_status!r}, "
                f"region={fb_region!r}"
            )


        result[
            "identity_refresh_state"
        ] = "VALIDATED"


        plate_id = str(
            fb.get(
                "finder_plate_id"
            )
            or ""
        ).strip().upper()


        hhh_url = str(
            fb.get(
                "skyview_raw_hhh_url"
            )
            or fb.get(
                "skyview_hhh_url"
            )
            or ""
        ).strip()


        # ----------------------------------------------------------
        # The fallback always writes a provenance sidecar.
        # Use it only as an exact resolver output if a field was not
        # exposed directly in the returned result.
        # ----------------------------------------------------------

        identity_dir = (
            IDENTITY_CACHE
            / safe(pid)
        )

        sidecars = sorted(
            identity_dir.glob(
                "*_skyview_identity.provenance.json"
            )
        )


        if len(sidecars) != 1:
            raise ValueError(
                "expected exactly one successful "
                "SkyView identity sidecar; "
                f"found {len(sidecars)}"
            )


        sidecar_obj = json.loads(
            sidecars[0].read_text(
                encoding="utf-8",
            )
        )


        if not hhh_url:
            hhh_url = str(
                recursive_first(
                    sidecar_obj,
                    "hhh_url",
                )
                or ""
            ).strip()


        if not plate_id:
            # Filename is written from ident['plate_id'] by the
            # reviewed fallback itself.
            suffix = (
                "_skyview_identity"
                ".provenance.json"
            )

            name = sidecars[
                0
            ].name

            if name.endswith(
                suffix
            ):
                plate_id = (
                    name[
                        :-len(suffix)
                    ]
                    .strip()
                    .upper()
                )


        if not plate_id:
            plate_id = str(
                recursive_first(
                    sidecar_obj,
                    "plate_id",
                )
                or ""
            ).strip().upper()


        if not plate_id:
            raise ValueError(
                "reviewed fallback validated identity "
                "but yielded no recoverable PLATEID"
            )


        result[
            "hhh_plate_id"
        ] = plate_id

        result[
            "fallback_hhh_url"
        ] = hhh_url


    except Exception as exc:
        result[
            "identity_refresh_state"
        ] = (
            "IDENTITY_REFRESH_FAILED"
        )

        result[
            "extraction_state"
        ] = (
            "NOT_ATTEMPTED"
        )

        result[
            "error"
        ] = (
            f"{type(exc).__name__}: {exc}"
        )

        results.append(
            result
        )

        print(
            "   IDENTITY FAILED:",
            result["error"][:160],
        )

        continue


    # ==============================================================
    # 2. Exact-plate STScI extraction.
    #
    # Use the frozen VI/25 nominal pointing solely as cutout centre.
    # Physical plate selection is controlled by the independently
    # recovered HHH PLATEID.
    # ==============================================================

    try:
        ra_deg = float(
            row["ra_deg"]
        )

        dec_deg = float(
            row["dec_deg"]
        )

        result[
            "requested_ra_deg"
        ] = ra_deg

        result[
            "requested_dec_deg"
        ] = dec_deg


        coord = SkyCoord(
            ra_deg * u.deg,
            dec_deg * u.deg,
            frame="icrs",
        )


        ra_text = (
            coord.ra.to_string(
                unit=u.hour,
                sep=":",
                precision=3,
                pad=True,
            )
        )

        dec_text = (
            coord.dec.to_string(
                unit=u.deg,
                sep=":",
                precision=2,
                pad=True,
                alwayssign=True,
            )
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
            + urlencode(
                params
            )
        )


        raw, headers, final_url = fetch(
            request_url
        )


        target_dir = (
            OUT_ROOT
            / safe(pid)
        )

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


        if not raw.startswith(
            b"SIMPLE"
        ):
            diag = (
                target_dir
                / "stsci_nonfits_response.bin"
            )

            diag.write_bytes(
                raw
            )

            raise ValueError(
                "STScI extraction response was "
                f"not FITS; saved {diag}"
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
                    "returned FITS is not a "
                    "2-D image"
                )


            wcs = WCS(
                header
            ).celestial

            if not wcs.has_celestial:
                raise ValueError(
                    "returned FITS lacks "
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
                returned_plateid
                != plate_id
            ):
                raise ValueError(
                    "PLATEID mismatch: "
                    f"{returned_plateid!r} "
                    f"!= {plate_id!r}"
                )


            if (
                returned_region
                != expected_region
            ):
                raise ValueError(
                    "REGION mismatch: "
                    f"{returned_region!r} "
                    f"!= {expected_region!r}"
                )


            shape = list(
                image.shape
            )


        fits_path = (
            target_dir
            / (
                f"{expected_region}_"
                f"{plate_id}_"
                "preflight.fits"
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
                "poss1_exact_plate_cutout_preflight",

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

            "vi25_recno":
                recno,

            "band":
                band,

            "frozen_region":
                expected_region,

            "identity_source":
                "reviewed_skyview_raw_fallback",

            "fallback_hhh_url":
                hhh_url,

            "hhh_plate_id":
                plate_id,

            "stsci_request_url":
                request_url,

            "stsci_final_url":
                final_url,

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

            "note":
                (
                    "Physical plate identity was reproduced "
                    "through the frozen SkyView descriptor/"
                    "raw-HHH resolver. The resulting HHH "
                    "PLATEID was supplied explicitly to the "
                    "STScI DSS Plate Finder extraction API. "
                    "Returned PLATEID and REGION were both "
                    "required to match before acceptance. "
                    "No transient detector was run."
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


        result[
            "extraction_state"
        ] = (
            "EXACT_PLATE_CUTOUT_READY"
        )

        result[
            "returned_region"
        ] = returned_region

        result[
            "returned_plateid"
        ] = returned_plateid

        result[
            "fits_path"
        ] = str(
            fits_path.resolve()
        )

        result[
            "fits_sha256"
        ] = digest

        result[
            "fits_shape"
        ] = json.dumps(
            shape
        )


        print(
            "   PASS:",
            f"PLATEID={plate_id}",
            f"REGION={returned_region}",
            f"shape={shape}",
        )


    except Exception as exc:
        result[
            "extraction_state"
        ] = (
            "EXACT_PLATE_EXTRACTION_FAILED"
        )

        result[
            "error"
        ] = (
            f"{type(exc).__name__}: {exc}"
        )

        print(
            "   EXTRACTION FAILED:",
            result["error"][:160],
        )


    results.append(
        result
    )


# ----------------------------------------------------------------------
# Persist result even when some targets failed.
# ----------------------------------------------------------------------

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


states = Counter(
    r[
        "extraction_state"
    ]
    for r in results
)


ready = [
    r
    for r in results
    if r[
        "extraction_state"
    ]
    == "EXACT_PLATE_CUTOUT_READY"
]


failed = [
    r
    for r in results
    if r[
        "extraction_state"
    ]
    != "EXACT_PLATE_CUTOUT_READY"
]


report = {
    "operation":
        "v028_corrected_exact_plate_cutout_preflight",

    "identity_method":
        (
            "frozen reviewed SkyView descriptor "
            "plus raw-HHH fallback"
        ),

    "targets":
        10,

    "identity_reproduced":
        sum(
            r[
                "identity_refresh_state"
            ]
            == "VALIDATED"
            for r in results
        ),

    "exact_plate_cutout_ready":
        len(
            ready
        ),

    "failed":
        len(
            failed
        ),

    "states":
        dict(
            states
        ),

    "result_sha256":
        sha256_file(
            RESULT
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
print("=" * 84)
print(
    "CORRECTED EXACT-PLATE PREFLIGHT COMPLETE"
)
print("=" * 84)

print(
    "Identity reproduced:",
    report[
        "identity_reproduced"
    ],
    "/ 10",
)

print(
    "Exact FITS ready:    ",
    len(ready),
    "/ 10",
)

print(
    "Failed:              ",
    len(failed),
)


if failed:
    print()
    print("Unresolved:")

    for r in failed:
        print(
            " ",
            r["exposure_id"],
            "=>",
            r["extraction_state"],
            "=>",
            r["error"][:140],
        )


print()
print("Result:")
print(" ", RESULT)

print("Report:")
print(" ", REPORT)

print()
print(
    "No transient detector was run."
)

if len(
    ready
) == 10:

    print()
    print(
        "MILESTONE: all ten previously pathless "
        "POSS-I identities now have exact-plate "
        "STScI FITS cutouts."
    )
