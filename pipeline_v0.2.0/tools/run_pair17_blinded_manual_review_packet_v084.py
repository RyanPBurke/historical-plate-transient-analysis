#!/usr/bin/env python3
from pathlib import Path
import csv, hashlib, html, json, math, shutil, struct
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_blinded_manual_review_packet_contract_v084.json"
)
EXPECTED_CONTRACT_SHA = "5b4fd85a1132972ca52bc552be7e7b281edf6263285a48cdc5d5b10f6ee9bbae"

V083 = ROOT / "results" / "pair17_standardized_manual_dossiers_v083"
MANIFEST = V083 / "pair17_manual_dossier_panel_manifest_v083.csv"
BANK = V083 / "pair17_v083b_bank_manifest.json"
V083_CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_standardized_manual_dossiers_contract_v083.json"
)
V083B = ROOT / "tools" / "run_pair17_standardized_manual_dossiers_v083b.py"

EXPECTED = {
    V083_CONTRACT:
        "ac6ed350c0f55e1a4d3010ecadcf20c963baa185718d860fa6a0f38318ed669f",
    V083B:
        "ad0a02aac10c44c6188245969db6b1917fb56e311a5464140d8695203fb4bc7a",
    BANK:
        "6f0f749852db04fc5d1a9b8bde773a2f0dc273ee59d8e0832b72e3743e9b658b",
}

OUT = ROOT / "results" / "pair17_blinded_manual_review_packet_v084"
ASSETS = OUT / "blind_assets"
OUT_HTML = OUT / "blind_review.html"
OUT_SHEET = OUT / "blind_review_sheet.csv"
OUT_AUDIT = OUT / "panel_integrity_audit_v084.csv"
OUT_JSON = OUT / "pair17_blinded_manual_review_packet_v084.json"

SALT = "pair17-v084-standardized-blind-manual-review-v001"
EXPECTED_PANELS = 32
EXPECTED_IDS = {"293118","293470","293841","294052","294130","294179"}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for b in iter(lambda: fh.read(8*1024*1024), b""):
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


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def png_size(path):
    b = Path(path).read_bytes()[:24]
    if len(b) < 24 or b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
        raise RuntimeError(f"Invalid PNG: {path}")
    w, h = struct.unpack(">II", b[16:24])
    return int(w), int(h)


def expected_side(width_arcsec, scale_arcsec):
    half = max(8, int(math.ceil((float(width_arcsec) / float(scale_arcsec)) / 2.0)))
    return 2*half + 1


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


def main():
    print("="*120)
    print("PAIR 17 — BLINDED MANUAL REVIEW PACKET v084")
    print("="*120)
    print("Network calls:              0")
    print("New FITS pixel reads:       0")
    print("Panel subsetting:           NO")
    print("Unblinding key emitted:     NO")
    print("Disposition changes:        NONE")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v084 contract SHA mismatch")

    for p,e in EXPECTED.items():
        if not p.is_file():
            raise RuntimeError(f"Missing frozen v084 prerequisite: {p}")
        a = sha(p)
        if a != e:
            raise RuntimeError(
                f"Frozen v084 prerequisite changed:\n{p}\nexpected {e}\nactual   {a}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    rows = read_csv(MANIFEST)

    if len(rows) != EXPECTED_PANELS:
        raise RuntimeError(f"Expected 32 v083b panel rows; got {len(rows)}")

    ids = {str(r.get("raw_match_row") or "") for r in rows}
    if ids != EXPECTED_IDS:
        raise RuntimeError(f"v083b candidate population changed: {sorted(ids)}")

    bank = json.loads(BANK.read_text(encoding="utf-8"))
    if bank.get("status") != "COMPLETE":
        raise RuntimeError("v083b bank manifest is not COMPLETE")

    audit = []

    for r in rows:
        scale = num(r.get("pixel_scale_arcsec"))
        if scale is None or scale <= 0:
            raise RuntimeError("Panel missing finite pixel scale")

        context_npy = V083 / str(r["context_npy"]).replace("\\","/")
        zoom_npy = V083 / str(r["zoom_npy"]).replace("\\","/")
        context_png = V083 / str(r["context_png"]).replace("\\","/")
        zoom_png = V083 / str(r["zoom_png"]).replace("\\","/")
        hp_png = V083 / str(r["zoom_highpass_png"]).replace("\\","/")

        for p in (context_npy,zoom_npy,context_png,zoom_png,hp_png):
            if not p.is_file():
                raise RuntimeError(f"Missing banked v083b panel asset: {p}")

        c = np.load(context_npy, mmap_mode="r")
        z = np.load(zoom_npy, mmap_mode="r")

        if c.ndim != 2 or z.ndim != 2:
            raise RuntimeError("Banked panel NPY is not 2-D")

        cpw,cph = png_size(context_png)
        zpw,zph = png_size(zoom_png)
        hpw,hph = png_size(hp_png)

        if (cpw,cph) != (c.shape[1],c.shape[0]):
            raise RuntimeError(f"Context PNG/NPY shape mismatch: {context_png}")
        if (zpw,zph) != (z.shape[1],z.shape[0]) or (hpw,hph) != (z.shape[1],z.shape[0]):
            raise RuntimeError(f"Zoom PNG/NPY shape mismatch: {zoom_png}")

        exp_c = expected_side(240.0, scale)
        exp_z = expected_side(60.0, scale)

        clipped_c = c.shape[0] < exp_c or c.shape[1] < exp_c
        clipped_z = z.shape[0] < exp_z or z.shape[1] < exp_z

        audit.append({
            "raw_match_row": r["raw_match_row"],
            "panel_role": r["panel_role"],
            "physical_plate_id": r["physical_plate_id"],
            "scan_id": r["scan_id"],
            "pixel_scale_arcsec": scale,
            "context_expected_side_px": exp_c,
            "context_actual_height_px": c.shape[0],
            "context_actual_width_px": c.shape[1],
            "context_edge_clipped": clipped_c,
            "zoom_expected_side_px": exp_z,
            "zoom_actual_height_px": z.shape[0],
            "zoom_actual_width_px": z.shape[1],
            "zoom_edge_clipped": clipped_z,
            "integrity_flag": (
                "EDGE_CLIPPED_RENDER" if (clipped_c or clipped_z) else "FULL_FROZEN_RENDER"
            )
        })

    write_csv(OUT_AUDIT, audit)

    # Deterministic blind ordering. Mapping is deliberately not emitted.
    ordered = sorted(rows, key=blind_sort_key)

    if ASSETS.exists():
        shutil.rmtree(ASSETS)
    ASSETS.mkdir(parents=True, exist_ok=True)

    sheet = []
    cards = []

    for i,r in enumerate(ordered,1):
        code = f"B{i:03d}"

        src_context = V083 / str(r["context_png"]).replace("\\","/")
        src_zoom = V083 / str(r["zoom_png"]).replace("\\","/")
        src_hp = V083 / str(r["zoom_highpass_png"]).replace("\\","/")

        dst_context = ASSETS / f"{code}_context.png"
        dst_zoom = ASSETS / f"{code}_zoom.png"
        dst_hp = ASSETS / f"{code}_highpass.png"

        shutil.copy2(src_context,dst_context)
        shutil.copy2(src_zoom,dst_zoom)
        shutil.copy2(src_hp,dst_hp)

        sheet.append({
            "blind_code": code,
            "feature_at_crosshair": "",
            "morphology": "",
            "local_context": "",
            "confidence_1_to_5": "",
            "notes": "",
        })

        cards.append(
            f"""
            <section class="card">
              <h2>{code}</h2>
              <div class="imgs">
                <figure><img src="blind_assets/{code}_context.png"><figcaption>Context</figcaption></figure>
                <figure><img src="blind_assets/{code}_zoom.png"><figcaption>Zoom</figcaption></figure>
                <figure><img src="blind_assets/{code}_highpass.png"><figcaption>High-pass</figcaption></figure>
              </div>
              <p><strong>Score in blind_review_sheet.csv:</strong>
              feature at crosshair; morphology; local context; confidence 1–5; notes.</p>
            </section>
            """
        )

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
<html><head><meta charset="utf-8"><title>Pair 17 v084 blinded review</title>
<style>
body{font-family:Arial,sans-serif;max-width:1500px;margin:20px auto;padding:0 20px}
.card{border:1px solid #aaa;padding:12px;margin:20px 0}
.imgs{display:flex;gap:10px;flex-wrap:wrap}
figure{margin:0;width:31%;min-width:300px}
img{width:100%;height:auto;image-rendering:auto}
figcaption{text-align:center;font-size:.9em}
code{background:#eee;padding:2px 4px}
</style></head><body>
<h1>Pair 17 — blinded manual morphology review v084</h1>
<p>All 32 frozen v083b panels are included. Candidate identity, role, observatory,
chronology and mechanical state are hidden. Review every panel before unblinding.</p>
<p>Allowed values:</p>
<ul>
<li><b>feature_at_crosshair</b>: ABSENT / WEAK_OR_AMBIGUOUS / DEFINITE</li>
<li><b>morphology</b>: STELLAR_COMPACT / NONSTELLAR_ARTIFACT / EXTENDED_OR_BLENDED / AMBIGUOUS</li>
<li><b>local_context</b>: CLEAN / CROWDED / DEFECT_AFFECTED / EDGE_OR_CLIPPED / AMBIGUOUS</li>
<li><b>confidence_1_to_5</b>: 1–5</li>
</ul>
""" + "\n".join(cards) + """
</body></html>
""",
        encoding="utf-8",
    )

    clipped = sum(x["integrity_flag"] == "EDGE_CLIPPED_RENDER" for x in audit)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_blinded_manual_review_packet_v084",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "population": {"candidates": 6, "panels": 32},
        "integrity": {
            "panels_audited": 32,
            "edge_clipped_render_panels": clipped,
            "full_frozen_render_panels": 32-clipped,
        },
        "blinding": {
            "blind_panels": 32,
            "unblinding_key_written": False,
            "blinding_salt_sha256": hashlib.sha256(SALT.encode()).hexdigest(),
        },
        "guards": {
            "network_calls": 0,
            "new_fits_pixel_reads": 0,
            "new_science_measurements": 0,
            "candidate_disposition_changes": False,
            "threshold_retuning": False,
        },
        "outputs": {
            "blind_review_html": str(OUT_HTML.relative_to(ROOT)).replace("\\","/"),
            "blind_review_sheet": str(OUT_SHEET.relative_to(ROOT)).replace("\\","/"),
            "integrity_audit": str(OUT_AUDIT.relative_to(ROOT)).replace("\\","/"),
        }
    }
    write_json(OUT_JSON, report)

    print()
    print("="*120)
    print("v084 BLINDED MANUAL REVIEW PACKET COMPLETE")
    print("="*120)
    print("Panels audited:", 32)
    print("Full frozen renders:", 32-clipped)
    print("Edge-clipped renders:", clipped)
    print("Blinded panels:", 32)
    print("Unblinding key written: NO")
    print("Open:", OUT_HTML)
    print("Score sheet:", OUT_SHEET)
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
