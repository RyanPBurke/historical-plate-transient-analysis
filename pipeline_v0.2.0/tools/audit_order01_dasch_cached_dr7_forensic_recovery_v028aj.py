#!/usr/bin/env python3
"""
ORDER 01 — DASCH cached-DR7 forensic recovery v028aj

Purpose
-------
v028ai returned zero exact rows, which conflicts with the already-completed
v028s/v028t/v028u official-DR7 work. This stage diagnoses and recovers those
cached records without assuming a flat row schema.

Strategy
--------
1. Scan results/work/tools text artifacts for exact string "ai43437".
2. Prioritise artifacts associated with v028r/v028s/v028t/v028u, querycat,
   lightcurve, platephot, and fitted-position adjudication.
3. Recursively walk JSON structures. Any dict/list subtree containing ai43437
   is retained with its JSON path and nearby scalar fields.
4. For CSV/TSV, retain rows containing ai43437 and nearby rows when the file is
   clearly ai43437-scoped.
5. For arbitrary text/MD/log files, retain compact line windows around ai43437.
6. Search recovered scalar dictionaries for candidate ranks, source IDs,
   fitted coordinates, flags, drad values, detections/nondetections, catalogue
   identities, and any coordinates within 30 arcsec of the six preserved DASCH
   endpoints.
7. Deduplicate recovered evidence fragments by normalized content.

This is a forensic evidence-recovery stage only.

NO network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"

OUT_JSON = BASE / "order01_dasch_cached_dr7_forensic_recovery_v028aj.json"
OUT_CSV = BASE / "order01_dasch_cached_dr7_forensic_recovery_v028aj.csv"
OUT_FILES = BASE / "order01_dasch_cached_dr7_forensic_files_v028aj.csv"
OUT_MD = BASE / "ORDER01_DASCH_CACHED_DR7_FORENSIC_RECOVERY_V028AJ.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
MAX_SEP_ARCSEC = 30.0
MAX_FILE_BYTES = 100_000_000
TEXT_SUFFIXES = {".json",".csv",".tsv",".md",".txt",".log"}

PRIORITY_TOKENS = (
    "v028r","v028s","v028t","v028u",
    "querycat","lightcurve","platephot","fitted",
    "official","dr7","dasch"
)

# known official-catalogue keywords from earlier work
INTERESTING_FIELD_TOKENS = (
    "plate","ra","dec","flag","drad","fit","source","atlas","apass",
    "object","catalog","mag","detect","nondetect","blend","defect",
    "neighbor","neighbour","radial","smooth","iso","sxt","match"
)


def read_csv(path, delim=","):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        x = float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def i(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def pick(row, *names, default=None):
    nm = {norm(k): k for k in row}
    for name in names:
        q = norm(name)
        if q in nm:
            return row[nm[q]]
    return default


def angsep_arcsec(ra1, dec1, ra2, dec2):
    r1, r2 = math.radians(ra1), math.radians(ra2)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c))*3600.0


def compact_scalars(obj, prefix="", depth=0, max_depth=4, out=None):
    """
    Flatten scalar fields from a small subtree. Lists of scalars are compacted.
    """
    if out is None:
        out = {}
    if depth > max_depth:
        return out

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[key] = v
            elif isinstance(v, list) and len(v) <= 12 and all(
                isinstance(x, (str, int, float, bool)) or x is None for x in v
            ):
                out[key] = v
            elif isinstance(v, (dict, list)):
                compact_scalars(v, key, depth+1, max_depth, out)
    elif isinstance(obj, list):
        for j, v in enumerate(obj[:12]):
            key = f"{prefix}[{j}]"
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[key] = v
            elif isinstance(v, (dict, list)):
                compact_scalars(v, key, depth+1, max_depth, out)
    return out


def contains_plate(obj):
    try:
        return PLATE in json.dumps(obj, default=str).lower()
    except Exception:
        return PLATE in str(obj).lower()


def context_label(path):
    low = str(path).lower()
    for tok in ("querycat","lightcurve","platephot","fitted"):
        if tok in low:
            return tok
    for tok in ("v028u","v028t","v028s","v028r"):
        if tok in low:
            return tok
    return "other"


def priority_score(path):
    low = str(path).lower()
    score = sum(10 for t in PRIORITY_TOKENS if t in low)
    if PLATE in low:
        score += 20
    return score


def recursive_plate_fragments(obj, path="$", inherited_plate=False, out=None, depth=0):
    """
    Recover dict/list fragments where ai43437 occurs either locally or in an
    ancestor scope. This handles JSON such as:
       {"plate":"ai43437", "rows":[{...},{...}]}
    where child rows do not repeat the plate id.
    """
    if out is None:
        out = []
    if depth > 12:
        return out

    local_plate = contains_plate(obj) if isinstance(obj, (dict, list)) else False
    scope_plate = inherited_plate or local_plate

    if isinstance(obj, dict):
        # Retain useful row-like dictionaries if plate-scoped.
        scalar = compact_scalars(obj, max_depth=2)
        useful = any(
            any(tok in str(k).lower() for tok in INTERESTING_FIELD_TOKENS)
            for k in scalar
        )
        if scope_plate and useful and len(scalar) >= 2:
            out.append({
                "json_path": path,
                "plate_inherited": inherited_plate and not local_plate,
                "scalars": scalar,
            })

        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                # If this dict itself contains plate id, pass plate scope to its children.
                recursive_plate_fragments(v, f"{path}.{k}", scope_plate, out, depth+1)

    elif isinstance(obj, list):
        for j, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                recursive_plate_fragments(v, f"{path}[{j}]", scope_plate, out, depth+1)

    return out


def candidate_coordinate_matches(scalars, science):
    """
    Search all scalar keys for plausible RA/Dec pairs. Returns best candidate
    match. This deliberately accepts more field naming variants than v028ai.
    """
    items = list(scalars.items())
    ras, decs = [], []

    for k, v in items:
        val = f(v)
        if val is None:
            continue
        kl = str(k).lower()
        nk = norm(k)

        # Avoid obvious query-centre/input fields when possible, but keep them
        # labelled so we can diagnose them.
        queryish = any(t in kl for t in ("query","input","target","center","centre","search"))

        if (
            nk.endswith("ra") or ".ra" in kl or "_ra" in kl or
            "rafit" in nk or "fittedra" in nk or nk.startswith("ra")
        ) and 0 <= val < 360:
            ras.append((k, val, queryish))

        if (
            nk.endswith("dec") or ".dec" in kl or "_dec" in kl or
            "decfit" in nk or "fitteddec" in nk or nk.startswith("dec")
        ) and -90 <= val <= 90:
            decs.append((k, val, queryish))

    matches = []
    for rk, ra, rq in ras:
        for dk, dec, dq in decs:
            # Prefer fields with similar path prefixes.
            rp = str(rk).rsplit(".", 1)[0]
            dp = str(dk).rsplit(".", 1)[0]
            prefix_bonus = 0 if rp == dp else 1
            for rank, s in science.items():
                sep = angsep_arcsec(s["ra"], s["dec"], ra, dec)
                matches.append({
                    "rank": rank,
                    "sep_arcsec": sep,
                    "ra": ra,
                    "dec": dec,
                    "ra_key": rk,
                    "dec_key": dk,
                    "queryish": bool(rq or dq),
                    "prefix_penalty": prefix_bonus,
                })

    if not matches:
        return None

    matches.sort(key=lambda x: (
        x["sep_arcsec"],
        x["queryish"],
        x["prefix_penalty"]
    ))
    return matches[0]


def identify_rank_from_scalars(scalars):
    for k, v in scalars.items():
        kl = str(k).lower()
        if "strict_rank" in kl or kl.endswith(".rank") or kl == "rank":
            rv = i(v)
            if rv in RANKS:
                return rv
    return None


def fragment_signature(rec):
    # Normalize away source-file/path duplication.
    core = {
        "context": rec.get("context"),
        "rank_hint": rec.get("rank_hint"),
        "best_rank": rec.get("best_rank"),
        "best_sep_arcsec": None if rec.get("best_sep_arcsec") is None
            else round(float(rec["best_sep_arcsec"]), 4),
        "scalars": rec.get("interesting_scalars"),
    }
    return json.dumps(core, sort_keys=True, default=str)


def main():
    print("="*128)
    print("ORDER 01 — DASCH CACHED-DR7 FORENSIC RECOVERY v028aj")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE, STRICT, DASCH_NATIVE):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set") != []:
        raise RuntimeError("Order-01 closure guard mismatch")

    strict_rows = read_csv(STRICT)
    native = read_csv(DASCH_NATIVE)
    strict = {i(r["strict_rank"]): r for r in strict_rows if i(r["strict_rank"]) in RANKS}
    if sorted(strict) != RANKS:
        raise RuntimeError("strict-rank guard mismatch")

    science = {}
    for rank in RANKS:
        sr = strict[rank]
        tile = str(pick(sr, "dasch_tile_id"))
        idx = i(pick(sr, "dasch_candidate_index", "dasch_index", "dasch_native_candidate_index"))
        q = [r for r in native
             if str(r.get("tile_id","")) == tile and i(r.get("candidate_index")) == idx]
        if len(q) != 1:
            raise RuntimeError(f"#{rank}: science row resolution failed ({len(q)})")
        nr = q[0]
        science[rank] = {
            "ra": f(nr["ra_deg"]),
            "dec": f(nr["dec_deg"]),
            "tile_id": tile,
            "candidate_index": idx,
        }

    # Scan text artifacts.
    files = []
    for top in (ROOT/"results", ROOT/"work", ROOT/"tools"):
        if not top.exists():
            continue
        for p in top.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if p.name in {OUT_JSON.name, OUT_CSV.name, OUT_FILES.name, OUT_MD.name}:
                continue
            try:
                size = p.stat().st_size
            except Exception:
                continue
            if size > MAX_FILE_BYTES:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            low = text.lower()
            if PLATE not in low:
                continue
            files.append({
                "path": p,
                "relative_path": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                "size_bytes": size,
                "priority": priority_score(p),
                "context": context_label(p),
                "plate_occurrences": low.count(PLATE),
            })

    files.sort(key=lambda r: (-r["priority"], r["relative_path"]))
    print(f"Artifacts containing exact '{PLATE}': {len(files)}")

    recovered = []
    text_windows = []

    for file_rec in files:
        p = file_rec["path"]
        ctx = file_rec["context"]
        suf = p.suffix.lower()

        if suf == ".json":
            try:
                obj = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                obj = None
            if obj is not None:
                frags = recursive_plate_fragments(obj)
                for frag in frags:
                    scalars = frag["scalars"]
                    rank_hint = identify_rank_from_scalars(scalars)
                    best = candidate_coordinate_matches(scalars, science)

                    interesting = {}
                    for k, v in scalars.items():
                        kl = str(k).lower()
                        if (
                            PLATE in str(v).lower()
                            or any(tok in kl for tok in INTERESTING_FIELD_TOKENS)
                            or (rank_hint is not None and "rank" in kl)
                        ):
                            interesting[k] = v
                        if len(interesting) >= 60:
                            break

                    recovered.append({
                        "source_file": file_rec["relative_path"],
                        "context": ctx,
                        "json_path": frag["json_path"],
                        "plate_inherited": frag["plate_inherited"],
                        "rank_hint": rank_hint,
                        "best_rank": None if best is None else best["rank"],
                        "best_sep_arcsec": None if best is None else best["sep_arcsec"],
                        "best_ra_deg": None if best is None else best["ra"],
                        "best_dec_deg": None if best is None else best["dec"],
                        "best_ra_field": None if best is None else best["ra_key"],
                        "best_dec_field": None if best is None else best["dec_key"],
                        "best_coord_queryish": None if best is None else best["queryish"],
                        "interesting_scalars": interesting,
                    })

        elif suf in (".csv", ".tsv"):
            try:
                rows = read_csv(p, "\t" if suf == ".tsv" else ",")
            except Exception:
                rows = []
            file_plate_scoped = PLATE in p.name.lower()
            for rn, row in enumerate(rows):
                row_text = json.dumps(row, default=str).lower()
                if PLATE not in row_text and not file_plate_scoped:
                    continue
                rank_hint = identify_rank_from_scalars(row)
                best = candidate_coordinate_matches(row, science)
                interesting = {
                    k: v for k, v in row.items()
                    if (
                        PLATE in str(v).lower()
                        or any(tok in str(k).lower() for tok in INTERESTING_FIELD_TOKENS)
                        or "rank" in str(k).lower()
                    )
                }
                recovered.append({
                    "source_file": file_rec["relative_path"],
                    "context": ctx,
                    "json_path": f"ROW[{rn}]",
                    "plate_inherited": bool(file_plate_scoped and PLATE not in row_text),
                    "rank_hint": rank_hint,
                    "best_rank": None if best is None else best["rank"],
                    "best_sep_arcsec": None if best is None else best["sep_arcsec"],
                    "best_ra_deg": None if best is None else best["ra"],
                    "best_dec_deg": None if best is None else best["dec"],
                    "best_ra_field": None if best is None else best["ra_key"],
                    "best_dec_field": None if best is None else best["dec_key"],
                    "best_coord_queryish": None if best is None else best["queryish"],
                    "interesting_scalars": interesting,
                })

        else:
            # Textual line windows around exact plate string.
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                lines = []
            for ln, line in enumerate(lines):
                if PLATE not in line.lower():
                    continue
                a = max(0, ln-3)
                b = min(len(lines), ln+4)
                window = "\n".join(lines[a:b])
                text_windows.append({
                    "source_file": file_rec["relative_path"],
                    "context": ctx,
                    "line_start": a+1,
                    "line_end": b,
                    "window": window[:8000],
                })

    # Keep only useful fragments: exact rank hint OR coordinate within 30" OR
    # known prior-stage context carrying official DR7 material.
    useful = []
    for r in recovered:
        coord_close = (
            r["best_sep_arcsec"] is not None and
            float(r["best_sep_arcsec"]) <= MAX_SEP_ARCSEC and
            not bool(r["best_coord_queryish"])
        )
        prior_ctx = r["context"] in {"v028s","v028t","v028u","querycat","lightcurve","platephot","fitted"}
        if r["rank_hint"] in RANKS or coord_close or prior_ctx:
            useful.append(r)

    # Deduplicate.
    dedup = {}
    for r in useful:
        sig = fragment_signature(r)
        if sig not in dedup:
            rr = dict(r)
            rr["duplicate_count"] = 1
            rr["all_source_files"] = [r["source_file"]]
            dedup[sig] = rr
        else:
            dedup[sig]["duplicate_count"] += 1
            if r["source_file"] not in dedup[sig]["all_source_files"]:
                dedup[sig]["all_source_files"].append(r["source_file"])

    unique = list(dedup.values())

    # Summarize per rank.
    per_rank = {}
    for rank in RANKS:
        hits = []
        for r in unique:
            rank_hit = r["rank_hint"] == rank
            coord_hit = (
                r["best_rank"] == rank and
                r["best_sep_arcsec"] is not None and
                r["best_sep_arcsec"] <= MAX_SEP_ARCSEC and
                not bool(r["best_coord_queryish"])
            )
            if rank_hit or coord_hit:
                hits.append(r)
        hits.sort(key=lambda r: (
            0 if r["rank_hint"] == rank else 1,
            999999 if r["best_sep_arcsec"] is None else r["best_sep_arcsec"],
            r["source_file"],
        ))
        per_rank[rank] = hits[:40]

    print(f"Recovered plate-scoped structural fragments: {len(recovered)}")
    print(f"Useful unique fragments after deduplication: {len(unique)}")
    print(f"Text windows around ai43437: {len(text_windows)}")

    print("\nPer-rank forensic recovery:")
    for rank in RANKS:
        hits = per_rank[rank]
        print(f"  #{rank}: unique relevant fragments={len(hits)}")
        for h in hits[:5]:
            sep = h["best_sep_arcsec"]
            sep_s = "n/a" if sep is None else f"{sep:.3f}\""
            print(
                f"       {h['context']:10s} rankHint={h['rank_hint']} "
                f"coordRank={h['best_rank']} sep={sep_s} "
                f"file={h['source_file']}"
            )

    file_rows = [{
        "relative_path": r["relative_path"],
        "size_bytes": r["size_bytes"],
        "priority": r["priority"],
        "context": r["context"],
        "plate_occurrences": r["plate_occurrences"],
    } for r in files]

    flat_rows = []
    for rank in RANKS:
        for h in per_rank[rank]:
            flat_rows.append({
                "strict_rank": rank,
                "source_file": h["source_file"],
                "context": h["context"],
                "json_path": h["json_path"],
                "rank_hint": h["rank_hint"],
                "best_rank": h["best_rank"],
                "best_sep_arcsec": h["best_sep_arcsec"],
                "best_ra_deg": h["best_ra_deg"],
                "best_dec_deg": h["best_dec_deg"],
                "best_ra_field": h["best_ra_field"],
                "best_dec_field": h["best_dec_field"],
                "best_coord_queryish": h["best_coord_queryish"],
                "duplicate_count": h["duplicate_count"],
                "all_source_files": ";".join(h["all_source_files"]),
                "interesting_scalars_json": json.dumps(
                    h["interesting_scalars"], sort_keys=True, default=str
                ),
            })

    payload = {
        "stage": "ORDER01_DASCH_CACHED_DR7_FORENSIC_RECOVERY_V028AJ",
        "plate": PLATE,
        "ranks": RANKS,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "nested_plate_scope_supported": True,
            "flat_row_assumption_removed": True,
            "queryish_coordinates_flagged": True,
        },
        "artifacts_containing_plate": len(files),
        "recovered_structural_fragment_count": len(recovered),
        "useful_unique_fragment_count": len(unique),
        "text_window_count": len(text_windows),
        "per_rank": {str(k): v for k, v in per_rank.items()},
        "text_windows": text_windows[:200],
        "interpretive_boundary": (
            "v028aj is a forensic cache-recovery stage created because v028ai's "
            "flat-schema assumptions produced a false zero-row result. Recovered "
            "fragments are evidence locations only; no DASCH endpoint is adjudicated "
            "or mutated here."
        ),
    }

    write_json(OUT_JSON, payload)
    fields = [
        "strict_rank","source_file","context","json_path","rank_hint",
        "best_rank","best_sep_arcsec","best_ra_deg","best_dec_deg",
        "best_ra_field","best_dec_field","best_coord_queryish",
        "duplicate_count","all_source_files","interesting_scalars_json"
    ]
    write_csv(OUT_CSV, flat_rows, fields)
    write_csv(
        OUT_FILES,
        file_rows,
        ["relative_path","size_bytes","priority","context","plate_occurrences"]
    )

    md = [
        "# ORDER 01 — DASCH Cached-DR7 Forensic Recovery v028aj","",
        "## Why this stage exists","",
        "v028ai returned zero rows because it assumed plate identity and source coordinates "
        "would coexist in one flat parsed row. Earlier v028s/v028t/v028u work already "
        "demonstrated cached ai43437 official rows, so a nested forensic recovery was required.","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No endpoint state was changed.","",
        f"Artifacts containing exact `{PLATE}`: **{len(files)}**.",
        f"Recovered structural fragments: **{len(recovered)}**.",
        f"Useful unique fragments after deduplication: **{len(unique)}**.","",
        "## Per-rank recovered fragments","",
        "| rank | recovered relevant fragments |",
        "|---:|---:|"
    ]
    for rank in RANKS:
        md.append(f"| #{rank} | {len(per_rank[rank])} |")
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_FILES}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
