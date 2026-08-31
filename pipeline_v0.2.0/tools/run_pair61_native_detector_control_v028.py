from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen
from dataclasses import fields
from datetime import datetime, timezone
import base64, csv, gzip, hashlib, json, subprocess, sys

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, search_around_sky
from astropy.io import fits
from astropy.wcs import WCS

from transient_pipeline.config import FrozenMethod
from transient_pipeline.detector import detect_array


ROOT = Path.cwd()

ORDER = 61

POSS_ID = "POSS-I:875:E:rec521"
REGION = "XE520"
POSS_PLATE = "090N"

DASCH_PLATE = "ai44092"

RA0 = 337.7875
DEC0 = 12.745

CORE = 1024
HALO = 64
SIZE = CORE + 2 * HALO


PAIRMAP = (
    ROOT / "research" /
    "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
)

METHOD = (
    ROOT / "config" /
    "frozen_method.json"
)

DETECTOR = (
    ROOT / "src" /
    "transient_pipeline" /
    "detector.py"
)

WORK = (
    ROOT / "work" /
    "pair61_native_detector_control_v028"
)

OUT = (
    ROOT / "results" /
    "pair61_native_detector_control_v028"
)

WORK.mkdir(
    parents=True,
    exist_ok=True,
)

OUT.mkdir(
    parents=True,
    exist_ok=True,
)


DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa"
    "0fd0fee864a81d954f74fe4a5f5af25e7"
)

METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd"
    "3002be90297e55bb0e0dcdd9dea1d0c4c1"
)

JAR_SHA = (
    "2b949f68d73899cd63b2f600f60f6c5d"
    "fd1795532ed29b6ea986f71f83d36afe"
)

API = (
    "https://api.starglass.cfa.harvard.edu/"
    "public/dasch/dr7/mosaic_package"
)

UA = (
    "historical-transient-pipeline/"
    "0.2.8-pair61-native-science"
)


def sha(path):
    h = hashlib.sha256()

    with Path(path).open("rb") as f:
        for b in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(b)

    return h.hexdigest()


def arrsha(a):
    a = np.ascontiguousarray(a)

    h = hashlib.sha256()

    h.update(
        str(a.dtype).encode()
    )

    h.update(
        repr(a.shape).encode()
    )

    h.update(
        a.tobytes()
    )

    return h.hexdigest()


def jdefault(o):
    if isinstance(
        o,
        np.generic,
    ):
        return o.item()

    if isinstance(
        o,
        np.ndarray,
    ):
        return o.tolist()

    if isinstance(
        o,
        Path,
    ):
        return str(o)

    return str(o)


def csvwrite(
    path,
    rows,
    names,
):
    with Path(path).open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        w = csv.DictWriter(
            f,
            fieldnames=names,
            extrasaction="ignore",
        )

        w.writeheader()
        w.writerows(rows)


def guard():
    if sha(DETECTOR) != DETECTOR_SHA:
        raise RuntimeError(
            "REFUSING: frozen detector SHA changed"
        )

    if sha(METHOD) != METHOD_SHA:
        raise RuntimeError(
            "REFUSING: frozen method SHA changed"
        )

    cfg = json.loads(
        METHOD.read_text(
            encoding="utf-8"
        )
    )

    names = {
        f.name
        for f in fields(FrozenMethod)
    }

    unknown = set(cfg) - names

    if unknown:
        raise RuntimeError(
            "REFUSING: unknown frozen "
            f"config fields: {sorted(unknown)}"
        )

    m = FrozenMethod(
        **cfg
    )

    expected = {
        "background_sigma_px": 8.0,
        "peak_sigma": 4.0,
        "max_window_px": 7,
        "edge_px": 30,
        "diagnostic_match_arcsec": 10.0,
        "strict_registered_match_arcsec": 3.0,
    }

    for k, v in expected.items():
        if getattr(m, k) != v:
            raise RuntimeError(
                f"REFUSING: {k} changed"
            )

    return m, cfg


def pairrow():
    with PAIRMAP.open(
        newline="",
        encoding="utf-8-sig",
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    hits = [
        r
        for r in rows
        if int(
            float(
                r["canonical_order"]
            )
        ) == ORDER
    ]

    if len(hits) != 1:
        raise RuntimeError(
            f"REFUSING: order61 rows={len(hits)}"
        )

    r = hits[0]

    if (
        r.get("poss_exposure_id") != POSS_ID
        or r.get("poss_region") != REGION
        or r.get(
            "partner_dasch_plate_id"
        ) != DASCH_PLATE
    ):
        raise RuntimeError(
            "REFUSING: order61 identity changed: "
            f"{r}"
        )

    return r


def findjar():
    hits = []

    for p in ROOT.rglob("*.jar"):
        try:
            if sha(p) == JAR_SHA:
                hits.append(p)
        except OSError:
            pass

    if not hits:
        raise RuntimeError(
            "REFUSING: frozen SkyView JAR "
            "not found"
        )

    return sorted(
        hits,
        key=lambda p: (
            len(str(p)),
            str(p),
        ),
    )[0]


def reference():
    hits = []

    for base in (
        ROOT / "work",
        ROOT / "cache",
        ROOT / "results",
    ):

        if not base.exists():
            continue

        for p in base.rglob(
            "*.fits"
        ):
            try:
                h = fits.getheader(
                    p,
                    0,
                )
            except Exception:
                continue

            if (
                str(
                    h.get(
                        "REGION",
                        "",
                    )
                ).strip().upper()
                == REGION

                and str(
                    h.get(
                        "PLATEID",
                        "",
                    )
                ).strip().upper()
                == POSS_PLATE

                and int(
                    h.get(
                        "NAXIS1",
                        0,
                    ) or 0
                ) == 177

                and int(
                    h.get(
                        "NAXIS2",
                        0,
                    ) or 0
                ) == 177
            ):
                hits.append(
                    (
                        p,
                        h,
                    )
                )

    if not hits:
        raise RuntimeError(
            "REFUSING: validated "
            "XE520/090N 177x177 "
            "reference FITS not found"
        )

    hits.sort(
        key=lambda x: (
            len(
                str(
                    x[0]
                )
            ),
            str(
                x[0]
            ),
        )
    )

    p, h = hits[0]

    if not WCS(
        h
    ).celestial.has_celestial:

        raise RuntimeError(
            "REFUSING: XE520 reference "
            "has no celestial WCS"
        )

    return p, h


JAVA = r"""
import java.io.DataOutputStream;
import java.io.FileOutputStream;
import skyview.survey.DSSImage;

public class DSSNativeExtract {

 public static void main(String[] a)
     throws Exception {

  DSSImage im =
      new DSSImage(a[0]);

  int x0 =
      Integer.parseInt(a[1]);

  int y0 =
      Integer.parseInt(a[2]);

  int w =
      Integer.parseInt(a[3]);

  int h =
      Integer.parseInt(a[4]);

  if (
      x0 < 0 ||
      y0 < 0 ||
      x0 + w > im.getWidth() ||
      y0 + h > im.getHeight()
  ) {
      throw new IllegalArgumentException(
          "bounds"
      );
  }

  try (
      DataOutputStream o =
          new DataOutputStream(
              new FileOutputStream(
                  a[5]
              )
          )
  ) {

   for (
       int y = 0;
       y < h;
       y++
   ) {

    long row =
        ((long)(y0 + y))
        * im.getWidth();

    for (
        int x = 0;
        x < w;
        x++
    ) {

     o.writeInt(
         (int)Math.round(
             im.getData(
                 row + x0 + x
             )
         )
     );
    }
   }
  }

  System.err.println(
      "native POSS "
      + im.getWidth()
      + "x"
      + im.getHeight()
  );
 }
}
"""


def poss_native(
    jar,
    h,
    w,
):
    src = (
        WORK /
        "DSSNativeExtract.java"
    )

    src.write_text(
        JAVA,
        encoding="utf-8",
    )

    c = subprocess.run(
        [
            "javac",
            "-cp",
            str(jar),
            str(src),
        ],
        capture_output=True,
        text=True,
    )

    if c.returncode:
        raise RuntimeError(
            "javac failed:\n"
            + c.stdout
            + "\n"
            + c.stderr
        )

    sky = SkyCoord(
        RA0 * u.deg,
        DEC0 * u.deg,
    )

    lx, ly = (
        w.world_to_pixel(
            sky
        )
    )

    cx = (
        float(lx)
        + float(
            h["CNPIX1"]
        )
        - 1.0
    )

    cy = (
        float(ly)
        + float(
            h["CNPIX2"]
        )
        - 1.0
    )

    x0 = (
        int(
            round(cx)
        )
        - SIZE // 2
    )

    y0 = (
        int(
            round(cy)
        )
        - SIZE // 2
    )

    fw = int(
        h.get(
            "XPIXELS",
            14000,
        )
    )

    fh = int(
        h.get(
            "YPIXELS",
            13999,
        )
    )

    if (
        x0 < 0
        or y0 < 0
        or x0 + SIZE > fw
        or y0 + SIZE > fh
    ):
        raise RuntimeError(
            "REFUSING: POSS window "
            "outside plate"
        )

    raw = (
        "https://skyview.gsfc.nasa.gov/"
        "surveys/dss/xe520"
    )

    b = (
        WORK /
        "xe520_native_1152_i32be.bin"
    )

    sep = (
        ";"
        if sys.platform.startswith(
            "win"
        )
        else ":"
    )

    r = subprocess.run(
        [
            "java",
            "-cp",
            str(WORK)
            + sep
            + str(jar),

            "DSSNativeExtract",

            raw,

            str(x0),
            str(y0),

            str(SIZE),
            str(SIZE),

            str(b),
        ],
        capture_output=True,
        text=True,
    )

    if r.returncode:
        raise RuntimeError(
            "POSS native extraction failed:\n"
            + r.stdout
            + "\n"
            + r.stderr
        )

    if (
        b.stat().st_size
        != SIZE * SIZE * 4
    ):
        raise RuntimeError(
            "REFUSING: POSS native "
            "byte count mismatch"
        )

    a = np.fromfile(
        b,
        dtype=">i4",
    ).reshape(
        SIZE,
        SIZE,
    ).astype(
        np.int32,
        copy=False,
    )

    np.save(
        WORK /
        "xe520_native_1152.npy",
        a,
    )

    return (
        a,
        {
            "x0": x0,
            "y0": y0,

            "center_x": cx,
            "center_y": cy,

            "full_shape": [
                fh,
                fw,
            ],

            "raw_base": raw,

            "sha256":
                arrsha(a),

            "java_stderr":
                r.stderr.strip(),
        },
    )


def package():
    body = json.dumps({
        "plate_id":
            DASCH_PLATE,

        "binning":
            1,
    }).encode()

    req = Request(
        API,
        data=body,
        method="POST",
        headers={
            "Accept":
                "application/json",

            "Content-Type":
                "application/json",

            "User-Agent":
                UA,
        },
    )

    with urlopen(
        req,
        timeout=120,
    ) as r:

        return json.loads(
            r.read().decode()
        )


def tpv(md):
    a = md.get(
        "astrometry"
    )

    if (
        not a
        or not a.get(
            "b01HeaderGz"
        )
    ):
        raise RuntimeError(
            "REFUSING: no DASCH astrometry"
        )

    bh = (
        fits.Header.fromstring(
            gzip.decompress(
                base64.b64decode(
                    a["b01HeaderGz"]
                )
            ),
            sep="\n",
        )
    )

    if "CTYPE1A" in bh:
        raise RuntimeError(
            "REFUSING: pair61 unexpectedly "
            "has multiple WCS solutions"
        )

    h = fits.Header()

    for k, v in {
        "WCSAXES":
            2,

        "WCSNAME":
            "DASCH astrometric solution #1",

        "RADESYS":
            "ICRS",

        "CTYPE1":
            "RA---TPV",

        "CTYPE2":
            "DEC--TPV",

        "CUNIT1":
            "deg",

        "CUNIT2":
            "deg",
    }.items():

        h[k] = v

    for k in (
        "CRVAL1",
        "CRVAL2",

        "CRPIX1",
        "CRPIX2",

        "CD1_1",
        "CD1_2",
        "CD2_1",
        "CD2_2",
    ):
        h[k] = bh[k]

    for k, v in bh.items():
        if (
            k.startswith(
                "PV"
            )
            and k[-1:].isdigit()
        ):
            h[k] = v

    w = WCS(
        h
    ).celestial

    rd = a.get(
        "rotationDelta"
    )

    rk = {
        90: -1,
        180: 2,
        -180: 2,
        -90: 1,
        0: 0,
        None: 0,
    }.get(
        rd,
        "BAD",
    )

    if rk == "BAD":
        raise RuntimeError(
            "REFUSING: unsupported "
            f"rotationDelta {rd}"
        )

    m = md["mosaic"]

    shape = (
        int(
            m["b01Height"]
        ),
        int(
            m["b01Width"]
        ),
    )

    return (
        w,
        h,
        rk,
        shape,
    )


def base_slice(
    ox0,
    oy0,
    n,
    k,
    H,
    W,
):
    ox1 = ox0 + n
    oy1 = oy0 + n

    if k == 0:
        return (
            oy0,
            oy1,
            ox0,
            ox1,
        )

    if k == -1:
        return (
            H - ox1,
            H - ox0,
            oy0,
            oy1,
        )

    if k == 1:
        return (
            ox0,
            ox1,
            W - oy1,
            W - oy0,
        )

    if k == 2:
        return (
            H - oy1,
            H - oy0,
            W - ox1,
            W - ox0,
        )

    raise RuntimeError(k)


def dasch_native(
    pkg,
    w,
    k,
    shape,
):
    H, W = shape

    if k in (
        -1,
        1,
    ):
        outH = W
        outW = H

    else:
        outH = H
        outW = W

    sky = SkyCoord(
        RA0 * u.deg,
        DEC0 * u.deg,
    )

    cx, cy = (
        w.world_to_pixel(
            sky
        )
    )

    cx = float(cx)
    cy = float(cy)

    ox0 = (
        int(
            round(cx)
        )
        - SIZE // 2
    )

    oy0 = (
        int(
            round(cy)
        )
        - SIZE // 2
    )

    if (
        ox0 < 0
        or oy0 < 0
        or ox0 + SIZE > outW
        or oy0 + SIZE > outH
    ):
        raise RuntimeError(
            "REFUSING: DASCH window "
            "outside plate"
        )

    by0, by1, bx0, bx1 = (
        base_slice(
            ox0,
            oy0,
            SIZE,
            k,
            H,
            W,
        )
    )

    with fits.open(
        pkg["baseFitsUrl"],

        use_fsspec=True,

        lazy_load_hdus=True,

        fsspec_kwargs={
            "block_size":
                4 * 1024 * 1024,

            "cache_type":
                "readahead",
        },
    ) as hdul:

        q = [
            (
                i,
                hdu,
            )
            for i, hdu
            in enumerate(hdul)
            if (
                getattr(
                    hdu,
                    "shape",
                    None,
                )
                and tuple(
                    map(
                        int,
                        hdu.shape,
                    )
                )
                == (
                    H,
                    W,
                )
            )
        ]

        if len(q) != 1:
            raise RuntimeError(
                "REFUSING: expected one "
                "DASCH image HDU; "
                f"got {len(q)}"
            )

        i, hdu = q[0]

        base = np.asarray(
            hdu.section[
                by0:by1,
                bx0:bx1
            ]
        )

        a = np.rot90(
            base,
            k=k,
        )

        comp = getattr(
            hdu,
            "compression_type",
            None,
        )

        tile = tuple(
            int(x)
            for x in (
                getattr(
                    hdu,
                    "tile_shape",
                    (),
                )
                or ()
            )
        )

        cls = (
            type(hdu).__name__
        )

    if a.shape != (
        SIZE,
        SIZE,
    ):
        raise RuntimeError(
            "REFUSING: DASCH section "
            f"shape {a.shape}"
        )

    if not np.issubdtype(
        a.dtype,
        np.integer,
    ):
        v = a[
            np.isfinite(a)
        ]

        if np.any(
            np.abs(
                v
                - np.rint(v)
            )
            > 1e-12
        ):
            raise RuntimeError(
                "REFUSING: noninteger "
                "DASCH bin1 pixels"
            )

    np.save(
        WORK /
        "ai44092_native_1152.npy",
        a,
    )

    return (
        a,
        {
            "output_x0":
                ox0,

            "output_y0":
                oy0,

            "center_x":
                cx,

            "center_y":
                cy,

            "base_shape":
                [
                    H,
                    W,
                ],

            "output_shape":
                [
                    outH,
                    outW,
                ],

            "rotation_k":
                k,

            "rotation_delta":
                pkg[
                    "metadata"
                ][
                    "astrometry"
                ].get(
                    "rotationDelta"
                ),

            "base_slice":
                [
                    by0,
                    by1,
                    bx0,
                    bx1,
                ],

            "hdu_index":
                i,

            "hdu_class":
                cls,

            "compression":
                comp,

            "tile_shape":
                tile,

            "object_bytes":
                int(
                    pkg[
                        "baseFitsSize"
                    ]
                ),

            "dtype":
                str(
                    a.dtype
                ),

            "sha256":
                arrsha(a),
        },
    )


def poss_rows(
    d,
    pm,
    rh,
    rw,
    dw,
    dm,
):
    rows = []

    for j in range(
        len(
            d["x"]
        )
    ):
        x = int(
            d["x"][j]
        )

        y = int(
            d["y"][j]
        )

        if not (
            HALO <= x < HALO + CORE
            and
            HALO <= y < HALO + CORE
        ):
            continue

        gx = (
            pm["x0"]
            + x
        )

        gy = (
            pm["y0"]
            + y
        )

        sky = (
            rw.pixel_to_world(
                gx
                - float(
                    rh[
                        "CNPIX1"
                    ]
                )
                + 1,

                gy
                - float(
                    rh[
                        "CNPIX2"
                    ]
                )
                + 1,
            )
        )

        dx, dy = map(
            float,
            dw.world_to_pixel(
                sky
            ),
        )

        inside = (
            dm["output_x0"]
            + HALO
            <= dx
            < dm["output_x0"]
            + HALO
            + CORE

            and

            dm["output_y0"]
            + HALO
            <= dy
            < dm["output_y0"]
            + HALO
            + CORE
        )

        rows.append({
            "candidate_index":
                len(rows),

            "local_x":
                x,

            "local_y":
                y,

            "global_x":
                gx,

            "global_y":
                gy,

            "ra_deg":
                float(
                    sky.ra.deg
                ),

            "dec_deg":
                float(
                    sky.dec.deg
                ),

            "snr":
                float(
                    d["snr"][j]
                ),

            "signal":
                float(
                    d["signal"][j]
                ),

            "polarity":
                int(
                    d[
                        "polarity"
                    ][j]
                ),

            "sigma":
                float(
                    d["sigma"]
                ),

            "inside_other_core":
                inside,
        })

    return rows


def dasch_rows(
    d,
    dm,
    dw,
    rh,
    rw,
    pm,
):
    rows = []

    for j in range(
        len(
            d["x"]
        )
    ):
        x = int(
            d["x"][j]
        )

        y = int(
            d["y"][j]
        )

        if not (
            HALO <= x < HALO + CORE
            and
            HALO <= y < HALO + CORE
        ):
            continue

        gx = (
            dm["output_x0"]
            + x
        )

        gy = (
            dm["output_y0"]
            + y
        )

        sky = (
            dw.pixel_to_world(
                gx,
                gy,
            )
        )

        px, py = (
            rw.world_to_pixel(
                sky
            )
        )

        fx = (
            float(px)
            + float(
                rh[
                    "CNPIX1"
                ]
            )
            - 1
        )

        fy = (
            float(py)
            + float(
                rh[
                    "CNPIX2"
                ]
            )
            - 1
        )

        inside = (
            pm["x0"]
            + HALO
            <= fx
            < pm["x0"]
            + HALO
            + CORE

            and

            pm["y0"]
            + HALO
            <= fy
            < pm["y0"]
            + HALO
            + CORE
        )

        rows.append({
            "candidate_index":
                len(rows),

            "local_x":
                x,

            "local_y":
                y,

            "global_x":
                gx,

            "global_y":
                gy,

            "ra_deg":
                float(
                    sky.ra.deg
                ),

            "dec_deg":
                float(
                    sky.dec.deg
                ),

            "snr":
                float(
                    d["snr"][j]
                ),

            "signal":
                float(
                    d["signal"][j]
                ),

            "polarity":
                int(
                    d[
                        "polarity"
                    ][j]
                ),

            "sigma":
                float(
                    d["sigma"]
                ),

            "inside_other_core":
                inside,
        })

    return rows


def match(
    pr,
    dr,
    m,
):
    p = [
        r
        for r in pr
        if r[
            "inside_other_core"
        ]
    ]

    d = [
        r
        for r in dr
        if r[
            "inside_other_core"
        ]
    ]

    if (
        not p
        or not d
    ):
        return []

    ps = SkyCoord(
        [
            r["ra_deg"]
            for r in p
        ] * u.deg,

        [
            r["dec_deg"]
            for r in p
        ] * u.deg,
    )

    ds = SkyCoord(
        [
            r["ra_deg"]
            for r in d
        ] * u.deg,

        [
            r["dec_deg"]
            for r in d
        ] * u.deg,
    )

    ip, id_, sep, _ = (
        search_around_sky(
            ps,
            ds,
            m.diagnostic_match_arcsec
            * u.arcsec,
        )
    )

    out = []

    for z in np.argsort(
        sep.arcsec
    ):
        a = p[
            int(
                ip[z]
            )
        ]

        b = d[
            int(
                id_[z]
            )
        ]

        s = float(
            sep.arcsec[z]
        )

        out.append({
            "match_index":
                len(out),

            "separation_arcsec":
                s,

            "strict_le_3arcsec":
                s
                <= m.strict_registered_match_arcsec,

            "poss_candidate_index":
                a[
                    "candidate_index"
                ],

            "poss_ra_deg":
                a[
                    "ra_deg"
                ],

            "poss_dec_deg":
                a[
                    "dec_deg"
                ],

            "poss_snr":
                a[
                    "snr"
                ],

            "poss_polarity":
                a[
                    "polarity"
                ],

            "dasch_candidate_index":
                b[
                    "candidate_index"
                ],

            "dasch_ra_deg":
                b[
                    "ra_deg"
                ],

            "dasch_dec_deg":
                b[
                    "dec_deg"
                ],

            "dasch_snr":
                b[
                    "snr"
                ],

            "dasch_polarity":
                b[
                    "polarity"
                ],
        })

    return out


def main():
    print(
        "=" * 80
    )

    print(
        "PAIR 61 — NATIVE-PIXEL "
        "FROZEN-DETECTOR SCIENCE CONTROL"
    )

    print(
        "=" * 80
    )

    print(
        "THIS RUN EXECUTES THE FROZEN "
        "4-SIGMA DETECTOR ON BOTH "
        "HISTORICAL PLATES."
    )

    print(
        "Raw coincidences are not yet "
        "astrophysical-transient "
        "classifications."
    )

    print()

    m, cfg = guard()

    row = pairrow()

    jar = findjar()

    refp, rh = (
        reference()
    )

    rw = WCS(
        rh
    ).celestial

    print(
        "Frozen detector/method/JAR: PASS"
    )

    print(
        "Pair identity: PASS"
    )

    print(
        "POSS WCS reference:",
        refp,
    )

    print()

    print(
        "[1/4] Reading native "
        "POSS XE520 pixels ..."
    )

    pa, pm = poss_native(
        jar,
        rh,
        rw,
    )

    print(
        "  shape/dtype:",
        pa.shape,
        pa.dtype,
    )

    print(
        "  SHA256:",
        pm["sha256"],
    )

    print(
        "[2/4] Reading native "
        "DASCH ai44092 pixels ..."
    )

    pkg = package()

    dw, dh, rk, bshape = (
        tpv(
            pkg["metadata"]
        )
    )

    da, dm = (
        dasch_native(
            pkg,
            dw,
            rk,
            bshape,
        )
    )

    (
        WORK /
        "ai44092_bin1_tpv_header.txt"
    ).write_text(
        dh.tostring(
            sep="\n",
            endcard=True,
            padding=False,
        )
        + "\n",

        encoding="utf-8",
    )

    print(
        "  shape/dtype:",
        da.shape,
        da.dtype,
    )

    print(
        "  SHA256:",
        dm["sha256"],
    )

    print(
        "  remote mosaic:",
        f"{dm['object_bytes'] / (1024**2):.1f} MiB",
        dm["hdu_class"],
        dm["compression"],
        dm["tile_shape"],
    )

    print()

    print(
        "[3/4] RUNNING FROZEN DETECTOR ..."
    )

    pd = detect_array(
        pa,
        m,
    )

    dd = detect_array(
        da,
        m,
    )

    pr = poss_rows(
        pd,
        pm,
        rh,
        rw,
        dw,
        dm,
    )

    dr = dasch_rows(
        dd,
        dm,
        dw,
        rh,
        rw,
        pm,
    )

    pc = [
        r
        for r in pr
        if r[
            "inside_other_core"
        ]
    ]

    dc = [
        r
        for r in dr
        if r[
            "inside_other_core"
        ]
    ]

    print(
        "  POSS all peaks / core / common:",
        len(
            pd["x"]
        ),
        len(pr),
        len(pc),
        "| sigma",
        f"{float(pd['sigma']):.6g}",
    )

    print(
        "  DASCH all peaks / core / common:",
        len(
            dd["x"]
        ),
        len(dr),
        len(dc),
        "| sigma",
        f"{float(dd['sigma']):.6g}",
    )

    print(
        "[4/4] Crossmatching "
        "common-sky peaks ..."
    )

    matches = match(
        pr,
        dr,
        m,
    )

    strict = [
        r
        for r in matches
        if r[
            "strict_le_3arcsec"
        ]
    ]

    cf = [
        "candidate_index",
        "local_x",
        "local_y",
        "global_x",
        "global_y",
        "ra_deg",
        "dec_deg",
        "snr",
        "signal",
        "polarity",
        "sigma",
        "inside_other_core",
    ]

    mf = [
        "match_index",
        "separation_arcsec",
        "strict_le_3arcsec",

        "poss_candidate_index",
        "poss_ra_deg",
        "poss_dec_deg",
        "poss_snr",
        "poss_polarity",

        "dasch_candidate_index",
        "dasch_ra_deg",
        "dasch_dec_deg",
        "dasch_snr",
        "dasch_polarity",
    ]

    pcsv = (
        OUT /
        "pair61_poss_native_candidates.csv"
    )

    dcsv = (
        OUT /
        "pair61_dasch_native_candidates.csv"
    )

    mcsv = (
        OUT /
        "pair61_raw_coincidences.csv"
    )

    csvwrite(
        pcsv,
        pr,
        cf,
    )

    csvwrite(
        dcsv,
        dr,
        cf,
    )

    csvwrite(
        mcsv,
        matches,
        mf,
    )

    overlap = float(
        row[
            "actual_overlap_s"
        ]
    )

    report = {
        "run_kind":
            (
                "pair61_native_pixel_"
                "frozen_detector_"
                "science_control"
            ),

        "recorded_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "canonical_order":
            ORDER,

        "pair_key":
            row.get(
                "pair_key"
            ),

        "poss_exposure_id":
            POSS_ID,

        "poss_region":
            REGION,

        "poss_plate_id":
            POSS_PLATE,

        "dasch_plate_id":
            DASCH_PLATE,

        "overlap_start_utc":
            row.get(
                "overlap_start_utc"
            ),

        "overlap_end_utc":
            row.get(
                "overlap_end_utc"
            ),

        "actual_overlap_s":
            overlap,

        "actual_overlap_minutes":
            overlap / 60,

        "field_center_icrs_deg":
            [
                RA0,
                DEC0,
            ],

        "frozen_detector_sha256":
            sha(
                DETECTOR
            ),

        "frozen_method_sha256":
            sha(
                METHOD
            ),

        "frozen_method":
            cfg,

        "skyview_jar":
            str(jar),

        "skyview_jar_sha256":
            sha(jar),

        "poss_wcs_reference":
            str(refp),

        "poss_wcs_reference_sha256":
            sha(refp),

        "window": {
            "core_px":
                CORE,

            "halo_px":
                HALO,

            "total_px":
                SIZE,

            "note":
                (
                    "Detector runs on "
                    "1152x1152 native pixels; "
                    "only central 1024x1024 "
                    "candidates are accepted. "
                    "64px halo exceeds frozen "
                    "30px edge mask and sigma8 "
                    "Gaussian ~32px default "
                    "support."
                ),
        },

        "poss_native":
            pm,

        "dasch_native":
            dm,

        "detector": {
            "poss_all_peaks":
                len(
                    pd["x"]
                ),

            "poss_sigma":
                float(
                    pd["sigma"]
                ),

            "poss_median_residual":
                float(
                    pd[
                        "median_residual"
                    ]
                ),

            "dasch_all_peaks":
                len(
                    dd["x"]
                ),

            "dasch_sigma":
                float(
                    dd["sigma"]
                ),

            "dasch_median_residual":
                float(
                    dd[
                        "median_residual"
                    ]
                ),

            "poss_core_peaks":
                len(pr),

            "dasch_core_peaks":
                len(dr),

            "poss_common_sky_peaks":
                len(pc),

            "dasch_common_sky_peaks":
                len(dc),
        },

        "crossmatch": {
            "diagnostic_arcsec":
                m.diagnostic_match_arcsec,

            "strict_arcsec":
                m.strict_registered_match_arcsec,

            "raw_le_10arcsec":
                len(matches),

            "raw_le_3arcsec":
                len(strict),
        },

        "interpretation":
            (
                "Actual frozen-detector "
                "execution on native historical "
                "pixels from POSS-I and DASCH. "
                "Matches are raw positional "
                "coincidences only; Gaia/static-"
                "source rejection, morphology, "
                "PSF/saturation/registration "
                "vetting, controls and injection-"
                "recovery remain pending."
            ),

        "outputs": {
            "poss_candidates_csv":
                str(pcsv),

            "dasch_candidates_csv":
                str(dcsv),

            "matches_csv":
                str(mcsv),
        },
    }

    rp = (
        OUT /
        "pair61_native_detector_control_report.json"
    )

    rp.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
            default=jdefault,
        )
        + "\n",

        encoding="utf-8",
    )

    print()

    print(
        "=" * 80
    )

    print(
        "PAIR 61 NATIVE-DETECTOR "
        "SCIENCE CONTROL COMPLETE"
    )

    print(
        "=" * 80
    )

    print(
        "Actual exposure overlap:",
        f"{overlap:.3f} s "
        f"({overlap / 60:.3f} min)",
    )

    print(
        "Raw <=10 arcsec coincidences:",
        len(matches),
    )

    print(
        "Raw <=3 arcsec coincidences: ",
        len(strict),
    )

    if matches:
        print()

        print(
            "Closest raw coincidences "
            "(max 20):"
        )

        for r in matches[:20]:
            print(
                f"  "
                f"{r['separation_arcsec']:8.4f}\""
                f" | POSS SNR="
                f"{r['poss_snr']:.2f}"
                f" pol="
                f"{r['poss_polarity']:+d}"
                f" | DASCH SNR="
                f"{r['dasch_snr']:.2f}"
                f" pol="
                f"{r['dasch_polarity']:+d}"
                f" | strict="
                f"{r['strict_le_3arcsec']}"
            )

    else:
        print()

        print(
            "No raw <=10 arcsec coincidence "
            "in this matched native field."
        )

    print()

    print(
        "POSS candidates:",
        pcsv,
    )

    print(
        "DASCH candidates:",
        dcsv,
    )

    print(
        "Raw matches:",
        mcsv,
    )

    print(
        "Report:",
        rp,
    )

    print()

    print(
        "FROZEN DETECTOR WAS RUN."
    )

    print(
        "No Gaia/static-source rejection "
        "has yet been applied."
    )

    print(
        "Do not interpret raw coincidences "
        "as astrophysical transients yet."
    )


if __name__ == "__main__":
    main()

