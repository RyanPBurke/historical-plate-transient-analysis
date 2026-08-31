from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import ast
import base64
import csv
import gzip
import hashlib
import json
import math
import os
import subprocess
import time

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u


ROOT = Path.cwd()

CANONICAL = (
    ROOT
    / "research"
    / "canonical_sub5_pairs_74.csv"
)

SOURCE_MAP = (
    ROOT
    / "research"
    / "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.csv"
)

ENV_REPORT = (
    ROOT
    / "research"
    / "DETECTOR_ENVIRONMENT_V028_2026-08-21.json"
)

JAR = (
    ROOT
    / "tools"
    / "vendor"
    / "skyview.jar"
)

EXPECTED_CANONICAL_SHA = (
    "58529e1d4de46f3c49865a89454d1cd488ee23ec920b01250006f2180d2ed99a"
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

CANONICAL_ORDER = 61

POSS_ID = "POSS-I:875:E:rec521"
EXPECTED_REGION = "XE520"
EXPECTED_POSS_PLATE = "090N"

DASCH_PLATE = "ai44092"

BINNING = 16
GRID_N = 65

WORK = (
    ROOT
    / "work"
    / "pair61_direct_tpv_geometry_v028"
)

JAVA_SOURCE = (
    WORK
    / "DSSGridProbe.java"
)

JAVA_GRID = (
    WORK
    / "xe520_wcs_grid_65.csv"
)

METADATA_PATH = (
    WORK
    / "ai44092_mosaic_package_metadata.json"
)

TPV_HEADER_PATH = (
    WORK
    / "ai44092_selected_tpv_header.txt"
)

CANDIDATES_PATH = (
    WORK
    / "ai44092_exposure_solution_candidates.json"
)

REPORT = (
    ROOT
    / "research"
    / "SUB5_V028_PAIR61_DIRECT_TPV_GEOMETRY_CONTROL_2026-08-21.json"
)

REPORT_TXT = (
    ROOT
    / "research"
    / "SUB5_V028_PAIR61_DIRECT_TPV_GEOMETRY_CONTROL_2026-08-21.txt"
)


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


def canonical_json_bytes(obj) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(
            csv.DictReader(fh)
        )


def parse_utc(text: str) -> datetime:
    raw = str(
        text
    ).strip()

    if not raw:
        raise ValueError(
            "empty datetime"
        )

    # Standard ISO handling first.
    candidate = raw

    if candidate.endswith("Z"):
        candidate = (
            candidate[:-1]
            + "+00:00"
        )

    try:
        dt = datetime.fromisoformat(
            candidate
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except ValueError:
        pass

    # Some DASCH representations use a space separator.
    candidate = raw.replace(
        " ",
        "T",
        1,
    )

    if candidate.endswith("Z"):
        candidate = (
            candidate[:-1]
            + "+00:00"
        )

    dt = datetime.fromisoformat(
        candidate
    )

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        timezone.utc
    )


def angular_sep_arcsec(
    ra1,
    dec1,
    ra2,
    dec2,
):
    c1 = SkyCoord(
        float(ra1) * u.deg,
        float(dec1) * u.deg,
        frame="icrs",
    )

    c2 = SkyCoord(
        float(ra2) * u.deg,
        float(dec2) * u.deg,
        frame="icrs",
    )

    return float(
        c1.separation(c2).arcsec
    )


# ======================================================================
# 0. Guards.
# ======================================================================

for path in (
    CANONICAL,
    SOURCE_MAP,
    ENV_REPORT,
    JAR,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: missing required file: {path}"
        )


if sha_file(CANONICAL) != EXPECTED_CANONICAL_SHA:
    raise SystemExit(
        "REFUSING: canonical 74-row queue hash changed."
    )


if sha_file(JAR) != EXPECTED_JAR_SHA:
    raise SystemExit(
        "REFUSING: SkyView JAR hash changed."
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
        "REFUSING: detector environment report "
        "does not identify the frozen detector."
    )


if env.get(
    "detector_run"
) is not False:
    raise SystemExit(
        "REFUSING: detector environment provenance changed."
    )


WORK.mkdir(
    parents=True,
    exist_ok=True,
)


# ======================================================================
# 1. Exact canonical pair 61.
# ======================================================================

rows = read_csv(
    CANONICAL
)

matches = [
    row
    for row in rows
    if int(
        row["canonical_order"]
    ) == CANONICAL_ORDER
]


if len(matches) != 1:
    raise SystemExit(
        "REFUSING: canonical order 61 "
        f"resolved to {len(matches)} rows."
    )


pair = matches[0]


if POSS_ID not in (
    pair["exposure_a"],
    pair["exposure_b"],
):
    raise SystemExit(
        "REFUSING: pair 61 POSS identity changed."
    )


if (
    "DASCH:" in pair["exposure_a"]
):
    dasch_exp = pair[
        "exposure_a"
    ]

    d_start = pair[
        "start_a_utc"
    ]

    d_end = pair[
        "end_a_utc"
    ]

    d_duration = float(
        pair[
            "duration_a_s"
        ]
    )

    d_ra = float(
        pair[
            "ra_a_deg"
        ]
    )

    d_dec = float(
        pair[
            "dec_a_deg"
        ]
    )

else:
    dasch_exp = pair[
        "exposure_b"
    ]

    d_start = pair[
        "start_b_utc"
    ]

    d_end = pair[
        "end_b_utc"
    ]

    d_duration = float(
        pair[
            "duration_b_s"
        ]
    )

    d_ra = float(
        pair[
            "ra_b_deg"
        ]
    )

    d_dec = float(
        pair[
            "dec_b_deg"
        ]
    )


if not dasch_exp.endswith(
    "/q/" + DASCH_PLATE
):
    raise SystemExit(
        "REFUSING: pair 61 DASCH plate changed: "
        f"{dasch_exp}"
    )


start_dt = parse_utc(
    d_start
)

end_dt = parse_utc(
    d_end
)

canonical_mid = (
    start_dt
    + (
        end_dt - start_dt
    ) / 2
)


# ======================================================================
# 2. Exact POSS native WCS source.
# ======================================================================

source_rows = read_csv(
    SOURCE_MAP
)

pmatches = [
    row
    for row in source_rows
    if row[
        "exposure_id"
    ] == POSS_ID
]


if len(pmatches) != 1:
    raise SystemExit(
        "REFUSING: XE520 native source "
        f"resolved to {len(pmatches)} rows."
    )


poss = pmatches[0]


if (
    poss[
        "region"
    ].strip().upper()
    != EXPECTED_REGION
):
    raise SystemExit(
        "REFUSING: expected XE520."
    )


if (
    poss[
        "plate_id"
    ].strip().upper()
    != EXPECTED_POSS_PLATE
):
    raise SystemExit(
        "REFUSING: expected PLATEID 090N."
    )


raw_dir = poss[
    "raw_plate_directory"
].strip()


if not raw_dir:
    raise SystemExit(
        "REFUSING: XE520 native raw directory absent."
    )


# ======================================================================
# 3. Direct public DASCH mosaic_package request.
#
# No S3/base mosaic download occurs.
# ======================================================================

payload = {
    "plate_id":
        DASCH_PLATE,

    "binning":
        BINNING,
}


payload_bytes = json.dumps(
    payload,
    separators=(",", ":"),
).encode(
    "utf-8"
)


last_error = None
response_obj = None


for attempt in range(
    1,
    4,
):
    req = Request(
        API,
        data=payload_bytes,
        method="POST",
        headers={
            "Accept":
                "application/json",

            "Content-Type":
                "application/json",

            "User-Agent":
                "historical-transient-pipeline/"
                "0.2.8-direct-tpv-geometry",
        },
    )

    try:
        with urlopen(
            req,
            timeout=120,
        ) as response:

            raw_response = (
                response.read()
            )

        response_obj = json.loads(
            raw_response.decode(
                "utf-8"
            )
        )

        break

    except (
        URLError,
        HTTPError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:

        last_error = (
            f"{type(exc).__name__}: {exc}"
        )

        if attempt < 3:
            time.sleep(
                3 * attempt
            )


if response_obj is None:
    raise SystemExit(
        "DASCH mosaic_package failed after "
        f"3 attempts: {last_error}"
    )


if not isinstance(
    response_obj,
    dict,
):
    raise SystemExit(
        "REFUSING: mosaic_package response "
        "is not a JSON object."
    )


metadata = response_obj.get(
    "metadata"
)


if not isinstance(
    metadata,
    dict,
):
    raise SystemExit(
        "REFUSING: mosaic_package returned "
        "no metadata object."
    )


# Deliberately persist metadata only.
# Do not persist temporary presigned S3 URL.
METADATA_PATH.write_text(
    json.dumps(
        metadata,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


metadata_sha = sha_file(
    METADATA_PATH
)


# ======================================================================
# 4. Decode archived pipeline astrometry exactly as daschlab does.
# ======================================================================

astrometry = metadata.get(
    "astrometry"
)


if not isinstance(
    astrometry,
    dict,
):
    raise SystemExit(
        "REFUSING: DASCH metadata has no astrometry."
    )


b01_header_gz = astrometry.get(
    "b01HeaderGz"
)


if not b01_header_gz:
    raise SystemExit(
        "REFUSING: no archived b01 astrometric header."
    )


try:
    compressed = base64.b64decode(
        b01_header_gz
    )

    hdr_bytes = gzip.decompress(
        compressed
    )

except Exception as exc:
    raise SystemExit(
        "REFUSING: unable to decode "
        "DASCH astrometric header: "
        f"{type(exc).__name__}: {exc}"
    )


astrometry_header_sha = sha_bytes(
    hdr_bytes
)


try:
    hdr_text = hdr_bytes.decode(
        "ascii"
    )

except UnicodeDecodeError:
    hdr_text = hdr_bytes.decode(
        "latin-1"
    )


base_hdr = fits.Header.fromstring(
    hdr_text,
    sep="\n",
)


# daschlab solution counting semantics.
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
        raise SystemExit(
            "REFUSING: malformed multi-WCS "
            "DASCH astrometry header."
        )


exposures = astrometry.get(
    "exposures"
)


if not isinstance(
    exposures,
    list,
):
    raise SystemExit(
        "REFUSING: DASCH astrometry exposure "
        "list absent."
    )


# ======================================================================
# 5. Resolve the historically correct WCS solution from
#    midpoint + duration.
# ======================================================================

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

    midpoint_raw = exp.get(
        "midpointDate"
    )

    dur_min = exp.get(
        "durMin"
    )

    midpoint_delta_s = math.inf
    duration_delta_s = math.inf
    metadata_mid = None
    duration_s = None


    if midpoint_raw:
        try:
            metadata_mid = parse_utc(
                midpoint_raw
            )

            midpoint_delta_s = abs(
                (
                    metadata_mid
                    - canonical_mid
                ).total_seconds()
            )

        except Exception:
            pass


    if dur_min is not None:
        try:
            duration_s = (
                float(
                    dur_min
                )
                * 60.0
            )

            duration_delta_s = abs(
                duration_s
                - d_duration
            )

        except Exception:
            pass


    center_sep = None

    if (
        exp.get("raDeg")
        is not None
        and exp.get("decDeg")
        is not None
    ):
        try:
            center_sep = (
                angular_sep_arcsec(
                    exp["raDeg"],
                    exp["decDeg"],
                    d_ra,
                    d_dec,
                )
            )
        except Exception:
            center_sep = None


    candidates.append({
        "solnum":
            solnum,

        "has_wcs":
            bool(
                solnum < nsol
            ),

        "exposure_number":
            exp.get(
                "number"
            ),

        "midpoint_raw":
            midpoint_raw,

        "canonical_midpoint_utc":
            canonical_mid.isoformat(),

        "midpoint_delta_s":
            midpoint_delta_s,

        "duration_s":
            duration_s,

        "canonical_duration_s":
            d_duration,

        "duration_delta_s":
            duration_delta_s,

        "ra_deg":
            exp.get(
                "raDeg"
            ),

        "dec_deg":
            exp.get(
                "decDeg"
            ),

        "canonical_center_sep_arcsec":
            center_sep,

        "center_source":
            exp.get(
                "centerSource"
            ),

        "date_source":
            exp.get(
                "dateSource"
            ),

        "date_accuracy_days":
            exp.get(
                "dateAccDays"
            ),
    })


CANDIDATES_PATH.write_text(
    json.dumps(
        candidates,
        indent=2,
        sort_keys=True,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)


good = [
    item
    for item in candidates
    if (
        item[
            "has_wcs"
        ]
        and item[
            "midpoint_delta_s"
        ] <= 2.0
        and item[
            "duration_delta_s"
        ] <= 2.0
    )
]


if len(good) != 1:
    raise SystemExit(
        "REFUSING: historical DASCH exposure "
        "did not resolve to exactly one WCS solution; "
        f"got {len(good)}. "
        f"See {CANDIDATES_PATH}"
    )


selected = good[0]

solnum = int(
    selected[
        "solnum"
    ]
)


# Input tag semantics from daschlab:
# one solution -> untagged;
# multiple -> solution 0 = A, 1 = B, ...
if nsol == 1:
    input_tag = ""
else:
    input_tag = chr(
        ord("A")
        + solnum
    )


# ======================================================================
# 6. Reconstruct this one solution as a primary TPV WCS,
#    using the exact current daschlab transformation.
# ======================================================================

whdr = fits.Header()

whdr[
    "WCSAXES"
] = 2

whdr[
    "WCSNAME"
] = (
    f"DASCH astrometric solution "
    f"#{solnum + 1}"
)

whdr[
    "RADESYS"
] = "ICRS"

whdr[
    "CTYPE1"
] = "RA---TPV"

whdr[
    "CTYPE2"
] = "DEC--TPV"

whdr[
    "CUNIT1"
] = "deg"

whdr[
    "CUNIT2"
] = "deg"


def source_key(
    base: str,
):
    return (
        base
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
    skey = source_key(
        key
    )

    if skey not in base_hdr:
        raise SystemExit(
            f"REFUSING: required DASCH WCS "
            f"keyword missing: {skey}"
        )


whdr[
    "CRVAL1"
] = base_hdr[
    source_key(
        "CRVAL1"
    )
]

whdr[
    "CRVAL2"
] = base_hdr[
    source_key(
        "CRVAL2"
    )
]

whdr[
    "CRPIX1"
] = (
    (
        base_hdr[
            source_key(
                "CRPIX1"
            )
        ]
        - 0.5
    )
    / BINNING
    + 0.5
)

whdr[
    "CRPIX2"
] = (
    (
        base_hdr[
            source_key(
                "CRPIX2"
            )
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
    whdr[
        key
    ] = (
        base_hdr[
            source_key(
                key
            )
        ]
        * BINNING
    )


# Copy the exact PV distortion terms belonging
# to this input WCS solution.
pv_count = 0


for key, value in base_hdr.items():

    if not key.startswith(
        "PV"
    ):
        continue


    if input_tag == "":
        # Untagged PV keyword ends numerically,
        # e.g. PV1_0.
        belongs = (
            bool(key)
            and key[-1].isdigit()
        )

        output_key = key

    else:
        belongs = key.endswith(
            input_tag
        )

        output_key = (
            key[:-1]
            if belongs
            else key
        )


    if belongs:
        whdr[
            output_key
        ] = value

        pv_count += 1


if pv_count == 0:
    raise SystemExit(
        "REFUSING: selected DASCH WCS "
        "contains no PV distortion coefficients."
    )


TPV_HEADER_PATH.write_text(
    whdr.tostring(
        sep="\n",
        endcard=True,
        padding=False,
    ),
    encoding="ascii",
)


tpv_header_sha = sha_file(
    TPV_HEADER_PATH
)


dwcs = WCS(
    whdr
).celestial


if not dwcs.has_celestial:
    raise SystemExit(
        "REFUSING: reconstructed DASCH "
        "TPV WCS is not celestial."
    )


# ======================================================================
# 7. Compute final bin16 geometry exactly as daschlab does.
# ======================================================================

mosaic_md = metadata.get(
    "mosaic"
)


if not isinstance(
    mosaic_md,
    dict,
):
    raise SystemExit(
        "REFUSING: mosaic metadata absent."
    )


try:
    b01_width = int(
        mosaic_md[
            "b01Width"
        ]
    )

    b01_height = int(
        mosaic_md[
            "b01Height"
        ]
    )

except Exception as exc:
    raise SystemExit(
        "REFUSING: invalid full-resolution "
        f"mosaic dimensions: {exc}"
    )


base_w = (
    b01_width
    // BINNING
)

base_h = (
    b01_height
    // BINNING
)


rotation_delta = astrometry.get(
    "rotationDelta"
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
    raise SystemExit(
        "REFUSING: unexpected DASCH "
        f"rotationDelta={rotation_delta!r}"
    )


if abs(
    rot_k
) % 2:
    dasch_h = base_w
    dasch_w = base_h

else:
    dasch_h = base_h
    dasch_w = base_w


# Selected exposure centre itself must land
# inside the distortion-aware image.
if (
    selected[
        "ra_deg"
    ] is not None
    and selected[
        "dec_deg"
    ] is not None
):
    sc = SkyCoord(
        float(
            selected[
                "ra_deg"
            ]
        ) * u.deg,

        float(
            selected[
                "dec_deg"
            ]
        ) * u.deg,

        frame="icrs",
    )

    sx, sy = dwcs.world_to_pixel(
        sc
    )

    selected_center_pixel = [
        float(sx),
        float(sy),
    ]

    selected_center_inside = bool(
        np.isfinite(sx)
        and np.isfinite(sy)
        and sx >= 0
        and sx <= (
            dasch_w - 1
        )
        and sy >= 0
        and sy <= (
            dasch_h - 1
        )
    )

else:
    selected_center_pixel = None
    selected_center_inside = None


if (
    selected_center_inside
    is False
):
    raise SystemExit(
        "REFUSING: historically matched exposure "
        "centre falls outside reconstructed DASCH "
        "TPV image. Rotation/WCS convention requires "
        "further investigation."
    )


# ======================================================================
# 8. Generate a dense WCS-only lattice over XE520.
#
# No DSSImage.getData() call occurs.
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
            new double[] {
                x,
                y
            },
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
            ra += (
                2.0
                * Math.PI
            );
        }

        double dec =
            Math.asin(
                vz
            );

        return new double[] {
            Math.toDegrees(
                ra
            ),
            Math.toDegrees(
                dec
            )
        };
    }


    public static void main(
        String[] args
    ) throws Exception {

        if (
            args.length != 3
        ) {
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

        System.out.println(
            "grid_n="
            + gridN
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
        "REFUSING: DSSGridProbe compilation failed:\n"
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


run_cp = subprocess.run(
    [
        "java",
        "-cp",
        classpath,
        "DSSGridProbe",
        raw_dir,
        str(
            GRID_N
        ),
        str(
            JAVA_GRID
        ),
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    check=False,
    timeout=300,
)


if run_cp.returncode != 0:
    raise SystemExit(
        "REFUSING: XE520 WCS grid failed:\n"
        + (
            run_cp.stderr
            or run_cp.stdout
            or ""
        )
    )


grid = read_csv(
    JAVA_GRID
)


if len(grid) != (
    GRID_N
    * GRID_N
):
    raise SystemExit(
        "REFUSING: incomplete XE520 grid; "
        f"got {len(grid)} points."
    )


# ======================================================================
# 9. Transform every native POSS sample through selected
#    distortion-aware DASCH TPV WCS.
# ======================================================================

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


dx, dy = dwcs.world_to_pixel(
    coords
)


inside = (
    np.isfinite(dx)
    & np.isfinite(dy)
    & (
        dx >= 0
    )
    & (
        dx
        <= dasch_w - 1
    )
    & (
        dy >= 0
    )
    & (
        dy
        <= dasch_h - 1
    )
)


n_inside = int(
    np.sum(
        inside
    )
)

n_total = len(
    grid
)


margin = np.minimum.reduce([
    dx,
    dy,
    (
        dasch_w - 1
    ) - dx,
    (
        dasch_h - 1
    ) - dy,
])


inside_margin = margin[
    inside
]


min_inside_margin = (
    float(
        np.min(
            inside_margin
        )
    )
    if len(
        inside_margin
    )
    else None
)


boundary_mask = np.array([
    (
        int(
            row["ix"]
        )
        in (
            0,
            GRID_N - 1,
        )
        or int(
            row["iy"]
        )
        in (
            0,
            GRID_N - 1,
        )
    )
    for row in grid
])


boundary_inside = inside[
    boundary_mask
]


n_boundary = int(
    boundary_mask.sum()
)

n_boundary_inside = int(
    boundary_inside.sum()
)


all_boundary_inside = bool(
    boundary_inside.all()
)


all_grid_inside = bool(
    inside.all()
)


# TPV numerical roundtrip.
roundtrip = dwcs.pixel_to_world(
    dx,
    dy
)


roundtrip_sep = coords.separation(
    roundtrip
).arcsec


max_roundtrip_arcsec = float(
    np.nanmax(
        roundtrip_sep
    )
)


# ======================================================================
# 10. Publication-facing control report.
# ======================================================================

report = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "operation":
        "v028_pair61_direct_public_api_tpv_geometry_control",

    "canonical_queue_sha256":
        sha_file(
            CANONICAL
        ),

    "canonical_order":
        CANONICAL_ORDER,

    "pair_key":
        pair[
            "pair_key"
        ],

    "poss": {
        "exposure_id":
            POSS_ID,

        "region":
            poss[
                "region"
            ],

        "plate_id":
            poss[
                "plate_id"
            ],

        "raw_plate_directory":
            raw_dir,

        "grid_n":
            GRID_N,

        "grid_points":
            n_total,

        "grid_csv":
            str(
                JAVA_GRID
            ),

        "grid_csv_sha256":
            sha_file(
                JAVA_GRID
            ),
    },

    "dasch": {
        "plate_id":
            DASCH_PLATE,

        "api":
            API,

        "api_payload":
            payload,

        "base_fits_downloaded":
            False,

        "metadata_path":
            str(
                METADATA_PATH
            ),

        "metadata_sha256":
            metadata_sha,

        "astrometry_header_sha256":
            astrometry_header_sha,

        "binning":
            BINNING,

        "b01_width":
            b01_width,

        "b01_height":
            b01_height,

        "rotation_delta":
            rotation_delta,

        "rot_k_equivalent":
            rot_k,

        "bin16_final_width":
            dasch_w,

        "bin16_final_height":
            dasch_h,

        "number_of_wcs_solutions":
            nsol,

        "selected_solution_number":
            solnum,

        "selected_input_wcs_tag":
            input_tag,

        "selected_exposure":
            selected,

        "selected_center_pixel":
            selected_center_pixel,

        "selected_center_inside":
            selected_center_inside,

        "tpv_pv_coefficient_count":
            pv_count,

        "tpv_header_path":
            str(
                TPV_HEADER_PATH
            ),

        "tpv_header_sha256":
            tpv_header_sha,
    },

    "geometry": {
        "points_inside":
            n_inside,

        "points_total":
            n_total,

        "all_grid_inside":
            all_grid_inside,

        "boundary_points_inside":
            n_boundary_inside,

        "boundary_points_total":
            n_boundary,

        "all_boundary_inside":
            all_boundary_inside,

        "minimum_inside_edge_margin_bin16_px":
            min_inside_margin,

        "maximum_tpv_roundtrip_arcsec":
            max_roundtrip_arcsec,

        "old_true_wcs_overlap_fraction":
            pair.get(
                "true_wcs_overlap_fraction"
            ),

        "old_true_wcs_intersection":
            pair.get(
                "true_wcs_intersection"
            ),
    },

    "method": {
        "dasch_wcs_reconstruction":
            (
                "Direct implementation of current "
                "daschlab mosaics._do_astrometry "
                "semantics: archived b01HeaderGz; "
                "TPV projection; CRPIX/CD scaled "
                "for bin16; PV coefficients unchanged."
            ),

        "poss_wcs":
            (
                "SkyView native DSSImage WCS "
                "previously validated pixel-for-pixel "
                "against exact STScI XE520 extraction."
            ),

        "geometry_only":
            True,

        "historical_science_pixels_read":
            False,

        "detector_run":
            False,
    },

    "script_sha256":
        sha_file(
            Path(
                __file__
            )
        ),
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
        default=str,
    )
    + "\n",
    encoding="utf-8",
)


summary = [
    "PAIR 61 DIRECT TPV GEOMETRY CONTROL",
    "=" * 76,

    f"POSS:  {POSS_ID} / {EXPECTED_REGION} / {EXPECTED_POSS_PLATE}",
    f"DASCH: {DASCH_PLATE}",

    "",
    f"DASCH WCS solutions: {nsol}",

    f"Selected solution: {solnum} "
    f"(input tag {input_tag!r})",

    f"Exposure midpoint delta: "
    f"{selected['midpoint_delta_s']:.9f} s",

    f"Exposure duration delta: "
    f"{selected['duration_delta_s']:.9f} s",

    f"Canonical-centre separation: "
    f"{selected['canonical_center_sep_arcsec']}",

    "",
    f"DASCH rotationDelta: {rotation_delta}",

    f"Final bin16 dimensions: "
    f"{dasch_w} x {dasch_h}",

    f"TPV coefficients copied: {pv_count}",

    f"Selected exposure centre in image: "
    f"{selected_center_inside}",

    "",
    f"XE520 grid inside DASCH: "
    f"{n_inside}/{n_total}",

    f"Boundary inside DASCH: "
    f"{n_boundary_inside}/{n_boundary}",

    f"All grid samples inside: "
    f"{all_grid_inside}",

    f"All boundary samples inside: "
    f"{all_boundary_inside}",

    f"Minimum inside DASCH edge margin: "
    f"{min_inside_margin} bin16 pixels",

    f"Maximum TPV roundtrip error: "
    f"{max_roundtrip_arcsec:.9f} arcsec",

    "",
    "DASCH base mosaic pixels downloaded: False",
    "Historical science pixels read: False",
    "Transient detector run: False",
]


REPORT_TXT.write_text(
    "\n".join(
        summary
    )
    + "\n",
    encoding="utf-8",
)


print("=" * 76)
print("PAIR 61 DIRECT TPV GEOMETRY CONTROL COMPLETE")
print("=" * 76)

print(
    "DASCH WCS solutions:",
    nsol,
)

print(
    "Selected solution:",
    solnum,
    "input tag:",
    repr(
        input_tag
    ),
)

print(
    "Midpoint delta:",
    f"{selected['midpoint_delta_s']:.9f}",
    "s",
)

print(
    "Duration delta:",
    f"{selected['duration_delta_s']:.9f}",
    "s",
)

print(
    "TPV coefficients:",
    pv_count,
)

print(
    "Selected centre inside:",
    selected_center_inside,
)

print()

print(
    "XE520 samples inside DASCH:",
    f"{n_inside}/{n_total}",
)

print(
    "Boundary samples inside:",
    f"{n_boundary_inside}/{n_boundary}",
)

print(
    "All grid inside:",
    all_grid_inside,
)

print(
    "All boundary inside:",
    all_boundary_inside,
)

print(
    "Minimum DASCH edge margin:",
    min_inside_margin,
    "bin16 px",
)

print(
    "Maximum TPV roundtrip:",
    f"{max_roundtrip_arcsec:.9f}",
    "arcsec",
)

print()

print(
    "Metadata:",
    METADATA_PATH,
)

print(
    "TPV header:",
    TPV_HEADER_PATH,
)

print(
    "Report:",
    REPORT,
)

print(
    "Summary:",
    REPORT_TXT,
)

print()

print(
    "No DASCH mosaic pixels were downloaded."
)

print(
    "No historical science pixels were read."
)

print(
    "No transient detector was run."
)
