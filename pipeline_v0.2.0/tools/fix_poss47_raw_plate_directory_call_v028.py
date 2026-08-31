from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import ast
import hashlib
import inspect
import sys


ROOT = Path.cwd()

TARGET = (
    ROOT
    / "tools"
    / "census_poss47_tpv_geometry_v028.py"
)

SKY = (
    ROOT
    / "src"
    / "transient_pipeline"
    / "poss1_skyview.py"
)

EXPECTED_SKY_SHA = (
    "22470c1956e6b0ddb885d51092aa0a30"
    "dd322bfc1d48c6b49bcd0ed3620a732e"
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


for path in (
    TARGET,
    SKY,
):
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: missing file: {path}"
        )


if sha256_file(SKY) != EXPECTED_SKY_SHA:
    raise SystemExit(
        "REFUSING: frozen poss1_skyview.py hash changed."
    )


# ------------------------------------------------------------------
# Verify the actual runtime helper contract first.
# ------------------------------------------------------------------

sys.path.insert(
    0,
    str(
        ROOT / "src"
    ),
)

import transient_pipeline.poss1_skyview as sv


sig = inspect.signature(
    sv.raw_plate_directory
)

required = (
    "band",
    "region",
    "descriptor_entry",
)


for name in required:

    if name not in sig.parameters:
        raise SystemExit(
            f"REFUSING: raw_plate_directory() "
            f"has no {name!r} parameter."
        )

    param = sig.parameters[
        name
    ]

    if (
        param.kind
        != inspect.Parameter.KEYWORD_ONLY
    ):
        raise SystemExit(
            f"REFUSING: expected {name} "
            "to be keyword-only."
        )


print(
    "Runtime helper signature:",
    sig,
)

print(
    "Keyword-only contract: PASS"
)


# ------------------------------------------------------------------
# Read target BOM-safely.
# ------------------------------------------------------------------

raw = TARGET.read_bytes()

had_bom = raw.startswith(
    b"\xef\xbb\xbf"
)

text = raw.decode(
    "utf-8-sig"
)

ast.parse(
    text,
    filename=str(TARGET),
)


old = '''    raw_dir = sv.raw_plate_directory(
        desc.file_prefix,
        matches[0].path,
    )
'''


new = '''    raw_dir = sv.raw_plate_directory(
        band=band,
        region=region,
        descriptor_entry=matches[0],
    )
'''


already_fixed = (
    new in text
    and old not in text
)


if already_fixed:

    print(
        "Wrapper fix already present."
    )

else:

    count = text.count(
        old
    )

    if count != 1:
        raise SystemExit(
            "REFUSING: expected exactly one "
            "known faulty raw_plate_directory() call; "
            f"found {count}."
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
            "pre_poss47_raw_plate_directory_fix_"
            + stamp
        )
    )

    backup_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    backup = (
        backup_dir
        / TARGET.name
    )

    # Exact original bytes, including optional BOM.
    backup.write_bytes(
        raw
    )


    patched = text.replace(
        old,
        new,
        1,
    )


    # Parse before mutation.
    ast.parse(
        patched,
        filename=str(TARGET),
    )


    TARGET.write_bytes(
        patched.encode(
            "utf-8"
        )
    )


    print(
        "Wrapper patch: PASS"
    )

    print(
        "Backup:",
        backup,
    )


# ------------------------------------------------------------------
# Independent post-write validation.
# ------------------------------------------------------------------

final_raw = TARGET.read_bytes()

final_text = final_raw.decode(
    "utf-8-sig"
)

ast.parse(
    final_text,
    filename=str(TARGET),
)


if old in final_text:
    raise SystemExit(
        "REFUSING: positional helper call remains."
    )


if new not in final_text:
    raise SystemExit(
        "REFUSING: corrected helper call absent."
    )


if sha256_file(SKY) != EXPECTED_SKY_SHA:
    raise SystemExit(
        "REFUSING: frozen SkyView source changed "
        "during wrapper repair."
    )


print(
    "Target syntax: PASS"
)

print(
    "Correct keyword call: PASS"
)

print(
    "Frozen poss1_skyview.py: UNCHANGED"
)

print(
    "Detector source: UNTOUCHED"
)

print(
    "Science pixels: NOT PROCESSED"
)

print(
    "Detector: NOT RUN"
)
