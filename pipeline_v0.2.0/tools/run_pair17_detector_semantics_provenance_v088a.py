#!/usr/bin/env python3
from pathlib import Path
from collections import Counter, defaultdict
import csv, hashlib, json, math, re

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_detector_semantics_provenance_contract_v088.json"
)
EXPECTED_CONTRACT_SHA = "ab185d416e82e71e573124ddbcf5d3ac3a3aa88a6d9a13a020e932bec5cb416d"

V087_DIR = ROOT / "results" / "pair17_direct_detector_pixel_provenance_v087"
V087_CSV = V087_DIR / "pair17_direct_detector_pixel_provenance_v087.csv"
V087_BANK = V087_DIR / "pair17_v087_bank_manifest.json"
EXPECTED_V087_BANK_SHA = "f71c234c35c6c8c679ec259d6401cd37eb556e2a5309fd2c290debb6a2caf6ae"

V075 = (
    ROOT / "results" / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)
EXPECTED_V075_SHA = "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097"

OUT = ROOT / "results" / "pair17_detector_semantics_provenance_audit_v088"
OUT_CSV = OUT / "pair17_detector_semantics_rows_v088.csv"
OUT_SRC = OUT / "pair17_detector_semantics_source_excerpt_v088.txt"
OUT_META = OUT / "pair17_detector_tile_metadata_inventory_v088.json"
OUT_JSON = OUT / "pair17_detector_semantics_provenance_audit_v088.json"


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def rcsv(p):
    with Path(p).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def wcsv(p, rr):
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rr[0].keys()) if rr else []
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if fields:
            w.writeheader()
            w.writerows(rr)


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def parse_origin(tile):
    m = re.fullmatch(r"x(\d+)-(\d+)_y(\d+)-(\d+)", tile)
    if not m:
        raise RuntimeError(f"Unparseable tile id: {tile}")
    return int(m.group(1)), int(m.group(3))


DETECTOR_SOURCE = (
    ROOT / "tools" / "_execute_wide_frozen_detector_v056.payload.py"
)

def load_frozen_detector_source():
    """
    v088a operational repair:
    bind directly to the exact frozen v056 detector execution payload rather
    than heuristically searching for Python files that happen to contain the
    same field names.
    """
    if not DETECTOR_SOURCE.is_file():
        raise RuntimeError(
            f"Frozen v056 detector payload missing: {DETECTOR_SOURCE}"
        )

    text = DETECTOR_SOURCE.read_text(
        encoding="utf-8",
        errors="strict"
    )

    required = (
        "polarity",
        "global_x",
        "global_y",
        "local_x",
        "candidate_index",
    )
    missing = [term for term in required if term not in text]
    if missing:
        raise RuntimeError(
            "Frozen v056 detector payload no longer exposes expected "
            f"provenance terms: {missing}"
        )

    return DETECTOR_SOURCE, text


def source_excerpt(path, text):
    lines = text.splitlines()
    hit_lines = set()
    patterns = [
        r"polarity",
        r"global_x",
        r"global_y",
        r"local_x",
        r"local_y",
        r"candidate_index",
        r"pad",
        r"overlap",
        r"tile",
    ]
    for i, line in enumerate(lines):
        if any(re.search(p, line, re.I) for p in patterns):
            for j in range(max(0, i-4), min(len(lines), i+5)):
                hit_lines.add(j)

    selected = sorted(hit_lines)
    blocks = []
    last = None
    for j in selected:
        if last is None or j != last + 1:
            blocks.append([])
        blocks[-1].append(j)
        last = j

    out = []
    out.append(f"Detector source: {path.relative_to(ROOT)}")
    out.append(f"SHA256: {sha(path)}")
    out.append("")
    for block in blocks:
        out.append("-" * 100)
        for j in block:
            out.append(f"{j+1:6d}: {lines[j]}")
    return "\n".join(out) + "\n"


def tile_json_for(detector_csv):
    # v056 stores a same-stem JSON beside *_candidates.csv.
    name = detector_csv.name
    if not name.endswith("_candidates.csv"):
        return None
    q = detector_csv.with_name(name[:-len("_candidates.csv")] + ".json")
    return q if q.is_file() else None


def extract_metadata_terms(obj, path="$", out=None):
    if out is None:
        out = []
    terms = ("pad","padding","overlap","margin","tile","x0","y0","x1","y1","origin","global","local","crop")
    if isinstance(obj, dict):
        interesting = {}
        for k,v in obj.items():
            kl = str(k).lower()
            if any(t in kl for t in terms) and not isinstance(v, (dict,list)):
                interesting[k] = v
        if interesting:
            out.append({"path": path, "values": interesting})
        for k,v in obj.items():
            extract_metadata_terms(v, f"{path}.{k}", out)
    elif isinstance(obj, list):
        for i,v in enumerate(obj):
            extract_metadata_terms(v, f"{path}[{i}]", out)
    return out


def main():
    print("="*120)
    print("PAIR 17 — DETECTOR SEMANTICS / PROVENANCE AUDIT v088a")
    print("="*120)
    print("Operational repair:     bind exact frozen v056 detector payload")
    print("Scientific contract changed: NO")
    print("Network calls:          0")
    print("FITS/NPY pixel reads:   0")
    print("Detector reruns:        0")
    print("Score changes:          NONE")
    print("Disposition changes:    NONE")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v088 contract SHA mismatch")
    if not V087_BANK.is_file() or sha(V087_BANK) != EXPECTED_V087_BANK_SHA:
        raise RuntimeError("v087 bank SHA mismatch")
    if not V075.is_file() or sha(V075) != EXPECTED_V075_SHA:
        raise RuntimeError("v075 SHA mismatch")
    if not V087_CSV.is_file():
        raise RuntimeError("v087 CSV missing")

    rows = rcsv(V087_CSV)
    if len(rows) != 12:
        raise RuntimeError(f"Expected 12 v087 rows; got {len(rows)}")

    # Bind to the exact frozen v056 detector execution payload.
    det_path, det_text = load_frozen_detector_source()

    OUT.mkdir(parents=True, exist_ok=True)
    OUT_SRC.write_text(source_excerpt(det_path, det_text), encoding="utf-8")

    metadata_inventory = []
    normalized = []

    for r in rows:
        tile = str(r["tile_id"])
        x0,y0 = parse_origin(tile)
        gx = num(r["detector_global_x"])
        gy = num(r["detector_global_y"])
        lx = num(r["detector_local_x"])
        ly = num(r["detector_local_y"])
        if None in (gx,gy,lx,ly):
            raise RuntimeError("Missing detector coordinate value in v087")

        offx = gx - (x0 + lx)
        offy = gy - (y0 + ly)

        det_csv = ROOT / str(r["detector_csv"]).replace("/", "\\")
        if not det_csv.is_file():
            # portable fallback
            det_csv = ROOT / Path(str(r["detector_csv"]))
        meta_path = tile_json_for(det_csv)
        meta_terms = []
        meta_sha = ""
        if meta_path is not None:
            try:
                obj = json.loads(meta_path.read_text(encoding="utf-8"))
                meta_terms = extract_metadata_terms(obj)
                meta_sha = sha(meta_path)
            except Exception as e:
                meta_terms = [{"path":"$", "values":{"READ_ERROR":repr(e)}}]

        metadata_inventory.append({
            "raw_match_row": r["raw_match_row"],
            "observatory": r["observatory"],
            "tile_id": tile,
            "candidate_index": r["candidate_index"],
            "metadata_json":
                "" if meta_path is None else str(meta_path.relative_to(ROOT)).replace("\\","/"),
            "metadata_json_sha256": meta_sha,
            "coordinate_related_metadata": meta_terms,
        })

        normalized.append({
            "raw_match_row": r["raw_match_row"],
            "observatory": r["observatory"],
            "blind_code": r["blind_code"],
            "manual_feature": r["manual_feature"],
            "manual_morphology": r["manual_morphology"],
            "manual_confidence": r["manual_confidence"],
            "manual_notes": r["manual_notes"],
            "detector_polarity": r["detector_polarity"],
            "detector_snr": r["detector_snr"],
            "detector_sigma": r["detector_sigma"],
            "tile_id": tile,
            "candidate_index": r["candidate_index"],
            "tile_origin_x": x0,
            "tile_origin_y": y0,
            "local_x": lx,
            "local_y": ly,
            "global_x": gx,
            "global_y": gy,
            "global_minus_origin_plus_local_x_px": offx,
            "global_minus_origin_plus_local_y_px": offy,
            "global_origin_local_residual_px": math.hypot(offx,offy),
            "crosshair_vs_detector_delta_px":
                r["crosshair_vs_detector_direct_delta_px"],
            "direct_alignment_band": r["direct_alignment_band"],
            "detector_vs_v075_radec_arcsec":
                r["detector_vs_v075_radec_arcsec"],
        })

    wcsv(OUT_CSV, normalized)
    OUT_META.write_text(
        json.dumps(metadata_inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )

    # Cross-tabs are descriptive only.
    polarity_feature = defaultdict(Counter)
    obs_pol_feature = defaultdict(Counter)
    for r in normalized:
        pol = str(r["detector_polarity"])
        feat = str(r["manual_feature"])
        polarity_feature[pol][feat] += 1
        obs_pol_feature[(r["observatory"],pol)][feat] += 1

    hamburg = [r for r in normalized if r["observatory"] == "HAMBURG"]
    bamberg = [r for r in normalized if r["observatory"] == "BAMBERG"]

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_detector_semantics_provenance_audit_v088",
        "operational_repair": "v088a binds tools/_execute_wide_frozen_detector_v056.payload.py explicitly instead of heuristic source discovery",
        "scientific_contract_changed_by_v088a": False,
        "parent_v088_runner_sha256": "f6d1df3655d65d9c84c1ae3cfc881201d2361516e40504553d4e004337e1d940",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "detector_source": str(det_path.relative_to(ROOT)).replace("\\","/"),
        "detector_source_sha256": sha(det_path),
        "population": {"science_endpoint_rows": 12, "candidates": 6},
        "polarity_feature_crosstab": {
            pol: dict(c) for pol,c in polarity_feature.items()
        },
        "observatory_polarity_feature_crosstab": {
            f"{obs}|polarity={pol}": dict(c)
            for (obs,pol),c in obs_pol_feature.items()
        },
        "hamburg_rows": [
            {
                "raw_match_row": r["raw_match_row"],
                "blind_code": r["blind_code"],
                "manual_feature": r["manual_feature"],
                "manual_morphology": r["manual_morphology"],
                "detector_polarity": r["detector_polarity"],
                "detector_snr": r["detector_snr"],
                "coordinate_semantic_offset_px":
                    r["global_origin_local_residual_px"],
            }
            for r in hamburg
        ],
        "bamberg_rows": [
            {
                "raw_match_row": r["raw_match_row"],
                "blind_code": r["blind_code"],
                "manual_feature": r["manual_feature"],
                "manual_morphology": r["manual_morphology"],
                "detector_polarity": r["detector_polarity"],
                "detector_snr": r["detector_snr"],
                "coordinate_semantic_offset_px":
                    r["global_origin_local_residual_px"],
            }
            for r in bamberg
        ],
        "max_crosshair_vs_detector_delta_px":
            max(float(r["crosshair_vs_detector_delta_px"]) for r in normalized),
        "max_detector_vs_v075_radec_arcsec":
            max(float(r["detector_vs_v075_radec_arcsec"]) for r in normalized),
        "max_coordinate_semantic_offset_px":
            max(r["global_origin_local_residual_px"] for r in normalized),
        "guards": {
            "network_calls": 0,
            "fits_reads": 0,
            "npy_pixel_reads": 0,
            "detector_reruns": 0,
            "new_feature_measurements": 0,
            "manual_scores_modified": False,
            "threshold_retuning": False,
            "candidate_disposition_changes": False
        },
        "output_hashes": {
            "rows_csv": sha(OUT_CSV),
            "source_excerpt": sha(OUT_SRC),
            "metadata_inventory": sha(OUT_META),
        }
    }

    OUT_JSON.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )

    print("Detector source:", report["detector_source"])
    print("Detector source SHA256:", report["detector_source_sha256"])
    print()
    print("POLARITY × BLIND FEATURE")
    for pol in sorted(polarity_feature, key=str):
        print(f"  polarity={pol}: {dict(polarity_feature[pol])}")
    print()
    print("HAMBURG SCIENCE ROWS")
    for r in hamburg:
        print(
            f'{r["raw_match_row"]} blind={r["blind_code"]} '
            f'feature={r["manual_feature"]:17s} '
            f'morph={r["manual_morphology"]:20s} '
            f'polarity={r["detector_polarity"]:>3s} '
            f'snr={str(r["detector_snr"]):>8s} '
            f'coord_semantic_offset={r["global_origin_local_residual_px"]:.6f}px'
        )
    print()
    print("BAMBERG SCIENCE ROWS")
    for r in bamberg:
        print(
            f'{r["raw_match_row"]} blind={r["blind_code"]} '
            f'feature={r["manual_feature"]:17s} '
            f'morph={r["manual_morphology"]:20s} '
            f'polarity={r["detector_polarity"]:>3s} '
            f'snr={str(r["detector_snr"]):>8s} '
            f'coord_semantic_offset={r["global_origin_local_residual_px"]:.6f}px'
        )

    print()
    print("Source excerpt:", OUT_SRC)
    print("Tile metadata inventory:", OUT_META)
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
