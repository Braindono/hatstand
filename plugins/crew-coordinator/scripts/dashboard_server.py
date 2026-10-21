"""Live dashboard for Crew Coordinator. Standard library only.

    python3 harness.py serve            -> http://127.0.0.1:7717  (live, polls every 2s; loopback hosts only)
    python3 harness.py dashboard        -> _harness/dashboard.html (static snapshot)
    http://127.0.0.1:7717/operator      -> which chats need /update, a restart or a new chat
    http://127.0.0.1:7717/health        -> corpus weight + prune candidates (tick to archive)
"""
import html as _html
import json
import hmac
import os
import secrets
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "dashboard.html")


def _page(snapshot=None):
    html = open(TEMPLATE, encoding="utf-8").read()
    if snapshot is not None:
        blob = json.dumps(snapshot, default=list).replace("</", "<\\/")
        html = html.replace("/*__SNAPSHOT__*/null", blob)
    return html


OP_CSS = """:root{--bg:#fff;--fg:#1b1b1b;--mut:#6b6b6b;--line:#e3e3e3;--warn:#b35c00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#ececec;--mut:#9a9a9a;--line:#2e2e2e;--warn:#f0a040;--bad:#ff7a70}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif;margin:24px}
h1{font-size:18px;margin:0 0 4px}p{color:var(--mut);margin:0 0 16px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
h2{font-size:15px;margin:18px 0 6px}th{color:var(--mut);font-weight:500}td.w{color:var(--warn)}td.b{color:var(--bad);font-weight:600}tr.q td{color:var(--mut)}"""


def operator_page(h, csrf=""):
    """Operator view: one row per live agent sorted by need, plus pending approvals (Approve/Deny, code typed by hand)."""
    e = lambda x: _html.escape(str(x))
    rows = h.operator_rows()
    tr = []
    for r in rows:
        act = ("new chat / restart" if r["restart"] or r["behind"] else
               "/handoff now" if r["ctx"] == "now" else "/update" if r["unread"] or r["ctx"] == "plan" else "")
        tr.append(f'<tr class="{"" if r["need"] else "q"}"><td>{e(r["name"])} <small>#{e(r["short"])}</small></td>'
                  f'<td>{e(r["project"])}</td><td>{e(r["surface"])}</td><td>{e(r["status"])}</td><td>{e(r["last_seen"])}</td>'
                  f'<td class="{"w" if r["unread"] else ""}">{r["unread"] or ""}</td>'
                  f'<td class="{"b" if r["restart"] else ""}">{"yes" if r["restart"] else ""}</td>'
                  f'<td class="{"b" if r["behind"] else ""}">{e(", ".join(r["behind"]))}</td>'
                  f'<td>{e(r["ctx"])}</td><td class="{"b" if r["need"] >= 4 else "w" if r["need"] else ""}">{e(act)}</td></tr>')
    import time as _t
    pr = []
    try:
        pend = h.approvals(pending_only=True)
    except Exception:
        pend = []
    for x in pend:
        left = max(0, int(float(x.get("expires") or 0) - _t.time()))
        pr.append(f'<tr data-id="{e(x["id"])}"><td>{e(x["id"])}</td><td>{e(x["action"])}</td>'
                  f'<td><code>{e(json.dumps(x.get("args"), ensure_ascii=False, default=str)[:400])}</code></td>'
                  f'<td>{e(str(x.get("caller"))[:8])}</td><td>{left}s</td><td><b>{e(x["args_digest"][:4])}</b></td>'
                  f'<td><input class="code" size="4" maxlength="4" autocomplete="off" placeholder="type code"> '
                  f'<button class="ap">Approve</button> <button class="dn">Deny</button></td></tr>')
    pend_html = ("<h2>Pending approvals</h2><table id=\"pend\"><tr><th>Id</th><th>Action</th><th>Args</th><th>Caller</th>"
                 f"<th>Expires</th><th>Code</th><th></th></tr>{''.join(pr)}</table><p id=\"msg\"></p>") if pr else ""
    js = """<script>
const T=document.querySelector('meta[name=csrf-token]').content;
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'X-CSRF-Token':T,'Content-Type':'application/json'},body:JSON.stringify(b)});
 const j=await r.json().catch(()=>({}));document.getElementById('msg').textContent=r.ok?'done: '+(j.state||''):'refused: '+(j.error||r.status);
 if(r.ok)setTimeout(()=>location.reload(),600);}
document.querySelectorAll('#pend tr[data-id]').forEach(tr=>{const id=tr.dataset.id;
 tr.querySelector('.ap').onclick=()=>post('/api/approve',{id,code:tr.querySelector('.code').value});
 tr.querySelector('.dn').onclick=()=>post('/api/deny',{id});});
setInterval(()=>{if([...document.querySelectorAll('input')].some(i=>i.value)||document.activeElement.tagName==='INPUT')return;location.reload();},5000);
</script>"""
    return ('<!doctype html><meta charset="utf-8">'
            f'<meta name="csrf-token" content="{e(csrf)}">'
            f'<title>Harness operator</title><style>{OP_CSS}</style><h1>Harness operator</h1>'
            f'<p>Run /update only in flagged chats. Behind = running code differs from the release registry. '
            f'Stale = not seen within the fleet window; ignored for drift.</p>{pend_html}<h2>Agents</h2><table><tr><th>Agent</th><th>Project</th>'
            '<th>Surface</th><th>Status</th><th>Seen</th><th>Unread</th><th>Restart</th><th>Behind</th><th>ctx</th>'
            f'<th>Action</th></tr>{"".join(tr) or "<tr><td colspan=10>No live agents.</td></tr>"}</table>{js}')


def write_static(h, out=None):
    out = out or os.path.join(h.store.dir, "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(_page(h.snapshot()))
    return {"path": out, "note": "Static snapshot. Run `harness.py serve` for a live view."}


LOOPBACK = ("127.0.0.1", "::1", "localhost")
MAX_BODY = 65536
SEC_HEADERS = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
               "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self' 'unsafe-inline'"}


def _with_csrf(html, token):
    i = html.lower().find("<meta")
    tag = f'<meta name="csrf-token" content="{_html.escape(token)}">'
    return html[:i] + tag + html[i:] if i >= 0 else tag + html


def make_server(h, host="127.0.0.1", port=7717):
    """Returns (server, csrf_token). Raises ValueError for a non-loopback host."""
    if host not in LOOPBACK:
        raise ValueError(f"dashboard refuses host {host!r}: loopback only ({', '.join(LOOPBACK)})")
    token = secrets.token_hex(16)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            b = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in SEC_HEADERS.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _hosts(self):
            p = self.server.server_address[1]
            return {f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}"}

        def _host_ok(self):
            if (self.headers.get("Host") or "").lower() not in self._hosts():
                self._send(403, "forbidden host", "text/plain")
                return False
            return True

        def do_GET(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            try:
                if u.path in ("/", "/index.html"):
                    self._send(200, _with_csrf(_page(None), token), "text/html; charset=utf-8")
                elif u.path == "/operator":
                    self._send(200, operator_page(h, token), "text/html; charset=utf-8")
                elif u.path == "/health":
                    import health as _hl
                    q = parse_qs(u.query)
                    self._send(200, _with_csrf(_hl.page(h, (q.get("project") or [None])[0], (q.get("agent") or [None])[0]), token),
                               "text/html; charset=utf-8")
                elif u.path == "/api/operator":
                    self._send(200, json.dumps(h.operator_rows()), "application/json")
                elif u.path == "/api/state":
                    self._send(200, json.dumps(h.snapshot(), default=list), "application/json")
                elif u.path == "/api/events":
                    since = int(parse_qs(u.query).get("since", ["0"])[0])
                    self._send(200, json.dumps(h.events(since, 0)), "application/json")
                elif u.path == "/export.jsonl":
                    with open(h.store.log, "rb") as f:
                        self._send(200, f.read(), "application/x-ndjson")
                else:
                    self._send(404, "not found", "text/plain")
            except Exception as e:  # keep serving
                self._send(500, json.dumps({"error": str(e)}), "application/json")

        def do_POST(self):
            if not self._host_ok():
                return
            origin = self.headers.get("Origin")
            if origin is not None:
                oh = origin.split("://", 1)[-1].lower()
                if not origin.lower().startswith("http://") or oh not in self._hosts():
                    return self._send(403, "forbidden origin", "text/plain")
            if not hmac.compare_digest(str(self.headers.get("X-CSRF-Token") or "").encode(), token.encode()):
                return self._send(403, "csrf token missing or wrong", "text/plain")
            u = urlparse(self.path)
            if u.path not in ("/api/archive", "/api/pin", "/api/approve", "/api/deny"):
                return self._send(404, "not found", "text/plain")
            if self.headers.get("Transfer-Encoding"):
                return self._send(400, "chunked bodies are not accepted", "text/plain")
            cl = self.headers.get("Content-Length")
            try:
                n = int(cl) if cl is not None and cl.strip().isdigit() else -1
            except ValueError:
                n = -1
            if n < 0:
                return self._send(400, "bad Content-Length", "text/plain")
            if n > MAX_BODY:
                return self._send(413, "body too large", "text/plain")
            raw = self.rfile.read(n).decode("utf-8", "replace")
            try:
                if "json" in (self.headers.get("Content-Type") or ""):
                    j = json.loads(raw or "{}")
                    q = {k: (v if isinstance(v, list) else [v]) for k, v in j.items()} if isinstance(j, dict) else {}
                else:
                    q = parse_qs(raw)
                one = lambda k: str((q.get(k) or [""])[0])
                if u.path == "/api/approve":
                    r = h.approve(one("id"), channel="dashboard", code=one("code"), tty=True)
                    return self._send(200, json.dumps(r, default=str), "application/json")
                if u.path == "/api/deny":
                    r = h.deny(one("id"), channel="dashboard")
                    return self._send(200, json.dumps(r, default=str), "application/json")
                if u.path == "/api/pin":
                    h.pin("operator", q.get("id") or [], True, one("reason"))
                else:
                    h.archive("operator", q.get("id") or [], one("reason"))
                self._send(200, json.dumps({"ok": True}), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}), "application/json")

    class S(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET

    return S((host, port), H), token


def serve(h, host="127.0.0.1", port=7717):
    try:
        srv, _ = make_server(h, host, port)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"Crew Coordinator dashboard: http://{host}:{port}   (home: {h.home})  Ctrl-C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
