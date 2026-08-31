#!/usr/bin/env python3
from __future__ import annotations

import csv, io, json, math, re
from pathlib import Path
import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_physical_morphology_v028ar.json"
OUT_SUMMARY = BASE / "order01_dasch_physical_morphology_summary_v028ar.csv"
OUT_CONTROLS = BASE / "order01_dasch_official_pixel_controls_v028ar.csv"
OUT_MD = BASE / "ORDER01_DASCH_PHYSICAL_MORPHOLOGY_V028AR.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
PATCH_RADIUS = 24
ANN_IN = 12.0
ANN_OUT = 20.0
CORE_RADIUS = 7.0
MIN_OFFICIAL_CONTROLS = 8

TILE_RE = re.compile(r"(D_x(?P<x0>\d+)-(?P<x1>\d+)_y(?P<y0>\d+)-(?P<y1>\d+))", re.I)


def read_csv_file(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def f(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        x = float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def i(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def robust_sigma(vals):
    a = np.asarray(vals, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 8:
        return None
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    sig = 1.4826 * mad
    if not np.isfinite(sig) or sig <= 0:
        sig = float(np.std(a))
    return sig if np.isfinite(sig) and sig > 0 else None


def parse_platephot(path):
    obj = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(obj, list) or not obj or not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{path.name}: expected JSON list[str]")
    return list(csv.DictReader(io.StringIO("\n".join(obj))))


def parse_tile(path):
    m = TILE_RE.search(path.stem)
    if not m:
        return None
    return {
        "tile_id": m.group(1),
        "x0": int(m.group("x0")), "x1": int(m.group("x1")),
        "y0": int(m.group("y0")), "y1": int(m.group("y1")),
        "path": path,
    }


def discover_tiles():
    found = {}
    for top in (WORK, BASE, ROOT / "work", ROOT / "results"):
        if not top.exists():
            continue
        for p in top.rglob("*.npy"):
            t = parse_tile(p)
            if t is None:
                continue
            score = 0
            low = str(p).lower()
            if "order01_native_full_v028" in low:
                score += 100
            if "dasch" in low:
                score += 20
            score -= len(p.parts)
            old = found.get(t["tile_id"])
            if old is None or score > old[0]:
                found[t["tile_id"]] = (score, t)
    return {k: v[1] for k, v in found.items()}


def tile_for_global(tiles, x, y):
    q = [t for t in tiles.values() if t["x0"] <= x < t["x1"] and t["y0"] <= y < t["y1"]]
    if not q:
        return None
    q.sort(key=lambda t: (t["x1"] - t["x0"]) * (t["y1"] - t["y0"]))
    return q[0]


ARR_CACHE = {}
def load_array(tile):
    key = str(tile["path"])
    if key not in ARR_CACHE:
        arr = np.load(tile["path"], mmap_mode="r")
        if arr.ndim != 2:
            raise RuntimeError(f"tile is not 2-D: {tile['path']} shape={arr.shape}")
        ARR_CACHE[key] = arr
    return ARR_CACHE[key]


def extract_patch(tile, lx, ly, r=PATCH_RADIUS):
    arr = load_array(tile)
    xi = int(round(lx))
    yi = int(round(ly))
    if yi-r < 0 or xi-r < 0 or yi+r >= arr.shape[0] or xi+r >= arr.shape[1]:
        return None
    return np.asarray(arr[yi-r:yi+r+1, xi-r:xi+r+1], dtype=float)


def raw_metrics(patch, polarity):
    n = patch.shape[0]
    c = (n - 1) / 2.0
    yy, xx = np.indices(patch.shape, dtype=float)
    dx = xx - c
    dy = yy - c
    rr = np.hypot(dx, dy)

    ann = patch[(rr >= ANN_IN) & (rr <= ANN_OUT)]
    bg = float(np.median(ann))
    sig = robust_sigma(ann)
    if sig is None:
        return None

    z = (patch - bg) / sig
    signed = polarity * z

    m3 = (np.abs(dx) <= 1) & (np.abs(dy) <= 1)
    center3 = float(np.mean(signed[m3]))

    core = rr <= CORE_RADIUS
    vals = signed[core]

    result = {
        "background_median": bg,
        "background_sigma": sig,
        "center3_signed_zmean": center3,
        "core_signed_peak_z": float(np.max(vals)),
        "core_signed_min_z": float(np.min(vals)),
    }

    for rad in (2, 3, 5, 7):
        m = rr <= rad
        result[f"ap{rad}_signed_zsum"] = float(np.sum(signed[m]))
        result[f"ap{rad}_signed_zmean"] = float(np.mean(signed[m]))

    w = np.where(core, np.clip(signed, 0, None), 0.0)
    sw = float(np.sum(w))
    if sw > 0:
        cx = float(np.sum(w * dx) / sw)
        cy = float(np.sum(w * dy) / sw)
        result["centroid_dx_pix"] = cx
        result["centroid_dy_pix"] = cy
        result["centroid_offset_pix"] = float(math.hypot(cx, cy))
        result["moment_radius_pix"] = float(math.sqrt(max(0.0, np.sum(w * (dx*dx + dy*dy)) / sw)))
    else:
        result["centroid_dx_pix"] = None
        result["centroid_dy_pix"] = None
        result["centroid_offset_pix"] = None
        result["moment_radius_pix"] = None

    quads = []
    for sx, sy in ((1,1),(-1,1),(-1,-1),(1,-1)):
        qm = core & (dx*sx >= 0) & (dy*sy >= 0)
        quads.append(float(np.sum(signed[qm])))
    qmean = float(np.mean(np.abs(quads)))
    result["quadrant_imbalance"] = float(np.std(quads) / qmean) if qmean > 0 else None

    for lo, hi in ((0,1.5),(1.5,3),(3,5),(5,7),(7,10),(10,12)):
        m = (rr >= lo) & (rr < hi)
        result[f"radial_{lo:g}_{hi:g}_signed_zmean"] = float(np.mean(signed[m]))

    return result


def percentile(vals, x):
    q = np.asarray([v for v in vals if v is not None and np.isfinite(v)], dtype=float)
    if x is None or q.size == 0:
        return None
    return float((np.sum(q < x) + 0.5*np.sum(q == x)) / q.size)


def main():
    print("="*128)
    print("ORDER 01 — DASCH PHYSICAL-PIXEL MORPHOLOGY VS OFFICIAL-SOURCE CONTROLS v028ar")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE, STRICT, DASCH_NATIVE):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set") != []:
        raise RuntimeError("Order-01 closure guard mismatch")

    strict_rows = read_csv_file(STRICT)
    native = read_csv_file(DASCH_NATIVE)
    strict = {i(r["strict_rank"]): r for r in strict_rows if i(r["strict_rank"]) in RANKS}

    science = {}
    for rank in RANKS:
        r = strict[rank]
        tile_id = str(r["dasch_tile_id"])
        idx = i(r.get("dasch_candidate_index"))
        q = [x for x in native if str(x.get("tile_id","")) == tile_id and i(x.get("candidate_index")) == idx]
        if len(q) != 1:
            raise RuntimeError(f"#{rank}: native science resolution failed ({len(q)})")
        science[rank] = q[0]

    tiles = discover_tiles()
    print(f"Discovered DASCH tile arrays: {len(tiles)}")

    for rank, row in science.items():
        tid = str(row["tile_id"])
        if tid not in tiles:
            raise RuntimeError(f"#{rank}: science tile array not found for {tid}")
        t = tiles[tid]
        gx, gy = f(row.get("global_x")), f(row.get("global_y"))
        lx, ly = f(row.get("local_x")), f(row.get("local_y"))
        if None not in (gx, gy, lx, ly):
            dx = abs((gx - t["x0"]) - lx)
            dy = abs((gy - t["y0"]) - ly)
            if dx > 1.1 or dy > 1.1:
                raise RuntimeError(f"#{rank}: native local/global guard failed dx={dx} dy={dy}")

    official = {}
    for rank in RANKS:
        p = RAW_DIR / f"{PLATE}_sol0_rank{rank}_apass_platephot.json"
        if not p.is_file():
            raise RuntimeError(f"missing platephot cache: {p}")
        for row in parse_platephot(p):
            if str(row.get("series","")).strip() != "ai" or i(row.get("plate_number")) != 43437:
                continue
            x, y = f(row.get("x_image")), f(row.get("y_image"))
            if x is None or y is None:
                continue
            key = (str(row.get("ref_number","")), round(x,3), round(y,3))
            official.setdefault(key, dict(row))

    print(f"Unique official platephot source positions pooled: {len(official)}")

    control_seed = []
    for row in official.values():
        x, y = f(row.get("x_image")), f(row.get("y_image"))
        tile = tile_for_global(tiles, x, y)
        if tile is None:
            continue
        lx, ly = x - tile["x0"], y - tile["y0"]
        patch = extract_patch(tile, lx, ly)
        if patch is None:
            continue
        m = raw_metrics(patch, +1)
        if m is not None:
            control_seed.append((row, tile, lx, ly, m))

    if len(control_seed) < MIN_OFFICIAL_CONTROLS:
        raise RuntimeError(f"too few usable official controls: {len(control_seed)}")

    strong_signs = []
    for _,_,_,_,m in control_seed:
        if abs(m["center3_signed_zmean"]) >= 0.5:
            strong_signs.append(1 if m["center3_signed_zmean"] > 0 else -1)

    physical_polarity = 1 if sum(strong_signs) >= 0 else -1
    sign_agree = sum(s == physical_polarity for s in strong_signs)
    sign_frac = sign_agree / len(strong_signs) if strong_signs else None

    print(
        "Empirical ordinary-source physical polarity: "
        + ("RAW_HIGH" if physical_polarity == 1 else "RAW_LOW")
        + f" (agreement={sign_agree}/{len(strong_signs)})"
    )

    controls = []
    for row, tile, lx, ly, _ in control_seed:
        patch = extract_patch(tile, lx, ly)
        m = raw_metrics(patch, physical_polarity)
        controls.append({
            "ref_number": row.get("ref_number"),
            "x_image": f(row.get("x_image")),
            "y_image": f(row.get("y_image")),
            "tile_id": tile["tile_id"],
            "local_x": lx,
            "local_y": ly,
            "ra_deg": f(row.get("ra_deg")),
            "dec_deg": f(row.get("dec_deg")),
            "flux_iso": f(row.get("flux_iso")),
            "fwhm_pix_official": f(row.get("fwhm_pix")),
            "ellipticity_official": f(row.get("ellipticity")),
            "aflags": i(row.get("aflags")),
            "bflags": i(row.get("bflags")),
            **m
        })

    metrics_for_percentile = [
        "center3_signed_zmean","core_signed_peak_z",
        "ap3_signed_zsum","ap5_signed_zsum","ap7_signed_zsum",
        "centroid_offset_pix","moment_radius_pix","quadrant_imbalance",
        "radial_0_1.5_signed_zmean","radial_1.5_3_signed_zmean",
        "radial_3_5_signed_zmean","radial_5_7_signed_zmean"
    ]
    ctrl_vals = {k: [r.get(k) for r in controls] for k in metrics_for_percentile}

    summaries = []
    print("\nScience endpoint physical morphology:")
    for rank in RANKS:
        row = science[rank]
        tile = tiles[str(row["tile_id"])]
        lx, ly = f(row.get("local_x")), f(row.get("local_y"))
        patch = extract_patch(tile, lx, ly)
        if patch is None:
            raise RuntimeError(f"#{rank}: science patch crosses tile edge")
        m = raw_metrics(patch, physical_polarity)
        if m is None:
            raise RuntimeError(f"#{rank}: raw morphology failed")

        rec = {
            "strict_rank": rank,
            "tile_id": str(row["tile_id"]),
            "candidate_index": i(row.get("candidate_index")),
            "science_snr": f(row.get("snr")),
            "detector_polarity": i(row.get("polarity")),
            "local_x": lx,
            "local_y": ly,
            "global_x": f(row.get("global_x")),
            "global_y": f(row.get("global_y")),
            "empirical_physical_polarity": "RAW_HIGH" if physical_polarity == 1 else "RAW_LOW",
            "official_control_count": len(controls),
            "official_control_sign_agreement_fraction": sign_frac,
            **m,
        }
        for k in metrics_for_percentile:
            rec[k + "_control_percentile"] = percentile(ctrl_vals[k], rec.get(k))

        star_dir = rec["center3_signed_zmean"] > 0
        ap_pos = rec["ap5_signed_zsum"] > 0
        cent = rec["centroid_offset_pix"]
        if star_dir and ap_pos and cent is not None and cent <= 3.0:
            desc = "RAW_FEATURE_STAR_DIRECTION_AND_LOCALLY_CONCENTRATED"
        elif star_dir and ap_pos:
            desc = "RAW_FEATURE_STAR_DIRECTION_BUT_OFFSET_OR_DIFFUSE"
        elif rec["center3_signed_zmean"] < 0 and rec["ap5_signed_zsum"] < 0:
            desc = "RAW_FEATURE_OPPOSITE_ORDINARY_SOURCE_POLARITY"
        else:
            desc = "RAW_FEATURE_MIXED_OR_NON_STELLAR_MORPHOLOGY"
        rec["descriptive_morphology"] = desc
        summaries.append(rec)

        cent_txt = "n/a" if cent is None else f"{cent:.2f}px"
        mr = rec["moment_radius_pix"]
        mr_txt = "n/a" if mr is None else f"{mr:.2f}px"
        print(
            f"#{rank}: center3={rec['center3_signed_zmean']:+.3f}z "
            f"peak={rec['core_signed_peak_z']:+.3f}z "
            f"ap5={rec['ap5_signed_zsum']:+.3f} "
            f"centroidOff={cent_txt} momentR={mr_txt} => {desc}"
        )
        print(
            f"    control percentiles: "
            f"center3={rec['center3_signed_zmean_control_percentile']:.3f} "
            f"ap5={rec['ap5_signed_zsum_control_percentile']:.3f} "
            f"centroid={rec['centroid_offset_pix_control_percentile']} "
            f"momentR={rec['moment_radius_pix_control_percentile']}"
        )

    payload = {
        "stage": "ORDER01_DASCH_PHYSICAL_PIXEL_MORPHOLOGY_V028AR",
        "plate": PLATE,
        "ranks": RANKS,
        "guards": {
            "network_access": False,
            "science_pixels_read": True,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "physical_polarity_inferred_from_official_same_plate_sources": True,
            "science_pixels_not_used_to_infer_physical_polarity": True,
            "native_local_global_coordinate_guard": True,
        },
        "empirical_physical_polarity": "RAW_HIGH" if physical_polarity == 1 else "RAW_LOW",
        "official_control_count": len(controls),
        "official_control_sign_agreement_fraction": sign_frac,
        "official_controls": controls,
        "science": summaries,
        "interpretive_boundary": (
            "v028ar reads actual DASCH science pixels and compares raw morphology "
            "with official DR7 source images on the same physical plate. Similarity "
            "can support a recorded stellar-image interpretation; abnormal or "
            "opposite-polarity morphology can support a plate/scanning/detector "
            "mechanism. Neither morphology alone establishes astrophysical transience."
        )
    }
    write_json(OUT_JSON, payload)
    write_csv(OUT_SUMMARY, summaries, list(summaries[0]))
    write_csv(OUT_CONTROLS, controls, list(controls[0]))

    md = [
        "# ORDER 01 — DASCH Physical-Pixel Morphology v028ar","",
        "## Guard state","",
        "- No network access.",
        "- **Science pixels were read.**",
        "- The frozen transient detector was not rerun.",
        "- No endpoint was promoted, deleted, or otherwise mutated.",
        "- Physical polarity was inferred only from official same-plate DR7 sources.",
        "- Science pixels were not used to infer ordinary-source polarity.","",
        f"Official same-plate controls: **{len(controls)}**.",
        f"Empirical ordinary-source polarity: **{'RAW_HIGH' if physical_polarity == 1 else 'RAW_LOW'}**.",
        f"Control sign agreement: **{sign_agree}/{len(strong_signs)}**.","",
        "## Science morphology","",
        "| rank | center 3x3 | ap5 signed | centroid offset | moment radius | descriptor |",
        "|---:|---:|---:|---:|---:|---|"
    ]
    for r in summaries:
        cent_txt = "—" if r["centroid_offset_pix"] is None else f"{r['centroid_offset_pix']:.2f} px"
        mr_txt = "—" if r["moment_radius_pix"] is None else f"{r['moment_radius_pix']:.2f} px"
        md.append(
            f"| #{r['strict_rank']} | {r['center3_signed_zmean']:+.3f} z | "
            f"{r['ap5_signed_zsum']:+.3f} | {cent_txt} | {mr_txt} | "
            f"{r['descriptive_morphology']} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_SUMMARY}")
    print(f"  {OUT_CONTROLS}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
