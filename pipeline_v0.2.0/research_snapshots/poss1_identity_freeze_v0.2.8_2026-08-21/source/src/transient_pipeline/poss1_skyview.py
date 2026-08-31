from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import json
import math
import re
from pathlib import Path
from typing import Any

from .http import InvalidRemotePayload, RetryPolicy, ValidatedSession
from .provenance import EvidenceStore, ExchangeContext, atomic_write_text, sha256_bytes, utcnow

SKYVIEW_XML_ROOT = "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml"
SKYVIEW_DSS1R_DESCRIPTOR = f"{SKYVIEW_XML_ROOT}/dss1r.xml.gz"
SKYVIEW_DSS1B_DESCRIPTOR = f"{SKYVIEW_XML_ROOT}/dss1b.xml.gz"
SKYVIEW_E_RAW_ROOT = "https://skyview.gsfc.nasa.gov/surveys/dss"
SKYVIEW_O_RAW_ROOT = "https://skyview.gsfc.nasa.gov/surveys/dss2/xo"

# Publication control result: the exact current SkyView JAR used to decode all five
# STScI controls byte-for-value. The identity fallback below does not require Java,
# but the hash is retained here as a provenance anchor for the control evidence.
SKYVIEW_CONTROL_JAR_SHA256 = "2b949f68d73899cd63b2f600f60f6c5dfd1795532ed29b6ea986f71f83d36afe"


@dataclass(frozen=True)
class SkyViewImageEntry:
    path: str
    ra_deg: float
    dec_deg: float
    epoch: float | None


@dataclass(frozen=True)
class SkyViewDescriptor:
    short_name: str
    file_prefix: str | None
    image_factory: str | None
    images: tuple[SkyViewImageEntry, ...]


def _maybe_decompress(raw: bytes) -> bytes:
    if raw.startswith(b"\x1f\x8b"):
        return gzip.decompress(raw)
    return raw


def _xml_text(raw: bytes) -> str:
    return _maybe_decompress(raw).decode("ISO-8859-1", errors="replace")


def _tag_text(text: str, tag: str) -> str | None:
    m = re.search(rf"(?is)<{re.escape(tag)}\b[^>]*>(.*?)</{re.escape(tag)}>", text)
    if not m:
        return None
    value = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", value).strip()


def parse_skyview_descriptor(raw: bytes) -> SkyViewDescriptor:
    text = _xml_text(raw)
    short_name = _tag_text(text, "ShortName") or ""
    file_prefix = _tag_text(text, "FilePrefix")
    image_factory = _tag_text(text, "ImageFactory")
    images: list[SkyViewImageEntry] = []
    for m in re.finditer(r"(?is)<Image\b[^>]*>(.*?)</Image>", text):
        body = re.sub(r"<[^>]+>", " ", m.group(1))
        parts = re.sub(r"\s+", " ", body).strip().split(" ")
        if len(parts) < 3:
            continue
        try:
            ra = float(parts[1])
            dec = float(parts[2])
            epoch = float(parts[3]) if len(parts) >= 4 else None
        except ValueError:
            continue
        images.append(SkyViewImageEntry(path=parts[0].strip(), ra_deg=ra, dec_deg=dec, epoch=epoch))
    return SkyViewDescriptor(
        short_name=short_name,
        file_prefix=file_prefix.strip() if file_prefix else None,
        image_factory=image_factory.strip() if image_factory else None,
        images=tuple(images),
    )


def _validate_descriptor_response(r):
    if len(r.content) < 1000:
        raise InvalidRemotePayload("SkyView survey descriptor suspiciously small")
    text = _xml_text(r.content).lower()
    if "<shortname>" not in text or "<image" not in text or "dssimagefactory" not in text:
        raise InvalidRemotePayload("SkyView response does not look like a DSS1 survey descriptor")


def _validate_hhh_response(r):
    if len(r.content) < 2880 or not r.content.startswith(b"SIMPLE"):
        raise InvalidRemotePayload("SkyView DSS .hhh response is not a FITS-style plate header")
    text = r.content.decode("ISO-8859-1", errors="replace")
    if "REGION" not in text[:20000] or "PLATEID" not in text[:20000]:
        raise InvalidRemotePayload("SkyView DSS .hhh lacks REGION/PLATEID")


def _validate_hcompress_tile(r):
    if len(r.content) < 32 or not r.content.startswith(b"\xDD\x99"):
        raise InvalidRemotePayload("SkyView DSS tile lacks H-compress DD99 magic")


def _fits_card_value(raw: bytes, key: str) -> str | None:
    text = raw.decode("ISO-8859-1", errors="replace")
    key = key.upper()
    for pos in range(0, len(text), 80):
        card = text[pos : pos + 80]
        if card[:8].strip().upper() != key:
            continue
        if len(card) < 10 or card[8] != "=":
            return card[8:].strip() or None
        rhs = card[10:].split("/", 1)[0].strip()
        if len(rhs) >= 2 and rhs.startswith("'") and "'" in rhs[1:]:
            return rhs.strip().strip("'").strip()
        return rhs or None
    return None


def hhh_identity(raw: bytes) -> dict[str, Any]:
    def fnum(key: str) -> float | None:
        v = _fits_card_value(raw, key)
        if v is None:
            return None
        try:
            return float(v.replace("D", "E"))
        except ValueError:
            return None

    return {
        "region": (_fits_card_value(raw, "REGION") or "").strip().upper(),
        "plate_id": (_fits_card_value(raw, "PLATEID") or "").strip(),
        "date_obs": (_fits_card_value(raw, "DATE-OBS") or "").strip(),
        "plate_ra_deg": fnum("PLATERA"),
        "plate_dec_deg": fnum("PLATEDEC"),
        "xpixels": fnum("XPIXELS"),
        "ypixels": fnum("YPIXELS"),
    }


def sexagesimal_ra_deg(value: str) -> float:
    parts = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", value or "")]
    if len(parts) < 3:
        raise ValueError(f"could not parse VI/25 ICRS RA {value!r}")
    h, m, s = parts[:3]
    return (h + m / 60.0 + s / 3600.0) * 15.0


def sexagesimal_dec_deg(value: str) -> float:
    m = re.match(r"\s*([+-]?)\s*(\d+)\s+(\d+)\s+([0-9.]+)", value or "")
    if not m:
        raise ValueError(f"could not parse VI/25 ICRS Dec {value!r}")
    sign_s, d, mm, ss = m.groups()
    sign = -1.0 if sign_s == "-" else 1.0
    return sign * (float(d) + float(mm) / 60.0 + float(ss) / 3600.0)


def angular_sep_arcsec(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    dot = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot)))) * 3600.0


def expected_region_for_vi25(record, band: str) -> str:
    """Map the VI/25 Master List Plate number to the DSS region.

    ``recno`` is the VizieR table-row identifier and is not the physical DSS
    plate/region identifier.  In VI/25 the DSS region sequence is keyed by MLP:
    MLP 523 -> X?522, MLP 297 -> X?296, etc.  A handful of legitimate rows have
    MLP != recno, so equality between those fields must never be an identity gate.
    """
    band = str(band).upper()
    if band not in {"E", "O"}:
        raise ValueError(f"unsupported POSS-I band {band!r}")
    mlp = str(record.mlp).strip()
    if not mlp.isdigit():
        raise ValueError(f"VI/25 MLP is not numeric for recno={record.recno}: {record.mlp!r}")
    mlp_n = int(mlp)
    if mlp_n <= 0:
        raise ValueError(f"invalid VI/25 MLP {mlp_n}")
    return f"X{band}{mlp_n - 1:03d}"


def decimal_year_for_date(value: str) -> float:
    d = datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = datetime(d.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(d.year + 1, 1, 1, tzinfo=timezone.utc)
    return d.year + (d - start).total_seconds() / (end - start).total_seconds()


def hhh_observing_date(raw_date_obs: str) -> str | None:
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", raw_date_obs or "")
    return m.group(1) if m else None


def raw_plate_directory(*, band: str, region: str, descriptor_entry: SkyViewImageEntry) -> str:
    band = str(band).upper()
    r = region.lower()
    if band == "E":
        # Exact path validated against three independent STScI POSS-I E controls.
        return f"{SKYVIEW_E_RAW_ROOT}/{r}"
    if band == "O":
        # Exact DSS1B raw path validated against two independent STScI POSS-I O controls.
        # Descriptor entries use xo/xo### and current FilePrefix is /surveys/dss2/.
        expected_tail = f"xo/{r}"
        if descriptor_entry.path.lower().rstrip("/") != expected_tail:
            raise ValueError(
                f"unexpected DSS1B descriptor path for {region}: {descriptor_entry.path!r}"
            )
        return f"{SKYVIEW_O_RAW_ROOT}/{r}"
    raise ValueError(f"unsupported POSS-I band {band!r}")


def fallback_identity(
    *,
    record,
    band: str,
    stage: str,
    job_key: str,
    attempt: int,
    cache_dir: str | Path,
    evidence: EvidenceStore | None,
    primary_failure: str,
    expected_start_utc: Any | None = None,
    expected_plate_id: str | None = None,
    expected_region: str | None = None,
    nominal_center_sanity_deg: float = 1.0,
    descriptor_epoch_tolerance_days: float = 14.0,
    descriptor_hhh_center_tolerance_arcsec: float = 5.0,
) -> dict[str, Any]:
    band = str(band).upper()

    # Production callers pass the already-normalized VI/25 UTC start.
    # Direct/test callers may omit it; derive it from the same authoritative
    # VI/25 helper rather than duplicating observing-night/PST logic here.
    if expected_start_utc is None:
        from .poss1 import vi25_start_utc
        expected_start_utc = vi25_start_utc(record, band)

    try:
        utc_offset = expected_start_utc.utcoffset()
    except Exception as exc:
        raise ValueError(
            "SkyView fallback received invalid normalized VI/25 UTC start"
        ) from exc
    if utc_offset is None or utc_offset.total_seconds() != 0:
        raise ValueError(
            "SkyView fallback expected_start_utc must be timezone-aware UTC"
        )

    expected_region_from_vi25 = expected_region_for_vi25(record, band)
    if expected_region and expected_region.upper() != expected_region_from_vi25:
        raise ValueError(
            f"STScI/SkyView region disagreement: {expected_region!r} vs {expected_region_from_vi25!r}"
        )

    ra_icrs = sexagesimal_ra_deg(record.ra_icrs)
    dec_icrs = sexagesimal_dec_deg(record.dec_icrs)
    descriptor_url = SKYVIEW_DSS1R_DESCRIPTOR if band == "E" else SKYVIEW_DSS1B_DESCRIPTOR

    session = ValidatedSession(
        RetryPolicy(attempts=4, base_delay_s=2.0, max_delay_s=20.0, timeout_s=90.0),
        user_agent="historical-transient-pipeline/0.2.7 publication-poss1-skyview-fallback",
    )
    ctx = ExchangeContext(stage=stage, job_key=job_key, attempt=attempt)

    rd = session.request("GET", descriptor_url, validator=_validate_descriptor_response)
    descriptor_exchange: dict[str, Any] = {}
    if evidence:
        descriptor_exchange = evidence.record_exchange(
            service="skyview_dss1_descriptor",
            context=ctx,
            method="GET",
            url=descriptor_url,
            request_payload=None,
            query_text=None,
            response_bytes=rd.content,
            response_content_type=rd.headers.get("Content-Type"),
            response_headers=dict(rd.headers),
            extension="xml",
        )
    desc = parse_skyview_descriptor(rd.content)
    if (desc.image_factory or "").strip() != "skyview.survey.DSSImageFactory":
        raise ValueError(f"unexpected SkyView image factory: {desc.image_factory!r}")

    wanted = expected_region_from_vi25.lower()
    matches = [x for x in desc.images if Path(x.path).name.lower() == wanted]
    if len(matches) == 0:
        # A valid VI/25 exposure can exist even when no digital DSS1 product is
        # exposed by the current SkyView mirror.  This is an archive-availability
        # state, not a plate-identity contradiction and never a scientific zero.
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_key)
        sidecar = Path(cache_dir) / safe / f"{expected_region_from_vi25}_archive_unavailable.provenance.json"
        sidecar_record = {
            "artifact_type": "poss1_archive_pixels_unavailable",
            "recorded_at_utc": utcnow(),
            "science_analysis_performed": False,
            "exposure_id": job_key,
            "identity_status": "catalogue_identified_pixels_unavailable",
            "eligible_for_science": False,
            "primary_archive_failure": primary_failure,
            "vi25": {
                "recno": record.recno,
                "poss": record.poss,
                "mlp": record.mlp,
                "band": band,
                "obs": record.obs,
                "fObs": record.fobs,
                "ra_icrs_raw": record.ra_icrs,
                "dec_icrs_raw": record.dec_icrs,
                "expected_region": expected_region_from_vi25,
            },
            "skyview": {
                "descriptor_url": descriptor_url,
                "descriptor_sha256": sha256_bytes(rd.content),
                "descriptor_exact_region_matches": 0,
                "descriptor_exchange": descriptor_exchange,
            },
            "interpretation": (
                "Physical exposure remains identified by VI/25 metadata, but no current SkyView DSS1 "
                "image entry exists for the deterministically expected region. Digital pixels are unavailable; "
                "the exposure remains in the prospective denominator and is ineligible for detector execution."
            ),
        }
        atomic_write_text(sidecar, json.dumps(sidecar_record, indent=2, sort_keys=True, default=str) + "\n")
        if evidence:
            evidence.record_artifact(
                path=sidecar,
                kind="poss1_archive_pixels_unavailable",
                stage=stage,
                job_key=job_key,
                source_url=descriptor_url,
                metadata={
                    "region": expected_region_from_vi25,
                    "band": band,
                    "vi25_recno": record.recno,
                    "eligible_for_science": False,
                },
                snapshot=True,
            )
        return {
            "identity_status": "catalogue_identified_pixels_unavailable",
            "identity_source": "vi25_plus_primary_stsci_failure_and_skyview_gap",
            "archive_availability_status": "digital_pixels_unavailable",
            "eligible_for_science": False,
            "vi25_poss": record.poss,
            "vi25_mlp": record.mlp,
            "vi25_observing_night_initial": record.obs,
            "vi25_observing_night_final": record.fobs,
            "finder_plate_id": expected_plate_id or "",
            "finder_region": expected_region_from_vi25,
            "skyview_descriptor_image_count": 0,
            "skyview_descriptor_sha256": ((descriptor_exchange.get("response") or {}).get("sha256") or sha256_bytes(rd.content)),
            "primary_archive_failure": primary_failure,
            "archive_unavailable_provenance_sidecar": str(sidecar),
        }
    if len(matches) != 1:
        raise ValueError(
            f"SkyView descriptor expected exactly one image for {expected_region_from_vi25}, got {len(matches)}"
        )
    entry = matches[0]
    # VI/25 carries a nominal field pointing while GSSS PLATERA/PLATEDEC are the
    # astrometric plate-solution centre.  They can differ by arcminutes (the known
    # XE296/06S2 control differs by ~182.5 arcsec), so this is only a broad sanity
    #/coverage guard, never an equality test.
    descriptor_center_sep = angular_sep_arcsec(ra_icrs, dec_icrs, entry.ra_deg, entry.dec_deg)
    if descriptor_center_sep > nominal_center_sanity_deg * 3600.0:
        raise ValueError(
            f"SkyView descriptor nominal-pointing sanity mismatch for {expected_region_from_vi25}: "
            f"{descriptor_center_sep:.3f} arcsec > {nominal_center_sanity_deg:.3f} deg"
        )

    # The descriptor epoch is rounded, so compare only at a coarse date scale.
    vi25_decimal_year = decimal_year_for_date(record.obs)
    descriptor_epoch_delta_days = None
    if entry.epoch is not None:
        descriptor_epoch_delta_days = abs(entry.epoch - vi25_decimal_year) * 365.25
        if descriptor_epoch_delta_days > descriptor_epoch_tolerance_days:
            raise ValueError(
                f"SkyView descriptor epoch mismatch for {expected_region_from_vi25}: "
                f"{descriptor_epoch_delta_days:.3f} days"
            )

    raw_dir = raw_plate_directory(band=band, region=expected_region_from_vi25, descriptor_entry=entry)
    hhh_url = f"{raw_dir}/{wanted}.hhh"
    try:
        rh = session.request("GET", hhh_url, validator=_validate_hhh_response)
    except Exception as exc:
        # A deterministic raw-HHH 404 means the exact descriptor region exists
        # but its current SkyView raw digital product is unavailable.  Do not
        # substitute a neighbouring region and do not convert this exposure
        # into a scientific zero.  Non-404 failures retain their original
        # exception/retry behaviour.
        msg = str(exc)
        if "HTTP 404" not in msg.upper():
            raise

        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_key)
        sidecar = (
            Path(cache_dir)
            / safe
            / f"{expected_region_from_vi25}_raw_hhh_unavailable.provenance.json"
        )
        sidecar_record = {
            "artifact_type": "poss1_archive_pixels_unavailable",
            "recorded_at_utc": utcnow(),
            "science_analysis_performed": False,
            "exposure_id": job_key,
            "identity_status": "catalogue_identified_pixels_unavailable",
            "eligible_for_science": False,
            "archive_failure_kind": "skyview_raw_hhh_http_404",
            "primary_archive_failure": primary_failure,
            "vi25": {
                "recno": record.recno,
                "poss": record.poss,
                "mlp": record.mlp,
                "band": band,
                "obs": record.obs,
                "fObs": record.fobs,
                "ra_icrs_raw": record.ra_icrs,
                "dec_icrs_raw": record.dec_icrs,
                "expected_region": expected_region_from_vi25,
            },
            "skyview": {
                "descriptor_url": descriptor_url,
                "descriptor_sha256": sha256_bytes(rd.content),
                "descriptor_exact_region_matches": 1,
                "descriptor_image_path": entry.path,
                "raw_plate_directory": raw_dir,
                "hhh_url": hhh_url,
                "hhh_failure": f"{type(exc).__name__}: {exc}",
                "descriptor_exchange": descriptor_exchange,
            },
            "interpretation": (
                "The deterministically expected POSS-I region is present in the "
                "current SkyView DSS1 descriptor, but its exact raw HHH product "
                "returns HTTP 404. The physical exposure remains catalogue-identified; "
                "digital pixels are currently unavailable. The exposure remains in "
                "the prospective denominator, is ineligible for detector execution, "
                "and is not a scientific zero. No neighbouring DSS region is substituted."
            ),
        }
        atomic_write_text(
            sidecar,
            json.dumps(sidecar_record, indent=2, sort_keys=True, default=str) + "\n",
        )

        if evidence:
            evidence.record_artifact(
                path=sidecar,
                kind="poss1_archive_pixels_unavailable",
                stage=stage,
                job_key=job_key,
                source_url=hhh_url,
                metadata={
                    "region": expected_region_from_vi25,
                    "band": band,
                    "vi25_recno": record.recno,
                    "eligible_for_science": False,
                    "archive_failure_kind": "skyview_raw_hhh_http_404",
                },
                snapshot=True,
            )

        return {
            "identity_status": "catalogue_identified_pixels_unavailable",
            "identity_source": (
                "vi25_plus_primary_stsci_failure_and_"
                "skyview_descriptor_raw_hhh_gap"
            ),
            "archive_availability_status": "digital_pixels_unavailable",
            "eligible_for_science": False,
            "vi25_poss": record.poss,
            "vi25_mlp": record.mlp,
            "vi25_observing_night_initial": record.obs,
            "vi25_observing_night_final": record.fobs,
            "finder_plate_id": expected_plate_id or "",
            "finder_region": expected_region_from_vi25,
            "skyview_descriptor_image_count": 1,
            "skyview_descriptor_sha256": (
                ((descriptor_exchange.get("response") or {}).get("sha256"))
                or sha256_bytes(rd.content)
            ),
            "skyview_descriptor_image_path": entry.path,
            "skyview_raw_hhh_url": hhh_url,
            "skyview_raw_hhh_failure": f"{type(exc).__name__}: {exc}",
            "archive_failure_kind": "skyview_raw_hhh_http_404",
            "primary_archive_failure": primary_failure,
            "archive_unavailable_provenance_sidecar": str(sidecar),
        }

    hhh_exchange: dict[str, Any] = {}
    if evidence:
        hhh_exchange = evidence.record_exchange(
            service="skyview_dss_raw_hhh",
            context=ctx,
            method="GET",
            url=hhh_url,
            request_payload=None,
            query_text=None,
            response_bytes=rh.content,
            response_content_type=rh.headers.get("Content-Type"),
            response_headers=dict(rh.headers),
            extension="hhh",
        )

    ident = hhh_identity(rh.content)
    if ident["region"] != expected_region_from_vi25:
        raise ValueError(
            f"SkyView HHH REGION mismatch: {ident['region']!r} != {expected_region_from_vi25!r}"
        )
    if not ident["plate_id"]:
        raise ValueError("SkyView HHH has no PLATEID")
    if expected_plate_id and ident["plate_id"] != expected_plate_id:
        raise ValueError(
            f"STScI/SkyView PLATEID disagreement: {expected_plate_id!r} vs {ident['plate_id']!r}"
        )
    if ident["plate_ra_deg"] is None or ident["plate_dec_deg"] is None:
        raise ValueError("SkyView HHH lacks PLATERA/PLATEDEC")

    # The descriptor XML centre and GSSS PLATERA/PLATEDEC are not equivalent
    # centre definitions.  v0.2.7 empirical controls established valid
    # pixel-equivalent POSS-I E/O cases with descriptor<->HHH separations up
    # to 357.680 arcsec; all four v0.2.6 rejected cases were inside that
    # verified-good range.  Preserve the separation as diagnostic provenance,
    # but never use it as a terminal plate-identity discriminator.
    descriptor_hhh_center_sep = angular_sep_arcsec(
        entry.ra_deg,
        entry.dec_deg,
        float(ident["plate_ra_deg"]),
        float(ident["plate_dec_deg"]),
    )

    # GSSS DATE-OBS calendar rollover is not uniform across the verified POSS-I
    # raw headers.  Pixel-equivalent controls retain the initial observing-night
    # calendar date even when the corresponding VI/25 PST exposure normalizes to
    # the following UTC date, while other valid raw headers use that normalized
    # UTC date.  Preserve a hard date identity check, but admit only those two
    # physically/documentarily justified encodings -- never an arbitrary +/-1 day.
    hhh_obs_date = hhh_observing_date(str(ident["date_obs"]))
    vi25_initial_night_date = str(record.obs).strip()
    vi25_normalized_utc_date = expected_start_utc.date().isoformat()
    allowed_hhh_dates = {
        vi25_initial_night_date,
        vi25_normalized_utc_date,
    }
    if hhh_obs_date not in allowed_hhh_dates:
        raise ValueError(
            f"SkyView HHH observing-date mismatch for {expected_region_from_vi25}: "
            f"{hhh_obs_date!r} not in reviewed VI/25-compatible dates "
            f"{sorted(allowed_hhh_dates)!r}"
        )

    hhh_nominal_center_sep = angular_sep_arcsec(
        ra_icrs,
        dec_icrs,
        float(ident["plate_ra_deg"]),
        float(ident["plate_dec_deg"]),
    )
    if hhh_nominal_center_sep > nominal_center_sanity_deg * 3600.0:
        raise ValueError(
            f"SkyView HHH nominal-pointing sanity mismatch for {expected_region_from_vi25}: "
            f"{hhh_nominal_center_sep:.3f} arcsec > {nominal_center_sanity_deg:.3f} deg"
        )

    probe_url = f"{raw_dir}/{wanted}.00"
    rp = session.request("GET", probe_url, validator=_validate_hcompress_tile)
    probe_exchange: dict[str, Any] = {}
    if evidence:
        probe_exchange = evidence.record_exchange(
            service="skyview_dss_raw_hcompress_probe",
            context=ctx,
            method="GET",
            url=probe_url,
            request_payload=None,
            query_text=None,
            response_bytes=rp.content,
            response_content_type=rp.headers.get("Content-Type"),
            response_headers=dict(rp.headers),
            extension="hcompress",
        )

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_key)
    sidecar = Path(cache_dir) / safe / f"{ident['plate_id']}_skyview_identity.provenance.json"
    sidecar_record = {
        "artifact_type": "poss1_skyview_raw_identity",
        "recorded_at_utc": utcnow(),
        "science_analysis_performed": False,
        "exposure_id": job_key,
        "identity_source": "skyview_raw_fallback",
        "primary_archive_failure": primary_failure,
        "vi25": {
            "recno": record.recno,
            "poss": record.poss,
            "mlp": record.mlp,
            "band": band,
            "ra_icrs_raw": record.ra_icrs,
            "dec_icrs_raw": record.dec_icrs,
            "ra_icrs_deg": ra_icrs,
            "dec_icrs_deg": dec_icrs,
            "observing_night_initial": record.obs,
            "observing_night_final": record.fobs,
            "normalized_start_utc": expected_start_utc.isoformat(),
            "normalized_start_utc_date": vi25_normalized_utc_date,
            "allowed_hhh_calendar_dates": sorted(allowed_hhh_dates),
        },
        "skyview": {
            "descriptor_url": descriptor_url,
            "descriptor_sha256": sha256_bytes(rd.content),
            "descriptor_image_path": entry.path,
            "descriptor_center_ra_deg": entry.ra_deg,
            "descriptor_center_dec_deg": entry.dec_deg,
            "descriptor_nominal_center_sep_arcsec": descriptor_center_sep,
            "descriptor_epoch_delta_days": descriptor_epoch_delta_days,
            "raw_plate_directory": raw_dir,
            "hhh_url": hhh_url,
            "hhh_sha256": sha256_bytes(rh.content),
            "region": ident["region"],
            "plate_id": ident["plate_id"],
            "date_obs": ident["date_obs"],
            "plate_ra_deg": ident["plate_ra_deg"],
            "plate_dec_deg": ident["plate_dec_deg"],
            "hhh_nominal_center_sep_arcsec": hhh_nominal_center_sep,
            "descriptor_hhh_center_sep_arcsec": descriptor_hhh_center_sep,
            "hhh_observing_date": hhh_obs_date,
            "hhh_date_identity_policy": (
                "vi25_initial_night_or_normalized_utc_date_v0.2.7"
            ),
            "probe_tile_url": probe_url,
            "probe_tile_sha256": sha256_bytes(rp.content),
            "probe_tile_bytes": len(rp.content),
            "probe_tile_magic": rp.content[:2].hex(),
        },
        "control_basis": {
            "strict_pixel_equivalence_controls": "5/5",
            "emulsions": ["POSS-I E", "POSS-I O"],
            "control_jar_sha256": SKYVIEW_CONTROL_JAR_SHA256,
            "descriptor_hhh_center_policy": "diagnostic_only_v0.2.7",
            "descriptor_hhh_verified_control_max_sep_arcsec": 357.680,
        },
        "descriptor_exchange": descriptor_exchange,
        "hhh_exchange": hhh_exchange,
        "probe_exchange": probe_exchange,
    }
    atomic_write_text(sidecar, json.dumps(sidecar_record, indent=2, sort_keys=True, default=str) + "\n")
    if evidence:
        evidence.record_artifact(
            path=sidecar,
            kind="poss1_skyview_raw_identity_sidecar",
            stage=stage,
            job_key=job_key,
            source_url=hhh_url,
            metadata={
                "region": ident["region"],
                "plate_id": ident["plate_id"],
                "band": band,
                "vi25_recno": int(record.recno),
                "identity_source": "skyview_raw_fallback",
            },
        )

    return {
        "identity_status": "validated",
        "identity_source": "skyview_raw_fallback",
        "eligible_for_science": True,
        "primary_archive_failure": primary_failure,
        "vi25_poss": record.poss,
        "vi25_mlp": record.mlp,
        "vi25_ra_icrs": record.ra_icrs,
        "vi25_dec_icrs": record.dec_icrs,
        "finder_plate_id": ident["plate_id"],
        "finder_region": ident["region"],
        "skyview_descriptor_url": descriptor_url,
        "skyview_descriptor_sha256": sha256_bytes(rd.content),
        "skyview_descriptor_image_path": entry.path,
        "skyview_descriptor_nominal_center_sep_arcsec": descriptor_center_sep,
        "skyview_descriptor_epoch_delta_days": descriptor_epoch_delta_days,
        "skyview_raw_plate_directory": raw_dir,
        "skyview_hhh_url": hhh_url,
        "skyview_hhh_sha256": sha256_bytes(rh.content),
        "skyview_hhh_date_obs": ident["date_obs"],
        "skyview_hhh_nominal_center_sep_arcsec": hhh_nominal_center_sep,
        "skyview_descriptor_hhh_center_sep_arcsec": descriptor_hhh_center_sep,
        "skyview_hhh_observing_date": hhh_obs_date,
        "skyview_probe_tile_url": probe_url,
        "skyview_probe_tile_sha256": sha256_bytes(rp.content),
        "skyview_probe_tile_bytes": len(rp.content),
        "skyview_probe_tile_magic": rp.content[:2].hex(),
        "fits_path": "",
        "fits_sha256": "",
        "provenance_sidecar": str(sidecar),
    }
