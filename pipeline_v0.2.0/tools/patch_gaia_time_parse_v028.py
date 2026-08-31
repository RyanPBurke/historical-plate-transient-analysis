from pathlib import Path
import ast
import shutil
from datetime import datetime, timezone

p = Path("tools/gaia_static_order61_v028.py")

text = p.read_text(encoding="utf-8-sig")
tree = ast.parse(text, filename=str(p))

hits = [
    n for n in tree.body
    if isinstance(n, ast.FunctionDef)
    and n.name == "midpoint_time"
]

if len(hits) != 1:
    raise SystemExit(
        f"REFUSING: expected exactly one midpoint_time(); found {len(hits)}"
    )

node = hits[0]
lines = text.splitlines(keepends=True)

replacement = '''def midpoint_time(report):
    """
    Parse the canonical UTC overlap interval robustly.

    Canonical result files use ISO-8601 strings with explicit
    UTC offsets such as 1953-10-31T03:31:00+00:00.
    Python datetime parses these directly; the installed
    Astropy Time ISO parser does not.
    """

    from datetime import datetime, timezone

    start = report.get("overlap_start_utc")
    end = report.get("overlap_end_utc")

    if not start or not end:
        raise RuntimeError(
            "REFUSING: overlap start/end absent from complete report"
        )

    def parse_utc(value):
        s = str(value).strip()

        if s.endswith("Z"):
            s = s[:-1] + "+00:00"

        dt = datetime.fromisoformat(s)

        if dt.tzinfo is None:
            raise RuntimeError(
                f"REFUSING: timezone-naive canonical timestamp: {value!r}"
            )

        dt = dt.astimezone(timezone.utc)

        return Time(
            dt,
            scale="utc",
        )

    t0 = parse_utc(start)
    t1 = parse_utc(end)

    if not (t1 > t0):
        raise RuntimeError(
            "REFUSING: invalid overlap interval"
        )

    return t0 + (t1 - t0) / 2.0
'''

start = node.lineno - 1
end = node.end_lineno

patched = "".join(
    lines[:start]
    + [replacement + "\n"]
    + lines[end:]
)

# Syntax-check before touching the original.
ast.parse(
    patched,
    filename=str(p),
)

stamp = datetime.now(
    timezone.utc
).strftime("%Y%m%dT%H%M%SZ")

backup = p.with_name(
    p.name
    + f".pre_time_parse_fix_{stamp}"
)

shutil.copy2(
    p,
    backup,
)

p.write_text(
    patched,
    encoding="utf-8",
)

# Compile the actual written file too.
compile(
    p.read_text(encoding="utf-8"),
    str(p),
    "exec",
)

print("Gaia timestamp parser patch: PASS")
print("Backup:", backup)
print("Only midpoint_time() was replaced.")
print("No detector run.")
print("No image pixels read.")
print("No Gaia query performed by this patch.")
