from pathlib import Path
import ast
import csv

ROOT = Path.cwd()
RUNNER = ROOT / "src" / "transient_pipeline" / "runner.py"
HANDOFF = ROOT / "research" / "SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv"

text = RUNNER.read_text(encoding="utf-8")
tree = ast.parse(text)

print("=" * 80)
print("STARGLASS WORKER — EXACT SOURCE")
print("=" * 80)

for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in {
        "_starglass_sidecar",
        "starglass_worker",
    }:
        print()
        print(ast.get_source_segment(text, node))
        print()

print("=" * 80)
print("FIRST 6 POSS PAIR ROWS")
print("=" * 80)

with HANDOFF.open("r", encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))

poss = [
    r for r in rows
    if str(r.get("poss_exposure_id") or "").startswith("POSS-I:")
]

fields = [
    "canonical_order",
    "legacy_rank",
    "pair_key",
    "exposure_a",
    "exposure_b",
    "ra_a_deg",
    "dec_a_deg",
    "ra_b_deg",
    "dec_b_deg",
    "poss_exposure_id",
    "true_wcs_intersection",
    "overlap_start_utc",
    "overlap_end_utc",
]

for r in poss[:6]:
    print("-" * 80)
    for f in fields:
        if f in r and str(r[f]).strip():
            print(f"{f}: {r[f]}")

print()
print("=" * 80)
print("TARGET/MANIFEST GENERATORS IN SOURCE")
print("=" * 80)

for path in sorted((ROOT / "src").rglob("*.py")):
    body = path.read_text(encoding="utf-8", errors="replace")

    hits = []
    for token in (
        "source_id",
        "ra_deg",
        "dec_deg",
        "analyze_fits_bytes(",
        "detect_array(",
        "load_manifest(",
    ):
        if token in body:
            hits.append(token)

    if len(hits) >= 3:
        print(path.relative_to(ROOT), "=>", ", ".join(hits))

print()
print("No archive request.")
print("No historical detector execution.")
