from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
import subprocess
import sys

import numpy as np
from astropy.io import fits


ROOT = Path.cwd()

SOURCE_MAP = (
    ROOT / "research" /
    "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.csv"
)

PREFLIGHT = (
    ROOT / "research" /
    "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_V2_2026-08-21.csv"
)

ENV_REPORT = (
    ROOT / "research" /
    "DETECTOR_ENVIRONMENT_V028_2026-08-21.json"
)

JAR = (
    ROOT / "tools" / "vendor" / "skyview.jar"
)

EXPECTED_JAR_SHA = (
    "2b949f68d73899cd63b2f600f60f6c5dfd1795532ed29b6ea986f71f83d36afe"
)

CONTROL_ID = "POSS-I:875:E:rec521"
EXPECTED_REGION = "XE520"
EXPECTED_PLATE_ID = "090N"

WORK = (
    ROOT / "work" /
    "native_dss_xe520_control_v028"
)

JAVA_FILE = WORK / "NativeDssProbe.java"
BIN_FILE = WORK / "native_patch_be_f64.bin"
JAVA_STDOUT = WORK / "java_stdout.txt"
JAVA_STDERR = WORK / "java_stderr.txt"

REPORT_JSON = (
    ROOT / "research" /
    "POSS1_V028_XE520_NATIVE_PIXEL_CONTROL_2026-08-21.json"
)

REPORT_TXT = (
    ROOT / "research" /
    "POSS1_V028_XE520_NATIVE_PIXEL_CONTROL_2026-08-21.txt"
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


for path in (
    SOURCE_MAP,
    PREFLIGHT,
    ENV_REPORT,
    JAR,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )


if sha256_file(JAR) != EXPECTED_JAR_SHA:
    raise SystemExit(
        "REFUSING: SkyView JAR hash changed."
    )


env = json.loads(
    ENV_REPORT.read_text(
        encoding="utf-8"
    )
)

if env.get("detector_run") is not False:
    raise SystemExit(
        "REFUSING: detector environment report "
        "does not state detector_run=false."
    )


source_rows = read_csv(SOURCE_MAP)
preflight_rows = read_csv(PREFLIGHT)

sources = {
    r["exposure_id"]: r
    for r in source_rows
}

preflight = {
    r["exposure_id"]: r
    for r in preflight_rows
}


if CONTROL_ID not in sources:
    raise SystemExit(
        "REFUSING: XE520 absent from native source map."
    )

if CONTROL_ID not in preflight:
    raise SystemExit(
        "REFUSING: XE520 absent from exact-plate preflight."
    )


src = sources[CONTROL_ID]
pf = preflight[CONTROL_ID]


if src["region"].strip().upper() != EXPECTED_REGION:
    raise SystemExit(
        "REFUSING: XE520 source-map REGION changed."
    )

if src["plate_id"].strip().upper() != EXPECTED_PLATE_ID:
    raise SystemExit(
        "REFUSING: XE520 source-map PLATEID changed."
    )

if pf["extraction_state"] != "EXACT_PLATE_CUTOUT_READY":
    raise SystemExit(
        "REFUSING: XE520 STScI control FITS "
        "is not marked READY."
    )

if pf["returned_region"].strip().upper() != EXPECTED_REGION:
    raise SystemExit(
        "REFUSING: XE520 STScI REGION mismatch."
    )

if pf["returned_plateid"].strip().upper() != EXPECTED_PLATE_ID:
    raise SystemExit(
        "REFUSING: XE520 STScI PLATEID mismatch."
    )


fits_path = Path(
    pf["fits_path"]
)

if not fits_path.is_file():
    raise SystemExit(
        f"REFUSING: XE520 control FITS missing: {fits_path}"
    )

if sha256_file(fits_path) != pf["fits_sha256"]:
    raise SystemExit(
        "REFUSING: XE520 control FITS SHA256 changed."
    )


raw_dir = src[
    "raw_plate_directory"
].strip()

ra_deg = float(
    pf["requested_ra_deg"]
)

dec_deg = float(
    pf["requested_dec_deg"]
)


# Slightly larger than the 177x177 STScI control,
# allowing deterministic alignment/orientation search.
PATCH_SIZE = 221


WORK.mkdir(
    parents=True,
    exist_ok=True,
)


java_source = r'''
import java.io.*;
import skyview.survey.DSSImage;
import skyview.geometry.WCS;
import skyview.geometry.Transformer;

public class NativeDssProbe {

    static double[] sphere(double raDeg, double decDeg) {
        double ra = Math.toRadians(raDeg);
        double dec = Math.toRadians(decDeg);
        double c = Math.cos(dec);

        return new double[] {
            c * Math.cos(ra),
            c * Math.sin(ra),
            Math.sin(dec)
        };
    }

    static double[] skyToPixel(
        WCS wcs,
        double raDeg,
        double decDeg
    ) throws Exception {

        double[] out = new double[2];

        wcs.transform(
            sphere(raDeg, decDeg),
            out
        );

        return out;
    }

    static double[] pixelToSky(
        WCS wcs,
        double x,
        double y
    ) throws Exception {

        double[] vec = new double[3];

        Transformer inv = wcs.inverse();

        inv.transform(
            new double[] {x, y},
            vec
        );

        double r = Math.sqrt(
            vec[0]*vec[0] +
            vec[1]*vec[1] +
            vec[2]*vec[2]
        );

        double vx = vec[0] / r;
        double vy = vec[1] / r;
        double vz = vec[2] / r;

        double ra = Math.atan2(vy, vx);

        if (ra < 0) {
            ra += 2.0 * Math.PI;
        }

        double dec = Math.asin(vz);

        return new double[] {
            Math.toDegrees(ra),
            Math.toDegrees(dec)
        };
    }

    public static void main(String[] args)
        throws Exception {

        if (args.length != 5) {
            throw new IllegalArgumentException(
                "usage: NativeDssProbe " +
                "<raw_dir> <ra_deg> <dec_deg> " +
                "<size> <output_bin>"
            );
        }

        String directory = args[0];
        double raDeg = Double.parseDouble(args[1]);
        double decDeg = Double.parseDouble(args[2]);
        int size = Integer.parseInt(args[3]);
        String output = args[4];

        DSSImage image = new DSSImage(directory);

        int fullWidth = image.getWidth();
        int fullHeight = image.getHeight();

        WCS wcs = image.getWCS();

        double[] center = skyToPixel(
            wcs,
            raDeg,
            decDeg
        );

        int cx = (int)Math.round(center[0]);
        int cy = (int)Math.round(center[1]);

        int half = size / 2;

        int x0 = cx - half;
        int y0 = cy - half;

        if (
            x0 < 0 ||
            y0 < 0 ||
            x0 + size > fullWidth ||
            y0 + size > fullHeight
        ) {
            throw new IllegalStateException(
                "requested native patch extends " +
                "outside plate bounds"
            );
        }

        double[] roundtrip = pixelToSky(
            wcs,
            center[0],
            center[1]
        );

        try (
            DataOutputStream out =
                new DataOutputStream(
                    new BufferedOutputStream(
                        new FileOutputStream(output)
                    )
                )
        ) {
            for (int y = y0; y < y0 + size; y++) {
                for (int x = x0; x < x0 + size; x++) {

                    long linear =
                        ((long)y * (long)fullWidth)
                        + (long)x;

                    if (linear > Integer.MAX_VALUE) {
                        throw new IllegalStateException(
                            "linear pixel index exceeds int"
                        );
                    }

                    double value = image.getData(
                        (int)linear
                    );

                    out.writeDouble(value);
                }
            }
        }

        System.out.println(
            "full_width=" + fullWidth
        );

        System.out.println(
            "full_height=" + fullHeight
        );

        System.out.println(
            "is_tiled=" + image.isTiled()
        );

        System.out.println(
            "center_pixel_x=" + center[0]
        );

        System.out.println(
            "center_pixel_y=" + center[1]
        );

        System.out.println(
            "patch_x0=" + x0
        );

        System.out.println(
            "patch_y0=" + y0
        );

        System.out.println(
            "patch_size=" + size
        );

        System.out.println(
            "roundtrip_ra_deg=" + roundtrip[0]
        );

        System.out.println(
            "roundtrip_dec_deg=" + roundtrip[1]
        );
    }
}
'''


JAVA_FILE.write_text(
    java_source,
    encoding="utf-8",
)


# ------------------------------------------------------------------
# Compile against the exact downloaded SkyView JAR.
# ------------------------------------------------------------------

javac = subprocess.run(
    [
        "javac",
        "-version",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    check=False,
)


if javac.returncode != 0:
    raise SystemExit(
        "REFUSING: javac is unavailable.\n"
        + (javac.stdout or "")
    )


compile_cp = subprocess.run(
    [
        "javac",
        "-cp",
        str(JAR),
        "-d",
        str(WORK),
        str(JAVA_FILE),
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    check=False,
)


if compile_cp.returncode != 0:
    (WORK / "javac_stdout.txt").write_text(
        compile_cp.stdout or "",
        encoding="utf-8",
    )

    (WORK / "javac_stderr.txt").write_text(
        compile_cp.stderr or "",
        encoding="utf-8",
    )

    raise SystemExit(
        "REFUSING: NativeDssProbe Java compilation failed. "
        "See work/native_dss_xe520_control_v028/"
        "javac_stderr.txt"
    )


# ------------------------------------------------------------------
# Read a single historical CONTROL patch.
#
# No detector call occurs anywhere in this script.
# ------------------------------------------------------------------

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
        "NativeDssProbe",
        raw_dir,
        repr(ra_deg),
        repr(dec_deg),
        str(PATCH_SIZE),
        str(BIN_FILE),
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    check=False,
    timeout=300,
)


JAVA_STDOUT.write_text(
    run_cp.stdout or "",
    encoding="utf-8",
)

JAVA_STDERR.write_text(
    run_cp.stderr or "",
    encoding="utf-8",
)


if run_cp.returncode != 0:
    raise SystemExit(
        "Native DSS control extraction failed. "
        "See:\n"
        f"  {JAVA_STDOUT}\n"
        f"  {JAVA_STDERR}\n"
        "STOP before detector execution."
    )


metadata = {}

for line in (
    run_cp.stdout or ""
).splitlines():

    if "=" not in line:
        continue

    key, value = line.split(
        "=",
        1,
    )

    metadata[
        key.strip()
    ] = value.strip()


required_meta = {
    "full_width",
    "full_height",
    "is_tiled",
    "center_pixel_x",
    "center_pixel_y",
    "patch_x0",
    "patch_y0",
    "patch_size",
    "roundtrip_ra_deg",
    "roundtrip_dec_deg",
}


if not required_meta <= set(metadata):
    raise SystemExit(
        "REFUSING: Java control metadata incomplete."
    )


count = (
    PATCH_SIZE
    * PATCH_SIZE
)

expected_bytes = (
    count * 8
)


if BIN_FILE.stat().st_size != expected_bytes:
    raise SystemExit(
        "REFUSING: native patch binary size mismatch."
    )


native = np.fromfile(
    BIN_FILE,
    dtype=">f8",
).reshape(
    PATCH_SIZE,
    PATCH_SIZE,
)


with fits.open(
    fits_path,
    memmap=False,
) as hdul:

    fits_data = np.asarray(
        hdul[0].data,
        dtype=np.float64,
    )

    fits_header = hdul[0].header


if fits_data.ndim != 2:
    raise SystemExit(
        "REFUSING: STScI control FITS is not 2-D."
    )


# ------------------------------------------------------------------
# Compare all eight square-image orientations.
#
# First choose candidate alignment using a sparse sample, then
# evaluate the best candidates with every pixel.
# ------------------------------------------------------------------

variants = []

for k in range(4):
    r = np.rot90(
        fits_data,
        k,
    )

    variants.append(
        (
            f"rot{k * 90}",
            r,
        )
    )

    variants.append(
        (
            f"rot{k * 90}_flipud",
            np.flipud(r),
        )
    )


fh, fw = fits_data.shape

if (
    fh > PATCH_SIZE
    or fw > PATCH_SIZE
):
    raise SystemExit(
        "REFUSING: control FITS larger than native patch."
    )


sample_step = 8

sample_y = np.arange(
    0,
    fh,
    sample_step,
)

sample_x = np.arange(
    0,
    fw,
    sample_step,
)


candidates = []


for orientation, arr in variants:

    ah, aw = arr.shape

    for oy in range(
        0,
        PATCH_SIZE - ah + 1,
    ):
        for ox in range(
            0,
            PATCH_SIZE - aw + 1,
        ):

            a = native[
                oy + sample_y[:, None],
                ox + sample_x[None, :],
            ].ravel()

            b = arr[
                sample_y[:, None],
                sample_x[None, :],
            ].ravel()

            finite = (
                np.isfinite(a)
                & np.isfinite(b)
            )

            if finite.sum() < 20:
                continue

            av = a[finite]
            bv = b[finite]

            # Allow a linear intensity relation when choosing
            # candidates, but do not call that pixel-equivalence.
            A = np.column_stack(
                (
                    bv,
                    np.ones_like(bv),
                )
            )

            slope, intercept = np.linalg.lstsq(
                A,
                av,
                rcond=None,
            )[0]

            predicted = (
                slope * bv
                + intercept
            )

            rmse = float(
                np.sqrt(
                    np.mean(
                        (
                            av
                            - predicted
                        ) ** 2
                    )
                )
            )

            candidates.append(
                (
                    rmse,
                    orientation,
                    ox,
                    oy,
                    float(slope),
                    float(intercept),
                )
            )


if not candidates:
    raise SystemExit(
        "REFUSING: no viable control alignment."
    )


candidates.sort(
    key=lambda x: x[0]
)


full_results = []


for sparse in candidates[:20]:

    (
        sparse_rmse,
        orientation,
        ox,
        oy,
        _,
        _,
    ) = sparse

    arr = dict(
        variants
    )[orientation]

    ah, aw = arr.shape

    a = native[
        oy:oy + ah,
        ox:ox + aw,
    ].ravel()

    b = arr.ravel()

    finite = (
        np.isfinite(a)
        & np.isfinite(b)
    )

    av = a[finite]
    bv = b[finite]

    A = np.column_stack(
        (
            bv,
            np.ones_like(bv),
        )
    )

    slope, intercept = np.linalg.lstsq(
        A,
        av,
        rcond=None,
    )[0]

    prediction = (
        slope * bv
        + intercept
    )

    residual = (
        av
        - prediction
    )

    rmse = float(
        np.sqrt(
            np.mean(
                residual ** 2
            )
        )
    )

    max_abs = float(
        np.max(
            np.abs(
                residual
            )
        )
    )

    corr = float(
        np.corrcoef(
            av,
            bv,
        )[0, 1]
    )

    exact_fraction = float(
        np.mean(
            av == bv
        )
    )

    rounded_exact_fraction = float(
        np.mean(
            np.rint(av)
            == np.rint(bv)
        )
    )

    full_results.append({
        "orientation":
            orientation,

        "offset_x_in_native_patch":
            ox,

        "offset_y_in_native_patch":
            oy,

        "finite_pixels":
            int(finite.sum()),

        "linear_slope_native_from_fits":
            float(slope),

        "linear_intercept_native_from_fits":
            float(intercept),

        "linear_rmse":
            rmse,

        "linear_max_abs_residual":
            max_abs,

        "pearson_r":
            corr,

        "exact_value_fraction":
            exact_fraction,

        "rounded_value_fraction":
            rounded_exact_fraction,

        "sparse_selection_rmse":
            sparse_rmse,
    })


full_results.sort(
    key=lambda r: (
        -r[
            "rounded_value_fraction"
        ],
        -r[
            "pearson_r"
        ],
        r[
            "linear_rmse"
        ],
    )
)


best = full_results[0]


# SkyView WCS roundtrip diagnostic.
rt_ra = float(
    metadata[
        "roundtrip_ra_deg"
    ]
)

rt_dec = float(
    metadata[
        "roundtrip_dec_deg"
    ]
)


def angular_sep_arcsec(
    ra1,
    dec1,
    ra2,
    dec2,
):
    r1 = math.radians(ra1)
    d1 = math.radians(dec1)
    r2 = math.radians(ra2)
    d2 = math.radians(dec2)

    cossep = (
        math.sin(d1) * math.sin(d2)
        + math.cos(d1)
        * math.cos(d2)
        * math.cos(r1 - r2)
    )

    cossep = max(
        -1.0,
        min(
            1.0,
            cossep,
        ),
    )

    return (
        math.degrees(
            math.acos(
                cossep
            )
        )
        * 3600.0
    )


roundtrip_sep = angular_sep_arcsec(
    ra_deg,
    dec_deg,
    rt_ra,
    rt_dec,
)


report = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "operation":
        "v028_xe520_native_dss_pixel_equivalence_control",

    "control_exposure_id":
        CONTROL_ID,

    "region":
        EXPECTED_REGION,

    "plate_id":
        EXPECTED_PLATE_ID,

    "native_raw_directory":
        raw_dir,

    "skyview_jar_sha256":
        sha256_file(
            JAR
        ),

    "native_patch_binary":
        str(
            BIN_FILE
        ),

    "native_patch_sha256":
        sha256_file(
            BIN_FILE
        ),

    "native_patch_shape":
        list(
            native.shape
        ),

    "native_patch_min":
        float(
            np.nanmin(
                native
            )
        ),

    "native_patch_max":
        float(
            np.nanmax(
                native
            )
        ),

    "stsci_control_fits":
        str(
            fits_path
        ),

    "stsci_control_fits_sha256":
        sha256_file(
            fits_path
        ),

    "stsci_control_shape":
        list(
            fits_data.shape
        ),

    "stsci_bitpix":
        fits_header.get(
            "BITPIX"
        ),

    "stsci_bscale":
        fits_header.get(
            "BSCALE"
        ),

    "stsci_bzero":
        fits_header.get(
            "BZERO"
        ),

    "java_metadata":
        metadata,

    "wcs_roundtrip_sep_arcsec":
        roundtrip_sep,

    "best_alignment":
        best,

    "top_alignments":
        full_results[:8],

    "detector_run":
        False,

    "science_candidate_search":
        False,

    "interpretation_policy": {
        "pixel_equivalent":
            (
                "rounded_value_fraction == 1.0 "
                "and slope ~= 1 and intercept ~= 0"
            ),

        "correlated_but_not_pixel_equivalent":
            (
                "high Pearson correlation but "
                "pixel-equivalence conditions fail"
            ),
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


summary = [
    "XE520 NATIVE DSS PIXEL CONTROL",
    "=" * 72,

    f"Exposure: {CONTROL_ID}",
    f"REGION:   {EXPECTED_REGION}",
    f"PLATEID:  {EXPECTED_PLATE_ID}",

    "",
    f"Full native plate: "
    f"{metadata['full_width']} x "
    f"{metadata['full_height']}",

    f"SkyView reports tiled: "
    f"{metadata['is_tiled']}",

    f"Native control patch: "
    f"{native.shape[1]} x "
    f"{native.shape[0]}",

    f"STScI control FITS: "
    f"{fits_data.shape[1]} x "
    f"{fits_data.shape[0]}",

    "",
    f"WCS round-trip separation: "
    f"{roundtrip_sep:.9f} arcsec",

    "",
    "BEST PIXEL ALIGNMENT",

    f"  orientation: "
    f"{best['orientation']}",

    f"  offset: "
    f"x={best['offset_x_in_native_patch']}, "
    f"y={best['offset_y_in_native_patch']}",

    f"  Pearson r: "
    f"{best['pearson_r']:.12f}",

    f"  exact-value fraction: "
    f"{best['exact_value_fraction']:.12f}",

    f"  rounded-value fraction: "
    f"{best['rounded_value_fraction']:.12f}",

    f"  slope: "
    f"{best['linear_slope_native_from_fits']:.12f}",

    f"  intercept: "
    f"{best['linear_intercept_native_from_fits']:.12f}",

    f"  RMSE: "
    f"{best['linear_rmse']:.12f}",

    "",
    "No frozen detector was run.",
    "No transient candidate search was performed.",
]


REPORT_TXT.write_text(
    "\n".join(
        summary
    ) + "\n",
    encoding="utf-8",
)


print("=" * 72)
print("XE520 NATIVE DSS CONTROL COMPLETE")
print("=" * 72)

print(
    "Full native plate:",
    metadata["full_width"],
    "x",
    metadata["full_height"],
)

print(
    "Tiled:",
    metadata["is_tiled"],
)

print(
    "WCS roundtrip:",
    f"{roundtrip_sep:.9f}",
    "arcsec",
)

print()

print(
    "Best orientation:",
    best["orientation"],
)

print(
    "Best offset:",
    best["offset_x_in_native_patch"],
    best["offset_y_in_native_patch"],
)

print(
    "Pearson r:",
    f"{best['pearson_r']:.12f}",
)

print(
    "Exact fraction:",
    f"{best['exact_value_fraction']:.12f}",
)

print(
    "Rounded fraction:",
    f"{best['rounded_value_fraction']:.12f}",
)

print(
    "Linear slope:",
    f"{best['linear_slope_native_from_fits']:.12f}",
)

print(
    "Linear intercept:",
    f"{best['linear_intercept_native_from_fits']:.12f}",
)

print(
    "Linear RMSE:",
    f"{best['linear_rmse']:.12f}",
)

print()

print(
    "Report:",
    REPORT_JSON,
)

print(
    "Summary:",
    REPORT_TXT,
)

print()

print(
    "No transient detector was run."
)

print(
    "No candidate search was performed."
)
