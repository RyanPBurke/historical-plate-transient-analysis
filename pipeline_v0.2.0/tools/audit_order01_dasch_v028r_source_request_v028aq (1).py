#!/usr/bin/env python3
"""
ORDER 01 — exact v028r source-level platephot request audit v028aq

Purpose
-------
v028ap could not recover rank-associated query geometry from the v028r result
JSON. This stage therefore inspects the ORIGINAL v028r Python source directly.

It extracts:
  * functions containing 'platephot';
  * every call whose function/URL/arguments mention platephot;
  * assignments feeding RA, Dec, radius, APASS, source/reference variables;
  * cache filename construction for ai43437_sol0_rank*_apass_platephot.json;
  * nearby source lines around each relevant AST node;
  * literal/default values for radii and units where statically recoverable.

It also performs a targeted text search for:
  - 'platephot'
  - 'apass'
  - 'radius'
  - 'arcsec' / 'arcmin' / 'degree'
  - 'rank'
  - 'cache'
  - 'ra' / 'dec'

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
TOOLS = ROOT / "tools"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
SRC = TOOLS / "audit_order01_official_dasch_platephot_astrometry_v028r.py"

OUT_JSON = BASE / "order01_dasch_v028r_source_request_audit_v028aq.json"
OUT_TXT = BASE / "ORDER01_DASCH_V028R_SOURCE_REQUEST_AUDIT_V028AQ.txt"
OUT_MD = BASE / "ORDER01_DASCH_V028R_SOURCE_REQUEST_AUDIT_V028AQ.md"

SEARCH_TERMS = (
    "platephot","apass","radius","arcsec","arcmin","degree","deg",
    "cache","rank","source_id","reference","ra","dec","ai43437"
)


def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def node_text(src,node):
    try:
        return ast.get_source_segment(src,node)
    except Exception:
        return None


def snippet(lines,lineno,end_lineno=None,context=8):
    if lineno is None:
        return ""
    a=max(1,lineno-context)
    b=min(len(lines), (end_lineno or lineno)+context)
    return "\n".join(f"{i:05d}: {lines[i-1]}" for i in range(a,b+1))


def call_name(call):
    f=call.func
    if isinstance(f,ast.Name):
        return f.id
    if isinstance(f,ast.Attribute):
        parts=[]
        cur=f
        while isinstance(cur,ast.Attribute):
            parts.append(cur.attr)
            cur=cur.value
        if isinstance(cur,ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ast.dump(f,include_attributes=False)


def names_in(node):
    return sorted({n.id for n in ast.walk(node) if isinstance(n,ast.Name)})


def constants_in(node):
    vals=[]
    for n in ast.walk(node):
        if isinstance(n,ast.Constant) and isinstance(n.value,(str,int,float,bool)):
            vals.append(n.value)
    return vals


def relevant_text(s):
    low=(s or "").lower()
    return any(t in low for t in SEARCH_TERMS)


def main():
    print("="*128)
    print("ORDER 01 — EXACT v028r SOURCE-LEVEL PLATEPHOT REQUEST AUDIT v028aq")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,SRC):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    src=SRC.read_text(encoding="utf-8",errors="ignore")
    lines=src.splitlines()
    tree=ast.parse(src,filename=str(SRC))

    functions=[]
    calls=[]
    assignments=[]

    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            text=node_text(src,node) or ""
            if relevant_text(node.name+" "+text):
                functions.append({
                    "name":node.name,
                    "lineno":node.lineno,
                    "end_lineno":getattr(node,"end_lineno",node.lineno),
                    "args":[a.arg for a in node.args.args],
                    "defaults":[node_text(src,d) for d in node.args.defaults],
                    "names":names_in(node),
                    "constants":constants_in(node),
                    "source":text,
                    "snippet":snippet(lines,node.lineno,getattr(node,"end_lineno",node.lineno),3),
                })

        elif isinstance(node,ast.Call):
            text=node_text(src,node) or ""
            cname=call_name(node)
            if relevant_text(cname+" "+text):
                calls.append({
                    "call_name":cname,
                    "lineno":getattr(node,"lineno",None),
                    "end_lineno":getattr(node,"end_lineno",getattr(node,"lineno",None)),
                    "source":text,
                    "args":[node_text(src,a) for a in node.args],
                    "keywords":[
                        {"arg":kw.arg,"value":node_text(src,kw.value)}
                        for kw in node.keywords
                    ],
                    "names":names_in(node),
                    "constants":constants_in(node),
                    "snippet":snippet(lines,getattr(node,"lineno",None),
                                      getattr(node,"end_lineno",None),10),
                })

        elif isinstance(node,(ast.Assign,ast.AnnAssign,ast.NamedExpr)):
            text=node_text(src,node) or ""
            if relevant_text(text):
                assignments.append({
                    "lineno":getattr(node,"lineno",None),
                    "end_lineno":getattr(node,"end_lineno",getattr(node,"lineno",None)),
                    "source":text,
                    "names":names_in(node),
                    "constants":constants_in(node),
                    "snippet":snippet(lines,getattr(node,"lineno",None),
                                      getattr(node,"end_lineno",None),6),
                })

    # Exact line-level grep windows.
    grep_hits=[]
    for idx,line in enumerate(lines,1):
        low=line.lower()
        terms=[t for t in SEARCH_TERMS if t in low]
        if terms:
            grep_hits.append({
                "lineno":idx,
                "terms":terms,
                "line":line,
            })

    # Focused blocks around literal 'platephot' and cache filename pattern.
    focus_lines=set()
    for h in grep_hits:
        if "platephot" in h["terms"] or "apass" in h["terms"] or "radius" in h["terms"]:
            for j in range(max(1,h["lineno"]-12),min(len(lines),h["lineno"]+12)+1):
                focus_lines.add(j)

    ranges=[]
    start=prev=None
    for j in sorted(focus_lines):
        if start is None:
            start=prev=j
        elif j==prev+1:
            prev=j
        else:
            ranges.append((start,prev));start=prev=j
    if start is not None:
        ranges.append((start,prev))

    focus_blocks=[{
        "start_line":a,
        "end_line":b,
        "text":"\n".join(f"{i:05d}: {lines[i-1]}" for i in range(a,b+1))
    } for a,b in ranges]

    print(f"Relevant functions: {len(functions)}")
    for f in functions:
        print(f"  function {f['name']} lines {f['lineno']}-{f['end_lineno']} args={f['args']} defaults={f['defaults']}")

    print(f"\nRelevant calls: {len(calls)}")
    for c in calls[:30]:
        print(f"  line {c['lineno']}: {c['call_name']}")
        print(f"    {c['source'][:1200]}")

    print(f"\nRelevant assignments: {len(assignments)}")
    for a in assignments[:40]:
        print(f"  line {a['lineno']}: {a['source'][:1200]}")

    print(f"\nFocused source blocks: {len(focus_blocks)}")
    for b in focus_blocks:
        print(f"\n--- source lines {b['start_line']}-{b['end_line']} ---")
        print(b["text"][:8000])

    payload={
        "stage":"ORDER01_DASCH_V028R_SOURCE_REQUEST_AUDIT_V028AQ",
        "source_file":str(SRC.relative_to(ROOT)),
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "query_geometry_recovered_from_source_not_result_json":True,
        },
        "functions":functions,
        "calls":calls,
        "assignments":assignments,
        "grep_hits":grep_hits,
        "focus_blocks":focus_blocks,
        "interpretive_boundary":(
            "v028aq is source-provenance analysis only. It identifies how v028r "
            "constructed the platephot requests so that v028ao's absence of close "
            "official rows can be interpreted against the actual queried footprint."
        )
    }
    write_json(OUT_JSON,payload)

    parts=[
        "ORDER 01 — v028r source-level platephot request audit v028aq\n",
        "=== RELEVANT FUNCTIONS ===\n"
    ]
    for f in functions:
        parts.append(f"\n## {f['name']} lines {f['lineno']}-{f['end_lineno']}\n")
        parts.append(f["source"])
        parts.append("\n")

    parts.append("\n=== RELEVANT CALLS ===\n")
    for c in calls:
        parts.append(f"\n## line {c['lineno']} {c['call_name']}\n")
        parts.append(c["snippet"])
        parts.append("\n")

    parts.append("\n=== RELEVANT ASSIGNMENTS ===\n")
    for a in assignments:
        parts.append(f"\n## line {a['lineno']}\n{a['snippet']}\n")

    parts.append("\n=== FOCUSED PLATEPHOT/APASS/RADIUS BLOCKS ===\n")
    for b in focus_blocks:
        parts.append(f"\n## lines {b['start_line']}-{b['end_line']}\n{b['text']}\n")

    OUT_TXT.write_text("\n".join(parts),encoding="utf-8")

    md=[
        "# ORDER 01 — v028r Source-Level Platephot Request Audit v028aq","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- No endpoint state was changed.",
        "- Query geometry is recovered from the original v028r source code rather than inferred from the result JSON.","",
        f"Relevant functions: **{len(functions)}**.",
        f"Relevant calls: **{len(calls)}**.",
        f"Relevant assignments: **{len(assignments)}**.",
        f"Focused source blocks: **{len(focus_blocks)}**.","",
        "## Interpretation boundary","",
        payload["interpretive_boundary"]
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_TXT}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
