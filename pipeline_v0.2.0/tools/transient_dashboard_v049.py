from __future__ import annotations

from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import argparse
import html
import json
import sys
import threading
import time
import webbrowser

ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CSS = """
body{font-family:system-ui;margin:0;background:#0d1117;color:#e6edf3}
header{background:#161b22;padding:20px}main{padding:20px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card,.panel{background:#161b22;border:1px solid #30363d;border-radius:9px;padding:14px}
.big{font-size:28px;font-weight:700}.muted{color:#9fb3c8}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left;font-size:13px}
.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}
.bar{height:15px;background:#30363d;border-radius:8px;overflow:hidden}.fill{height:100%;background:#3fb950}
@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}}
"""


def load(path: Path):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def registry_rows():
    try:
        from automation.registry_order01 import ORDER01_STAGES
        rows = []
        for stage in ORDER01_STAGES:
            products = [ROOT / x for x in stage.produces]
            complete = bool(products) and all(x.exists() for x in products)
            missing = [x for x in stage.requires if not (ROOT / x).exists()]
            status = "COMPLETE" if complete else ("BLOCKED/WAITING" if missing else "READY")
            access = []
            if getattr(stage, "network_access", False):
                access.append("network")
            if getattr(stage, "science_pixels_read", False) or getattr(stage, "non_science_pixels_read", False):
                access.append("pixels")
            rows.append((stage.stage_id, stage.title, status, " ".join(access)))
        return rows, None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def page():
    rows, error = registry_rows()
    counts = {name: sum(x[2] == name for x in rows) for name in ("COMPLETE", "READY", "BLOCKED/WAITING")}
    v48 = load(Path("results/census_scope_audit_v048.json"))
    wide = v48.get("wider_archive_pair_inventory", {})
    checkpoint = load(Path("results/wide_census_physical_timing_v049/checkpoint_v049.json"))
    final = load(Path("results/wide_census_physical_timing_v049.json"))

    remote_done = int(checkpoint.get("remote_done", 0))
    remote_total = int(checkpoint.get("remote_total", 60) or 60)
    pct = 100.0 * remote_done / remote_total if remote_total else 0.0
    classifications = final.get("classification_counts") or checkpoint.get("pair_classification_counts") or {}

    reg_html = "".join(
        f"<tr><td><code>{html.escape(stage_id)}</code><br><span class='muted'>{html.escape(title)}</span></td>"
        f"<td class='{'ok' if status == 'COMPLETE' else 'warn'}'>{status}</td><td>{html.escape(access)}</td></tr>"
        for stage_id, title, status, access in rows
    )
    if error:
        reg_html = f"<tr><td>{html.escape(error)}</td><td class='bad'>ERROR</td><td></td></tr>"

    class_html = "".join(
        f"<tr><td>{html.escape(str(name))}</td><td>{count}</td></tr>"
        for name, count in sorted(classifications.items())
    ) or "<tr><td colspan='2'>Awaiting pair evaluation</td></tr>"

    return f"""<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='3'>
<title>Historical Transient Investigation</title><style>{CSS}</style>
<header><h2 style='margin:0'>Historical Transient Investigation</h2>
<div class='muted'>Local read-only dashboard · refreshes every 3 seconds</div></header>
<main>
<div class='grid'>
<div class='card'><div class='muted'>Complete stages</div><div class='big'>{counts['COMPLETE']}</div></div>
<div class='card'><div class='muted'>Ready</div><div class='big'>{counts['READY']}</div></div>
<div class='card'><div class='muted'>Blocked / waiting</div><div class='big'>{counts['BLOCKED/WAITING']}</div></div>
<div class='card'><div class='muted'>≤15 min census pairs</div><div class='big'>{wide.get('le15_physical_timing_validation_queue_rows','—')}</div></div>
</div>
<div class='panel' style='margin-top:14px'><h2>Physical timing / plate identity v049</h2>
<div>APPLAUSE local: <strong>{checkpoint.get('applause_resolved',0)}/{checkpoint.get('applause_total',96)}</strong>
 · POSS: <strong>{checkpoint.get('poss_done',0)}/{checkpoint.get('poss_total',18)}</strong>
 · DASCH: <strong>{checkpoint.get('dasch_done',0)}/{checkpoint.get('dasch_total',42)}</strong></div>
<div class='bar' style='margin-top:10px'><div class='fill' style='width:{pct:.1f}%'></div></div>
<div class='muted'>{remote_done}/{remote_total} remote identities cached · {pct:.1f}%</div>
<table style='margin-top:10px'><tr><th>Pair state</th><th>Count</th></tr>{class_html}</table>
<div style='margin-top:8px'>Timing survivors awaiting footprint validation: <strong>{final.get('timing_survivor_count', checkpoint.get('timing_survivor_count','—'))}</strong>
 · unresolved: <strong>{final.get('unresolved_pair_count', checkpoint.get('unresolved_pair_count','—'))}</strong></div>
</div>
<div class='panel' style='margin-top:14px'><h2>Automation registry</h2>
<table><tr><th>Stage</th><th>Status</th><th>Access</th></tr>{reg_html}</table></div>
<div class='muted' style='margin-top:14px'>Updated {time.strftime('%Y-%m-%d %H:%M:%S')}</div>
</main>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        body = page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print("Historical Transient Investigation dashboard")
    print(url)
    print("Read-only. Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
