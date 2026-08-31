from __future__ import annotations
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import argparse, json, threading, time, webbrowser

ROOT=Path.cwd(); HOST='127.0.0.1'; DEFAULT_PORT=8765

def loadj(p):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except Exception:return None

def stage_rows():
    rows=[]
    try:
        from automation.registry_order01 import ORDER01_STAGES
        complete=set()
        for s in ORDER01_STAGES:
            prods=[ROOT/p for p in (getattr(s,'produces',()) or ())]
            if prods and all(p.exists() for p in prods): complete.add(s.stage_id)
        for s in ORDER01_STAGES:
            prods=[ROOT/p for p in (getattr(s,'produces',()) or ())]
            reqs=[ROOT/p for p in (getattr(s,'requires',()) or ())]
            deps=list(getattr(s,'dependencies',()) or ())
            if prods and all(p.exists() for p in prods): st='COMPLETE'
            elif any(not p.exists() for p in reqs): st='BLOCKED'
            elif any(d not in complete for d in deps): st='WAITING'
            else: st='READY'
            rows.append({'id':s.stage_id,'title':getattr(s,'title',s.stage_id),'status':st,'network':bool(getattr(s,'network_access',False)),'pixels':bool(getattr(s,'science_pixels_read',False) or getattr(s,'non_science_pixels_read',False))})
    except Exception as e:
        rows.append({'id':'registry','title':f'Registry unavailable: {e}','status':'ERROR','network':False,'pixels':False})
    return rows

def snapshot():
    stages=stage_rows(); counts={k:sum(r['status']==k for r in stages) for k in ('COMPLETE','READY','WAITING','BLOCKED','ERROR')}
    timing=loadj(ROOT/'results/remaining_pair_physical_timing_census_v028cg.json') or {}
    g=loadj(ROOT/'results/order11_followup_match3_v042/order11_match3_gaia_epoch_report_v042.json') or {}
    a43=loadj(ROOT/'results/order11_followup_match3_v043a/order11_match3_local_astrometry_report_v043a.json') or {}
    a44=loadj(ROOT/'results/order11_followup_match3_v044/order11_match3_sparse_astrometry_report_v044.json') or {}
    f45=loadj(ROOT/'results/order11_followup_match3_v045/order11_match3_final_adjudication_v045.json') or {}
    return {'time':time.strftime('%Y-%m-%d %H:%M:%S'),'counts':counts,'stages':stages,'census_rows':len(timing.get('results',[])),'match3':{'gaia':g.get('classification'),'common_astrometry':a43.get('classification'),'sparse_astrometry':a44.get('classification'),'final':f45.get('classification'),'poss_morph':((f45.get('morphology') or {}).get('POSS') or {}).get('classification'),'dasch_morph':((f45.get('morphology') or {}).get('DASCH') or {}).get('classification')}}

HTML='''<!doctype html><html><head><meta charset="utf-8"><title>Transient Dashboard</title><style>body{font-family:system-ui,Segoe UI,Arial;margin:0;background:#10131a;color:#e8edf5}header{padding:20px 28px;background:#171c26;position:sticky;top:0}h1{margin:0;font-size:22px}.sub,.muted{color:#98a4b5}.wrap{padding:22px 28px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.card,.panel{background:#171c26;border:1px solid #293142;border-radius:10px;padding:15px}.big{font-size:28px;font-weight:700}.label{color:#9aa7b8;font-size:12px;text-transform:uppercase}.panel{margin-top:16px}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:8px;border-bottom:1px solid #293142;text-align:left}.COMPLETE{color:#67d391}.READY{color:#7eb6ff}.BLOCKED,.ERROR{color:#ff7d7d}.WAITING{color:#e5c36a}code{color:#b9d2ff}</style></head><body><header><h1>Historical Transient Investigation</h1><div class="sub">Local read-only dashboard · refreshes every 3 seconds</div></header><div class="wrap"><div id="app">Loading…</div></div><script>function e(x){return String(x??'—').replace(/[&<>]/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[s]));}async function go(){let d=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json()),c=d.counts,m=d.match3;let rows=d.stages.map(s=>`<tr><td><code>${e(s.id)}</code><div class="muted">${e(s.title)}</div></td><td class="${s.status}">${s.status}</td><td>${s.network?'network ':''}${s.pixels?'pixels':''}</td></tr>`).join('');document.getElementById('app').innerHTML=`<div class="cards"><div class="card"><div class="label">Complete stages</div><div class="big">${c.COMPLETE||0}</div></div><div class="card"><div class="label">Ready</div><div class="big">${c.READY||0}</div></div><div class="card"><div class="label">Blocked / waiting</div><div class="big">${(c.BLOCKED||0)+(c.WAITING||0)}</div></div><div class="card"><div class="label">Timing census rows</div><div class="big">${d.census_rows}</div></div></div><div class="panel"><h2>Order 11 · Match 3</h2><table><tr><th>Evidence</th><th>State</th></tr><tr><td>Gaia epoch association</td><td>${e(m.gaia)}</td></tr><tr><td>Common-reference astrometry</td><td>${e(m.common_astrometry)}</td></tr><tr><td>Sparse-field astrometry</td><td>${e(m.sparse_astrometry)}</td></tr><tr><td>POSS morphology</td><td>${e(m.poss_morph)}</td></tr><tr><td>DASCH morphology</td><td>${e(m.dasch_morph)}</td></tr><tr><td><b>Disposition</b></td><td><b>${e(m.final)}</b></td></tr></table></div><div class="panel"><h2>Automation registry</h2><table><tr><th>Stage</th><th>Status</th><th>Access</th></tr>${rows}</table></div><div class="muted" style="margin-top:12px">Updated ${e(d.time)}</div>`}go();setInterval(go,3000);</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/status'):
            b=json.dumps(snapshot()).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b);return
        if self.path=='/' or self.path.startswith('/index'):
            b=HTML.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b);return
        self.send_response(404);self.end_headers()
    def log_message(self,format,*args):pass

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=DEFAULT_PORT);ap.add_argument('--no-browser',action='store_true');a=ap.parse_args();url=f'http://{HOST}:{a.port}/';srv=ThreadingHTTPServer((HOST,a.port),Handler)
    print('Transient dashboard:',url);print('Read-only; Ctrl+C to stop.')
    if not a.no_browser:threading.Timer(0.5,lambda:webbrowser.open(url)).start()
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
if __name__=='__main__':main()
