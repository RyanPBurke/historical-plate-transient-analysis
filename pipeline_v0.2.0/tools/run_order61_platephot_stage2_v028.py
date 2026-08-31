from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
import time
from collections import Counter

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_platephot_stage2_v028"
CACHE = WORK / "api_cache"

PAIR_REPORT = BASE / "order61_whole_pair_report.json"
PREFLIGHT_REPORT = BASE / "order61_platephot_preflight_report.json"
EXPOSURE_CENSUS = BASE / "order61_queryexps_exposure_census.csv"
PS1_TRIAGE = BASE / "order61_ps1_static_triage.csv"

STAGE1_REPORT = BASE / "order61_platephot_stage1_report.json"
STAGE1_POLICY = BASE / "order61_platephot_stage1_policy.json"
STAGE1_MANIFEST = BASE / "order61_platephot_stage1_manifest.csv"
STAGE1_DETAIL = BASE / "order61_platephot_stage1_detail.csv"
STAGE1_PLATES = BASE / "order61_platephot_stage1_plate_summary.csv"

CUM_MANIFEST = BASE / "order61_platephot_stage2_cumulative_manifest.csv"
NEW_MANIFEST = BASE / "order61_platephot_stage2_new_call_manifest.csv"
POLICY = BASE / "order61_platephot_stage2_policy.json"
DETAIL_NEW = BASE / "order61_platephot_stage2_detail_new.csv"
PLATES_NEW = BASE / "order61_platephot_stage2_plate_summary_new.csv"
RANK_CUM = BASE / "order61_platephot_stage2_rank_summary_cumulative.csv"
REPORT = BASE / "order61_platephot_stage2_report.json"

for d in (WORK, CACHE):
    d.mkdir(parents=True, exist_ok=True)

API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/platephot"
UA = "historical-transient-pipeline/0.2.8-order61-platephot-stage2"

EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa"
    "0fd0fee864a81d954f74fe4a5f5af25e7"
)
EXPECTED_METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd30"
    "02be90297e55bb0e0dcdd9dea1d0c4c1"
)
EXPECTED_POLICY_SHA = (
    "44fc3453c3291a7cbe72894d781729a3"
    "0943ad540aa169b2c0897b446c5c8ec7"
)

STAGE1_MANIFEST_SHA = (
    "272b767d112769ed5b75a147c2dddbbea"
    "199eb07952f641cb5d86405c93a69fd"
)
STAGE1_POLICY_SHA = (
    "fddf36901281c19884f24da940bc5d8d"
    "ebc777540bc520fe3a343b431e5c2e7b"
)

ACTIVE_RANKS = [11, 14, 20]
RECURRENT_STAGE1_RANK = 22
DISCOVERY_PLATE = "ai44092"

STAGE1_PREFIX = 64
STAGE2_CUMULATIVE_PREFIX = 256
SELECTION_SALT = "order61-platephot-stage1-v028-sha256-blind"

STRONG_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
LOCAL_DENSITY_RADIUS_ARCSEC = 60.0
MIN_INDEPENDENT_RECURRENCE_PLATES = 2

REQUEST_PAUSE_S = 0.25
MAX_ATTEMPTS = 4

MANIFEST_FIELDS = [
    "strict_rank",
    "rank_sample_order",
    "selection_sha256",
    "plate_id",
    "series",
    "platenum",
    "solnum",
    "expnum",
    "expdate",
    "selected_refcat_for_platephot",
    "limMagApass",
    "limMagAtlas",
    "centerdist",
    "edgedist",
    "target_ra_deg",
    "target_dec_deg",
]

DETAIL_FIELDS = [
    "strict_rank",
    "rank_sample_order",
    "plate_id",
    "solution_number",
    "refcat",
    "source_index",
    "ra_deg",
    "dec_deg",
    "sep_target_arcsec",
    "within_3arcsec",
    "within_5arcsec",
    "within_60arcsec",
    "ref_number",
    "catalog_matched",
    "catalog_ra_deg",
    "catalog_dec_deg",
    "magcal_magdep",
    "fwhm_world_raw",
    "ellipticity",
    "aflags",
    "bflags",
    "plate_quality_flag",
]

PLATE_FIELDS = [
    "strict_rank",
    "rank_sample_order",
    "plate_id",
    "solution_number",
    "refcat",
    "api_status",
    "response_rows",
    "sources_within_60arcsec",
    "sources_within_5arcsec",
    "sources_within_3arcsec",
    "nearest_sep_arcsec",
    "nearest_ref_number",
    "nearest_catalog_matched",
    "nearest_magcal_magdep",
    "expected_chance_within_3_from_local60",
    "expected_chance_within_5_from_local60",
]

RANK_FIELDS = [
    "strict_rank",
    "cumulative_selected_plates",
    "cumulative_completed_plates",
    "stage2_new_selected_plates",
    "stage2_new_completed_plates",
    "stage2_new_failed_plates",
    "plates_with_source_within_3arcsec",
    "plates_with_source_within_5arcsec",
    "total_sources_within_60arcsec",
    "observed_sources_within_3arcsec",
    "observed_sources_within_5arcsec",
    "expected_chance_within_3_from_local60",
    "expected_chance_within_5_from_local60",
    "multi_independent_plate_recurrence_3arcsec",
    "multi_independent_plate_recurrence_5arcsec",
    "stage2_complete",
]


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ffloat(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "null", "none", "--"}:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def fint(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def normkey(k):
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def getv(row, *aliases):
    nr = {normkey(k): v for k, v in row.items()}
    for a in aliases:
        k = normkey(a)
        if k in nr:
            return nr[k]
    return None


def angular_sep_arcsec(ra1, dec1, ra2, dec2):
    r1 = math.radians(float(ra1))
    d1 = math.radians(float(dec1))
    r2 = math.radians(float(ra2))
    d2 = math.radians(float(dec2))
    dr = r2 - r1
    while dr > math.pi:
        dr -= 2 * math.pi
    while dr < -math.pi:
        dr += 2 * math.pi

    a = (
        math.sin((d2 - d1) / 2.0) ** 2
        + math.cos(d1) * math.cos(d2) * math.sin(dr / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2.0 * math.asin(math.sqrt(a)) * 206264.80624709636


def parse_json_csv_lines(obj, label):
    if not isinstance(obj, list):
        raise RuntimeError(f"{label}: expected JSON list")
    if not obj:
        raise RuntimeError(f"{label}: empty response; missing CSV header")
    if not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{label}: non-string response record")
    text = "\n".join(x.rstrip("\r\n") for x in obj) + "\n"
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise RuntimeError(f"{label}: missing CSV header")
    return list(reader), list(reader.fieldnames)


def build_ordered_candidates(census, triage, ranks):
    target_by_rank = {
        int(r["strict_rank"]): (
            float(r["dasch_ra_deg"]),
            float(r["dasch_dec_deg"]),
        )
        for r in triage
        if int(r["strict_rank"]) in ranks
    }

    out = {}

    for rank in ranks:
        eligible = [
            r for r in census
            if int(r["strict_rank"]) == rank
            and as_bool(r["eligible_independent_platephot"])
            and str(r["plate_id"]).strip().lower() != DISCOVERY_PLATE
        ]

        by_plate = {}

        for r in eligible:
            pid = str(r["plate_id"]).strip().lower()
            key = (
                int(r["solnum"]),
                str(r["selected_refcat_for_platephot"]),
                str(r.get("expdate", "")),
            )
            if pid not in by_plate or key < by_plate[pid][0]:
                by_plate[pid] = (key, r)

        cand = []
        ra, dec = target_by_rank[rank]

        for pid, (_, r) in by_plate.items():
            token = (
                f"{SELECTION_SALT}|rank={rank}|plate={pid}|"
                f"sol={r['solnum']}|refcat={r['selected_refcat_for_platephot']}"
            )
            h = hashlib.sha256(token.encode("utf-8")).hexdigest()
            cand.append({
                "strict_rank": rank,
                "selection_sha256": h,
                "plate_id": pid,
                "series": r["series"],
                "platenum": r["platenum"],
                "solnum": int(r["solnum"]),
                "expnum": r["expnum"],
                "expdate": r["expdate"],
                "selected_refcat_for_platephot": (
                    r["selected_refcat_for_platephot"]
                ),
                "limMagApass": r["limMagApass"],
                "limMagAtlas": r["limMagAtlas"],
                "centerdist": r["centerdist"],
                "edgedist": r["edgedist"],
                "target_ra_deg": ra,
                "target_dec_deg": dec,
            })

        cand.sort(key=lambda q: (q["selection_sha256"], q["plate_id"]))

        for i, r in enumerate(cand, 1):
            r["rank_sample_order"] = i

        out[rank] = cand

    return out


def verify_stage1_prefix(ordered, stage1_manifest):
    for rank in ACTIVE_RANKS:
        old = sorted(
            [
                r for r in stage1_manifest
                if int(r["strict_rank"]) == rank
            ],
            key=lambda r: int(r["rank_sample_order"]),
        )

        if len(old) != STAGE1_PREFIX:
            raise RuntimeError(
                f"REFUSING: stage1 rank {rank} row count {len(old)} != 64"
            )

        new = ordered[rank][:STAGE1_PREFIX]

        for i, (a, b) in enumerate(zip(old, new), 1):
            checks = {
                "rank_sample_order": int(a["rank_sample_order"]) == i,
                "plate_id": str(a["plate_id"]).lower() == b["plate_id"],
                "solnum": int(a["solnum"]) == int(b["solnum"]),
                "refcat": (
                    str(a["selected_refcat_for_platephot"])
                    == b["selected_refcat_for_platephot"]
                ),
                "selection_sha256": (
                    str(a["selection_sha256"]) == b["selection_sha256"]
                ),
            }
            if not all(checks.values()):
                raise RuntimeError(
                    f"REFUSING: stage1 prefix mismatch rank={rank} "
                    f"order={i}: {checks}"
                )


def curl_platephot(item):
    rank = int(item["strict_rank"])
    order = int(item["rank_sample_order"])
    plate = item["plate_id"]
    solnum = int(item["solnum"])
    refcat = item["selected_refcat_for_platephot"]

    stem = f"r{rank:02d}_{order:03d}_{plate}_s{solnum}_{refcat}"
    raw_path = CACHE / f"{stem}.json"
    meta_path = CACHE / f"{stem}.meta.json"

    payload = {
        "plate_id": plate,
        "solution_number": solnum,
        "refcat": refcat,
        "center_ra_deg": float(item["target_ra_deg"]),
        "center_dec_deg": float(item["target_dec_deg"]),
    }

    if raw_path.is_file() and meta_path.is_file():
        raw = raw_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("complete") is True
            and meta.get("payload") == payload
            and meta.get("sha256") == sha256_bytes(raw)
        ):
            rows, header = parse_json_csv_lines(
                json.loads(raw.decode("utf-8")),
                stem,
            )
            return rows, header, "cached"

    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl.exe/curl unavailable; TLS will not be weakened")

    part = raw_path.with_suffix(".json.part")
    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    errors = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if part.exists():
            part.unlink()

        cmd = [
            curl,
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout", "30",
            "--max-time", "180",
            "--user-agent", UA,
            "--header", "Accept: application/json",
            "--header", "Content-Type: application/json",
            "--data-binary", payload_text,
            "--output", str(part),
            API,
        ]

        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=210,
                check=False,
            )

            if cp.returncode != 0:
                err = (cp.stderr or cp.stdout or "").strip()
                raise RuntimeError(f"curl exit {cp.returncode}: {err[:600]}")

            if not part.is_file():
                raise RuntimeError("curl success without response file")

            raw = part.read_bytes()
            rows, header = parse_json_csv_lines(
                json.loads(raw.decode("utf-8")),
                stem,
            )

            part.replace(raw_path)
            write_json(meta_path, {
                "complete": True,
                "payload": payload,
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
                "row_count": len(rows),
                "transport": "curl_verified_https",
                "tls_verification_disabled": False,
            })

            time.sleep(REQUEST_PAUSE_S)
            return rows, header, "done"

        except (
            subprocess.TimeoutExpired,
            RuntimeError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(repr(exc))
            print(
                f"    {stem} attempt {attempt}/{MAX_ATTEMPTS} FAILED: {exc}",
                flush=True,
            )
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)

    raise RuntimeError(errors[-1])


def parse_source(item, idx, row):
    ra = ffloat(getv(row, "ra_deg", "raDeg", "ra"))
    dec = ffloat(getv(row, "dec_deg", "decDeg", "dec"))
    if ra is None or dec is None:
        return None

    tra = float(item["target_ra_deg"])
    tdec = float(item["target_dec_deg"])
    sep = angular_sep_arcsec(tra, tdec, ra, dec)

    refnum = fint(getv(row, "ref_number", "refNumber"))

    return {
        "strict_rank": int(item["strict_rank"]),
        "rank_sample_order": int(item["rank_sample_order"]),
        "plate_id": item["plate_id"],
        "solution_number": int(item["solnum"]),
        "refcat": item["selected_refcat_for_platephot"],
        "source_index": idx,
        "ra_deg": ra,
        "dec_deg": dec,
        "sep_target_arcsec": sep,
        "within_3arcsec": sep <= STRONG_ARCSEC,
        "within_5arcsec": sep <= DIAGNOSTIC_ARCSEC,
        "within_60arcsec": sep <= LOCAL_DENSITY_RADIUS_ARCSEC,
        "ref_number": refnum,
        "catalog_matched": refnum is not None and refnum >= 0,
        "catalog_ra_deg": ffloat(getv(row, "catalog_ra", "catalogRa")),
        "catalog_dec_deg": ffloat(getv(row, "catalog_dec", "catalogDec")),
        "magcal_magdep": ffloat(getv(row, "magcal_magdep", "magcalMagdep")),
        "fwhm_world_raw": ffloat(getv(
            row, "fwhm_world", "fwhmWorld", "fwhmDeg"
        )),
        "ellipticity": ffloat(getv(row, "ellipticity")),
        "aflags": fint(getv(row, "aflags")),
        "bflags": fint(getv(row, "bflags")),
        "plate_quality_flag": fint(getv(
            row, "plate_quality_flag", "plateQualityFlag"
        )),
    }


def summarize_plate(item, sources, status, response_rows):
    local60 = [s for s in sources if s["within_60arcsec"]]
    close5 = [s for s in sources if s["within_5arcsec"]]
    close3 = [s for s in sources if s["within_3arcsec"]]

    nearest = min(
        sources,
        key=lambda s: float(s["sep_target_arcsec"]),
        default=None,
    )

    n60 = len(local60)

    return {
        "strict_rank": int(item["strict_rank"]),
        "rank_sample_order": int(item["rank_sample_order"]),
        "plate_id": item["plate_id"],
        "solution_number": int(item["solnum"]),
        "refcat": item["selected_refcat_for_platephot"],
        "api_status": status,
        "response_rows": response_rows,
        "sources_within_60arcsec": n60,
        "sources_within_5arcsec": len(close5),
        "sources_within_3arcsec": len(close3),
        "nearest_sep_arcsec": (
            None if nearest is None else nearest["sep_target_arcsec"]
        ),
        "nearest_ref_number": (
            None if nearest is None else nearest["ref_number"]
        ),
        "nearest_catalog_matched": (
            None if nearest is None else nearest["catalog_matched"]
        ),
        "nearest_magcal_magdep": (
            None if nearest is None else nearest["magcal_magdep"]
        ),
        "expected_chance_within_3_from_local60": (
            n60 * (STRONG_ARCSEC / LOCAL_DENSITY_RADIUS_ARCSEC) ** 2
        ),
        "expected_chance_within_5_from_local60": (
            n60 * (DIAGNOSTIC_ARCSEC / LOCAL_DENSITY_RADIUS_ARCSEC) ** 2
        ),
    }


def rank22_disposition(stage1_detail, stage1_report):
    r22 = next(
        r for r in stage1_report["rank_summaries"]
        if int(r["strict_rank"]) == 22
    )

    close5 = [
        r for r in stage1_detail
        if int(r["strict_rank"]) == 22
        and float(r["sep_target_arcsec"]) <= DIAGNOSTIC_ARCSEC
    ]
    within60 = [
        r for r in stage1_detail
        if int(r["strict_rank"]) == 22
        and float(r["sep_target_arcsec"]) <= LOCAL_DENSITY_RADIUS_ARCSEC
    ]

    groups5 = Counter(
        (str(r["refcat"]), str(r["ref_number"]))
        for r in close5
    )
    groups60 = Counter(
        (str(r["refcat"]), str(r["ref_number"]))
        for r in within60
    )

    return {
        "strict_rank": 22,
        "stage1_fixed_gate_recurrence_5arcsec": bool(
            r22["multi_independent_plate_recurrence_5arcsec"]
        ),
        "stage1_fixed_gate_recurrence_3arcsec": bool(
            r22["multi_independent_plate_recurrence_3arcsec"]
        ),
        "plates_with_source_within_5arcsec": int(
            r22["plates_with_source_within_5arcsec"]
        ),
        "plates_with_source_within_3arcsec": int(
            r22["plates_with_source_within_3arcsec"]
        ),
        "close5_reference_groups": [
            {"refcat": k[0], "ref_number": k[1], "count": v}
            for k, v in groups5.most_common()
        ],
        "within60_reference_groups_top10": [
            {"refcat": k[0], "ref_number": k[1], "count": v}
            for k, v in groups60.most_common(10)
        ],
        "disposition": (
            "HISTORICAL_RECURRENCE_STATIC_CONTAMINATION_AT_PREDECLARED_5ARCSEC_GATE"
        ),
        "retained_in_audit": True,
        "included_in_stage2_expansion": False,
        "reason": (
            "Stage 1 met the prospectively fixed >=2 independent physical "
            "plate recurrence criterion within the 5-arcsec diagnostic gate. "
            "Eight of nine <=5-arcsec rows share one APASS reference number; "
            "the result is therefore dominated by a repeatedly observed "
            "persistent reference source rather than independent random "
            "single-plate coincidences."
        ),
    }


def main():
    print("=" * 98)
    print("ORDER 61 — DASCH PLATEPHOT RECURRENCE STAGE 2: SAME BLIND PREFIX TO 256")
    print("=" * 98)
    print(
        "Ranks 11/14/20 only: recurrence not established in Stage 1. "
        "Rank 22 retained as Stage-1 recurrent/static audit disposition."
    )
    print()

    required = [
        PAIR_REPORT, PREFLIGHT_REPORT, EXPOSURE_CENSUS, PS1_TRIAGE,
        STAGE1_REPORT, STAGE1_POLICY, STAGE1_MANIFEST,
        STAGE1_DETAIL, STAGE1_PLATES,
    ]
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT_REPORT.read_text(encoding="utf-8"))
    stage1_report = json.loads(STAGE1_REPORT.read_text(encoding="utf-8"))
    stage1_policy = json.loads(STAGE1_POLICY.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 61,
        "detector": pair_report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": pair_report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "preflight_complete": preflight.get("status") == "COMPLETE",
        "stage1_complete": stage1_report.get("status") == "COMPLETE",
        "stage1_manifest_sha": sha256_file(STAGE1_MANIFEST) == STAGE1_MANIFEST_SHA,
        "stage1_policy_sha": sha256_file(STAGE1_POLICY) == STAGE1_POLICY_SHA,
        "stage1_report_manifest_sha": (
            stage1_report.get("manifest_sha256") == STAGE1_MANIFEST_SHA
        ),
        "stage1_report_policy_sha": (
            stage1_report.get("policy_sha256") == STAGE1_POLICY_SHA
        ),
        "same_selection_salt": (
            stage1_policy.get("selection_salt") == SELECTION_SALT
        ),
        "same_spatial_gates": (
            float(stage1_policy.get("strong_arcsec")) == STRONG_ARCSEC
            and float(stage1_policy.get("diagnostic_arcsec")) == DIAGNOSTIC_ARCSEC
        ),
    }

    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: guard failure: " + json.dumps(guards, sort_keys=True)
        )

    s1_by_rank = {
        int(r["strict_rank"]): r
        for r in stage1_report["rank_summaries"]
    }

    for rank in ACTIVE_RANKS:
        if s1_by_rank[rank]["multi_independent_plate_recurrence_5arcsec"]:
            raise RuntimeError(
                f"REFUSING: rank {rank} already met Stage-1 5-arcsec recurrence"
            )

    if not s1_by_rank[22]["multi_independent_plate_recurrence_5arcsec"]:
        raise RuntimeError(
            "REFUSING: rank 22 did not meet expected Stage-1 recurrence gate"
        )

    census = read_csv(EXPOSURE_CENSUS)
    triage = read_csv(PS1_TRIAGE)
    stage1_manifest = read_csv(STAGE1_MANIFEST)
    stage1_detail = read_csv(STAGE1_DETAIL)
    stage1_plates = read_csv(STAGE1_PLATES)

    ordered = build_ordered_candidates(census, triage, ACTIVE_RANKS)
    verify_stage1_prefix(ordered, stage1_manifest)

    cumulative = []
    new_calls = []

    for rank in ACTIVE_RANKS:
        if len(ordered[rank]) < STAGE2_CUMULATIVE_PREFIX:
            raise RuntimeError(
                f"rank {rank}: only {len(ordered[rank])} ordered plates; "
                f"need {STAGE2_CUMULATIVE_PREFIX}"
            )

        cumulative.extend(ordered[rank][:STAGE2_CUMULATIVE_PREFIX])
        new_calls.extend(
            ordered[rank][STAGE1_PREFIX:STAGE2_CUMULATIVE_PREFIX]
        )

    cumulative.sort(key=lambda r: (
        int(r["rank_sample_order"]),
        int(r["strict_rank"]),
    ))
    new_calls.sort(key=lambda r: (
        int(r["rank_sample_order"]),
        int(r["strict_rank"]),
    ))

    write_csv(CUM_MANIFEST, cumulative, MANIFEST_FIELDS)
    write_csv(NEW_MANIFEST, new_calls, MANIFEST_FIELDS)

    cumulative_sha = sha256_file(CUM_MANIFEST)
    new_sha = sha256_file(NEW_MANIFEST)

    rank22 = rank22_disposition(stage1_detail, stage1_report)

    policy_obj = {
        "analysis_kind": "order61_platephot_recurrence_stage2_fixed",
        "active_ranks": ACTIVE_RANKS,
        "stage1_recurrent_rank_audit_only": 22,
        "stage1_prefix_per_rank": STAGE1_PREFIX,
        "stage2_cumulative_prefix_per_active_rank": STAGE2_CUMULATIVE_PREFIX,
        "new_calls_per_active_rank": STAGE2_CUMULATIVE_PREFIX - STAGE1_PREFIX,
        "total_new_calls": len(new_calls),
        "selection_salt": SELECTION_SALT,
        "selection_rule": (
            "identical Stage-1 one-eligible-exposure-per-physical-plate "
            "ordering by ascending SHA256; Stage 2 uses prefix 65..256 only"
        ),
        "stage1_prefix_verified_exact": True,
        "stage1_manifest_sha256": STAGE1_MANIFEST_SHA,
        "stage1_policy_sha256": STAGE1_POLICY_SHA,
        "cumulative_manifest_sha256": cumulative_sha,
        "new_call_manifest_sha256": new_sha,
        "strong_arcsec": STRONG_ARCSEC,
        "diagnostic_arcsec": DIAGNOSTIC_ARCSEC,
        "local_density_radius_arcsec": LOCAL_DENSITY_RADIUS_ARCSEC,
        "minimum_independent_recurrence_plates": (
            MIN_INDEPENDENT_RECURRENCE_PLATES
        ),
        "rank22_excluded_from_expansion_because_predeclared_gate_met": True,
        "selection_uses_stage2_outcomes": False,
        "selection_uses_exposure_date": False,
        "selection_uses_limiting_magnitude": False,
        "selection_uses_morphology": False,
        "selection_uses_source_density": False,
        "api": API,
        "transport": "curl_verified_https",
        "tls_verification_disabled": False,
    }
    write_json(POLICY, policy_obj)
    policy_sha = sha256_file(POLICY)

    print("Completed-stage guards: PASS")
    print("Stage-1 prefix reproduction for ranks 11/14/20: PASS")
    print(f"Cumulative manifest: {len(cumulative)} rows SHA={cumulative_sha}")
    print(f"New-call manifest:   {len(new_calls)} rows SHA={new_sha}")
    print(f"Stage-2 policy SHA:  {policy_sha}")
    print(
        "Rank #22 disposition: "
        f"{rank22['disposition']} "
        f"(<=5\" plates={rank22['plates_with_source_within_5arcsec']})"
    )
    print("Manifests/policy frozen before first Stage-2 API request: PASS")
    print()

    detail_new = []
    plates_new = []
    failures = []

    for i, item in enumerate(new_calls, 1):
        rank = int(item["strict_rank"])

        try:
            rows, header, status = curl_platephot(item)
        except RuntimeError as exc:
            failures.append({
                "new_call_order": i,
                "strict_rank": rank,
                "rank_sample_order": int(item["rank_sample_order"]),
                "plate_id": item["plate_id"],
                "solnum": int(item["solnum"]),
                "refcat": item["selected_refcat_for_platephot"],
                "error": str(exc),
            })
            print(
                f"  [{i:03d}/{len(new_calls)}] rank #{rank:02d} "
                f"prefix={int(item['rank_sample_order']):03d} "
                f"{item['plate_id']}: FAILED",
                flush=True,
            )
            continue

        sources = []

        for j, row in enumerate(rows, 1):
            s = parse_source(item, j, row)
            if s is not None:
                sources.append(s)

        detail_new.extend(sources)
        ps = summarize_plate(item, sources, status, len(rows))
        plates_new.append(ps)

        nearest = ps["nearest_sep_arcsec"]
        nearest_txt = "none" if nearest is None else f"{float(nearest):.2f}\""

        print(
            f"  [{i:03d}/{len(new_calls)}] rank #{rank:02d} "
            f"prefix={int(item['rank_sample_order']):03d} "
            f"{item['plate_id']} {status.upper():6s} "
            f"n60={int(ps['sources_within_60arcsec']):3d} "
            f"<=5={int(ps['sources_within_5arcsec'])} "
            f"<=3={int(ps['sources_within_3arcsec'])} "
            f"nearest={nearest_txt}",
            flush=True,
        )

        if i % 24 == 0:
            write_csv(DETAIL_NEW, detail_new, DETAIL_FIELDS)
            write_csv(PLATES_NEW, plates_new, PLATE_FIELDS)

    write_csv(DETAIL_NEW, detail_new, DETAIL_FIELDS)
    write_csv(PLATES_NEW, plates_new, PLATE_FIELDS)

    # Cumulative 64 + new 192 summaries for active ranks.
    cumulative_plate_rows = [
        r for r in stage1_plates
        if int(r["strict_rank"]) in ACTIVE_RANKS
    ] + plates_new

    rank_rows = []

    for rank in ACTIVE_RANKS:
        done = [
            r for r in cumulative_plate_rows
            if int(r["strict_rank"]) == rank
        ]
        new_done = [
            r for r in plates_new
            if int(r["strict_rank"]) == rank
        ]
        fail = [
            r for r in failures
            if int(r["strict_rank"]) == rank
        ]

        # No duplicate physical plate in a cumulative prefix.
        pids = [str(r["plate_id"]).lower() for r in done]
        if len(pids) != len(set(pids)):
            raise RuntimeError(
                f"REFUSING: cumulative rank {rank} contains duplicate plate IDs"
            )

        p3 = [r for r in done if int(r["sources_within_3arcsec"]) > 0]
        p5 = [r for r in done if int(r["sources_within_5arcsec"]) > 0]

        rank_rows.append({
            "strict_rank": rank,
            "cumulative_selected_plates": STAGE2_CUMULATIVE_PREFIX,
            "cumulative_completed_plates": len(done),
            "stage2_new_selected_plates": (
                STAGE2_CUMULATIVE_PREFIX - STAGE1_PREFIX
            ),
            "stage2_new_completed_plates": len(new_done),
            "stage2_new_failed_plates": len(fail),
            "plates_with_source_within_3arcsec": len(p3),
            "plates_with_source_within_5arcsec": len(p5),
            "total_sources_within_60arcsec": sum(
                int(r["sources_within_60arcsec"]) for r in done
            ),
            "observed_sources_within_3arcsec": sum(
                int(r["sources_within_3arcsec"]) for r in done
            ),
            "observed_sources_within_5arcsec": sum(
                int(r["sources_within_5arcsec"]) for r in done
            ),
            "expected_chance_within_3_from_local60": sum(
                float(r["expected_chance_within_3_from_local60"]) for r in done
            ),
            "expected_chance_within_5_from_local60": sum(
                float(r["expected_chance_within_5_from_local60"]) for r in done
            ),
            "multi_independent_plate_recurrence_3arcsec": (
                len(p3) >= MIN_INDEPENDENT_RECURRENCE_PLATES
            ),
            "multi_independent_plate_recurrence_5arcsec": (
                len(p5) >= MIN_INDEPENDENT_RECURRENCE_PLATES
            ),
            "stage2_complete": (
                len(done) == STAGE2_CUMULATIVE_PREFIX and len(fail) == 0
            ),
        })

    write_csv(RANK_CUM, rank_rows, RANK_FIELDS)

    status = "COMPLETE" if not failures else "INCOMPLETE_API_FAILURES"

    report = {
        "status": status,
        "analysis_kind": "order61_platephot_recurrence_stage2",
        "guards": guards,
        "policy_sha256": policy_sha,
        "cumulative_manifest_sha256": cumulative_sha,
        "new_call_manifest_sha256": new_sha,
        "rank22_stage1_disposition": rank22,
        "active_rank_summaries_cumulative_256": rank_rows,
        "new_call_count_selected": len(new_calls),
        "new_call_count_completed": len(plates_new),
        "new_call_count_failed": len(failures),
        "failures": failures,
        "no_candidate_deleted": True,
        "rank22_retained_in_audit": True,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "outputs": {
            "policy_json": str(POLICY),
            "cumulative_manifest_csv": str(CUM_MANIFEST),
            "new_call_manifest_csv": str(NEW_MANIFEST),
            "detail_new_csv": str(DETAIL_NEW),
            "plate_summary_new_csv": str(PLATES_NEW),
            "rank_summary_cumulative_csv": str(RANK_CUM),
        },
        "next_stage_if_complete": (
            "For active ranks still without recurrence at cumulative 256, "
            "expand the identical SHA256 ordering to prefix 1024 or move "
            "to discovery-plate/manual morphology adjudication if a stronger "
            "predeclared publication criterion is reached. Do not alter the "
            "3/5-arcsec gates or prior sample."
        ),
    }
    write_json(REPORT, report)

    print()
    print("=" * 98)
    print("ORDER 61 PLATEPHOT RECURRENCE STAGE 2 " + status)
    print("=" * 98)
    print(
        f"New calls selected/completed/failed: "
        f"{len(new_calls)}/{len(plates_new)}/{len(failures)}"
    )
    print()

    print(
        "strict #22: "
        f"{rank22['disposition']} | "
        f"Stage1 plates <=5\"={rank22['plates_with_source_within_5arcsec']} "
        f"<=3\"={rank22['plates_with_source_within_3arcsec']}"
    )

    for r in rank_rows:
        print(
            f"strict #{int(r['strict_rank']):02d}: cumulative="
            f"{int(r['cumulative_completed_plates'])}/"
            f"{int(r['cumulative_selected_plates'])} "
            f"plates <=3\"={int(r['plates_with_source_within_3arcsec'])} "
            f"<=5\"={int(r['plates_with_source_within_5arcsec'])} "
            f"| expected chance <=3\"≈"
            f"{float(r['expected_chance_within_3_from_local60']):.3f} "
            f"<=5\"≈{float(r['expected_chance_within_5_from_local60']):.3f} "
            f"| recurrent3={r['multi_independent_plate_recurrence_3arcsec']} "
            f"recurrent5={r['multi_independent_plate_recurrence_5arcsec']}"
        )

    print()
    print("Outputs:")
    print(" ", REPORT)
    print(" ", POLICY)
    print(" ", CUM_MANIFEST)
    print(" ", NEW_MANIFEST)
    print(" ", DETAIL_NEW)
    print(" ", PLATES_NEW)
    print(" ", RANK_CUM)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted.")


if __name__ == "__main__":
    main()
