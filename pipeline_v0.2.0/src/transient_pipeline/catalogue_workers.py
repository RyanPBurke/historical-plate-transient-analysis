from __future__ import annotations

from .archives import applause_adql, vizier_adql_csv
from .astrometry import angular_sep_arcsec, propagate_gps1_to_epoch
from .checkpoint import Job
from .config import FrozenMethod
from .http import InvalidRemotePayload, ValidatedSession
from .provenance import EvidenceStore, ExchangeContext
from .tables import parse_csv, parse_votable_tabledata


def applause_resolve_ids(
    session: ValidatedSession,
    source_ids: list[str],
    process_id: int = 9548,
    solution_num: int = 0,
    *,
    evidence: EvidenceStore | None = None,
):
    if not source_ids:
        return []
    where = " OR ".join(f"source_id={int(x)}" for x in source_ids)
    q = (
        "SELECT source_id,ra_icrs,dec_icrs FROM applause_dr4.source_calib "
        f"WHERE process_id={int(process_id)} AND solution_num={int(solution_num)} AND ({where}) ORDER BY source_id"
    )
    context = ExchangeContext(stage=f"resolve-applause:{process_id}:solution{solution_num}", job_key="batch", attempt=1)
    rows = parse_votable_tabledata(applause_adql(session, q, evidence=evidence, context=context))
    return [
        {"source_id": r["source_id"], "ra_deg": float(r["ra_icrs"]), "dec_deg": float(r["dec_icrs"])}
        for r in rows
    ]


def hamburg_recurrence_worker(
    method: FrozenMethod,
    processes: list[int],
    session: ValidatedSession | None = None,
    *,
    evidence: EvidenceStore | None = None,
    stage: str | None = None,
):
    session = session or ValidatedSession()
    proc = " OR ".join(f"process_id={int(p)}" for p in processes)
    radius_deg = method.hamburg_recurrence_arcsec / 3600.0
    stage = stage or ("hamburg:" + ",".join(str(x) for x in processes))

    def worker(job: Job):
        ra, dec = float(job.payload["ra_deg"]), float(job.payload["dec_deg"])
        q = (
            "SELECT process_id,source_id,ra_icrs,dec_icrs FROM applause_dr4.source_calib "
            f"WHERE ({proc}) AND 1=CONTAINS(POINT('ICRS',ra_icrs,dec_icrs),"
            f"CIRCLE('ICRS',{ra:.15f},{dec:.15f},{radius_deg:.15f})) ORDER BY process_id,source_id"
        )
        context = ExchangeContext(stage=stage, job_key=job.job_key, attempt=job.attempts)
        rows = parse_votable_tabledata(applause_adql(session, q, evidence=evidence, context=context))
        hits = []
        for r in rows:
            sep = angular_sep_arcsec(ra, dec, float(r["ra_icrs"]), float(r["dec_icrs"]))
            if sep <= method.hamburg_recurrence_arcsec + 1e-9:
                hits.append((sep, int(r["process_id"]), r["source_id"]))
        hits.sort()
        return {
            "hamburg_recurrence_match": bool(hits),
            "hamburg_recurrence_hit_count": len(hits),
            "hamburg_nearest_sep_arcsec": hits[0][0] if hits else None,
            "hamburg_nearest_process_id": hits[0][1] if hits else None,
            "hamburg_nearest_source_id": hits[0][2] if hits else None,
        }

    return worker


def gps1_worker(
    method: FrozenMethod,
    session: ValidatedSession | None = None,
    *,
    evidence: EvidenceStore | None = None,
    stage: str | None = None,
):
    session = session or ValidatedSession()
    radius_deg = method.gps1_query_radius_arcsec / 3600.0
    stage = stage or f"gps1:epoch{method.gps1_epoch}"

    def worker(job: Job):
        ra, dec = float(job.payload["ra_deg"]), float(job.payload["dec_deg"])
        q = (
            "SELECT TOP 20000 \"RAICRS\",\"DEICRS\",\"objid\",\"pmRA\",\"pmDE\" "
            "FROM \"I/343/gps1\" WHERE \"pmRA\" IS NOT NULL AND \"pmDE\" IS NOT NULL AND "
            f"1=CONTAINS(POINT('ICRS',\"RAICRS\",\"DEICRS\"),CIRCLE('ICRS',{ra:.15f},{dec:.15f},{radius_deg:.15f}))"
        )
        context = ExchangeContext(stage=stage, job_key=job.job_key, attempt=job.attempts)
        rows = parse_csv(vizier_adql_csv(session, q, evidence=evidence, context=context))
        if len(rows) >= 20000:
            raise InvalidRemotePayload("GPS1 query hit TOP 20000 cap; result is scientifically unusable")
        nearest = None
        for r in rows:
            try:
                hra, hdec = propagate_gps1_to_epoch(
                    float(r["RAICRS"]),
                    float(r["DEICRS"]),
                    float(r["pmRA"]),
                    float(r["pmDE"]),
                    method.gps1_epoch,
                )
            except (ValueError, TypeError):
                continue
            sep = angular_sep_arcsec(ra, dec, hra, hdec)
            item = (sep, r.get("objid", ""), hra, hdec)
            if nearest is None or item[0] < nearest[0]:
                nearest = item
        if nearest is None:
            return {
                "gps1_rows": len(rows),
                "gps1_nearest_sep_arcsec": None,
                "gps1_nearest_objid": None,
                "gps1_static_veto": False,
            }
        return {
            "gps1_rows": len(rows),
            "gps1_nearest_sep_arcsec": nearest[0],
            "gps1_nearest_objid": nearest[1],
            "gps1_nearest_ra_epoch": nearest[2],
            "gps1_nearest_dec_epoch": nearest[3],
            "gps1_static_veto": nearest[0] <= method.gps1_static_veto_arcsec,
        }

    return worker
