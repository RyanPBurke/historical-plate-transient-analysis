from __future__ import annotations

from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import argparse
import csv
import json
import math
import re
import threading
import time
import webbrowser

ROOT = Path.cwd()
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DASHBOARD_VERSION = "2.0-process-flow"


def loadj(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv(path: Path | None):
    if not path or not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def csv_count(path: Path | None):
    if not path or not path.is_file():
        return None
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rdr = csv.reader(fh)
            next(rdr, None)
            return sum(1 for _ in rdr)
    except Exception:
        return None


def first_existing(*paths):
    for p in paths:
        p = Path(p)
        if p.is_file():
            return p
    return None


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def pick(row, *names, default=None):
    if not isinstance(row, dict):
        return default
    lookup = {norm(k): k for k in row}
    for name in names:
        key = lookup.get(norm(name))
        if key is not None and row.get(key) not in (None, ""):
            return row.get(key)
    return default


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def find_scalar(obj, *keys):
    wanted = {norm(k) for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if norm(k) in wanted and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            got = find_scalar(v, *keys)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find_scalar(v, *keys)
            if got is not None:
                return got
    return None


def fmt_int(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return "—"


def fmt_float(v, digits=3):
    try:
        return f"{float(v):,.{digits}f}"
    except Exception:
        return "—"


def rel(path):
    if not path:
        return None
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def metric(label, value, note="", tone="normal"):
    return {"label": label, "value": value, "note": note, "tone": tone}


def stage_rows():
    rows = []
    try:
        from automation.registry_order01 import ORDER01_STAGES
        complete = set()
        for s in ORDER01_STAGES:
            prods = [ROOT / p for p in (getattr(s, "produces", ()) or ())]
            if prods and all(p.exists() for p in prods):
                complete.add(s.stage_id)
        for s in ORDER01_STAGES:
            prods = [ROOT / p for p in (getattr(s, "produces", ()) or ())]
            reqs = [ROOT / p for p in (getattr(s, "requires", ()) or ())]
            deps = list(getattr(s, "dependencies", ()) or ())
            if prods and all(p.exists() for p in prods):
                st = "COMPLETE"
            elif any(not p.exists() for p in reqs):
                st = "BLOCKED"
            elif any(d not in complete for d in deps):
                st = "WAITING"
            else:
                st = "READY"
            rows.append({
                "id": s.stage_id,
                "title": getattr(s, "title", s.stage_id),
                "status": st,
                "network": bool(getattr(s, "network_access", False)),
                "pixels": bool(
                    getattr(s, "science_pixels_read", False)
                    or getattr(s, "non_science_pixels_read", False)
                ),
            })
    except Exception as exc:
        rows.append({
            "id": "registry",
            "title": f"Registry unavailable: {exc}",
            "status": "ERROR",
            "network": False,
            "pixels": False,
        })
    return rows


def opportunity_snapshot():
    path = first_existing(
        ROOT / "archive_pair_overlap_candidates.csv",
        ROOT / "source_data" / "archive_pair_overlap_candidates.csv",
        ROOT / "research" / "archive_pair_overlap_candidates.csv",
    )
    rows = read_csv(path)
    total = len(rows) if rows else None
    mids = []
    overlaps = []
    for r in rows:
        m = fnum(pick(
            r,
            "midpoint_delta_minutes",
            "midpoint_separation_minutes",
            "midpoint_delta_min",
            "midpoint_minutes",
        ))
        if m is not None:
            mids.append(abs(m))
        o = fnum(pick(
            r,
            "overlap_seconds",
            "actual_exposure_overlap_s",
            "catalogue_interval_overlap_s",
            "interval_overlap_seconds",
            "overlap_s",
        ))
        if o is not None:
            overlaps.append(o)
    return {
        "path": path,
        "total": total,
        "le5": sum(x <= 5 for x in mids) if mids else None,
        "le10": sum(x <= 10 for x in mids) if mids else None,
        "le15": sum(x <= 15 for x in mids) if mids else None,
        "interval_positive": sum(x > 0 for x in overlaps) if overlaps else None,
    }


def timing_snapshot():
    path = first_existing(
        ROOT / "results" / "wide_census_physical_timing_v050.json",
        ROOT / "results" / "wide_census_physical_timing_v049a.json",
        ROOT / "results" / "wide_census_physical_timing_v049.json",
    )
    report = loadj(path) if path else None
    counts = (report or {}).get("classification_counts", {})
    survive = sum(int(v) for k, v in counts.items() if "TIMING_OVERLAP_SURVIVES" in str(k))
    fragile = sum(int(v) for k, v in counts.items() if "FRAGILE" in str(k))
    no_overlap = sum(int(v) for k, v in counts.items() if "NO_ARCHIVE_SUPPORTED_TIME_OVERLAP" in str(k))
    total = sum(int(v) for v in counts.values()) if counts else None
    other = None if total is None else total - survive - fragile - no_overlap
    return {
        "path": path,
        "report": report,
        "total": total,
        "survive": survive if counts else None,
        "fragile": fragile if counts else None,
        "no_overlap": no_overlap if counts else None,
        "other": other,
    }


def footprint_snapshot():
    path = ROOT / "results" / "wide_census_exact_footprint_v052.json"
    report = loadj(path) if path.is_file() else None
    counts = (report or {}).get("classification_counts", {})
    return {
        "path": path if path.is_file() else None,
        "report": report,
        "total": sum(int(v) for v in counts.values()) if counts else None,
        "robust": counts.get("TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST") if counts else None,
        "holds": counts.get("EXACT_FOOTPRINT_UNRESOLVED") if counts else None,
        "closed": counts.get("NO_TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST") if counts else None,
    }


def geometry_snapshot():
    v57 = (
        ROOT / "results" / "wide_census_geometry_hold_inventory_v057"
        / "wide_census_geometry_hold_inventory_v057.csv"
    )
    v58 = (
        ROOT / "results" / "wide_census_applause_hold_metadata_v058"
        / "wide_census_applause_hold_endpoint_inventory_v058.csv"
    )
    v59 = (
        ROOT / "results" / "wide_census_applause_process_audit_v059"
        / "wide_census_applause_process_audit_v059.json"
    )
    v60 = (
        ROOT / "results" / "wide_census_astrometric_rescue_preflight_v060"
        / "wide_census_astrometric_rescue_preflight_v060.json"
    )
    hold_rows = read_csv(v57)
    applause = read_csv(v58)
    j59 = loadj(v59) if v59.is_file() else {}
    j60 = loadj(v60) if v60.is_file() else {}
    unique_exp = {str(pick(r, "exposure_id")) for r in applause if pick(r, "exposure_id") not in (None, "")}
    unique_plate = {str(pick(r, "plate_id")) for r in applause if pick(r, "plate_id") not in (None, "")}
    states59 = (j59 or {}).get("plate_state_counts", {})
    ready60 = (j60 or {}).get("readiness_counts", {})
    dasch_no_header = 0
    for r in hold_rows:
        txt = " ".join(str(v) for v in r.values())
        if "UNRESOLVED_DASCH_NO_ASTROMETRY_HEADER" in txt:
            dasch_no_header += 1
    return {
        "applause_occurrences": len(applause) if applause else None,
        "applause_unique_exposures": len(unique_exp) if applause else None,
        "applause_unique_plates": len(unique_plate) if applause else None,
        "completed_unsolved": states59.get("PROCESS_COMPLETED_ASTROMETRICALLY_UNSOLVED") if states59 else None,
        "no_process": states59.get("NO_PROCESS_ROW_FOR_EXACT_SCAN") if states59 else None,
        "centroid_ready": ready60.get("OFFICIAL_CENTROID_CATALOGUE_READY_FOR_PROSPECTIVE_SOLVER") if ready60 else None,
        "pixel_extract": ready60.get("PIXEL_SOURCE_EXTRACTION_REQUIRED_NO_APPLAUSE_PROCESS") if ready60 else None,
        "dasch_no_header": dasch_no_header if hold_rows else None,
    }


def detector_snapshot():
    path = ROOT / "results" / "wide_census_detector_execution_v056.json"
    report = loadj(path) if path.is_file() else None
    pair_path = ROOT / "results" / "wide_census_pair_raw_match_summary_v056.csv"
    pair_rows = read_csv(pair_path)
    complete = isinstance(report, dict) and str(report.get("status", "")).upper() == "COMPLETE"
    return {
        "path": path if path.is_file() else None,
        "report": report,
        "pairs": len(pair_rows) if pair_rows else find_scalar(report, "pair_count", "opportunities"),
        "tiles": find_scalar(report, "tiles_total", "total_tiles", "tiles_complete") or (6293 if complete else None),
        "candidates": find_scalar(report, "accepted_native_detector_candidates_total", "accepted_detector_candidates"),
        "raw10": find_scalar(report, "raw_le_10arcsec_match_count", "raw_le10_count"),
        "raw3": find_scalar(report, "raw_le_3arcsec_match_count", "raw_le3_count"),
        "zero_sigma": find_scalar(report, "uninformative_zero_sigma_tiles", "zero_sigma_tiles"),
        "uninformative_pairs": find_scalar(report, "pairs_with_uninformative_detector_coverage", "uninformative_detector_coverage_pairs"),
    }


def post_snapshot():
    path = (
        ROOT / "results" / "wide_census_postdetector_inventory_v061"
        / "wide_census_postdetector_inventory_v061.json"
    )
    report = loadj(path) if path.is_file() else None
    hist = (report or {}).get("global_raw_separation_histogram", {})
    return {
        "path": path if path.is_file() else None,
        "report": report,
        "hist": hist,
        "control_jobs": csv_count(ROOT / "results" / "wide_census_population_control_queue_v061.csv"),
        "astrometry_jobs": csv_count(ROOT / "results" / "wide_census_primary_astrometry_queue_v061.csv"),
    }


def controls_snapshot():
    base = ROOT / "results" / "wide_census_population_controls_v062"
    report_path = base / "wide_census_population_controls_v062.json"
    state_path = base / "state_v062.json"
    report = loadj(report_path) if report_path.is_file() else None
    state = loadj(state_path) if state_path.is_file() else None
    if isinstance(report, dict) and report.get("status") == "COMPLETE":
        status = "COMPLETE"
        done_pairs, done_jobs = 33, 528
    elif isinstance(state, dict):
        status = "COMPLETE" if str(state.get("status", "")).upper() == "COMPLETE" else "RUNNING"
        done_pairs = len(state.get("completed_pair_indices", []) or [])
        done_jobs = len(state.get("control_rows", []) or [])
    else:
        status, done_pairs, done_jobs = "PENDING", 0, 0
    dist = (report or {}).get("global_control_distribution", {})
    return {
        "status": status,
        "done_pairs": done_pairs,
        "done_jobs": done_jobs,
        "ratio3": dist.get("observed_to_control3_mean_ratio") if isinstance(dist, dict) else None,
        "ratio10": dist.get("observed_to_control10_mean_ratio") if isinstance(dist, dict) else None,
        "mean3": ((dist.get("le_3arcsec") or {}).get("mean")) if isinstance(dist, dict) else None,
        "mean10": ((dist.get("le_10arcsec") or {}).get("mean")) if isinstance(dist, dict) else None,
        "source": report_path if report_path.is_file() else (state_path if state_path.is_file() else None),
    }


def match3_snapshot():
    def j(*parts):
        return loadj(ROOT.joinpath(*parts)) or {}
    g = j("results", "order11_followup_match3_v042", "order11_match3_gaia_epoch_report_v042.json")
    a43 = j("results", "order11_followup_match3_v043a", "order11_match3_local_astrometry_report_v043a.json")
    a44 = j("results", "order11_followup_match3_v044", "order11_match3_sparse_astrometry_report_v044.json")
    f45 = j("results", "order11_followup_match3_v045", "order11_match3_final_adjudication_v045.json")
    return {
        "gaia": g.get("classification"),
        "common_astrometry": a43.get("classification"),
        "sparse_astrometry": a44.get("classification"),
        "poss_morph": ((f45.get("morphology") or {}).get("POSS") or {}).get("classification"),
        "dasch_morph": ((f45.get("morphology") or {}).get("DASCH") or {}).get("classification"),
        "final": f45.get("classification"),
    }


def process_snapshot():
    opp = opportunity_snapshot()
    timing = timing_snapshot()
    foot = footprint_snapshot()
    geom = geometry_snapshot()
    det = detector_snapshot()
    post = post_snapshot()
    ctrl = controls_snapshot()

    def rep_status(report, path):
        if isinstance(report, dict) and str(report.get("status", "")).upper() == "COMPLETE":
            return "COMPLETE"
        return "READY" if path else "PENDING"

    stages = [
        {
            "number": 1,
            "title": "Catalogue opportunity census",
            "status": "COMPLETE" if opp["total"] is not None else "PENDING",
            "question": "Which archival exposure pairs are close enough in time to investigate?",
            "metrics": [
                metric("Catalogue-level pairs", fmt_int(opp["total"]), "Broad opportunity universe"),
                metric("Midpoint ≤5 min", fmt_int(opp["le5"])),
                metric("Midpoint ≤10 min", fmt_int(opp["le10"])),
                metric("Midpoint ≤15 min", fmt_int(opp["le15"]), "Working time-gate population", "accent"),
                metric("Catalogue interval overlap", fmt_int(opp["interval_positive"]), "Metadata-level only"),
            ],
            "meaning": "This is a screening universe, not a transient list. Midpoint proximity is only a pre-filter; real exposure overlap is tested next.",
            "source": rel(opp["path"]),
        },
        {
            "number": 2,
            "title": "Physical exposure timing",
            "status": rep_status(timing["report"], timing["path"]),
            "question": "Did the two physical exposures actually overlap in time?",
            "metrics": [
                metric("Pairs evaluated", fmt_int(timing["total"])),
                metric("Physical-overlap survivors", fmt_int(timing["survive"]), "Proceed to footprint validation", "good"),
                metric("Timing fragile", fmt_int(timing["fragile"]), "Preserved separately", "warn"),
                metric("No supported overlap", fmt_int(timing["no_overlap"]), "Closed for simultaneity", "closed"),
                metric("Other / provenance-excluded", fmt_int(timing["other"])),
            ],
            "meaning": "Physical exposure intervals are authoritative. A small midpoint separation does not establish simultaneity.",
            "source": rel(timing["path"]),
        },
        {
            "number": 3,
            "title": "Exact common-sky footprint",
            "status": rep_status(foot["report"], foot["path"]),
            "question": "Did both exposures image the same patch of sky?",
            "metrics": [
                metric("Timing survivors", fmt_int(foot["total"])),
                metric("Robust true overlap", fmt_int(foot["robust"]), "Main detector branch", "good"),
                metric("No true sky overlap", fmt_int(foot["closed"]), "Closed for common-sky coincidence", "closed"),
                metric("Geometry holds", fmt_int(foot["holds"]), "Outside detector denominator", "warn"),
            ],
            "meaning": "A temporally overlapping pair is useful only if the physical scans cover common sky. Unresolved geometry is held, not treated as a negative.",
            "source": rel(foot["path"]),
            "branch": {
                "title": "Geometry-hold recovery branch",
                "status": "ACTIVE",
                "intro": "Held pairs remain preserved outside the detector denominator while missing archive geometry is independently recovered.",
                "metrics": [
                    metric("Held pairs", fmt_int(foot["holds"])),
                    metric("APPLAUSE endpoint occurrences", fmt_int(geom["applause_occurrences"])),
                    metric("Unique APPLAUSE exposures", fmt_int(geom["applause_unique_exposures"])),
                    metric("APPLAUSE physical plates", fmt_int(geom["applause_unique_plates"])),
                    metric("Completed but unsolved plates", fmt_int(geom["completed_unsolved"])),
                    metric("Centroid catalogues ready", fmt_int(geom["centroid_ready"]), "For later prospectively frozen solver", "good"),
                    metric("Needs pixel source extraction", fmt_int(geom["pixel_extract"])),
                    metric("DASCH no-header occurrences", fmt_int(geom["dasch_no_header"])),
                ],
                "note": "Recovery audits do not mutate the original v052 hold classification. The hold set stays visible until separately resolved.",
            },
        },
        {
            "number": 4,
            "title": "Frozen residual-peak detector",
            "status": rep_status(det["report"], det["path"]),
            "question": "What residual peaks exist in each robust-overlap exposure?",
            "metrics": [
                metric("Robust pairs analysed", fmt_int(det["pairs"])),
                metric("Native detector candidates", fmt_int(det["candidates"]), "Residual detections, not transients", "accent"),
                metric("Native tiles", fmt_int(det["tiles"])),
                metric("Zero-sigma tiles", fmt_int(det["zero_sigma"]), "Uninformative, not clean negatives", "warn"),
                metric("Pairs with some uninformative coverage", fmt_int(det["uninformative_pairs"]), "", "warn"),
            ],
            "meaning": "The frozen detector deliberately produces a huge generic residual population. Detection itself is not a transient classification.",
            "source": rel(det["path"]),
        },
        {
            "number": 5,
            "title": "Raw cross-observatory coincidence census",
            "status": "COMPLETE" if post["report"] else "PENDING",
            "question": "How many residual peaks land near a residual peak in the paired exposure?",
            "metrics": [
                metric("Raw ≤10″ coincidences", fmt_int(det["raw10"]), "Measurement only"),
                metric("Raw ≤3″ coincidences", fmt_int(det["raw3"]), "Strict raw gate; still not source identity", "accent"),
                metric("Raw ≤0.5″", fmt_int(post["hist"].get("le0p5"))),
                metric("Raw ≤1″", fmt_int(post["hist"].get("le1"))),
                metric("Raw ≤2″", fmt_int(post["hist"].get("le2"))),
                metric("Raw ≤5″", fmt_int(post["hist"].get("le5"))),
            ],
            "meaning": "Raw coordinate coincidence is not identity. Chance overlap, persistent sources, detector structure and archive astrometric offsets can all contribute.",
            "source": rel(post["path"]),
        },
        {
            "number": 6,
            "title": "Shifted population controls",
            "status": ctrl["status"],
            "question": "Are true alignments richer in close matches than nearby deliberately shifted alignments?",
            "progress": {"current": ctrl["done_jobs"], "total": 528, "label": f"{ctrl['done_pairs']}/33 pairs · {ctrl['done_jobs']}/528 shifts"},
            "metrics": [
                metric("Control jobs", f"{ctrl['done_jobs']:,} / 528", "60″/120″ × 8 directions", "accent"),
                metric("Pairs checkpointed", f"{ctrl['done_pairs']:,} / 33"),
                metric("Observed/control mean ≤3″", fmt_float(ctrl["ratio3"], 4), "Final report only"),
                metric("Observed/control mean ≤10″", fmt_float(ctrl["ratio10"], 4), "Final report only"),
                metric("Control mean ≤3″", fmt_float(ctrl["mean3"], 1)),
                metric("Control mean ≤10″", fmt_float(ctrl["mean10"], 1)),
            ],
            "meaning": "This is population context only. Even a large excess cannot decide an individual coincidence; it tells us whether the raw-match population contains spatial correlation.",
            "source": rel(ctrl["source"]),
        },
        {
            "number": 7,
            "title": "Common-reference astrometric registration",
            "status": "READY" if post["astrometry_jobs"] else "PENDING",
            "question": "After measuring local archive coordinate offsets, which raw coincidences still agree on the sky?",
            "metrics": [
                metric("Primary registration jobs", fmt_int(post["astrometry_jobs"]), "33 pairs × 5′/10′/20′/30′"),
                metric("Minimum common Gaia refs", "5", "Same Gaia sources in both archives"),
                metric("Primary model", "Translation median", "No clipping; no higher-order fit"),
                metric("Sparse fallback", "Conditional", "Only if primary has <5 refs at 30′"),
            ],
            "meaning": "This is the main mechanical explanation stage for candidate coincidence: local archive offsets are measured from independent stars before judging the candidate separation.",
            "source": rel(ROOT / "results" / "wide_census_primary_astrometry_queue_v061.csv") if (ROOT / "results" / "wide_census_primary_astrometry_queue_v061.csv").is_file() else None,
        },
        {
            "number": 8,
            "title": "Candidate-level adjudication",
            "status": "PENDING",
            "question": "For astrometric survivors, is there an ordinary astrophysical or plate-based explanation?",
            "metrics": [
                metric("Gaia", "Epoch propagated", "3″ strict / 5″ diagnostic"),
                metric("Morphology", "Contextual", "Never proof by itself"),
                metric("Recurrence", "Sensitivity-qualified", "Only meaningful negatives count"),
                metric("Near-Earth branch", "Separate", "Parallax-aware hypothesis"),
            ],
            "meaning": "Only mechanically surviving coincidences reach this stage. Catalogue absence alone is never treated as evidence of transience.",
            "source": "prospective v057 adjudication contract",
        },
        {
            "number": 9,
            "title": "Terminal manual review & science disposition",
            "status": "PENDING",
            "question": "Does any terminal survivor warrant a science-positive two-observatory transient classification?",
            "metrics": [
                metric("Science-positive classifications so far", "0", "Adjudication is not complete", "neutral"),
                metric("Manual-review policy", "Terminal only", "Survivors / unresolved ambiguities"),
                metric("Pair vs endpoint state", "Separate", "Pair closure does not auto-close endpoints"),
            ],
            "meaning": "Human review is last. Frozen mechanical tests first remove ordinary explanations so attention is reserved for genuine terminal survivors.",
            "source": None,
        },
    ]

    return {"stages": stages, "opp": opp, "timing": timing, "foot": foot, "det": det, "post": post, "ctrl": ctrl}


def snapshot():
    proc = process_snapshot()
    stages = proc["stages"]
    current = next((s for s in stages if s["status"] in {"RUNNING", "READY", "PENDING", "BLOCKED"}), stages[-1])

    reg = stage_rows()
    rc = {k: sum(r["status"] == k for r in reg) for k in ("COMPLETE", "READY", "WAITING", "BLOCKED", "ERROR")}

    def val(stage_no, label):
        s = next(x for x in stages if x["number"] == stage_no)
        m = next((m for m in s["metrics"] if m["label"] == label), None)
        return m["value"] if m else "—"

    funnel = [
        {"value": val(1, "Catalogue-level pairs"), "label": "catalogue pairs", "kind": "pairs"},
        {"value": val(1, "Midpoint ≤15 min"), "label": "≤15 min pre-filter", "kind": "pairs"},
        {"value": val(2, "Physical-overlap survivors"), "label": "physical time overlap", "kind": "pairs"},
        {"value": val(3, "Robust true overlap"), "label": "exact common-sky pairs", "kind": "pairs"},
        {"value": val(4, "Native detector candidates"), "label": "residual detections", "kind": "detections"},
        {"value": val(5, "Raw ≤3″ coincidences"), "label": "raw ≤3″ coincidences", "kind": "matches"},
        {"value": "0", "label": "science-positive classifications", "kind": "classifications"},
    ]

    return {
        "dashboard_version": DASHBOARD_VERSION,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_phase": {"number": current["number"], "title": current["title"], "status": current["status"], "question": current["question"]},
        "funnel": funnel,
        "process": stages,
        "match3": match3_snapshot(),
        "registry_counts": rc,
        "registry": reg,
        "terminology": [
            {"term": "Opportunity pair", "meaning": "Two archival exposures worth testing for temporal/spatial overlap."},
            {"term": "Endpoint", "meaning": "One archival exposure/scan participating in an opportunity pair."},
            {"term": "Detector candidate", "meaning": "One frozen-detector residual peak on one endpoint; not a transient."},
            {"term": "Raw coincidence", "meaning": "Two detector peaks close in catalogue coordinates; not source identity."},
            {"term": "Science positive", "meaning": "A terminal two-observatory survivor after frozen adjudication; none classified yet."},
        ],
        "guardrails": [
            "Physical exposure overlap is authoritative; midpoint separation is only a pre-filter.",
            "Raw coordinate coincidence is not source identity.",
            "Catalogue absence is not evidence of transience.",
            "Zero-sigma detector coverage is uninformative, not a clean negative.",
            "Population-control null/excess does not decide individual candidates.",
            "Pair/common-sky closure does not automatically close individual endpoints.",
            "Thresholds are not retuned after outcomes are seen.",
        ],
        "publication": [
            {"name": "Geometry holds", "state": "OPEN", "detail": "41 v052 pairs remain preserved outside the main detector denominator while APPLAUSE/DASCH geometry recovery continues."},
            {"name": "POSS timing-semantics audit", "state": "PENDING", "detail": "Publication provenance must confirm VI/25 timing is authoritative wherever POSS physical timing is claimed; HHH DATE-OBS is identity/date context only."},
            {"name": "11-row vs 236-row reconciliation", "state": "PENDING", "detail": "Needed for publication accounting because the legacy identity-repair cohort is not the wider opportunity universe."},
            {"name": "Full-census claim", "state": "NOT YET", "detail": "Do not claim global completeness until geometry holds, timing provenance and opportunity-universe reconciliation are closed."},
        ],
    }


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Historical Transient Investigation - Process Dashboard</title>
<style>
:root{--bg:#0b0f16;--panel:#121925;--panel2:#172132;--line:#28364c;--text:#eaf0f8;--muted:#93a2b7;--good:#66d69a;--run:#70b7ff;--warn:#e6c569;--bad:#ff8484;--violet:#b59cff;--cyan:#72d5e8;--shadow:0 12px 34px rgba(0,0,0,.22)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0%,rgba(60,110,180,.11),transparent 28%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Arial,sans-serif}header{position:sticky;top:0;z-index:10;background:rgba(11,15,22,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}.head{max-width:1500px;margin:auto;padding:18px 28px;display:flex;gap:20px;align-items:center;justify-content:space-between}h1{font-size:21px;margin:0 0 3px}.subtitle,.muted{color:var(--muted);font-size:12px}.wrap{max-width:1500px;margin:auto;padding:24px 28px 60px}.current{display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:center;padding:18px 20px;border:1px solid #355077;border-radius:14px;background:linear-gradient(100deg,rgba(42,91,150,.20),rgba(21,30,44,.78));box-shadow:var(--shadow)}.current .num{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:#203c60;border:1px solid #4f78a8;font-weight:800}.current h2{font-size:17px;margin:0 0 4px}.current .q{color:#c0ccda;font-size:13px}.badge{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:5px 9px;font-size:11px;font-weight:750;letter-spacing:.035em}.COMPLETE{color:var(--good);border-color:rgba(102,214,154,.38);background:rgba(102,214,154,.07)}.RUNNING{color:var(--run);border-color:rgba(112,183,255,.42);background:rgba(112,183,255,.09)}.READY{color:var(--cyan);border-color:rgba(114,213,232,.35);background:rgba(114,213,232,.07)}.PENDING,.WAITING{color:var(--warn);border-color:rgba(230,197,105,.34);background:rgba(230,197,105,.06)}.BLOCKED,.ERROR{color:var(--bad);border-color:rgba(255,132,132,.35);background:rgba(255,132,132,.07)}.ACTIVE{color:var(--violet);border-color:rgba(181,156,255,.38);background:rgba(181,156,255,.07)}.sectiontitle{display:flex;align-items:end;justify-content:space-between;margin:30px 0 12px}.sectiontitle h2{font-size:18px;margin:0}.sectiontitle p{margin:0;color:var(--muted);font-size:12px}.funnel{display:grid;grid-template-columns:repeat(7,minmax(120px,1fr));gap:8px;overflow-x:auto}.funnel .f{min-width:125px;position:relative;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px}.funnel .f:not(:last-child):after{content:'›';position:absolute;right:-10px;top:27px;color:#647b9b;font-size:22px;z-index:2}.f .v{font-size:22px;font-weight:790}.f .l{font-size:11px;color:var(--muted);margin-top:4px;line-height:1.3}.f .k{font-size:9px;color:#617086;text-transform:uppercase;margin-top:7px;letter-spacing:.07em}.note{margin-top:9px;padding:9px 11px;border-left:3px solid #3e5f88;color:#aebdd0;background:rgba(32,48,70,.33);font-size:12px;border-radius:0 7px 7px 0}.flow{position:relative;margin-top:8px}.flow:before{content:'';position:absolute;left:23px;top:28px;bottom:28px;width:2px;background:linear-gradient(var(--line),#354b6d,var(--line))}.stage{position:relative;margin:0 0 14px 58px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:visible}.stage:before{content:attr(data-num);position:absolute;left:-58px;top:20px;width:46px;height:46px;display:grid;place-items:center;border-radius:50%;background:#172235;border:2px solid #3a4d6a;font-weight:800;color:#dce8f6;z-index:2}.stagehead{padding:16px 18px 13px;display:flex;gap:14px;align-items:flex-start;justify-content:space-between;border-bottom:1px solid rgba(40,54,76,.72)}.stagehead h3{font-size:16px;margin:0 0 4px}.question{font-size:12px;color:#b5c3d4;max-width:900px}.metrics{padding:13px 18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:8px}.metric{background:var(--panel2);border:1px solid #233149;border-radius:9px;padding:10px 11px;min-height:76px}.ml{font-size:10px;text-transform:uppercase;color:#8595aa;letter-spacing:.055em;line-height:1.25}.mv{font-size:20px;font-weight:770;margin:5px 0 2px}.mn{font-size:10px;color:#74859d;line-height:1.25}.metric.good .mv{color:var(--good)}.metric.warn .mv{color:var(--warn)}.metric.accent .mv{color:var(--cyan)}.metric.closed .mv{color:#aab6c5}.meaning{padding:0 18px 14px;font-size:12px;line-height:1.5;color:#aab8c9}.source{padding:0 18px 14px;color:#60738c;font-size:10px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.progressbox{padding:11px 18px 0}.progressmeta{font-size:11px;color:#9eb0c7;margin-bottom:5px}.progress{height:7px;background:#0d1420;border:1px solid #26364d;border-radius:999px;overflow:hidden}.progress>div{height:100%;background:linear-gradient(90deg,#428ce0,#75c0ff)}.branch{margin:0 18px 16px 28px;border:1px solid rgba(181,156,255,.34);border-radius:12px;background:rgba(99,75,145,.09);position:relative}.branch:before{content:'';position:absolute;left:-28px;top:24px;width:27px;height:2px;background:#69588d}.branchhead{padding:12px 14px 7px;display:flex;justify-content:space-between}.branch h4{margin:0;font-size:13px;color:#d9ccff}.branchintro,.branchnote{padding:0 14px 10px;color:#a99fc6;font-size:11px;line-height:1.45}.branch .metrics{padding:4px 14px 10px}.two{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:20px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:16px;box-shadow:var(--shadow)}.panel h3{font-size:15px;margin:0 0 10px}.gloss{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:7px}.glossitem{padding:9px 10px;background:var(--panel2);border-radius:8px;border:1px solid #223047}.glossitem b{display:block;font-size:11px;margin-bottom:3px}.glossitem span{font-size:10px;color:#8797ab;line-height:1.35}.rules{margin:0;padding-left:17px;color:#9cacc0;font-size:11px;line-height:1.55}.pubrow{display:grid;grid-template-columns:170px 90px 1fr;gap:10px;align-items:start;padding:9px 0;border-bottom:1px solid #243147;font-size:11px}.pubrow:last-child{border-bottom:0}.pubrow .name{font-weight:650}.pubrow .detail{color:#8fa0b4;line-height:1.4}details{margin-top:14px;background:var(--panel);border:1px solid var(--line);border-radius:12px}summary{cursor:pointer;padding:13px 15px;font-size:13px;font-weight:680;color:#cbd7e5}.detailbody{padding:0 15px 15px}table{width:100%;border-collapse:collapse;font-size:11px}th,td{padding:7px 8px;border-bottom:1px solid #243147;text-align:left;vertical-align:top}th{color:#8fa0b4;font-size:10px;text-transform:uppercase}code{color:#aecbf1;font-size:10px}.footer{margin-top:14px;color:#66758a;font-size:10px;text-align:right}@media(max-width:900px){.head{padding:15px}.wrap{padding:16px}.current{grid-template-columns:auto 1fr}.current>.badge{grid-column:1/-1;width:max-content}.two{grid-template-columns:1fr}.funnel{grid-template-columns:repeat(7,145px)}.stage{margin-left:48px}.stage:before{left:-49px;width:38px;height:38px}.flow:before{left:18px}}
</style></head>
<body><header><div class="head"><div><h1>Historical Photographic-Plate Transient Investigation</h1><div class="subtitle">Science-process dashboard · local · read-only · auto-refresh 3 s</div></div><div class="badge READY" id="version">dashboard</div></div></header>
<div class="wrap"><div id="app">Loading process state…</div></div>
<script>
function e(x){return String(x??'—').replace(/[&<>\"]/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[s]));}
function mc(m){return `<div class="metric ${e(m.tone||'normal')}"><div class="ml">${e(m.label)}</div><div class="mv">${e(m.value)}</div><div class="mn">${e(m.note||'')}</div></div>`}
function prog(p){if(!p||!p.total)return '';let pc=Math.max(0,Math.min(100,100*(Number(p.current)||0)/Number(p.total)));return `<div class="progressbox"><div class="progressmeta">${e(p.label)} · ${pc.toFixed(1)}%</div><div class="progress"><div style="width:${pc}%"></div></div></div>`}
function br(b){if(!b)return '';return `<div class="branch"><div class="branchhead"><h4>${e(b.title)}</h4><span class="badge ${e(b.status)}">${e(b.status)}</span></div><div class="branchintro">${e(b.intro)}</div><div class="metrics">${(b.metrics||[]).map(mc).join('')}</div><div class="branchnote">${e(b.note)}</div></div>`}
function st(s){return `<section class="stage" data-num="${e(s.number)}"><div class="stagehead"><div><h3>${e(s.title)}</h3><div class="question">${e(s.question)}</div></div><span class="badge ${e(s.status)}">${e(s.status)}</span></div>${prog(s.progress)}<div class="metrics">${(s.metrics||[]).map(mc).join('')}</div><div class="meaning"><b>Interpretation:</b> ${e(s.meaning)}</div>${s.source?`<div class="source">source: ${e(s.source)}</div>`:''}${br(s.branch)}</section>`}
async function go(){try{let d=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());document.getElementById('version').textContent=d.dashboard_version;let rr=d.registry_counts||{};let reg=(d.registry||[]).map(s=>`<tr><td><code>${e(s.id)}</code><div class="muted">${e(s.title)}</div></td><td><span class="badge ${e(s.status)}">${e(s.status)}</span></td><td>${s.network?'network ':''}${s.pixels?'pixels':''}</td></tr>`).join('');let m=d.match3||{};document.getElementById('app').innerHTML=`<section class="current"><div class="num">${e(d.current_phase.number)}</div><div><h2>Current science phase · ${e(d.current_phase.title)}</h2><div class="q">${e(d.current_phase.question)}</div></div><span class="badge ${e(d.current_phase.status)}">${e(d.current_phase.status)}</span></section><div class="note"><b>How to read this:</b> this is a scientific funnel, not a task counter. Units change from exposure <i>pairs</i>, to detector <i>detections</i>, to raw <i>matches</i>. A raw match is never automatically a transient.</div><div class="sectiontitle"><div><h2>Investigation funnel</h2><p>Scale change through the pipeline</p></div></div><div class="funnel">${(d.funnel||[]).map(x=>`<div class="f"><div class="v">${e(x.value)}</div><div class="l">${e(x.label)}</div><div class="k">${e(x.kind)}</div></div>`).join('')}</div><div class="sectiontitle"><div><h2>Science process flow</h2><p>Question → evidence → interpretation → next gate</p></div></div><div class="flow">${(d.process||[]).map(st).join('')}</div><div class="two"><div class="panel"><h3>Terminology</h3><div class="gloss">${(d.terminology||[]).map(x=>`<div class="glossitem"><b>${e(x.term)}</b><span>${e(x.meaning)}</span></div>`).join('')}</div></div><div class="panel"><h3>Scientific guardrails</h3><ul class="rules">${(d.guardrails||[]).map(x=>`<li>${e(x)}</li>`).join('')}</ul></div></div><div class="sectiontitle"><div><h2>Publication / completeness gates</h2><p>Separate from candidate adjudication</p></div></div><div class="panel">${(d.publication||[]).map(x=>`<div class="pubrow"><div class="name">${e(x.name)}</div><div><span class="badge ${x.state==='OPEN'?'ACTIVE':'PENDING'}">${e(x.state)}</span></div><div class="detail">${e(x.detail)}</div></div>`).join('')}</div><details><summary>Method-validation case · Order 11 Match 3</summary><div class="detailbody"><div class="note" style="margin-bottom:10px">Match 3 is retained as a validation example; it is no longer the main dashboard narrative.</div><table><tr><th>Evidence</th><th>State</th></tr><tr><td>Gaia epoch context</td><td>${e(m.gaia)}</td></tr><tr><td>Primary common-reference astrometry</td><td>${e(m.common_astrometry)}</td></tr><tr><td>Sparse-field astrometry</td><td>${e(m.sparse_astrometry)}</td></tr><tr><td>POSS morphology</td><td>${e(m.poss_morph)}</td></tr><tr><td>DASCH morphology</td><td>${e(m.dasch_morph)}</td></tr><tr><td><b>Final pair disposition</b></td><td><b>${e(m.final)}</b></td></tr></table></div></details><details><summary>Automation registry · ${rr.COMPLETE||0} complete · ${rr.READY||0} ready · ${(rr.BLOCKED||0)+(rr.WAITING||0)} blocked/waiting</summary><div class="detailbody"><table><tr><th>Stage</th><th>Status</th><th>Access</th></tr>${reg}</table></div></details><div class="footer">Updated ${e(d.time)} · read-only dashboard</div>`}catch(err){document.getElementById('app').innerHTML=`<div class="panel"><h3>Dashboard read error</h3><code>${e(err)}</code></div>`}}
go();setInterval(go,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            body = json.dumps(snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/" or self.path.startswith("/index"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    url = f"http://{HOST}:{args.port}/"
    srv = ThreadingHTTPServer((HOST, args.port), Handler)
    print("Historical transient process dashboard:", url)
    print("Dashboard version:", DASHBOARD_VERSION)
    print("READ-ONLY: no science, candidate or automation state is mutated.")
    print("Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
