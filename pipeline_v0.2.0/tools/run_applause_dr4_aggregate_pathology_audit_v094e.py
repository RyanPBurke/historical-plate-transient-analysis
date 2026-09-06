#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import Counter, defaultdict
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import subprocess
import sys

import numpy as np
from scipy.spatial import cKDTree

CONTRACT_REL = Path("pipeline_v0.2.0/research/prospective_freezes/applause_dr4_aggregate_pathology_contract_v094e.json")
PROVENANCE_REL = Path("pipeline_v0.2.0/research/prospective_freezes/applause_dr4_aggregate_pathology_parent_provenance_v094e.json")
INVENTORY_REL = Path("pipeline_v0.2.0/research/prospective_freezes/applause_dr4_v094c_source_cache_inventory_v094e.csv")
RUNNER_REL = Path("pipeline_v0.2.0/tools/run_applause_dr4_aggregate_pathology_audit_v094e.py")

EXPECTED_V094C_CANDIDATE_SHA = "68f1e5f0a42a2c292371c930aad51ff8a5d7d2bd4d71e5026449b35928939d1d"
EXPECTED_V094C_RUNNER_SHA = "89bc8b0c4d93a9057a6aaec62495f974ef32762b2556a31a0d65fe79e2520492"
EXPECTED_ZERO = {109445, 114677, 114682, 114813, 115031, 115911, 116377, 116528, 117980}
EXPECTED_CANDIDATE_ROWS = 327883
EXPECTED_TRIPLETS = 784
EXPECTED_ZERO_HOLDS = 21
EXPECTED_MATCHABLE = 763
MATCH_CHUNK = 100000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def fnum(v):
    try:
        x = float(str(v if v is not None else "").strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x = fnum(v)
    if x is None:
        return None
    r = int(round(x))
    return r if abs(x - r) < 1e-9 else None


def bval(v):
    return str(v if v is not None else "").strip().lower() in {"1", "true", "yes"}


def ratio(a, b):
    return None if not b else float(a) / float(b)


def gini(values):
    a = np.asarray([float(x) for x in values if x is not None and x >= 0], dtype=float)
    if len(a) == 0 or a.sum() == 0:
        return 0.0
    a.sort()
    n = len(a)
    return float((2.0 * np.dot(np.arange(1, n + 1), a) / (n * a.sum())) - (n + 1.0) / n)


def concentration(counter: Counter):
    vals = sorted((int(v) for v in counter.values()), reverse=True)
    total = sum(vals)
    if not vals:
        return {"groups": 0, "nonzero_groups": 0, "total_rows": 0, "gini": 0.0, "hhi": 0.0}
    shares = [v / total for v in vals] if total else [0.0 for _ in vals]
    def topn(n):
        return sum(vals[:min(n, len(vals))]) / total if total else 0.0
    return {
        "groups": len(vals),
        "nonzero_groups": sum(v > 0 for v in vals),
        "total_rows": total,
        "max_group_rows": vals[0],
        "median_group_rows": float(np.median(vals)),
        "gini": gini(vals),
        "hhi": float(sum(s * s for s in shares)),
        "top1_group_share": topn(1),
        "top5_group_share": topn(5),
        "top10_group_share": topn(10),
        "top1pct_groups_share": topn(max(1, math.ceil(len(vals) * 0.01))),
        "top5pct_groups_share": topn(max(1, math.ceil(len(vals) * 0.05))),
        "top10pct_groups_share": topn(max(1, math.ceil(len(vals) * 0.10))),
    }


def multiplicity_summary(counter: Counter):
    hist = Counter(counter.values())
    total_rows = sum(k * n for k, n in hist.items())
    reused_rows = sum(k * n for k, n in hist.items() if k > 1)
    return {
        "unique_signatures": len(counter),
        "total_rows": total_rows,
        "signatures_used_more_than_once": sum(n for k, n in hist.items() if k > 1),
        "rows_in_reused_signatures": reused_rows,
        "fraction_rows_in_reused_signatures": ratio(reused_rows, total_rows),
        "max_multiplicity": max(hist) if hist else 0,
        "multiplicity_histogram": {str(k): hist[k] for k in sorted(hist)},
    }


def sep_hist(values, edges):
    counts = [0] * (len(edges) - 1)
    above = 0
    below = 0
    for x in values:
        if x < edges[0]:
            below += 1
        elif x > edges[-1]:
            above += 1
        else:
            placed = False
            for i in range(len(edges) - 1):
                lo, hi = edges[i], edges[i + 1]
                if (x >= lo) and (x <= hi if i == len(edges) - 2 else x < hi):
                    counts[i] += 1
                    placed = True
                    break
            if not placed:
                above += 1
    return {
        "edges": edges,
        "counts": counts,
        "below": below,
        "above": above,
    }


def git(args, cwd: Path, check=True):
    p = subprocess.run(["git", "-C", str(cwd), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p


def verify_frozen_git(repo: Path, freeze_commit: str):
    git(["cat-file", "-e", f"{freeze_commit}^{{commit}}"], repo)
    for rel in (CONTRACT_REL, PROVENANCE_REL, INVENTORY_REL, RUNNER_REL):
        git(["cat-file", "-e", f"{freeze_commit}:{rel.as_posix()}"], repo)
        p = git(["diff", "--quiet", freeze_commit, "--", rel.as_posix()], repo, check=False)
        if p.returncode != 0:
            raise RuntimeError(f"Frozen v094e file differs from commit {freeze_commit}: {rel}")


def load_v094c_module(project: Path):
    runner = project / "tools" / "run_applause_dr4_tierA_busko_source_census_v094c.py"
    if sha256(runner) != EXPECTED_V094C_RUNNER_SHA:
        raise RuntimeError("Operational v094c runner hash mismatch")
    spec = importlib.util.spec_from_file_location("frozen_v094c", runner)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load frozen v094c runner")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reconstruct_triplets(mod):
    opp = {r["canonical_pair"]: r for r in mod.rows(mod.OPP)}
    controls = []
    for c in mod.rows(mod.COMP):
        if c.get("tier") != "A_LE30MIN":
            continue
        if not mod.bval(c.get("primary_common_coverage_ge50pct")):
            continue
        if not mod.bval(c.get("same_site_control")):
            continue
        o = opp.get(c["canonical_pair"])
        if o is None:
            continue
        sep = mod.fnum(o.get("corrected_site_separation_km"))
        if sep is None or sep < mod.MIN_SITE_KM:
            continue
        ep = c.get("comparison_for_endpoint")
        if ep == "A":
            pp, qp = mod.inum(o.get("plate_a")), mod.inum(o.get("plate_b"))
            pe, qe = mod.inum(o.get("exposure_a")), mod.inum(o.get("exposure_b"))
            pn, qn = mod.inum(o.get("plate_numexp_a")), mod.inum(o.get("plate_numexp_b"))
        elif ep == "B":
            pp, qp = mod.inum(o.get("plate_b")), mod.inum(o.get("plate_a"))
            pe, qe = mod.inum(o.get("exposure_b")), mod.inum(o.get("exposure_a"))
            pn, qn = mod.inum(o.get("plate_numexp_b")), mod.inum(o.get("plate_numexp_a"))
        else:
            continue
        cp, ce, cn = mod.inum(c.get("comparison_plate_id")), mod.inum(c.get("comparison_exposure_id")), mod.inum(c.get("comparison_plate_numexp"))
        if None in (pp, qp, cp, pe, qe, ce) or not (pn == 1 and qn == 1 and cn == 1):
            continue
        controls.append({
            "canonical_pair": c["canonical_pair"], "endpoint": ep,
            "positive_plate": pp, "independent_plate": qp, "control_plate": cp,
            "positive_exposure": pe, "independent_exposure": qe, "control_exposure": ce,
            "gap_minutes": mod.fnum(c.get("endpoint_interval_gap_minutes")),
            "temporal_relation": c.get("temporal_relation"), "site_separation_km": sep,
            "science_overlap_start_utc": o.get("physical_overlap_start_utc"),
            "science_overlap_end_utc": o.get("physical_overlap_end_utc"),
        })
    unique = {}
    for r in controls:
        k = (r["positive_plate"], r["independent_plate"], r["control_plate"])
        if k not in unique or ((r["gap_minutes"] or 1e99) < (unique[k]["gap_minutes"] or 1e99)):
            unique[k] = r
    triplets = list(unique.values())

    st = mod.load_table_any(mod.SCAN_CACHE)
    plate_scans = defaultdict(list)
    for r in st:
        try:
            plate_scans[int(r["plate_id"])].append(int(r["scan_id"]))
        except Exception:
            pass
    for pid in list(plate_scans):
        plate_scans[pid] = sorted(set(plate_scans[pid]))

    solt = mod.load_table_any(mod.SOLUTION_CACHE)
    scan_polys = defaultdict(list)
    for r in solt:
        try:
            sid = int(r["scan_id"])
        except Exception:
            continue
        poly = mod.parse_stc(r["stc_polygon"])
        if poly:
            scan_polys[sid].append(poly)

    eligible = []
    for r in triplets:
        ps = [s for s in plate_scans.get(r["positive_plate"], []) if scan_polys.get(s)]
        qs = [s for s in plate_scans.get(r["independent_plate"], []) if scan_polys.get(s)]
        cs = [s for s in plate_scans.get(r["control_plate"], []) if scan_polys.get(s)]
        if min(len(ps), len(qs), len(cs)) < 1:
            continue
        x = dict(r)
        x.update({"positive_scan_ids": ps, "independent_scan_ids": qs, "control_scan_ids": cs})
        eligible.append(x)
    if len(eligible) != EXPECTED_TRIPLETS:
        raise RuntimeError(f"Triplet reconstruction mismatch: {len(eligible)} != {EXPECTED_TRIPLETS}")

    matchable_ord = 0
    zero_count = 0
    for ti, r in enumerate(eligible, 1):
        all_scans = set(r["positive_scan_ids"]) | set(r["independent_scan_ids"]) | set(r["control_scan_ids"])
        zero = sorted(all_scans & EXPECTED_ZERO)
        r["triplet_index"] = ti
        r["zero_source_scan_ids"] = zero
        r["zero_source_hold"] = bool(zero)
        if zero:
            zero_count += 1
            r["matchable_ordinal"] = None
        else:
            matchable_ord += 1
            r["matchable_ordinal"] = matchable_ord
    if zero_count != EXPECTED_ZERO_HOLDS or matchable_ord != EXPECTED_MATCHABLE:
        raise RuntimeError(f"Zero/matchable reconstruction mismatch: zero={zero_count}, matchable={matchable_ord}")
    return eligible, scan_polys


def load_timing_map(path: Path):
    out = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            ti = inum(r.get("legacy_triplet_index"))
            if ti is None:
                raise RuntimeError("v094d legacy timing row missing legacy_triplet_index")
            def multi(field):
                n = inum(r.get(field))
                return n is not None and n > 1
            out[ti] = {
                "timing_impact_class": r.get("timing_impact_class"),
                "positive_exposure": inum(r.get("positive_exposure")),
                "independent_exposure": inum(r.get("independent_exposure")),
                "control_exposure": inum(r.get("control_exposure")),
                "any_num_sub_gt1": any(multi(x) for x in ("positive_num_sub_raw", "independent_num_sub_raw", "control_num_sub_raw")),
                "science_num_sub_gt1": any(multi(x) for x in ("positive_num_sub_raw", "independent_num_sub_raw")),
            }
    if len(out) != EXPECTED_TRIPLETS:
        raise RuntimeError(f"v094d timing map has {len(out)} rows, expected 784")
    return out


def verify_source_inventory(project: Path, inventory_path: Path, expected_sha: str):
    if sha256(inventory_path) != expected_sha:
        raise RuntimeError("Frozen source-cache inventory hash mismatch")
    rows = []
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            sid = inum(r.get("scan_id"))
            rel = r.get("relative_path")
            if sid is None or not rel:
                raise RuntimeError("Malformed source-cache inventory")
            p = project / rel
            if not p.is_file():
                raise FileNotFoundError(p)
            actual = sha256(p)
            if actual != r.get("sha256"):
                raise RuntimeError(f"Source cache changed after freeze: scan {sid}")
            rows.append(sid)
            if len(rows) % 100 == 0:
                print(f"source-cache verification: {len(rows)}/1073", flush=True)
    if len(rows) != 1073 or len(set(rows)) != 1073:
        raise RuntimeError("Source-cache inventory does not contain exactly 1073 unique scans")


def stream_candidate_aggregates(path: Path, timing_map, triplets_by_index):
    by_triplet = Counter()
    by_pair = Counter()
    by_pp = Counter(); by_qp = Counter(); by_cp = Counter()
    support = Counter(); epoch = Counter(); timing = Counter(); multisub = Counter(); coverage_triplet = Counter()
    positive_sig = Counter(); independent_sig = Counter(); pair_sig = Counter(); exact_coord = Counter()
    ras = []; decs = []; indep_sep = []; control_sep = []
    sky = Counter(); disposition = Counter(); classes = Counter()
    invalid = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        for n, r in enumerate(rdr, 1):
            ti = inum(r.get("triplet_index")); ra = fnum(r.get("candidate_ra_icrs")); dec = fnum(r.get("candidate_dec_icrs"))
            if ti is None or ti not in triplets_by_index or ra is None or dec is None or not (0 <= ra < 360) or not (-90 <= dec <= 90):
                invalid += 1
                continue
            tr = triplets_by_index[ti]
            # Identity consistency check only; no candidate-level output.
            if any(inum(r.get(k)) != tr[k] for k in ("positive_plate", "independent_plate", "control_plate", "positive_exposure", "independent_exposure", "control_exposure")):
                raise RuntimeError(f"Candidate CSV triplet identity mismatch at row {n}")
            tm = timing_map[ti]
            if tm["positive_exposure"] != tr["positive_exposure"] or tm["independent_exposure"] != tr["independent_exposure"] or tm["control_exposure"] != tr["control_exposure"]:
                raise RuntimeError(f"v094d/v094c triplet identity mismatch for triplet {ti}")

            by_triplet[ti] += 1
            by_pair[r.get("canonical_pair", "")] += 1
            by_pp[tr["positive_plate"]] += 1; by_qp[tr["independent_plate"]] += 1; by_cp[tr["control_plate"]] += 1
            support[f"{r.get('positive_scan_support_class')}|{r.get('independent_scan_support_class')}"] += 1
            epoch[r.get("epoch_stratum", "")] += 1
            classes[r.get("confirmation_class", "")] += 1
            timing[tm["timing_impact_class"]] += 1
            multisub[f"any={tm['any_num_sub_gt1']}|science={tm['science_num_sub_gt1']}"] += 1
            coverage_triplet[f"P{r.get('positive_scan_coverage_count')}|I{r.get('independent_scan_coverage_count')}|C{r.get('control_scan_coverage_count')}"] += 1
            disposition[r.get("candidate_disposition", "")] += 1

            ps = r.get("positive_source_ids", ""); qs = r.get("independent_source_ids", "")
            positive_sig[ps] += 1; independent_sig[qs] += 1; pair_sig[(ps, qs)] += 1
            exact_coord[(r.get("candidate_ra_icrs", ""), r.get("candidate_dec_icrs", ""))] += 1
            ras.append(ra); decs.append(dec)
            qsep = fnum(r.get("independent_sep_arcsec")); csep = fnum(r.get("control_nearest_catalog_sep_arcsec"))
            if qsep is not None: indep_sep.append(qsep)
            if csep is not None: control_sep.append(csep)

            ira = min(23, int(ra / 15.0))
            s = (math.sin(math.radians(dec)) + 1.0) / 2.0
            idec = min(11, max(0, int(s * 12.0)))
            sky[(ira, idec)] += 1
            if n % 50000 == 0:
                print(f"candidate aggregate stream: {n:,}/{EXPECTED_CANDIDATE_ROWS:,}", flush=True)

    if invalid:
        raise RuntimeError(f"Invalid candidate rows encountered: {invalid}")
    if sum(by_triplet.values()) != EXPECTED_CANDIDATE_ROWS:
        raise RuntimeError(f"Candidate row count mismatch: {sum(by_triplet.values())}")

    xyz = np.column_stack((
        np.cos(np.radians(decs)) * np.cos(np.radians(ras)),
        np.cos(np.radians(decs)) * np.sin(np.radians(ras)),
        np.sin(np.radians(decs)),
    ))
    tree = cKDTree(xyz)
    dd, _ = tree.query(xyz, k=2)
    nearest_chord = dd[:, 1]
    nearest_arcsec = np.degrees(2.0 * np.arcsin(np.clip(nearest_chord, 0, 2) / 2.0)) * 3600.0
    nn = {}
    for rad in (0.01, 0.1, 0.5, 1.0, 3.0, 5.0):
        c = int(np.count_nonzero(nearest_arcsec <= rad))
        nn[str(rad)] = {"rows": c, "fraction": c / len(nearest_arcsec)}

    indep_thresholds = {}
    for t in (0.5, 1.0, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
        c = sum(x <= t for x in indep_sep)
        indep_thresholds[str(t)] = {"rows_le_threshold": c, "fraction_of_candidate_rows": c / EXPECTED_CANDIDATE_ROWS}
    control_survival = {}
    for t in (5.0, 5.1, 5.25, 5.5, 6.0, 10.0, 30.0):
        c = sum(x > t for x in control_sep)
        control_survival[str(t)] = {"rows_with_control_sep_gt_threshold": c, "fraction_of_candidate_rows": c / EXPECTED_CANDIDATE_ROWS}

    top_sky = sorted(sky.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    sky_summary = {
        "binning": "24 RA bins of 15 deg x 12 equal-sin(dec) bins",
        "occupied_bins": len(sky),
        "concentration": concentration(sky),
        "top20_bins": [
            {"ra_bin": k[0], "sin_dec_bin": k[1], "rows": v, "fraction": v / EXPECTED_CANDIDATE_ROWS}
            for k, v in top_sky
        ]
    }

    return {
        "by_triplet": by_triplet, "by_pair": by_pair, "by_positive_plate": by_pp, "by_independent_plate": by_qp, "by_control_plate": by_cp,
        "support": support, "epoch": epoch, "timing": timing, "multisub": multisub, "coverage": coverage_triplet,
        "classes": classes, "disposition": disposition,
        "source_reuse": {
            "positive_source_signature": multiplicity_summary(positive_sig),
            "independent_source_signature": multiplicity_summary(independent_sig),
            "positive_independent_signature_pair": multiplicity_summary(pair_sig),
            "exact_candidate_coordinate_string": multiplicity_summary(exact_coord),
        },
        "nearest_neighbor": nn,
        "independent_sep_hist": sep_hist(indep_sep, [0, 0.25, 0.5, 1, 2, 2.5, 3, 3.5, 4, 4.5, 4.75, 4.9, 5]),
        "control_sep_hist": sep_hist(control_sep, [5, 5.05, 5.1, 5.25, 5.5, 6, 10, 30, 60, 300, 3600]),
        "independent_threshold_sensitivity": indep_thresholds,
        "control_threshold_sensitivity": control_survival,
        "sky": sky_summary,
    }


def replay_mechanical_funnel(mod, eligible, scan_polys, candidate_counts, timing_map):
    pcache = mod.PlateLRU()
    per = []
    global_counts = Counter()

    for idx, tr in enumerate(eligible, 1):
        ti = tr["triplet_index"]
        tm = timing_map[ti]
        base = {
            "triplet_index": ti,
            "matchable_ordinal": tr["matchable_ordinal"],
            "canonical_pair": tr["canonical_pair"],
            "positive_plate": tr["positive_plate"], "positive_exposure": tr["positive_exposure"],
            "independent_plate": tr["independent_plate"], "independent_exposure": tr["independent_exposure"],
            "control_plate": tr["control_plate"], "control_exposure": tr["control_exposure"],
            "zero_source_hold": tr["zero_source_hold"],
            "timing_impact_class": tm["timing_impact_class"],
            "any_num_sub_gt1": tm["any_num_sub_gt1"],
            "science_num_sub_gt1": tm["science_num_sub_gt1"],
            "positive_representatives": 0, "covered_all3": 0, "control_mismatch_gt5": 0,
            "independent_match_le5": 0, "primary_le3": 0, "diagnostic_gt3_le5": 0,
            "candidate_csv_rows": candidate_counts.get(ti, 0), "source_data_status": "ZERO_SOURCE_PROVENANCE_HOLD" if tr["zero_source_hold"] else "PENDING"
        }
        if tr["zero_source_hold"]:
            per.append(base)
            continue

        pdata = pcache.get(tr["positive_plate"], tr["positive_scan_ids"])
        qdata = pcache.get(tr["independent_plate"], tr["independent_scan_ids"])
        cdata = pcache.get(tr["control_plate"], tr["control_scan_ids"])
        if not pdata["usable"] or not qdata["usable"] or not cdata["usable"]:
            base["source_data_status"] = "UNUSABLE_UNEXPECTED"
            per.append(base)
            continue
        base["source_data_status"] = "USABLE"
        p_ra, p_dec = pdata["rep_ra"], pdata["rep_dec"]
        base["positive_representatives"] = len(p_ra)
        q_tree = cKDTree(mod.xyz(qdata["rep_ra"], qdata["rep_dec"])) if len(qdata["rep_ra"]) else None

        for start in range(0, len(p_ra), MATCH_CHUNK):
            end = min(start + MATCH_CHUNK, len(p_ra))
            ra = p_ra[start:end]; dec = p_dec[start:end]
            covp = mod.coverage_count_batch(ra, dec, pdata["scan_ids"], scan_polys)
            covq = mod.coverage_count_batch(ra, dec, qdata["scan_ids"], scan_polys)
            covc = mod.coverage_count_batch(ra, dec, cdata["scan_ids"], scan_polys)
            covered = (covp >= 1) & (covq >= 1) & (covc >= 1)
            global_counts["candidate_not_covered_all3"] += int(np.count_nonzero(~covered))
            n_cov = int(np.count_nonzero(covered)); base["covered_all3"] += n_cov
            if not n_cov:
                continue
            local = np.flatnonzero(covered)
            d_control, _ = cdata["all_tree"].query(mod.xyz(ra[local], dec[local]), k=1)
            control_sep = mod.arcsec_from_chord_array(d_control)
            mismatch = control_sep > mod.BUSKO_R_ARCSEC
            n_mis = int(np.count_nonzero(mismatch)); base["control_mismatch_gt5"] += n_mis
            global_counts["control_catalog_match_le5"] += int(np.count_nonzero(~mismatch))
            global_counts["busko_catalog_mismatch"] += n_mis
            if not n_mis:
                continue
            local2 = local[mismatch]
            if q_tree is None:
                global_counts["no_independent_representative_catalog"] += len(local2)
                continue
            d_q, _ = q_tree.query(mod.xyz(ra[local2], dec[local2]), k=1)
            q_sep = mod.arcsec_from_chord_array(d_q)
            confirmed = q_sep <= mod.CONFIRM_DIAG_ARCSEC
            global_counts["no_independent_match_le5"] += int(np.count_nonzero(~confirmed))
            n_conf = int(np.count_nonzero(confirmed)); base["independent_match_le5"] += n_conf
            if not n_conf:
                continue
            confsep = q_sep[confirmed]
            n_pri = int(np.count_nonzero(confsep <= mod.CONFIRM_PRIMARY_ARCSEC))
            n_diag = n_conf - n_pri
            base["primary_le3"] += n_pri; base["diagnostic_gt3_le5"] += n_diag
            global_counts["PRIMARY_LE3"] += n_pri; global_counts["DIAGNOSTIC_GT3_LE5"] += n_diag

        base["coverage_fraction"] = ratio(base["covered_all3"], base["positive_representatives"])
        base["control_mismatch_fraction_of_covered"] = ratio(base["control_mismatch_gt5"], base["covered_all3"])
        base["independent_confirm_fraction_of_mismatch"] = ratio(base["independent_match_le5"], base["control_mismatch_gt5"])
        base["primary_fraction_of_confirmed"] = ratio(base["primary_le3"], base["independent_match_le5"])
        base["final_fraction_of_positive_representatives"] = ratio(base["independent_match_le5"], base["positive_representatives"])
        base["candidate_csv_reproduction_match"] = base["independent_match_le5"] == base["candidate_csv_rows"]
        per.append(base)
        if idx % 25 == 0:
            print(f"mechanical funnel replay: {idx}/{len(eligible)} triplets", flush=True)

    bad = [r["triplet_index"] for r in per if not r["zero_source_hold"] and not r.get("candidate_csv_reproduction_match", False)]
    if bad:
        raise RuntimeError(f"Per-triplet candidate reproduction mismatch for {len(bad)} triplets; first={bad[:10]}")
    return per, global_counts


def write_per_triplet(path: Path, rows):
    fields = [
        "triplet_index", "matchable_ordinal", "canonical_pair",
        "positive_plate", "positive_exposure", "independent_plate", "independent_exposure", "control_plate", "control_exposure",
        "zero_source_hold", "timing_impact_class", "any_num_sub_gt1", "science_num_sub_gt1", "source_data_status",
        "positive_representatives", "covered_all3", "control_mismatch_gt5", "independent_match_le5", "primary_le3", "diagnostic_gt3_le5", "candidate_csv_rows",
        "coverage_fraction", "control_mismatch_fraction_of_covered", "independent_confirm_fraction_of_mismatch", "primary_fraction_of_confirmed", "final_fraction_of_positive_representatives", "candidate_csv_reproduction_match"
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def make_order_bins(per):
    bins = []
    matchable = [r for r in per if r["matchable_ordinal"] is not None]
    for start in range(1, EXPECTED_MATCHABLE + 1, 25):
        end = min(EXPECTED_MATCHABLE, start + 24)
        rr = [r for r in matchable if start <= r["matchable_ordinal"] <= end]
        sums = {k: sum(int(x.get(k) or 0) for x in rr) for k in ("positive_representatives", "covered_all3", "control_mismatch_gt5", "independent_match_le5", "primary_le3", "diagnostic_gt3_le5", "candidate_csv_rows")}
        bins.append({
            "matchable_ordinal_start": start, "matchable_ordinal_end": end, "triplets": len(rr), **sums,
            "coverage_fraction": ratio(sums["covered_all3"], sums["positive_representatives"]),
            "control_mismatch_fraction_of_covered": ratio(sums["control_mismatch_gt5"], sums["covered_all3"]),
            "independent_confirm_fraction_of_mismatch": ratio(sums["independent_match_le5"], sums["control_mismatch_gt5"]),
            "final_fraction_of_positive_representatives": ratio(sums["independent_match_le5"], sums["positive_representatives"]),
            "candidate_row_share": sums["candidate_csv_rows"] / EXPECTED_CANDIDATE_ROWS,
        })
    return bins


def write_order_bins(path: Path, rows):
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)



def stage_profile(rows):
    keys = ("positive_representatives", "covered_all3", "control_mismatch_gt5", "independent_match_le5", "primary_le3", "diagnostic_gt3_le5", "candidate_csv_rows")
    sums = {k: sum(int(r.get(k) or 0) for r in rows) for k in keys}
    return {
        **sums,
        "triplets": len(rows),
        "coverage_fraction": ratio(sums["covered_all3"], sums["positive_representatives"]),
        "control_mismatch_fraction_of_covered": ratio(sums["control_mismatch_gt5"], sums["covered_all3"]),
        "independent_confirm_fraction_of_mismatch": ratio(sums["independent_match_le5"], sums["control_mismatch_gt5"]),
        "final_fraction_of_positive_representatives": ratio(sums["independent_match_le5"], sums["positive_representatives"]),
    }


def compare_window(per, lo, hi):
    matchable = [r for r in per if r["matchable_ordinal"] is not None]
    inside = [r for r in matchable if lo <= r["matchable_ordinal"] <= hi]
    outside = [r for r in matchable if not (lo <= r["matchable_ordinal"] <= hi)]
    allp = stage_profile(matchable); pin = stage_profile(inside); pout = stage_profile(outside)
    shares = {}
    for k in ("positive_representatives", "covered_all3", "control_mismatch_gt5", "independent_match_le5", "primary_le3", "diagnostic_gt3_le5", "candidate_csv_rows"):
        shares[k] = ratio(pin[k], allp[k])
    ampl = {
        "coverage_rate_inside_vs_outside": ratio(pin["coverage_fraction"], pout["coverage_fraction"]),
        "control_mismatch_rate_inside_vs_outside": ratio(pin["control_mismatch_fraction_of_covered"], pout["control_mismatch_fraction_of_covered"]),
        "independent_confirm_rate_inside_vs_outside": ratio(pin["independent_confirm_fraction_of_mismatch"], pout["independent_confirm_fraction_of_mismatch"]),
        "final_per_positive_rep_inside_vs_outside": ratio(pin["final_fraction_of_positive_representatives"], pout["final_fraction_of_positive_representatives"]),
    }
    return {"ordinal_start": lo, "ordinal_end": hi, "inside": pin, "outside": pout, "inside_share_of_global_stage": shares, "inside_vs_outside_rate_ratio": ampl}

def self_test():
    c = Counter({"a": 10, "b": 0, "c": 5})
    x = concentration(c)
    assert x["total_rows"] == 15 and x["max_group_rows"] == 10
    m = multiplicity_summary(Counter({"x": 2, "y": 1, "z": 3}))
    assert m["total_rows"] == 6 and m["max_multiplicity"] == 3
    h = sep_hist([0.1, 0.9, 1.0, 2.0], [0, 1, 2])
    assert sum(h["counts"]) == 4
    print("v094e self-test PASS")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root")
    ap.add_argument("--repo-root")
    ap.add_argument("--freeze-commit")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.project_root or not args.repo_root or not args.freeze_commit:
        ap.error("--project-root, --repo-root and --freeze-commit are required")

    project = Path(args.project_root).resolve(); repo = Path(args.repo_root).resolve(); freeze = args.freeze_commit.strip()
    verify_frozen_git(repo, freeze)
    contract = json.loads((repo / CONTRACT_REL).read_text(encoding="utf-8"))
    prov = json.loads((repo / PROVENANCE_REL).read_text(encoding="utf-8"))
    if contract.get("status") != "PROSPECTIVE_AGGREGATE_PATHOLOGY_AUDIT":
        raise RuntimeError("v094e contract status mismatch")
    if prov.get("status") != "FROZEN_PARENT_PROVENANCE_PREPARED_BEFORE_V094E_EXECUTION":
        raise RuntimeError("v094e parent provenance status mismatch")

    # Verify parent files against the pre-execution provenance frozen in Git.
    for section, keys in {
        "v094c": [("candidate_csv", "candidate_csv_sha256"), ("report", "report_sha256"), ("bank", "bank_sha256"), ("runner", "runner_sha256")],
        "v094d": [("report", "report_sha256"), ("master_registry", "master_registry_sha256"), ("legacy_impact", "legacy_impact_sha256"), ("output_manifest", "output_manifest_sha256")],
        "selection_and_geometry": [("v093e_opportunities", "v093e_opportunities_sha256"), ("v093e_comparisons", "v093e_comparisons_sha256"), ("v093_scan_cache", "v093_scan_cache_sha256"), ("v093_solution_cache", "v093_solution_cache_sha256"), ("v094b_selection_snapshot", "v094b_selection_snapshot_sha256")]
    }.items():
        sec = prov[section]
        for pkey, hkey in keys:
            p = project / sec[pkey]
            if sha256(p) != sec[hkey]:
                raise RuntimeError(f"Parent input changed after v094e freeze: {section}.{pkey}")

    candidate = project / prov["v094c"]["candidate_csv"]
    if sha256(candidate) != EXPECTED_V094C_CANDIDATE_SHA:
        raise RuntimeError("Frozen v094c candidate CSV hash mismatch")
    verify_source_inventory(project, repo / INVENTORY_REL, prov["source_cache_inventory"]["inventory_sha256"])

    mod = load_v094c_module(project)
    eligible, scan_polys = reconstruct_triplets(mod)
    by_index = {r["triplet_index"]: r for r in eligible}
    timing_path = project / prov["v094d"]["legacy_impact"]
    timing_map = load_timing_map(timing_path)

    print("Streaming frozen v094c candidate catalogue for aggregate-only diagnostics...", flush=True)
    agg = stream_candidate_aggregates(candidate, timing_map, by_index)
    print("Replaying frozen v094c mechanical funnel as per-triplet counters only...", flush=True)
    per, replay = replay_mechanical_funnel(mod, eligible, scan_polys, agg["by_triplet"], timing_map)

    v094c_report = json.loads((project / prov["v094c"]["report"]).read_text(encoding="utf-8"))
    expected_mech = v094c_report.get("mechanical_counter", {})
    key_compare = ["candidate_not_covered_all3", "control_catalog_match_le5", "busko_catalog_mismatch", "no_independent_match_le5", "PRIMARY_LE3", "DIAGNOSTIC_GT3_LE5"]
    mismatch = {k: {"replayed": replay.get(k, 0), "frozen": expected_mech.get(k, 0)} for k in key_compare if int(replay.get(k, 0)) != int(expected_mech.get(k, 0))}
    if mismatch:
        raise RuntimeError(f"Global mechanical replay mismatch: {mismatch}")

    outdir = project / "results" / "applause_dr4_aggregate_pathology_audit_v094e"
    outdir.mkdir(parents=True, exist_ok=True)
    per_path = outdir / "per_triplet_mechanical_funnel_v094e.csv"
    bins_path = outdir / "matchable_order_25bin_pathology_v094e.csv"
    report_path = outdir / "applause_dr4_aggregate_pathology_audit_v094e.json"
    manifest_path = outdir / "v094e_output_manifest.sha256"
    write_per_triplet(per_path, per)
    bins = make_order_bins(per); write_order_bins(bins_path, bins)

    trip_counter = Counter({r["triplet_index"]: int(r["candidate_csv_rows"]) for r in per})
    pair_counter = Counter(); pp_counter = Counter(); qp_counter = Counter(); cp_counter = Counter()
    for r in per:
        n = int(r["candidate_csv_rows"])
        pair_counter[r["canonical_pair"]] += n; pp_counter[r["positive_plate"]] += n; qp_counter[r["independent_plate"]] += n; cp_counter[r["control_plate"]] += n

    # Exact known order-window shares, now recomputed from frozen matchable ordinals.
    def ord_share(lo, hi):
        n = sum(int(r["candidate_csv_rows"]) for r in per if r["matchable_ordinal"] is not None and lo <= r["matchable_ordinal"] <= hi)
        return {"rows": n, "share": n / EXPECTED_CANDIDATE_ROWS}

    timing_rows = Counter()
    multi_rows = Counter()
    for r in per:
        n = int(r["candidate_csv_rows"])
        timing_rows[r["timing_impact_class"]] += n
        multi_rows[f"any={r['any_num_sub_gt1']}|science={r['science_num_sub_gt1']}"] += n

    profile_251_275 = compare_window(per, 251, 275)
    profile_251_300 = compare_window(per, 251, 300)
    top_bins = sorted(bins, key=lambda r: (-r["candidate_csv_rows"], r["matchable_ordinal_start"]))[:5]

    report = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_aggregate_pathology_audit_v094e",
        "freeze_commit": freeze,
        "guards": contract["guards"],
        "input_reproduction": {
            "triplets": len(per),
            "zero_source_holds": sum(bool(r["zero_source_hold"]) for r in per),
            "matchable_triplets": sum(r["matchable_ordinal"] is not None for r in per),
            "candidate_rows": sum(int(r["candidate_csv_rows"]) for r in per),
            "per_triplet_candidate_reproduction": "PASS",
            "global_mechanical_counter_reproduction": "PASS",
            "replayed_mechanical_counters": dict(replay),
        },
        "order_concentration": {
            "matchable_ordinal_251_275": ord_share(251, 275),
            "matchable_ordinal_251_300": ord_share(251, 300),
            "stage_profile_251_275": profile_251_275,
            "stage_profile_251_300": profile_251_300,
            "top5_25triplet_bins_by_candidate_rows": top_bins,
            "all_25bin_rows_written": bins_path.name,
        },
        "candidate_row_concentration": {
            "triplet": concentration(trip_counter),
            "canonical_pair": concentration(pair_counter),
            "positive_plate": concentration(pp_counter),
            "independent_plate": concentration(qp_counter),
            "control_plate": concentration(cp_counter),
        },
        "candidate_aggregate_strata": {
            "confirmation_class_counts": dict(agg["classes"]),
            "scan_support_class_counts": dict(agg["support"]),
            "epoch_counts": dict(agg["epoch"]),
            "timing_impact_class_candidate_rows": dict(timing_rows),
            "num_sub_candidate_rows": dict(multi_rows),
            "coverage_count_patterns": dict(agg["coverage"]),
            "candidate_disposition_counts": dict(agg["disposition"]),
        },
        "recurrence_and_reuse": {
            **agg["source_reuse"],
            "global_nearest_neighbor_arcsec": agg["nearest_neighbor"],
            "note": "No candidate coordinate or source identifier is emitted; only multiplicity/nearest-neighbour aggregate statistics are retained."
        },
        "threshold_sensitivity": {
            "independent_sep_histogram": agg["independent_sep_hist"],
            "control_nearest_sep_histogram": agg["control_sep_hist"],
            "independent_cumulative": agg["independent_threshold_sensitivity"],
            "control_survival": agg["control_threshold_sensitivity"],
            "interpretation_limit": "Diagnostic sensitivity only; thresholds are not retuned and no corrected candidate population is created."
        },
        "coarse_spatial_aggregate": agg["sky"],
        "timing_interaction": {
            "legacy_timing_class_candidate_rows": dict(timing_rows),
            "timing_invalid_triplets": 3,
            "timing_invalid_candidate_rows": timing_rows.get("HOLD_NO_FRAGMENT_LEVEL_SCIENCE_OVERLAP", 0),
            "timing_invalid_candidate_row_share": timing_rows.get("HOLD_NO_FRAGMENT_LEVEL_SCIENCE_OVERLAP", 0) / EXPECTED_CANDIDATE_ROWS,
            "multi_sub_candidate_rows": dict(multi_rows)
        },
        "interpretive_boundary": contract["interpretive_boundary"],
        "next_stop": contract["next_stop"],
        "outputs": {}
    }
    report["outputs"] = {
        per_path.name: {"sha256": sha256(per_path), "size_bytes": per_path.stat().st_size},
        bins_path.name: {"sha256": sha256(bins_path), "size_bytes": bins_path.stat().st_size},
    }
    write_json(report_path, report)
    manifest_path.write_text(
        f"{sha256(per_path)}  {per_path.name}\n{sha256(bins_path)}  {bins_path.name}\n{sha256(report_path)}  {report_path.name}\n",
        encoding="ascii"
    )

    print("\n" + "=" * 92)
    print("v094e AGGREGATE PATHOLOGY AUDIT COMPLETE")
    print("=" * 92)
    print(f"Triplets reconstructed:                  {len(per)}")
    print(f"Zero-source holds:                       {sum(bool(r['zero_source_hold']) for r in per)}")
    print(f"Mechanically matchable:                  {sum(r['matchable_ordinal'] is not None for r in per)}")
    print(f"Candidate rows reproduced:               {sum(int(r['candidate_csv_rows']) for r in per):,}")
    print(f"Order 251-275 candidate share:           {ord_share(251, 275)['share']:.4%}")
    print(f"Order 251-300 candidate share:           {ord_share(251, 300)['share']:.4%}")
    print(f"Triplet Gini:                            {concentration(trip_counter)['gini']:.6f}")
    print(f"Triplet top-10 share:                    {concentration(trip_counter)['top10_group_share']:.4%}")
    print(f"Positive-plate top-5 share:              {concentration(pp_counter)['top5_group_share']:.4%}")
    p = profile_251_275["inside_share_of_global_stage"]
    a = profile_251_275["inside_vs_outside_rate_ratio"]
    print(f"251-275 share of positive reps:          {p['positive_representatives']:.4%}")
    print(f"251-275 share after all3 coverage:       {p['covered_all3']:.4%}")
    print(f"251-275 share after control mismatch:    {p['control_mismatch_gt5']:.4%}")
    print(f"251-275 share after independent <=5:     {p['independent_match_le5']:.4%}")
    print(f"251-275 coverage rate vs outside:        {a['coverage_rate_inside_vs_outside']:.3f}x")
    print(f"251-275 control-mismatch rate vs outside:{a['control_mismatch_rate_inside_vs_outside']:.3f}x")
    print(f"251-275 confirm rate vs outside:         {a['independent_confirm_rate_inside_vs_outside']:.3f}x")
    print(f"Rows with global NN <=3 arcsec:          {agg['nearest_neighbor']['3.0']['fraction']:.4%}")
    print(f"Rows in repeated exact coord strings:    {agg['source_reuse']['exact_candidate_coordinate_string']['fraction_rows_in_reused_signatures']:.4%}")
    print(f"Timing-invalid candidate rows:           {timing_rows.get('HOLD_NO_FRAGMENT_LEVEL_SCIENCE_OVERLAP', 0):,}")
    print(f"Timing-invalid candidate share:          {timing_rows.get('HOLD_NO_FRAGMENT_LEVEL_SCIENCE_OVERLAP', 0)/EXPECTED_CANDIDATE_ROWS:.4%}")
    print("Mechanical replay reproduction:          PASS")
    print("STOP: interpret aggregate pathology before candidate inspection or registration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
