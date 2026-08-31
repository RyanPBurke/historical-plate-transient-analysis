from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import re
import urllib.request

from astropy.io import fits
from astropy.wcs import WCS

ROOT = Path.cwd()

PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
NATIVE_MAP = ROOT / "research" / "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.csv"
WHOLE61 = ROOT / "tools" / "run_order61_whole_native_v028.py"

ORDER = 1
EXPECTED_POSS = "POSS-I:413:E:rec297"
EXPECTED_REGION = "XE296"
EXPECTED_DASCH = "ai43437"
EXPECTED_OVERLAP_S = 3480.0
EXPECTED_STATE = "POSS_PIXEL_READY_PARTNER_PIXEL_WORK_PENDING"

DASCH_MOSAIC_API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"

OUT = ROOT / "results" / "order01_native_preflight_v028" / "order01_native_preflight_v028.json"


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def select_order_row(rows):
    matches = []
    for r in rows:
        try:
            order = int(float(str(r.get("canonical_order", "")).strip()))
        except Exception:
            continue
        if order == ORDER:
            matches.append(r)
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one canonical order {ORDER}; got {len(matches)}")
    return matches[0]


def row_contains(row, needle):
    n = str(needle).strip().lower()
    return any(n in str(v).strip().lower() for v in row.values() if v is not None)


def native_matches(rows):
    exact = [r for r in rows if row_contains(r, EXPECTED_POSS)]
    if exact:
        return exact, "exact_exposure_id"
    region = [r for r in rows if row_contains(r, EXPECTED_REGION)]
    return region, "region_fallback"


def candidate_paths_from_row(row):
    out = []
    for k, v in row.items():
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        # Only treat things that already look path-like as candidate paths.
        if (
            "\\" in s
            or "/" in s
            or re.search(r"\.(fits?|hhh|gz|npy|json|csv)$", s, re.I)
        ):
            p = Path(s)
            if not p.is_absolute():
                p = ROOT / p
            out.append((k, p))
    return out


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "historical-transient-pipeline/0.2.8-order01-native-preflight",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read()
        status = getattr(resp, "status", None)
        final_url = resp.geturl()
    return json.loads(raw.decode("utf-8")), status, final_url


def recursive_find(obj, wanted):
    hits = []

    def walk(x, path="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}"
                if norm(k) in wanted:
                    hits.append({"path": p, "value": v})
                walk(v, p)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")

    walk(obj)
    return hits


def fits_preflight(path: Path):
    with fits.open(path, memmap=False) as hdul:
        hdu = hdul[0]
        hdr = hdu.header.copy()
        shape = None if hdu.data is None else tuple(int(x) for x in hdu.data.shape)

    w = WCS(hdr).celestial
    keys = [
        "PLATEID", "REGION", "DATE-OBS", "DATEOBS", "OBJECT",
        "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
        "CTYPE1", "CTYPE2", "CDELT1", "CDELT2",
        "CNPIX1", "CNPIX2", "PLTSCALE",
        "NAXIS1", "NAXIS2",
    ]
    selected = {k: hdr.get(k) for k in keys if k in hdr}

    return {
        "shape": shape,
        "dtype": None if hdu.data is None else str(hdu.data.dtype),
        "has_celestial_wcs": bool(w.has_celestial),
        "selected_header": selected,
    }


def scan_hardcodes(path: Path):
    text = path.read_text(encoding="utf-8")
    patterns = [
        r"\bai44092\b",
        r"\bXE520\b",
        r"POSS-I:875:E:rec521",
        r"\border61\b",
        r"\bORDER\s*=\s*61\b",
        r"\b61\b",
    ]
    rows = text.splitlines()
    hits = []
    for i, line in enumerate(rows, 1):
        if any(re.search(p, line, re.I) for p in patterns):
            hits.append({"line": i, "text": line.rstrip()})
    return {
        "path": str(path),
        "line_count": len(rows),
        "order61_specific_hit_count": len(hits),
        "hits": hits[:200],
        "hits_truncated": len(hits) > 200,
    }


def main():
    print("=" * 110)
    print("ORDER 01 — NATIVE POSS/DASCH READ-ONLY EXECUTION PREFLIGHT v028")
    print("=" * 110)
    print("No detector. No native science pixels. No DASCH mosaic download.")
    print()

    for p in (PAIR_MAP, NATIVE_MAP, WHOLE61):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pair_rows = read_csv(PAIR_MAP)
    if len(pair_rows) != 47:
        raise RuntimeError(f"REFUSING: expected frozen 47-row POSS pair map, got {len(pair_rows)}")

    row = select_order_row(pair_rows)

    poss = str(row.get("poss_exposure_id", "")).strip()
    region = str(row.get("poss_region", "")).strip()
    dasch = str(row.get("partner_dasch_plate_id", "")).strip()
    state = str(row.get("pair_execution_state", "")).strip()
    overlap_s = float(row.get("actual_overlap_s", "nan"))

    guards = {
        "canonical_order_1": int(float(row["canonical_order"])) == 1,
        "poss_exposure": poss == EXPECTED_POSS,
        "poss_region": region == EXPECTED_REGION,
        "dasch_plate": dasch.lower() == EXPECTED_DASCH,
        "actual_overlap_s": abs(overlap_s - EXPECTED_OVERLAP_S) < 1e-6,
        "execution_state": state == EXPECTED_STATE,
        "true_wcs_intersection": str(row.get("true_wcs_intersection", "")).strip().lower() == "true",
        "true_wcs_overlap_fraction": abs(float(row.get("true_wcs_overlap_fraction", "nan")) - 1.0) < 1e-12,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: frozen Order-01 pair-map guard failure: " + repr(guards))

    print("Frozen Order-01 pair-map guards: PASS")
    print(f"  POSS:    {poss} -> {region}")
    print(f"  DASCH:   {dasch}")
    print(f"  overlap: {overlap_s:.3f} s ({overlap_s/60:.3f} min)")
    print()

    # ------------------------------------------------------------------
    # Frozen POSS FITS identity / WCS reference.
    # ------------------------------------------------------------------
    print("[1/4] Verifying frozen POSS FITS identity/WCS reference ...", flush=True)

    poss_fits = Path(str(row["poss_fits_path"]).strip())
    if not poss_fits.is_file():
        raise RuntimeError(f"Missing frozen POSS FITS path: {poss_fits}")

    actual_fits_sha = sha256_file(poss_fits)
    expected_fits_sha = str(row["poss_fits_sha256"]).strip().lower()
    if actual_fits_sha.lower() != expected_fits_sha:
        raise RuntimeError(
            "REFUSING: frozen POSS FITS SHA mismatch: "
            f"expected={expected_fits_sha} actual={actual_fits_sha}"
        )

    fpre = fits_preflight(poss_fits)
    if not fpre["has_celestial_wcs"]:
        raise RuntimeError("REFUSING: frozen POSS FITS has no celestial WCS")

    print(f"  path: {poss_fits}")
    print(f"  SHA256: {actual_fits_sha} PASS")
    print(f"  shape/dtype: {fpre['shape']} / {fpre['dtype']}")
    print(f"  celestial WCS: PASS")
    print(f"  selected header: {fpre['selected_header']}")
    print()

    # ------------------------------------------------------------------
    # Native source map lookup. We intentionally do not assume its schema.
    # ------------------------------------------------------------------
    print("[2/4] Resolving frozen native POSS source-map entry ...", flush=True)

    native_rows = read_csv(NATIVE_MAP)
    nmatches, nmode = native_matches(native_rows)
    if len(nmatches) != 1:
        raise RuntimeError(
            f"REFUSING: expected exactly one native-map match for {EXPECTED_POSS}/{EXPECTED_REGION}; "
            f"mode={nmode} matches={len(nmatches)}"
        )
    nrow = nmatches[0]

    path_audit = []
    for field, p in candidate_paths_from_row(nrow):
        exists = p.exists()
        entry = {
            "field": field,
            "value": str(nrow[field]),
            "resolved_path": str(p),
            "exists": bool(exists),
            "is_file": bool(p.is_file()) if exists else False,
        }
        if p.is_file() and p.stat().st_size <= 100 * 1024 * 1024:
            try:
                entry["sha256"] = sha256_file(p)
                entry["size_bytes"] = p.stat().st_size
            except Exception as exc:
                entry["sha_error"] = repr(exc)
        path_audit.append(entry)

    print(f"  native map rows: {len(native_rows)}")
    print(f"  match mode: {nmode}")
    print("  matched row:")
    for k, v in nrow.items():
        if str(v).strip():
            print(f"    {k}: {v}")
    if path_audit:
        print("  path-like fields:")
        for p in path_audit:
            print(f"    {p['field']}: exists={p['exists']} file={p['is_file']} -> {p['resolved_path']}")
    print()

    # ------------------------------------------------------------------
    # Current official DR7 mosaic package metadata only — no FITS bytes.
    # ------------------------------------------------------------------
    print("[3/4] Querying official DASCH DR7 full-resolution mosaic metadata ...", flush=True)

    pkg, http_status, final_url = post_json(
        DASCH_MOSAIC_API,
        {"plate_id": EXPECTED_DASCH, "binning": 1},
    )

    base_url = pkg.get("baseFitsUrl")
    base_size = pkg.get("baseFitsSize")
    metadata = pkg.get("metadata")

    if not base_url or metadata is None:
        raise RuntimeError(
            "REFUSING: DR7 mosaic_package response lacks baseFitsUrl and/or metadata"
        )

    interesting = recursive_find(
        pkg,
        {
            "plateid", "plate_id", "shape", "width", "height", "naxis1", "naxis2",
            "rotk", "binning", "astrometry", "b01headergz", "location",
        },
    )

    print(f"  HTTP status: {http_status}")
    print(f"  final URL: {final_url}")
    print(f"  baseFitsUrl: {base_url}")
    print(f"  baseFitsSize: {base_size}")
    print(f"  metadata type: {type(metadata).__name__}")
    print(f"  selected recursive metadata hits: {len(interesting)}")
    for h in interesting[:40]:
        val = h["value"]
        if isinstance(val, (dict, list)):
            val = f"<{type(val).__name__} len={len(val)}>"
        print(f"    {h['path']}: {val}")
    if len(interesting) > 40:
        print(f"    ... {len(interesting)-40} more metadata hits retained in JSON")
    print()

    # ------------------------------------------------------------------
    # Generalisation audit: identify Order-61-specific constants/hardcodes.
    # ------------------------------------------------------------------
    print("[4/4] Auditing Order-61 whole-native worker for order-specific hardcodes ...", flush=True)

    hardcodes = scan_hardcodes(WHOLE61)
    print(f"  source: {WHOLE61}")
    print(f"  source lines: {hardcodes['line_count']}")
    print(f"  order-specific candidate lines: {hardcodes['order61_specific_hit_count']}")
    for h in hardcodes["hits"][:30]:
        print(f"    L{h['line']}: {h['text']}")
    if hardcodes["order61_specific_hit_count"] > 30:
        print("    ... remainder retained in JSON")
    print()

    result = {
        "status": "COMPLETE",
        "analysis_kind": "order01_native_execution_preflight_v028",
        "guards": guards,
        "frozen_pair_map_row": row,
        "poss_fits": {
            "path": str(poss_fits),
            "sha256": actual_fits_sha,
            **fpre,
        },
        "native_source_map": {
            "path": str(NATIVE_MAP),
            "match_mode": nmode,
            "matched_row": nrow,
            "path_audit": path_audit,
        },
        "dasch_mosaic_package": {
            "api": DASCH_MOSAIC_API,
            "request": {"plate_id": EXPECTED_DASCH, "binning": 1},
            "http_status": http_status,
            "final_url": final_url,
            "baseFitsUrl": base_url,
            "baseFitsSize": base_size,
            "metadata": metadata,
            "interesting_metadata_hits": interesting,
            "science_pixels_downloaded": False,
        },
        "order61_generalisation_audit": hardcodes,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "If all guards pass, create an Order-01 execution worker by parameterising the "
            "Order-61 whole-native path over pair-map/native-map/DR7 metadata while preserving "
            "the frozen native tile policy and detector unchanged. Before science execution, "
            "run exact POSS full-plate geometry and DASCH TPV footprint containment checks."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(OUT)

    print("=" * 110)
    print("ORDER 01 NATIVE EXECUTION PREFLIGHT COMPLETE")
    print("=" * 110)
    print("Output:", OUT)
    print()
    print("No detector was rerun.")
    print("No native science image pixel was read.")
    print("No DASCH FITS mosaic was downloaded.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
