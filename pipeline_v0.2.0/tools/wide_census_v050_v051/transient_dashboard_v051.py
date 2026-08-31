
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


def load(path):
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


CSS = """body{font-family:system-ui;margin:0;background:#0d1117;color:#e6edf3}
header{background:#161b22;padding:20px}main{padding:20px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card,.panel{background:#161b22;border:1px solid #30363d;border-radius:9px;padding:14px}
.big{font-size:28px;font-weight:700}.muted{color:#9fb3c8}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left;font-size:13px}
.ok{color:#3fb950}.warn{color:#d29922}"""


def page():
    rows, err = registry_rows()
    counts = {
        name: sum(row[2] == name for row in rows)
        for name in ("COMPLETE", "READY", "BLOCKED/WAITING")
    }

    v050 = load(Path("results/wide_census_physical_timing_final_v050.json"))
    v051 = load(Path("results/wide_census_footprint_plan_v051.json"))

    registry_html = "".join(
        f"<tr><td><code>{html.escape(stage_id)}</code><br><span class='muted'>{html.escape(title)}</span></td>"
        f"<td class='{'ok' if status == 'COMPLETE' else 'warn'}'>{status}</td><td>{html.escape(access)}</td></tr>"
        for stage_id, title, status, access in rows
    )
    if err:
        registry_html = f"<tr><td>{html.escape(err)}</td><td>ERROR</td><td></td></tr>"

    timing_counts = v050.get("classification_counts") or {}
    coarse_counts = v051.get("coarse_priority_counts") or {}

    return f"""<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='3'>
<title>Historical Transient Investigation</title><style>{CSS}</style>
<header><h2 style='margin:0'>Historical Transient Investigation</h2>
<div class='muted'>Local read-only dashboard · refreshes every 3 seconds</div></header>
<main>
<div class='grid'>
<div class='card'><div class='muted'>Complete stages</div><div class='big'>{counts['COMPLETE']}</div></div>
<div class='card'><div class='muted'>Ready</div><div class='big'>{counts['READY']}</div></div>
<div class='card'><div class='muted'>Timing survivors</div><div class='big'>{v050.get('timing_survivor_count','—')}</div></div>
<div class='card'><div class='muted'>Exact-footprint queue</div><div class='big'>{v051.get('exact_footprint_queue_count','—')}</div></div>
</div>

<div class='panel' style='margin-top:14px'><h2>Final timing census v050</h2>
<div>Timing unresolved: <strong>{v050.get('timing_unresolved_pair_count','—')}</strong>
 · provenance unresolved but already time-excluded:
<strong>{v050.get('provenance_unresolved_but_timing_nonopportunity_count','—')}</strong></div>
<table style='margin-top:8px'>
{''.join(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k,v in sorted(timing_counts.items()))}
</table></div>

<div class='panel' style='margin-top:14px'><h2>Footprint / independence plan v051</h2>
<div>Entered from timing: <strong>{v051.get('timing_survivors_entering','—')}</strong>
 · closed before exact geometry: <strong>{v051.get('closed_before_exact_footprint_count','—')}</strong>
 · queued: <strong>{v051.get('exact_footprint_queue_count','—')}</strong></div>
<div>Unique APPLAUSE plates: <strong>{v051.get('unique_applause_physical_plates_needed','—')}</strong>
 · DASCH plates: <strong>{v051.get('unique_dasch_plates_needed','—')}</strong></div>
<table style='margin-top:8px'>
{''.join(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k,v in sorted(coarse_counts.items()))}
</table>
<div class='muted'>Coarse geometry is prioritization only. Exact archive footprint is still required.</div>
</div>

<div class='panel' style='margin-top:14px'><h2>Automation registry</h2>
<table><tr><th>Stage</th><th>Status</th><th>Access</th></tr>{registry_html}</table></div>
<div class='muted' style='margin-top:14px'>Updated {time.strftime('%Y-%m-%d %H:%M:%S')}</div>
</main>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        body = page().encode()
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
