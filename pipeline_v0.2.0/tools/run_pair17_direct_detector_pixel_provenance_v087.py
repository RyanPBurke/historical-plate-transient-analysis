#!/usr/bin/env python3
from pathlib import Path
import csv, hashlib, json, math, re

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_direct_detector_pixel_provenance_contract_v087.json"
)
EXPECTED_CONTRACT_SHA = "4466ba7f8ea4fa268771cab2ad2b576bc2f40e4f6988bab869ae86169753f0ca"

V075 = (
    ROOT / "results" / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)
V086 = (
    ROOT / "results" / "pair17_astrometric_locator_audit_v086"
    / "pair17_science_locator_audit_v086.csv"
)
V086_BANK = (
    ROOT / "results" / "pair17_astrometric_locator_audit_v086"
    / "pair17_v086a_bank_manifest.json"
)

EXPECTED_V075_SHA = "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097"
EXPECTED_V086_BANK_SHA = "3308d357147d9eb5a09609b8b969802581e399f37d8aeffe53ddf058890c10b7"

SURV = ["293118","293470","293841","294052","294130","294179"]

ENDPOINTS = [
    ("a", "HAMBURG", "APPLAUSE:14120"),
    ("b", "BAMBERG", "APPLAUSE:132654"),
]

OUT = ROOT / "results" / "pair17_direct_detector_pixel_provenance_v087"
OUT_CSV = OUT / "pair17_direct_detector_pixel_provenance_v087.csv"
OUT_JSON = OUT / "pair17_direct_detector_pixel_provenance_v087.json"


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def read_csv(p):
    with Path(p).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p, rr):
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rr[0].keys()) if rr else []
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rr)


def fnum(v):
    try:
        x = float(str(v).strip())
    except Exception:
        return None
    return x if math.isfinite(x) else None


def inum(v):
    x = fnum(v)
    if x is None:
        return None
    return int(round(x))


def sphere_sep_arcsec(ra1, dec1, ra2, dec2):
    r1 = math.radians(ra1)
    d1 = math.radians(dec1)
    r2 = math.radians(ra2)
    d2 = math.radians(dec2)
    c = (
        math.sin(d1)*math.sin(d2)
        + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    )
    c = min(1.0, max(-1.0, c))
    return math.degrees(math.acos(c)) * 3600.0


def parse_tile_origin(tile_id):
    m = re.fullmatch(
        r"x(\d+)-(\d+)_y(\d+)-(\d+)",
        str(tile_id).strip()
    )
    if not m:
        raise RuntimeError(f"Unparseable tile_id: {tile_id!r}")
    return int(m.group(1)), int(m.group(3))


def alignment_band(delta):
    if delta <= 1e-6:
        return "EXACT"
    if delta <= 0.5:
        return "SUBPIXEL"
    if delta <= 1.0:
        return "WITHIN_1PX"
    if delta <= 2.0:
        return "WITHIN_2PX"
    return "OFFSET_GT2PX"


def main():
    print("="*120)
    print("PAIR 17 — DIRECT DETECTOR PIXEL PROVENANCE AUDIT v087")
    print("="*120)
    print("Network calls:            0")
    print("FITS reads:               0")
    print("Detector reruns:          0")
    print("New feature measurements: 0")
    print("Score changes:            NONE")
    print("Disposition changes:      NONE")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v087 contract SHA mismatch")
    if not V075.is_file() or sha(V075) != EXPECTED_V075_SHA:
        raise RuntimeError("v075 frozen input SHA mismatch")
    if not V086_BANK.is_file() or sha(V086_BANK) != EXPECTED_V086_BANK_SHA:
        raise RuntimeError("v086a bank SHA mismatch")
    if not V086.is_file():
        raise RuntimeError("v086 science locator audit CSV missing")

    v075 = {str(r["raw_match_row"]): r for r in read_csv(V075)}
    v086_rows = read_csv(V086)

    cross = {}
    for r in v086_rows:
        key = (str(r["raw_match_row"]), str(r["observatory"]).upper())
        if key in cross:
            raise RuntimeError(f"Duplicate v086 science crosshair row: {key}")
        cross[key] = r

    if set(v075).isdisjoint(SURV):
        raise RuntimeError("No survivor records found in v075")

    out = []

    for rid in SURV:
        if rid not in v075:
            raise RuntimeError(f"Missing survivor {rid} in v075")

        vr = v075[rid]

        for ep, obs, endpoint in ENDPOINTS:
            tile_id = str(vr[f"{ep}_tile_id"]).strip()
            cand_idx = inum(vr[f"{ep}_candidate_index"])
            if cand_idx is None:
                raise RuntimeError(f"{rid} {ep}: invalid candidate_index")

            detector_csv = (
                ROOT / "results" / "wide_census_detector_execution_v056"
                / "tiles" / endpoint.replace(":","_")
                / f"{tile_id}_candidates.csv"
            )

            # Existing v056 directory names use the endpoint key exactly as APPLAUSE_14120 / APPLAUSE_132654.
            if not detector_csv.is_file():
                raise RuntimeError(f"Detector candidate CSV missing: {detector_csv}")

            drows = read_csv(detector_csv)
            matches = [
                r for r in drows
                if inum(r.get("candidate_index")) == cand_idx
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"{rid} {obs}: expected exactly one candidate_index={cand_idx} "
                    f"in {detector_csv}; found {len(matches)}"
                )
            d = matches[0]

            # Provenance identity checks.
            if str(d.get("endpoint_key","")).strip() not in {
                endpoint, endpoint.replace(":","_")
            }:
                raise RuntimeError(
                    f"{rid} {obs}: endpoint_key mismatch: {d.get('endpoint_key')!r}"
                )
            if str(d.get("tile_id","")).strip() != tile_id:
                raise RuntimeError(
                    f"{rid} {obs}: detector tile_id mismatch"
                )
            if inum(d.get("candidate_index")) != cand_idx:
                raise RuntimeError(
                    f"{rid} {obs}: detector candidate_index mismatch"
                )

            gx = fnum(d.get("global_x"))
            gy = fnum(d.get("global_y"))
            lx = fnum(d.get("local_x"))
            ly = fnum(d.get("local_y"))
            dra = fnum(d.get("ra_deg"))
            ddec = fnum(d.get("dec_deg"))

            if None in (gx,gy,lx,ly,dra,ddec):
                raise RuntimeError(
                    f"{rid} {obs}: detector row missing required numeric provenance"
                )

            v_ra = fnum(vr[f"{ep}_ra_deg"])
            v_dec = fnum(vr[f"{ep}_dec_deg"])
            if v_ra is None or v_dec is None:
                raise RuntimeError(f"{rid} {obs}: v075 endpoint RA/Dec missing")

            ra_sep = sphere_sep_arcsec(dra,ddec,v_ra,v_dec)

            x0,y0 = parse_tile_origin(tile_id)
            tile_dx = gx - (x0 + lx)
            tile_dy = gy - (y0 + ly)
            tile_resid = math.hypot(tile_dx,tile_dy)

            cr = cross.get((rid,obs))
            if cr is None:
                raise RuntimeError(f"{rid} {obs}: v086 crosshair row missing")

            cx = fnum(cr.get("banked_crosshair_x_px"))
            cy = fnum(cr.get("banked_crosshair_y_px"))
            if cx is None or cy is None:
                raise RuntimeError(f"{rid} {obs}: invalid crosshair pixel")

            dx = cx-gx
            dy = cy-gy
            delta = math.hypot(dx,dy)

            # Diagnose only: common one-based/zero-based alternatives.
            delta_detector_minus1 = math.hypot(cx-(gx-1.0), cy-(gy-1.0))
            delta_detector_plus1 = math.hypot(cx-(gx+1.0), cy-(gy+1.0))

            alt = {
                "DIRECT": delta,
                "DETECTOR_MINUS1_BOTH_AXES": delta_detector_minus1,
                "DETECTOR_PLUS1_BOTH_AXES": delta_detector_plus1,
            }
            best_name = min(alt, key=alt.get)
            best_delta = alt[best_name]

            out.append({
                "raw_match_row": rid,
                "observatory": obs,
                "endpoint": endpoint,
                "blind_code": cr.get("blind_code",""),
                "manual_feature": cr.get("manual_feature",""),
                "manual_morphology": cr.get("manual_morphology",""),
                "manual_confidence": cr.get("manual_confidence",""),
                "manual_notes": cr.get("manual_notes",""),
                "tile_id": tile_id,
                "candidate_index": cand_idx,
                "detector_csv":
                    str(detector_csv.relative_to(ROOT)).replace("\\","/"),
                "detector_csv_sha256": sha(detector_csv),
                "detector_local_x": lx,
                "detector_local_y": ly,
                "detector_global_x": gx,
                "detector_global_y": gy,
                "detector_ra_deg": dra,
                "detector_dec_deg": ddec,
                "v075_ra_deg": v_ra,
                "v075_dec_deg": v_dec,
                "detector_vs_v075_radec_arcsec": ra_sep,
                "tile_origin_x": x0,
                "tile_origin_y": y0,
                "global_minus_tilepluslocal_x_px": tile_dx,
                "global_minus_tilepluslocal_y_px": tile_dy,
                "global_tile_local_residual_px": tile_resid,
                "crosshair_x_px": cx,
                "crosshair_y_px": cy,
                "crosshair_minus_detector_x_px": dx,
                "crosshair_minus_detector_y_px": dy,
                "crosshair_vs_detector_direct_delta_px": delta,
                "crosshair_vs_detector_minus1_delta_px": delta_detector_minus1,
                "crosshair_vs_detector_plus1_delta_px": delta_detector_plus1,
                "best_simple_coordinate_convention": best_name,
                "best_simple_coordinate_delta_px": best_delta,
                "direct_alignment_band": alignment_band(delta),
                "detector_snr": d.get("snr",""),
                "detector_signal": d.get("signal",""),
                "detector_polarity": d.get("polarity",""),
                "detector_sigma": d.get("sigma",""),
            })

    if len(out) != 12:
        raise RuntimeError(f"Expected 12 audit rows; got {len(out)}")

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_CSV, out)

    counts = {}
    for r in out:
        counts[r["direct_alignment_band"]] = counts.get(
            r["direct_alignment_band"], 0
        ) + 1

    suspicious = [
        r for r in out
        if r["direct_alignment_band"] == "OFFSET_GT2PX"
    ]

    report = {
        "status": "COMPLETE",
        "analysis_kind":
            "pair17_direct_detector_pixel_provenance_audit_v087",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "population": {
            "candidates": 6,
            "science_endpoint_rows": 12
        },
        "alignment_band_counts": counts,
        "max_direct_crosshair_detector_delta_px":
            max(r["crosshair_vs_detector_direct_delta_px"] for r in out),
        "max_detector_vs_v075_radec_arcsec":
            max(r["detector_vs_v075_radec_arcsec"] for r in out),
        "max_global_tile_local_residual_px":
            max(r["global_tile_local_residual_px"] for r in out),
        "offset_gt2px_rows": [
            {
                "raw_match_row": r["raw_match_row"],
                "observatory": r["observatory"],
                "blind_code": r["blind_code"],
                "manual_feature": r["manual_feature"],
                "delta_px": r["crosshair_vs_detector_direct_delta_px"],
                "best_simple_coordinate_convention":
                    r["best_simple_coordinate_convention"],
                "best_simple_coordinate_delta_px":
                    r["best_simple_coordinate_delta_px"],
                "manual_notes": r["manual_notes"],
            }
            for r in suspicious
        ],
        "guards": {
            "network_calls": 0,
            "fits_reads": 0,
            "detector_reruns": 0,
            "new_pixel_feature_measurements": 0,
            "manual_scores_modified": False,
            "threshold_retuning": False,
            "candidate_disposition_changes": False
        },
        "output_csv_sha256": sha(OUT_CSV)
    }

    OUT_JSON.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )

    print()
    print("="*120)
    print("v087 DIRECT DETECTOR PIXEL AUDIT COMPLETE")
    print("="*120)
    print("Alignment bands:", json.dumps(counts, sort_keys=True))
    print(
        "Max direct crosshair-detector delta px:",
        f'{report["max_direct_crosshair_detector_delta_px"]:.9f}'
    )
    print(
        "Max detector-v075 RA/Dec disagreement arcsec:",
        f'{report["max_detector_vs_v075_radec_arcsec"]:.9f}'
    )
    print(
        "Max global-(tile_origin+local) residual px:",
        f'{report["max_global_tile_local_residual_px"]:.9f}'
    )
    print()
    print("SCIENCE ENDPOINT SUMMARY")
    for r in out:
        print(
            f'{r["raw_match_row"]} {r["observatory"]:7s} '
            f'blind={r["blind_code"] or "-":4s} '
            f'manual={r["manual_feature"] or "-":17s} '
            f'delta_px={r["crosshair_vs_detector_direct_delta_px"]:.6f} '
            f'band={r["direct_alignment_band"]:12s} '
            f'best={r["best_simple_coordinate_convention"]} '
            f'best_delta={r["best_simple_coordinate_delta_px"]:.6f}'
        )

    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
