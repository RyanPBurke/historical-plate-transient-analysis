from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import csv
import hashlib
import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Iterable

from .checkpoint import Job
from .http import InvalidRemotePayload, RetryPolicy, RetryableRemoteError, ValidatedSession
from .provenance import EvidenceStore, ExchangeContext, atomic_write_bytes, atomic_write_text, sha256_bytes, utcnow
from .poss1_skyview import fallback_identity as skyview_fallback_identity

PLATE_FINDER = "https://archive.stsci.edu/cgi-bin/dss_plate_finder"
PST = timezone(timedelta(hours=-8))


@dataclass(frozen=True)
class VI25Record:
    recno: int
    poss: str
    mlp: str
    obs: str
    fobs: str
    obse: str
    obso: str
    eexp_min: float | None
    oexp_min: float | None
    ra_icrs: str = ""
    dec_icrs: str = ""


@dataclass(frozen=True)
class FinderCandidate:
    plate_id: str
    survey: str
    row_text: str
    exposure_min: float
    region: str
    epoch_date: str
    epoch_clock_raw: str
    plate_scale_arcsec_px: float | None


def parse_exposure_key(value: str) -> tuple[str, str, int]:
    m = re.fullmatch(r"POSS-I:([^:]+):([EO]):rec(\d+)", str(value).strip(), flags=re.I)
    if not m:
        raise ValueError(f"invalid POSS-I exposure key: {value!r}")
    return m.group(1), m.group(2).upper(), int(m.group(3))


def load_vi25_records(path: str | Path) -> dict[int, VI25Record]:
    path = Path(path)
    out: dict[int, VI25Record] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw = (row.get("recno") or "").strip()
            if not raw.isdigit():
                continue
            recno = int(raw)
            def fnum(name: str) -> float | None:
                v = (row.get(name) or "").strip()
                if not v:
                    return None
                try:
                    return float(v)
                except ValueError:
                    return None
            out[recno] = VI25Record(
                recno=recno,
                poss=(row.get("POSS") or "").strip(),
                mlp=(row.get("MLP") or "").strip(),
                obs=(row.get("Obs") or "").strip(),
                fobs=(row.get("fObs") or "").strip(),
                obse=(row.get("ObsE") or "").strip(),
                obso=(row.get("ObsO") or "").strip(),
                eexp_min=fnum("Eexp"),
                oexp_min=fnum("Oexp"),
                ra_icrs=(row.get("_RA.icrs") or "").strip(),
                dec_icrs=(row.get("_DE.icrs") or "").strip(),
            )
    if not out:
        raise ValueError(f"no VI/25 records parsed from {path}")
    return out


def _parse_initial_date(obs: str) -> date:
    return datetime.strptime(obs.strip(), "%Y-%m-%d").date()


def _parse_final_date(initial: date, fobs: str) -> date:
    s = fobs.strip()
    # VizieR renders the year-less final date as forms such as 0-11-05.
    m = re.search(r"(\d{1,2})-(\d{1,2})$", s)
    if not m:
        raise ValueError(f"could not parse VI/25 fObs={fobs!r}")
    month, day = map(int, m.groups())
    year = initial.year
    candidate = date(year, month, day)
    if candidate < initial:
        candidate = date(year + 1, month, day)
    return candidate


def _parse_hhmm(value: str) -> tuple[int, int]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", value or "")
    if not m:
        raise ValueError(f"could not parse VI/25 time={value!r}")
    hh, mm = map(int, m.groups())
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"invalid VI/25 hh:mm={value!r}")
    return hh, mm


def vi25_start_utc(record: VI25Record, band: str) -> datetime:
    initial = _parse_initial_date(record.obs)
    final = _parse_final_date(initial, record.fobs)
    raw = record.obse if band == "E" else record.obso
    hh, mm = _parse_hhmm(raw)
    # POSS observations are nighttime. Clock times after noon belong to the
    # initial observing date; post-midnight morning times belong to final date.
    local_date = initial if hh >= 12 else final
    local = datetime(local_date.year, local_date.month, local_date.day, hh, mm, tzinfo=PST)
    return local.astimezone(timezone.utc)


def vi25_duration_min(record: VI25Record, band: str) -> float:
    value = record.eexp_min if band == "E" else record.oexp_min
    if value is None:
        raise ValueError(f"VI/25 missing exposure duration for recno={record.recno} band={band}")
    return float(value)


def legacy_decimal_clock_seconds(clock: str) -> float:
    """Parse DSS Plate Finder's legacy HH:hundredths[:00] display.

    Values such as 06:75 mean 6.75 decimal hours, i.e. 06:45, not an
    impossible sexagesimal minute value.
    """
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", clock)
    if not m:
        raise ValueError(f"could not parse DSS legacy epoch clock {clock!r}")
    hh = int(m.group(1))
    hundredths = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= hundredths <= 99):
        raise ValueError(f"invalid DSS legacy epoch clock {clock!r}")
    return (hh + hundredths / 100.0) * 3600.0


def _clean_html(fragment: str) -> str:
    fragment = re.sub(r"(?i)<br\s*/?>", " | ", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def parse_platefinder_candidates(raw: bytes) -> list[FinderCandidate]:
    text = raw.decode("ISO-8859-1", errors="replace")
    out: list[FinderCandidate] = []
    for m in re.finditer(r"(?is)<tr\b[^>]*>(.*?)</tr>", text):
        row_html = m.group(1)
        pid = re.search(
            r'''(?ix)name\s*=\s*["']plate_id["'][^>]*?value\s*=\s*["']([^"']+)["']''',
            row_html,
        )
        if not pid:
            continue
        row = _clean_html(row_html)
        band_m = re.search(r"\(POSS-I\s+([EO])\)\s+([0-9.]+)\s+(X[EO][A-Za-z0-9]+)\s+\|\s+\(([^)]+)\)\s+(\d{4}-\d{2}-\d{2})\s+([0-9]{2}:[0-9]{2}(?::[0-9]{2})?)\s+([0-9.]+)", row, flags=re.I)
        if not band_m:
            continue
        band, exp, region, row_pid, epoch_date, epoch_clock, scale = band_m.groups()
        if row_pid != pid.group(1):
            raise ValueError(f"plate_id mismatch inside finder row: {pid.group(1)} vs {row_pid}")
        survey = "POSS-I E" if band.upper() == "E" else "POSS-I O"
        out.append(FinderCandidate(
            plate_id=pid.group(1),
            survey=survey,
            row_text=row,
            exposure_min=float(exp),
            region=region.upper(),
            epoch_date=epoch_date,
            epoch_clock_raw=epoch_clock,
            plate_scale_arcsec_px=float(scale) if scale else None,
        ))
    return out


def select_candidate(
    candidates: Iterable[FinderCandidate],
    *,
    record: VI25Record,
    band: str,
    expected_start_utc: datetime,
    duration_min: float,
    clock_tolerance_s: float = 90.0,
) -> tuple[FinderCandidate | None, list[dict[str, Any]]]:
    expected_date = _parse_initial_date(record.obs).isoformat()
    expected_clock = (
        expected_start_utc.hour * 3600
        + expected_start_utc.minute * 60
        + expected_start_utc.second
        + expected_start_utc.microsecond / 1e6
    )
    diagnostics: list[dict[str, Any]] = []
    matches: list[FinderCandidate] = []
    for c in candidates:
        c_band = "E" if c.survey.endswith(" E") else "O"
        clock = legacy_decimal_clock_seconds(c.epoch_clock_raw)
        delta = abs(clock - expected_clock)
        delta = min(delta, 86400.0 - delta)
        rec = {
            "plate_id": c.plate_id,
            "region": c.region,
            "band": c_band,
            "exposure_min": c.exposure_min,
            "epoch_date": c.epoch_date,
            "epoch_clock_raw": c.epoch_clock_raw,
            "clock_delta_s": delta,
            "band_match": c_band == band,
            "duration_match": abs(c.exposure_min - duration_min) < 1e-6,
            "observing_night_date_match": c.epoch_date == expected_date,
            "clock_match": delta <= clock_tolerance_s,
        }
        rec["identity_match"] = all(
            rec[k]
            for k in ("band_match", "duration_match", "observing_night_date_match", "clock_match")
        )
        diagnostics.append(rec)
        if rec["identity_match"]:
            matches.append(c)
    if len(matches) == 1:
        return matches[0], diagnostics
    return None, diagnostics


def _validate_html_response(r):
    if len(r.content) < 500:
        raise InvalidRemotePayload("Plate Finder response suspiciously small")
    text = r.content.decode("ISO-8859-1", errors="replace").lower()
    markers = ["survey name", "emulsion", "region", "epoch", "plate scale"]
    if sum(x in text for x in markers) < 3:
        raise InvalidRemotePayload("response does not look like a Plate Finder results page")


def _validate_fits_response(r):
    if len(r.content) < 2880 or not r.content.startswith(b"SIMPLE"):
        raise InvalidRemotePayload("forced plate response is not FITS")


def queue_poss_jobs(queue_path: str | Path, cohort: str = "prospective_production"):
    with Path(queue_path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    seen: set[str] = set()
    for row in rows:
        if cohort and (row.get("publication_cohort") or "") != cohort:
            continue
        exposure = None
        side = None
        for label in ("a", "b"):
            value = row.get(f"exposure_{label}") or ""
            if value.startswith("POSS-I:"):
                exposure = value
                side = label
                break
        if not exposure or exposure in seen:
            continue
        seen.add(exposure)
        poss, band, recno = parse_exposure_key(exposure)
        yield exposure, {
            "exposure_id": exposure,
            "poss": poss,
            "band": band,
            "recno": recno,
            "ra_deg": float(row[f"ra_{side}_deg"]),
            "dec_deg": float(row[f"dec_{side}_deg"]),
            "queue_start_utc": row[f"start_{side}_utc"],
            "queue_end_utc": row[f"end_{side}_utc"],
            "queue_duration_s": float(row[f"duration_{side}_s"]),
            "queue_canonical_order_first_seen": int(row["canonical_order"]),
            "publication_cohort": row.get("publication_cohort") or "",
        }


def poss1_identity_worker(
    *,
    vi25_records: dict[int, VI25Record],
    evidence: EvidenceStore | None,
    cache_dir: str | Path,
    stage: str,
    cutout_arcmin: float = 15.0,
):
    cache_dir = Path(cache_dir)
    session = ValidatedSession(
        RetryPolicy(attempts=1, base_delay_s=0.0, max_delay_s=0.0, timeout_s=20.0),
        user_agent="historical-transient-pipeline/0.2.6 publication-poss1-primary-stsci-v026",
    )

    def worker(job: Job):
        p = job.payload
        band = str(p["band"]).upper()
        recno = int(p["recno"])
        record = vi25_records.get(recno)
        if record is None:
            return {"identity_status": "vi25_record_missing", "eligible_for_science": False}
        if str(record.poss) != str(p["poss"]):
            return {
                "identity_status": "vi25_poss_mismatch",
                "eligible_for_science": False,
                "vi25_poss": record.poss,
            }
        expected_start = vi25_start_utc(record, band)
        expected_duration_min = vi25_duration_min(record, band)
        queue_start = datetime.fromisoformat(str(p["queue_start_utc"]).replace("Z", "+00:00"))
        queue_start_delta_s = abs((expected_start - queue_start).total_seconds())
        duration_delta_s = abs(expected_duration_min * 60.0 - float(p["queue_duration_s"]))
        if queue_start_delta_s > 61.0 or duration_delta_s > 1.0:
            return {
                "identity_status": "queue_vi25_time_mismatch",
                "eligible_for_science": False,
                "vi25_normalized_start_utc": expected_start.isoformat(),
                "queue_start_delta_s": queue_start_delta_s,
                "duration_delta_s": duration_delta_s,
            }

        finder_payload = {
            "resolved_target": "",
            "resolver_used": "",
            "target": "",
            "resolver": "SIMBAD",
            "ra": f"{float(p['ra_deg']):.10f}",
            "dec": f"{float(p['dec_deg']):.10f}",
            "equinox": "J2000",
            "height": f"{cutout_arcmin:.1f}",
            "width": f"{cutout_arcmin:.1f}",
            "format": "FITS",
            "save": "Display",
            "action": "Find plates",
        }
        try:
            r = session.request("POST", PLATE_FINDER, data=finder_payload, validator=_validate_html_response)
        except RetryableRemoteError as exc:
            return skyview_fallback_identity(
                record=record,
                band=band,
                stage=stage,
                job_key=job.job_key,
                attempt=job.attempts,
                cache_dir=cache_dir,
                evidence=evidence,
                expected_start_utc=expected_start,
                primary_failure=f"stsci_platefinder_retryable: {exc}",
            )
        finder_exchange = {}
        ctx = ExchangeContext(stage=stage, job_key=job.job_key, attempt=job.attempts)
        if evidence:
            finder_exchange = evidence.record_exchange(
                service="stsci_dss_platefinder",
                context=ctx,
                method="POST",
                url=PLATE_FINDER,
                request_payload=finder_payload,
                query_text=None,
                response_bytes=r.content,
                response_content_type=r.headers.get("Content-Type"),
                response_headers=dict(r.headers),
                extension="html",
            )

        candidates = parse_platefinder_candidates(r.content)
        selected, diagnostics = select_candidate(
            candidates,
            record=record,
            band=band,
            expected_start_utc=expected_start,
            duration_min=expected_duration_min,
        )
        if selected is None:
            # A syntactically valid Plate Finder response can still fail to resolve
            # one unique physical plate (zero or ambiguous matching candidates).
            # That is primary-source non-resolution, not an identity contradiction.
            # Route it through the already validated SkyView raw-DSS identity path
            # rather than completing the job as an unvalidated success.
            finder_sha256 = ((finder_exchange.get("response") or {}).get("sha256") or sha256_bytes(r.content))
            result = skyview_fallback_identity(
                record=record,
                band=band,
                stage=stage,
                job_key=job.job_key,
                attempt=job.attempts,
                cache_dir=cache_dir,
                evidence=evidence,
                expected_start_utc=expected_start,
                primary_failure=(
                    "stsci_platefinder_no_unique_match: "
                    f"candidate_count={len(candidates)}; finder_response_sha256={finder_sha256}"
                ),
            )
            result.update({
                "stsci_platefinder_resolution_status": "no_unique_platefinder_match",
                "vi25_normalized_start_utc": expected_start.isoformat(),
                "finder_candidate_count": len(candidates),
                "finder_diagnostics_json": json.dumps(diagnostics, sort_keys=True),
                "finder_response_sha256": finder_sha256,
            })
            return result

        params = {
            "ra": f"{float(p['ra_deg']):.10f}",
            "dec": f"{float(p['dec_deg']):.10f}",
            "height": f"{cutout_arcmin:.1f}",
            "width": f"{cutout_arcmin:.1f}",
            "format": "FITS",
            "plate_id": selected.plate_id,
            "action": "Extract",
        }
        try:
            rf = session.request("GET", PLATE_FINDER, params=params, validator=_validate_fits_response)
        except RetryableRemoteError as exc:
            return skyview_fallback_identity(
                record=record,
                band=band,
                stage=stage,
                job_key=job.job_key,
                attempt=job.attempts,
                cache_dir=cache_dir,
                evidence=evidence,
                expected_start_utc=expected_start,
                primary_failure=f"stsci_forced_extract_retryable: {exc}",
                expected_plate_id=selected.plate_id,
                expected_region=selected.region,
            )
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", job.job_key)
        fits_path = cache_dir / safe / f"{selected.plate_id}_identity.fits"
        atomic_write_bytes(fits_path, rf.content)
        fits_hash = hashlib.sha256(rf.content).hexdigest()

        forced_exchange = {}
        if evidence:
            forced_exchange = evidence.record_exchange(
                service="stsci_dss_forced_plate",
                context=ctx,
                method="GET",
                url=PLATE_FINDER,
                request_payload=params,
                query_text=None,
                response_bytes=rf.content,
                response_content_type=rf.headers.get("Content-Type"),
                response_headers=dict(rf.headers),
                extension="fits",
            )

        from astropy.io import fits
        with fits.open(BytesIO(rf.content), memmap=False, checksum=False) as hdul:
            if not hdul or hdul[0].data is None:
                raise InvalidRemotePayload("forced FITS has no primary image data")
            header = hdul[0].header
            shape = [int(x) for x in hdul[0].data.shape]
            header_region = str(header.get("REGION", "")).strip().upper()
            selected_header = {
                key: header[key]
                for key in (
                    "REGION", "DATE-OBS", "DATE", "EPOCH", "EQUINOX", "PLTRAH", "PLTRAM", "PLTRAS",
                    "PLTDECSN", "PLTDECD", "PLTDECM", "PLTDECS", "CNPIX1", "CNPIX2", "XPIXELSZ", "YPIXELSZ",
                    "PPO3", "PPO6",
                )
                if key in header
            }

        header_region_match = (not header_region) or (header_region == selected.region)
        sidecar = fits_path.with_suffix(".fits.provenance.json")
        sidecar_rec = {
            "artifact_type": "poss1_forced_identity_cutout_fits",
            "recorded_at_utc": utcnow(),
            "exposure_id": job.job_key,
            "vi25": {
                "recno": record.recno,
                "poss": record.poss,
                "mlp": record.mlp,
                "obs": record.obs,
                "fObs": record.fobs,
                "band": band,
                "raw_start": record.obse if band == "E" else record.obso,
                "normalized_start_utc": expected_start.isoformat(),
                "duration_min": expected_duration_min,
            },
            "platefinder": {
                "plate_id": selected.plate_id,
                "region": selected.region,
                "epoch_date": selected.epoch_date,
                "epoch_clock_raw": selected.epoch_clock_raw,
                "row_text": selected.row_text,
            },
            "fits": {
                "path": str(fits_path),
                "sha256": fits_hash,
                "bytes": len(rf.content),
                "shape": shape,
                "header_region": header_region,
                "header_region_match": header_region_match,
                "selected_header": selected_header,
            },
            "finder_exchange": finder_exchange,
            "forced_exchange": forced_exchange,
        }
        atomic_write_text(sidecar, json.dumps(sidecar_rec, indent=2, sort_keys=True, default=str) + "\n")
        if evidence:
            evidence.record_artifact(
                path=fits_path,
                kind="poss1_forced_identity_cutout_fits",
                stage=stage,
                job_key=job.job_key,
                source_url=rf.url,
                metadata={
                    "plate_id": selected.plate_id,
                    "region": selected.region,
                    "band": band,
                    "vi25_recno": recno,
                    "provenance_sidecar": str(sidecar),
                },
            )

        return {
            "identity_status": "validated" if header_region_match else "fits_region_mismatch",
            "eligible_for_science": bool(header_region_match),
            "vi25_poss": record.poss,
            "vi25_mlp": record.mlp,
            "vi25_observing_night_initial": record.obs,
            "vi25_observing_night_final": record.fobs,
            "vi25_raw_start_pst": record.obse if band == "E" else record.obso,
            "vi25_normalized_start_utc": expected_start.isoformat(),
            "queue_start_delta_s": queue_start_delta_s,
            "finder_plate_id": selected.plate_id,
            "finder_region": selected.region,
            "finder_epoch_date": selected.epoch_date,
            "finder_epoch_clock_raw": selected.epoch_clock_raw,
            "finder_exposure_min": selected.exposure_min,
            "finder_response_sha256": ((finder_exchange.get("response") or {}).get("sha256") or sha256_bytes(r.content)),
            "fits_sha256": fits_hash,
            "fits_path": str(fits_path),
            "fits_bytes": len(rf.content),
            "fits_shape_json": json.dumps(shape),
            "fits_header_region": header_region,
            "fits_header_region_match": header_region_match,
            "provenance_sidecar": str(sidecar),
        }

    return worker
