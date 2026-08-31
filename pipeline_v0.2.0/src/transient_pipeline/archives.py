from __future__ import annotations

import base64
import gzip
from typing import Any

from .http import InvalidRemotePayload, ValidatedSession
from .provenance import EvidenceStore, ExchangeContext

APPLAUSE_TAP = "http://www.plate-archive.org/tap/sync"
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
STARGLASS_CUTOUT = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/cutout"


def _validate_tap_votable(r):
    text = r.text
    if "<VOTABLE" not in text:
        raise InvalidRemotePayload("TAP response is not VOTable")
    if "QUERY_STATUS" in text and "ERROR" in text:
        raise InvalidRemotePayload("TAP QUERY_STATUS=ERROR")


def _headers_for_record(r) -> dict[str, Any]:
    keep = {"content-type", "content-length", "etag", "last-modified", "date"}
    return {k: v for k, v in r.headers.items() if k.lower() in keep}


def applause_adql(
    session: ValidatedSession,
    query: str,
    *,
    evidence: EvidenceStore | None = None,
    context: ExchangeContext | None = None,
) -> str:
    payload = {"REQUEST": "doQuery", "LANG": "ADQL", "QUERY": query}
    r = session.request("POST", APPLAUSE_TAP, data=payload, validator=_validate_tap_votable)
    if evidence and context:
        evidence.record_exchange(
            service="applause_tap",
            context=context,
            method="POST",
            url=APPLAUSE_TAP,
            request_payload={"REQUEST": "doQuery", "LANG": "ADQL"},
            query_text=query,
            response_bytes=r.content,
            response_content_type=r.headers.get("Content-Type"),
            extension="votable.xml",
            response_headers=_headers_for_record(r),
        )
    return r.text


def vizier_adql_csv(
    session: ValidatedSession,
    query: str,
    *,
    evidence: EvidenceStore | None = None,
    context: ExchangeContext | None = None,
) -> str:
    def validate(r):
        text = r.text.lstrip()
        if text.startswith("<") or "QUERY_STATUS" in text[:1000]:
            raise InvalidRemotePayload("VizieR returned XML/error instead of CSV")
        if "RAICRS" not in text.splitlines()[0]:
            raise InvalidRemotePayload("VizieR CSV missing expected RAICRS header")

    payload = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    r = session.request("POST", VIZIER_TAP, data=payload, validator=validate)
    if evidence and context:
        evidence.record_exchange(
            service="vizier_tap_gps1",
            context=context,
            method="POST",
            url=VIZIER_TAP,
            request_payload={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv"},
            query_text=query,
            response_bytes=r.content,
            response_content_type=r.headers.get("Content-Type"),
            extension="csv",
            response_headers=_headers_for_record(r),
        )
    return r.text


def starglass_cutout_fits_bytes(
    session: ValidatedSession,
    plate_id: str,
    ra_deg: float,
    dec_deg: float,
    solution_number: int = 0,
) -> bytes:
    payload = {
        "plate_id": plate_id,
        "solution_number": solution_number,
        "center_ra_deg": ra_deg,
        "center_dec_deg": dec_deg,
    }

    def validate(r):
        try:
            encoded = r.json()
        except Exception as exc:
            raise InvalidRemotePayload(f"StarGlass body is not JSON: {exc}")
        if not isinstance(encoded, str) or len(encoded) < 100:
            raise InvalidRemotePayload("StarGlass JSON is not a base64 string")
        try:
            raw = gzip.decompress(base64.b64decode(encoded, validate=True))
        except Exception as exc:
            raise InvalidRemotePayload(f"StarGlass base64/gzip invalid: {exc}")
        if not raw.startswith(b"SIMPLE"):
            raise InvalidRemotePayload("StarGlass payload does not begin with FITS SIMPLE card")

    r = session.request("POST", STARGLASS_CUTOUT, json=payload, validator=validate)
    return gzip.decompress(base64.b64decode(r.json(), validate=True))
