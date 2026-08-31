from __future__ import annotations
import csv
import io
import xml.etree.ElementTree as ET


def parse_votable_tabledata(text: str) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    # Ignore namespaces by local-name matching.
    fields = [el.attrib.get("name", "") for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "FIELD"]
    rows = []
    for tr in root.iter():
        if tr.tag.rsplit("}", 1)[-1] != "TR":
            continue
        vals = []
        for td in tr:
            if td.tag.rsplit("}", 1)[-1] == "TD":
                vals.append((td.text or "").strip())
        if vals:
            rows.append(dict(zip(fields, vals)))
    return rows


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))
