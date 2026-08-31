
from __future__ import annotations
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import argparse, html, json, sys, threading, time, webbrowser

ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def load(path):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except Exception:
        return None

def registry_rows():
    try:
        from automation.registry_order01 import ORDER01_STAGES
        rows = []
        for s in ORDER01_STAGES:
            prod = [ROOT / x for x in s.produces]
            complete = bool(prod) and all(p.exists() for p in prod)
            missing = [x for x in getattr(s, "requires", ()) if not (ROOT / x).exists()]
            if complete:
                status = "COMPLETE"
            elif missing:
                status = "BLOCKED/WAITING"
            else:
                status = "READY"
            access = []
            if getattr(s, "network_access", False):
                access.append("network")
            if getattr(s, "science_pixels_read", False) or getattr(s, "non_science_pixels_read", False):
                access.append("pixels")
            rows.append((s.stage_id, s.title, status, " ".join(access)))
        return rows, None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"

def state():
    rr, err = registry_rows()
    counts = {k: sum(x[2] == k for x in rr) for k in ("COMPLETE", "READY", "BLOCKED/WAITING")}
    timing = load(Path("results/remaining_pair_physical_timing_census_v028cg.json")) or {}
    v45 = load(Path("results/order11_followup_match3_v045a/order11_match3_final_adjudication_v045a.json")) or {}
    v48 = load(Path("results/census_scope_audit_v048.json")) or {}
    return {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "registry": rr,
        "registry_error": err,
        "counts": counts,
        "timing_rows": len(timing.get("results", [])),
        "match3_disposition": v45.get("final_disposition") or v45.get("disposition"),
        "census": v48.get("wider_archive_pair_inventory") or {},
        "scope_classification": v48.get("scope_classification"),
    }

CSS = '''body{font-family:system-ui;margin:0;background:#0d1117;color:#e6edf3}header{background:#161b22;padding:20px}main{padding:20px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,.panel{background:#161b22;border:1px solid #30363d;border-radius:9px;padding:14px}.big{font-size:28px;font-weight:700}.muted{color:#9fb3c8}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left;font-size:13px}.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}}'''

def page():
    s = state()
    c = s["counts"]
    w = s["census"]
    gates = w.get("time_gate_counts") or {}
    def val(x):
        return "—" if x is None else html.escape(str(x))
    reg = "".join(
        f"<tr><td><code>{html.escape(a)}</code><br><span class='muted'>{html.escape(b)}</span></td>"
        f"<td class='{'ok' if st=='COMPLETE' else 'warn'}'>{st}</td><td>{html.escape(ac)}</td></tr>"
        for a,b,st,ac in s["registry"]
    )
    if s["registry_error"]:
        reg = f"<tr><td>registry<br><span class='muted'>{html.escape(s['registry_error'])}</span></td><td class='bad'>ERROR</td><td></td></tr>"
    return f'''<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=3>
<title>Historical Transient Investigation</title><style>{CSS}</style>
<header><h2 style="margin:0">Historical Transient Investigation</h2><div class=muted>Local read-only dashboard · refreshes every 3 seconds</div></header>
<main>
<div class=grid>
<div class=card><div class=muted>Complete stages</div><div class=big>{c["COMPLETE"]}</div></div>
<div class=card><div class=muted>Ready</div><div class=big>{c["READY"]}</div></div>
<div class=card><div class=muted>Blocked / waiting</div><div class=big>{c["BLOCKED/WAITING"]}</div></div>
<div class=card><div class=muted>Current timing census rows</div><div class=big>{s["timing_rows"]}</div></div>
</div>
<div class=panel style="margin-top:14px"><h2>Census scope</h2><table>
<tr><td>Scope classification</td><td>{val(s["scope_classification"])}</td></tr>
<tr><td>Wide catalogue-time candidate pairs</td><td>{val(w.get("rows"))}</td></tr>
<tr><td>Archive-pair families</td><td>{val(w.get("archive_pair_family_count"))}</td></tr>
<tr><td>≤5 min catalogue midpoint</td><td>{val(gates.get("LE5"))}</td></tr>
<tr><td>≤10 min cumulative</td><td>{val(gates.get("LE10_CUMULATIVE"))}</td></tr>
<tr><td>≤15 min cumulative</td><td>{val(gates.get("LE15_CUMULATIVE"))}</td></tr>
<tr><td>Queued for physical timing/provenance validation</td><td><strong>{val(w.get("le15_physical_timing_validation_queue_rows"))}</strong></td></tr>
</table></div>
<div class=panel style="margin-top:14px"><h2>Order 11 · Match 3</h2><table>
<tr><td><strong>Disposition</strong></td><td><strong>{val(s["match3_disposition"])}</strong></td></tr>
</table></div>
<div class=panel style="margin-top:14px"><h2>Automation registry</h2><table><tr><th>Stage</th><th>Status</th><th>Access</th></tr>{reg}</table></div>
<div class=muted style="margin-top:14px">Updated {s["updated"]}</div></main>'''

class H(BaseHTTPRequestHandler):
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    server = ThreadingHTTPServer((a.host, a.port), H)
    url = f"http://{a.host}:{a.port}/"
    print("Historical Transient Investigation dashboard")
    print(url)
    print("Read-only. Ctrl+C to stop.")
    if not a.no_browser:
        threading.Timer(.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
