from pathlib import Path
import ast
import shutil
from datetime import datetime

p = Path("tools/validate_remote_native_dasch_section_v028.py")

raw = p.read_text(
    encoding="utf-8-sig"
)

old = '''            sort_keys=True,
        ) + "\\n",
'''

new = '''            sort_keys=True,
            default=lambda o: (
                o.item()
                if hasattr(o, "item")
                else str(o)
            ),
        ) + "\\n",
'''

if raw.count(old) != 1:
    raise SystemExit(
        f"REFUSING: expected one JSON serialization site; "
        f"found {raw.count(old)}"
    )

backup = p.with_name(
    p.stem
    + ".pre_json_numpy_fix_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + p.suffix
)

shutil.copy2(
    p,
    backup,
)

patched = raw.replace(
    old,
    new,
    1,
)

ast.parse(
    patched,
    filename=str(p),
)

p.write_text(
    patched,
    encoding="utf-8",
)

print("JSON-only repair: PASS")
print("Backup:", backup)
print("No acquisition logic changed.")
print("No detector logic changed.")
