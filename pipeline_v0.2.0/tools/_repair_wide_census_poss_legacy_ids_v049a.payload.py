
from __future__ import annotations

from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.request

from transient_pipeline.poss1 import load_vi25_records, vi25_start_utc
from transient_pipeline.poss1_skyview import (
    parse_skyview_descriptor,
    raw_plate_directory,
    hhh_identity,
    expected_region_for_vi25,
)

ROOT = Path.cwd()

QUEUE = ROOT / "results" / "wide_census_physical_timing_queue_v048.csv"
V049 = ROOT / "results" / "wide_census_physical_timing_v049.json"
POSS_META = ROOT / "research" / "census_inputs" / "poss1_plate_metadata.csv"
POLICY = ROOT / "config" / "candidate_adjudication_policy_v002.json"

V049_CACHE = ROOT / "results" / "wide_census_physical_timing_v049" / "cache"
OUT_DIR = ROOT / "results" / "wide_census_physical_timing_v049a"
CACHE = OUT_DIR / "cache"
CHECKPOINT = OUT_DIR / "checkpoint_v049a.json"

OUT_JSON = ROOT / "results" / "wide_census_physical_timing_v049a.json"
OUT_CSV = ROOT / "results" / "wide_census_physical_timing_v049a.csv"
SURVIVOR_CSV = ROOT / "results" / "wide_census_timing_survivors_for_footprint_v049a.csv"
AUDIT_CSV = ROOT / "results" / "poss_legacy_identity_resolution_audit_v049a.csv"

EXPECTED_POSS_SHA = "41b5732086f5a1d17e6f6d85c99f97a48a0985f19db1ad496cd3e3a2387830c1"
EXPECTED_POLICY_ID = "candidate_adjudication_policy_v002"
EXPECTED_QUEUE_ROWS = 111
EXPECTED_LEGACY_POSS_IDS = 18
EXPECTED_V049_COUNTS = {
    "NO_ARCHIVE_SUPPORTED_TIME_OVERLAP": 5,
    "TIMING_OVERLAP_FRAGILE_TO_DOCUMENTED_UNCERTAINTY": 6,
    "TIMING_OVERLAP_SURVIVES_ARCHIVE_SUPPORTED_NO_COMPLETE_FORMAL_UNCERTAINTY": 82,
    "UNRESOLVED_TIMING_OR_IDENTITY": 18,
}

DSS_DESCRIPTOR = {
    "E": "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1r.xml.gz",
    "O": "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1b.xml.gz",
}

UA = "historical-transient-pipeline/wide-census-poss-legacy-repair-v049a"
REMOTE_BATCH = 6
MAX_TRANSPORT_ATTEMPTS = 4


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_time(value):
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    x = dt.datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc)


def interval_overlap(a0, a1, b0, b1):
    start = max(a0, b0)
    end = min(a1, b1)
    return start, end, max(0.0, (end - start).total_seconds())


def conservative_overlap(a0, a1, b0, b1, ua_s, ub_s):
    vals = []
    for sa in (-ua_s, ua_s):
        for sb in (-ub_s, ub_s):
            _, _, sec = interval_overlap(
                a0 + dt.timedelta(seconds=sa),
                a1 + dt.timedelta(seconds=sa),
                b0 + dt.timedelta(seconds=sb),
                b1 + dt.timedelta(seconds=sb),
            )
            vals.append(sec)
    return min(vals)


def get_bytes(url: str, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read(), getattr(response, "status", None), response.geturl()


def source_kind(exposure: str) -> str:
    s = str(exposure)
    if s.startswith("POSS-I:"):
        return "POSS"
    if s.startswith("APPLAUSE:"):
        return "APPLAUSE"
    if "DASCH:" in s or "/dasch/q/" in s:
        return "DASCH"
    return "UNKNOWN"


def parse_legacy_poss_id(exposure: str):
    m = re.fullmatch(r"POSS-I:(\d+):([EO])", str(exposure).strip(), re.I)
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def raw_clock_field(band: str) -> str:
    return "ObsE" if band == "E" else "ObsO"


def raw_duration_field(band: str) -> str:
    return "Eexp" if band == "E" else "Oexp"


def queue_occurrences(queue, exposure: str):
    found = []
    for row in queue:
        for side in ("a", "b"):
            if str(row[f"exposure_{side}"]).strip() == exposure:
                found.append({
                    "catalog_start_utc": row[f"catalog_start_{side}_utc"],
                    "canonical_pair": row["canonical_pair"],
                })
    return found


def select_legacy_vi25_identity(exposure: str, queue, raw_rows):
    parsed = parse_legacy_poss_id(exposure)
    if parsed is None:
        return {
            "status": "UNRESOLVED_NOT_LEGACY_POSS_ID",
            "exposure": exposure,
        }

    poss_number, band = parsed
    occurrences = queue_occurrences(queue, exposure)
    if not occurrences:
        return {
            "status": "UNRESOLVED_NO_QUEUE_OCCURRENCE",
            "exposure": exposure,
        }

    candidates = []
    for row in raw_rows:
        try:
            row_poss = int(str(row["POSS"]).strip())
        except Exception:
            continue
        if row_poss != poss_number:
            continue

        obs_date = str(row.get("Obs", "")).strip()
        raw_clock = str(row.get(raw_clock_field(band), "")).strip()
        recno = str(row.get("recno", "")).strip()

        exact_hits = []
        for occurrence in occurrences:
            cat = parse_time(occurrence["catalog_start_utc"])
            if obs_date == cat.date().isoformat() and raw_clock == cat.strftime("%H:%M"):
                exact_hits.append(occurrence["canonical_pair"])

        candidates.append({
            "recno": recno,
            "obs_date": obs_date,
            "raw_clock": raw_clock,
            "exact_identity_hits": exact_hits,
            "exact_hit_count": len(exact_hits),
        })

    matched = [x for x in candidates if x["exact_hit_count"] > 0]
    if len(matched) != 1:
        return {
            "status": "UNRESOLVED_LEGACY_POSS_IDENTITY_AMBIGUOUS",
            "exposure": exposure,
            "poss_number": poss_number,
            "band": band,
            "queue_occurrences": occurrences,
            "candidate_rows": candidates,
            "matching_candidate_count": len(matched),
        }

    selected = matched[0]
    return {
        "status": "IDENTITY_RESOLVED",
        "exposure": exposure,
        "poss_number": poss_number,
        "band": band,
        "vi25_recno": int(selected["recno"]),
        "legacy_identity_rule": (
            "POSS number + band + exact VI/25 raw observing date/clock match "
            "to the pre-existing wide-inventory catalogue timestamp. "
            "This clock is used for identity selection only, never as final UTC timing."
        ),
        "selected_raw_obs_date": selected["obs_date"],
        "selected_raw_clock": selected["raw_clock"],
        "exact_identity_hits": selected["exact_identity_hits"],
        "candidate_rows_considered": candidates,
    }


def descriptor_path(band: str):
    return V049_CACHE / f"skyview_dss1_{band.lower()}_descriptor.xml"


def load_descriptor(band: str):
    path = descriptor_path(band)
    if not path.is_file():
        raise RuntimeError(f"REFUSING: v049 descriptor cache missing: {path}")
    return parse_skyview_descriptor(path.read_bytes())


def poss_cache_path(exposure: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", exposure)
    return CACHE / "poss" / f"{safe}.json"


def checkpoint_default():
    return {
        "status": "IN_PROGRESS",
        "attempts": {},
        "terminal_transport": {},
        "last_error": None,
    }


def mark_transport(cp, key, exc):
    attempt = int(cp["attempts"].get(key, 0)) + 1
    cp["attempts"][key] = attempt
    cp["last_error"] = {
        "key": key,
        "attempt": attempt,
        "type": type(exc).__name__,
        "message": str(exc),
    }
    if attempt >= MAX_TRANSPORT_ATTEMPTS:
        cp["terminal_transport"][key] = cp["last_error"]
    write_json(CHECKPOINT, cp)
    return attempt


def resolve_poss_physical_identity(identity, vi25_records, descriptors):
    exposure = identity["exposure"]
    recno = int(identity["vi25_recno"])
    band = identity["band"]

    record = vi25_records.get(recno)
    if record is None:
        return {
            "status": "UNRESOLVED_POSS_VI25_RECNO",
            "exposure": exposure,
            "vi25_recno": recno,
        }

    start = vi25_start_utc(record, band)
    duration_min = record.eexp_min if band == "E" else record.oexp_min
    if duration_min is None or float(duration_min) <= 0:
        return {
            "status": "UNRESOLVED_POSS_VI25_DURATION",
            "exposure": exposure,
            "vi25_recno": recno,
        }
    end = start + dt.timedelta(minutes=float(duration_min))

    region = expected_region_for_vi25(record, band).upper()
    matches = [x for x in descriptors[band].images if Path(x.path).name.upper() == region]
    if len(matches) != 1:
        return {
            "status": "UNRESOLVED_POSS_DESCRIPTOR_REGION",
            "exposure": exposure,
            "expected_region": region,
            "descriptor_matches": len(matches),
        }

    entry = matches[0]
    raw_dir = raw_plate_directory(band=band, region=region, descriptor_entry=entry)
    hhh_url = f"{raw_dir}/{region.lower()}.hhh"

    try:
        raw, http_status, final_url = get_bytes(hhh_url, "application/octet-stream,*/*")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "status": "UNRESOLVED_POSS_RAW_HHH_ARCHIVE_UNAVAILABLE",
                "exposure": exposure,
                "expected_region": region,
                "http_status": 404,
            }
        raise

    ident = hhh_identity(raw)
    if str(ident.get("region", "")).strip().upper() != region:
        return {
            "status": "UNRESOLVED_POSS_HHH_REGION",
            "exposure": exposure,
            "expected_region": region,
        }
    if not ident.get("plate_id"):
        return {
            "status": "UNRESOLVED_POSS_HHH_PLATE_ID",
            "exposure": exposure,
            "expected_region": region,
        }

    hhh_date = str(ident.get("date_obs", ""))[:10]
    allowed_dates = {str(record.obs).strip(), start.date().isoformat()}
    if hhh_date and hhh_date not in allowed_dates:
        return {
            "status": "UNRESOLVED_POSS_HHH_DATE_IDENTITY",
            "exposure": exposure,
            "expected_region": region,
            "hhh_date": hhh_date,
            "allowed_dates": sorted(allowed_dates),
        }

    return {
        "status": "RESOLVED",
        "kind": "POSS",
        "exposure": exposure,
        "poss_number": identity["poss_number"],
        "band": band,
        "vi25_recno": recno,
        "region": region,
        "hhh_plate_id": ident.get("plate_id"),
        "physical_plate_key": f"POSS:{band}:{region}:{ident.get('plate_id')}",
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "duration_s": float(duration_min) * 60.0,
        "timing_basis": "AUTHORITATIVE_VI25_NORMALIZED_UTC_PLUS_VI25_BAND_DURATION",
        "timing_quality": "VI25_NORMALIZED_PST_UTC",
        "formal_time_accuracy_s": None,
        "legacy_catalog_clock_used_for_timing": False,
        "legacy_catalog_clock_used_for_identity_only": True,
        "legacy_identity_audit": identity,
        "hhh_clock_used_for_timing": False,
        "hhh_date_identity_only": True,
        "hhh_date": hhh_date,
        "allowed_hhh_dates": sorted(allowed_dates),
        "hhh_url": hhh_url,
        "hhh_final_url": final_url,
        "hhh_http_status": http_status,
        "hhh_sha256": hashlib.sha256(raw).hexdigest(),
    }


def evaluate_pair(queue_row, a, b):
    base = {
        "timing_validation_priority": int(queue_row["timing_validation_priority"]),
        "current_time_gate": queue_row["current_time_gate"],
        "canonical_pair": queue_row["canonical_pair"],
        "exposure_a": queue_row["exposure_a"],
        "archive_a": queue_row["archive_a"],
        "exposure_b": queue_row["exposure_b"],
        "archive_b": queue_row["archive_b"],
        "side_a": a,
        "side_b": b,
    }

    if a.get("status") != "RESOLVED" or b.get("status") != "RESOLVED":
        base.update({
            "classification": "UNRESOLVED_TIMING_OR_IDENTITY",
            "timing_survivor": False,
            "science_eligible": False,
        })
        return base

    if a.get("physical_plate_key") == b.get("physical_plate_key"):
        base.update({
            "classification": "NOT_INDEPENDENT_SAME_PHYSICAL_PLATE",
            "timing_survivor": False,
            "science_eligible": False,
        })
        return base

    a0, a1 = parse_time(a["start_utc"]), parse_time(a["end_utc"])
    b0, b1 = parse_time(b["start_utc"]), parse_time(b["end_utc"])
    overlap_start, overlap_end, nominal = interval_overlap(a0, a1, b0, b1)

    ua = a.get("formal_time_accuracy_s")
    ub = b.get("formal_time_accuracy_s")
    ua_known = float(ua) if ua is not None else 0.0
    ub_known = float(ub) if ub is not None else 0.0
    conservative = conservative_overlap(a0, a1, b0, b1, ua_known, ub_known)
    formal_complete = ua is not None and ub is not None

    if nominal <= 0:
        classification = "NO_ARCHIVE_SUPPORTED_TIME_OVERLAP"
        survivor = False
    elif (ua is not None or ub is not None) and conservative <= 0:
        classification = "TIMING_OVERLAP_FRAGILE_TO_DOCUMENTED_UNCERTAINTY"
        survivor = False
    elif formal_complete:
        classification = "TIMING_OVERLAP_SURVIVES_CONSERVATIVE"
        survivor = True
    else:
        classification = "TIMING_OVERLAP_SURVIVES_ARCHIVE_SUPPORTED_NO_COMPLETE_FORMAL_UNCERTAINTY"
        survivor = True

    base.update({
        "classification": classification,
        "timing_survivor": survivor,
        "science_eligible": False,
        "physical_overlap_start_utc": overlap_start.isoformat() if nominal > 0 else "",
        "physical_overlap_end_utc": overlap_end.isoformat() if nominal > 0 else "",
        "physical_overlap_s": nominal,
        "conservative_overlap_known_uncertainties_s": conservative,
        "formal_time_uncertainty_available_both": formal_complete,
        "next_gate": "TRUE_FOOTPRINT_AND_PHYSICAL_PLATE_PROVENANCE_REVIEW" if survivor else "",
    })
    return base


def main():
    print("=" * 132)
    print("WIDE CENSUS — LEGACY POSS IDENTITY REPAIR + TIMING RECLASSIFICATION v049a")
    print("=" * 132)
    print("NETWORK: up to 18 SkyView raw HHH identity metadata requests only.")
    print("NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("Legacy catalogue clock is used only to recover the missing VI/25 recno; final POSS timing still uses vi25_start_utc().\n")

    for path in (QUEUE, V049, POSS_META, POLICY):
        if not path.is_file():
            raise RuntimeError(f"REFUSING: missing required input: {path}")

    if sha256_file(POSS_META) != EXPECTED_POSS_SHA:
        raise RuntimeError("REFUSING: pinned POSS VI/25 source hash changed")

    policy = load_json(POLICY, {})
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise RuntimeError("REFUSING: candidate adjudication policy mismatch")

    v049 = load_json(V049, {})
    if v049.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: v049 is not complete")
    if v049.get("classification_counts") != EXPECTED_V049_COUNTS:
        raise RuntimeError(
            "REFUSING: unexpected v049 classification state: "
            + json.dumps(v049.get("classification_counts"), sort_keys=True)
        )

    queue = read_csv(QUEUE)
    if len(queue) != EXPECTED_QUEUE_ROWS:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_QUEUE_ROWS} queue rows, got {len(queue)}")

    legacy_ids = sorted({
        row[f"exposure_{side}"]
        for row in queue
        for side in ("a", "b")
        if parse_legacy_poss_id(row[f"exposure_{side}"]) is not None
    })
    if len(legacy_ids) != EXPECTED_LEGACY_POSS_IDS:
        raise RuntimeError(
            f"REFUSING: expected {EXPECTED_LEGACY_POSS_IDS} legacy POSS IDs, got {len(legacy_ids)}"
        )

    raw_rows = read_csv(POSS_META)
    identity_audit = [select_legacy_vi25_identity(x, queue, raw_rows) for x in legacy_ids]
    unresolved_identity = [x for x in identity_audit if x["status"] != "IDENTITY_RESOLVED"]
    if unresolved_identity:
        raise RuntimeError(
            "REFUSING: deterministic local legacy-ID preflight did not resolve all 18: "
            + json.dumps(unresolved_identity, sort_keys=True)
        )

    print("Local legacy POSS identity preflight: 18/18 uniquely resolved")
    for item in identity_audit:
        print(
            f"  {item['exposure']} -> rec{item['vi25_recno']} "
            f"({item['selected_raw_obs_date']} {item['selected_raw_clock']}, identity-only)"
        )

    # Audit CSV is written before any network request.
    audit_fields = [
        "exposure", "poss_number", "band", "vi25_recno",
        "selected_raw_obs_date", "selected_raw_clock", "status",
    ]
    tmp = AUDIT_CSV.with_suffix(AUDIT_CSV.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=audit_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(identity_audit)
    tmp.replace(AUDIT_CSV)

    vi25_records = load_vi25_records(POSS_META)
    descriptors = {"E": load_descriptor("E"), "O": load_descriptor("O")}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = load_json(CHECKPOINT, checkpoint_default())

    identity_by_id = {x["exposure"]: x for x in identity_audit}
    remote_this_run = 0

    for exposure in legacy_ids:
        cache_path = poss_cache_path(exposure)
        if cache_path.is_file():
            continue

        key = f"poss:{exposure}"
        if key in cp["terminal_transport"]:
            write_json(
                cache_path,
                {
                    "status": "METADATA_TRANSPORT_UNRESOLVED",
                    "exposure": exposure,
                    "transport": cp["terminal_transport"][key],
                },
            )
            continue

        if remote_this_run >= REMOTE_BATCH:
            break

        try:
            result = resolve_poss_physical_identity(
                identity_by_id[exposure],
                vi25_records,
                descriptors,
            )
            write_json(cache_path, result)
            print(f"POSS {exposure}: {result.get('status')}")
        except Exception as exc:
            attempt = mark_transport(cp, key, exc)
            print(
                f"POSS transport retry {attempt}/{MAX_TRANSPORT_ATTEMPTS} "
                f"{exposure}: {type(exc).__name__}: {exc}"
            )

        remote_this_run += 1

    done = sum(poss_cache_path(x).is_file() for x in legacy_ids)
    cp.update({
        "status": "IN_PROGRESS",
        "poss_legacy_done": done,
        "poss_legacy_total": len(legacy_ids),
    })
    write_json(CHECKPOINT, cp)

    if done < len(legacy_ids):
        print(f"\nCHECKPOINT: repaired POSS metadata {done}/{len(legacy_ids)}")
        print("RETURN 10: checkpointed IN_PROGRESS")
        return 10

    repaired_poss = {
        exposure: load_json(poss_cache_path(exposure), {})
        for exposure in legacy_ids
    }

    v049_pairs = {
        row["canonical_pair"]: row
        for row in v049.get("pairs", [])
    }
    if len(v049_pairs) != EXPECTED_QUEUE_ROWS:
        raise RuntimeError(
            f"REFUSING: expected {EXPECTED_QUEUE_ROWS} v049 pair records, got {len(v049_pairs)}"
        )

    repaired_pairs = []
    for queue_row in queue:
        old = v049_pairs.get(queue_row["canonical_pair"])
        if old is None:
            raise RuntimeError(f"REFUSING: v049 pair missing: {queue_row['canonical_pair']}")

        exp_a = queue_row["exposure_a"]
        exp_b = queue_row["exposure_b"]

        a = repaired_poss.get(exp_a, old.get("side_a", {}))
        b = repaired_poss.get(exp_b, old.get("side_b", {}))
        repaired_pairs.append(evaluate_pair(queue_row, a, b))

    counts = {}
    for row in repaired_pairs:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1

    survivors = [x for x in repaired_pairs if x.get("timing_survivor")]
    unresolved = [
        x for x in repaired_pairs
        if x["classification"] == "UNRESOLVED_TIMING_OR_IDENTITY"
    ]

    fields = [
        "timing_validation_priority", "current_time_gate", "canonical_pair",
        "exposure_a", "archive_a", "exposure_b", "archive_b",
        "classification", "timing_survivor", "science_eligible",
        "physical_overlap_start_utc", "physical_overlap_end_utc",
        "physical_overlap_s", "conservative_overlap_known_uncertainties_s",
        "formal_time_uncertainty_available_both", "next_gate",
    ]

    for path, rows in (
        (OUT_CSV, repaired_pairs),
        (SURVIVOR_CSV, survivors),
    ):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(path)

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_physical_timing_poss_legacy_repair_v049a",
        "supersedes_for_census_interpretation": "wide_census_physical_timing_v049",
        "guards": {
            "network_access": True,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "input_sha256": {
            "queue": sha256_file(QUEUE),
            "v049": sha256_file(V049),
            "poss_vi25": sha256_file(POSS_META),
            "policy": sha256_file(POLICY),
        },
        "legacy_poss_identity_repair": {
            "legacy_ids": len(legacy_ids),
            "locally_uniquely_resolved": len(identity_audit),
            "identity_rule": (
                "POSS number + band + exact legacy VI/25 raw date/clock match. "
                "Legacy clock is identity-only; final UTC is recomputed using vi25_start_utc()."
            ),
            "audit_csv": str(AUDIT_CSV.relative_to(ROOT)),
        },
        "classification_counts": counts,
        "timing_survivor_count": len(survivors),
        "unresolved_pair_count": len(unresolved),
        "science_eligible_count": 0,
        "interpretation_boundary": (
            "v049a repairs the systematic legacy POSS identifier-format failure in v049. "
            "Timing survivors remain non-science-eligible until true sky-footprint intersection "
            "and physical-observation independence are frozen."
        ),
        "pairs": repaired_pairs,
        "next_stage": (
            "If unresolved_pair_count is zero or all remaining unresolved rows are explicitly "
            "proven archive-unavailable, freeze the true-footprint/independence census for timing survivors."
        ),
    }
    write_json(OUT_JSON, payload)

    cp.update({
        "status": "COMPLETE",
        "classification_counts": counts,
        "timing_survivor_count": len(survivors),
        "unresolved_pair_count": len(unresolved),
    })
    write_json(CHECKPOINT, cp)

    print("\n" + "=" * 132)
    print("LEGACY POSS REPAIR + TIMING RECLASSIFICATION COMPLETE")
    print("=" * 132)
    print("Classification counts:", json.dumps(counts, sort_keys=True))
    print(f"Timing survivors awaiting footprint validation: {len(survivors)}")
    print(f"Unresolved timing/identity pairs: {len(unresolved)}")
    print("SCIENCE ELIGIBLE: 0")
    print(f"Report: {OUT_JSON}")
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
