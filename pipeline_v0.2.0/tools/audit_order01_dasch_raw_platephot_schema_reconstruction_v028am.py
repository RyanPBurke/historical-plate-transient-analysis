#!/usr/bin/env python3
"""
ORDER 01 — raw DASCH platephot schema + table reconstruction audit v028am

Why this stage exists
---------------------
v028al successfully opened all six rank-scoped ai43437 platephot caches but found
no recognizable row-dictionary RA/Dec fields. That is a parser/schema result,
NOT evidence that the raw platephot responses contain no nearby sources.

Earlier v028r work demonstrably extracted official fitted positions from these
same rank-scoped caches, so v028am inspects the raw response structure and
reconstructs table-oriented JSON representations such as:

    {"fields": [...], "data": [[...], ...]}
    {"columns": [...], "rows": [[...], ...]}
    {"schema": {"fields": [...]}, "data": [...]}

It then searches reconstructed rows for explicit source/fitted coordinates and
measures their angular distance from each preserved DASCH science endpoint.

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
WORK = ROOT / "work" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
DASCH_NATIVE = BASE / "order01_dasch_native_candidates.csv"
RAW_DIR = WORK / "official_dasch_platephot_v028r"

OUT_JSON = BASE / "order01_dasch_raw_platephot_schema_reconstruction_v028am.json"
OUT_ROWS = BASE / "order01_dasch_raw_platephot_reconstructed_rows_v028am.csv"
OUT_SCHEMA = BASE / "order01_dasch_raw_platephot_schema_v028am.csv"
OUT_MD = BASE / "ORDER01_DASCH_RAW_PLATEPHOT_SCHEMA_RECONSTRUCTION_V028AM.md"

PLATE = "ai43437"
RANKS = [10,24,25,26,29,30]
KEEP_NEAREST = 20
MAX_REPORT_SEP_ARCSEC = 180.0

HEADER_KEYS = (
    "fields","columns","colnames","column_names","columnnames","names",
    "schema","metadata","meta"
)
ROW_KEYS = (
    "data","rows","results","records","values","table"
)

BAD_COORD_TOKENS = (
    "query","input","target","center","centre","search","requested","cone",
    "science","candidate"
)

RA_NAMES = (
    "official_fit_ra_deg","fit_ra_deg","ra_fit_deg","fitted_ra_deg",
    "official_fit_ra","fit_ra","ra_fit","fitted_ra",
    "ra_deg","radeg","raj2000","ra2000","ra"
)
DEC_NAMES = (
    "official_fit_dec_deg","fit_dec_deg","dec_fit_deg","fitted_dec_deg",
    "official_fit_dec","fit_dec","dec_fit","fitted_dec",
    "dec_deg","decdeg","dej2000","dec2000","dec"
)

INTERESTING = (
    "flag","drad","source","atlas","apass","object","catalog","mag","flux",
    "fwhm","ellip","blend","defect","neighbor","neighbour","radial","status",
    "detect","nondetect","image","iso","x","y"
)


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


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


def resolve_science(strict_rows, native_rows):
    strict = {i(r["strict_rank"]): r for r in strict_rows if i(r["strict_rank"]) in RANKS}
    if sorted(strict) != RANKS:
        raise RuntimeError("strict-rank guard mismatch")

    out = {}
    for rank in RANKS:
        sr = strict[rank]
        tile = str(pick(sr, "dasch_tile_id"))
        idx = i(pick(sr, "dasch_candidate_index", "dasch_index", "dasch_native_candidate_index"))
        q = [
            r for r in native_rows
            if str(r.get("tile_id","")) == tile and i(r.get("candidate_index")) == idx
        ]
        if len(q) != 1:
            raise RuntimeError(f"#{rank}: DASCH science row resolution failed ({len(q)})")
        nr = q[0]
        out[rank] = {
            "ra": f(nr["ra_deg"]),
            "dec": f(nr["dec_deg"]),
            "tile_id": tile,
            "candidate_index": idx,
        }
    return out


def walk(obj, path="$", depth=0, out=None):
    if out is None:
        out = []
    if depth > 16:
        return out
    out.append((path, obj))
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                walk(v, f"{path}.{k}", depth+1, out)
    elif isinstance(obj, list):
        for j, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                walk(v, f"{path}[{j}]", depth+1, out)
    return out


def field_names_from(value):
    """
    Convert common field/schema encodings into an ordered list of field names.
    """
    if isinstance(value, list):
        if all(isinstance(x, str) for x in value):
            return [str(x) for x in value]
        if all(isinstance(x, dict) for x in value):
            names = []
            for x in value:
                nm = (
                    x.get("name") or x.get("field") or x.get("column") or
                    x.get("key") or x.get("id") or x.get("label")
                )
                if nm is None:
                    return None
                names.append(str(nm))
            return names

    if isinstance(value, dict):
        # Apache-arrow-ish or nested schema object.
        for k in ("fields","columns","names","colnames","column_names"):
            if k in value:
                q = field_names_from(value[k])
                if q:
                    return q
        # Mapping field-name -> type.
        if value and all(isinstance(k, str) for k in value):
            if all(not isinstance(v, (list, dict)) for v in value.values()):
                return list(value.keys())
    return None


def row_arrays_from(value):
    """
    Return list-of-list rows from common row containers.
    """
    if isinstance(value, list):
        if not value:
            return []
        if all(isinstance(x, (list, tuple)) for x in value):
            return [list(x) for x in value]
    return None


def reconstruct_tables(obj):
    """
    Discover sibling or nearby field-name lists + row arrays.
    Returns table descriptors with reconstructed dict rows.
    """
    tables = []

    for path, node in walk(obj):
        if not isinstance(node, dict):
            continue

        # Discover header candidates in this dict.
        headers = []
        for k, v in node.items():
            kl = str(k).lower()
            if any(tok == kl or tok in kl for tok in HEADER_KEYS):
                names = field_names_from(v)
                if names:
                    headers.append((k, names))

        # Also direct schema nesting.
        if "schema" in node:
            names = field_names_from(node["schema"])
            if names:
                headers.append(("schema", names))

        # Discover row-array candidates in this dict.
        rowsets = []
        for k, v in node.items():
            kl = str(k).lower()
            if any(tok == kl or tok in kl for tok in ROW_KEYS):
                arr = row_arrays_from(v)
                if arr is not None:
                    rowsets.append((k, arr))

        # Pair compatible widths.
        for hk, names in headers:
            for rk, rows in rowsets:
                if not rows:
                    continue
                widths = [len(r) for r in rows[:50]]
                modal = max(set(widths), key=widths.count)
                if modal != len(names):
                    continue
                recs = []
                for idx, vals in enumerate(rows):
                    if len(vals) != len(names):
                        continue
                    recs.append(dict(zip(names, vals)))
                if recs:
                    tables.append({
                        "path": path,
                        "header_key": str(hk),
                        "row_key": str(rk),
                        "field_count": len(names),
                        "row_count": len(recs),
                        "fields": names,
                        "rows": recs,
                    })

    # Global fallback: find header lists and row arrays at different nearby paths.
    all_headers = []
    all_rowsets = []
    for path, node in walk(obj):
        names = field_names_from(node)
        if names and 3 <= len(names) <= 300:
            all_headers.append((path, names))
        rows = row_arrays_from(node)
        if rows and 1 <= len(rows) <= 2_000_000:
            all_rowsets.append((path, rows))

    for hp, names in all_headers:
        for rp, rows in all_rowsets:
            widths = [len(r) for r in rows[:50] if isinstance(r, list)]
            if not widths:
                continue
            modal = max(set(widths), key=widths.count)
            if modal != len(names):
                continue
            # Prefer structurally nearby path pairs.
            common = 0
            for a, b in zip(hp.split("."), rp.split(".")):
                if a != b:
                    break
                common += 1
            if common < 1:
                continue
            recs = []
            for vals in rows:
                if len(vals) == len(names):
                    recs.append(dict(zip(names, vals)))
            if recs:
                tables.append({
                    "path": f"GLOBAL_PAIR:{hp}::{rp}",
                    "header_key": hp,
                    "row_key": rp,
                    "field_count": len(names),
                    "row_count": len(recs),
                    "fields": names,
                    "rows": recs,
                })

    # Deduplicate tables by field list + row count + first rows.
    dedup = {}
    for t in tables:
        sig = json.dumps({
            "fields": t["fields"],
            "row_count": t["row_count"],
            "first": t["rows"][:3],
        }, sort_keys=True, default=str)
        if sig not in dedup:
            dedup[sig] = t
    return list(dedup.values())


def direct_dict_rows(obj):
    out = []
    for path, node in walk(obj):
        if not isinstance(node, dict):
            continue
        # Row-like if at least one explicit plausible coordinate pair exists.
        pos = actual_positions(node)
        if pos:
            out.append((path, node))
    return out


def actual_positions(row):
    nm = {norm(k): k for k in row}
    ras = []
    decs = []

    for name in RA_NAMES:
        q = norm(name)
        if q in nm:
            k = nm[q]
            kl = str(k).lower()
            if any(t in kl for t in BAD_COORD_TOKENS):
                continue
            x = f(row[k])
            if x is not None and 0 <= x < 360:
                ras.append((k, x))
    for name in DEC_NAMES:
        q = norm(name)
        if q in nm:
            k = nm[q]
            kl = str(k).lower()
            if any(t in kl for t in BAD_COORD_TOKENS):
                continue
            x = f(row[k])
            if x is not None and -90 <= x <= 90:
                decs.append((k, x))

    # permissive fallback for *_ra_deg / *_dec_deg patterns
    for k, v in row.items():
        kl = str(k).lower()
        if any(t in kl for t in BAD_COORD_TOKENS):
            continue
        nk = norm(k)
        x = f(v)
        if x is None:
            continue
        if (
            ("ra" in nk and ("deg" in nk or "fit" in nk)) and
            not any(k0 == k for k0, _ in ras) and 0 <= x < 360
        ):
            ras.append((k, x))
        if (
            ("dec" in nk and ("deg" in nk or "fit" in nk)) and
            not any(k0 == k for k0, _ in decs) and -90 <= x <= 90
        ):
            decs.append((k, x))

    out = []
    for rk, ra in ras:
        for dk, dec in decs:
            # Prefer semantic pairings with similar prefixes.
            rp = norm(rk).replace("ra","")
            dp = norm(dk).replace("dec","")
            penalty = 0 if rp == dp else 1
            out.append((penalty, ra, dec, str(rk), str(dk)))
    out.sort(key=lambda z: z[0])
    return out


def compact_fields(row):
    out = {}
    for k, v in row.items():
        kl = str(k).lower()
        if (
            any(t in kl for t in INTERESTING)
            or "ra" in kl or "dec" in kl
            or "plate" in kl
        ):
            out[str(k)] = v
        if len(out) >= 60:
            break
    return out


def json_shape(obj):
    if isinstance(obj, dict):
        return {
            "type": "dict",
            "keys": list(obj.keys())[:100],
            "key_count": len(obj),
        }
    if isinstance(obj, list):
        return {
            "type": "list",
            "length": len(obj),
            "element_types": sorted(set(type(x).__name__ for x in obj[:100])),
        }
    return {"type": type(obj).__name__, "value_preview": str(obj)[:500]}


def main():
    print("="*128)
    print("ORDER 01 — RAW DASCH PLATEPHOT SCHEMA + TABLE RECONSTRUCTION AUDIT v028am")
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

    science = resolve_science(read_csv(STRICT), read_csv(DASCH_NATIVE))

    summaries = []
    all_rows = []
    schema_rows = []

    for rank in RANKS:
        p = RAW_DIR / f"{PLATE}_sol0_rank{rank}_apass_platephot.json"
        if not p.is_file():
            print(f"#{rank}: MISSING {p}")
            summaries.append({
                "strict_rank": rank,
                "cache_status": "MISSING",
                "top_level_type": None,
                "table_count": 0,
                "direct_coordinate_dict_count": 0,
                "reconstructed_unique_coordinate_row_count": 0,
                "nearest_sep_arcsec": None,
                "within3": 0, "within5": 0, "within10": 0, "within30": 0,
            })
            continue

        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            print(f"#{rank}: JSON parse failure: {e}")
            summaries.append({
                "strict_rank": rank,
                "cache_status": f"JSON_PARSE_ERROR:{e}",
                "top_level_type": None,
                "table_count": 0,
                "direct_coordinate_dict_count": 0,
                "reconstructed_unique_coordinate_row_count": 0,
                "nearest_sep_arcsec": None,
                "within3": 0, "within5": 0, "within10": 0, "within30": 0,
            })
            continue

        tables = reconstruct_tables(obj)
        direct = direct_dict_rows(obj)

        schema_rows.append({
            "strict_rank": rank,
            "source_file": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            "top_level_shape_json": json.dumps(json_shape(obj), sort_keys=True, default=str),
            "table_count": len(tables),
            "table_schemas_json": json.dumps([
                {
                    "path": t["path"],
                    "header_key": t["header_key"],
                    "row_key": t["row_key"],
                    "field_count": t["field_count"],
                    "row_count": t["row_count"],
                    "fields": t["fields"],
                } for t in tables
            ], sort_keys=True, default=str),
            "direct_coordinate_dict_count": len(direct),
        })

        candidates = []

        # Reconstructed table rows.
        for ti, t in enumerate(tables):
            for ri, row in enumerate(t["rows"]):
                for _, ra, dec, rk, dk in actual_positions(row):
                    sep = angsep_arcsec(
                        science[rank]["ra"], science[rank]["dec"], ra, dec
                    )
                    if sep <= MAX_REPORT_SEP_ARCSEC:
                        candidates.append({
                            "strict_rank": rank,
                            "source_kind": "RECONSTRUCTED_TABLE",
                            "source_path": t["path"],
                            "table_index": ti,
                            "row_index": ri,
                            "science_sep_arcsec": sep,
                            "row_ra_deg": ra,
                            "row_dec_deg": dec,
                            "ra_field": rk,
                            "dec_field": dk,
                            "fields_json": json.dumps(
                                compact_fields(row), sort_keys=True, default=str
                            ),
                        })

        # Native dict rows if any.
        for path, row in direct:
            for _, ra, dec, rk, dk in actual_positions(row):
                sep = angsep_arcsec(
                    science[rank]["ra"], science[rank]["dec"], ra, dec
                )
                if sep <= MAX_REPORT_SEP_ARCSEC:
                    candidates.append({
                        "strict_rank": rank,
                        "source_kind": "DIRECT_DICT",
                        "source_path": path,
                        "table_index": None,
                        "row_index": None,
                        "science_sep_arcsec": sep,
                        "row_ra_deg": ra,
                        "row_dec_deg": dec,
                        "ra_field": rk,
                        "dec_field": dk,
                        "fields_json": json.dumps(
                            compact_fields(row), sort_keys=True, default=str
                        ),
                    })

        # Deduplicate exact coordinate/field/selected-content echoes.
        dedup = {}
        for r in candidates:
            sig = (
                round(r["row_ra_deg"], 9),
                round(r["row_dec_deg"], 9),
                r["ra_field"], r["dec_field"],
                r["fields_json"],
            )
            if sig not in dedup:
                rr = dict(r)
                rr["duplicate_count"] = 1
                dedup[sig] = rr
            else:
                dedup[sig]["duplicate_count"] += 1

        unique = list(dedup.values())
        unique.sort(key=lambda r: r["science_sep_arcsec"])
        nearest = unique[0]["science_sep_arcsec"] if unique else None

        within3 = sum(r["science_sep_arcsec"] <= 3 for r in unique)
        within5 = sum(r["science_sep_arcsec"] <= 5 for r in unique)
        within10 = sum(r["science_sep_arcsec"] <= 10 for r in unique)
        within30 = sum(r["science_sep_arcsec"] <= 30 for r in unique)

        summaries.append({
            "strict_rank": rank,
            "cache_status": "OK",
            "top_level_type": type(obj).__name__,
            "table_count": len(tables),
            "direct_coordinate_dict_count": len(direct),
            "reconstructed_unique_coordinate_row_count": len(unique),
            "nearest_sep_arcsec": nearest,
            "within3": within3,
            "within5": within5,
            "within10": within10,
            "within30": within30,
        })

        all_rows.extend(unique[:KEEP_NEAREST])

        print(
            f"#{rank}: top={type(obj).__name__} "
            f"tables={len(tables)} directCoordDicts={len(direct)} "
            f"uniqueCoordRows={len(unique)} "
            f"nearest={'n/a' if nearest is None else f'{nearest:.3f}\"'} "
            f"within3/5/10/30={within3}/{within5}/{within10}/{within30}"
        )

        # Print schema previews.
        for ti, t in enumerate(tables[:4]):
            print(
                f"    table[{ti}] rows={t['row_count']} fields={t['field_count']} "
                f"path={t['path']}"
            )
            print("      fields=" + ", ".join(t["fields"][:40]))
        for r in unique[:5]:
            print(
                f"    nearest {r['science_sep_arcsec']:.3f}\" "
                f"{r['ra_field']}/{r['dec_field']} "
                f"RA={r['row_ra_deg']:.8f} Dec={r['row_dec_deg']:.8f}"
            )

    payload = {
        "stage": "ORDER01_DASCH_RAW_PLATEPHOT_SCHEMA_RECONSTRUCTION_V028AM",
        "plate": PLATE,
        "ranks": RANKS,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "v028al_raw_n_a_not_interpreted_as_absence": True,
            "table_oriented_json_reconstruction_enabled": True,
            "query_input_coordinates_rejected": True,
        },
        "summaries": summaries,
        "nearest_reconstructed_rows": all_rows,
        "schema": schema_rows,
        "interpretive_boundary": (
            "v028am is a parser/schema correction stage. A recovered raw platephot "
            "row is an official-data measurement candidate, not proof of an "
            "astrophysical transient. Conversely, failure to reconstruct a row is "
            "not evidence that no source exists."
        ),
    }

    write_json(OUT_JSON, payload)
    write_csv(
        OUT_ROWS,
        all_rows,
        [
            "strict_rank","source_kind","source_path","table_index","row_index",
            "science_sep_arcsec","row_ra_deg","row_dec_deg","ra_field","dec_field",
            "fields_json","duplicate_count"
        ]
    )
    write_csv(
        OUT_SCHEMA,
        schema_rows,
        [
            "strict_rank","source_file","top_level_shape_json","table_count",
            "table_schemas_json","direct_coordinate_dict_count"
        ]
    )

    md = [
        "# ORDER 01 — Raw DASCH Platephot Schema Reconstruction v028am","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- v028al `raw nearest=n/a` is treated as a schema/parser result, not source absence.",
        "- Table-oriented JSON structures are reconstructed.",
        "- Query/input/target coordinates are rejected.",
        "- No endpoint state was changed.","",
        "## Per-rank reconstruction","",
        "| rank | tables | direct coord dicts | unique coord rows | nearest | <=3″ | <=5″ | <=10″ | <=30″ |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for r in summaries:
        n = r["nearest_sep_arcsec"]
        md.append(
            f"| #{r['strict_rank']} | {r['table_count']} | "
            f"{r['direct_coordinate_dict_count']} | "
            f"{r['reconstructed_unique_coordinate_row_count']} | "
            f"{'—' if n is None else f'{n:.3f}″'} | "
            f"{r['within3']} | {r['within5']} | {r['within10']} | {r['within30']} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_ROWS}")
    print(f"  {OUT_SCHEMA}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
