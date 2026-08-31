#!/usr/bin/env python3
"""
ORDER 01 — DASCH historical-flag provenance audit v028at

Purpose
-------
v028ar-r1/v028as show that all six preserved DASCH endpoints are centered,
same-polarity, amplitude-normalized stellar-like images.

Earlier stages nevertheless recorded DASCH quality/defect/blend warnings,
especially for rank #25. Before those warnings are used in endpoint adjudication,
v028at traces them to the exact source object/row and coordinate.

Questions
---------
1. Which v028i-era files/scripts generated the previously quoted flags?
2. Were those flags attached to:
     a) the frozen native science endpoint itself,
     b) a DR7 official source row near the endpoint,
     c) a catalogue/reference source tens of arcseconds away,
     d) a plate-level record,
     e) an unresolved/ambiguous context?
3. For any flag-bearing object with coordinates, what is its angular separation
   from the frozen DASCH science coordinate?
4. Do the exact v028r raw platephot rows contain the same numerical flags?

This is provenance analysis only.

NO network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"
TOOLS = ROOT / "tools"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_historical_flag_provenance_v028at.json"
OUT_CSV = BASE / "order01_dasch_historical_flag_provenance_v028at.csv"
OUT_TXT = BASE / "ORDER01_DASCH_HISTORICAL_FLAG_PROVENANCE_V028AT.txt"
OUT_MD = BASE / "ORDER01_DASCH_HISTORICAL_FLAG_PROVENANCE_V028AT.md"

RANKS = [10,24,25,26,29,30]

# Previously reported stage-v028i composite/direct/photometric values from the
# frozen audit narrative. These are search anchors only; v028at determines what
# object they actually belonged to.
KNOWN_COMPOSITE = {
    10: 0x00003800,
    25: 0x06884000,
    26: 0x00003000,
    30: 0x10001800,
}

FLAG_WORDS = (
    "CLOSE_TO_LIMITING",
    "LARGE_ISO_RMS",
    "LARGE_LOCAL_SMOOTH_RMS",
    "BLEND",
    "LARGE_DRAD",
    "NEIGHBORS",
    "RADIAL_BIN_9",
    "SUSPECTED_DEFECT",
    "SXT_BLEND",
    "UNCERTAIN_CATALOG_MAG",
    "LARGE_SMOOTHING_CORRECTION",
)

SEARCH_FILE_TOKENS = ("v028i", "flag", "dasch")


def read_csv_file(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


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
        s = str(v).strip()
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(float(s))
    except Exception:
        return default


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def pick(row, *names):
    nm = {norm(k): k for k in row}
    for name in names:
        q = norm(name)
        if q in nm:
            return row[nm[q]]
    return None


def angsep_arcsec(ra1, dec1, ra2, dec2):
    r1, r2 = math.radians(ra1), math.radians(ra2)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c))*3600.0


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def resolve_science():
    strict = read_csv_file(STRICT)
    native = read_csv_file(DASCH_NATIVE)
    sr = {i(r["strict_rank"]): r for r in strict if i(r["strict_rank"]) in RANKS}
    out = {}
    for rank in RANKS:
        r = sr[rank]
        tid = str(r["dasch_tile_id"])
        idx = i(r.get("dasch_candidate_index"))
        q = [
            x for x in native
            if str(x.get("tile_id","")) == tid
            and i(x.get("candidate_index")) == idx
        ]
        if len(q) != 1:
            raise RuntimeError(f"#{rank}: science row resolution failed ({len(q)})")
        n = q[0]
        out[rank] = {
            "ra_deg": f(n["ra_deg"]),
            "dec_deg": f(n["dec_deg"]),
            "tile_id": tid,
            "candidate_index": idx,
        }
    return out


def parse_platephot(path):
    obj = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(obj, list) or not obj or not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{path.name}: expected JSON list[str]")
    return list(csv.DictReader(io.StringIO("\n".join(obj))))


def recursive_dicts(obj, path="$", out=None, depth=0):
    if out is None:
        out = []
    if depth > 14:
        return out
    if isinstance(obj, dict):
        out.append((path, obj))
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                recursive_dicts(v, f"{path}.{k}", out, depth+1)
    elif isinstance(obj, list):
        for j, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                recursive_dicts(v, f"{path}[{j}]", out, depth+1)
    return out


def rank_hint_from_dict(d):
    for k, v in d.items():
        kl = str(k).lower()
        if "strict_rank" in kl or kl in ("rank", "candidate_rank"):
            rv = i(v)
            if rv in RANKS:
                return rv
    return None


def coord_pairs(d):
    nm = {norm(k): k for k in d}
    pairs = []
    candidates = (
        ("ra_deg","dec_deg"),
        ("fit_ra_deg","fit_dec_deg"),
        ("official_fit_ra_deg","official_fit_dec_deg"),
        ("catalog_ra_deg","catalog_dec_deg"),
        ("official_catalog_ra_deg","official_catalog_dec_deg"),
        ("frozen_dasch_ra_deg","frozen_dasch_dec_deg"),
        ("dasch_ra_deg","dasch_dec_deg"),
        ("ra","dec"),
    )
    for rn, dn in candidates:
        rk, dk = nm.get(norm(rn)), nm.get(norm(dn))
        if rk is None or dk is None:
            continue
        ra, dec = f(d[rk]), f(d[dk])
        if ra is not None and dec is not None and 0 <= ra < 360 and -90 <= dec <= 90:
            pairs.append((str(rk), str(dk), ra, dec))
    # dedup
    seen = set()
    out = []
    for p in pairs:
        sig = (p[0], p[1], round(p[2],9), round(p[3],9))
        if sig not in seen:
            seen.add(sig)
            out.append(p)
    return out


def flagish_fields(d):
    out = {}
    for k, v in d.items():
        kl = str(k).lower()
        sv = str(v)
        if (
            "flag" in kl or "defect" in kl or "blend" in kl or
            "drad" in kl or any(word.lower() in sv.lower() for word in FLAG_WORDS)
        ):
            out[str(k)] = v
    return out


def classify_context(path, d, sep):
    low = (path + " " + " ".join(map(str, d.keys()))).lower()
    if "plate" in low and not any(x in low for x in ("source","row","candidate","science","nearest")):
        return "PLATE_LEVEL_OR_GLOBAL"
    if "nearest" in low or "official" in low or "platephot" in low:
        if sep is not None and sep <= 10:
            return "OFFICIAL_SOURCE_NEAR_SCIENCE"
        if sep is not None:
            return "OFFICIAL_OR_REFERENCE_SOURCE_DISPLACED_FROM_SCIENCE"
        return "OFFICIAL_OR_REFERENCE_SOURCE_NO_COORDINATE"
    if "candidate" in low or "science" in low or "strict_rank" in low:
        if sep is not None and sep <= 3:
            return "SCIENCE_ENDPOINT_ASSOCIATED"
        return "SCIENCE_CONTEXT_BUT_COORDINATE_AMBIGUOUS"
    return "AMBIGUOUS_CONTEXT"


def candidate_files():
    found = []
    roots = (BASE, WORK, TOOLS)
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            low = p.name.lower()
            if p.suffix.lower() not in (".json",".csv",".tsv",".md",".txt",".py"):
                continue
            if "v028i" in low or ("flag" in low and "dasch" in low):
                found.append(p)
    # Also include the likely source script even if naming differs but content says v028i.
    for p in TOOLS.rglob("*.py") if TOOLS.exists() else []:
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:20000].lower()
        except Exception:
            continue
        if "v028i" in head and "dasch" in head and p not in found:
            found.append(p)
    return sorted(set(found))


def scan_json(path, science):
    hits = []
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return hits
    for jpath, d in recursive_dicts(obj):
        ff = flagish_fields(d)
        if not ff:
            continue
        rh = rank_hint_from_dict(d)
        ranks = [rh] if rh in RANKS else []
        # If no explicit rank, search flag values for known composite anchors.
        if not ranks:
            blob = json.dumps(d, default=str).lower()
            for rank, val in KNOWN_COMPOSITE.items():
                if str(val) in blob or hex(val).lower() in blob:
                    ranks.append(rank)
        if not ranks:
            continue

        cps = coord_pairs(d)
        for rank in sorted(set(ranks)):
            best_sep = None
            best_cp = None
            for rk, dk, ra, dec in cps:
                sep = angsep_arcsec(
                    science[rank]["ra_deg"], science[rank]["dec_deg"], ra, dec
                )
                if best_sep is None or sep < best_sep:
                    best_sep = sep
                    best_cp = (rk, dk, ra, dec)

            hits.append({
                "strict_rank": rank,
                "source_file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "source_kind": "JSON",
                "object_path": jpath,
                "flag_fields_json": json.dumps(ff, sort_keys=True, default=str),
                "coordinate_fields": None if best_cp is None else f"{best_cp[0]}/{best_cp[1]}",
                "object_ra_deg": None if best_cp is None else best_cp[2],
                "object_dec_deg": None if best_cp is None else best_cp[3],
                "science_sep_arcsec": best_sep,
                "context_classification": classify_context(jpath, d, best_sep),
            })
    return hits


def scan_csv(path, science):
    hits = []
    try:
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter=delim))
    except Exception:
        return hits

    for idx, d in enumerate(rows):
        ff = flagish_fields(d)
        if not ff:
            continue
        rh = rank_hint_from_dict(d)
        if rh not in RANKS:
            continue
        cps = coord_pairs(d)
        best_sep = None
        best_cp = None
        for rk, dk, ra, dec in cps:
            sep = angsep_arcsec(
                science[rh]["ra_deg"], science[rh]["dec_deg"], ra, dec
            )
            if best_sep is None or sep < best_sep:
                best_sep = sep
                best_cp = (rk, dk, ra, dec)

        hits.append({
            "strict_rank": rh,
            "source_file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "source_kind": "CSV_OR_TSV",
            "object_path": f"ROW[{idx}]",
            "flag_fields_json": json.dumps(ff, sort_keys=True, default=str),
            "coordinate_fields": None if best_cp is None else f"{best_cp[0]}/{best_cp[1]}",
            "object_ra_deg": None if best_cp is None else best_cp[2],
            "object_dec_deg": None if best_cp is None else best_cp[3],
            "science_sep_arcsec": best_sep,
            "context_classification": classify_context(f"ROW[{idx}]", d, best_sep),
        })
    return hits


def source_snippets(path):
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    hit = set()
    for idx, line in enumerate(lines):
        low = line.lower()
        if (
            "flag" in low or "defect" in low or "blend" in low or
            "drad" in low or "v028i" in low
        ):
            for j in range(max(0, idx-7), min(len(lines), idx+12)):
                hit.add(j)
    if not hit:
        return []
    ranges = []
    start = prev = None
    for j in sorted(hit):
        if start is None:
            start = prev = j
        elif j == prev + 1:
            prev = j
        else:
            ranges.append((start, prev))
            start = prev = j
    ranges.append((start, prev))
    return [
        {
            "start_line": a+1,
            "end_line": b+1,
            "text": "\n".join(f"{n+1:05d}: {lines[n]}" for n in range(a,b+1))
        }
        for a,b in ranges
    ]


def main():
    print("="*128)
    print("ORDER 01 — DASCH HISTORICAL-FLAG PROVENANCE AUDIT v028at")
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

    science = resolve_science()
    files = candidate_files()
    print(f"Candidate v028i/flag provenance files: {len(files)}")
    for p in files:
        print("  " + str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p))

    hits = []
    snippets = []

    for p in files:
        suf = p.suffix.lower()
        if suf == ".json":
            hits.extend(scan_json(p, science))
        elif suf in (".csv",".tsv"):
            hits.extend(scan_csv(p, science))
        elif suf == ".py":
            sn = source_snippets(p)
            if sn:
                snippets.append({
                    "source_file": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                    "snippets": sn,
                })

    # Exact raw-v028r comparison for every rank.
    raw_matches = []
    for rank in RANKS:
        p = RAW_DIR / f"ai43437_sol0_rank{rank}_apass_platephot.json"
        if not p.is_file():
            continue
        rows = parse_platephot(p)
        for ridx, row in enumerate(rows, start=1):
            ra, dec = f(row.get("ra_deg")), f(row.get("dec_deg"))
            sep = None if None in (ra,dec) else angsep_arcsec(
                science[rank]["ra_deg"], science[rank]["dec_deg"], ra, dec
            )
            raw_matches.append({
                "strict_rank": rank,
                "raw_row_number": ridx,
                "science_sep_arcsec": sep,
                "aflags": i(row.get("aflags")),
                "a2flags": i(row.get("a2flags")),
                "bflags": i(row.get("bflags")),
                "b2flags": i(row.get("b2flags")),
                "drad_rms2": f(row.get("drad_rms2")),
                "ra_deg": ra,
                "dec_deg": dec,
            })

    # Print best/most informative provenance per rank.
    print("\nPer-rank historical flag provenance:")
    summaries = []
    for rank in RANKS:
        rh = [h for h in hits if h["strict_rank"] == rank]
        rh.sort(key=lambda h: (
            h["science_sep_arcsec"] is None,
            float("inf") if h["science_sep_arcsec"] is None else h["science_sep_arcsec"],
            h["source_file"],
        ))
        nearest_raw = sorted(
            [r for r in raw_matches if r["strict_rank"] == rank and r["science_sep_arcsec"] is not None],
            key=lambda r:r["science_sep_arcsec"]
        )

        print(f"\n  #{rank}: provenance hits={len(rh)}")
        for h in rh[:10]:
            sep = "n/a" if h["science_sep_arcsec"] is None else f"{h['science_sep_arcsec']:.3f}\""
            print(
                f"    {h['context_classification']} sep={sep} "
                f"{h['source_file']} @ {h['object_path']}"
            )
            print(f"      {h['flag_fields_json'][:1600]}")

        if nearest_raw:
            rr = nearest_raw[0]
            print(
                f"    nearest exact raw v028r row: sep={rr['science_sep_arcsec']:.3f}\" "
                f"aflags={rr['aflags']} bflags={rr['bflags']} drad={rr['drad_rms2']}"
            )

        near_science_flag_hits = [
            h for h in rh
            if h["science_sep_arcsec"] is not None and h["science_sep_arcsec"] <= 3.0
        ]
        summaries.append({
            "strict_rank": rank,
            "known_composite_anchor_decimal": KNOWN_COMPOSITE.get(rank),
            "known_composite_anchor_hex":
                None if rank not in KNOWN_COMPOSITE else hex(KNOWN_COMPOSITE[rank]),
            "provenance_hit_count": len(rh),
            "flag_bearing_hits_within3arcsec_science": len(near_science_flag_hits),
            "nearest_flag_bearing_hit_sep_arcsec":
                None if not rh or rh[0]["science_sep_arcsec"] is None else rh[0]["science_sep_arcsec"],
            "nearest_flag_bearing_context":
                None if not rh else rh[0]["context_classification"],
            "nearest_raw_v028r_source_sep_arcsec":
                None if not nearest_raw else nearest_raw[0]["science_sep_arcsec"],
            "nearest_raw_v028r_aflags":
                None if not nearest_raw else nearest_raw[0]["aflags"],
            "nearest_raw_v028r_bflags":
                None if not nearest_raw else nearest_raw[0]["bflags"],
            "nearest_raw_v028r_drad_rms2":
                None if not nearest_raw else nearest_raw[0]["drad_rms2"],
        })

    payload = {
        "stage": "ORDER01_DASCH_HISTORICAL_FLAG_PROVENANCE_V028AT",
        "ranks": RANKS,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "historical_flags_not_assumed_to_belong_to_science_endpoint": True,
            "coordinate_separation_required_when_available": True,
        },
        "known_composite_search_anchors": {
            str(k): {"decimal":v, "hex":hex(v)} for k,v in KNOWN_COMPOSITE.items()
        },
        "candidate_files": [
            str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
            for p in files
        ],
        "summaries": summaries,
        "provenance_hits": hits,
        "exact_raw_v028r_rows": raw_matches,
        "source_snippets": snippets,
        "interpretive_boundary": (
            "v028at traces historical DASCH flags to their source objects. A quality "
            "flag on an official/reference source displaced from the frozen native "
            "science coordinate must not be used as if it directly characterized "
            "the uncatalogued native science feature."
        ),
    }
    write_json(OUT_JSON, payload)
    write_csv(OUT_CSV, summaries, list(summaries[0]))

    txt = [
        "ORDER 01 — DASCH historical-flag provenance v028at\n",
        "=== SOURCE SNIPPETS ===\n",
    ]
    for block in snippets:
        txt.append(f"\n## {block['source_file']}\n")
        for sn in block["snippets"]:
            txt.append(f"\n--- lines {sn['start_line']}-{sn['end_line']} ---\n")
            txt.append(sn["text"])
            txt.append("\n")
    txt.append("\n=== PROVENANCE HITS ===\n")
    txt.append(json.dumps(hits, indent=2, sort_keys=True, default=str))
    OUT_TXT.write_text("\n".join(txt), encoding="utf-8")

    md = [
        "# ORDER 01 — DASCH Historical-Flag Provenance v028at","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No endpoint state was changed.",
        "- Earlier flag labels are not assumed to characterize a science endpoint unless their provenance supports that association.","",
        "## Per-rank provenance summary","",
        "| rank | flag hits | flag hits <=3″ | nearest flag-hit separation | nearest context | nearest raw DR7 source |",
        "|---:|---:|---:|---:|---|---:|"
    ]
    for r in summaries:
        fh = r["nearest_flag_bearing_hit_sep_arcsec"]
        rr = r["nearest_raw_v028r_source_sep_arcsec"]
        md.append(
            f"| #{r['strict_rank']} | {r['provenance_hit_count']} | "
            f"{r['flag_bearing_hits_within3arcsec_science']} | "
            f"{'—' if fh is None else f'{fh:.3f}″'} | "
            f"{r['nearest_flag_bearing_context'] or '—'} | "
            f"{'—' if rr is None else f'{rr:.3f}″'} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_TXT}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
