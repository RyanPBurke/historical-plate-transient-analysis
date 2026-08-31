from pathlib import Path
import csv
import hashlib
import json

from astropy.io import fits
from astropy.wcs import WCS


ROOT = Path.cwd()

PAIR_MAP = (
    ROOT / "research" /
    "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
)

OUT = (
    ROOT / "research" /
    "SUB5_V028_REMAINING_GEOMETRY_INPUT_INSPECTION_2026-08-21.json"
)

ORDERS = {2, 48, 49, 62, 65, 66}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)
    return h.hexdigest()


with PAIR_MAP.open(
    "r",
    encoding="utf-8-sig",
    newline="",
) as f:
    rows = list(csv.DictReader(f))


targets = [
    r for r in rows
    if int(float(r["canonical_order"])) in ORDERS
]


if len(targets) != 6:
    raise SystemExit(
        f"REFUSING: expected 6 target rows; got {len(targets)}"
    )


results = []


for r in sorted(
    targets,
    key=lambda x: int(float(x["canonical_order"])),
):
    order = int(float(r["canonical_order"]))

    stored = (
        r.get("poss_fits_path")
        or ""
    ).strip()

    expected_sha = (
        r.get("poss_fits_sha256")
        or ""
    ).strip().lower()

    path = Path(stored)

    if stored and not path.is_absolute():
        path = ROOT / path

    rec = {
        "canonical_order": order,
        "poss_exposure_id": r["poss_exposure_id"],
        "poss_region": r["poss_region"],
        "fits_path": str(path) if stored else "",
        "fits_exists": False,
        "hash_match": False,
    }

    if not stored or not path.is_file():
        rec["state"] = "NO_LOCAL_FROZEN_FITS"
        results.append(rec)
        continue

    actual_sha = sha(path)

    rec["fits_exists"] = True
    rec["actual_sha256"] = actual_sha
    rec["expected_sha256"] = expected_sha
    rec["hash_match"] = (
        bool(expected_sha)
        and actual_sha == expected_sha
    )

    if expected_sha and actual_sha != expected_sha:
        rec["state"] = "HASH_MISMATCH"
        results.append(rec)
        continue

    # HEADER ONLY. No image array is opened/read.
    hdr = fits.getheader(
        path,
        ext=0,
    )

    try:
        w = WCS(hdr).celestial
        celestial = bool(
            w.has_celestial
        )
    except Exception as exc:
        celestial = False
        rec["wcs_error"] = (
            f"{type(exc).__name__}: {exc}"
        )

    amdx = sorted(
        k for k in hdr
        if str(k).startswith("AMDX")
    )

    amdy = sorted(
        k for k in hdr
        if str(k).startswith("AMDY")
    )

    ppo = sorted(
        k for k in hdr
        if str(k).startswith("PPO")
    )

    rec.update({
        "state": "HEADER_READ",
        "naxis1": hdr.get("NAXIS1"),
        "naxis2": hdr.get("NAXIS2"),
        "region": hdr.get("REGION"),
        "platelabel": hdr.get("PLTLABEL"),
        "plateid": hdr.get("PLATEID"),
        "ctype1": hdr.get("CTYPE1"),
        "ctype2": hdr.get("CTYPE2"),
        "crpix1": hdr.get("CRPIX1"),
        "crpix2": hdr.get("CRPIX2"),
        "cnpix1": hdr.get("CNPIX1"),
        "cnpix2": hdr.get("CNPIX2"),
        "celestial_wcs": celestial,
        "amdx_terms": len(amdx),
        "amdy_terms": len(amdy),
        "ppo_terms": len(ppo),
        "has_plate_ra": "PLTRAH" in hdr,
        "has_plate_dec": "PLTDECD" in hdr,
        "header_cards": len(hdr),
    })

    results.append(rec)


# Inspect the already-cached order-45 DASCH metadata too.
dmeta_path = (
    ROOT / "work" /
    "poss47_tpv_geometry_census_v028" /
    "dasch_metadata" /
    "j03761_mosaic_package_metadata.json"
)

order45 = {
    "metadata_path": str(dmeta_path),
    "exists": dmeta_path.is_file(),
}

if dmeta_path.is_file():
    obj = json.loads(
        dmeta_path.read_text(
            encoding="utf-8"
        )
    )

    astro = obj.get("astrometry") or {}

    exposures = astro.get("exposures") or []

    order45["exposures"] = [
        {
            "index": i,
            "number": e.get("number"),
            "midpointDate": e.get("midpointDate"),
            "durMin": e.get("durMin"),
            "raDeg": e.get("raDeg"),
            "decDeg": e.get("decDeg"),
            "centerSource": e.get("centerSource"),
            "dateSource": e.get("dateSource"),
        }
        for i, e in enumerate(exposures)
        if isinstance(e, dict)
    ]


report = {
    "frozen_poss_headers": results,
    "order45_dasch": order45,
    "historical_pixel_arrays_read": False,
    "detector_run": False,
}

OUT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


print("=" * 76)
print("REMAINING GEOMETRY INPUT INSPECTION")
print("=" * 76)

for r in results:
    print(
        f"order {r['canonical_order']:2d} "
        f"{r['poss_exposure_id']} / {r['poss_region']}"
    )

    print(
        "  state:",
        r["state"],
    )

    if r["state"] == "HEADER_READ":
        print(
            "  dimensions:",
            r["naxis1"],
            "x",
            r["naxis2"],
        )

        print(
            "  REGION / PLTLABEL / PLATEID:",
            r["region"],
            "/",
            r["platelabel"],
            "/",
            r["plateid"],
        )

        print(
            "  celestial WCS:",
            r["celestial_wcs"],
        )

        print(
            "  CNPIX:",
            r["cnpix1"],
            r["cnpix2"],
        )

        print(
            "  GSSS terms:",
            "AMDX",
            r["amdx_terms"],
            "AMDY",
            r["amdy_terms"],
            "PPO",
            r["ppo_terms"],
        )


print()
print("Order 45 DASCH exposures:")

for e in order45.get(
    "exposures",
    [],
):
    print(
        " ",
        e,
    )


print()
print("Report:", OUT)
print("No historical image arrays were read.")
print("No detector was run.")
