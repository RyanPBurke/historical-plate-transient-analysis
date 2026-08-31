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
STAGE = AUTO / "stages" / "query_science25_analogue_catalog_provenance_v028bq.py"
BACKUP = AUTO / "backups" / "pre_v022"
STAGE_CONTENT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport csv\nimport io\nimport json\nimport math\nimport os\nimport time\nfrom datetime import datetime, timezone\nfrom pathlib import Path\n\nimport requests\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nWORK = ROOT / "work" / "order01_native_full_v028" / "catalog_provenance_v028bq"\n\nAR_JSON = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"\nBJ = BASE / "order01_dasch_platewide_morphology_metrics_v028bj.json"\nBO = BASE / "order01_dasch_science25_direct_shape_neighbourhood_v028bo.json"\n\nOUT_JSON = BASE / "order01_dasch_science25_analogue_catalog_provenance_v028bq.json"\nOUT_CSV = BASE / "order01_dasch_science25_analogue_catalog_provenance_v028bq.csv"\nOUT_MD = BASE / "ORDER01_DASCH_SCIENCE25_ANALOGUE_CATALOG_PROVENANCE_V028BQ.md"\n\nBASE_URL = "https://api.starglass.cfa.harvard.edu/public/"\nQUERYCAT_PATH = "dasch/dr7/querycat"\nLIGHTCURVE_PATH = "dasch/dr7/lightcurve"\nQUERY_RADIUS_ARCSEC = 120.0\nLIGHTCURVE_TRIGGER_ARCSEC = 15.0\nTIMEOUT = 90\nREFCATS = ("apass", "atlas")\nTARGET_ORDERS = (30, 344)\nPLATE_ID = "ai43437"\nPLATE_EPOCH_ISO = "1951-11-05T07:30:00+00:00"\n\n\ndef f(v, default=None):\n    try:\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\n\ndef i(v, default=None):\n    try:\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\n\ndef first(row, *keys):\n    for k in keys:\n        if k in row and row[k] not in ("", None):\n            return row[k]\n    return None\n\n\ndef parse_api_csv(obj):\n    if not isinstance(obj, list):\n        raise RuntimeError(f"expected JSON list of CSV strings; got {type(obj).__name__}")\n    if not obj:\n        return []\n    text = "\\n".join(str(x) for x in obj)\n    return list(csv.DictReader(io.StringIO(text)))\n\n\ndef angular_sep_arcsec(ra1, dec1, ra2, dec2):\n    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))\n    sd = math.sin((d2 - d1) / 2.0)\n    sr = math.sin((r2 - r1) / 2.0)\n    a = sd * sd + math.cos(d1) * math.cos(d2) * sr * sr\n    a = min(1.0, max(0.0, a))\n    return math.degrees(2.0 * math.asin(math.sqrt(a))) * 3600.0\n\n\ndef decimal_year(dt):\n    start = datetime(dt.year, 1, 1, tzinfo=timezone.utc)\n    end = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)\n    return dt.year + (dt - start).total_seconds() / (end - start).total_seconds()\n\n\nPLATE_EPOCH = datetime.fromisoformat(PLATE_EPOCH_ISO)\nPLATE_JYEAR = decimal_year(PLATE_EPOCH)\n\n\ndef post_json(path, payload, cache_path):\n    cache_path.parent.mkdir(parents=True, exist_ok=True)\n    if cache_path.is_file():\n        return json.loads(cache_path.read_text(encoding="utf-8")), True\n\n    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")\n    delays = (2, 5, 10)\n    last = None\n    for attempt in range(1, 4):\n        try:\n            r = requests.post(\n                url,\n                json=payload,\n                timeout=TIMEOUT,\n                headers={"accept": "application/json"},\n            )\n            if r.status_code in (408, 425, 429) or 500 <= r.status_code <= 599:\n                raise requests.HTTPError(f"retryable HTTP {r.status_code}", response=r)\n            r.raise_for_status()\n            obj = r.json()\n            tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")\n            tmp.write_text(json.dumps(obj, indent=2) + "\\n", encoding="utf-8")\n            tmp.replace(cache_path)\n            time.sleep(1.0)\n            return obj, False\n        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:\n            last = exc\n            if attempt == 3:\n                break\n            time.sleep(delays[attempt - 1])\n    raise RuntimeError(f"POST {path} failed after 3 attempts: {type(last).__name__}: {last}")\n\n\ndef normalize_source(row, target_ra, target_dec, refcat):\n    ra = f(first(row, "raDeg", "ra_deg", "ra", "RA"))\n    dec = f(first(row, "decDeg", "dec_deg", "dec", "DEC"))\n    if ra is None or dec is None:\n        return None\n\n    pmra = f(first(\n        row,\n        "pmRaMasyr", "pm_ra_masyr",\n        "pmRaCosdec", "pmRaCosDec", "pm_ra_cosdec",\n    ))\n    pmdec = f(first(row, "pmDecMasyr", "pm_dec_masyr", "pmDec", "pm_dec"))\n    epoch = f(first(row, "posEpoch", "pos_epoch", "epoch", "positionEpoch"))\n\n    current_sep = angular_sep_arcsec(target_ra, target_dec, ra, dec)\n    pra, pdec = ra, dec\n    propagated = False\n\n    # DASCH catalog documentation describes the stored RA PM component as\n    # pm_ra_cosdec.  Apply the cos(dec) correction when converting to delta-RA.\n    if pmra is not None and pmdec is not None and epoch is not None:\n        dt = PLATE_JYEAR - epoch\n        cosd = math.cos(math.radians(dec))\n        if abs(cosd) > 1e-8:\n            pra = ra + (pmra * dt / (3.6e6 * cosd))\n            pdec = dec + (pmdec * dt / 3.6e6)\n            propagated = True\n\n    prop_sep = angular_sep_arcsec(target_ra, target_dec, pra, pdec)\n\n    return {\n        "refcat": refcat,\n        "ref_text": first(row, "refText", "ref_text"),\n        "ref_number": i(first(row, "refNumber", "ref_number")),\n        "gsc_bin_index": i(first(row, "gscBinIndex", "gsc_bin_index")),\n        "num_matches": i(first(row, "numMatches", "num_matches"), 0),\n        "stdmag": f(first(row, "stdmag", "stdMag", "std_mag")),\n        "class": i(first(row, "class", "sourceClass")),\n        "catalog_ra_deg": ra,\n        "catalog_dec_deg": dec,\n        "pm_ra_cosdec_masyr": pmra,\n        "pm_dec_masyr": pmdec,\n        "pos_epoch_jyear": epoch,\n        "proper_motion_propagated": propagated,\n        "propagated_ra_1951_deg": pra,\n        "propagated_dec_1951_deg": pdec,\n        "current_catalog_sep_arcsec": current_sep,\n        "propagated_1951_sep_arcsec": prop_sep,\n        "raw": row,\n    }\n\n\ndef lightcurve_summary(rows, target_ra, target_dec):\n    ai_rows = []\n    for row in rows:\n        series = str(first(row, "series", "Series") or "").lower()\n        platenum = i(first(row, "platenum", "plateNum", "plate_num"))\n        if series == "ai" and platenum == 43437:\n            ra = f(first(row, "raDeg", "ra_deg", "ra"))\n            dec = f(first(row, "decDeg", "dec_deg", "dec"))\n            sep = None\n            if ra is not None and dec is not None:\n                sep = angular_sep_arcsec(target_ra, target_dec, ra, dec)\n            ai_rows.append({\n                "series": series,\n                "platenum": platenum,\n                "solnum": i(first(row, "solnum", "solNum")),\n                "expnum": i(first(row, "expnum", "expNum")),\n                "ra_deg": ra,\n                "dec_deg": dec,\n                "fitted_sep_to_target_arcsec": sep,\n                "magcal_magdep": f(first(row, "magcalMagdep", "magcal_magdep")),\n                "limiting_mag_local": f(first(row, "limitingMagLocal", "limiting_mag_local")),\n                "aflags": first(row, "aflags", "aFlags"),\n                "bflags": first(row, "bflags", "bFlags"),\n                "raw": row,\n            })\n\n    return {\n        "row_count": len(rows),\n        "ai43437_row_count": len(ai_rows),\n        "ai43437_rows": ai_rows,\n        "ai43437_min_fitted_sep_arcsec": min(\n            [x["fitted_sep_to_target_arcsec"] for x in ai_rows if x["fitted_sep_to_target_arcsec"] is not None],\n            default=None,\n        ),\n    }\n\n\ndef main():\n    print("=" * 128)\n    print("ORDER 01 — #25 / q0030 / q0344 DASCH CATALOG PROVENANCE v028bq")\n    print("=" * 128)\n    print("NETWORK ACCESS: TRUE (DASCH DR7 PUBLIC API ONLY).")\n    print("NO PIXELS ARE READ.")\n    print("Frozen transient detector is NOT rerun.")\n    print("No candidate state is changed.\\n")\n\n    for p in (AR_JSON, BJ, BO):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    ar = json.loads(AR_JSON.read_text(encoding="utf-8"))\n    bj = json.loads(BJ.read_text(encoding="utf-8"))\n    bo = json.loads(BO.read_text(encoding="utf-8"))\n\n    science = {int(r["strict_rank"]): r for r in ar.get("science", [])}\n    if 25 not in science:\n        print("FAIL science #25 missing")\n        return 3\n\n    success = {\n        int(r["queue_order"]): r\n        for r in bj.get("results", [])\n        if r.get("status") == "SUCCESS"\n    }\n    if any(o not in success for o in TARGET_ORDERS):\n        print("FAIL q0030/q0344 v028bj provenance missing")\n        return 3\n\n    if int(bo.get("nearest_direct_control", {}).get("queue_order", -1)) != 344:\n        print("FAIL v028bo nearest direct control guard mismatch")\n        return 3\n    if int(bo.get("nearest_direct_above_control_amplitude_control", {}).get("queue_order", -1)) != 30:\n        print("FAIL v028bo nearest amplitude analogue guard mismatch")\n        return 3\n\n    targets = [\n        {\n            "target": "science25",\n            "ra_deg": float(science[25]["ra_deg"]),\n            "dec_deg": float(science[25]["dec_deg"]),\n        },\n        {\n            "target": "q0030",\n            "ra_deg": float(success[30]["ra_deg"]),\n            "dec_deg": float(success[30]["dec_deg"]),\n        },\n        {\n            "target": "q0344",\n            "ra_deg": float(success[344]["ra_deg"]),\n            "dec_deg": float(success[344]["dec_deg"]),\n        },\n    ]\n\n    all_rows = []\n    results = {}\n\n    for t in targets:\n        tname = t["target"]\n        tra, tdec = t["ra_deg"], t["dec_deg"]\n        tres = {\n            "target": tname,\n            "ra_deg": tra,\n            "dec_deg": tdec,\n            "plate_epoch_iso": PLATE_EPOCH_ISO,\n            "plate_epoch_jyear": PLATE_JYEAR,\n            "refcats": {},\n        }\n\n        print(f"{tname}: RA={tra:.9f} Dec={tdec:.9f}")\n\n        for refcat in REFCATS:\n            payload = {\n                "refcat": refcat,\n                "ra_deg": tra,\n                "dec_deg": tdec,\n                "radius_arcsec": QUERY_RADIUS_ARCSEC,\n            }\n            qcache = WORK / f"{tname}_{refcat}_querycat.json"\n            obj, cache_used = post_json(QUERYCAT_PATH, payload, qcache)\n            rows = parse_api_csv(obj)\n\n            sources = []\n            for row in rows:\n                s = normalize_source(row, tra, tdec, refcat)\n                if s is not None:\n                    sources.append(s)\n\n            sources.sort(key=lambda x: (x["propagated_1951_sep_arcsec"], x["current_catalog_sep_arcsec"]))\n            nearest = sources[0] if sources else None\n\n            rres = {\n                "query_payload": payload,\n                "cache_used": cache_used,\n                "raw_row_count": len(rows),\n                "valid_source_count": len(sources),\n                "nearest_sources": sources[:10],\n                "nearest": nearest,\n                "lightcurve": None,\n            }\n\n            if nearest is not None:\n                print(\n                    f"  {refcat}: n={len(sources)} "\n                    f"nearest current={nearest[\'current_catalog_sep_arcsec\']:.3f}\\" "\n                    f"epoch1951={nearest[\'propagated_1951_sep_arcsec\']:.3f}\\" "\n                    f"numMatches={nearest[\'num_matches\']} "\n                    f"pmProp={nearest[\'proper_motion_propagated\']}"\n                )\n\n                if (\n                    nearest["propagated_1951_sep_arcsec"] <= LIGHTCURVE_TRIGGER_ARCSEC\n                    and nearest["ref_number"] is not None\n                    and nearest["gsc_bin_index"] is not None\n                    and (nearest["num_matches"] or 0) > 0\n                ):\n                    lpayload = {\n                        "refcat": refcat,\n                        "ref_number": nearest["ref_number"],\n                        "gsc_bin_index": nearest["gsc_bin_index"],\n                    }\n                    lcache = WORK / f"{tname}_{refcat}_nearest_lightcurve.json"\n                    lobj, lcache_used = post_json(LIGHTCURVE_PATH, lpayload, lcache)\n                    lrows = parse_api_csv(lobj)\n                    lsum = lightcurve_summary(lrows, tra, tdec)\n                    lsum["query_payload"] = lpayload\n                    lsum["cache_used"] = lcache_used\n                    rres["lightcurve"] = lsum\n                    print(\n                        f"    lightcurve rows={lsum[\'row_count\']} "\n                        f"ai43437Rows={lsum[\'ai43437_row_count\']} "\n                        f"ai43437MinSep={lsum[\'ai43437_min_fitted_sep_arcsec\']}"\n                    )\n            else:\n                print(f"  {refcat}: no valid sources returned")\n\n            tres["refcats"][refcat] = rres\n\n            for s in sources[:10]:\n                all_rows.append({\n                    "target": tname,\n                    "target_ra_deg": tra,\n                    "target_dec_deg": tdec,\n                    "refcat": refcat,\n                    "ref_text": s["ref_text"],\n                    "ref_number": s["ref_number"],\n                    "gsc_bin_index": s["gsc_bin_index"],\n                    "num_matches": s["num_matches"],\n                    "stdmag": s["stdmag"],\n                    "class": s["class"],\n                    "catalog_ra_deg": s["catalog_ra_deg"],\n                    "catalog_dec_deg": s["catalog_dec_deg"],\n                    "pm_ra_cosdec_masyr": s["pm_ra_cosdec_masyr"],\n                    "pm_dec_masyr": s["pm_dec_masyr"],\n                    "pos_epoch_jyear": s["pos_epoch_jyear"],\n                    "proper_motion_propagated": s["proper_motion_propagated"],\n                    "propagated_ra_1951_deg": s["propagated_ra_1951_deg"],\n                    "propagated_dec_1951_deg": s["propagated_dec_1951_deg"],\n                    "current_catalog_sep_arcsec": s["current_catalog_sep_arcsec"],\n                    "propagated_1951_sep_arcsec": s["propagated_1951_sep_arcsec"],\n                })\n\n        results[tname] = tres\n\n    def best_for(target):\n        cands = []\n        for refcat in REFCATS:\n            n = results[target]["refcats"][refcat]["nearest"]\n            if n is not None:\n                cands.append(n)\n        return min(cands, key=lambda x: x["propagated_1951_sep_arcsec"]) if cands else None\n\n    best = {t["target"]: best_for(t["target"]) for t in targets}\n\n    print("\\nBEST 1951-PROPAGATED CATALOG MATCHES")\n    for name in ("science25", "q0030", "q0344"):\n        b = best[name]\n        if b is None:\n            print(f"  {name}: none")\n        else:\n            print(\n                f"  {name}: {b[\'refcat\']} {b[\'ref_text\']} "\n                f"sep1951={b[\'propagated_1951_sep_arcsec\']:.3f}\\" "\n                f"current={b[\'current_catalog_sep_arcsec\']:.3f}\\" "\n                f"numMatches={b[\'num_matches\']} stdmag={b[\'stdmag\']}"\n            )\n\n    payload = {\n        "stage": "ORDER01_DASCH_SCIENCE25_ANALOGUE_CATALOG_PROVENANCE_V028BQ",\n        "guards": {\n            "network_access": True,\n            "network_scope": "https://api.starglass.cfa.harvard.edu/public/",\n            "science_pixels_read": False,\n            "non_science_pixels_read": False,\n            "transient_detector_rerun": False,\n            "candidate_state_mutation": False,\n        },\n        "documented_api_contract": {\n            "querycat": {\n                "path": QUERYCAT_PATH,\n                "refcats": list(REFCATS),\n                "radius_arcsec": QUERY_RADIUS_ARCSEC,\n            },\n            "lightcurve": {\n                "path": LIGHTCURVE_PATH,\n                "trigger_propagated_sep_arcsec": LIGHTCURVE_TRIGGER_ARCSEC,\n                "selection": "nearest source in each refcat with numMatches>0 and required identifiers",\n            },\n        },\n        "plate_epoch_iso": PLATE_EPOCH_ISO,\n        "plate_epoch_jyear": PLATE_JYEAR,\n        "targets": results,\n        "best_1951_propagated_catalog_match": best,\n        "interpretive_boundary": (\n            "A nearby reference-catalog source becomes a plausible persistent-source "\n            "explanation only if its astrometry, including available proper motion, "\n            "is consistent with the 1951 image position. numMatches alone does not "\n            "prove identity. Likewise, absence of a close catalog source does not "\n            "establish transience; it leaves the image unresolved."\n        ),\n        "next_gate": {\n            "analogue_persistence_interpretation_may_run": True,\n        },\n    }\n\n    OUT_JSON.write_text(\n        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\\n",\n        encoding="utf-8",\n    )\n\n    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:\n        fields = list(all_rows[0].keys()) if all_rows else [\n            "target", "refcat", "ref_text", "propagated_1951_sep_arcsec"\n        ]\n        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")\n        w.writeheader()\n        w.writerows(all_rows)\n\n    md = [\n        "# ORDER 01 — #25 / q0030 / q0344 DASCH Catalog Provenance v028bq",\n        "",\n        f"- Query radius: **{QUERY_RADIUS_ARCSEC:.0f} arcsec** in APASS and ATLAS refcats.",\n        f"- Plate epoch used for PM propagation: **{PLATE_EPOCH_ISO}**.",\n        "",\n        "## Best propagated catalog matches",\n        "",\n        "| target | refcat | source | 1951 sep | current sep | DASCH numMatches | stdmag |",\n        "|---|---|---|---:|---:|---:|---:|",\n    ]\n    for name in ("science25", "q0030", "q0344"):\n        b = best[name]\n        if b is None:\n            md.append(f"| {name} | — | — | — | — | — | — |")\n        else:\n            md.append(\n                f"| {name} | {b[\'refcat\']} | {b[\'ref_text\']} | "\n                f"{b[\'propagated_1951_sep_arcsec\']:.3f}\\" | "\n                f"{b[\'current_catalog_sep_arcsec\']:.3f}\\" | "\n                f"{b[\'num_matches\']} | {b[\'stdmag\']} |"\n            )\n    md += [\n        "",\n        "Lightcurves are fetched only when the nearest propagated source lies within "\n        f"{LIGHTCURVE_TRIGGER_ARCSEC:.0f}\\" and has DASCH detections.",\n        "",\n        "Catalog proximity is evidence about source identity, not automatic proof of persistence.",\n    ]\n    OUT_MD.write_text("\\n".join(md), encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {OUT_MD}")\n    print("\\nSTAGE STATUS: PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'

ENTRY = """
    StageContract(
        stage_id="dasch_science25_analogue_catalog_provenance_v028bq",
        title="Query APASS/ATLAS provenance for #25, q0030 and q0344 with 1951 PM propagation",
        script="automation/stages/query_science25_analogue_catalog_provenance_v028bq.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_physical_morphology_v028ar_r1.json",
            "results/order01_native_full_v028/order01_dasch_platewide_morphology_metrics_v028bj.json",
            "results/order01_native_full_v028/order01_dasch_science25_direct_shape_neighbourhood_v028bo.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_science25_analogue_catalog_provenance_v028bq.json",
        ),
        dependencies=("dasch_science25_direct_visual_analogue_audit_v028bp",),
        network_required=True,
        notes="Six documented DR7 querycat calls max plus conditional nearest-source lightcurves; no pixels/detector/state mutation.",
    ),
"""


def register_stage(text):
    if 'stage_id="dasch_science25_analogue_catalog_provenance_v028bq"' in text:
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
    print("=" * 112)
    print("TRANSIENT AUTOMATION UPGRADE v0.2.2 — #25 ANALOGUE CATALOG PROVENANCE")
    print("=" * 112)
    print("THE UPGRADE ITSELF MAKES NO NETWORK CALLS.")
    print("Registered v028bq requires explicit --allow-network.")
    print("NO PIXELS ARE READ.")
    print("No candidate state is changed.\n")

    for p in (REGISTRY, RUNNER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p in (REGISTRY, RUNNER, AUTO / "__init__.py"):
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
        "Transient automation v0.2.2 - Order01 registry status",
        runner,
        count=1,
    )
    RUNNER.write_text(runner, encoding="utf-8")
    (AUTO / "__init__.py").write_text('__version__ = "0.2.2"\n', encoding="utf-8")

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
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    print(
        r'  & ".\.venv\Scripts\python.exe" -m automation.runner '
        r'verify-stage --stage dasch_science25_analogue_catalog_provenance_v028bq'
    )
    print("\nv028bq uses the DASCH public API only and performs no pixel access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
