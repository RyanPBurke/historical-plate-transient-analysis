#!/usr/bin/env python3
from pathlib import Path
import ast
import py_compile
import re
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REGISTRY = AUTO / "registry_order01.py"
RUNNER = AUTO / "runner.py"
STAGE = AUTO / "stages" / "analyze_platewide_official_association_v028bf.py"
BACKUP = AUTO / "backups" / "pre_v011"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport importlib.util\nimport json\nimport math\nimport sys\nfrom pathlib import Path\n\nimport numpy as np\nfrom scipy.spatial import cKDTree\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\n\nFULL = BASE / "order01_dasch_platephot_full_fetch_v028be.json"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\nSTRICT = BASE / "order01_strict_match_triage_v028.csv"\nV028R = ROOT / "tools" / "audit_order01_official_dasch_platephot_astrometry_v028r.py"\n\nOUT_JSON = BASE / "order01_dasch_platewide_official_association_census_v028bf.json"\nOUT_CSV = BASE / "order01_dasch_platewide_native_official_associations_v028bf.csv"\nOUT_MD = BASE / "ORDER01_DASCH_PLATEWIDE_OFFICIAL_ASSOCIATION_CENSUS_V028BF.md"\n\nSCIENCE_RANKS = [10, 24, 25, 26, 29, 30]\nRADII = [3.0, 5.0, 10.0, 30.0, 60.0]\nPRIMARY = 10.0\nEXPECTED_NATIVE = 3986\nEXPECTED_NONSCIENCE = 3980\n\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\n\ndef f(v, default=None):\n    try:\n        if v is None or str(v).strip() == "":\n            return default\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef i(v, default=None):\n    try:\n        if v is None or str(v).strip() == "":\n            return default\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef load_v028r():\n    spec = importlib.util.spec_from_file_location("v028r_assoc_census", V028R)\n    if spec is None or spec.loader is None:\n        raise RuntimeError("cannot import exact v028r source")\n    mod = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = mod\n    spec.loader.exec_module(mod)\n    for name in ("csv_records_from_api_json", "extract_official_fields"):\n        if not hasattr(mod, name):\n            raise RuntimeError(f"v028r missing helper {name}")\n    return mod\n\n\ndef official_coord(q):\n    ra_keys = ("ra_deg", "ra", "radeg", "raDeg", "RA", "RA_DEG")\n    dec_keys = ("dec_deg", "dec", "decdeg", "decDeg", "DEC", "DEC_DEG")\n    ra = None\n    dec = None\n    for k in ra_keys:\n        x = f(q.get(k))\n        if x is not None:\n            ra = x\n            break\n    for k in dec_keys:\n        x = f(q.get(k))\n        if x is not None:\n            dec = x\n            break\n    return ra, dec\n\n\ndef unit_xyz(ra_deg, dec_deg):\n    ra = np.radians(np.asarray(ra_deg, dtype=float))\n    dec = np.radians(np.asarray(dec_deg, dtype=float))\n    cd = np.cos(dec)\n    return np.column_stack((cd*np.cos(ra), cd*np.sin(ra), np.sin(dec)))\n\n\ndef chord_to_arcsec(chord):\n    x = np.clip(np.asarray(chord, dtype=float)/2.0, 0.0, 1.0)\n    return np.degrees(2.0*np.arcsin(x))*3600.0\n\n\ndef pct(vals, q):\n    return None if not vals else float(np.percentile(np.asarray(vals, dtype=float), q))\n\n\ndef write_json(path, obj):\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\\n", encoding="utf-8")\n    tmp.replace(path)\n\n\ndef write_csv(path, rows, fields):\n    tmp = path.with_suffix(path.suffix + ".tmp")\n    with tmp.open("w", encoding="utf-8", newline="") as fh:\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(rows)\n    tmp.replace(path)\n\n\ndef subgroup(rows):\n    if not rows:\n        return {"count": 0}\n    vals = [float(r["nearest_official_sep_arcsec"]) for r in rows]\n    assoc = sum(v <= PRIMARY for v in vals)\n    return {\n        "count": len(rows),\n        "associated_le_10arcsec": assoc,\n        "unassociated_gt_10arcsec": len(rows)-assoc,\n        "associated_fraction": assoc/len(rows),\n        "nearest_sep_arcsec_median": pct(vals, 50),\n        "nearest_sep_arcsec_p90": pct(vals, 90),\n        "nearest_sep_arcsec_p95": pct(vals, 95),\n    }\n\n\ndef main():\n    print("="*128)\n    print("ORDER 01 — PLATE-WIDE OFFICIAL ASSOCIATION CENSUS v028bf")\n    print("="*128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (FULL, NATIVE, STRICT, V028R):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    full = json.loads(FULL.read_text(encoding="utf-8"))\n    if not full.get("summary", {}).get("complete"):\n        print("FAIL v028be acquisition is not complete")\n        return 3\n    if int(full.get("summary", {}).get("success_count", -1)) != int(full.get("queue_count", -2)):\n        print("FAIL v028be success_count != queue_count")\n        return 3\n\n    mod = load_v028r()\n    raw_api_rows = 0\n    selected = []\n    invalid_coord = 0\n    cache_count = 0\n\n    for item in full.get("items", []):\n        cache_rel = item.get("cache")\n        if not cache_rel:\n            print(f"FAIL missing cache path at queue item {item.get(\'queue_order\')}")\n            return 3\n        cache = ROOT / cache_rel\n        if not cache.is_file():\n            print(f"FAIL missing validated cache: {cache}")\n            return 3\n\n        obj = json.loads(cache.read_text(encoding="utf-8"))\n        raw_rows = mod.csv_records_from_api_json(obj)\n        raw_api_rows += len(raw_rows)\n        cache_count += 1\n\n        for rr in raw_rows:\n            q = mod.extract_official_fields(rr)\n            solnum = q.get("solnum")\n            if solnum is not None and i(solnum) != 0:\n                continue\n            ra, dec = official_coord(q)\n            if ra is None or dec is None:\n                invalid_coord += 1\n                continue\n            selected.append({"ra_deg": ra, "dec_deg": dec})\n\n    if not selected:\n        print("FAIL no official positions recovered")\n        return 3\n\n    uniq = {}\n    for r in selected:\n        uniq.setdefault((round(r["ra_deg"], 7), round(r["dec_deg"], 7)), r)\n    official = list(uniq.values())\n\n    strict_rows = read_csv(STRICT)\n    science_map = {}\n    for r in strict_rows:\n        rank = i(r.get("strict_rank"))\n        if rank not in SCIENCE_RANKS:\n            continue\n        key = (str(r.get("dasch_tile_id", "")), i(r.get("dasch_candidate_index")))\n        science_map[key] = rank\n\n    if sorted(science_map.values()) != SCIENCE_RANKS:\n        print(f"FAIL science map mismatch: {sorted(science_map.values())}")\n        return 3\n\n    native = []\n    for r in read_csv(NATIVE):\n        ra, dec = f(r.get("ra_deg")), f(r.get("dec_deg"))\n        if ra is None or dec is None:\n            continue\n        key = (str(r.get("tile_id", "")), i(r.get("candidate_index")))\n        native.append({\n            "tile_id": key[0],\n            "candidate_index": key[1],\n            "ra_deg": ra,\n            "dec_deg": dec,\n            "snr": f(r.get("snr")),\n            "polarity": i(r.get("polarity")),\n            "science_rank": science_map.get(key),\n        })\n\n    if len(native) != EXPECTED_NATIVE:\n        print(f"FAIL expected {EXPECTED_NATIVE} native rows; got {len(native)}")\n        return 3\n\n    non_science_n = sum(r["science_rank"] is None for r in native)\n    if non_science_n != EXPECTED_NONSCIENCE:\n        print(f"FAIL expected {EXPECTED_NONSCIENCE} non-science; got {non_science_n}")\n        return 3\n\n    tree = cKDTree(unit_xyz(\n        [r["ra_deg"] for r in official],\n        [r["dec_deg"] for r in official],\n    ))\n    d, idx = tree.query(unit_xyz(\n        [r["ra_deg"] for r in native],\n        [r["dec_deg"] for r in native],\n    ), k=1)\n    sep = chord_to_arcsec(d)\n\n    rows = []\n    for n, r in enumerate(native):\n        o = official[int(idx[n])]\n        s = float(sep[n])\n        out = {\n            "tile_id": r["tile_id"],\n            "candidate_index": r["candidate_index"],\n            "ra_deg": r["ra_deg"],\n            "dec_deg": r["dec_deg"],\n            "snr": r["snr"],\n            "polarity": r["polarity"],\n            "is_science": r["science_rank"] is not None,\n            "science_rank": r["science_rank"],\n            "nearest_official_ra_deg": o["ra_deg"],\n            "nearest_official_dec_deg": o["dec_deg"],\n            "nearest_official_sep_arcsec": s,\n            "official_associated_le_10arcsec": s <= PRIMARY,\n        }\n        for radius in RADII:\n            out[f"official_within_{int(radius)}arcsec"] = s <= radius\n        rows.append(out)\n\n    non_science = [r for r in rows if not r["is_science"]]\n    science = sorted([r for r in rows if r["is_science"]], key=lambda r: int(r["science_rank"]))\n\n    counts = {}\n    for radius in RADII:\n        k = f"official_within_{int(radius)}arcsec"\n        n = sum(bool(r[k]) for r in non_science)\n        counts[str(int(radius))] = {\n            "associated_count": n,\n            "unassociated_count": len(non_science)-n,\n            "associated_fraction": n/len(non_science),\n            "unassociated_fraction": (len(non_science)-n)/len(non_science),\n        }\n\n    plus = [r for r in non_science if i(r.get("polarity")) == 1]\n    minus = [r for r in non_science if i(r.get("polarity")) == -1]\n    ns_sep = [float(r["nearest_official_sep_arcsec"]) for r in non_science]\n\n    science_summary = []\n    for r in science:\n        s = float(r["nearest_official_sep_arcsec"])\n        science_summary.append({\n            "rank": int(r["science_rank"]),\n            "nearest_official_sep_arcsec": s,\n            "official_associated_le_10arcsec": bool(r["official_associated_le_10arcsec"]),\n            "empirical_non_science_nearest_sep_percentile": sum(x <= s for x in ns_sep)/len(ns_sep),\n        })\n\n    regression_ok = all(not r["official_associated_le_10arcsec"] for r in science_summary)\n\n    print(f"Validated cache files pooled:               {cache_count}")\n    print(f"Raw official API rows pooled:               {raw_api_rows}")\n    print(f"Solution-0 valid-coordinate rows:           {len(selected)}")\n    print(f"Unique official positions:                  {len(official)}")\n    print(f"Frozen native DASCH detections:             {len(native)}")\n    print(f"Non-science native detections:              {len(non_science)}")\n    print()\n    for radius in RADII:\n        c = counts[str(int(radius))]\n        print(f"Official association <= {int(radius):2d}\\": {c[\'associated_count\']}/{len(non_science)} ({100*c[\'associated_fraction\']:.3f}%)")\n    print()\n    print(f"Detector +1: {subgroup(plus)}")\n    print(f"Detector -1: {subgroup(minus)}")\n    print("\\nSCIENCE ENDPOINTS")\n    for r in science_summary:\n        print(f"  #{r[\'rank\']:02d} nearest={r[\'nearest_official_sep_arcsec\']:.3f}\\" assoc<=10={r[\'official_associated_le_10arcsec\']} nonSciencePct={r[\'empirical_non_science_nearest_sep_percentile\']:.5f}")\n    print(f"\\nScience <=10\\" regression guard: {regression_ok}")\n\n    payload = {\n        "stage": "ORDER01_DASCH_PLATEWIDE_OFFICIAL_ASSOCIATION_CENSUS_V028BF",\n        "guards": {\n            "network_access": False,\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "official_pool": {\n            "validated_cache_files": cache_count,\n            "raw_api_rows": raw_api_rows,\n            "solution0_valid_coordinate_rows": len(selected),\n            "invalid_official_coordinate_rows": invalid_coord,\n            "unique_positions": len(official),\n        },\n        "summary": {\n            "native_valid_rows": len(native),\n            "science_rows": len(science),\n            "non_science_rows": len(non_science),\n            "association_radii_arcsec": RADII,\n            "primary_association_radius_arcsec": PRIMARY,\n            "counts_by_radius": counts,\n            "all_non_science": subgroup(non_science),\n            "detector_polarity_plus1": subgroup(plus),\n            "detector_polarity_minus1": subgroup(minus),\n            "science_endpoint_regression_guard_no_official_within_10arcsec": regression_ok,\n        },\n        "science_endpoints": science_summary,\n        "next_gate": {"platewide_morphology_prevalence_may_run": regression_ok},\n        "interpretive_boundary": (\n            "This is an official DR7 platephot association census only. "\n            "An unassociated native detection is not thereby astrophysical."\n        ),\n    }\n\n    write_json(OUT_JSON, payload)\n    write_csv(OUT_CSV, rows, list(rows[0].keys()))\n\n    c10 = counts["10"]\n    OUT_MD.write_text(\n        "# ORDER 01 — Plate-wide Official Association Census v028bf\\n\\n"\n        f"- Non-science native detections: **{len(non_science)}**.\\n"\n        f"- Associated within 10 arcsec: **{c10[\'associated_count\']}** ({100*c10[\'associated_fraction\']:.3f}%).\\n"\n        f"- No official source within 10 arcsec: **{c10[\'unassociated_count\']}** ({100*c10[\'unassociated_fraction\']:.3f}%).\\n"\n        f"- All six science endpoints remain >10 arcsec: **{regression_ok}**.\\n\\n"\n        "No pixels were read and no candidate state changed.\\n",\n        encoding="utf-8",\n    )\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n\n    if not regression_ok:\n        print("\\nFAIL: science-endpoint regression guard reversed.")\n        return 6\n\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_platewide_official_association_v028bf",
        title="Plate-wide DASCH native-to-official association census",
        script="automation/stages/analyze_platewide_official_association_v028bf.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_platephot_full_fetch_v028be.json",
            "results/order01_native_full_v028/order01_dasch_native_candidates.csv",
            "results/order01_native_full_v028/order01_strict_match_triage_v028.csv",
            "tools/audit_order01_official_dasch_platephot_astrometry_v028r.py",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_platewide_official_association_census_v028bf.json",
        ),
        dependencies=("dasch_platephot_full_queue_v028be",),
        notes="No network/pixels; complete plate-wide official-association denominator before morphology prevalence.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_platewide_official_association_v028bf"' in text:
        return text, "already registered"

    tree = ast.parse(text)
    container = None
    for node in tree.body:
        value = None
        matched = False
        if isinstance(node, ast.Assign):
            value = node.value
            matched = any(isinstance(t, ast.Name) and t.id == "ORDER01_STAGES" for t in node.targets)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            matched = isinstance(node.target, ast.Name) and node.target.id == "ORDER01_STAGES"
        if matched and isinstance(value, (ast.List, ast.Tuple)):
            container = value
            break

    if container is None:
        raise RuntimeError("ORDER01_STAGES list/tuple not found")

    lines = text.splitlines(keepends=True)
    lines.insert(container.end_lineno - 1, "\n" + ENTRY.rstrip() + "\n")
    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted before ORDER01_STAGES closing line {container.end_lineno}"


def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.1.1 — PLATE-WIDE ASSOCIATION CENSUS")
    print("="*112)
    print("NO NETWORK ACCESS.")
    print("NO PIXELS ARE READ BY THE UPGRADE.")
    print("No candidate state is changed.\n")

    for p in (REGISTRY, RUNNER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, AUTO/"__init__.py"):
        if p.is_file():
            dst = BACKUP / p.name
            if not dst.exists():
                shutil.copy2(p, dst)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_CONTENT, encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)
    print(f"Stage validated: {STAGE.relative_to(ROOT)}")

    reg = REGISTRY.read_text(encoding="utf-8")
    reg, note = register_stage(reg)
    REGISTRY.write_text(reg, encoding="utf-8")
    print(f"Registry: {note}")

    runner = RUNNER.read_text(encoding="utf-8")
    runner, _ = re.subn(
        r"Transient automation v[0-9.]+ - Order01 registry status",
        "Transient automation v0.1.1 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO/"__init__.py").write_text('__version__ = "0.1.1"\n', encoding="utf-8")

    failures = []
    py_files = sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p, exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")

    if failures:
        print("\nAUTOMATION UPGRADE STATUS: FAIL")
        return 4

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_platewide_official_association_v028bf')
    print("\nNo network or pixel access is required by v028bf.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
