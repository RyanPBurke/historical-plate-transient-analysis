from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, timezone
import csv
import hashlib
import inspect
import json
import platform
import subprocess
import sys
import zipfile

ROOT = Path.cwd()

PREFLIGHT = (
    ROOT / "research" /
    "POSS1_V028_EXACT_PLATE_CUTOUT_PREFLIGHT_V2_2026-08-21.csv"
)

IDENTITY_CACHE = (
    ROOT / "cache" /
    "poss1_exact_plate_identity_refresh_v028"
)

SOURCE_MAP = (
    ROOT / "research" /
    "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.csv"
)

SOURCE_REPORT = (
    ROOT / "research" /
    "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.json"
)

ENV_REPORT = (
    ROOT / "research" /
    "DETECTOR_ENVIRONMENT_V028_2026-08-21.json"
)

JAR_DIR = (
    ROOT / "tools" / "vendor"
)

JAR = (
    JAR_DIR / "skyview.jar"
)

JAVA_SOURCE_DIR = (
    ROOT / "work" /
    "skyview_native_dss_source_v028"
)

JAVA_REPORT = (
    ROOT / "research" /
    "SKYVIEW_NATIVE_DSS_API_INSPECTION_2026-08-21.txt"
)

DETECTOR = (
    ROOT / "src" /
    "transient_pipeline" /
    "detector.py"
)

METHOD = (
    ROOT / "config" /
    "frozen_method.json"
)

PROTOCOL = (
    ROOT / "research_snapshots" /
    "sub5_production_freeze_v0.2.1_2026-08-20" /
    "inputs" /
    "PROTOCOL_v1.0_PRE_REMAINING_SUB5_2026-08-20.md"
)

DETECTOR_MANIFEST = (
    ROOT / "research_snapshots" /
    "detector_freeze_v0.2.8_2026-08-21" /
    "freeze_manifest.json"
)

EXPECTED = {
    DETECTOR:
        "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7",

    METHOD:
        "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1",

    PROTOCOL:
        "9479666b93df3f7dc85b3f61861c93ea70fe50be47c1070e6ce7ec444c66a700",

    DETECTOR_MANIFEST:
        "4d66c8f7099ece364053a451f15688ba7d2105c8a3b112d392e8e7a4a6c97c06",
}

EXPECTED_SNAPSHOT_ID = (
    "e3a9b42eaf58027171bb5449533e8bc413672acae7881d9641884363fb2aef7a"
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


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


def safe(pid: str):
    return "".join(
        c if c.isalnum() or c in "-_."
        else "_"
        for c in pid
    )


# ======================================================================
# 1. Immutable detector/environment guards.
# ======================================================================

for path, expected in EXPECTED.items():
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required frozen file missing: {path}"
        )

    actual = sha_file(path)

    if actual != expected:
        raise SystemExit(
            f"REFUSING: frozen hash mismatch:\n"
            f"{path}\n"
            f"expected={expected}\n"
            f"actual={actual}"
        )


manifest = json.loads(
    DETECTOR_MANIFEST.read_text(
        encoding="utf-8"
    )
)

snapshot_id = str(
    manifest.get("snapshot_id")
    or manifest.get("snapshotId")
    or ""
)

if (
    snapshot_id
    and snapshot_id != EXPECTED_SNAPSHOT_ID
):
    raise SystemExit(
        "REFUSING: detector snapshot ID changed."
    )


import numpy
import scipy
import astropy
from scipy.ndimage import (
    gaussian_filter,
    maximum_filter,
)


env = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "python_version":
        sys.version,

    "python_executable":
        sys.executable,

    "platform":
        platform.platform(),

    "numpy_version":
        numpy.__version__,

    "scipy_version":
        scipy.__version__,

    "astropy_version":
        astropy.__version__,

    "gaussian_filter_signature":
        str(
            inspect.signature(
                gaussian_filter
            )
        ),

    "maximum_filter_signature":
        str(
            inspect.signature(
                maximum_filter
            )
        ),

    "detector_sha256":
        sha_file(DETECTOR),

    "frozen_method_sha256":
        sha_file(METHOD),

    "protocol_sha256":
        sha_file(PROTOCOL),

    "detector_manifest_sha256":
        sha_file(DETECTOR_MANIFEST),

    "detector_snapshot_id":
        EXPECTED_SNAPSHOT_ID,

    "science_pixels_processed":
        False,

    "detector_run":
        False,
}


ENV_REPORT.write_text(
    json.dumps(
        env,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


# ======================================================================
# 2. Recover exact native-DSS source identity from sidecars.
# ======================================================================

if not PREFLIGHT.is_file():
    raise SystemExit(
        f"REFUSING: missing exact-plate preflight: {PREFLIGHT}"
    )


rows = read_csv(PREFLIGHT)

if len(rows) != 10:
    raise SystemExit(
        f"REFUSING: expected 10 preflight rows; got {len(rows)}"
    )


native_rows = []


for row in rows:
    pid = row["exposure_id"]

    region = str(
        row["expected_region"]
    ).strip().upper()

    plate_id = str(
        row["hhh_plate_id"]
    ).strip().upper()

    if (
        row.get("identity_refresh_state")
        != "VALIDATED"
    ):
        raise SystemExit(
            f"REFUSING: identity not validated: {pid}"
        )

    identity_dir = (
        IDENTITY_CACHE /
        safe(pid)
    )

    sidecars = sorted(
        identity_dir.glob(
            "*_skyview_identity.provenance.json"
        )
    )

    if len(sidecars) != 1:
        raise SystemExit(
            f"REFUSING: {pid} has "
            f"{len(sidecars)} SkyView identity sidecars"
        )

    obj = json.loads(
        sidecars[0].read_text(
            encoding="utf-8"
        )
    )

    sky = obj.get("skyview") or {}

    sc_region = str(
        sky.get("region") or ""
    ).strip().upper()

    sc_plate = str(
        sky.get("plate_id") or ""
    ).strip().upper()

    raw_dir = str(
        sky.get("raw_plate_directory")
        or ""
    ).strip()

    hhh_url = str(
        sky.get("hhh_url")
        or ""
    ).strip()

    probe_url = str(
        sky.get("probe_tile_url")
        or ""
    ).strip()

    if sc_region != region:
        raise SystemExit(
            f"REFUSING: sidecar REGION mismatch for {pid}: "
            f"{sc_region!r} != {region!r}"
        )

    if sc_plate != plate_id:
        raise SystemExit(
            f"REFUSING: sidecar PLATEID mismatch for {pid}: "
            f"{sc_plate!r} != {plate_id!r}"
        )

    if not raw_dir or not hhh_url or not probe_url:
        raise SystemExit(
            f"REFUSING: incomplete native DSS provenance for {pid}"
        )

    native_rows.append({
        "exposure_id":
            pid,

        "region":
            region,

        "plate_id":
            plate_id,

        "raw_plate_directory":
            raw_dir,

        "hhh_url":
            hhh_url,

        "hhh_sha256":
            str(
                sky.get(
                    "hhh_sha256"
                ) or ""
            ),

        "probe_tile_url":
            probe_url,

        "probe_tile_sha256":
            str(
                sky.get(
                    "probe_tile_sha256"
                ) or ""
            ),

        "probe_tile_bytes":
            str(
                sky.get(
                    "probe_tile_bytes"
                ) or ""
            ),

        "identity_sidecar":
            str(
                sidecars[0]
            ),
    })


with SOURCE_MAP.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:

    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            native_rows[0].keys()
        ),
    )

    writer.writeheader()
    writer.writerows(
        native_rows
    )


# ======================================================================
# 3. Java availability.
# ======================================================================

java = subprocess.run(
    [
        "java",
        "-version",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    check=False,
)

java_text = (
    java.stdout or ""
).strip()

if java.returncode != 0:
    raise SystemExit(
        "REFUSING: Java is not usable.\n"
        + java_text
    )


# ======================================================================
# 4. Obtain official SkyView JAR only if not already present.
# ======================================================================

JAR_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

jar_downloaded = False

if not JAR.is_file():
    url = (
        "https://skyview.gsfc.nasa.gov/"
        "jar/skyview.jar"
    )

    req = Request(
        url,
        headers={
            "User-Agent":
                "historical-transient-pipeline/"
                "0.2.8-native-dss-preflight"
        },
    )

    with urlopen(
        req,
        timeout=180,
    ) as response:
        raw = response.read()

    if not raw.startswith(
        b"PK"
    ):
        raise SystemExit(
            "REFUSING: SkyView JAR response "
            "is not a ZIP/JAR."
        )

    JAR.write_bytes(
        raw
    )

    jar_downloaded = True


jar_sha = sha_file(
    JAR
)


# ======================================================================
# 5. Inspect/extract official native DSS implementation source.
# ======================================================================

JAVA_SOURCE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


wanted_names = (
    "DSSImage.java",
    "DSSImageFactory.java",
    "HDecomp.java",
    "HDecompressor.java",
    "DSS.java",
)


extracted = []


with zipfile.ZipFile(
    JAR,
    "r",
) as zf:

    names = zf.namelist()

    matches = [
        name
        for name in names
        if any(
            name.endswith(
                wanted
            )
            for wanted in wanted_names
        )
    ]

    for name in sorted(
        matches
    ):
        data = zf.read(
            name
        )

        out = (
            JAVA_SOURCE_DIR
            / Path(name).name
        )

        # Avoid two different package files silently
        # overwriting one another.
        if out.exists():
            out = (
                JAVA_SOURCE_DIR
                / name.replace(
                    "/",
                    "__"
                )
            )

        out.write_bytes(
            data
        )

        extracted.append({
            "jar_entry":
                name,

            "output":
                str(out),

            "sha256":
                sha_file(out),

            "bytes":
                len(data),
        })


if not any(
    x["jar_entry"].endswith(
        "DSSImage.java"
    )
    for x in extracted
):
    raise SystemExit(
        "REFUSING: official JAR contains no "
        "DSSImage.java source."
    )


# ======================================================================
# 6. Compact source/API report.
# ======================================================================

interesting = (
    "class DSSImage",
    "DSSImage(",
    "getData(",
    "getDataArray(",
    "getWidth(",
    "getHeight(",
    "getWCS(",
    "HDecomp",
    "decomp(",
    "getNx(",
    "getNy(",
)


report_lines = []

report_lines.append(
    "SKYVIEW NATIVE DSS API INSPECTION"
)

report_lines.append(
    "=" * 72
)

report_lines.append(
    f"java_returncode: {java.returncode}"
)

report_lines.append(
    "java_version:"
)

report_lines.extend(
    "  " + line
    for line in java_text.splitlines()
)

report_lines.append("")

report_lines.append(
    f"skyview_jar: {JAR}"
)

report_lines.append(
    f"skyview_jar_sha256: {jar_sha}"
)

report_lines.append(
    f"jar_downloaded_this_run: {jar_downloaded}"
)

report_lines.append("")

report_lines.append(
    "Extracted source:"
)

for item in extracted:
    report_lines.append(
        "  "
        + item["jar_entry"]
        + " -> "
        + item["output"]
    )


report_lines.append("")
report_lines.append(
    "Relevant source lines:"
)


for item in extracted:
    path = Path(
        item["output"]
    )

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        continue

    hits = []

    for number, line in enumerate(
        text.splitlines(),
        start=1,
    ):
        if any(
            token in line
            for token in interesting
        ):
            hits.append(
                f"{number:5d}: {line.strip()}"
            )

    if hits:
        report_lines.append("")
        report_lines.append(
            f"[{path.name}]"
        )

        report_lines.extend(
            hits[:120]
        )


JAVA_REPORT.write_text(
    "\n".join(
        report_lines
    ) + "\n",
    encoding="utf-8",
)


source_report = {
    "recorded_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "native_dss_exposures":
        len(native_rows),

    "source_map_sha256":
        sha_file(SOURCE_MAP),

    "java_returncode":
        java.returncode,

    "java_version_output":
        java_text,

    "skyview_jar":
        str(JAR),

    "skyview_jar_sha256":
        jar_sha,

    "jar_downloaded_this_run":
        jar_downloaded,

    "extracted_java_sources":
        extracted,

    "api_report":
        str(JAVA_REPORT),

    "detector_environment_report":
        str(ENV_REPORT),

    "science_pixels_processed":
        False,

    "detector_run":
        False,
}


SOURCE_REPORT.write_text(
    json.dumps(
        source_report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


print("=" * 78)
print("NATIVE DSS PREPARATION COMPLETE")
print("=" * 78)

print(
    "Exact native DSS source identities:",
    len(native_rows),
    "/ 10",
)

print(
    "Java:",
    "PASS"
    if java.returncode == 0
    else "FAIL",
)

print(
    "SkyView JAR SHA256:",
    jar_sha,
)

print(
    "Official Java source files extracted:",
    len(extracted),
)

print()

print(
    "Detector environment supplement:",
    ENV_REPORT,
)

print(
    "Native source map:",
    SOURCE_MAP,
)

print(
    "Native source report:",
    SOURCE_REPORT,
)

print(
    "SkyView API inspection:",
    JAVA_REPORT,
)

print()

print(
    "No historical science pixel was analysed."
)

print(
    "No transient detector was run."
)
