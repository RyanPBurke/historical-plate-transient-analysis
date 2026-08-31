from pathlib import Path
import ast

ROOT = Path.cwd()

FILES = [
    ROOT / "src" / "transient_pipeline" / "catalogue_workers.py",
    ROOT / "src" / "transient_pipeline" / "cli.py",
]

WANTED_NAMES = {
    "load_manifest",
}

TOKENS = (
    "source_id",
    "ra_deg",
    "dec_deg",
    "resolve",
    "applause",
    "catalog",
    "catalogue",
    "manifest",
)

for path in FILES:
    if not path.is_file():
        raise SystemExit(f"Missing: {path}")

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    tree = ast.parse(
        text,
        filename=str(path),
    )

    print()
    print("=" * 88)
    print(path.relative_to(ROOT))
    print("=" * 88)

    found = 0

    for node in tree.body:
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        segment = (
            ast.get_source_segment(
                text,
                node,
            )
            or ""
        )

        lower = (
            node.name.lower()
            + "\n"
            + segment.lower()
        )

        relevant = (
            node.name in WANTED_NAMES
            or (
                "source_id" in lower
                and "ra_deg" in lower
                and "dec_deg" in lower
            )
            or (
                "manifest" in node.name.lower()
                and (
                    "ra_deg" in lower
                    or "source_id" in lower
                )
            )
            or (
                "applause" in lower
                and "resolve" in lower
            )
        )

        if not relevant:
            continue

        found += 1

        print()
        print(
            f"### {node.name} "
            f"[lines {node.lineno}-{node.end_lineno}]"
        )
        print(segment)

    if found == 0:
        print()
        print("<no relevant functions found>")

print()
print("=" * 88)
print("TARGET-MACHINERY INSPECTION COMPLETE")
print("=" * 88)
print("No archive request.")
print("No detector execution.")
