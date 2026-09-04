#!/usr/bin/env python3
"""
v084a — display-only repair for the blinded Pair-17 manual review packet.

Purpose:
  * preserve the exact frozen B001..B032 blind ordering from v084;
  * preserve all raw pixels and frozen v083b rendering parameters;
  * add UNMARKED zoom/high-pass images so the crosshair cannot obscure morphology;
  * retain the original marked zoom as a locator view;
  * enlarge tiny images in-browser using nearest-neighbour rendering;
  * emit no unblinding key and no candidate identities/roles in the blind HTML.

No network. No FITS reads. No new science measurements. No disposition changes.
"""

from pathlib import Path
import csv, hashlib, html, json, math, shutil, struct, zlib
import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parents[1]

V083 = ROOT / "results" / "pair17_standardized_manual_dossiers_v083"
V083_MANIFEST = V083 / "pair17_manual_dossier_panel_manifest_v083.csv"
V083_BANK = V083 / "pair17_v083b_bank_manifest.json"

V084 = ROOT / "results" / "pair17_blinded_manual_review_packet_v084"
V084_REPORT = V084 / "pair17_blinded_manual_review_packet_v084.json"
V084_BANK = V084 / "pair17_v084_bank_manifest.json"
V084_RUNNER = ROOT / "tools" / "run_pair17_blinded_manual_review_packet_v084.py"

EXPECTED = {
    V083_BANK:
        "6f0f749852db04fc5d1a9b8bde773a2f0dc273ee59d8e0832b72e3743e9b658b",
    V084_BANK:
        "484b097bb0914945af502187240ffb1620324b62c9ee6b97e520bf46fdd01898",
    V084_RUNNER:
        "eeb3165019173a42f001936c0a162ca5e9a3e60a28eb71569dd9bb37d02e3c67",
}

SALT = "pair17-v084-standardized-blind-manual-review-v001"
EXPECTED_PANELS = 32

OUT = ROOT / "results" / "pair17_blinded_manual_review_packet_v084a"
ASSETS = OUT / "blind_assets"
OUT_HTML = OUT / "blind_review.html"
OUT_SHEET = OUT / "blind_review_sheet.csv"
OUT_JSON = OUT / "pair17_blinded_manual_review_packet_v084a.json"

PLO = 1.0
PHI = 99.5
HP_CLIP_SIGMA = 5.0
BACKGROUND_SIGMA = 8.0


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for b in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if fields:
            w.writeheader()
            w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def blind_sort_key(r):
    s = "|".join([
        SALT,
        str(r.get("raw_match_row") or ""),
        str(r.get("panel_role") or ""),
        str(r.get("physical_plate_id") or ""),
        str(r.get("scan_id") or ""),
        str(r.get("filename_scan") or ""),
    ])
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _png_chunk(kind, data):
    payload = kind + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", zlib.crc32(payload) & 0xffffffff)
    )


def write_gray_png(path, image):
    arr = np.asarray(image, dtype=np.uint8)
    if arr.ndim != 2:
        raise RuntimeError("PNG writer expects a 2-D grayscale image")

    h, w = arr.shape
    raw = b"".join(
        b"\x00" + arr[y, :].tobytes(order="C")
        for y in range(h)
    )

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0),
    ))
    png.extend(_png_chunk(b"IDAT", zlib.compress(raw, 9)))
    png.extend(_png_chunk(b"IEND", b""))

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(bytes(png))
    tmp.replace(path)


def robust_sigma(arr):
    q = np.asarray(arr, dtype=float)
    q = q[np.isfinite(q)]
    if q.size == 0:
        return None
    med = float(np.median(q))
    mad = float(np.median(np.abs(q - med)))
    sig = 1.4826 * mad
    return sig if math.isfinite(sig) and sig > 0 else None


def normalize_raw(arr):
    q = np.asarray(arr, dtype=float)
    finite = q[np.isfinite(q)]
    if finite.size < 10:
        raise RuntimeError("Insufficient finite pixels for unmarked display")

    lo, hi = np.percentile(finite, [PLO, PHI])

    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        lo, hi = float(np.min(finite)), float(np.max(finite))

    if hi <= lo:
        hi = lo + 1.0

    z = np.clip((q - lo) / (hi - lo), 0, 1)
    z[~np.isfinite(z)] = 0
    return np.rint(z * 255.0).astype(np.uint8)


def normalize_highpass(arr):
    q = np.asarray(arr, dtype=float)
    finite = np.isfinite(q)
    fill = float(np.nanmedian(q[finite])) if np.any(finite) else 0.0

    work = np.where(finite, q, fill)
    hp = work - gaussian_filter(work, float(BACKGROUND_SIGMA))

    sig = robust_sigma(hp)
    clip = (
        HP_CLIP_SIGMA * sig
        if sig is not None
        else max(1.0, float(np.std(hp)))
    )

    z = np.clip((hp + clip) / (2.0 * clip), 0, 1)
    z[~np.isfinite(z)] = 0.5
    return np.rint(z * 255.0).astype(np.uint8)


def main():
    print("=" * 120)
    print("PAIR 17 — BLINDED REVIEW DISPLAY REPAIR v084a")
    print("=" * 120)
    print("Network calls:              0")
    print("FITS reads:                 0")
    print("Science measurements:       0")
    print("Blind ordering changed:     NO")
    print("Unblinding key emitted:     NO")
    print("Disposition changes:        NONE")
    print()

    for p, expected in EXPECTED.items():
        if not p.is_file():
            raise RuntimeError(f"Missing frozen v084a prerequisite: {p}")

        actual = sha(p)
        if actual != expected:
            raise RuntimeError(
                f"Frozen v084a prerequisite changed:\n"
                f"{p}\nexpected {expected}\nactual   {actual}"
            )

        print("HASH PASS:", p.relative_to(ROOT))

    report84 = json.loads(V084_REPORT.read_text(encoding="utf-8"))
    if report84.get("status") != "COMPLETE":
        raise RuntimeError("v084 report is not COMPLETE")

    if report84["population"] != {"candidates": 6, "panels": 32}:
        raise RuntimeError("v084 population changed")

    if report84["blinding"]["unblinding_key_written"] is not False:
        raise RuntimeError("v084 unexpectedly contains unblinding output")

    rows = read_csv(V083_MANIFEST)

    if len(rows) != EXPECTED_PANELS:
        raise RuntimeError(f"Expected 32 v083b panels; got {len(rows)}")

    ordered = sorted(rows, key=blind_sort_key)

    if OUT.exists():
        shutil.rmtree(OUT)
    ASSETS.mkdir(parents=True, exist_ok=True)

    sheet = []
    cards = []
    asset_records = []

    for i, r in enumerate(ordered, 1):
        code = f"B{i:03d}"

        # Existing marked locator views are reused exactly from v084.
        marked_context = V084 / "blind_assets" / f"{code}_context.png"
        marked_zoom = V084 / "blind_assets" / f"{code}_zoom.png"
        marked_hp = V084 / "blind_assets" / f"{code}_highpass.png"

        for p in (marked_context, marked_zoom, marked_hp):
            if not p.is_file():
                raise RuntimeError(f"Missing frozen v084 blind asset: {p}")

        # Recreate UNMARKED views from the already-banked v083 raw NPYs.
        # We deliberately do not reveal which source panel produced this B-code.
        zoom_npy = V083 / str(r["zoom_npy"]).replace("\\", "/")

        if not zoom_npy.is_file():
            raise RuntimeError(f"Missing frozen v083 zoom NPY: {zoom_npy}")

        zoom = np.load(zoom_npy, mmap_mode="r")

        if zoom.ndim != 2:
            raise RuntimeError("Frozen zoom NPY is not 2-D")

        dst_context = ASSETS / f"{code}_context_locator.png"
        dst_zoom_locator = ASSETS / f"{code}_zoom_locator.png"
        dst_zoom_unmarked = ASSETS / f"{code}_zoom_unmarked.png"
        dst_hp_unmarked = ASSETS / f"{code}_highpass_unmarked.png"

        shutil.copy2(marked_context, dst_context)
        shutil.copy2(marked_zoom, dst_zoom_locator)

        write_gray_png(dst_zoom_unmarked, normalize_raw(zoom))
        write_gray_png(dst_hp_unmarked, normalize_highpass(zoom))

        asset_records.append({
            "blind_code": code,
            "context_locator_sha256": sha(dst_context),
            "zoom_locator_sha256": sha(dst_zoom_locator),
            "zoom_unmarked_sha256": sha(dst_zoom_unmarked),
            "highpass_unmarked_sha256": sha(dst_hp_unmarked),
            "zoom_height_px": int(zoom.shape[0]),
            "zoom_width_px": int(zoom.shape[1]),
        })

        sheet.append({
            "blind_code": code,
            "feature_at_crosshair": "",
            "morphology": "",
            "local_context": "",
            "confidence_1_to_5": "",
            "notes": "",
        })

        cards.append(f"""
        <section class="card">
          <h2>{code}</h2>
          <div class="grid">
            <figure>
              <img class="pix" src="blind_assets/{code}_context_locator.png">
              <figcaption>Context — locator crosshair</figcaption>
            </figure>
            <figure>
              <img class="pix" src="blind_assets/{code}_zoom_locator.png">
              <figcaption>Zoom — locator crosshair</figcaption>
            </figure>
            <figure>
              <img class="pix" src="blind_assets/{code}_zoom_unmarked.png">
              <figcaption>Zoom — UNMARKED</figcaption>
            </figure>
            <figure>
              <img class="pix" src="blind_assets/{code}_highpass_unmarked.png">
              <figcaption>High-pass — UNMARKED</figcaption>
            </figure>
          </div>
          <p class="instruction">
            Use the marked views only to locate the centre. Judge the photographic
            feature in the adjacent <b>UNMARKED</b> views.
          </p>
        </section>
        """)

    write_csv(
        OUT_SHEET,
        sheet,
        fields=[
            "blind_code",
            "feature_at_crosshair",
            "morphology",
            "local_context",
            "confidence_1_to_5",
            "notes",
        ],
    )

    OUT_HTML.write_text(
        """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Pair 17 v084a blinded review</title>
<style>
body{
  font-family:Arial,sans-serif;
  max-width:1600px;
  margin:20px auto;
  padding:0 20px;
}
.card{
  border:1px solid #aaa;
  padding:14px;
  margin:24px 0;
}
.grid{
  display:grid;
  grid-template-columns:repeat(2,minmax(320px,1fr));
  gap:14px;
}
figure{
  margin:0;
  border:1px solid #ddd;
  padding:8px;
  background:#f7f7f7;
}
img.pix{
  width:100%;
  height:auto;
  image-rendering:pixelated;
  image-rendering:crisp-edges;
  background:#888;
}
figcaption{
  text-align:center;
  font-weight:600;
  margin-top:6px;
}
.instruction{
  margin-bottom:0;
}
code{
  background:#eee;
  padding:2px 4px;
}
@media(max-width:850px){
  .grid{grid-template-columns:1fr;}
}
</style>
</head>
<body>
<h1>Pair 17 — blinded manual morphology review v084a</h1>
<p>
All 32 frozen blind panels are retained in the exact v084 blind order.
Candidate identity, role, observatory, chronology and mechanical state remain hidden.
</p>
<p>
For each panel: first use the locator image to find the centre, then judge the
<b>unmarked zoom and unmarked high-pass</b>. Tiny native cutouts are enlarged by
the browser using nearest-neighbour/pixel-preserving display.
</p>
<p>Allowed score-sheet values:</p>
<ul>
<li><b>feature_at_crosshair</b>: ABSENT / WEAK_OR_AMBIGUOUS / DEFINITE</li>
<li><b>morphology</b>: STELLAR_COMPACT / NONSTELLAR_ARTIFACT / EXTENDED_OR_BLENDED / AMBIGUOUS</li>
<li><b>local_context</b>: CLEAN / CROWDED / DEFECT_AFFECTED / EDGE_OR_CLIPPED / AMBIGUOUS</li>
<li><b>confidence_1_to_5</b>: 1–5</li>
</ul>
""" + "\n".join(cards) + """
</body>
</html>
""",
        encoding="utf-8",
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_blinded_manual_review_display_repair_v084a",
        "parent_v084_bank_manifest_sha256":
            "484b097bb0914945af502187240ffb1620324b62c9ee6b97e520bf46fdd01898",
        "parent_v084_runner_sha256":
            "eeb3165019173a42f001936c0a162ca5e9a3e60a28eb71569dd9bb37d02e3c67",
        "population": {
            "blind_panels": 32,
            "blind_order_changed": False,
        },
        "display_repair": {
            "marked_locator_retained": True,
            "unmarked_zoom_added": True,
            "unmarked_highpass_added": True,
            "nearest_neighbor_browser_scaling": True,
            "raw_pixels_changed": False,
            "stretch_rule_changed": False,
            "highpass_rule_changed": False,
        },
        "blinding": {
            "unblinding_key_written": False,
            "candidate_identity_in_blind_html": False,
            "role_in_blind_html": False,
        },
        "guards": {
            "network_calls": 0,
            "fits_reads": 0,
            "new_science_measurements": 0,
            "candidate_disposition_changes": False,
            "threshold_retuning": False,
        },
        "assets": asset_records,
        "outputs": {
            "blind_review_html": str(OUT_HTML.relative_to(ROOT)).replace("\\", "/"),
            "blind_review_sheet": str(OUT_SHEET.relative_to(ROOT)).replace("\\", "/"),
        },
    }

    write_json(OUT_JSON, report)

    print()
    print("=" * 120)
    print("v084a BLINDED DISPLAY REPAIR COMPLETE")
    print("=" * 120)
    print("Blind panels:", 32)
    print("Blind order changed: NO")
    print("Unmarked zooms:", 32)
    print("Unmarked high-pass:", 32)
    print("Unblinding key written: NO")
    print("Open:", OUT_HTML)
    print("Score sheet:", OUT_SHEET)
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
