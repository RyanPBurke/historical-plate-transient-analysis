#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
import csv, hashlib, json, math, os, re

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_astrometric_locator_audit_contract_v086.json"
)
EXPECTED_CONTRACT_SHA = "b802fc02354f2911f2551c6e49e6cf4dabc088686d1ee99172127101bf73eb89"

V075 = (
    ROOT / "results" / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)
V079 = ROOT / "results" / "pair17_pixel_followup_scan_plan_and_acquisition_v079"
V079_ACQ = V079 / "pair17_scan_acquisition_manifest_v079.csv"

V080 = ROOT / "results" / "pair17_registered_native_pixel_recurrence_sensitivity_v080"
V080_TARGETS = V080 / "pair17_registered_target_coordinates_v080.csv"
V080_PLATES = V080 / "pair17_native_pixel_plate_measurements_v080.csv"

V083 = ROOT / "results" / "pair17_standardized_manual_dossiers_v083"
V083_MAN = V083 / "pair17_manual_dossier_panel_manifest_v083.csv"
V083_BANK = V083 / "pair17_v083b_bank_manifest.json"

V084A = ROOT / "results" / "pair17_blinded_manual_review_packet_v084a"
V084A_BANK = V084A / "pair17_v084a_bank_manifest.json"

V085 = ROOT / "results" / "pair17_unblind_blind_review_v085"
V085_PANELS = V085 / "pair17_unblinded_panel_scores_v085.csv"
V085_BANK = V085 / "pair17_v085_bank_manifest.json"

EXPECTED = {
    V083_BANK:
        "6f0f749852db04fc5d1a9b8bde773a2f0dc273ee59d8e0832b72e3743e9b658b",
    V084A_BANK:
        "53e4c77094d8087ac6ca7f9e80d108a2b23829874b258d0321d3970311ff0293",
    V085_BANK:
        "c54982481ee6746b8e5b8b18bb9cbb2b7057b14259837f620507c4ac8c13bc71",
    V075:
        "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097",
}

SURV = ["293118","293470","293841","294052","294130","294179"]

SCI = {
    "HAMBURG": {
        "endpoint": "a",
        "plate_id": 7685,
        "basename": "LA08164_y.fits",
    },
    "BAMBERG": {
        "endpoint": "b",
        "plate_id": 89580,
        "basename": "012673_1953_h.fits",
    },
}

OUT = ROOT / "results" / "pair17_astrometric_locator_audit_v086"
OUT_ALL = OUT / "pair17_locator_audit_all_panels_v086.csv"
OUT_SCI = OUT / "pair17_science_locator_audit_v086.csv"
OUT_PROV = OUT / "pair17_science_direct_pixel_provenance_inventory_v086.csv"
OUT_JSON = OUT / "pair17_astrometric_locator_audit_v086.json"

TOL = 1e-6


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def rows(p):
    with Path(p).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p, rr, fields=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rr[0].keys()) if rr else []
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if fields:
            w.writeheader()
            w.writerows(rr)


def write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8"
    )


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def integer(v):
    x = num(v)
    return None if x is None else int(x)


def unique_file(basename):
    matches = []
    for parent in (ROOT/"work", ROOT/"results"):
        if parent.exists():
            matches.extend(p.resolve() for p in parent.rglob(basename) if p.is_file())
    matches = sorted(set(matches))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one local {basename}; found {len(matches)}: {matches}"
        )
    return matches[0]


def choose_wcs_from_header(path):
    # Header-only access: do not touch HDU data.
    hdr = fits.getheader(path, 0, ignore_missing_end=True)
    w = WCS(hdr).celestial
    if w.pixel_n_dim != 2 or w.world_n_dim != 2:
        raise RuntimeError(f"No usable celestial WCS: {path}")
    return w


def acq_map():
    out = {}
    for r in rows(V079_ACQ):
        sid = integer(r.get("scan_id"))
        pid = integer(r.get("physical_plate_id"))
        if sid is None or pid is None:
            continue
        p = ROOT / str(r.get("local_path") or "").replace("/", os.sep)
        out[(sid,pid)] = p
    return out


def measurement_map():
    out = {}
    for r in rows(V080_PLATES):
        key = (
            str(r.get("raw_match_row") or ""),
            integer(r.get("physical_plate_id")),
            integer(r.get("scan_id")),
        )
        out[key] = r
    return out


def comparison_target_pixel(meas, target, w):
    c = target
    if str(meas.get("registration_mode") or "") == "PRIMARY":
        east = num(meas.get("registration_shift_east_arcsec"))
        north = num(meas.get("registration_shift_north_arcsec"))
        if east is not None and north is not None:
            c = target.spherical_offsets_by(east*u.arcsec, north*u.arcsec)

    pix = np.asarray(
        w.all_world2pix([[float(c.ra.deg), float(c.dec.deg)]], 0),
        dtype=float
    )[0]

    if not np.all(np.isfinite(pix)):
        raise RuntimeError("Non-finite reconstructed comparison target pixel")
    return float(pix[0]), float(pix[1])


def science_target_pixel(tri, endpoint, w):
    ra = num(tri.get(f"{endpoint}_ra_deg"))
    dec = num(tri.get(f"{endpoint}_dec_deg"))
    if ra is None or dec is None:
        raise RuntimeError(
            f"Missing v075 {endpoint}_ra_deg/{endpoint}_dec_deg"
        )
    pix = np.asarray(w.all_world2pix([[ra,dec]],0), dtype=float)[0]
    if not np.all(np.isfinite(pix)):
        raise RuntimeError("Non-finite reconstructed science target pixel")
    return float(pix[0]), float(pix[1]), ra, dec


def direct_pixel_candidates_from_row(row, endpoint):
    """
    Inventory exact pre-existing endpoint pixel-like fields.
    Automatically compare only the explicit *_x_global/*_y_global pair.
    Other x/y-like fields are reported for provenance inspection.
    """
    result = []
    keys = list(row.keys())

    # Exact global pair first.
    xk = f"{endpoint}_x_global"
    yk = f"{endpoint}_y_global"
    if xk in row and yk in row:
        xv, yv = num(row.get(xk)), num(row.get(yk))
        result.append((xk, yk, xv, yv, "EXACT_GLOBAL_PAIR"))

    # Other same-prefix x/y pairs, without interpreting their coordinate system.
    prefixes = {}
    for k in keys:
        lk = k.lower()
        if not lk.startswith(endpoint.lower() + "_"):
            continue

        if re.search(r"(^|_)x($|_)", lk):
            stem = re.sub(r"(^|_)x($|_)", r"\1XY\2", lk, count=1)
            prefixes.setdefault(stem, {})["x"] = k
        if re.search(r"(^|_)y($|_)", lk):
            stem = re.sub(r"(^|_)y($|_)", r"\1XY\2", lk, count=1)
            prefixes.setdefault(stem, {})["y"] = k

    seen = {(xk,yk)}
    for _, pair in sorted(prefixes.items()):
        if "x" not in pair or "y" not in pair:
            continue
        pk = (pair["x"], pair["y"])
        if pk in seen:
            continue
        seen.add(pk)
        xv, yv = num(row.get(pk[0])), num(row.get(pk[1]))
        result.append((pk[0], pk[1], xv, yv, "OTHER_ENDPOINT_XY_PAIR"))

    return result


def scan_frozen_pair17_csv_provenance():
    """
    Search only frozen Pair-17 CSV result products whose path names indicate
    v067/v068/v075 lineage. No pixels, no detector rerun.
    """
    candidates = []
    results_root = ROOT / "results"

    for p in sorted(results_root.rglob("*.csv")):
        s = str(p).lower().replace("\\","/")
        if "pair17" not in s:
            continue
        if not any(tag in s for tag in ("v067","v068","v075")):
            continue
        candidates.append(p)

    found = []

    for p in candidates:
        try:
            with p.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    continue
                fields = reader.fieldnames
                if "raw_match_row" not in fields:
                    continue

                for r in reader:
                    rid = str(r.get("raw_match_row") or "")
                    if rid not in SURV:
                        continue

                    for obs, sm in SCI.items():
                        ep = sm["endpoint"]
                        for xk,yk,xv,yv,kind in direct_pixel_candidates_from_row(r,ep):
                            found.append({
                                "raw_match_row": rid,
                                "observatory": obs,
                                "endpoint": ep,
                                "source_file":
                                    str(p.relative_to(ROOT)).replace("\\","/"),
                                "x_field": xk,
                                "y_field": yk,
                                "x_value": "" if xv is None else xv,
                                "y_value": "" if yv is None else yv,
                                "provenance_pair_kind": kind,
                            })
        except Exception as e:
            found.append({
                "raw_match_row": "",
                "observatory": "",
                "endpoint": "",
                "source_file": str(p.relative_to(ROOT)).replace("\\","/"),
                "x_field": "",
                "y_field": "",
                "x_value": "",
                "y_value": "",
                "provenance_pair_kind": "CSV_READ_ERROR:" + repr(e),
            })

    return found


def main():
    print("="*120)
    print("PAIR 17 — ASTROMETRIC LOCATOR AUDIT v086")
    print("="*120)
    print("Post-unblind diagnostic audit")
    print("Network calls:              0")
    print("FITS DATA reads:            0")
    print("FITS HEADER reads:          allowed")
    print("Detector reruns:            0")
    print("New feature measurements:   0")
    print("Score changes:              NONE")
    print("Disposition changes:        NONE")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v086 contract SHA mismatch")

    for p,e in EXPECTED.items():
        if not p.is_file() or sha(p) != e:
            raise RuntimeError(f"Frozen v086 input mismatch: {p}")
        print("HASH PASS:", p.relative_to(ROOT))

    tri = {str(r["raw_match_row"]):r for r in rows(V075)}
    targets = {str(r["raw_match_row"]):r for r in rows(V080_TARGETS)}
    meas = measurement_map()
    acq = acq_map()
    panels = rows(V083_MAN)
    scores = {r["blind_code"]:r for r in rows(V085_PANELS)}

    if len(panels) != 32:
        raise RuntimeError(f"Expected 32 v083 panels; got {len(panels)}")
    if len(scores) != 32:
        raise RuntimeError(f"Expected 32 v085 panel scores; got {len(scores)}")

    # v085 row already contains blind_code and panel identity. Build identity lookup.
    score_by_identity = {}
    for r in scores.values():
        key = (
            str(r.get("raw_match_row") or ""),
            str(r.get("panel_role") or ""),
            str(r.get("physical_plate_id") or ""),
            str(r.get("scan_id") or ""),
        )
        score_by_identity[key] = r

    science_paths = {
        obs: unique_file(meta["basename"])
        for obs,meta in SCI.items()
    }

    all_audit = []
    science_audit = []

    for p in panels:
        rid = str(p["raw_match_row"])
        role = str(p["panel_role"])
        pid = integer(p.get("physical_plate_id"))
        sid = integer(p.get("scan_id"))
        science = "SCIENCE_" in role

        if science:
            obs = str(p["observatory"])
            path = science_paths[obs]
            w = choose_wcs_from_header(path)
            ep = SCI[obs]["endpoint"]
            rx,ry,ra,dec = science_target_pixel(tri[rid], ep, w)
            reconstruction_source = (
                f"v075 {ep}_ra_deg/{ep}_dec_deg -> exact science FITS WCS"
            )
            registration_mode = "SCIENCE"
        else:
            path = acq.get((sid,pid))
            if path is None or not path.is_file():
                raise RuntimeError(
                    f"Comparison scan missing for {rid} plate={pid} scan={sid}"
                )
            w = choose_wcs_from_header(path)
            m = meas.get((rid,pid,sid))
            if m is None:
                raise RuntimeError(
                    f"v080 measurement missing for {rid} plate={pid} scan={sid}"
                )
            t = targets[rid]
            target = SkyCoord(
                float(t["registered_target_ra_deg"])*u.deg,
                float(t["registered_target_dec_deg"])*u.deg,
                frame="icrs"
            )
            rx,ry = comparison_target_pixel(m,target,w)
            ra=dec=""
            reconstruction_source = (
                "v080 registered target + banked local registration shift -> exact comparison FITS WCS"
            )
            registration_mode = m.get("registration_mode","")

        bx = float(p["target_pixel_x"])
        by = float(p["target_pixel_y"])
        dx = rx-bx
        dy = ry-by
        resid = math.hypot(dx,dy)
        status = "PASS" if resid <= TOL else "FAIL"

        skey = (rid,role,str(p.get("physical_plate_id") or ""),str(p.get("scan_id") or ""))
        s = score_by_identity.get(skey, {})

        rec = {
            "raw_match_row": rid,
            "blind_code": s.get("blind_code",""),
            "panel_role": role,
            "observatory": p.get("observatory",""),
            "physical_plate_id": p.get("physical_plate_id",""),
            "scan_id": p.get("scan_id",""),
            "registration_mode": registration_mode,
            "banked_crosshair_x_px": bx,
            "banked_crosshair_y_px": by,
            "reconstructed_x_px": rx,
            "reconstructed_y_px": ry,
            "delta_x_px": dx,
            "delta_y_px": dy,
            "residual_px": resid,
            "render_reconstruction_status": status,
            "reconstruction_source": reconstruction_source,
            "manual_feature": s.get("feature_at_crosshair",""),
            "manual_morphology": s.get("morphology",""),
            "manual_confidence": s.get("confidence_1_to_5",""),
            "manual_notes": s.get("notes",""),
        }
        all_audit.append(rec)

        if science:
            tr = tri[rid]
            ep = SCI[str(p["observatory"])]["endpoint"]
            direct_x = num(tr.get(f"{ep}_x_global"))
            direct_y = num(tr.get(f"{ep}_y_global"))

            delta_direct = ""
            delta_direct_1based = ""
            best_direct = ""

            if direct_x is not None and direct_y is not None:
                d0 = math.hypot(bx-direct_x, by-direct_y)
                # Also test common 1-based vs 0-based convention.
                d1 = math.hypot(bx-(direct_x-1.0), by-(direct_y-1.0))
                delta_direct = d0
                delta_direct_1based = d1
                best_direct = min(d0,d1)

            science_audit.append({
                **rec,
                "endpoint": ep,
                "v075_endpoint_ra_deg": ra,
                "v075_endpoint_dec_deg": dec,
                "v075_direct_x_global": "" if direct_x is None else direct_x,
                "v075_direct_y_global": "" if direct_y is None else direct_y,
                "crosshair_vs_v075_direct_delta_px": delta_direct,
                "crosshair_vs_v075_direct_if_1based_delta_px": delta_direct_1based,
                "crosshair_vs_v075_direct_best_delta_px": best_direct,
                "direct_pixel_provenance_available":
                    direct_x is not None and direct_y is not None,
            })

    write_csv(OUT_ALL, all_audit)
    write_csv(OUT_SCI, science_audit)

    provenance = scan_frozen_pair17_csv_provenance()

    # Add delta-to-crosshair only for exact global provenance rows.
    sci_lookup = {
        (r["raw_match_row"],r["observatory"]):r
        for r in science_audit
    }

    for r in provenance:
        r["delta_to_banked_crosshair_px"] = ""
        r["delta_to_banked_crosshair_if_1based_px"] = ""
        r["best_global_delta_px"] = ""

        if r.get("provenance_pair_kind") != "EXACT_GLOBAL_PAIR":
            continue

        key = (r.get("raw_match_row",""),r.get("observatory",""))
        a = sci_lookup.get(key)
        xv,yv = num(r.get("x_value")),num(r.get("y_value"))
        if a is None or xv is None or yv is None:
            continue

        bx=float(a["banked_crosshair_x_px"])
        by=float(a["banked_crosshair_y_px"])
        d0=math.hypot(bx-xv,by-yv)
        d1=math.hypot(bx-(xv-1.0),by-(yv-1.0))
        r["delta_to_banked_crosshair_px"]=d0
        r["delta_to_banked_crosshair_if_1based_px"]=d1
        r["best_global_delta_px"]=min(d0,d1)

    write_csv(
        OUT_PROV,
        provenance,
        fields=[
            "raw_match_row","observatory","endpoint","source_file",
            "x_field","y_field","x_value","y_value","provenance_pair_kind",
            "delta_to_banked_crosshair_px",
            "delta_to_banked_crosshair_if_1based_px",
            "best_global_delta_px"
        ]
    )

    recon_fail = [r for r in all_audit if r["render_reconstruction_status"]!="PASS"]
    science_direct = [
        r for r in science_audit
        if r["direct_pixel_provenance_available"]
    ]

    global_prov = [
        r for r in provenance
        if r.get("provenance_pair_kind")=="EXACT_GLOBAL_PAIR"
        and num(r.get("x_value")) is not None
        and num(r.get("y_value")) is not None
    ]

    report = {
        "status":"COMPLETE",
        "analysis_kind":"pair17_astrometric_locator_audit_v086",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "population":{"panels":32,"science_panels":12,"candidates":6},
        "render_reconstruction":{
            "pass_tolerance_px":TOL,
            "passes":32-len(recon_fail),
            "failures":len(recon_fail),
            "max_residual_px":max(r["residual_px"] for r in all_audit),
        },
        "science_direct_pixel_provenance":{
            "available_in_v075_science_rows":len(science_direct),
            "exact_global_provenance_rows_found_across_frozen_v067_v068_v075_csvs":
                len(global_prov),
            "note":(
                "Render reconstruction tests whether the crosshair matches the frozen "
                "astrometric calculation. Direct pixel provenance, when available, is "
                "the stronger check against the original detector pixel location."
            )
        },
        "guards":{
            "network_calls":0,
            "fits_data_reads":0,
            "fits_header_reads":"yes",
            "detector_reruns":0,
            "new_pixel_feature_measurements":0,
            "manual_scores_modified":False,
            "threshold_retuning":False,
            "candidate_disposition_changes":False,
        },
        "outputs":{
            "all_panels":str(OUT_ALL.relative_to(ROOT)).replace("\\","/"),
            "science_panels":str(OUT_SCI.relative_to(ROOT)).replace("\\","/"),
            "provenance_inventory":str(OUT_PROV.relative_to(ROOT)).replace("\\","/"),
        }
    }

    write_json(OUT_JSON,report)

    print()
    print("="*120)
    print("v086 LOCATOR AUDIT COMPLETE")
    print("="*120)
    print("Render reconstruction passes:", report["render_reconstruction"]["passes"], "/ 32")
    print("Render reconstruction failures:", report["render_reconstruction"]["failures"])
    print("Max reconstruction residual px:", report["render_reconstruction"]["max_residual_px"])
    print("Science panels with direct v075 x_global/y_global:", len(science_direct), "/ 12")
    print("Exact global provenance rows recovered from frozen CSV lineage:", len(global_prov))
    print()
    print("SCIENCE PANEL SUMMARY")
    for r in science_audit:
        print(
            f'{r["raw_match_row"]} {r["observatory"]:7s} '
            f'blind={r["blind_code"] or "-":4s} '
            f'manual={r["manual_feature"] or "-":17s} '
            f'recon={r["render_reconstruction_status"]} '
            f'resid_px={r["residual_px"]:.9f} '
            f'direct={"YES" if r["direct_pixel_provenance_available"] else "NO"} '
            f'note={r["manual_notes"]}'
        )

    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
