from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import math
import urllib.request

from astropy.io import fits

from transient_pipeline.poss1_skyview import (
    SKYVIEW_DSS1R_DESCRIPTOR,
    parse_skyview_descriptor,
    raw_plate_directory,
    hhh_identity,
)

ROOT = Path.cwd()

PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"

ORDER = 1
EXPECTED_POSS = "POSS-I:413:E:rec297"
EXPECTED_BAND = "E"
EXPECTED_REGION = "XE296"
EXPECTED_PLATE_ID = "06S2"
EXPECTED_DASCH = "ai43437"
EXPECTED_OVERLAP_S = 3480.0

DASCH_API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"

OUT_DIR = ROOT / "results" / "order01_native_preflight_v028"
OUT = OUT_DIR / "order01_exact_native_source_and_dasch_metadata_v028.json"
DESC_COPY = OUT_DIR / "order01_skyview_dss1r_descriptor_v028.xml"
HHH_COPY = OUT_DIR / "order01_xe296_hhh_v028.hhh"

UA = "historical-transient-pipeline/0.2.8-order01-exact-native-metadata-preflight"


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha256_bytes(data: bytes):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_bytes(url: str, *, accept: str = "*/*", timeout: int = 90):
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": UA,
            "Accept": accept,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return {
            "status": getattr(r, "status", None),
            "final_url": r.geturl(),
            "content_type": r.headers.get("Content-Type"),
            "bytes": body,
        }


def post_json(url: str, payload: dict, *, timeout: int = 90):
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        method="POST",
        data=raw,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return {
            "status": getattr(r, "status", None),
            "final_url": r.geturl(),
            "content_type": r.headers.get("Content-Type"),
            "json": json.loads(body.decode("utf-8")),
        }


def angular_sep_arcsec(ra1, dec1, ra2, dec2):
    r1 = math.radians(float(ra1))
    d1 = math.radians(float(dec1))
    r2 = math.radians(float(ra2))
    d2 = math.radians(float(dec2))
    a = (
        math.sin((d2-d1)/2.0)**2
        + math.cos(d1)*math.cos(d2)*math.sin((r2-r1)/2.0)**2
    )
    a = min(1.0, max(0.0, a))
    return math.degrees(2.0*math.asin(math.sqrt(a))) * 3600.0


def select_order_row(rows):
    hits = []
    for r in rows:
        try:
            if int(float(str(r.get("canonical_order", "")).strip())) == ORDER:
                hits.append(r)
        except Exception:
            pass
    if len(hits) != 1:
        raise RuntimeError(f"Expected one canonical Order {ORDER}; got {len(hits)}")
    return hits[0]


def fits_identity(path: Path):
    if not path.is_file():
        raise RuntimeError(f"Missing frozen identity FITS: {path}")

    file_sha = sha256_file(path)
    with fits.open(path, memmap=False) as hdul:
        h = hdul[0].header.copy()
        shape = tuple(int(x) for x in hdul[0].data.shape)

    return {
        "path": str(path),
        "sha256": file_sha,
        "shape": shape,
        "plate_id": str(h.get("PLATEID", "")).strip().upper(),
        "region": str(h.get("REGION", "")).strip().upper(),
        "date_obs": str(h.get("DATE-OBS", "")).strip(),
        "crval1": float(h["CRVAL1"]) if "CRVAL1" in h else None,
        "crval2": float(h["CRVAL2"]) if "CRVAL2" in h else None,
        "cnpix1": float(h["CNPIX1"]) if "CNPIX1" in h else None,
        "cnpix2": float(h["CNPIX2"]) if "CNPIX2" in h else None,
        "selected_header": {
            k: h[k]
            for k in (
                "PLATEID", "REGION", "DATE-OBS",
                "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
                "CTYPE1", "CTYPE2",
                "CNPIX1", "CNPIX2",
                "XPIXELS", "YPIXELS",
                "PLTRAH", "PLTRAM", "PLTRAS",
                "PLTDECSN", "PLTDECD", "PLTDECM", "PLTDECS",
                "PPO3", "PPO6", "PLTSCALE",
            )
            if k in h
        },
    }


def parse_hhh_header(raw: bytes):
    if len(raw) < 2880 or not raw.startswith(b"SIMPLE"):
        raise RuntimeError("REFUSING: XE296 .hhh is not a FITS-style plate header")

    text = raw.decode("ISO-8859-1", errors="replace")
    try:
        hdr = fits.Header.fromstring(text, sep="")
    except Exception as exc:
        return {
            "parsed": False,
            "parse_error": repr(exc),
            "selected_header": {},
        }

    selected = {
        k: hdr[k]
        for k in (
            "SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2",
            "PLATEID", "REGION", "DATE-OBS",
            "XPIXELS", "YPIXELS",
            "PLTRAH", "PLTRAM", "PLTRAS",
            "PLTDECSN", "PLTDECD", "PLTDECM", "PLTDECS",
            "XPIXELSZ", "YPIXELSZ",
            "PPO3", "PPO6", "PLTSCALE",
        )
        if k in hdr
    }
    return {
        "parsed": True,
        "parse_error": None,
        "selected_header": selected,
    }


def main():
    print("=" * 112)
    print("ORDER 01 — EXACT NATIVE POSS SOURCE + DASCH METADATA PREFLIGHT v028")
    print("=" * 112)
    print(
        "Uses the frozen poss1_skyview implementation itself. Fetches only SkyView descriptor/HHH "
        "metadata and DASCH mosaic-package metadata; no DSS tile and no DASCH FITS mosaic."
    )
    print("No detector. No native science pixels.")
    print()

    if not PAIR_MAP.is_file():
        raise RuntimeError(f"Missing pair map: {PAIR_MAP}")

    rows = read_csv(PAIR_MAP)
    if len(rows) != 47:
        raise RuntimeError(f"REFUSING: expected 47 POSS rows, got {len(rows)}")

    row = select_order_row(rows)

    pair_guards = {
        "poss_exposure_id": row.get("poss_exposure_id") == EXPECTED_POSS,
        "poss_region": row.get("poss_region") == EXPECTED_REGION,
        "dasch_plate": str(row.get("partner_dasch_plate_id", "")).strip().lower() == EXPECTED_DASCH,
        "actual_overlap_s": abs(float(row["actual_overlap_s"]) - EXPECTED_OVERLAP_S) < 1e-6,
        "true_wcs_intersection": str(row.get("true_wcs_intersection", "")).strip().lower() == "true",
        "true_wcs_overlap_fraction": abs(float(row["true_wcs_overlap_fraction"]) - 1.0) < 1e-12,
    }
    if not all(pair_guards.values()):
        raise RuntimeError("REFUSING: Order-1 pair-map guard failure: " + repr(pair_guards))

    identity_path = Path(row["poss_fits_path"])
    ident_fits = fits_identity(identity_path)

    identity_guards = {
        "fits_sha": ident_fits["sha256"].lower() == str(row["poss_fits_sha256"]).strip().lower(),
        "plate_id": ident_fits["plate_id"] == EXPECTED_PLATE_ID,
        "region": ident_fits["region"] == EXPECTED_REGION,
    }
    if not all(identity_guards.values()):
        raise RuntimeError("REFUSING: frozen POSS identity guard failure: " + repr(identity_guards))

    print("Frozen pair/FITS identity guards: PASS")
    print(f"  {EXPECTED_POSS} -> {EXPECTED_REGION} / {EXPECTED_PLATE_ID}")
    print(f"  FITS SHA: {ident_fits['sha256']}")
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # SkyView descriptor exact-region resolution.
    # ------------------------------------------------------------------
    print("[1/3] Resolving exact DSS1R descriptor entry for XE296 ...", flush=True)

    desc_resp = get_bytes(SKYVIEW_DSS1R_DESCRIPTOR, accept="application/xml,*/*")
    desc_raw = desc_resp["bytes"]

    if len(desc_raw) < 1000:
        raise RuntimeError("REFUSING: DSS1R descriptor suspiciously small")

    desc = parse_skyview_descriptor(desc_raw)
    if (desc.image_factory or "").strip() != "skyview.survey.DSSImageFactory":
        raise RuntimeError(
            f"REFUSING: unexpected DSS1R ImageFactory {desc.image_factory!r}"
        )

    wanted = EXPECTED_REGION.lower()
    matches = [
        x for x in desc.images
        if Path(x.path).name.lower() == wanted
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"REFUSING: expected exactly one descriptor image basename {wanted!r}; "
            f"got {len(matches)}"
        )

    entry = matches[0]
    raw_dir = raw_plate_directory(
        band=EXPECTED_BAND,
        region=EXPECTED_REGION,
        descriptor_entry=entry,
    )
    expected_raw_dir = "https://skyview.gsfc.nasa.gov/surveys/dss/xe296"
    if raw_dir.rstrip("/").lower() != expected_raw_dir.lower():
        raise RuntimeError(
            f"REFUSING: resolved raw dir {raw_dir!r} != {expected_raw_dir!r}"
        )

    DESC_COPY.write_bytes(desc_raw)

    descriptor_identity_sep = None
    if ident_fits["crval1"] is not None and ident_fits["crval2"] is not None:
        descriptor_identity_sep = angular_sep_arcsec(
            entry.ra_deg,
            entry.dec_deg,
            ident_fits["crval1"],
            ident_fits["crval2"],
        )

    print(f"  descriptor URL: {SKYVIEW_DSS1R_DESCRIPTOR}")
    print(f"  descriptor SHA256: {sha256_bytes(desc_raw)}")
    print(f"  exact region matches: {len(matches)}")
    print(
        f"  entry: path={entry.path!r} RA={entry.ra_deg:.9f} "
        f"Dec={entry.dec_deg:+.9f} epoch={entry.epoch}"
    )
    print(f"  resolved native raw dir: {raw_dir}")
    if descriptor_identity_sep is not None:
        print(
            "  descriptor -> frozen identity CRVAL separation: "
            f"{descriptor_identity_sep:.3f}\" (diagnostic only)"
        )
    print()

    # ------------------------------------------------------------------
    # Exact raw HHH metadata identity.
    # ------------------------------------------------------------------
    print("[2/3] Fetching exact XE296 .hhh metadata and checking physical plate identity ...", flush=True)

    hhh_url = f"{raw_dir}/{wanted}.hhh"
    hhh_resp = get_bytes(hhh_url, accept="application/octet-stream,*/*")
    hhh_raw = hhh_resp["bytes"]

    if len(hhh_raw) < 2880 or not hhh_raw.startswith(b"SIMPLE"):
        raise RuntimeError("REFUSING: raw XE296 .hhh is not FITS-style metadata")

    hident = hhh_identity(hhh_raw)
    hhh_guards = {
        "region": str(hident.get("region", "")).strip().upper() == EXPECTED_REGION,
        "plate_id_present": bool(str(hident.get("plate_id", "")).strip()),
        "plate_id": str(hident.get("plate_id", "")).strip().upper() == EXPECTED_PLATE_ID,
        "plate_ra_present": hident.get("plate_ra_deg") is not None,
        "plate_dec_present": hident.get("plate_dec_deg") is not None,
    }
    if not all(hhh_guards.values()):
        raise RuntimeError("REFUSING: XE296 HHH identity guard failure: " + repr(hhh_guards))

    HHH_COPY.write_bytes(hhh_raw)
    hhh_header = parse_hhh_header(hhh_raw)

    descriptor_hhh_sep = angular_sep_arcsec(
        entry.ra_deg,
        entry.dec_deg,
        float(hident["plate_ra_deg"]),
        float(hident["plate_dec_deg"]),
    )

    identity_hhh_sep = None
    if ident_fits["crval1"] is not None and ident_fits["crval2"] is not None:
        identity_hhh_sep = angular_sep_arcsec(
            ident_fits["crval1"],
            ident_fits["crval2"],
            float(hident["plate_ra_deg"]),
            float(hident["plate_dec_deg"]),
        )

    print(f"  HHH URL: {hhh_url}")
    print(f"  HHH SHA256: {sha256_bytes(hhh_raw)}")
    print(f"  REGION: {hident['region']} PASS")
    print(f"  PLATEID: {hident['plate_id']} PASS")
    print(f"  DATE-OBS: {hident.get('date_obs')}")
    print(
        f"  GSSS plate centre: RA={float(hident['plate_ra_deg']):.9f} "
        f"Dec={float(hident['plate_dec_deg']):+.9f}"
    )
    print(
        f"  descriptor <-> HHH centre separation: {descriptor_hhh_sep:.3f}\" "
        "(diagnostic only; never an identity veto)"
    )
    if identity_hhh_sep is not None:
        print(
            f"  frozen identity CRVAL <-> HHH plate-centre separation: "
            f"{identity_hhh_sep:.3f}\""
        )
    if hhh_header["parsed"]:
        print(f"  selected HHH header: {hhh_header['selected_header']}")
    else:
        print(f"  HHH full-header parse warning: {hhh_header['parse_error']}")
    print()

    # ------------------------------------------------------------------
    # DASCH metadata only.
    # ------------------------------------------------------------------
    print("[3/3] Querying ai43437 DR7 bin1 mosaic-package metadata ...", flush=True)

    dasch_resp = post_json(
        DASCH_API,
        {"plate_id": EXPECTED_DASCH, "binning": 1},
    )
    pkg = dasch_resp["json"]

    if not pkg.get("baseFitsUrl"):
        raise RuntimeError("REFUSING: DASCH mosaic package lacks baseFitsUrl")
    if pkg.get("metadata") is None:
        raise RuntimeError("REFUSING: DASCH mosaic package lacks metadata")

    metadata = pkg["metadata"]

    print(f"  HTTP status: {dasch_resp['status']}")
    print(f"  baseFitsUrl: {pkg.get('baseFitsUrl')}")
    print(f"  baseFitsSize: {pkg.get('baseFitsSize')}")
    print(f"  metadata keys: {sorted(metadata.keys()) if isinstance(metadata, dict) else type(metadata).__name__}")
    print()

    result = {
        "status": "COMPLETE",
        "analysis_kind": "order01_exact_native_source_and_dasch_metadata_v028",
        "pair_guards": pair_guards,
        "identity_guards": identity_guards,
        "frozen_pair_map_row": row,
        "frozen_poss_identity_fits": ident_fits,
        "skyview_descriptor": {
            "url": SKYVIEW_DSS1R_DESCRIPTOR,
            "http_status": desc_resp["status"],
            "final_url": desc_resp["final_url"],
            "content_type": desc_resp["content_type"],
            "sha256": sha256_bytes(desc_raw),
            "saved_copy": str(DESC_COPY),
            "short_name": desc.short_name,
            "file_prefix": desc.file_prefix,
            "image_factory": desc.image_factory,
            "image_count": len(desc.images),
            "exact_region_matches": len(matches),
            "selected_entry": {
                "path": entry.path,
                "ra_deg": entry.ra_deg,
                "dec_deg": entry.dec_deg,
                "epoch": entry.epoch,
            },
            "descriptor_identity_crval_sep_arcsec_diagnostic_only": descriptor_identity_sep,
        },
        "poss_native_source": {
            "band": EXPECTED_BAND,
            "region": EXPECTED_REGION,
            "plate_id": EXPECTED_PLATE_ID,
            "raw_plate_directory": raw_dir,
            "hhh_url": hhh_url,
            "hhh_http_status": hhh_resp["status"],
            "hhh_final_url": hhh_resp["final_url"],
            "hhh_content_type": hhh_resp["content_type"],
            "hhh_bytes": len(hhh_raw),
            "hhh_sha256": sha256_bytes(hhh_raw),
            "hhh_saved_copy": str(HHH_COPY),
            "hhh_identity": hident,
            "hhh_guards": hhh_guards,
            "hhh_header_parse": hhh_header,
            "descriptor_hhh_center_sep_arcsec_diagnostic_only": descriptor_hhh_sep,
            "identity_crval_hhh_center_sep_arcsec": identity_hhh_sep,
            "native_science_tile_requested": False,
        },
        "dasch_mosaic_package": {
            "api": DASCH_API,
            "request": {"plate_id": EXPECTED_DASCH, "binning": 1},
            "http_status": dasch_resp["status"],
            "final_url": dasch_resp["final_url"],
            "baseFitsUrl": pkg.get("baseFitsUrl"),
            "baseFitsSize": pkg.get("baseFitsSize"),
            "metadata": metadata,
            "science_mosaic_downloaded": False,
        },
        "provenance_notes": {
            "repair_only_native_map_used_for_resolution": False,
            "native_resolution_contract": (
                "VI/25-derived frozen region -> exact current DSS1R descriptor basename match -> "
                "poss1_skyview.raw_plate_directory keyword-only helper -> exact raw HHH REGION/PLATEID"
            ),
            "descriptor_hhh_center_gate": "diagnostic_only_never_terminal",
            "neighbouring_region_substitution": False,
        },
        "detector_rerun": False,
        "native_science_pixels_read": False,
        "dasch_science_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Build one parameterized whole-native execution worker using this resolved Order-1 input plus "
            "the frozen NATIVE_TILE_EXECUTION_POLICY_V028. Before detector execution, validate the full "
            "POSS GSSS dimensions/footprint and ai43437 direct-TPV containment. Do not inherit XE520-specific "
            "reference FITS or 14000x13999 dimension assumptions."
        ),
    }

    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUT)

    print("=" * 112)
    print("ORDER 01 EXACT NATIVE SOURCE + DASCH METADATA PREFLIGHT COMPLETE")
    print("=" * 112)
    print("Output:", OUT)
    print()
    print("No detector was rerun.")
    print("No DSS native science tile was requested.")
    print("No DASCH science mosaic was downloaded.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
