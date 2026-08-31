from urllib.request import Request, urlopen
import base64
import gzip
import hashlib
import json

import numpy as np
import fsspec
from astropy.io import fits


API = (
    "https://api.starglass.cfa.harvard.edu/"
    "public/dasch/dr7/mosaic_package"
)

PLATE = "ai44092"
SIZE = 1152


# Get fresh full-resolution DASCH mosaic URL.
req = Request(
    API,
    data=json.dumps({
        "plate_id": PLATE,
        "binning": 1,
    }).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "historical-transient-pipeline/0.2.8-native-dasch-test",
    },
    method="POST",
)

with urlopen(req, timeout=120) as r:
    package = json.loads(
        r.read().decode("utf-8")
    )

url = package["baseFitsUrl"]
size_bytes = int(package["baseFitsSize"])


def array_hash(a):
    a = np.ascontiguousarray(a)

    h = hashlib.sha256()
    h.update(str(a.dtype).encode())
    h.update(str(a.shape).encode())
    h.update(a.tobytes())

    return h.hexdigest()


with fits.open(
    url,
    use_fsspec=True,
    lazy_load_hdus=True,
    fsspec_kwargs={
        "block_size": 4 * 1024 * 1024,
        "cache_type": "readahead",
    },
) as hdul:

    candidates = [
        (i, hdu)
        for i, hdu in enumerate(hdul)
        if (
            getattr(hdu, "shape", None)
            and len(hdu.shape) == 2
            and hdu.shape[0] > SIZE
            and hdu.shape[1] > SIZE
        )
    ]

    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one large image HDU; "
            f"found {len(candidates)}"
        )

    index, hdu = candidates[0]

    height, width = hdu.shape

    x0 = width // 2 - SIZE // 2
    y0 = height // 2 - SIZE // 2

    # Two independent reads of exactly the same remote section.
    a = np.asarray(
        hdu.section[
            y0:y0 + SIZE,
            x0:x0 + SIZE
        ]
    )

    b = np.asarray(
        hdu.section[
            y0:y0 + SIZE,
            x0:x0 + SIZE
        ]
    )

    ha = array_hash(a)
    hb = array_hash(b)

    finite = np.isfinite(a)

    if np.issubdtype(
        a.dtype,
        np.integer,
    ):
        noninteger_fraction = 0.0
    else:
        vals = a[finite]
        noninteger_fraction = float(
            np.mean(
                np.abs(vals - np.rint(vals))
                > 1e-12
            )
        )

    exact = (
        ha == hb
        and np.array_equal(
            a,
            b,
            equal_nan=True,
        )
    )

    print("=" * 72)
    print("NATIVE DASCH SECTION CONTROL")
    print("=" * 72)

    print("Plate:", PLATE)

    print(
        "Remote full mosaic:",
        f"{size_bytes / (1024**2):.1f} MiB"
    )

    print(
        "Image HDU:",
        index,
        type(hdu).__name__,
    )

    print(
        "Full shape:",
        width,
        "x",
        height,
    )

    print(
        "Compression:",
        getattr(
            hdu,
            "compression_type",
            None,
        ),
    )

    print(
        "Compression tile:",
        getattr(
            hdu,
            "tile_shape",
            None,
        ),
    )

    print()

    print(
        "Native section:",
        a.shape[1],
        "x",
        a.shape[0],
    )

    print("dtype:", a.dtype)

    print(
        "finite:",
        int(finite.sum()),
    )

    print(
        "min / median / max:",
        float(np.nanmin(a)),
        "/",
        float(np.nanmedian(a)),
        "/",
        float(np.nanmax(a)),
    )

    print(
        "non-integer fraction:",
        noninteger_fraction,
    )

    print()

    print("SHA256:", ha)
    print("Repeat SHA256:", hb)
    print("Repeat exact:", exact)

    if not exact:
        raise RuntimeError(
            "Repeated native section reads differ."
        )

    print()
    print(
        "Historical full-resolution DASCH pixels WERE read."
    )
    print(
        "No transient detector was run."
    )
