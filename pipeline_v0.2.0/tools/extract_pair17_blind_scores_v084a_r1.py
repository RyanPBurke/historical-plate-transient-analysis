#!/usr/bin/env python3
"""
Operational repair for blind-score extraction after Google Sheets export.

Scientific/manual-review semantics are unchanged. The only repair is to
canonicalize spreadsheet confidence values such as 5.0 -> "5" when they are
exact integers in the allowed range 1..5.

No blind mapping is read and no unblinding is performed.
"""
from pathlib import Path
import csv, hashlib, json, math, re, sys, zipfile
import xml.etree.ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

EXPECTED_XLSX_SHA = "c46b4c6589e68ae051b09cd9a8234d11a6565ff76a7c5a9f8b15993970980f1a"
SHEET_NAME = "Blind Review"

FEATURE = {"ABSENT","WEAK_OR_AMBIGUOUS","DEFINITE"}
MORPH = {"STELLAR_COMPACT","NONSTELLAR_ARTIFACT","EXTENDED_OR_BLENDED","AMBIGUOUS"}
CONTEXT = {"CLEAN","CROWDED","DEFECT_AFFECTED","EDGE_OR_CLIPPED","AMBIGUOUS"}
CONF = {"1","2","3","4","5"}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def colnum(ref):
    m=re.match(r"([A-Z]+)",ref)
    n=0
    for ch in m.group(1):
        n=n*26+ord(ch)-64
    return n

def normalize_confidence(raw, code):
    s=str(raw).strip()
    if s in CONF:
        return s

    # Google Sheets commonly serializes numeric cells as e.g. "5.0".
    try:
        x=float(s)
    except Exception:
        raise RuntimeError(f"{code}: invalid confidence {raw!r}")

    if not math.isfinite(x):
        raise RuntimeError(f"{code}: invalid confidence {raw!r}")

    xi=int(round(x))
    if abs(x-xi) > 1e-12 or str(xi) not in CONF:
        raise RuntimeError(f"{code}: invalid confidence {raw!r}")

    return str(xi)

def main():
    if len(sys.argv)!=4:
        raise SystemExit("usage: extractor.py INPUT.xlsx OUTPUT.csv OUTPUT.json")

    src,out_csv,out_json=map(Path,sys.argv[1:])
    actual=sha(src)

    if actual!=EXPECTED_XLSX_SHA:
        raise RuntimeError(f"Submitted workbook SHA mismatch: {actual}")

    with zipfile.ZipFile(src) as z:
        shared=[]
        if "xl/sharedStrings.xml" in z.namelist():
            root=ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{NS_MAIN}}}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")))

        wb=ET.fromstring(z.read("xl/workbook.xml"))
        rid=None
        for s in wb.find(f"{{{NS_MAIN}}}sheets"):
            if s.attrib.get("name")==SHEET_NAME:
                rid=s.attrib.get(f"{{{NS_REL}}}id")
                break
        if not rid:
            raise RuntimeError("Blind Review sheet not found")

        rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target=None
        for r in rels:
            if r.attrib.get("Id")==rid:
                target=r.attrib["Target"]
                break
        if not target:
            raise RuntimeError("Blind Review worksheet relationship missing")

        sheet_path="xl/"+target.lstrip("/")
        root=ET.fromstring(z.read(sheet_path))

        vals={}
        for c in root.iter(f"{{{NS_MAIN}}}c"):
            ref=c.attrib.get("r")
            if not ref:
                continue
            row=int(re.search(r"\d+",ref).group())
            col=colnum(ref)

            if not (5<=row<=36 and 1<=col<=6):
                continue

            typ=c.attrib.get("t")
            v=c.find(f"{{{NS_MAIN}}}v")
            isel=c.find(f"{{{NS_MAIN}}}is")
            value=""

            if typ=="s" and v is not None:
                value=shared[int(v.text)]
            elif typ=="inlineStr" and isel is not None:
                value="".join(t.text or "" for t in isel.iter(f"{{{NS_MAIN}}}t"))
            elif v is not None:
                value=v.text or ""

            vals[(row,col)]=value

    rows=[]
    normalized_confidence_cells=0

    for r in range(5,37):
        row=[str(vals.get((r,c),"")).strip() for c in range(1,7)]
        code,feat,morph,ctx,conf_raw,notes=row
        expected=f"B{r-4:03d}"

        if code!=expected:
            raise RuntimeError(f"Expected {expected} at row {r}; got {code!r}")
        if feat not in FEATURE:
            raise RuntimeError(f"{code}: invalid feature {feat!r}")
        if morph not in MORPH:
            raise RuntimeError(f"{code}: invalid morphology {morph!r}")
        if ctx not in CONTEXT:
            raise RuntimeError(f"{code}: invalid local_context {ctx!r}")

        conf=normalize_confidence(conf_raw, code)
        if conf != conf_raw:
            normalized_confidence_cells += 1

        rows.append({
            "blind_code":code,
            "feature_at_crosshair":feat,
            "morphology":morph,
            "local_context":ctx,
            "confidence_1_to_5":conf,
            "notes":notes,
        })

    out_csv.parent.mkdir(parents=True,exist_ok=True)
    with out_csv.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    report={
        "status":"COMPLETE",
        "analysis_kind":"pair17_blind_score_extraction_v084a_r1",
        "operational_repair":"canonicalize integer-equivalent spreadsheet confidence values (e.g. 5.0 -> 5)",
        "source_workbook_sha256":actual,
        "rows":32,
        "canonical_csv_sha256":sha(out_csv),
        "feature_counts":dict(Counter(r["feature_at_crosshair"] for r in rows)),
        "morphology_counts":dict(Counter(r["morphology"] for r in rows)),
        "local_context_counts":dict(Counter(r["local_context"] for r in rows)),
        "confidence_counts":dict(Counter(r["confidence_1_to_5"] for r in rows)),
        "normalized_confidence_cells":normalized_confidence_cells,
        "all_scores_complete":True,
        "blind_mapping_read":False,
        "unblinding_performed":False,
        "manual_scores_modified":False
    }

    out_json.write_text(
        json.dumps(report,indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    print(json.dumps(report,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
