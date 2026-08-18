#!/usr/bin/env python3
"""Create conservative archive-pair and launch/date candidate matrices."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


def angular_sep(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    value = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, value))))


def load_exposures() -> pd.DataFrame:
    frames = []
    applause_path = DATA / "applause_exposures_1951_1955.csv"
    if applause_path.exists():
        a = pd.read_csv(applause_path, low_memory=False)
        a = pd.DataFrame({
            "exposure_id": "APPLAUSE:" + a["exposure_id"].astype(str),
            "archive": a["archive_name"].fillna("APPLAUSE archive " + a["archive_id"].astype(str)),
            "site": a["institute"].fillna(a["archive_name"]),
            "ra_deg": pd.to_numeric(a["ra_icrs"], errors="coerce"),
            "dec_deg": pd.to_numeric(a["dec_icrs"], errors="coerce"),
            "fov_diameter_deg": 5.0,
            "start": pd.to_datetime(a["obs_start_utc"], errors="coerce", utc=True),
            "duration_s": pd.to_numeric(a["exptime"], errors="coerce"),
            "access_url": "https://www.plate-archive.org/",
            "precision": a["time_precision"],
        })
        frames.append(a)
    dasch_path = DATA / "dasch_exposures_1951_1955.csv"
    if dasch_path.exists():
        d = pd.read_csv(dasch_path, low_memory=False)
        d = pd.DataFrame({
            "exposure_id": "DASCH:" + d["obs_id"].astype(str),
            "archive": "Harvard DASCH",
            # GAVO's facility_name identifies the holding institution rather
            # than reliably identifying the historical observing station.
            "site": "DASCH historical observing site unresolved",
            "ra_deg": pd.to_numeric(d["s_ra"], errors="coerce"),
            "dec_deg": pd.to_numeric(d["s_dec"], errors="coerce"),
            "fov_diameter_deg": pd.to_numeric(d["s_fov"], errors="coerce"),
            "start": pd.to_datetime(d["obs_start_utc"], errors="coerce", utc=True),
            "duration_s": pd.to_numeric(d["t_exptime"], errors="coerce"),
            "access_url": d["access_url"],
            "precision": "service_timestamp",
        })
        frames.append(d)
    poss_path = DATA / "poss1_plate_metadata.csv"
    if poss_path.exists():
        p = pd.read_csv(poss_path, low_memory=False, dtype=str)
        p = p[p["Obs"].astype(str).str.match(r"^19\d\d-\d\d-\d\d$")].copy()

        def hms_to_deg(value):
            try:
                h, m, s = map(float, str(value).split())
                return 15.0 * (h + m / 60.0 + s / 3600.0)
            except Exception:
                return math.nan

        def dms_to_deg(value):
            try:
                parts = str(value).split()
                sign = -1 if parts[0].startswith("-") else 1
                d = abs(float(parts[0])); m = float(parts[1]); s = float(parts[2])
                return sign * (d + m / 60.0 + s / 3600.0)
            except Exception:
                return math.nan

        p["ra_parsed"] = p["_RA.icrs"].apply(hms_to_deg)
        p["dec_parsed"] = p["_DE.icrs"].apply(dms_to_deg)
        for band, time_col, exp_col in (("E", "ObsE", "Eexp"), ("O", "ObsO", "Oexp")):
            start_text = p["Obs"] + "T" + p[time_col].fillna("") + "Z"
            band_frame = pd.DataFrame({
                "exposure_id": "POSS-I:" + p["POSS"].astype(str).str.strip() + ":" + band,
                "archive": "POSS-I Palomar",
                "site": "Palomar Observatory",
                "ra_deg": p["ra_parsed"], "dec_deg": p["dec_parsed"],
                "fov_diameter_deg": 6.5,
                "start": pd.to_datetime(start_text, errors="coerce", utc=True),
                "duration_s": pd.to_numeric(p[exp_col], errors="coerce") * 60.0,
                "access_url": "https://archive.stsci.edu/dss/",
                "precision": "catalog_recorded_time_basis_verify",
            })
            frames.append(band_frame)
    if not frames:
        raise RuntimeError("No exposure catalogues found; run build_catalogues.py")
    result = pd.concat(frames, ignore_index=True)
    result["duration_s"] = result["duration_s"].fillna(0)
    result["midpoint"] = result["start"] + pd.to_timedelta(result["duration_s"] / 2, unit="s")
    return result.dropna(subset=["ra_deg", "dec_deg", "midpoint"])


def build_pairs(exposures: pd.DataFrame, max_minutes=30.0) -> pd.DataFrame:
    e = exposures.sort_values("midpoint").reset_index(drop=True)
    pairs = []
    window = pd.Timedelta(minutes=max_minutes)
    for i, left in e.iterrows():
        candidates = e.iloc[i + 1:]
        candidates = candidates[candidates["midpoint"] - left["midpoint"] <= window]
        candidates = candidates[candidates["site"] != left["site"]]
        for _, right in candidates.iterrows():
            separation = angular_sep(left.ra_deg, left.dec_deg, right.ra_deg, right.dec_deg)
            radius_sum = (left.fov_diameter_deg + right.fov_diameter_deg) / 2
            if separation <= radius_sum:
                pairs.append({
                    "exposure_a": left.exposure_id, "archive_a": left.archive, "site_a": left.site,
                    "start_a_utc": left.start.isoformat(), "duration_a_s": left.duration_s,
                    "end_a_utc": (left.start + pd.to_timedelta(left.duration_s, unit="s")).isoformat(),
                    "time_precision_a": left.precision,
                    "ra_a_deg": left.ra_deg, "dec_a_deg": left.dec_deg,
                    "fov_a_deg": left.fov_diameter_deg, "access_a": left.access_url,
                    "exposure_b": right.exposure_id, "archive_b": right.archive, "site_b": right.site,
                    "start_b_utc": right.start.isoformat(), "duration_b_s": right.duration_s,
                    "end_b_utc": (right.start + pd.to_timedelta(right.duration_s, unit="s")).isoformat(),
                    "time_precision_b": right.precision,
                    "ra_b_deg": right.ra_deg, "dec_b_deg": right.dec_deg,
                    "fov_b_deg": right.fov_diameter_deg, "access_b": right.access_url,
                    "midpoint_delta_minutes": abs((right.midpoint - left.midpoint).total_seconds()) / 60,
                    "center_separation_deg": separation,
                    "classification": "candidate_independent_overlap",
                    "validation_needed": "inspect logbooks; verify timestamp precision; use true footprint; inspect pixels",
                })
    return pd.DataFrame(pairs)


def build_triplets(pairs: pd.DataFrame) -> pd.DataFrame:
    if pairs.empty:
        return pd.DataFrame()
    edge = {}
    metadata = {}
    for _, row in pairs.iterrows():
        a, b = sorted((row.exposure_a, row.exposure_b))
        edge[(a, b)] = row
        metadata[row.exposure_a] = (row.archive_a, row.site_a, row.start_a_utc)
        metadata[row.exposure_b] = (row.archive_b, row.site_b, row.start_b_utc)
    neighbors = {}
    for a, b in edge:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    triplets = []
    seen = set()
    for a, near in neighbors.items():
        for b in near:
            common = near.intersection(neighbors.get(b, set()))
            for c in common:
                ids = tuple(sorted((a, b, c)))
                if ids in seen:
                    continue
                seen.add(ids)
                sites = {metadata[x][1] for x in ids}
                if len(sites) < 3:
                    continue
                triplets.append({
                    "exposure_a": ids[0], "archive_a": metadata[ids[0]][0], "site_a": metadata[ids[0]][1], "start_a_utc": metadata[ids[0]][2],
                    "exposure_b": ids[1], "archive_b": metadata[ids[1]][0], "site_b": metadata[ids[1]][1], "start_b_utc": metadata[ids[1]][2],
                    "exposure_c": ids[2], "archive_c": metadata[ids[2]][0], "site_c": metadata[ids[2]][1], "start_c_utc": metadata[ids[2]][2],
                    "classification": "candidate_three_site_pairwise_overlap",
                    "validation_needed": "verify three timestamps and true footprint intersection; inspect all pixels",
                })
    return pd.DataFrame(triplets)


def build_launch_screen(exposures: pd.DataFrame, days=1) -> pd.DataFrame:
    launches = pd.read_csv(DATA / "launches_1951_1955.csv", low_memory=False)
    launches["launch_day"] = pd.to_datetime(launches["launch_date_utc"], errors="coerce", utc=True)
    exp = exposures.copy()
    exp["obs_day"] = exp["start"].dt.floor("D")
    # Join on explicit date keys rather than materializing a 14M-row cross join.
    chunks = []
    for offset in range(-days, days + 1):
        keyed = launches.dropna(subset=["launch_day"]).copy()
        keyed["obs_day"] = keyed["launch_day"] + pd.to_timedelta(offset, unit="D")
        part = exp.merge(keyed, on="obs_day", how="inner")
        part["delta_days"] = offset
        chunks.append(part)
    matches = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    columns = [
        "exposure_id", "archive", "site", "start", "ra_deg", "dec_deg",
        "launch_id", "launch_datetime_utc", "launch_date_utc", "rocket", "flight_number",
        "launch_site", "outcome", "delta_days", "source_url",
    ]
    matches = matches[columns]
    matches["classification"] = "date_screen_only"
    matches["geometric_visibility"] = "not_evaluated"
    return matches


def main():
    exposures = load_exposures()
    pairs = build_pairs(exposures, max_minutes=30.0)
    same_night_pairs = build_pairs(exposures, max_minutes=360.0)
    triplets = build_triplets(same_night_pairs)
    screen = build_launch_screen(exposures)
    pairs.to_csv(RESULTS / "archive_pair_overlap_candidates.csv", index=False)
    same_night_pairs.to_csv(RESULTS / "archive_pair_same_night_candidates.csv", index=False)
    triplets.to_csv(RESULTS / "archive_triplet_overlap_candidates.csv", index=False)
    screen.to_csv(RESULTS / "launch_plate_date_candidates.csv", index=False)
    print(f"normalized exposures: {len(exposures)}")
    print(f"pair candidates: {len(pairs)}")
    print(f"same-night pair candidates: {len(same_night_pairs)}")
    print(f"same-night triplet candidates: {len(triplets)}")
    print(f"launch/date candidates: {len(screen)}")


if __name__ == "__main__":
    main()
