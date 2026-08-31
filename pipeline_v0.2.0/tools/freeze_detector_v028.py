from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import ast
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter


ROOT = Path.cwd()

DETECTOR = ROOT / "src" / "transient_pipeline" / "detector.py"
CONFIG_PY = ROOT / "src" / "transient_pipeline" / "config.py"
METHOD_JSON = ROOT / "config" / "frozen_method.json"

PROTOCOL = (
    ROOT
    / "protocol"
    / "PROTOCOL_v1.0_PRE_REMAINING_SUB5_2026-08-20.md"
)

IDENTITY_FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
)

IDENTITY_MANIFEST = (
    IDENTITY_FREEZE
    / "freeze_manifest.json"
)

PIXEL_REPORT = (
    ROOT
    / "research"
    / "POSS1_V028_PIXEL_PROVENANCE_RECONCILIATION_2026-08-21.json"
)

TEST_FILE = (
    ROOT
    / "tests"
    / "test_detector_array.py"
)

OUT = (
    ROOT
    / "research_snapshots"
    / "detector_freeze_v0.2.8_2026-08-21"
)

CLOSURE = (
    ROOT
    / "research"
    / "DETECTOR_FREEZE_V028_CLOSURE_2026-08-21.md"
)

EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
)

EXPECTED_METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
)

EXPECTED_PROTOCOL_SHA = (
    "9479666b93df3f7dc85b3f61861c93ea70fe50be47c1070e6ce7ec444c66a700"
)

EXPECTED_IDENTITY_MANIFEST_SHA = (
    "56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e"
)

EXPECTED_IDENTITY_SNAPSHOT_ID = (
    "8dc070b9df3febaa5db3585408e1fe88e9b3b9d71d436ddba16a71081b066d0e"
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


def require(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )


def copy_into(
    src: Path,
    relative: str,
) -> dict:
    dst = OUT / relative

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(src, dst)

    return {
        "snapshot_path":
            relative.replace("\\", "/"),
        "source":
            str(src.relative_to(ROOT)).replace("\\", "/"),
        "sha256":
            sha256_file(dst),
        "bytes":
            dst.stat().st_size,
    }


for path in (
    DETECTOR,
    CONFIG_PY,
    METHOD_JSON,
    PROTOCOL,
    IDENTITY_MANIFEST,
    PIXEL_REPORT,
    TEST_FILE,
):
    require(path)


print("=" * 100)
print("v0.2.8 FROZEN 4-SIGMA DETECTOR CONFORMANCE + FREEZE")
print("=" * 100)
print(
    "Detector execution in this program is restricted "
    "to deterministic synthetic fixtures."
)


# ======================================================================
# 1. Provenance guards
# ======================================================================

guards = {
    "detector.py":
        (
            sha256_file(DETECTOR),
            EXPECTED_DETECTOR_SHA,
        ),

    "frozen_method.json":
        (
            sha256_file(METHOD_JSON),
            EXPECTED_METHOD_SHA,
        ),

    "protocol":
        (
            sha256_file(PROTOCOL),
            EXPECTED_PROTOCOL_SHA,
        ),

    "identity_manifest":
        (
            sha256_file(IDENTITY_MANIFEST),
            EXPECTED_IDENTITY_MANIFEST_SHA,
        ),
}


print()
print("HASH GUARDS")
print("-" * 100)

for label, (actual, expected) in guards.items():
    print(label)
    print(" expected:", expected)
    print(" actual:  ", actual)

    if actual != expected:
        raise SystemExit(
            f"REFUSING: hash guard failed for {label}"
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


pixel_report = json.loads(
    PIXEL_REPORT.read_text(
        encoding="utf-8",
    )
)

if pixel_report.get("detector_run") is not False:
    raise SystemExit(
        "REFUSING: pixel reconciliation does not state detector_run=False."
    )


# ======================================================================
# 2. Freeze exact method values.
# ======================================================================

method_values = json.loads(
    METHOD_JSON.read_text(
        encoding="utf-8",
    )
)

required_method = {
    "background_sigma_px": 8.0,
    "peak_sigma": 4.0,
    "max_window_px": 7,
    "edge_px": 30,
    "diagnostic_match_arcsec": 10.0,
    "strict_registered_match_arcsec": 3.0,
    "hamburg_recurrence_arcsec": 3.2,
    "gps1_static_veto_arcsec": 10.0,
    "gps1_query_radius_arcsec": 120.0,
    "gps1_epoch": 1952.6198,
}

if method_values != required_method:
    raise SystemExit(
        "REFUSING: frozen method values changed:\n"
        + json.dumps(
            method_values,
            indent=2,
            sort_keys=True,
        )
    )


# ======================================================================
# 3. AST semantic guards.
#
# These make several subtle detector choices explicit rather than relying
# on prose alone.
# ======================================================================

source = DETECTOR.read_text(
    encoding="utf-8",
)

tree = ast.parse(source)

detect_node = None

for node in tree.body:
    if (
        isinstance(node, ast.FunctionDef)
        and node.name == "detect_array"
    ):
        detect_node = node
        break

if detect_node is None:
    raise SystemExit(
        "REFUSING: detect_array() missing."
    )

segment = ast.get_source_segment(
    source,
    detect_node,
) or ""

required_fragments = (
    "gaussian_filter(work, method.background_sigma_px)",
    "np.median(residual[finite])",
    "np.median(np.abs(residual[finite] - med))",
    "1.4826 * mad",
    "np.abs(residual - med)",
    "maximum_filter(signal, method.max_window_px)",
    "signal > method.peak_sigma * sigma",
    "peaks[:e, :] = False",
    "peaks[-e:, :] = False",
    "peaks[:, :e] = False",
    "peaks[:, -e:] = False",
)

missing_fragments = [
    fragment
    for fragment in required_fragments
    if fragment not in segment
]

if missing_fragments:
    raise SystemExit(
        "REFUSING: detector semantics changed; missing:\n"
        + "\n".join(
            missing_fragments
        )
    )


strict_gt_found = False

for node in ast.walk(detect_node):
    if not isinstance(node, ast.Compare):
        continue

    if any(
        isinstance(op, ast.Gt)
        for op in node.ops
    ):
        text = ast.get_source_segment(
            source,
            node,
        ) or ""

        if (
            "method.peak_sigma"
            in text
            and "sigma"
            in text
        ):
            strict_gt_found = True


if not strict_gt_found:
    raise SystemExit(
        "REFUSING: strict > peak threshold was not found."
    )


print()
print("AST semantic guards: PASS")
print("  residual = image - Gaussian(background sigma 8 px)")
print("  MAD measured on finite residual pixels")
print("  robust sigma = 1.4826 * MAD")
print("  signal = absolute residual about residual median")
print("  local maximum window = 7 px")
print("  threshold comparison = STRICT > 4 sigma")
print("  edge exclusion = 30 px after peak construction")


# ======================================================================
# 4. Import the actual package implementation.
# ======================================================================

sys.path.insert(
    0,
    str(ROOT / "src"),
)

from transient_pipeline.config import FrozenMethod
from transient_pipeline.detector import (
    analyze_fits_bytes,
    detect_array,
)


method = FrozenMethod(
    **method_values
)

if asdict(method) != method_values:
    raise SystemExit(
        "REFUSING: FrozenMethod runtime values differ "
        "from frozen_method.json."
    )

print()
print("Runtime FrozenMethod/config equivalence: PASS")


# ======================================================================
# 5. Independent reference implementation.
#
# This intentionally does not call transient_pipeline.detector.
# ======================================================================

def reference_detect(
    image: np.ndarray,
    method: FrozenMethod,
):
    finite = np.isfinite(image)

    if not finite.any():
        raise ValueError(
            "image contains no finite pixels"
        )

    fill = float(
        np.nanmedian(image)
    )

    work = np.where(
        finite,
        image,
        fill,
    ).astype(
        float,
        copy=False,
    )

    residual = (
        work
        - gaussian_filter(
            work,
            method.background_sigma_px,
        )
    )

    med = float(
        np.median(
            residual[finite]
        )
    )

    mad = float(
        np.median(
            np.abs(
                residual[finite]
                - med
            )
        )
    )

    sigma = 1.4826 * mad

    if (
        not np.isfinite(sigma)
        or sigma <= 0
    ):
        raise ValueError(
            f"invalid robust sigma {sigma}"
        )

    signal = np.abs(
        residual
        - med
    )

    peaks = (
        signal
        == maximum_filter(
            signal,
            method.max_window_px,
        )
    ) & (
        signal
        > method.peak_sigma * sigma
    )

    e = method.edge_px

    peaks[:e, :] = False
    peaks[-e:, :] = False
    peaks[:, :e] = False
    peaks[:, -e:] = False

    y, x = np.nonzero(
        peaks & finite
    )

    return {
        "x": x,
        "y": y,
        "signal": signal[y, x],
        "snr": signal[y, x] / sigma,
        "polarity":
            np.sign(
                residual[y, x]
                - med
            ).astype(int),
        "sigma": sigma,
        "median_residual": med,
    }


# ======================================================================
# 6. Deterministic synthetic array conformance.
# ======================================================================

cases = []

for seed in range(10):
    rng = np.random.default_rng(
        10000 + seed
    )

    image = rng.normal(
        1000.0,
        2.0,
        size=(240, 260),
    )

    # Strong opposite-polarity interior signals.
    py = 80 + seed
    px = 100 + seed

    ny = 155 - seed
    nx = 175 - seed

    image[py, px] += (
        70.0 + seed
    )

    image[ny, nx] -= (
        75.0 + seed
    )

    # Edge events must never survive.
    image[5, 5] += 120.0
    image[-6, -6] -= 120.0

    # Exercise finite-mask behaviour.
    image[
        40 + seed,
        45,
    ] = np.nan

    actual = detect_array(
        image.copy(),
        method,
    )

    reference = reference_detect(
        image.copy(),
        method,
    )

    for key in (
        "x",
        "y",
        "polarity",
    ):
        if not np.array_equal(
            actual[key],
            reference[key],
        ):
            raise SystemExit(
                f"REFUSING: synthetic case {seed} "
                f"differs for {key}."
            )

    for key in (
        "signal",
        "snr",
    ):
        if not np.allclose(
            actual[key],
            reference[key],
            rtol=0,
            atol=0,
        ):
            raise SystemExit(
                f"REFUSING: synthetic case {seed} "
                f"differs for {key}."
            )

    if actual["sigma"] != reference["sigma"]:
        raise SystemExit(
            f"REFUSING: sigma mismatch case {seed}."
        )

    if (
        actual["median_residual"]
        != reference["median_residual"]
    ):
        raise SystemExit(
            f"REFUSING: residual median mismatch case {seed}."
        )

    coords = set(
        zip(
            actual["y"].tolist(),
            actual["x"].tolist(),
        )
    )

    if (py, px) not in coords:
        raise SystemExit(
            f"REFUSING: positive injection lost in case {seed}."
        )

    if (ny, nx) not in coords:
        raise SystemExit(
            f"REFUSING: negative injection lost in case {seed}."
        )

    if (5, 5) in coords:
        raise SystemExit(
            f"REFUSING: positive edge event survived case {seed}."
        )

    if (
        image.shape[0] - 6,
        image.shape[1] - 6,
    ) in coords:
        raise SystemExit(
            f"REFUSING: negative edge event survived case {seed}."
        )

    lookup = {
        (int(y), int(x)):
            int(pol)
        for y, x, pol
        in zip(
            actual["y"],
            actual["x"],
            actual["polarity"],
        )
    }

    if lookup[(py, px)] != 1:
        raise SystemExit(
            f"REFUSING: positive polarity wrong case {seed}."
        )

    if lookup[(ny, nx)] != -1:
        raise SystemExit(
            f"REFUSING: negative polarity wrong case {seed}."
        )

    cases.append({
        "seed":
            seed,
        "sigma":
            actual["sigma"],
        "median_residual":
            actual["median_residual"],
        "peak_count":
            len(actual["x"]),
        "positive_injection":
            [py, px],
        "negative_injection":
            [ny, nx],
        "reference_exact_match":
            True,
        "positive_recovered":
            True,
        "negative_recovered":
            True,
        "edge_rejected":
            True,
    })


print()
print(
    "Synthetic array conformance: "
    f"PASS ({len(cases)}/{len(cases)})"
)


# ======================================================================
# 7. FITS/WCS end-to-end synthetic fixture.
# ======================================================================

try:
    from astropy.io import fits
    from astropy.wcs import WCS
except ImportError as exc:
    raise SystemExit(
        f"REFUSING: astropy unavailable: {exc}"
    )


rng = np.random.default_rng(
    20260821
)

image = rng.normal(
    1000.0,
    2.0,
    size=(220, 220),
)

target_y = 110
target_x = 110

image[
    target_y,
    target_x,
] += 100.0


w = WCS(
    naxis=2
)

# ~1 arcsec per pixel.
w.wcs.crpix = [
    target_x + 1,
    target_y + 1,
]

w.wcs.cdelt = np.array([
    -1.0 / 3600.0,
    1.0 / 3600.0,
])

w.wcs.crval = [
    180.0,
    15.0,
]

w.wcs.ctype = [
    "RA---TAN",
    "DEC--TAN",
]


hdu = fits.PrimaryHDU(
    data=image,
    header=w.to_header(),
)

buf = io.BytesIO()

fits.HDUList(
    [hdu]
).writeto(buf)

summary = analyze_fits_bytes(
    buf.getvalue(),
    180.0,
    15.0,
    method,
)

if summary.nearest_peak_sep_arcsec > 0.01:
    raise SystemExit(
        "REFUSING: synthetic WCS target was not "
        f"recovered at expected position: "
        f"{summary.nearest_peak_sep_arcsec} arcsec"
    )

if summary.nearest_peak_snr <= 4.0:
    raise SystemExit(
        "REFUSING: synthetic WCS target did not exceed 4 sigma."
    )

if summary.nearest_peak_polarity != 1:
    raise SystemExit(
        "REFUSING: synthetic WCS target polarity is wrong."
    )


print("Synthetic FITS/WCS end-to-end test: PASS")
print(
    "  target separation:",
    summary.nearest_peak_sep_arcsec,
    "arcsec",
)
print(
    "  target SNR:",
    summary.nearest_peak_snr,
)
print(
    "  total detected peaks:",
    summary.peak_count,
)


# ======================================================================
# 8. Existing complete test tree.
# ======================================================================

print()
print("=" * 100)
print("FULL TEST TREE")
print("=" * 100)

test = subprocess.run(
    [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "pytest",
        "-q",
        str(ROOT / "tests"),
    ],
    cwd=ROOT,
)

if test.returncode != 0:
    raise SystemExit(
        "REFUSING: test tree failed."
    )


# ======================================================================
# 9. Reconcile downstream execution denominator.
# ======================================================================

rows = (
    pixel_report
    .get("exposure_dispositions", {})
    .get("rows", [])
)

if len(rows) != 40:
    raise SystemExit(
        "REFUSING: pixel report does not contain 40 exposure dispositions."
    )


counts = {}

for row in rows:
    value = row[
        "pixel_disposition"
    ]

    counts[value] = (
        counts.get(value, 0)
        + 1
    )


expected_pixel_counts = {
    "FROZEN_IDENTITY_PIXEL_AVAILABLE_NO_PROVEN_LEGACY_MATCH": 27,
    "NO_REUSABLE_PIXEL_PRODUCT_LOCATED": 10,
    "UNAVAILABLE_NO_DETECTOR": 3,
}

if counts != expected_pixel_counts:
    raise SystemExit(
        "REFUSING: post-identity pixel accounting changed:\n"
        + json.dumps(
            counts,
            indent=2,
            sort_keys=True,
        )
    )


needs_acquisition = sorted(
    row["exposure_id"]
    for row in rows
    if (
        row["pixel_disposition"]
        == "NO_REUSABLE_PIXEL_PRODUCT_LOCATED"
    )
)

available_now = sorted(
    row["exposure_id"]
    for row in rows
    if (
        row["pixel_disposition"]
        == "FROZEN_IDENTITY_PIXEL_AVAILABLE_NO_PROVEN_LEGACY_MATCH"
    )
)

unavailable = sorted(
    row["exposure_id"]
    for row in rows
    if (
        row["pixel_disposition"]
        == "UNAVAILABLE_NO_DETECTOR"
    )
)


# ======================================================================
# 10. Create immutable detector freeze.
# ======================================================================

if OUT.exists():
    raise SystemExit(
        f"REFUSING: detector freeze already exists: {OUT}"
    )

OUT.mkdir(
    parents=True,
    exist_ok=False,
)


files = []

files.append(
    copy_into(
        DETECTOR,
        "source/transient_pipeline/detector.py",
    )
)

files.append(
    copy_into(
        CONFIG_PY,
        "source/transient_pipeline/config.py",
    )
)

files.append(
    copy_into(
        METHOD_JSON,
        "config/frozen_method.json",
    )
)

files.append(
    copy_into(
        PROTOCOL,
        "protocol/PROTOCOL_v1.0_PRE_REMAINING_SUB5_2026-08-20.md",
    )
)

files.append(
    copy_into(
        TEST_FILE,
        "tests/test_detector_array.py",
    )
)

files.append(
    copy_into(
        IDENTITY_MANIFEST,
        "provenance/poss1_identity_v028_freeze_manifest.json",
    )
)

files.append(
    copy_into(
        PIXEL_REPORT,
        "provenance/POSS1_V028_PIXEL_PROVENANCE_RECONCILIATION_2026-08-21.json",
    )
)


conformance = {
    "operation":
        "v028_detector_conformance",

    "detector_source_sha256":
        sha256_file(DETECTOR),

    "frozen_method_sha256":
        sha256_file(METHOD_JSON),

    "config_source_sha256":
        sha256_file(CONFIG_PY),

    "protocol_sha256":
        sha256_file(PROTOCOL),

    "identity_snapshot_id":
        EXPECTED_IDENTITY_SNAPSHOT_ID,

    "method":
        method_values,

    "semantics": {
        "background":
            "image minus Gaussian-filtered image",
        "background_sigma_px":
            8.0,
        "finite_pixel_policy":
            "non-finite image pixels filled with nanmedian for filtering; "
            "robust statistics use original finite mask",
        "residual_centre":
            "median of finite residual pixels",
        "robust_sigma":
            "1.4826 * median(abs(residual - residual_median))",
        "signal":
            "abs(residual - residual_median)",
        "local_maximum":
            "signal == maximum_filter(signal, size=7)",
        "threshold":
            "signal > 4.0 * robust_sigma",
        "threshold_is_strict":
            True,
        "edge_exclusion_px":
            30,
        "edge_mask_applied_after_threshold_and_local_max":
            True,
        "polarity":
            "sign(residual - residual_median)",
        "diagnostic_cross_observatory_arcsec":
            10.0,
        "strict_registered_match_arcsec":
            3.0,
    },

    "synthetic_array_cases":
        cases,

    "synthetic_array_reference_matches":
        len(cases),

    "synthetic_fits_wcs": {
        "passed":
            True,
        "nearest_peak_sep_arcsec":
            summary.nearest_peak_sep_arcsec,
        "nearest_peak_snr":
            summary.nearest_peak_snr,
        "nearest_peak_polarity":
            summary.nearest_peak_polarity,
        "peak_count":
            summary.peak_count,
    },

    "existing_test_tree":
        "passed",

    "science_pixel_detector_runs":
        0,

    "execution_denominator": {
        "identity_validated":
            37,
        "pixels_ready_from_identity_cache":
            27,
        "clean_acquisition_required":
            10,
        "pixels_unavailable_no_detector":
            3,
    },

    "available_now":
        available_now,

    "requires_clean_acquisition":
        needs_acquisition,

    "unavailable":
        unavailable,
}


conf_path = (
    OUT
    / "conformance"
    / "detector_conformance.json"
)

conf_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

conf_path.write_text(
    json.dumps(
        conformance,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

files.append({
    "snapshot_path":
        "conformance/detector_conformance.json",
    "source":
        "<generated>",
    "sha256":
        sha256_file(conf_path),
    "bytes":
        conf_path.stat().st_size,
})


core = {
    "snapshot_format":
        1,

    "version":
        "0.2.8",

    "purpose":
        "freeze exact 4-sigma detector implementation and method "
        "before clean <=5-minute science execution",

    "detector_source_sha256":
        EXPECTED_DETECTOR_SHA,

    "frozen_method_sha256":
        EXPECTED_METHOD_SHA,

    "protocol_sha256":
        EXPECTED_PROTOCOL_SHA,

    "identity_snapshot_id":
        EXPECTED_IDENTITY_SNAPSHOT_ID,

    "identity_manifest_sha256":
        EXPECTED_IDENTITY_MANIFEST_SHA,

    "science_pixel_detector_runs_during_freeze":
        0,

    "synthetic_conformance":
        "passed",

    "files":
        sorted(
            files,
            key=lambda x:
                x["snapshot_path"],
        ),
}


snapshot_id = hashlib.sha256(
    json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


manifest = {
    **core,

    "snapshot_id":
        snapshot_id,

    "created_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "project_root_at_capture":
        str(ROOT),
}


manifest_path = (
    OUT
    / "freeze_manifest.json"
)

manifest_path.write_text(
    json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

manifest_sha = sha256_file(
    manifest_path
)


# ======================================================================
# 11. Closure / execution plan.
# ======================================================================

closure = f"""# Detector freeze closure — v0.2.8

## Detector

Source:

`src/transient_pipeline/detector.py`

SHA256:

`{EXPECTED_DETECTOR_SHA}`

Frozen method SHA256:

`{EXPECTED_METHOD_SHA}`

## Frozen semantics

- Gaussian local-background sigma: **8 px**
- residual: image minus Gaussian-filtered image
- centre: median of finite residuals
- robust sigma: **1.4826 × MAD**
- both polarities through absolute centred residual
- threshold: **strictly >4 robust sigma**
- local-maximum window: **7 px**
- edge exclusion: **30 px**
- broad diagnostic radius: **10 arcsec**
- strict registered coincidence gate: **3 arcsec**

The edge mask is applied after local-maximum/threshold construction.

## Conformance

- deterministic synthetic array cases: **{len(cases)} passed**
- independent reference equivalence: **{len(cases)}/{len(cases)}**
- opposite polarities recovered: **passed**
- edge injections rejected: **passed**
- finite/NaN handling exercised: **passed**
- synthetic FITS/WCS end-to-end: **passed**
- existing repository tests: **passed**

No historical science pixel was analysed during this freeze.

## Science execution boundary

- physical POSS exposures: **40**
- detector-eligible identities: **37**
- identity-cache pixels presently linked: **27**
- require clean acquisition/reacquisition: **10**
- pixels unavailable / no detector: **3**

The three unavailable exposures remain in the denominator and are not
scientific non-detections.

Old exploratory detector dispositions are not reused.

Snapshot ID:

`{snapshot_id}`

Manifest SHA256:

`{manifest_sha}`
"""


CLOSURE.write_text(
    closure,
    encoding="utf-8",
)

shutil.copy2(
    CLOSURE,
    OUT / "DETECTOR_FREEZE_V028_CLOSURE_2026-08-21.md",
)


print()
print("=" * 100)
print("DETECTOR FREEZE v0.2.8 PASSED")
print("=" * 100)

print("Snapshot:", OUT)
print("Snapshot ID:", snapshot_id)
print("Manifest SHA256:", manifest_sha)

print()
print("Detector:")
print("  source SHA256: ", EXPECTED_DETECTOR_SHA)
print("  method SHA256: ", EXPECTED_METHOD_SHA)

print()
print("Conformance:")
print("  synthetic array cases:       ", len(cases))
print("  exact reference matches:      ", len(cases))
print("  FITS/WCS end-to-end:           PASS")
print("  repository test tree:          PASS")

print()
print("Science execution denominator:")
print("  detector-eligible:             37")
print("  pixels already linked:         27")
print("  clean acquisition required:    10")
print("  unavailable / no detector:      3")

print()
print("10 exposures requiring clean acquisition:")

for pid in needs_acquisition:
    print(" ", pid)

print()
print("3 unavailable exposures:")

for pid in unavailable:
    print(" ", pid)

print()
print(
    "No historical science pixel was analysed during this freeze."
)
print()
print(
    "NEXT: clean-acquire the 10 missing pixel products, "
    "then execute this exact frozen detector across all 37 usable exposures."
)
