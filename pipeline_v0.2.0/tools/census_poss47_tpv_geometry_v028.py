from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import base64
import csv
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


ROOT = Path.cwd()

CANONICAL = (
    ROOT / "research" /
    "canonical_sub5_pairs_74.csv"
)

PAIR_MAP = (
    ROOT / "research" /
    "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
)

NATIVE10 = (
    ROOT / "research" /
    "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.csv"
)

ENV_REPORT = (
    ROOT / "research" /
    "DETECTOR_ENVIRONMENT_V028_2026-08-21.json"
)

SKY_SOURCE = (
    ROOT / "src" /
    "transient_pipeline" /
    "poss1_skyview.py"
)

JAR = (
    ROOT / "tools" /
    "vendor" /
    "skyview.jar"
)

OUT_CSV = (
    ROOT / "research" /
    "SUB5_V028_POSS47_TPV_GEOMETRY_CENSUS_2026-08-21.csv"
)

OUT_JSON = (
    ROOT / "research" /
    "SUB5_V028_POSS47_TPV_GEOMETRY_CENSUS_2026-08-21.json"
)

WORK = (
    ROOT / "work" /
    "poss47_tpv_geometry_census_v028"
)

DASCH_CACHE = (
    WORK / "dasch_metadata"
)

POSS_GRID_CACHE = (
    WORK / "poss_wcs_grids"
)

JAVA_SOURCE = (
    WORK / "DSSGridProbe.java"
)


EXPECTED_CANONICAL_SHA = (
    "58529e1d4de46f3c49865a89454d1cd488ee23ec920b01250006f2180d2ed99a"
)

EXPECTED_SKY_SOURCE_SHA = (
    "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e"
)

EXPECTED_JAR_SHA = (
    "2b949f68d73899cd63b2f600f60f6c5dfd1795532ed29b6ea986f71f83d36afe"
)

EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
)


API = (
    "https://api.starglass.cfa.harvard.edu/"
    "public/dasch/dr7/mosaic_package"
)

BINNING = 16

# 65 x 65 gives 4225 samples per POSS plate.
GRID_N = 65


def sha_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def sha_bytes(data: bytes) -> str:
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


def write_csv(
    path: Path,
    rows,
):
    if not rows:
        return

    with path.open(
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
        writer.writerows(rows)


def safe(text: str) -> str:
    return "".join(
        c if (
            c.isalnum()
            or c in "-_."
        )
        else "_"
        for c in text
    )


def parse_utc(text: str) -> datetime:
    raw = str(text).strip()

    # DASCH can encode an exact minute boundary using
    # seconds=60, e.g. 09:27:60.0Z. Python's ISO parser
    # rejects that representation, so normalize it by
    # parsing second 59 and adding one second.
    overflow = re.match(
        r"^(.*T\d{2}:\d{2}):60(\.\d+)?"
        r"(Z|[+-]\d{2}:\d{2})$",
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
        raise ValueError(
            "empty UTC timestamp"
        )

    if raw.endswith("Z"):
        raw = (
            raw[:-1]
            + "+00:00"
        )

    try:
        dt = datetime.fromisoformat(
            raw
        )
    except ValueError:
        dt = datetime.fromisoformat(
            raw.replace(
                " ",
                "T",
                1,
            )
        )

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        timezone.utc
    )


# ======================================================================
# Guards.
# ======================================================================

for path in (
    CANONICAL,
    PAIR_MAP,
    NATIVE10,
    ENV_REPORT,
    SKY_SOURCE,
    JAR,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: missing required file: {path}"
        )


if sha_file(
    CANONICAL
) != EXPECTED_CANONICAL_SHA:

    raise SystemExit(
        "REFUSING: canonical queue hash changed."
    )


if sha_file(
    SKY_SOURCE
) != EXPECTED_SKY_SOURCE_SHA:

    raise SystemExit(
        "REFUSING: frozen POSS SkyView source changed."
    )


if sha_file(
    JAR
) != EXPECTED_JAR_SHA:

    raise SystemExit(
        "REFUSING: SkyView JAR changed."
    )


env = json.loads(
    ENV_REPORT.read_text(
        encoding="utf-8"
    )
)


if (
    env.get("detector_sha256")
    != EXPECTED_DETECTOR_SHA
):
    raise SystemExit(
        "REFUSING: detector environment guard failed."
    )


if env.get(
    "detector_run"
) is not False:

    raise SystemExit(
        "REFUSING: detector environment report changed."
    )


WORK.mkdir(
    parents=True,
    exist_ok=True,
)

DASCH_CACHE.mkdir(
    parents=True,
    exist_ok=True,
)

POSS_GRID_CACHE.mkdir(
    parents=True,
    exist_ok=True,
)


# ======================================================================
# Load authoritative 47-row POSS map and 74-row canonical queue.
# ======================================================================

canonical = read_csv(
    CANONICAL
)

pair_rows = read_csv(
    PAIR_MAP
)

native10_rows = read_csv(
    NATIVE10
)


if len(canonical) != 74:
    raise SystemExit(
        f"REFUSING: canonical rows={len(canonical)}"
    )


if len(pair_rows) != 47:
    raise SystemExit(
        f"REFUSING: pair-map rows={len(pair_rows)}"
    )


if len(native10_rows) != 10:
    raise SystemExit(
        f"REFUSING: native-ten rows={len(native10_rows)}"
    )


canonical_by_order = {
    int(
        float(
            r["canonical_order"]
        )
    ): r
    for r in canonical
}


native10 = {
    r["exposure_id"]: r
    for r in native10_rows
}


# Every pair-map row must agree with canonical identity.
for row in pair_rows:

    order = int(
        float(
            row["canonical_order"]
        )
    )

    if order not in canonical_by_order:
        raise SystemExit(
            f"REFUSING: order {order} absent canonical."
        )

    c = canonical_by_order[
        order
    ]

    if (
        row["pair_key"]
        != c["pair_key"]
    ):
        raise SystemExit(
            f"REFUSING: pair-key disagreement order {order}."
        )


# ======================================================================
# Import hash-guarded frozen SkyView descriptor machinery.
# ======================================================================

sys.path.insert(
    0,
    str(
        ROOT / "src"
    ),
)

import transient_pipeline.poss1_skyview as sv


descriptor_cache = {}


def load_descriptor(
    band: str,
):
    band = band.upper()

    if band in descriptor_cache:
        return descriptor_cache[
            band
        ]

    if band == "E":
        url = (
            sv.SKYVIEW_DSS1R_DESCRIPTOR
        )
    elif band == "O":
        url = (
            sv.SKYVIEW_DSS1B_DESCRIPTOR
        )
    else:
        raise ValueError(
            f"unexpected POSS band {band!r}"
        )

    session = sv.ValidatedSession(
        sv.RetryPolicy(
            attempts=4,
            base_delay_s=2.0,
            max_delay_s=20.0,
            timeout_s=90.0,
        ),
        user_agent=(
            "historical-transient-pipeline/"
            "0.2.8-geometry-census"
        ),
    )

    response = session.request(
        "GET",
        url,
        validator=(
            sv._validate_descriptor_response
        ),
    )

    desc = sv.parse_skyview_descriptor(
        response.content
    )

    descriptor_cache[
        band
    ] = desc

    return desc


def resolve_raw_dir(
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
    # Ten repaired plates already have an exact,
    # identity-validated native source.
    if pid in native10:
        return (
            native10[
                pid
            ][
                "raw_plate_directory"
            ].strip(),
            "frozen_native10_source_map",
        )

    parts = pid.split(":")

    if len(parts) < 4:
        raise ValueError(
            f"bad POSS exposure ID: {pid}"
        )

    band = parts[2].upper()

    desc = load_descriptor(
        band
    )

    wanted = region.lower()

    matches = [
        entry
        for entry in desc.images
        if Path(
            entry.path
        ).name.lower()
        == wanted
    ]

    if len(matches) != 1:
        raise ValueError(
            f"SkyView descriptor exact-region "
            f"matches={len(matches)} "
            f"for {pid} / {region}"
        )

    raw_dir = sv.raw_plate_directory(
        band=band,
        region=region,
        descriptor_entry=matches[0],
    )

    return (
        raw_dir,
        "frozen_descriptor_exact_region",
    )


# ======================================================================
# Compile one WCS-only Java sampler.
#
# Critically, it NEVER calls DSSImage.getData().
# ======================================================================

java_source = r'''
import java.io.*;
import skyview.survey.DSSImage;
import skyview.geometry.WCS;
import skyview.geometry.Transformer;

public class DSSGridProbe {

    static double[] pixelToSky(
        WCS wcs,
        double x,
        double y
    ) throws Exception {

        Transformer inv =
            wcs.inverse();

        double[] vec =
            new double[3];

        inv.transform(
            new double[] {x, y},
            vec
        );

        double r =
            Math.sqrt(
                vec[0] * vec[0]
                + vec[1] * vec[1]
                + vec[2] * vec[2]
            );

        double vx =
            vec[0] / r;

        double vy =
            vec[1] / r;

        double vz =
            vec[2] / r;

        double ra =
            Math.atan2(
                vy,
                vx
            );

        if (ra < 0) {
            ra += 2.0 * Math.PI;
        }

        double dec =
            Math.asin(
                vz
            );

        return new double[] {
            Math.toDegrees(ra),
            Math.toDegrees(dec)
        };
    }


    public static void main(
        String[] args
    ) throws Exception {

        if (args.length != 3) {
            throw new IllegalArgumentException(
                "usage: DSSGridProbe "
                + "<raw_dir> <grid_n> <csv>"
            );
        }

        String rawDir =
            args[0];

        int gridN =
            Integer.parseInt(
                args[1]
            );

        String output =
            args[2];

        DSSImage image =
            new DSSImage(
                rawDir
            );

        int width =
            image.getWidth();

        int height =
            image.getHeight();

        WCS wcs =
            image.getWCS();

        PrintWriter out =
            new PrintWriter(
                new BufferedWriter(
                    new FileWriter(
                        output
                    )
                )
            );

        out.println(
            "ix,iy,x,y,ra_deg,dec_deg"
        );

        for (
            int iy = 0;
            iy < gridN;
            iy++
        ) {

            double y =
                (height - 1.0)
                * iy
                / (gridN - 1.0);

            for (
                int ix = 0;
                ix < gridN;
                ix++
            ) {

                double x =
                    (width - 1.0)
                    * ix
                    / (gridN - 1.0);

                double[] sky =
                    pixelToSky(
                        wcs,
                        x,
                        y
                    );

                out.println(
                    ix
                    + ","
                    + iy
                    + ","
                    + x
                    + ","
                    + y
                    + ","
                    + sky[0]
                    + ","
                    + sky[1]
                );
            }
        }

        out.close();

        System.out.println(
            "width="
            + width
        );

        System.out.println(
            "height="
            + height
        );
    }
}
'''


JAVA_SOURCE.write_text(
    java_source,
    encoding="utf-8",
)


compile_cp = subprocess.run(
    [
        "javac",
        "-cp",
        str(JAR),
        "-d",
        str(WORK),
        str(JAVA_SOURCE),
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    check=False,
)


if compile_cp.returncode != 0:
    raise SystemExit(
        "REFUSING: Java WCS helper failed to compile:\n"
        + (
            compile_cp.stderr
            or compile_cp.stdout
            or ""
        )
    )


classpath = (
    str(JAR)
    + os.pathsep
    + str(WORK)
)


# ======================================================================
# Cache POSS WCS grids by physical exposure.
# ======================================================================

poss_grid_cache = {}


def get_poss_grid(
    pid: str,
    region: str,
):
    key = (
        pid,
        region,
    )

    if key in poss_grid_cache:
        return poss_grid_cache[
            key
        ]

    raw_dir, source_kind = (
        resolve_raw_dir(
            pid,
            region,
        )
    )

    out = (
        POSS_GRID_CACHE
        / (
            safe(pid)
            + "_"
            + region
            + "_grid65.csv"
        )
    )

    if not out.exists():

        cp = subprocess.run(
            [
                "java",
                "-cp",
                classpath,
                "DSSGridProbe",
                raw_dir,
                str(GRID_N),
                str(out),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=300,
        )

        if cp.returncode != 0:
            raise RuntimeError(
                cp.stderr
                or cp.stdout
                or "DSSGridProbe failed"
            )

    grid = read_csv(
        out
    )

    if len(grid) != (
        GRID_N
        * GRID_N
    ):
        raise ValueError(
            f"{pid}: grid has "
            f"{len(grid)} rows"
        )

    result = {
        "raw_dir":
            raw_dir,

        "source_kind":
            source_kind,

        "grid_path":
            out,

        "grid_sha256":
            sha_file(out),

        "rows":
            grid,
    }

    poss_grid_cache[
        key
    ] = result

    return result


# ======================================================================
# Direct DASCH metadata retrieval/cache.
# ======================================================================

dasch_metadata_cache = {}


def get_dasch_metadata(
    plate_id: str,
):
    if plate_id in dasch_metadata_cache:
        return dasch_metadata_cache[
            plate_id
        ]

    cache = (
        DASCH_CACHE
        / (
            plate_id
            + "_mosaic_package_metadata.json"
        )
    )

    if cache.exists():
        obj = json.loads(
            cache.read_text(
                encoding="utf-8"
            )
        )

        dasch_metadata_cache[
            plate_id
        ] = obj

        return obj


    payload = json.dumps(
        {
            "plate_id":
                plate_id,

            "binning":
                BINNING,
        },
        separators=(",", ":"),
    ).encode("utf-8")


    last_error = None

    response_obj = None


    for attempt in range(
        1,
        4,
    ):

        request = Request(
            API,
            data=payload,
            method="POST",
            headers={
                "Accept":
                    "application/json",

                "Content-Type":
                    "application/json",

                "User-Agent":
                    "historical-transient-pipeline/"
                    "0.2.8-poss47-geometry-census",
            },
        )

        try:
            with urlopen(
                request,
                timeout=120,
            ) as response:

                raw = response.read()

            response_obj = json.loads(
                raw.decode(
                    "utf-8"
                )
            )

            break

        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:

            last_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            if attempt < 3:
                time.sleep(
                    attempt * 2
                )


    if response_obj is None:
        raise RuntimeError(
            "mosaic_package failed: "
            + str(last_error)
        )


    metadata = response_obj.get(
        "metadata"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        raise ValueError(
            "mosaic_package metadata absent"
        )


    cache.write_text(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


    dasch_metadata_cache[
        plate_id
    ] = metadata

    return metadata


# ======================================================================
# DASCH TPV reconstruction.
# ======================================================================

def count_solutions(
    base_hdr,
):
    # Exact current daschlab semantics.
    nsol = 1

    if "CTYPE1A" in base_hdr:

        while True:
            next_key = chr(
                ord("A")
                + nsol
            )

            if (
                f"CTYPE1{next_key}"
                not in base_hdr
            ):
                break

            nsol += 1


        if nsol == 1:
            raise ValueError(
                "unexpected astrometry header: "
                "CTYPE1A but no CTYPE1B"
            )

    return nsol


def build_solution_wcs(
    metadata,
    solnum: int,
):
    astrometry = metadata.get(
        "astrometry"
    )

    if not isinstance(
        astrometry,
        dict,
    ):
        raise ValueError(
            "no astrometry metadata"
        )

    encoded = astrometry.get(
        "b01HeaderGz"
    )

    if not encoded:
        raise ValueError(
            "no b01HeaderGz"
        )


    raw = gzip.decompress(
        base64.b64decode(
            encoded
        )
    )


    try:
        text = raw.decode(
            "ascii"
        )
    except UnicodeDecodeError:
        text = raw.decode(
            "latin-1"
        )


    base_hdr = fits.Header.fromstring(
        text,
        sep="\n",
    )


    nsol = count_solutions(
        base_hdr
    )


    if solnum < 0 or solnum >= nsol:
        raise ValueError(
            f"solnum {solnum} outside "
            f"0..{nsol - 1}"
        )


    # Current daschlab:
    # 1 solution => untagged.
    # Multiple => input tags A, B, C ...
    if nsol == 1:
        input_tag = ""
    else:
        input_tag = chr(
            ord("A")
            + solnum
        )


    h = fits.Header()

    h["WCSAXES"] = 2
    h["WCSNAME"] = (
        f"DASCH astrometric solution "
        f"#{solnum + 1}"
    )

    h["RADESYS"] = "ICRS"

    h["CTYPE1"] = "RA---TPV"
    h["CTYPE2"] = "DEC--TPV"

    h["CUNIT1"] = "deg"
    h["CUNIT2"] = "deg"


    def skey(
        key,
    ):
        return (
            key
            + input_tag
        )


    for key in (
        "CRVAL1",
        "CRVAL2",
        "CRPIX1",
        "CRPIX2",
        "CD1_1",
        "CD1_2",
        "CD2_1",
        "CD2_2",
    ):
        if skey(
            key
        ) not in base_hdr:
            raise ValueError(
                f"missing WCS keyword "
                f"{skey(key)}"
            )


    h["CRVAL1"] = base_hdr[
        skey("CRVAL1")
    ]

    h["CRVAL2"] = base_hdr[
        skey("CRVAL2")
    ]

    h["CRPIX1"] = (
        (
            base_hdr[
                skey("CRPIX1")
            ]
            - 0.5
        )
        / BINNING
        + 0.5
    )

    h["CRPIX2"] = (
        (
            base_hdr[
                skey("CRPIX2")
            ]
            - 0.5
        )
        / BINNING
        + 0.5
    )


    for key in (
        "CD1_1",
        "CD1_2",
        "CD2_1",
        "CD2_2",
    ):
        h[key] = (
            base_hdr[
                skey(key)
            ]
            * BINNING
        )


    pv_count = 0

    for key, value in base_hdr.items():

        if not key.startswith(
            "PV"
        ):
            continue


        if input_tag == "":

            belongs = (
                bool(key)
                and key[-1].isdigit()
            )

            outkey = key

        else:

            belongs = key.endswith(
                input_tag
            )

            outkey = (
                key[:-1]
                if belongs
                else key
            )


        if belongs:
            h[
                outkey
            ] = value

            pv_count += 1


    if pv_count == 0:
        raise ValueError(
            "selected solution has no PV terms"
        )


    wcs = WCS(
        h
    ).celestial


    if not wcs.has_celestial:
        raise ValueError(
            "selected WCS not celestial"
        )


    mosaic = metadata.get(
        "mosaic"
    )

    if not isinstance(
        mosaic,
        dict,
    ):
        raise ValueError(
            "mosaic metadata absent"
        )


    base_w = int(
        mosaic["b01Width"]
    ) // BINNING

    base_h = int(
        mosaic["b01Height"]
    ) // BINNING


    # daschlab rotates the base data to make it agree
    # with the archived astrometric WCS.
    rotation_delta = (
        astrometry.get(
            "rotationDelta"
        )
    )


    if rotation_delta == 90:
        rot_k = -1

    elif rotation_delta in (
        180,
        -180,
    ):
        rot_k = 2

    elif rotation_delta == -90:
        rot_k = 1

    elif rotation_delta in (
        0,
        None,
    ):
        rot_k = 0

    else:
        raise ValueError(
            "unexpected rotationDelta="
            + repr(
                rotation_delta
            )
        )


    if abs(
        rot_k
    ) % 2:
        final_h = base_w
        final_w = base_h

    else:
        final_h = base_h
        final_w = base_w


    return {
        "wcs":
            wcs,

        "nsol":
            nsol,

        "input_tag":
            input_tag,

        "pv_count":
            pv_count,

        "width":
            final_w,

        "height":
            final_h,

        "rotation_delta":
            rotation_delta,

        "astrometry_header_sha256":
            sha_bytes(raw),
    }


def canonical_dasch_fields(
    c,
    plate_id,
):
    if (
        "DASCH:"
        in c["exposure_a"]
    ):

        exposure = c[
            "exposure_a"
        ]

        start = c[
            "start_a_utc"
        ]

        end = c[
            "end_a_utc"
        ]

        duration = float(
            c[
                "duration_a_s"
            ]
        )

        ra = float(
            c[
                "ra_a_deg"
            ]
        )

        dec = float(
            c[
                "dec_a_deg"
            ]
        )

    else:

        exposure = c[
            "exposure_b"
        ]

        start = c[
            "start_b_utc"
        ]

        end = c[
            "end_b_utc"
        ]

        duration = float(
            c[
                "duration_b_s"
            ]
        )

        ra = float(
            c[
                "ra_b_deg"
            ]
        )

        dec = float(
            c[
                "dec_b_deg"
            ]
        )


    if not exposure.endswith(
        "/q/" + plate_id
    ):
        raise ValueError(
            "canonical DASCH identity mismatch"
        )


    start_dt = parse_utc(
        start
    )

    end_dt = parse_utc(
        end
    )

    midpoint = (
        start_dt
        + (
            end_dt
            - start_dt
        ) / 2
    )


    return {
        "midpoint":
            midpoint,

        "duration_s":
            duration,

        "ra_deg":
            ra,

        "dec_deg":
            dec,
    }


def select_solution(
    metadata,
    canonical_fields,
):
    astrometry = metadata.get(
        "astrometry"
    )

    if not isinstance(
        astrometry,
        dict,
    ):
        raise ValueError(
            "no astrometry"
        )


    encoded = astrometry.get(
        "b01HeaderGz"
    )

    if not encoded:
        raise ValueError(
            "no b01HeaderGz"
        )


    raw = gzip.decompress(
        base64.b64decode(
            encoded
        )
    )

    try:
        text = raw.decode(
            "ascii"
        )
    except UnicodeDecodeError:
        text = raw.decode(
            "latin-1"
        )


    base_hdr = fits.Header.fromstring(
        text,
        sep="\n",
    )

    nsol = count_solutions(
        base_hdr
    )


    exposures = astrometry.get(
        "exposures"
    )

    if not isinstance(
        exposures,
        list,
    ):
        raise ValueError(
            "exposure list absent"
        )


    candidates = []


    for solnum, exp in enumerate(
        exposures
    ):

        if exp is None:
            continue

        if not isinstance(
            exp,
            dict,
        ):
            continue


        midpoint_delta = math.inf

        duration_delta = math.inf


        if exp.get(
            "midpointDate"
        ):
            try:
                m = parse_utc(
                    exp[
                        "midpointDate"
                    ]
                )

                midpoint_delta = abs(
                    (
                        m
                        - canonical_fields[
                            "midpoint"
                        ]
                    ).total_seconds()
                )

            except Exception:
                pass


        duration_s = None

        if exp.get(
            "durMin"
        ) is not None:

            try:
                duration_s = (
                    float(
                        exp[
                            "durMin"
                        ]
                    )
                    * 60.0
                )

                duration_delta = abs(
                    duration_s
                    - canonical_fields[
                        "duration_s"
                    ]
                )

            except Exception:
                pass


        center_sep = None

        if (
            exp.get(
                "raDeg"
            ) is not None
            and exp.get(
                "decDeg"
            ) is not None
        ):
            try:
                c1 = SkyCoord(
                    float(
                        exp[
                            "raDeg"
                        ]
                    ) * u.deg,

                    float(
                        exp[
                            "decDeg"
                        ]
                    ) * u.deg,
                )

                c2 = SkyCoord(
                    canonical_fields[
                        "ra_deg"
                    ] * u.deg,

                    canonical_fields[
                        "dec_deg"
                    ] * u.deg,
                )

                center_sep = float(
                    c1.separation(
                        c2
                    ).arcsec
                )

            except Exception:
                pass


        candidates.append({
            "solnum":
                solnum,

            "has_wcs":
                bool(
                    solnum < nsol
                ),

            "midpoint_delta_s":
                midpoint_delta,

            "duration_delta_s":
                duration_delta,

            "duration_s":
                duration_s,

            "center_sep_arcsec":
                center_sep,

            "expnum":
                exp.get(
                    "number"
                ),
        })


    good = [
        c
        for c in candidates
        if (
            c[
                "has_wcs"
            ]
            and c[
                "midpoint_delta_s"
            ] <= 2.0
            and c[
                "duration_delta_s"
            ] <= 2.0
        )
    ]


    if len(good) != 1:

        nearest = sorted(
            candidates,
            key=lambda x: (
                x[
                    "midpoint_delta_s"
                ],
                x[
                    "duration_delta_s"
                ],
            ),
        )[:4]

        raise ValueError(
            "solution resolution count="
            f"{len(good)}; nearest="
            + json.dumps(
                nearest,
                sort_keys=True,
            )
        )


    return good[0]


# ======================================================================
# Execute geometry census.
# ======================================================================

results = []


for index, pair_row in enumerate(
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
    ),
    start=1,
):

    order = int(
        float(
            pair_row[
                "canonical_order"
            ]
        )
    )

    pid = pair_row[
        "poss_exposure_id"
    ]

    region = pair_row[
        "poss_region"
    ].strip().upper()

    plate = pair_row[
        "partner_dasch_plate_id"
    ].strip()

    c = canonical_by_order[
        order
    ]


    out = {
        "canonical_order":
            order,

        "legacy_rank":
            pair_row.get(
                "legacy_rank",
                "",
            ),

        "pair_key":
            pair_row[
                "pair_key"
            ],

        "poss_exposure_id":
            pid,

        "poss_region":
            region,

        "dasch_plate_id":
            plate,

        "overlap_start_utc":
            pair_row[
                "overlap_start_utc"
            ],

        "overlap_end_utc":
            pair_row[
                "overlap_end_utc"
            ],

        "actual_overlap_s":
            pair_row[
                "actual_overlap_s"
            ],

        "old_true_wcs_intersection":
            pair_row[
                "true_wcs_intersection"
            ],

        "old_true_wcs_overlap_fraction":
            pair_row[
                "true_wcs_overlap_fraction"
            ],

        "pair_execution_state":
            pair_row[
                "pair_execution_state"
            ],

        "geometry_state":
            "",

        "geometry_error":
            "",

        "poss_wcs_source":
            "",

        "poss_raw_plate_directory":
            "",

        "poss_grid_sha256":
            "",

        "dasch_metadata_sha256":
            "",

        "dasch_solution_number":
            "",

        "dasch_solution_input_tag":
            "",

        "dasch_number_of_wcs_solutions":
            "",

        "dasch_pv_coefficients":
            "",

        "dasch_rotation_delta":
            "",

        "dasch_final_width_bin16":
            "",

        "dasch_final_height_bin16":
            "",

        "dasch_midpoint_delta_s":
            "",

        "dasch_duration_delta_s":
            "",

        "sample_points_inside":
            "",

        "sample_points_total":
            "",

        "boundary_points_inside":
            "",

        "boundary_points_total":
            "",

        "all_sample_points_inside":
            "",

        "all_boundary_points_inside":
            "",

        "minimum_inside_edge_margin_bin16_px":
            "",

        "maximum_tpv_roundtrip_arcsec":
            "",
    }


    if pair_row[
        "pair_execution_state"
    ].startswith(
        "BLOCKED_POSS_ARCHIVE_UNAVAILABLE"
    ):

        out[
            "geometry_state"
        ] = (
            "BLOCKED_POSS_ARCHIVE_UNAVAILABLE_"
            "NOT_A_NONDETECTION"
        )

        results.append(
            out
        )

        continue


    try:
        poss_grid = get_poss_grid(
            pid,
            region,
        )

        out[
            "poss_wcs_source"
        ] = poss_grid[
            "source_kind"
        ]

        out[
            "poss_raw_plate_directory"
        ] = poss_grid[
            "raw_dir"
        ]

        out[
            "poss_grid_sha256"
        ] = poss_grid[
            "grid_sha256"
        ]


        metadata = get_dasch_metadata(
            plate
        )

        metadata_path = (
            DASCH_CACHE
            / (
                plate
                + "_mosaic_package_metadata.json"
            )
        )

        out[
            "dasch_metadata_sha256"
        ] = sha_file(
            metadata_path
        )


        cf = canonical_dasch_fields(
            c,
            plate,
        )

        selected = select_solution(
            metadata,
            cf,
        )

        solnum = int(
            selected[
                "solnum"
            ]
        )


        d = build_solution_wcs(
            metadata,
            solnum,
        )


        out[
            "dasch_solution_number"
        ] = solnum

        out[
            "dasch_solution_input_tag"
        ] = d[
            "input_tag"
        ]

        out[
            "dasch_number_of_wcs_solutions"
        ] = d[
            "nsol"
        ]

        out[
            "dasch_pv_coefficients"
        ] = d[
            "pv_count"
        ]

        out[
            "dasch_rotation_delta"
        ] = d[
            "rotation_delta"
        ]

        out[
            "dasch_final_width_bin16"
        ] = d[
            "width"
        ]

        out[
            "dasch_final_height_bin16"
        ] = d[
            "height"
        ]

        out[
            "dasch_midpoint_delta_s"
        ] = (
            selected[
                "midpoint_delta_s"
            ]
        )

        out[
            "dasch_duration_delta_s"
        ] = (
            selected[
                "duration_delta_s"
            ]
        )


        grid = poss_grid[
            "rows"
        ]

        coords = SkyCoord(
            [
                float(
                    row[
                        "ra_deg"
                    ]
                )
                for row in grid
            ] * u.deg,

            [
                float(
                    row[
                        "dec_deg"
                    ]
                )
                for row in grid
            ] * u.deg,

            frame="icrs",
        )


        dx, dy = d[
            "wcs"
        ].world_to_pixel(
            coords
        )


        inside = (
            np.isfinite(
                dx
            )
            & np.isfinite(
                dy
            )
            & (
                dx >= 0
            )
            & (
                dx
                <= d[
                    "width"
                ] - 1
            )
            & (
                dy >= 0
            )
            & (
                dy
                <= d[
                    "height"
                ] - 1
            )
        )


        n_total = len(
            grid
        )

        n_inside = int(
            inside.sum()
        )


        boundary_mask = np.array([
            (
                int(
                    row[
                        "ix"
                    ]
                )
                in (
                    0,
                    GRID_N - 1,
                )
                or int(
                    row[
                        "iy"
                    ]
                )
                in (
                    0,
                    GRID_N - 1,
                )
            )
            for row in grid
        ])


        boundary = inside[
            boundary_mask
        ]

        n_boundary = int(
            boundary_mask.sum()
        )

        n_boundary_inside = int(
            boundary.sum()
        )


        margin = np.minimum.reduce([
            dx,
            dy,
            (
                d[
                    "width"
                ] - 1
            ) - dx,
            (
                d[
                    "height"
                ] - 1
            ) - dy,
        ])


        inside_margin = margin[
            inside
        ]


        if len(
            inside_margin
        ):
            min_margin = float(
                np.min(
                    inside_margin
                )
            )
        else:
            min_margin = None


        roundtrip = d[
            "wcs"
        ].pixel_to_world(
            dx,
            dy
        )


        roundtrip_sep = (
            coords.separation(
                roundtrip
            ).arcsec
        )


        max_roundtrip = float(
            np.nanmax(
                roundtrip_sep
            )
        )


        all_inside = bool(
            inside.all()
        )

        all_boundary = bool(
            boundary.all()
        )


        out[
            "sample_points_inside"
        ] = n_inside

        out[
            "sample_points_total"
        ] = n_total

        out[
            "boundary_points_inside"
        ] = n_boundary_inside

        out[
            "boundary_points_total"
        ] = n_boundary

        out[
            "all_sample_points_inside"
        ] = all_inside

        out[
            "all_boundary_points_inside"
        ] = all_boundary

        out[
            "minimum_inside_edge_margin_bin16_px"
        ] = min_margin

        out[
            "maximum_tpv_roundtrip_arcsec"
        ] = max_roundtrip


        if (
            all_inside
            and all_boundary
        ):

            out[
                "geometry_state"
            ] = (
                "FULL_POSS_FOOTPRINT_"
                "DENSELY_SAMPLED_INSIDE_DASCH"
            )

        elif n_inside == 0:

            out[
                "geometry_state"
            ] = (
                "NO_SAMPLED_INTERSECTION_"
                "REQUIRES_REVIEW"
            )

        else:

            out[
                "geometry_state"
            ] = (
                "PARTIAL_COMMON_FOOTPRINT_"
                "REQUIRES_EXACT_BOUNDARY"
            )


    except Exception as exc:

        out[
            "geometry_state"
        ] = (
            "GEOMETRY_PREFLIGHT_FAILED"
        )

        out[
            "geometry_error"
        ] = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )


    results.append(
        out
    )


    # Durable checkpoint after each pair.
    write_csv(
        OUT_CSV,
        results,
    )


# ======================================================================
# Final census accounting.
# ======================================================================

write_csv(
    OUT_CSV,
    results,
)


states = Counter(
    row[
        "geometry_state"
    ]
    for row in results
)


old_full_disagreements = []

for row in results:

    old = str(
        row[
            "old_true_wcs_overlap_fraction"
        ]
    ).strip()

    try:
        old_float = float(
            old
        )
    except Exception:
        continue


    if (
        row[
            "geometry_state"
        ]
        == (
            "FULL_POSS_FOOTPRINT_"
            "DENSELY_SAMPLED_INSIDE_DASCH"
        )
        and abs(
            old_float - 1.0
        ) > 1e-9
    ):
        old_full_disagreements.append(
            int(
                row[
                    "canonical_order"
                ]
            )
        )


report = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "operation":
        "v028_poss47_distortion_geometry_census",

    "inputs": {
        "canonical_sha256":
            sha_file(
                CANONICAL
            ),

        "pair_map_sha256":
            sha_file(
                PAIR_MAP
            ),

        "native10_sha256":
            sha_file(
                NATIVE10
            ),

        "poss1_skyview_sha256":
            sha_file(
                SKY_SOURCE
            ),

        "skyview_jar_sha256":
            sha_file(
                JAR
            ),
    },

    "poss_pair_rows":
        len(
            results
        ),

    "geometry_state_counts":
        dict(
            states
        ),

    "dense_grid_n":
        GRID_N,

    "dense_grid_points_per_plate":
        GRID_N
        * GRID_N,

    "old_full_overlap_disagreements":
        old_full_disagreements,

    "output_csv":
        str(
            OUT_CSV
        ),

    "output_csv_sha256":
        sha_file(
            OUT_CSV
        ),

    "science_pixels_processed":
        False,

    "dasch_mosaic_pixels_downloaded":
        False,

    "detector_run":
        False,
}


OUT_JSON.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print("=" * 78)
print("POSS47 DISTORTION-AWARE GEOMETRY CENSUS COMPLETE")
print("=" * 78)

print(
    "Pair rows:",
    len(results),
    "/ 47",
)

print()

print(
    "Geometry states:"
)

for state, count in sorted(
    states.items()
):
    print(
        f"  {state}: {count}"
    )


partials = [
    r
    for r in results
    if (
        "PARTIAL_COMMON_FOOTPRINT"
        in r[
            "geometry_state"
        ]
    )
]


failed = [
    r
    for r in results
    if r[
        "geometry_state"
    ] in {
        "GEOMETRY_PREFLIGHT_FAILED",
        "NO_SAMPLED_INTERSECTION_REQUIRES_REVIEW",
    }
]


if partials:
    print()
    print(
        "Rows requiring exact boundary construction:"
    )

    for row in partials:
        print(
            " ",
            row[
                "canonical_order"
            ],
            row[
                "poss_exposure_id"
            ],
            "<->",
            row[
                "dasch_plate_id"
            ],
            "|",
            row[
                "sample_points_inside"
            ],
            "/",
            row[
                "sample_points_total"
            ],
        )


if failed:
    print()
    print(
        "Rows requiring review:"
    )

    for row in failed:
        print(
            " ",
            row[
                "canonical_order"
            ],
            row[
                "geometry_state"
            ],
            "|",
            row[
                "geometry_error"
            ][:140],
        )


print()

print(
    "Output:",
    OUT_CSV,
)

print(
    "Report:",
    OUT_JSON,
)

print()

print(
    "No DASCH mosaic pixels were downloaded."
)

print(
    "No historical science pixels were processed."
)

print(
    "No transient detector was run."
)
