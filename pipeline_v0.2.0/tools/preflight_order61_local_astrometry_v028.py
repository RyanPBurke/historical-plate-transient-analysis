from __future__ import annotations

from pathlib import Path
import csv
import json
import math
import hashlib

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

STAGE3_REPORT = BASE / "order61_platephot_stage3_report.json"
STAGE3_POLICY = BASE / "order61_platephot_stage3_policy.json"

POSS = BASE / "order61_poss_native_candidates.csv"
DASCH = BASE / "order61_dasch_native_candidates.csv"
RAW = BASE / "order61_raw_coincidences.csv"
GAIA_TRIAGE = BASE / "order61_gaia_static_triage.csv"
GAIA_SOURCES = BASE / "order61_gaia_source_candidates.csv"
MORPH = BASE / "order61_survivor_native_morphology.csv"

OUT = BASE / "order61_local_astrometry_preflight_v028.json"

EXPECTED_ACTIVE = [11, 14, 20]
RADII_ARCMIN = [5, 10, 20, 30]


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
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def find_col(fieldnames, aliases):
    by = {norm(x): x for x in fieldnames}
    for a in aliases:
        if norm(a) in by:
            return by[norm(a)]
    return None


def ffloat(v):
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def sep_arcsec(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, [ra1, dec1, ra2, dec2])
    dr = r2 - r1
    while dr > math.pi:
        dr -= 2 * math.pi
    while dr < -math.pi:
        dr += 2 * math.pi
    a = (
        math.sin((d2 - d1) / 2) ** 2
        + math.cos(d1) * math.cos(d2) * math.sin(dr / 2) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2 * math.asin(math.sqrt(a)) * 206264.80624709636


def midpoint(ra1, dec1, ra2, dec2):
    # Cartesian spherical midpoint.
    def vec(ra, dec):
        rr, dd = math.radians(ra), math.radians(dec)
        return (
            math.cos(dd) * math.cos(rr),
            math.cos(dd) * math.sin(rr),
            math.sin(dd),
        )
    a = vec(ra1, dec1)
    b = vec(ra2, dec2)
    x, y, z = (a[0]+b[0], a[1]+b[1], a[2]+b[2])
    n = math.sqrt(x*x+y*y+z*z)
    x, y, z = x/n, y/n, z/n
    return (
        math.degrees(math.atan2(y, x)) % 360.0,
        math.degrees(math.atan2(z, math.sqrt(x*x+y*y))),
    )


def inspect_candidate_table(path: Path, archive_name: str):
    rows = read_csv(path)
    if not rows:
        raise RuntimeError(f"{archive_name}: empty candidate table")
    fields = list(rows[0].keys())

    ra_col = find_col(fields, ["ra_deg", "ra", "ra_icrs", "world_ra_deg"])
    dec_col = find_col(fields, ["dec_deg", "dec", "dec_icrs", "world_dec_deg"])
    x_col = find_col(fields, ["x", "x_px", "global_x", "x_global"])
    y_col = find_col(fields, ["y", "y_px", "global_y", "y_global"])
    snr_col = find_col(fields, ["snr"])
    pol_col = find_col(fields, ["polarity"])
    tile_col = find_col(fields, ["tile_id", "tile", "tile_key"])

    if ra_col is None or dec_col is None:
        raise RuntimeError(
            f"{archive_name}: could not locate sky coordinate columns; "
            f"fields={fields}"
        )

    return {
        "rows": rows,
        "fields": fields,
        "ra_col": ra_col,
        "dec_col": dec_col,
        "x_col": x_col,
        "y_col": y_col,
        "snr_col": snr_col,
        "pol_col": pol_col,
        "tile_col": tile_col,
    }


def main():
    print("=" * 94)
    print("ORDER 61 — LOCAL ASTROMETRY / PLATE-SYSTEMATICS PREFLIGHT v028")
    print("=" * 94)
    print("Read-only science preflight: no detector, no image pixels, no catalogue query.")
    print()

    required = [
        STAGE3_REPORT, STAGE3_POLICY, POSS, DASCH, RAW,
        GAIA_TRIAGE, GAIA_SOURCES, MORPH,
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("Missing required files:\n  " + "\n  ".join(missing))

    report = json.loads(STAGE3_REPORT.read_text(encoding="utf-8"))
    policy = json.loads(STAGE3_POLICY.read_text(encoding="utf-8"))

    by_rank = {
        int(r["strict_rank"]): r
        for r in report.get("active_rank_summaries_cumulative_1024", [])
    }

    guards = {
        "stage3_complete": report.get("status") == "COMPLETE",
        "active_ranks": sorted(by_rank) == EXPECTED_ACTIVE,
        "all_1024_complete": all(
            int(by_rank[r]["cumulative_completed_plates"]) == 1024
            for r in EXPECTED_ACTIVE
        ),
        "all_zero_within5": all(
            int(by_rank[r]["observed_sources_within_5arcsec"]) == 0
            for r in EXPECTED_ACTIVE
        ),
        "detector_not_rerun": report.get("detector_rerun") is False,
        "science_pixels_not_read_stage3": (
            report.get("science_image_pixels_read") is False
        ),
        "fixed_strong_gate": float(policy.get("strong_arcsec")) == 3.0,
        "fixed_diag_gate": float(policy.get("diagnostic_arcsec")) == 5.0,
        "blind_ordering": policy.get("selection_uses_stage3_outcomes") is False,
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: Stage-3 guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    poss = inspect_candidate_table(POSS, "POSS")
    dasch = inspect_candidate_table(DASCH, "DASCH")
    raw = read_csv(RAW)
    gaia = read_csv(GAIA_TRIAGE)
    gs = read_csv(GAIA_SOURCES)
    morph = read_csv(MORPH)

    print("Stage-3 guards: PASS")
    print(
        f"POSS candidates:  {len(poss['rows']):,} "
        f"RA={poss['ra_col']} DEC={poss['dec_col']} "
        f"X={poss['x_col']} Y={poss['y_col']} TILE={poss['tile_col']}"
    )
    print(
        f"DASCH candidates: {len(dasch['rows']):,} "
        f"RA={dasch['ra_col']} DEC={dasch['dec_col']} "
        f"X={dasch['x_col']} Y={dasch['y_col']} TILE={dasch['tile_col']}"
    )
    print(f"Raw <=10\" coincidence rows: {len(raw):,}")
    print(f"Gaia triage rows:             {len(gaia):,}")
    print(f"Gaia source audit rows:       {len(gs):,}")
    print(f"Morphology rows:              {len(morph):,}")
    print()

    if not gaia:
        raise RuntimeError("Gaia triage is empty")
    gf = list(gaia[0].keys())
    rank_col = find_col(gf, ["strict_rank", "rank"])
    pra_col = find_col(gf, ["poss_ra_deg", "poss_ra"])
    pdec_col = find_col(gf, ["poss_dec_deg", "poss_dec"])
    dra_col = find_col(gf, ["dasch_ra_deg", "dasch_ra"])
    ddec_col = find_col(gf, ["dasch_dec_deg", "dasch_dec"])

    needed = [rank_col, pra_col, pdec_col, dra_col, ddec_col]
    if any(x is None for x in needed):
        raise RuntimeError(
            "Gaia triage lacks survivor endpoint coordinate schema; "
            f"fields={gf}"
        )

    gby = {int(r[rank_col]): r for r in gaia}

    local = {}
    for rank in EXPECTED_ACTIVE:
        if rank not in gby:
            raise RuntimeError(f"Missing Gaia triage survivor rank {rank}")

        gr = gby[rank]
        pra = float(gr[pra_col])
        pdec = float(gr[pdec_col])
        dra = float(gr[dra_col])
        ddec = float(gr[ddec_col])
        mra, mdec = midpoint(pra, pdec, dra, ddec)

        counts = {"POSS": {}, "DASCH": {}}
        for archive_name, tab in [("POSS", poss), ("DASCH", dasch)]:
            rr = tab["ra_col"]
            dd = tab["dec_col"]
            seps = []
            bad = 0
            for row in tab["rows"]:
                ra = ffloat(row.get(rr))
                dec = ffloat(row.get(dd))
                if ra is None or dec is None:
                    bad += 1
                    continue
                seps.append(sep_arcsec(mra, mdec, ra, dec))
            for radius in RADII_ARCMIN:
                counts[archive_name][f"{radius}arcmin"] = sum(
                    s <= radius * 60.0 for s in seps
                )
            counts[archive_name]["nonfinite_sky_rows"] = bad

        local[rank] = {
            "poss_ra_deg": pra,
            "poss_dec_deg": pdec,
            "dasch_ra_deg": dra,
            "dasch_dec_deg": ddec,
            "midpoint_ra_deg": mra,
            "midpoint_dec_deg": mdec,
            "candidate_pair_sep_arcsec": sep_arcsec(pra, pdec, dra, ddec),
            "local_detector_candidate_counts": counts,
        }

        print(
            f"strict #{rank:02d}: pairsep="
            f"{local[rank]['candidate_pair_sep_arcsec']:.3f}\" "
            f"mid=({mra:.6f},{mdec:.6f})"
        )
        print(
            "  POSS local candidates : "
            + ", ".join(
                f"{r}'={counts['POSS'][f'{r}arcmin']}"
                for r in RADII_ARCMIN
            )
        )
        print(
            "  DASCH local candidates: "
            + ", ".join(
                f"{r}'={counts['DASCH'][f'{r}arcmin']}"
                for r in RADII_ARCMIN
            )
        )

    print()

    poss_tiles = ROOT / "work" / "order61_native_full_v028" / "poss_tiles"
    dasch_tiles = ROOT / "work" / "order61_native_full_v028" / "dasch_tiles"

    tile_inventory = {}
    for name, d in [("POSS", poss_tiles), ("DASCH", dasch_tiles)]:
        npys = sorted(d.rglob("*.npy")) if d.is_dir() else []
        metas = sorted(d.rglob("*.json")) if d.is_dir() else []
        csvs = sorted(d.rglob("*.csv")) if d.is_dir() else []
        tile_inventory[name] = {
            "directory": str(d),
            "exists": d.is_dir(),
            "npy_count": len(npys),
            "meta_json_count": len(metas),
            "candidate_csv_count": len(csvs),
            "sample_npy_names": [p.name for p in npys[:5]],
        }
        print(
            f"{name} native tile cache: exists={d.is_dir()} "
            f"NPY={len(npys)} JSON={len(metas)} CSV={len(csvs)}"
        )

    out = {
        "status": "COMPLETE",
        "analysis_kind": "order61_local_astrometry_preflight_v028",
        "guards": guards,
        "stage3_report_sha256": sha256_file(STAGE3_REPORT),
        "stage3_policy_sha256": sha256_file(STAGE3_POLICY),
        "tables": {
            "poss": {
                "path": str(POSS),
                "rows": len(poss["rows"]),
                "fields": poss["fields"],
                "resolved_columns": {
                    k: poss[k] for k in [
                        "ra_col", "dec_col", "x_col", "y_col",
                        "snr_col", "pol_col", "tile_col"
                    ]
                },
            },
            "dasch": {
                "path": str(DASCH),
                "rows": len(dasch["rows"]),
                "fields": dasch["fields"],
                "resolved_columns": {
                    k: dasch[k] for k in [
                        "ra_col", "dec_col", "x_col", "y_col",
                        "snr_col", "pol_col", "tile_col"
                    ]
                },
            },
            "raw": {
                "path": str(RAW),
                "rows": len(raw),
                "fields": list(raw[0].keys()) if raw else [],
            },
            "gaia_triage": {
                "path": str(GAIA_TRIAGE),
                "rows": len(gaia),
                "fields": gf,
            },
            "gaia_sources": {
                "path": str(GAIA_SOURCES),
                "rows": len(gs),
                "fields": list(gs[0].keys()) if gs else [],
            },
            "morphology": {
                "path": str(MORPH),
                "rows": len(morph),
                "fields": list(morph[0].keys()) if morph else [],
            },
        },
        "survivor_local_inventory": local,
        "native_tile_inventory": tile_inventory,
        "next_stage": (
            "Build prospectively fixed local astrometric/systematics adjudication "
            "using nearby static reference stars on the discovery plates. "
            "Do not change the detector or the predeclared 3/5 arcsec recurrence gates."
        ),
        "detector_rerun": False,
        "image_pixels_read": False,
    }

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT)

    print()
    print("=" * 94)
    print("LOCAL ASTROMETRY / PLATE-SYSTEMATICS PREFLIGHT COMPLETE")
    print("=" * 94)
    print("Output:")
    print(" ", OUT)
    print()
    print("No detector was rerun.")
    print("No image pixel was read.")
    print("No science candidate was deleted.")


if __name__ == "__main__":
    main()
