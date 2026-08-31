from pathlib import Path
import ast

FILES = [
    Path("tools/repair_remaining_poss_geometry_v028.py"),
    Path("tools/validate_pair61_direct_tpv_geometry_v028.py"),
    Path("tools/census_poss47_tpv_geometry_v028.py"),
    Path("tools/run_pair61_native_detector_control_v028.py"),
]

KEYS = (
    "dss",
    "poly",
    "world",
    "radec",
    "tpv",
    "rotation",
    "base_slice",
    "poss_native",
    "dasch_native",
)

for path in FILES:
    print()
    print("=" * 100)
    print(path)
    print("=" * 100)

    text = path.read_text(
        encoding="utf-8-sig"
    )

    tree = ast.parse(
        text,
        filename=str(path),
    )

    lines = text.splitlines()

    hits = []

    for node in tree.body:
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            name = node.name.lower()

            if any(
                k in name
                for k in KEYS
            ):
                hits.append(node)

    if not hits:
        print("<no matching functions>")
        continue

    for node in hits:
        end = getattr(
            node,
            "end_lineno",
            node.lineno,
        )

        print()
        print(
            f"--- {node.name} "
            f"[{node.lineno}-{end}] ---"
        )

        print(
            "\n".join(
                lines[
                    node.lineno - 1:end
                ]
            )
        )

print()
print("=" * 100)
print("READ-ONLY GEOMETRY INTERFACE INSPECTION COMPLETE")
print("=" * 100)
print("No files changed.")
print("No pixels read.")
print("No detector run.")
