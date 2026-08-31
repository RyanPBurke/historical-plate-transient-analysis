#!/usr/bin/env python3
from pathlib import Path
import py_compile, shutil

ROOT=Path.cwd()
AUTO=ROOT/"automation"
REGISTRY=AUTO/"registry_order01.py"
RUNNER=AUTO/"runner.py"
STAGE=AUTO/"stages"/"replan_ai43437_prevalence_v028bc.py"
BACKUP=AUTO/"backups"/"pre_v008"
STAGE_CONTENT='#!/usr/bin/env python3\n"""\nORDER 01 — documented 10-arcmin DASCH platephot coverage replanner v028bc\n\nScientific/technical basis\n--------------------------\nDASCH DR7 Web API documentation states that POST /dasch/dr7/platephot returns\nsources covering approximately a radius of 10 arcminutes around the supplied\ncenter. v028ax used a deliberately conservative 5-arcmin radius because this\nhad not yet been checked against the current official documentation.\n\nv028bc replaces the *planned* 5\' expansion queue with a 10\' conservative\ncircular-coverage queue. It does not alter any science conclusion and does not\ndelete the v028ax queue; the latter remains preserved as historical provenance.\n\nNO NETWORK ACCESS.\nNO PIXELS READ.\nNO DETECTOR RERUN.\nNO CANDIDATE STATE MUTATION.\n"""\n\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom collections import defaultdict\nfrom pathlib import Path\n\nROOT = Path.cwd()\nBASE = ROOT / "results" / "order01_native_full_v028"\nAUTO = ROOT / "automation"\nQUEUES = AUTO / "queues"\n\nSTRICT = BASE / "order01_strict_match_triage_v028.csv"\nNATIVE = BASE / "order01_dasch_native_candidates.csv"\nOLD_PLAN = BASE / "order01_dasch_ai43437_prevalence_coverage_plan_v028ax.json"\nCERT = BASE / "order01_dasch_v028r_executor_contract_certified_v028bb.json"\n\nOUT_JSON = BASE / "order01_dasch_ai43437_prevalence_coverage_plan_v028bc.json"\nOUT_CSV = BASE / "order01_dasch_ai43437_prevalence_query_queue_v028bc.csv"\nQUEUE_JSON = QUEUES / "ai43437_prevalence_v028bc.json"\nOUT_MD = BASE / "ORDER01_DASCH_AI43437_PREVALENCE_COVERAGE_PLAN_V028BC.md"\n\nRANKS = [10,24,25,26,29,30]\nPLATE_ID = "ai43437"\nRADIUS_ARCSEC = 600.0\nDOC_URL = "https://dasch.cfa.harvard.edu/dr7/web-apis/"\nDOC_STATEMENT = (\n    "POST /dasch/dr7/platephot returned sources approximately cover a radius "\n    "of 10 arcminutes; source selection uses simple bounding RA/dec values."\n)\n\ndef read_csv(path):\n    with path.open("r", encoding="utf-8-sig", newline="") as fh:\n        return list(csv.DictReader(fh))\n\ndef f(v, default=None):\n    try:\n        if v is None or str(v).strip() == "":\n            return default\n        x = float(str(v).strip())\n        return x if math.isfinite(x) else default\n    except Exception:\n        return default\n\ndef i(v, default=None):\n    try:\n        if v is None or str(v).strip() == "":\n            return default\n        return int(float(str(v).strip()))\n    except Exception:\n        return default\n\ndef angsep_arcsec(ra1, dec1, ra2, dec2):\n    r1, r2 = math.radians(ra1), math.radians(ra2)\n    d1, d2 = math.radians(dec1), math.radians(dec2)\n    c = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)\n    c = max(-1.0, min(1.0, c))\n    return math.degrees(math.acos(c))*3600.0\n\ndef tangent_xy(ra, dec, ra0, dec0):\n    return (\n        (ra-ra0)*math.cos(math.radians(dec0))*3600.0,\n        (dec-dec0)*3600.0,\n    )\n\ndef build_neighbors(rows, radius):\n    if not rows:\n        return {}\n    ra0 = sum(r["ra_deg"] for r in rows)/len(rows)\n    dec0 = sum(r["dec_deg"] for r in rows)/len(rows)\n    cell = radius\n    buckets = defaultdict(list)\n    xy = {}\n    for idx,r in enumerate(rows):\n        x,y = tangent_xy(r["ra_deg"],r["dec_deg"],ra0,dec0)\n        xy[idx]=(x,y)\n        buckets[(math.floor(x/cell),math.floor(y/cell))].append(idx)\n\n    out={}\n    for idx,r in enumerate(rows):\n        x,y=xy[idx]\n        cx,cy=math.floor(x/cell),math.floor(y/cell)\n        cand=[]\n        for dx in (-1,0,1):\n            for dy in (-1,0,1):\n                cand.extend(buckets.get((cx+dx,cy+dy),[]))\n        hit=set()\n        for j in cand:\n            q=rows[j]\n            if angsep_arcsec(r["ra_deg"],r["dec_deg"],q["ra_deg"],q["dec_deg"]) <= radius:\n                hit.add(j)\n        out[idx]=hit\n    return out\n\ndef greedy_cover(rows, radius):\n    if not rows:\n        return []\n    neigh=build_neighbors(rows,radius)\n    uncovered=set(range(len(rows)))\n    plan=[]\n    while uncovered:\n        best=None\n        best_cover=set()\n        best_key=None\n        # Candidate positions are valid query centres; deterministic tiebreak.\n        for idx in sorted(uncovered):\n            cover=neigh[idx] & uncovered\n            r=rows[idx]\n            key=(\n                len(cover),\n                f(r.get("snr"),-1e99),\n                -(i(r.get("candidate_index"),10**12)),\n                -idx,\n            )\n            if best_key is None or key>best_key:\n                best_key=key\n                best=idx\n                best_cover=cover\n        if best is None or not best_cover:\n            raise RuntimeError("greedy planner made no progress")\n        r=rows[best]\n        plan.append({\n            "queue_order":len(plan)+1,\n            "center_ra_deg":r["ra_deg"],\n            "center_dec_deg":r["dec_deg"],\n            "center_tile_id":r["tile_id"],\n            "center_candidate_index":r["candidate_index"],\n            "center_detector_snr":r["snr"],\n            "native_candidates_covered":len(best_cover),\n            "covered_row_indices":sorted(best_cover),\n        })\n        uncovered -= best_cover\n    return plan\n\ndef write_json(path,obj):\n    path.parent.mkdir(parents=True,exist_ok=True)\n    tmp=path.with_suffix(path.suffix+".tmp")\n    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\\n",encoding="utf-8")\n    tmp.replace(path)\n\ndef write_csv(path,rows,fields):\n    path.parent.mkdir(parents=True,exist_ok=True)\n    tmp=path.with_suffix(path.suffix+".tmp")\n    with tmp.open("w",encoding="utf-8",newline="") as fh:\n        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")\n        w.writeheader()\n        w.writerows(rows)\n    tmp.replace(path)\n\ndef main():\n    print("="*128)\n    print("ORDER 01 — DOCUMENTED 10\' DASCH PLATEPHOT COVERAGE REPLANNER v028bc")\n    print("="*128)\n    print("NO NETWORK ACCESS.")\n    print("SCIENCE PIXELS ARE NOT READ.")\n    print("NON-SCIENCE PIXELS ARE NOT READ.")\n    print("Frozen transient detector is NOT rerun.\\n")\n\n    for p in (STRICT,NATIVE,OLD_PLAN,CERT):\n        if not p.is_file():\n            print(f"FAIL missing input: {p}")\n            return 2\n\n    cert=json.loads(CERT.read_text(encoding="utf-8"))\n    if not cert.get("executor_gate",{}).get("network_executor_may_be_built"):\n        raise RuntimeError("certified executor gate is not true")\n\n    strict_rows=read_csv(STRICT)\n    native_rows=read_csv(NATIVE)\n    strict={i(r["strict_rank"]):r for r in strict_rows if i(r.get("strict_rank")) in RANKS}\n    if sorted(strict)!=RANKS:\n        raise RuntimeError("strict-rank set mismatch")\n\n    science_keys=set()\n    existing_centres=[]\n    for rank in RANKS:\n        r=strict[rank]\n        pra,pdec=f(r.get("poss_ra_deg")),f(r.get("poss_dec_deg"))\n        dra,ddec=f(r.get("dasch_ra_deg")),f(r.get("dasch_dec_deg"))\n        existing_centres.append({\n            "rank":rank,\n            "ra_deg":(pra+dra)/2.0,\n            "dec_deg":(pdec+ddec)/2.0,\n        })\n        science_keys.add((str(r.get("dasch_tile_id","")),i(r.get("dasch_candidate_index"))))\n\n    usable=[]\n    for r in native_rows:\n        ra,dec=f(r.get("ra_deg")),f(r.get("dec_deg"))\n        if ra is None or dec is None:\n            continue\n        key=(str(r.get("tile_id","")),i(r.get("candidate_index")))\n        usable.append({\n            "tile_id":key[0],\n            "candidate_index":key[1],\n            "ra_deg":ra,\n            "dec_deg":dec,\n            "snr":f(r.get("snr")),\n            "polarity":i(r.get("polarity")),\n            "is_science":key in science_keys,\n            "existing_query_nearest_sep_arcsec":min(\n                angsep_arcsec(ra,dec,c["ra_deg"],c["dec_deg"])\n                for c in existing_centres\n            ),\n        })\n\n    non_science=[r for r in usable if not r["is_science"]]\n    existing=[r for r in non_science if r["existing_query_nearest_sep_arcsec"]<=RADIUS_ARCSEC]\n    uncovered=[r for r in non_science if r["existing_query_nearest_sep_arcsec"]>RADIUS_ARCSEC]\n\n    plan=greedy_cover(uncovered,RADIUS_ARCSEC)\n\n    queue=[]\n    cumul=0\n    for item in plan:\n        cumul += item["native_candidates_covered"]\n        queue.append({\n            "queue_order":item["queue_order"],\n            "plate_id":PLATE_ID,\n            "solution":0,\n            "refcat":"apass",\n            "center_ra_deg":item["center_ra_deg"],\n            "center_dec_deg":item["center_dec_deg"],\n            "documented_radius_arcsec":RADIUS_ARCSEC,\n            "native_candidates_covered":item["native_candidates_covered"],\n            "cumulative_native_candidates_covered":cumul,\n            "center_tile_id":item["center_tile_id"],\n            "center_candidate_index":item["center_candidate_index"],\n            "center_detector_snr":item["center_detector_snr"],\n            "network_status":"NOT_REQUESTED",\n            "science_status":"PLANNED_ONLY",\n        })\n\n    if cumul != len(uncovered):\n        raise RuntimeError(f"coverage mismatch {cumul} != {len(uncovered)}")\n\n    old=json.loads(OLD_PLAN.read_text(encoding="utf-8"))\n    old_n=old.get("summary",{}).get("additional_query_centres_planned")\n    reduction=(1-len(queue)/old_n) if old_n else None\n\n    print(f"Non-science native rows:                         {len(non_science)}")\n    print(f"Covered by existing six queries at <=10\':       {len(existing)}")\n    print(f"Still requiring planned coverage:                {len(uncovered)}")\n    print(f"v028ax 5\' planned additional centres:            {old_n}")\n    print(f"v028bc documented-10\' additional centres:        {len(queue)}")\n    if reduction is not None:\n        print(f"Planned request-count reduction vs v028ax:       {100*reduction:.2f}%")\n    if queue:\n        counts=[r["native_candidates_covered"] for r in queue]\n        counts_sorted=sorted(counts)\n        print(f"Native detections per new centre: median={counts_sorted[len(counts)//2]} max={max(counts)}")\n\n    payload={\n        "stage":"ORDER01_DASCH_AI43437_PREVALENCE_COVERAGE_PLAN_V028BC",\n        "guards":{\n            "network_access":False,\n            "science_pixels_read":False,\n            "non_science_pixels_read":False,\n            "transient_detector_rerun":False,\n            "candidate_state_mutation":False,\n        },\n        "documentation_basis":{\n            "url":DOC_URL,\n            "documented_platephot_radius_arcmin":10.0,\n            "documented_platephot_radius_arcsec":RADIUS_ARCSEC,\n            "statement":DOC_STATEMENT,\n            "coverage_shape_note":"Documentation says selection uses simple bounding RA/dec values; planner retains circular <=10\' membership as a conservative subset.",\n        },\n        "summary":{\n            "non_science_native_rows":len(non_science),\n            "existing_queries_cover_non_science_rows":len(existing),\n            "outside_existing_documented_coverage_rows":len(uncovered),\n            "v028ax_additional_centres":old_n,\n            "v028bc_additional_centres":len(queue),\n            "request_count_reduction_fraction_vs_v028ax":reduction,\n            "planned_rows_covered":cumul,\n        },\n        "existing_query_centres":existing_centres,\n        "planned_query_queue":queue,\n        "supersedes_for_execution":"AI43437_PREVALENCE_V028AX",\n        "preserves_v028ax_as_provenance":True,\n        "interpretive_boundary":(\n            "v028bc changes only the future query plan. It does not alter any "\n            "existing scientific classification or imply coverage for regions "\n            "that have not yet been queried."\n        ),\n    }\n\n    queue_payload={\n        "queue_id":"AI43437_PREVALENCE_V028BC",\n        "queue_version":1,\n        "plate_id":PLATE_ID,\n        "status":"PLANNED_NOT_FETCHED",\n        "documented_radius_arcsec":RADIUS_ARCSEC,\n        "supersedes_for_execution":"AI43437_PREVALENCE_V028AX",\n        "items":queue,\n        "guards":{\n            "created_without_network":True,\n            "candidate_state_mutation":False,\n        },\n    }\n\n    write_json(OUT_JSON,payload)\n    write_json(QUEUE_JSON,queue_payload)\n    fields=list(queue[0].keys()) if queue else [\n        "queue_order","plate_id","solution","refcat","center_ra_deg","center_dec_deg"\n    ]\n    write_csv(OUT_CSV,queue,fields)\n\n    md=[\n        "# ORDER 01 — Documented 10′ Platephot Coverage Plan v028bc","",\n        f"- Non-science native detections: **{len(non_science)}**.",\n        f"- Already covered by the six existing queries at ≤10′: **{len(existing)}**.",\n        f"- Additional query centres: **{len(queue)}**.",\n        f"- Previous v028ax 5′ plan: **{old_n}**.",\n        f"- Reduction: **{(100*reduction if reduction is not None else float(\'nan\')):.2f}%**.","",\n        "The v028ax queue is preserved but superseded for execution.",\n        "No network request was made."\n    ]\n    OUT_MD.write_text("\\n".join(md),encoding="utf-8")\n\n    print("\\nOutputs:")\n    print(f"  {OUT_JSON}")\n    print(f"  {OUT_CSV}")\n    print(f"  {QUEUE_JSON}")\n    print(f"  {OUT_MD}")\n    print()\n    print("NO network query was made.")\n    print("SCIENCE PIXELS WERE NOT READ.")\n    print("NON-SCIENCE PIXELS WERE NOT READ.")\n    print("Transient detector was NOT rerun.")\n    print("No endpoint state was changed.")\n    return 0\n\nif __name__=="__main__":\n    raise SystemExit(main())\n'

REGISTRY_ENTRY = """
    StageContract(
        stage_id="dasch_prevalence_replan_10arcmin_v028bc",
        title="Replan ai43437 prevalence coverage using documented 10-arcmin platephot radius",
        script="automation/stages/replan_ai43437_prevalence_v028bc.py",
        requires=(
            "results/order01_native_full_v028/order01_dasch_ai43437_prevalence_coverage_plan_v028ax.json",
            "results/order01_native_full_v028/order01_dasch_v028r_executor_contract_certified_v028bb.json",
        ),
        produces=(
            "results/order01_native_full_v028/order01_dasch_ai43437_prevalence_coverage_plan_v028bc.json",
            "automation/queues/ai43437_prevalence_v028bc.json",
        ),
        dependencies=("dasch_executor_contract_certified_v028bb",),
        notes="Supersedes the conservative 5-arcmin future execution plan using official documented 10-arcmin platephot coverage.",
    ),
"""

def main():
    print("="*112)
    print("TRANSIENT AUTOMATION UPGRADE v0.0.8 — DOCUMENTED COVERAGE REPLAN")
    print("="*112)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("No existing science/result artifact is modified.")
    print("No candidate state is changed.\n")

    for p in (REGISTRY,RUNNER):
        if not p.is_file():
            print(f"FAIL missing automation file: {p}")
            return 2

    BACKUP.mkdir(parents=True,exist_ok=True)
    for p in (REGISTRY,RUNNER,AUTO/"__init__.py"):
        if p.is_file():
            dst=BACKUP/p.name
            if not dst.exists():
                shutil.copy2(p,dst)

    if STAGE.exists():
        print(f"FAIL stage already exists: {STAGE}")
        return 2

    STAGE.parent.mkdir(parents=True,exist_ok=True)
    STAGE.write_text(STAGE_CONTENT,encoding="utf-8")
    print(f"Created: {STAGE.relative_to(ROOT)}")

    reg=REGISTRY.read_text(encoding="utf-8")
    marker="\n]\n\ndef by_id():"
    if marker not in reg:
        print("FAIL registry insertion marker not found.")
        return 3
    reg=reg.replace(marker,"\n"+REGISTRY_ENTRY.rstrip()+"\n]\n\ndef by_id():",1)
    REGISTRY.write_text(reg,encoding="utf-8")
    print("Registered: dasch_prevalence_replan_10arcmin_v028bc")

    runner=RUNNER.read_text(encoding="utf-8")
    runner=runner.replace(
        'print("Transient automation v0.0.7 - Order01 registry status\\n")',
        'print("Transient automation v0.0.8 - Order01 registry status\\n")',
    )
    RUNNER.write_text(runner,encoding="utf-8")
    (AUTO/"__init__.py").write_text('__version__ = "0.0.8"\n',encoding="utf-8")

    failures=[]
    py_files=sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts)
    print(f"\nCompiling automation package ({len(py_files)} Python files):")
    for p in py_files:
        try:
            py_compile.compile(str(p),doraise=True)
            print(f"  PASS {p.relative_to(ROOT)}")
        except Exception as exc:
            failures.append((p,exc))
            print(f"  FAIL {p.relative_to(ROOT)}: {exc}")
    if failures:
        print("\nAUTOMATION UPGRADE STATUS: FAIL")
        return 4

    print("\nAUTOMATION UPGRADE STATUS: PASS")
    print("\nNext commands:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage dasch_prevalence_replan_10arcmin_v028bc')
    print("\nNo network request will be made by v028bc.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
