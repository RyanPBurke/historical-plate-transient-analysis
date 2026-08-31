from pathlib import Path
from datetime import datetime
import ast
import shutil

p = Path("tools/run_order61_whole_native_v028.py")

text = p.read_text(
    encoding="utf-8-sig"
)

tree = ast.parse(
    text,
    filename=str(p),
)

hits = [
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "find_jar"
]

if len(hits) != 1:
    raise SystemExit(
        f"REFUSING: expected one find_jar(); "
        f"found {len(hits)}"
    )

node = hits[0]

lines = text.splitlines(
    keepends=True
)

start = node.lineno - 1
end = node.end_lineno

replacement = '''def find_jar():
    """
    Resolve the exact SkyView JAR already validated by the
    completed pair-61 native-detector control.

    The prior control report is authoritative provenance.
    Recursive discovery is retained only as a guarded fallback.
    """

    control_report = (
        ROOT
        / "results"
        / "pair61_native_detector_control_v028"
        / "pair61_native_detector_control_report.json"
    )

    if control_report.is_file():
        report = json.loads(
            control_report.read_text(
                encoding="utf-8"
            )
        )

        recorded_path = str(
            report.get(
                "skyview_jar",
                ""
            )
        ).strip()

        recorded_sha = str(
            report.get(
                "skyview_jar_sha256",
                ""
            )
        ).strip().lower()

        if recorded_sha:
            if recorded_sha != EXPECTED_JAR_SHA:
                raise RuntimeError(
                    "REFUSING: prior pair61 report "
                    "records an unexpected SkyView "
                    f"JAR SHA: {recorded_sha}"
                )

        if recorded_path:
            candidate = Path(
                recorded_path
            )

            if not candidate.is_absolute():
                candidate = (
                    ROOT
                    / candidate
                )

            if candidate.is_file():
                actual = sha_file(
                    candidate
                )

                if actual != EXPECTED_JAR_SHA:
                    raise RuntimeError(
                        "REFUSING: previously validated "
                        "SkyView JAR path now has a "
                        "different SHA256: "
                        f"{candidate} -> {actual}"
                    )

                print(
                    "SkyView JAR recovered from "
                    "validated pair61 report:",
                    candidate,
                )

                return candidate

    # Guarded fallback only.
    scanned = []

    for candidate in ROOT.rglob(
        "*.jar"
    ):
        try:
            actual = sha_file(
                candidate
            )

            scanned.append(
                (
                    candidate,
                    actual,
                )
            )

            if actual == EXPECTED_JAR_SHA:
                print(
                    "SkyView JAR recovered by "
                    "fallback hash discovery:",
                    candidate,
                )

                return candidate

        except OSError:
            pass

    detail = "\\n".join(
        f"  {path} -> {digest}"
        for path, digest
        in scanned[:25]
    )

    raise RuntimeError(
        "REFUSING: validated SkyView JAR "
        "not found.\\n"
        f"JAR files scanned: {len(scanned)}"
        + (
            "\\n" + detail
            if detail
            else ""
        )
    )
'''

new_lines = (
    lines[:start]
    + [
        replacement
        + (
            "\n"
            if not replacement.endswith("\n")
            else ""
        )
    ]
    + lines[end:]
)

patched = "".join(
    new_lines
)

ast.parse(
    patched,
    filename=str(p),
)

backup = p.with_name(
    p.name
    + ".pre_jar_provenance_fix_"
    + datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
)

shutil.copy2(
    p,
    backup,
)

p.write_text(
    patched,
    encoding="utf-8",
)

print("JAR provenance patch: PASS")
print("Backup:", backup)
print(
    "Only find_jar() was replaced."
)
