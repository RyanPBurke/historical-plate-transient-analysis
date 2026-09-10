#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin
import argparse
import csv
import io
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from v095a_runtime_rc4 import ProjectLock, BoundedHTTP

CONTRACT_SHA = "597322e7c10413fc34d4eca39bef013c026a5483633266efd8e74b6100e7e5c3"
SQL_SHA = "1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21"
BINS_SHA = "c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313"

V094Z_COMMIT = "97005975e356fdef17022d000fb593006f9e6c3e"
V094Y_RESULTS_COMMIT = "2d30c9f780d2f2c9d572f81843af9d1c141444ad"
V094Y_PROOF_SHA = "1d6cdfe596711dad561ad67892536d2d4a6b779c6b57416afe2e3b95be65b84e"
V094Y_PROVENANCE_SHA = "fac0993e225b3a35e325cdda78aaa8e25437384f2db1bce026cb3564baaf44db"

V094Z_PAIR_SHA = "a34fd25fe7539e2e04e022d86c9866403a340c0c4b7ba6a1b9a7e154a07b1462"
V094Z_FRAG_SHA = "8c70f9452f022748d350ac73724afc871c4475978f66d0779a35f0957ba28e93"
V094Z_SUMMARY_SHA = "bcd28db6a7fb26c4581299a459661165c558a1c7cd1d8e10d72e1bf6f95f8522"

EXPECTED_PAIRS = 2655
EXPECTED_FRAGMENTS = 2683
EXPECTED_PLATES = 2440
EXPECTED_PRE_PAIRS = 1223
EXPECTED_PRE_FRAGMENTS = 1237
SPUTNIK = datetime(1957, 10, 4, 19, 28, 34, tzinfo=timezone.utc)

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "v095a_stageA_contract_rc4.json"
SQL_FILE = HERE / "v095a_stageA_queries_rc4.sql"
BINS_FILE = HERE / "v095a_stageA_bins_rc4.json"
RELEASE_MANIFEST = HERE / "release_manifest.sha256"

Q0_BATCH = 1000
Q1_BATCH = 250
Q2_BATCH = 500

TAP_BASE = "https://www.plate-archive.org/tap"
TAP_ASYNC = TAP_BASE.rstrip("/") + "/async"
TAP_LANG = "postgresql-9.6"
TAP_QUEUE = "1h"
HTTP_TIMEOUT = (15, 120)
ATTEMPT_DEADLINE_S = 3900.0
RETRY_DELAYS = (30, 120)
TERMINAL_PHASES = {"COMPLETED", "ERROR", "ABORTED"}

Q0_FIELDS = [
    "key_id", "solution_id", "expected_plate_id", "expected_scan_id",
    "returned_plate_id", "returned_scan_id", "process_id", "solution_num",
    "solutionset_id", "solution_row_found",
]
Q1_FIELDS = [
    "key_id", "plate_id", "scan_id", "process_id", "solution_num", "source_rows",
    "gaia_null", "gaia_lt0", "gaia_eq0", "gaia_gt0",
    "sexflag_null", "sexflag_lt0", "sexflag_eq0", "sexflag_gt0",
    "mp_null", "mp_lt0", "mp_0_010", "mp_010_050", "mp_050_090", "mp_090_099", "mp_099_100", "mp_gt1",
    "raerr_null", "raerr_lt0", "raerr_eq0", "raerr_0_025", "raerr_025_050", "raerr_050_100", "raerr_100_200", "raerr_200_500", "raerr_500_1000", "raerr_gt1000",
    "decerr_null", "decerr_lt0", "decerr_eq0", "decerr_0_025", "decerr_025_050", "decerr_050_100", "decerr_100_200", "decerr_200_500", "decerr_500_1000", "decerr_gt1000",
    "coord_both_null", "coord_ra_null_only", "coord_dec_null_only", "coord_valid_icrs_bounds", "coord_out_of_bounds",
    "annular_null", "annular_1", "annular_2", "annular_3", "annular_4", "annular_5", "annular_6", "annular_7", "annular_8", "annular_9", "annular_other",
]
Q2_FIELDS = [
    "plate_id", "all_processing_source_rows", "distinct_scans", "distinct_processes",
    "distinct_process_solution_nums", "distinct_scan_process_solution_nums",
]

Q1_GROUPS = {
    "gaia": ["gaia_null", "gaia_lt0", "gaia_eq0", "gaia_gt0"],
    "sexflag": ["sexflag_null", "sexflag_lt0", "sexflag_eq0", "sexflag_gt0"],
    "model_prediction": ["mp_null", "mp_lt0", "mp_0_010", "mp_010_050", "mp_050_090", "mp_090_099", "mp_099_100", "mp_gt1"],
    "ra_error": ["raerr_null", "raerr_lt0", "raerr_eq0", "raerr_0_025", "raerr_025_050", "raerr_050_100", "raerr_100_200", "raerr_200_500", "raerr_500_1000", "raerr_gt1000"],
    "dec_error": ["decerr_null", "decerr_lt0", "decerr_eq0", "decerr_0_025", "decerr_025_050", "decerr_050_100", "decerr_100_200", "decerr_200_500", "decerr_500_1000", "decerr_gt1000"],
    "coordinates": ["coord_both_null", "coord_ra_null_only", "coord_dec_null_only", "coord_valid_icrs_bounds", "coord_out_of_bounds"],
    "annular": ["annular_null", "annular_1", "annular_2", "annular_3", "annular_4", "annular_5", "annular_6", "annular_7", "annular_8", "annular_9", "annular_other"],
}

V094Z_REL = Path("pipeline_v0.2.0/research/prospective_freezes/v094z_source_blind_matcher_population_rc1")
RELEASE_REL = Path("pipeline_v0.2.0/research/prospective_freezes/v095a_stageA_aggregate_inventory_rc4")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def atomic_json(path: Path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def parse_int(v, field="value"):
    s = str(v if v is not None else "")
    if any(c in s for c in ('\r', '\n', '\x00')):
        raise ValueError(f"RESULT_PARSE_HOLD: invalid integer encoding in {field}")
    s = s.strip()
    if s == "":
        raise ValueError(f"missing integer {field}")
    if s.startswith("+"):
        s = s[1:]
    if not s or any(c not in "-0123456789" for c in s) or s.count("-") > 1 or ("-" in s and not s.startswith("-")):
        raise ValueError(f"RESULT_PARSE_HOLD: non-integer {field}")
    return int(s)


def run_git(repo: Path, *args, check=True):
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and cp.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {cp.stderr.strip()}")
    return cp


def verify_release_manifest():
    if sha(CONTRACT) != CONTRACT_SHA:
        raise SystemExit("RELEASE_HOLD: contract SHA mismatch")
    if sha(SQL_FILE) != SQL_SHA:
        raise SystemExit("RELEASE_HOLD: SQL SHA mismatch")
    if sha(BINS_FILE) != BINS_SHA:
        raise SystemExit("RELEASE_HOLD: bins SHA mismatch")
    if not RELEASE_MANIFEST.is_file():
        raise SystemExit("RELEASE_HOLD: missing release_manifest.sha256")
    entries = {}
    for line in RELEASE_MANIFEST.read_text(encoding="utf-8-sig").splitlines():
        q = line.strip().split(None, 1)
        if len(q) != 2:
            raise SystemExit("RELEASE_HOLD: malformed manifest line")
        digest, name = q[0].lower(), q[1].strip()
        if name in entries or Path(name).name != name or len(digest) != 64:
            raise SystemExit("RELEASE_HOLD: duplicate or invalid manifest entry")
        p = HERE / name
        if not p.is_file() or sha(p) != digest:
            raise SystemExit(f"RELEASE_HOLD: manifest mismatch {name}")
        entries[name] = digest
    required = {
        "v095a_source_matcher_design_rc4.md", "v095a_stageA_contract_rc4.json",
        "v095a_stageA_queries_rc4.sql", "v095a_stageA_bins_rc4.json",
        "run_v095a_stageA_inventory_rc4.py", "create_v095a_stageA_rc4_freeze_evidence.ps1",
        "run_v095a_stageA_rc4_selftest.ps1", "run_v095a_stageA_rc4_preflight.ps1",
        "run_v095a_stageA_rc4_production.ps1", ".gitattributes",
        "v095a_runtime_rc4.py", "v095a_jobs_rc4.py", "test_v095a_rc4.py",
        "test_sql_rc4.mjs", "package.json", "package-lock.json",
    }
    miss = required - set(entries)
    if miss:
        raise SystemExit(f"RELEASE_HOLD: manifest lacks {sorted(miss)}")
    return entries


def extract_template(family: str) -> str:
    text = SQL_FILE.read_text(encoding="utf-8-sig")
    a = f"-- BEGIN {family}"
    b = f"-- END {family}"
    if text.count(a) != 1 or text.count(b) != 1:
        raise SystemExit(f"QUERY_HASH_HOLD: query markers {family}")
    body = text.split(a, 1)[1].split(b, 1)[0].strip() + "\n"
    return body


def materialize(template: str, placeholder: str, rows) -> bytes:
    if template.count(placeholder) != 1:
        raise SystemExit(f"QUERY_HASH_HOLD: placeholder count {placeholder}")
    vals = []
    for row in rows:
        if any(type(x) is not int for x in row):
            raise SystemExit("QUERY_HASH_HOLD: VALUES require exact integers")
        vals.append("    (" + ", ".join(str(int(x)) for x in row) + ")")
    if not vals:
        raise SystemExit("QUERY_HASH_HOLD: empty VALUES batch")
    q = template.replace(placeholder, ",\n".join(vals))
    return q.encode("utf-8")


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def poll_interval(elapsed: float) -> int:
    if elapsed < 60:
        return 5
    if elapsed < 600:
        return 15
    return 30


def validate_header(header, expected, family):
    if list(header) != list(expected):
        raise ValueError(f"RESULT_SCHEMA_HOLD {family}: unexpected columns or order")


def parse_csv_bytes(data: bytes, expected_fields, family):
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        header = reader.fieldnames or []
        rows = list(reader)
    except Exception as e:
        raise ValueError(f"RESULT_PARSE_HOLD {family}: {e}")
    validate_header(header, expected_fields, family)
    if any(None in r or any(v is None or any(c in v for c in ('\r', '\n', '\x00'))
                           for v in r.values()) for r in rows):
        raise ValueError(f"RESULT_PARSE_HOLD {family}: malformed row")
    return rows


def validate_q0(rows, expected_map):
    if len(rows) != len(expected_map):
        raise ValueError(f"MISSING_SOLUTION_BINDING_HOLD: rows={len(rows)} expected={len(expected_map)}")
    seen = set()
    out = []
    for r in rows:
        kid = parse_int(r["key_id"], "key_id")
        if kid in seen or kid not in expected_map:
            raise ValueError(f"MISSING_SOLUTION_BINDING_HOLD: unexpected/duplicate key {kid}")
        seen.add(kid)
        exp = expected_map[kid]
        got = (
            parse_int(r["solution_id"], "solution_id"),
            parse_int(r["expected_plate_id"], "expected_plate_id"),
            parse_int(r["expected_scan_id"], "expected_scan_id"),
        )
        if got != exp:
            raise ValueError(f"MISSING_SOLUTION_BINDING_HOLD: requested tuple mismatch key {kid}")
        if parse_int(r["solution_row_found"], "solution_row_found") != 1:
            raise ValueError(f"MISSING_SOLUTION_BINDING_HOLD: solution not found key {kid}")
        rp = parse_int(r["returned_plate_id"], "returned_plate_id")
        rs = parse_int(r["returned_scan_id"], "returned_scan_id")
        if (rp, rs) != (exp[1], exp[2]):
            raise ValueError(f"MISSING_SOLUTION_BINDING_HOLD: plate/scan mismatch key {kid}")
        proc = parse_int(r["process_id"], "process_id")
        soln = parse_int(r["solution_num"], "solution_num")
        ss = str(r.get("solutionset_id", "")).strip()
        solutionset = None if ss == "" else parse_int(ss, "solutionset_id")
        out.append({
            "key_id": kid, "solution_id": exp[0], "plate_id": rp, "scan_id": rs,
            "process_id": proc, "solution_num": soln, "solutionset_id": solutionset,
        })
    if seen != set(expected_map):
        raise ValueError("MISSING_SOLUTION_BINDING_HOLD: key set mismatch")
    science = Counter((x["plate_id"], x["scan_id"], x["process_id"], x["solution_num"]) for x in out)
    collisions = [k for k, n in science.items() if n > 1]
    if collisions:
        raise ValueError(f"MISSING_SOLUTION_BINDING_HOLD: science-key collision count={len(collisions)}")
    return sorted(out, key=lambda x: x["key_id"])


def validate_q1(rows, expected_map):
    if len(rows) != len(expected_map):
        raise ValueError(f"SELECTED_KEY_RESULT_MISSING_HOLD: rows={len(rows)} expected={len(expected_map)}")
    seen = set()
    out = []
    for r in rows:
        kid = parse_int(r["key_id"], "key_id")
        if kid in seen or kid not in expected_map:
            raise ValueError(f"SELECTED_KEY_RESULT_MISSING_HOLD: unexpected/duplicate key {kid}")
        seen.add(kid)
        exp = expected_map[kid]
        got = tuple(parse_int(r[x], x) for x in ("plate_id", "scan_id", "process_id", "solution_num"))
        if got != exp:
            raise ValueError(f"SELECTED_KEY_RESULT_MISSING_HOLD: science key mismatch {kid}")
        rr = {k: parse_int(r[k], k) if k not in {"key_id"} else kid for k in Q1_FIELDS}
        total = rr["source_rows"]
        if total < 0:
            raise ValueError(f"AGGREGATE_COMPLETENESS_HOLD: negative source_rows key {kid}")
        for name, fields in Q1_GROUPS.items():
            if any(rr[f] < 0 for f in fields) or sum(rr[f] for f in fields) != total:
                raise ValueError(f"AGGREGATE_COMPLETENESS_HOLD: {name} sum key {kid}")
        out.append(rr)
    if seen != set(expected_map):
        raise ValueError("SELECTED_KEY_RESULT_MISSING_HOLD: key set mismatch")
    return sorted(out, key=lambda x: x["key_id"])


def validate_q2(rows, expected_plates):
    expected = set(expected_plates)
    if len(rows) != len(expected):
        raise ValueError(f"PHYSICAL_PLATE_RESULT_MISSING_HOLD: rows={len(rows)} expected={len(expected)}")
    seen = set()
    out = []
    for r in rows:
        pid = parse_int(r["plate_id"], "plate_id")
        if pid in seen or pid not in expected:
            raise ValueError(f"PHYSICAL_PLATE_RESULT_MISSING_HOLD: unexpected/duplicate plate {pid}")
        seen.add(pid)
        rr = {k: parse_int(r[k], k) for k in Q2_FIELDS}
        if any(rr[k] < 0 for k in Q2_FIELDS[1:]):
            raise ValueError(f"AGGREGATE_COMPLETENESS_HOLD: negative Q2 count plate {pid}")
        if rr["all_processing_source_rows"] == 0 and any(rr[k] != 0 for k in Q2_FIELDS[2:]):
            raise ValueError(f"AGGREGATE_COMPLETENESS_HOLD: empty-plate composite count nonzero plate {pid}")
        n = rr['all_processing_source_rows']
        scans, processes = rr['distinct_scans'], rr['distinct_processes']
        ps, sps = rr['distinct_process_solution_nums'], rr['distinct_scan_process_solution_nums']
        if not (scans <= sps <= n and processes <= ps <= sps):
            raise ValueError(f"AGGREGATE_COMPLETENESS_HOLD: impossible Q2 multiplicity plate {pid}")
        if n > 0 and (ps < 1 or sps < 1):
            raise ValueError(f"AGGREGATE_COMPLETENESS_HOLD: missing Q2 composite plate {pid}")
        out.append(rr)
    if seen != expected:
        raise ValueError("PHYSICAL_PLATE_RESULT_MISSING_HOLD: plate set mismatch")
    return sorted(out, key=lambda x: x["plate_id"])


def validate_cross_totals(q1, q2):
    totals = Counter()
    for row in q1:
        totals[row['plate_id']] += row['source_rows']
    available = {row['plate_id']: row['all_processing_source_rows'] for row in q2}
    for plate, total in totals.items():
        if plate not in available or total > available[plate]:
            raise ValueError(f'AGGREGATE_COMPLETENESS_HOLD: selected/all-processing mismatch plate {plate}')


def self_test():
    verify_release_manifest()
    import unittest
    import test_v095a_rc4
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_v095a_rc4)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit("SELFTEST_HOLD: regression failure")
    print("v095a Stage A RC4 SELF-TEST PASS")
    print("Python lifecycle/parser/lock regressions passed; PostgreSQL SQL suite is test_sql_rc4.mjs")
    print("catalogue/network calls: 0")


def manifest_check(manifest: Path, base: Path):
    seen = {}
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        q = line.strip().split(None, 1)
        if len(q) != 2:
            continue
        digest, name = q[0].lower(), q[1].strip()
        p = base / name
        if not p.is_file() or sha(p) != digest:
            raise SystemExit(f"PARENT_HOLD: manifest mismatch {name}")
        seen[name] = digest
    return seen


def foundation_provenance(project: Path, repo: Path):
    v094s = project / "research/prospective_freezes/v094s_source_free_opportunity_population_parent_provenance.json"
    if not v094s.is_file():
        raise SystemExit("PARENT_HOLD: missing v094s provenance")
    prov = read_json(v094s)
    solution = project / prov["inputs"]["solution_full"]["path"]
    files = {
        "v094x_science_runner": project / "tools/run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py",
        "geometry_execution_module": repo / "pipeline_v0.2.0/tools/run_applause_dr4_historical_geometry_validation_v094r3c.py",
        "v094t_csv": project / "results/applause_dr4_source_free_opportunity_population_repair_v094t/applause_dr4_source_free_cross_site_opportunities_v094t.csv",
        "v094t_report": project / "results/applause_dr4_source_free_opportunity_population_repair_v094t/applause_dr4_source_free_opportunity_population_repair_v094t.json",
        "v094t_manifest": project / "results/applause_dr4_source_free_opportunity_population_repair_v094t/v094t_output_manifest.sha256",
        "v094w_site": project / "results/applause_dr4_v094w_full_site_reference_coverage_replay/v094w_site_foundation.csv",
        "v094w_report": project / "results/applause_dr4_v094w_full_site_reference_coverage_replay/v094w_full_site_reference_coverage_replay.json",
        "v094w_manifest": project / "results/applause_dr4_v094w_full_site_reference_coverage_replay/v094w_output_manifest.sha256",
        "v094s_provenance": v094s,
        "solution_full": solution,
        "c01": repo / "pipeline_v0.2.0/research/prospective_freezes/v094r3b_historical_geometry_validation/inputs/acquisition/references/EOP_C01_IAU2000_1846-now.txt",
        "historic_deltat": repo / "pipeline_v0.2.0/research/prospective_freezes/v094r3b_historical_geometry_validation/inputs/acquisition/references/historic_deltat.data",
        "monthly_deltat": repo / "pipeline_v0.2.0/research/prospective_freezes/v094v_site_reference_acquisition/deltat.data",
    }
    for name, p in files.items():
        if not p.is_file():
            raise SystemExit(f"PARENT_HOLD: missing foundation file {name}: {p}")
    q = {k: {"path": str(v), "sha256": sha(v)} for k, v in files.items()}
    digest = canonical_sha(q)
    if digest != V094Y_PROVENANCE_SHA:
        raise SystemExit(f"PARENT_HOLD: v094y foundation provenance digest {digest}")
    manifest_check(files["v094t_manifest"], files["v094t_manifest"].parent)
    manifest_check(files["v094w_manifest"], files["v094w_manifest"].parent)
    return q, files


def verify_v094z(repo: Path):
    cp = run_git(repo, "cat-file", "-e", V094Z_COMMIT + "^{commit}", check=False)
    if cp.returncode:
        raise SystemExit("PARENT_HOLD: v094z freeze commit unavailable")
    cp = run_git(repo, "merge-base", "--is-ancestor", V094Z_COMMIT, "HEAD", check=False)
    if cp.returncode:
        raise SystemExit("PARENT_HOLD: v094z freeze is not ancestor of HEAD")
    base = repo / V094Z_REL
    p_pair = base / "v094z_matcher_pairs.csv"
    p_frag = base / "v094z_matcher_fragments.csv"
    p_sum = base / "v094z_matcher_population.json"
    for p, digest in ((p_pair, V094Z_PAIR_SHA), (p_frag, V094Z_FRAG_SHA), (p_sum, V094Z_SUMMARY_SHA)):
        if not p.is_file() or sha(p) != digest:
            raise SystemExit(f"PARENT_HOLD: v094z byte mismatch {p.name}")
    pairs = read_csv(p_pair); frags = read_csv(p_frag); summary = read_json(p_sum)
    if len(pairs) != EXPECTED_PAIRS or len(frags) != EXPECTED_FRAGMENTS:
        raise SystemExit("PARENT_HOLD: v094z population count mismatch")
    if summary.get("status") != "COMPLETE" or int(summary.get("population_pairs", -1)) != EXPECTED_PAIRS or int(summary.get("population_fragments", -1)) != EXPECTED_FRAGMENTS:
        raise SystemExit("PARENT_HOLD: v094z summary mismatch")
    plates = {parse_int(r["plate_a"], "plate_a") for r in pairs} | {parse_int(r["plate_b"], "plate_b") for r in pairs}
    if len(plates) != EXPECTED_PLATES:
        raise SystemExit(f"PARENT_HOLD: unique v094z plates {len(plates)}")
    pre_frags = [r for r in frags if datetime.fromisoformat(r["end_utc"].replace("Z", "+00:00")).astimezone(timezone.utc) <= SPUTNIK]
    pre_pairs = {r["pair_id"] for r in pre_frags}
    straddle = [r for r in frags if datetime.fromisoformat(r["start_utc"].replace("Z", "+00:00")).astimezone(timezone.utc) < SPUTNIK < datetime.fromisoformat(r["end_utc"].replace("Z", "+00:00")).astimezone(timezone.utc)]
    if len(pre_frags) != EXPECTED_PRE_FRAGMENTS or len(pre_pairs) != EXPECTED_PRE_PAIRS or straddle:
        raise SystemExit(f"PARENT_HOLD: pre-Sputnik replay {len(pre_pairs)} pairs/{len(pre_frags)} fragments/straddle={len(straddle)}")
    return pairs, frags, sorted(plates)


def build_parent_associations(pairs, v094t_csv: Path):
    parent = read_csv(v094t_csv)
    by = {}
    for r in parent:
        pid = str(r.get("pair_id", "")).strip()
        if pid in by:
            raise SystemExit(f"PARENT_HOLD: duplicate v094t pair_id {pid}")
        by[pid] = r
    out = []
    for p in pairs:
        pid = str(p["pair_id"]).strip()
        if pid not in by:
            raise SystemExit(f"PARENT_HOLD: v094z pair absent from v094t {pid}")
        r = by[pid]
        ea, eb = parse_int(r["exposure_a"], "exposure_a"), parse_int(r["exposure_b"], "exposure_b")
        if pid != f"{ea}|{eb}":
            raise SystemExit(f"PARENT_HOLD: pair/exposure identity mismatch {pid}")
        for side in ("a", "b"):
            plate = parse_int(r[f"plate_{side}"], f"plate_{side}")
            if plate != parse_int(p[f"plate_{side}"], f"v094z plate_{side}"):
                raise SystemExit(f"PARENT_HOLD: pair-side plate mismatch {pid}/{side}")
            out.append({
                "pair_id": pid,
                "side": side.upper(),
                "exposure_id": parse_int(r[f"exposure_{side}"], f"exposure_{side}"),
                "plate_id": plate,
                "scan_id": parse_int(r[f"scan_id_{side}"], f"scan_id_{side}"),
                "solution_id": parse_int(r[f"solution_id_{side}"], f"solution_id_{side}"),
            })
    if len(out) != EXPECTED_PAIRS * 2:
        raise SystemExit("PARENT_HOLD: pair-side association count")
    triples = {}
    for r in out:
        sid = r["solution_id"]
        tup = (sid, r["plate_id"], r["scan_id"])
        if sid in triples and triples[sid] != tup:
            raise SystemExit(f"PARENT_HOLD: conflicting frozen solution association {sid}")
        triples[sid] = tup
    wanted = []
    for kid, tup in enumerate(sorted(triples.values()), 1):
        wanted.append((kid, tup[0], tup[1], tup[2]))
    return out, wanted


def preflight(project: Path, repo: Path, write_plan=True, owner=None):
    if write_plan and owner is None:
        with ProjectLock(project) as held:
            return preflight(project, repo, write_plan, owner=held)
    if write_plan:
        owner.require(project)
    verify_release_manifest()
    contract = read_json(CONTRACT)
    if contract.get("contract_id") != "v095a_stageA_aggregate_inventory_rc4":
        raise SystemExit("RELEASE_HOLD: contract id")
    proof = project / "research/proof_archives/v094y_rc4_proof_archive.zip"
    if not proof.is_file() or sha(proof) != V094Y_PROOF_SHA:
        raise SystemExit("PARENT_HOLD: v094y proof archive missing/hash mismatch")
    prov, files = foundation_provenance(project, repo)
    pairs, frags, plates = verify_v094z(repo)
    associations, q0_wanted = build_parent_associations(pairs, files["v094t_csv"])

    plan = {
        "status": "PREFLIGHT_PASS_NO_CATALOGUE_CALLS",
        "created_utc": utcnow(),
        "pairs": len(pairs), "fragments": len(frags), "physical_plates": len(plates),
        "pair_side_associations": len(associations), "unique_selected_solutions": len(q0_wanted),
        "pre_sputnik_pairs": EXPECTED_PRE_PAIRS, "pre_sputnik_fragments": EXPECTED_PRE_FRAGMENTS,
        "v094y_foundation_input_provenance_sha256": V094Y_PROVENANCE_SHA,
        "v094y_proof_archive_sha256": V094Y_PROOF_SHA,
        "v094z_exact_byte_freeze_commit": V094Z_COMMIT,
        "planned_batch_sizes": {"q0": Q0_BATCH, "q1": Q1_BATCH, "q2": Q2_BATCH},
        "planned_q0_batches": (len(q0_wanted) + Q0_BATCH - 1) // Q0_BATCH,
        "planned_q2_batches": (len(plates) + Q2_BATCH - 1) // Q2_BATCH,
        "q1_batches_known_after_q0": True,
        "catalogue_calls": 0, "individual_source_calls": 0,
    }
    if write_plan:
        work = project / "work/v095a_stageA_aggregate_inventory_rc4"
        plan_dir = work / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        write_csv(plan_dir / "v095a_parent_pair_side_associations.csv",
                  ["pair_id", "side", "exposure_id", "plate_id", "scan_id", "solution_id"], associations)
        write_csv(plan_dir / "v095a_q0_selected_solution_requests.csv",
                  ["key_id", "solution_id", "expected_plate_id", "expected_scan_id"],
                  [{"key_id":x[0],"solution_id":x[1],"expected_plate_id":x[2],"expected_scan_id":x[3]} for x in q0_wanted])
        plan['parent_associations_sha256'] = sha(plan_dir / 'v095a_parent_pair_side_associations.csv')
        plan['q0_request_rows_sha256'] = sha(plan_dir / 'v095a_q0_selected_solution_requests.csv')
        atomic_json(plan_dir / "v095a_preflight.json", plan)
    return plan, associations, q0_wanted, plates


def verify_freeze(repo: Path, freeze_commit: str, evidence: Path):
    if len(freeze_commit) != 40 or any(c not in "0123456789abcdefABCDEF" for c in freeze_commit):
        raise SystemExit("FREEZE_HOLD: freeze commit must be full 40-hex SHA")
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    if head.lower() != freeze_commit.lower():
        raise SystemExit(f"FREEZE_HOLD: HEAD {head} != freeze {freeze_commit}")
    dirty = run_git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        raise SystemExit("FREEZE_HOLD: tracked worktree/index not clean")
    if run_git(repo, "merge-base", "--is-ancestor", V094Z_COMMIT, freeze_commit, check=False).returncode:
        raise SystemExit("FREEZE_HOLD: v094z freeze not ancestor")
    ev = read_json(evidence)
    if ev.get("status") != "REMOTE_FREEZE_VERIFIED" or str(ev.get("freeze_commit", "")).lower() != freeze_commit.lower() or str(ev.get("origin_main", "")).lower() != freeze_commit.lower():
        raise SystemExit("FREEZE_HOLD: freeze evidence content")
    if ev.get("release_manifest_sha256") != sha(RELEASE_MANIFEST):
        raise SystemExit("FREEZE_HOLD: release manifest evidence mismatch")
    # Direct remote verification is intentional provenance network traffic and is counted separately.
    remote = run_git(repo, "ls-remote", "origin", "refs/heads/main").stdout.strip().split()
    if not remote or remote[0].lower() != freeze_commit.lower():
        raise SystemExit("FREEZE_HOLD: origin/main mismatch")
    # Prove exact release bytes are Git blobs at the freeze commit.
    entries = verify_release_manifest()
    for name in entries:
        p = HERE / name
        raw = run_git(repo, "hash-object", "--no-filters", str(p)).stdout.strip()
        spec = f"{freeze_commit}:{(RELEASE_REL / name).as_posix()}"
        blob = run_git(repo, "rev-parse", spec).stdout.strip()
        if raw != blob:
            raise SystemExit(f"FREEZE_HOLD: Git blob byte mismatch {name}")
    return 1


def make_session(token_env="APPLAUSE_TOKEN"):
    try:
        import requests
    except ImportError:
        raise SystemExit('ENVIRONMENT_HOLD: requests must be installed before production')
    token = os.environ.get(token_env, "").strip()
    return BoundedHTTP(token), "TOKEN" if token else "ANONYMOUS"


def run_batch(session, family, batch_no, query_bytes, expected_fields, validator, expected_arg,
              work, counters, *, owner, context):
    from v095a_jobs_rc4 import run_batch as execute_batch
    return execute_batch(session, family, batch_no, query_bytes, expected_fields,
                         parse_csv_bytes, validator, expected_arg, work, counters,
                         owner=owner, context=context)


def copy_validated_jobs(work, staging, batch_counts):
    cumulative = Counter()
    for family, count in batch_counts.items():
        for number in range(1, count+1):
            source = work / 'jobs' / family / f'batch_{number:04d}'
            meta = read_json(source / 'meta.json')
            if meta['status'] != 'COMPLETED_VALIDATED':
                raise SystemExit('PUBLICATION_HOLD: incomplete checkpoint')
            target = staging / 'jobs' / family / source.name
            target.mkdir(parents=True)
            files = {'query.sql': meta['query_sha256'], 'result.csv': meta['result_sha256'],
                     'meta.json': sha(source / 'meta.json')}
            for attempt in meta['attempts']:
                for artifact in attempt.get('artifacts', []):
                    name = artifact['file']
                    if Path(name).name != name:
                        raise SystemExit('PUBLICATION_HOLD: unexpected artifact path')
                    files[name] = artifact['sha256']
            for name, expected in files.items():
                if sha(source / name) != expected:
                    raise SystemExit('PUBLICATION_HOLD: checkpoint changed during publication')
                shutil.copyfile(source / name, target / name)
                if sha(target / name) != expected:
                    raise SystemExit('PUBLICATION_HOLD: copied checkpoint hash')
            key = 'catalogue_tap_metadata_binding_calls' if family.startswith('Q0_') else 'catalogue_tap_aggregate_inventory_calls'
            cumulative[key] += meta['transport_request_attempts']
            cumulative['tap_job_submission_attempts'] += len(meta['attempts'])
    return dict(cumulative)


def run_production(project: Path, repo: Path, freeze_commit: str, freeze_evidence: Path, token_env: str):
    with ProjectLock(project) as owner:
        return _run_production_locked(project, repo, freeze_commit, freeze_evidence, token_env, owner)


def _run_production_locked(project, repo, freeze_commit, freeze_evidence, token_env, owner):
    owner.require(project)
    if (project / "results/applause_dr4_v095a_stageA_aggregate_inventory_rc4").exists():
        raise SystemExit("PUBLICATION_HOLD: final result directory already exists")
    counters = Counter({
        "git_provenance_network_calls": 0,
        "catalogue_tap_metadata_binding_calls": 0,
        "catalogue_tap_aggregate_inventory_calls": 0,
        "individual_source_catalogue_calls": 0,
        "pixel_or_scan_network_calls": 0,
    })
    counters["git_provenance_network_calls"] += verify_freeze(repo, freeze_commit, freeze_evidence)
    plan, associations, q0_wanted, plates = preflight(project, repo, write_plan=True, owner=owner)
    work = project / "work/v095a_stageA_aggregate_inventory_rc4"
    context = {
        'release_freeze_commit': freeze_commit.lower(), 'release_manifest_sha256': sha(RELEASE_MANIFEST),
        'contract_sha256': CONTRACT_SHA, 'sql_sha256': SQL_SHA, 'bins_sha256': BINS_SHA,
        'parent_pair_sha256': V094Z_PAIR_SHA, 'parent_fragment_sha256': V094Z_FRAG_SHA,
        'parent_summary_sha256': V094Z_SUMMARY_SHA, 'foundation_sha256': V094Y_PROVENANCE_SHA,
        'proof_archive_sha256': V094Y_PROOF_SHA,
    }
    atomic_json(work / 'execution_context.json', context)
    session, auth_mode = make_session(token_env)

    q0_template = extract_template("Q0_SELECTED_SOLUTION_BINDING")
    all_q0 = []
    for bn, batch in enumerate(chunks(q0_wanted, Q0_BATCH), 1):
        expected = {x[0]: (x[1], x[2], x[3]) for x in batch}
        q = materialize(q0_template, "/*__Q0_VALUES__*/", batch)
        rows = run_batch(session, "Q0_SELECTED_SOLUTION_BINDING", bn, q, Q0_FIELDS, validate_q0, expected, work, counters, owner=owner, context=context)
        all_q0.extend(rows)
    expected_q0 = {x[0]: (x[1], x[2], x[3]) for x in q0_wanted}
    bindings = validate_q0(all_q0, expected_q0)
    write_csv(work / "plan/v095a_selected_solution_keys.csv",
              ["key_id", "solution_id", "plate_id", "scan_id", "process_id", "solution_num", "solutionset_id"], bindings)

    science = []
    for kid, b in enumerate(sorted(bindings, key=lambda x: (x["plate_id"], x["scan_id"], x["process_id"], x["solution_num"])), 1):
        science.append((kid, b["plate_id"], b["scan_id"], b["process_id"], b["solution_num"]))
    science_map = {x[0]: (x[1], x[2], x[3], x[4]) for x in science}

    q1_template = extract_template("Q1_SELECTED_SCIENCE_KEY_AGGREGATES")
    all_q1 = []
    for bn, batch in enumerate(chunks(science, Q1_BATCH), 1):
        expected = {x[0]: (x[1], x[2], x[3], x[4]) for x in batch}
        q = materialize(q1_template, "/*__Q1_VALUES__*/", batch)
        rows = run_batch(session, "Q1_SELECTED_SCIENCE_KEY_AGGREGATES", bn, q, Q1_FIELDS, validate_q1, expected, work, counters, owner=owner, context=context)
        all_q1.extend(rows)
    q1 = validate_q1(all_q1, science_map)

    q2_template = extract_template("Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY")
    all_q2 = []
    plate_rows = [(p,) for p in plates]
    for bn, batch in enumerate(chunks(plate_rows, Q2_BATCH), 1):
        expected = [x[0] for x in batch]
        q = materialize(q2_template, "/*__Q2_VALUES__*/", batch)
        rows = run_batch(session, "Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY", bn, q, Q2_FIELDS, validate_q2, expected, work, counters, owner=owner, context=context)
        all_q2.extend(rows)
    q2 = validate_q2(all_q2, plates)
    validate_cross_totals(q1, q2)

    results = project / 'results'
    results.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='v095a_rc4_staging_', dir=results))
    final = project / "results/applause_dr4_v095a_stageA_aggregate_inventory_rc4"

    # Parent-association provenance is source-blind metadata, retained in final archive.
    write_csv(staging / "v095a_parent_pair_side_associations.csv",
              ["pair_id", "side", "exposure_id", "plate_id", "scan_id", "solution_id"], associations)
    write_csv(staging / "v095a_selected_solution_bindings.csv",
              ["key_id", "solution_id", "plate_id", "scan_id", "process_id", "solution_num", "solutionset_id"], bindings)
    write_csv(staging / "v095a_selected_key_inventory.csv", Q1_FIELDS, q1)
    write_csv(staging / "v095a_plate_processing_multiplicity.csv", Q2_FIELDS, q2)

    # Copy validated job audit metadata and query bytes, but no source-level records exist anywhere in this stage.
    batch_counts = {
        'Q0_SELECTED_SOLUTION_BINDING': (len(q0_wanted)+Q0_BATCH-1)//Q0_BATCH,
        'Q1_SELECTED_SCIENCE_KEY_AGGREGATES': (len(science)+Q1_BATCH-1)//Q1_BATCH,
        'Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY': (len(plates)+Q2_BATCH-1)//Q2_BATCH,
    }
    cumulative = copy_validated_jobs(work, staging, batch_counts)
    atomic_json(staging / 'execution_context.json', context)

    globalsums = {f: sum(r[f] for r in q1) for f in Q1_FIELDS[5:]}
    summary = {
        "analysis_kind": "v095a_stageA_aggregate_inventory_rc4",
        "status": "COMPLETE",
        "completed_utc": utcnow(),
        "release_freeze_commit": freeze_commit,
        "release_manifest_sha256": sha(RELEASE_MANIFEST),
        "parent_v094z_commit": V094Z_COMMIT,
        "v094y_foundation_input_provenance_sha256": V094Y_PROVENANCE_SHA,
        "v094y_proof_archive_sha256": V094Y_PROOF_SHA,
        "population_pairs": EXPECTED_PAIRS,
        "population_fragments": EXPECTED_FRAGMENTS,
        "physical_plates": EXPECTED_PLATES,
        "pair_side_associations": len(associations),
        "selected_solution_bindings": len(bindings),
        "selected_science_keys": len(q1),
        "selected_science_key_source_rows_total": sum(r["source_rows"] for r in q1),
        "selected_science_keys_zero_source_rows": sum(r["source_rows"] == 0 for r in q1),
        "physical_plate_all_processing_source_rows_total": sum(r["all_processing_source_rows"] for r in q2),
        "physical_plates_zero_source_rows": sum(r["all_processing_source_rows"] == 0 for r in q2),
        "selected_key_aggregate_global_sums": globalsums,
        "pre_sputnik_pairs": EXPECTED_PRE_PAIRS,
        "pre_sputnik_fragments": EXPECTED_PRE_FRAGMENTS,
        "retained_fragment_straddles_launch": 0,
        "tap_authentication_mode": auth_mode,
        "network_counters_this_invocation": dict(counters),
        "catalogue_request_attempts_cumulative": cumulative,
        "network_counter_semantics": "HTTP operation attempts, including failed transport; current invocation and retained checkpoints reported separately",
        "permissions": {
            "aggregate_only_candidate_identity_blind": True,
            "individual_source_extraction_allowed": False,
            "cross_observatory_source_pairing_allowed": False,
            "pixels_or_scans_allowed": False,
        },
        "next_stage": "Interpret inventory, then prospectively freeze uncertainty/chance-control contract before individual-source extraction.",
    }
    atomic_json(staging / "v095a_stageA_aggregate_inventory.json", summary)

    manifest_files = sorted(p for p in staging.rglob('*') if p.is_file())
    with (staging / "v095a_output_manifest.sha256").open("w", encoding="ascii", newline="\n") as stream:
        for path in manifest_files:
            stream.write(f"{sha(path)}  {path.relative_to(staging).as_posix()}\n")
        stream.flush(); os.fsync(stream.fileno())
    if final.exists():
        raise SystemExit('PUBLICATION_HOLD: final directory appeared; staging retained')
    os.replace(staging, final)
    print("v095a Stage A RC4 PRODUCTION PASS")
    print(f"pairs/fragments/plates={EXPECTED_PAIRS}/{EXPECTED_FRAGMENTS}/{EXPECTED_PLATES}")
    print(f"selected_solutions/science_keys={len(bindings)}/{len(q1)}")
    print(f"selected_source_rows={summary['selected_science_key_source_rows_total']} zero_keys={summary['selected_science_keys_zero_source_rows']}")
    print(f"tap_calls=q0:{counters['catalogue_tap_metadata_binding_calls']} aggregate:{counters['catalogue_tap_aggregate_inventory_calls']} individual:0 pixels:0")
    print("individual_source_extraction_allowed=false")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--production", action="store_true")
    ap.add_argument("--project-root")
    ap.add_argument("--repo-root")
    ap.add_argument("--freeze-commit")
    ap.add_argument("--freeze-evidence")
    ap.add_argument("--token-env", default="APPLAUSE_TOKEN")
    a = ap.parse_args()
    modes = sum(bool(x) for x in (a.self_test, a.preflight_only, a.production))
    if modes != 1:
        ap.error("choose exactly one of --self-test, --preflight-only, --production")
    if a.self_test:
        self_test(); return 0
    if not a.project_root or not a.repo_root:
        ap.error("--project-root and --repo-root required")
    project, repo = Path(a.project_root).resolve(), Path(a.repo_root).resolve()
    if a.preflight_only:
        self_test()
        p, _, q0, plates = preflight(project, repo, write_plan=True)
        print("v095a Stage A RC4 PREFLIGHT PASS")
        print(f"pairs/fragments/plates={p['pairs']}/{p['fragments']}/{p['physical_plates']}")
        print(f"pair_sides/selected_solutions={p['pair_side_associations']}/{p['unique_selected_solutions']}")
        print(f"pre_sputnik={p['pre_sputnik_pairs']} pairs/{p['pre_sputnik_fragments']} fragments")
        print("catalogue/network calls=0")
        return 0
    if not a.freeze_commit or not a.freeze_evidence:
        ap.error("production requires --freeze-commit and --freeze-evidence")
    return run_production(project, repo, a.freeze_commit, Path(a.freeze_evidence).resolve(), a.token_env)


if __name__ == "__main__":
    raise SystemExit(main())
