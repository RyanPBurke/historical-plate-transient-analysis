#!/usr/bin/env python3
"""Build public launch and photographic-plate metadata catalogues."""

from __future__ import annotations

import csv
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
USER_AGENT = "Transients-Villarroel-reproducibility/1.0 (research use)"
EXPECTED = {1951: 61, 1952: 56, 1953: 88, 1954: 95, 1955: 156}
EXPECTED_BY_ROCKET = {
    1951: {"R-2": 13},
    1952: {"R-1": 7, "R-2": 14},
    1953: {"R-1": 23, "R-2": 4},
    1954: {"R-1": 22, "R-2": 23},
    1955: {
        "R-2": 42, "R-5": 8, "R-5M": 24, "Nike-Deacon": 3,
        "X-17": 3, "Nike-Nike-T40-T55": 2,
        "Nike-Nike-Tri-Deacon-T40": 1,
    },
}


def get(url: str, data: bytes | None = None, attempts: int = 5) -> bytes:
    last = None
    for n in range(attempts):
        try:
            req = Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=180) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            time.sleep(2**n)
    raise RuntimeError(f"Failed to retrieve {url}: {last}")


def clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def first_nonempty(values) -> str:
    for value in values:
        value = clean(value)
        if value:
            return value
    return ""


def parse_launch_date(raw: str, year: int) -> tuple[str, str, str]:
    raw = clean(raw)
    match = re.search(
        r"(?P<day>\d{1,2})\s+(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+(?P<clock>\d{1,2}:\d{2}(?::\d{2})?))?",
        raw,
    )
    if not match:
        return "", "", "unknown"
    date = datetime.strptime(
        f"{match.group('day')} {match.group('month')} {year}", "%d %B %Y"
    ).date().isoformat()
    clock = match.group("clock") or ""
    iso = f"{date}T{clock}:00Z" if clock and clock.count(":") == 1 else (
        f"{date}T{clock}Z" if clock else ""
    )
    return date, iso, "minute" if clock else "day"


def build_launches() -> pd.DataFrame:
    output = []
    for year in EXPECTED:
        url = f"https://en.wikipedia.org/wiki/{year}_in_spaceflight?printable=yes"
        tables = pd.read_html(io.BytesIO(get(url)))
        annual = []
        for table in tables:
            columns = [tuple(map(str, c)) if isinstance(c, tuple) else (str(c),) for c in table.columns]
            if len(table.columns) != 8 or not any("Date and time" in " ".join(c) for c in columns):
                continue
            date_col = table.columns[0]
            for raw_date, group in table.groupby(date_col, sort=False, dropna=False):
                date_text = clean(raw_date)
                if not date_text or date_text.lower() == "nan":
                    continue
                rows = group.reset_index(drop=True)
                rocket = first_nonempty(rows.iloc[:, 1])
                if not rocket:
                    continue
                launch_date, launch_iso, precision = parse_launch_date(date_text, year)
                top = rows.iloc[0]
                detail = rows.iloc[2] if len(rows) > 2 else pd.Series([""] * 8)
                remarks = first_nonempty(rows.iloc[3:, 2].tolist()) if len(rows) > 3 else ""
                payload = clean(top.iloc[2])
                if payload == rocket:
                    payload = ""
                annual.append({
                    "year": year,
                    "launch_date_utc": launch_date,
                    "launch_datetime_utc": launch_iso,
                    "time_precision": precision,
                    "raw_date_time": date_text,
                    "rocket": rocket,
                    "payload": payload,
                    "flight_number": clean(top.iloc[3]),
                    "launch_site": clean(top.iloc[4]),
                    "launch_service_provider": clean(top.iloc[6]),
                    "operator": clean(detail.iloc[3]),
                    "trajectory_class": clean(detail.iloc[4]) or "Suborbital",
                    "function": clean(detail.iloc[5]),
                    "decay_or_impact_date_utc": clean(detail.iloc[6]) or launch_date,
                    "outcome": clean(detail.iloc[7]),
                    "remarks": remarks,
                    "source_url": url.replace("?printable=yes", ""),
                    "source_tier": "compiled_event_table",
                })
        # Some source tables collapse a missile-test series into one dated row
        # while the annual statistics count every firing. Preserve that fact by
        # adding explicitly unresolved aggregate members; do not invent dates.
        normalized_counts = {}
        for row in annual:
            key = re.sub(r"\[.*?\]", "", row["rocket"]).replace("Rockoon", "rockoon").strip()
            normalized_counts[key] = normalized_counts.get(key, 0) + 1
        for rocket, expected_count in EXPECTED_BY_ROCKET.get(year, {}).items():
            missing = expected_count - normalized_counts.get(rocket, 0)
            for sequence in range(1, max(0, missing) + 1):
                annual.append({
                    "year": year, "launch_date_utc": "", "launch_datetime_utc": "",
                    "time_precision": "year_only_aggregate", "raw_date_time": "",
                    "rocket": rocket, "payload": "", "flight_number": "",
                    "launch_site": "", "launch_service_provider": "",
                    "operator": "", "trajectory_class": "Suborbital",
                    "function": "Missile test", "decay_or_impact_date_utc": "",
                    "outcome": "",
                    "remarks": f"Aggregate series member {sequence}/{missing}; individual date not enumerated in source event table",
                    "source_url": url.replace("?printable=yes", ""),
                    "source_tier": "annual_statistics_reconciliation",
                })
        if len(annual) != EXPECTED[year]:
            raise RuntimeError(f"{year}: reconciled {len(annual)} launches; expected {EXPECTED[year]}")
        output.extend(annual)
    frame = pd.DataFrame(output)
    frame.insert(0, "launch_id", [f"L{n:04d}" for n in range(1, len(frame) + 1)])
    frame.to_csv(DATA / "launches_1951_1955.csv", index=False)
    return frame


def parse_votable(payload: bytes) -> pd.DataFrame:
    root = ET.fromstring(payload)
    ns = {"v": "http://www.ivoa.net/xml/VOTable/v1.3"}
    fields = [x.attrib.get("name", "") for x in root.findall(".//v:FIELD", ns)]
    rows = []
    for tr in root.findall(".//v:TR", ns):
        values = [(td.text or "").strip() for td in tr.findall("v:TD", ns)]
        rows.append(values)
    if not rows:
        info = [x.text for x in root.findall(".//v:INFO", ns)]
        raise RuntimeError(f"TAP query returned no rows: {info}")
    return pd.DataFrame(rows, columns=fields)


def tap_query(endpoint: str, query: str, fmt: str = "votable") -> bytes:
    request = urlencode({
        "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": fmt,
        "RESPONSEFORMAT": fmt, "QUERY": query,
    }).encode()
    return get(endpoint, data=request)


def build_applause() -> pd.DataFrame:
    endpoint = "https://www.plate-archive.org/tap/sync"
    exposure_query = (
        "SELECT exposure_id,plate_id,archive_id,ra_icrs,dec_icrs,"
        "date_orig_start,date_orig_end,time_orig_start,time_orig_end,"
        "ut_start,ut_mid,ut_end,jd_start,jd_mid,jd_end,exptime,flag_time "
        "FROM applause_dr4.exposure"
    )
    archive_query = "SELECT archive_id,archive_name,institute,num_plates,num_scans FROM applause_dr4.archive"
    exposures = parse_votable(tap_query(endpoint, exposure_query))
    archives = parse_votable(tap_query(endpoint, archive_query))
    exposures = exposures.merge(archives, how="left", on="archive_id")
    dates = pd.to_datetime(exposures["date_orig_start"], errors="coerce", utc=True)
    exposures = exposures[(dates >= "1951-01-01") & (dates < "1956-01-01")].copy()
    exposures["obs_start_utc"] = exposures["ut_start"].fillna("").str.replace(" ", "T", regex=False) + "Z"
    exposures["obs_end_utc"] = exposures["ut_end"].fillna("").str.replace(" ", "T", regex=False) + "Z"
    exposures["time_precision"] = exposures["ut_start"].apply(lambda x: "calibrated_ut" if clean(x) else "missing_calibrated_ut")
    exposures["source_archive"] = "APPLAUSE DR4"
    exposures["source_url"] = "https://www.plate-archive.org/tap/"
    exposures.to_csv(DATA / "applause_exposures_1951_1955.csv", index=False)
    return exposures


def unix_to_mjd(dt: datetime) -> float:
    return 40587.0 + dt.replace(tzinfo=timezone.utc).timestamp() / 86400.0


def build_dasch() -> pd.DataFrame:
    endpoint = "https://dc.g-vo.org/tap/sync"
    lo = unix_to_mjd(datetime(1951, 1, 1))
    hi = unix_to_mjd(datetime(1956, 1, 1))
    frames = []
    for table in ("dasch.wide_plates", "dasch.narrow_plates"):
        query = (
            "SELECT obs_id,obs_title,access_url,s_ra,s_dec,s_fov,t_min,t_max,t_exptime,"
            "facility_name,instrument_name,dasch_id,plate_class "
            f"FROM {table} WHERE t_min >= {lo:.6f} AND t_min < {hi:.6f}"
        )
        payload = tap_query(endpoint, query, "text/csv").decode("utf-8", "replace")
        columns = [
            "obs_id", "obs_title", "access_url", "s_ra", "s_dec", "s_fov",
            "t_min", "t_max", "t_exptime", "facility_name", "instrument_name",
            "dasch_id", "plate_class",
        ]
        # This TAP service's CSV serialization omits a header row.
        frame = pd.read_csv(io.StringIO(payload), header=None, names=columns)
        frame["dasch_table"] = table
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    epoch = pd.Timestamp("1858-11-17T00:00:00Z")
    result["obs_start_utc"] = result["t_min"].apply(lambda x: (epoch + pd.to_timedelta(float(x), unit="D")).isoformat())
    result["obs_end_utc"] = result["t_max"].apply(lambda x: (epoch + pd.to_timedelta(float(x), unit="D")).isoformat())
    result["source_archive"] = "Harvard DASCH"
    result["source_url"] = "https://dc.g-vo.org/tap"
    result.to_csv(DATA / "dasch_exposures_1951_1955.csv", index=False)
    return result


def build_poss() -> pd.DataFrame:
    url = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=VI/25&-out.all=1"
    payload = get(url).decode("utf-8", "replace")
    if "QUERY_STATUS=ERROR" in payload or "# -- no connection" in payload:
        raise RuntimeError("VizieR returned a service/database error for VI/25")
    lines = [line for line in payload.splitlines() if not line.startswith("Content-") and not line.startswith("DocumentRef:")]
    frame = pd.read_csv(io.StringIO("\n".join(lines)), sep="\t", comment="#", dtype=str)
    frame = frame.dropna(how="all")
    frame["source_archive"] = "POSS-I VI/25"
    frame["source_url"] = "https://cdsarc.cds.unistra.fr/viz-bin/cat/VI/25"
    frame.to_csv(DATA / "poss1_plate_metadata.csv", index=False)
    return frame


def main() -> int:
    builders = [build_launches, build_applause, build_dasch, build_poss]
    failures = []
    for builder in builders:
        try:
            result = builder()
            print(f"{builder.__name__}: {len(result)} rows")
        except Exception as exc:
            failures.append((builder.__name__, str(exc)))
            print(f"ERROR {builder.__name__}: {exc}", file=sys.stderr)
    if failures:
        print("Some public endpoints were unavailable; rerun to complete:", failures, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
