
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

TOTAL = 6293


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
            status = "COMPLETE" if complete else (
                "BLOCKED/WAITING" if missing else "READY"
            )
            access = []
            if getattr(stage, "network_access", False):
                access.append("network")
            if (
                getattr(stage, "science_pixels_read", False)
                or getattr(stage, "non_science_pixels_read", False)
            ):
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
.ok{color:#3fb950}.warn{color:#d29922}.bar{height:18px;background:#30363d;border-radius:9px;overflow:hidden}.fill{height:100%;background:#3fb950}"""


def page():
    rows, err = registry_rows()
    counts = {
        name: sum(row[2] == name for row in rows)
        for name in ("COMPLETE", "READY", "BLOCKED/WAITING")
    }

    state = load(Path("results/wide_census_detector_execution_v056/state_v056.json"))
    final = load(Path("results/wide_census_detector_execution_v056.json"))
    contract = load(Path("results/wide_census_disk_bounded_execution_contract_v055.json"))

    done = int(state.get("completed_tiles", TOTAL if final else 0))
    pct = 100.0 * done / TOTAL
    terminal = len(state.get("terminal", {}))
    free_gib = float(state.get("free_disk_bytes", 0)) / 1024**3 if state else 0

    reg = "".join(
        f"<tr><td><code>{html.escape(i)}</code><br><span class='muted'>{html.escape(t)}</span></td>"
        f"<td class='{'ok' if s == 'COMPLETE' else 'warn'}'>{s}</td><td>{html.escape(a)}</td></tr>"
        for i, t, s, a in rows
    )
    if err:
        reg = f"<tr><td>{html.escape(err)}</td><td>ERROR</td><td></td></tr>"

    return f"""<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='3'>
<title>Historical Transient Investigation</title><style>{CSS}</style>
<header><h2 style='margin:0'>Historical Transient Investigation</h2>
<div class='muted'>Heavy frozen-detector run · local read-only dashboard · refreshes every 3 seconds</div></header>
<main>
<div class='grid'>
<div class='card'><div class='muted'>Tiles complete</div><div class='big'>{done}/{TOTAL}</div></div>
<div class='card'><div class='muted'>Progress</div><div class='big'>{pct:.2f}%</div></div>
<div class='card'><div class='muted'>Terminal tile failures</div><div class='big'>{terminal}</div></div>
<div class='card'><div class='muted'>Free disk</div><div class='big'>{free_gib:.1f} GiB</div></div>
</div>

<div class='panel' style='margin-top:14px'><h2>Frozen detector v056</h2>
<div class='bar'><div class='fill' style='width:{pct:.3f}%'></div></div>
<div style='margin-top:10px'>
Last cycle completed: <strong>{state.get('last_cycle_completed_tiles','—')}</strong>
 · total opportunities: <strong>33</strong>
 · endpoints: <strong>53</strong></div>
<div>Science pixels: <strong>YES while running</strong>
 · frozen detector: <strong>YES</strong>
 · persistent pixel tiles: <strong>NO</strong></div>
<div class='muted'>Each native tile is content-hashed, detector output/audit metadata is checkpointed, then the in-memory pixels are released.</div>
</div>

<div class='panel' style='margin-top:14px'><h2>Completion result</h2>
<div>Accepted detector candidates: <strong>{final.get('accepted_native_detector_candidates_total','—')}</strong></div>
<div>Raw ≤10″ matches: <strong>{final.get('raw_le_10arcsec_match_count','—')}</strong>
 · raw ≤3″ matches: <strong>{final.get('raw_le_3arcsec_match_count','—')}</strong></div>
<div>Pairs with ≤10″: <strong>{final.get('pairs_with_raw_le_10arcsec_match','—')}</strong>
 · pairs with ≤3″: <strong>{final.get('pairs_with_raw_le_3arcsec_match','—')}</strong></div>
<div class='muted'>Raw coincidences are not transient classifications.</div>
</div>

<div class='panel' style='margin-top:14px'><h2>Automation registry</h2>
<table><tr><th>Stage</th><th>Status</th><th>Access</th></tr>{reg}</table></div>
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
    print("Historical Transient Investigation — heavy detector dashboard")
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
