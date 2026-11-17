"""Web dashboard for the emergency notification server (stdlib only)."""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.server import NotificationServer

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Emergency Notification Console</title>
<style>
:root{--bg:#0f1419;--card:#18202a;--line:#2a3441;--tx:#e6edf3;--mut:#8b98a8;--red:#ef4444;--amb:#f59e0b;--grn:#22c55e;--blu:#3b82f6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px system-ui,sans-serif}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 24px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--grn);margin-right:6px}
.dot.off{background:var(--red)}main{display:grid;grid-template-columns:340px 1fr;gap:16px;padding:16px 24px;max-width:1200px;margin:auto}
@media(max-width:800px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 12px}
.seg{display:flex;gap:8px;margin-bottom:12px}.seg label{flex:1;text-align:center;padding:9px;border:1px solid var(--line);border-radius:8px;cursor:pointer;color:var(--mut)}
.seg input{display:none}.seg input:checked+span{color:#fff}
.seg label:has(input[value=EMERGENCY]:checked){background:var(--red);border-color:var(--red);color:#fff}
.seg label:has(input[value=NORMAL]:checked){background:var(--blu);border-color:var(--blu);color:#fff}
textarea{width:100%;height:90px;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:10px;font:inherit;resize:vertical}
button{width:100%;margin-top:10px;padding:11px;border:0;border-radius:8px;background:var(--red);color:#fff;font:600 15px inherit;cursor:pointer}
button:disabled{opacity:.5}#err{color:var(--red);font-size:13px;min-height:18px;margin-top:8px}
.cl{display:flex;justify-content:space-between;padding:8px 0;border-top:1px solid var(--line);font-size:14px}.cl:first-of-type{border-top:0}
.mut{color:var(--mut);font-size:12px}.n{border-left:4px solid var(--blu);padding:12px 14px;background:var(--bg);border-radius:8px;margin-bottom:10px}
.n.EMERGENCY{border-color:var(--red)}.top{display:flex;justify-content:space-between;gap:10px;align-items:center}
.b{font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;text-transform:uppercase}
.b.pending{background:#78350f;color:#fcd34d}.b.acknowledged{background:#14532d;color:#86efac}.b.failed{background:#7f1d1d;color:#fca5a5}
.msg{margin:6px 0;word-break:break-word}.bar{height:6px;background:var(--line);border-radius:4px;overflow:hidden;margin:8px 0}
.bar>i{display:block;height:100%;background:var(--grn);transition:width .3s}.chip{display:inline-block;font-size:12px;padding:2px 8px;margin:2px 4px 0 0;border-radius:6px;background:#14532d;color:#86efac}
.chip.miss{background:#3b2a12;color:#fcd34d}.empty{color:var(--mut);text-align:center;padding:24px}
</style></head><body>
<header><h1>Emergency Notification Console</h1><div class="mut"><span id="dot" class="dot"></span><span id="conn">connecting</span></div></header>
<main><div>
<div class="card"><h2>Send notification</h2>
<div class="seg"><label><input type="radio" name="t" value="EMERGENCY" checked><span>Emergency</span></label>
<label><input type="radio" name="t" value="NORMAL"><span>Normal</span></label></div>
<textarea id="m" placeholder="Message to all clients..."></textarea>
<button id="send">Send to all clients</button><div id="err"></div></div>
<div class="card"><h2>Clients (<span id="cc">0</span>)</h2><div id="clients"></div></div></div>
<div><div class="card"><h2>Notifications</h2><div id="feed"></div></div></div></main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){
 try{const s=await (await fetch('/api/state')).json();
  $('dot').className='dot';$('conn').textContent='server up :'+s.port;
  $('cc').textContent=s.clients.length;
  $('clients').innerHTML=s.clients.length?s.clients.map(c=>`<div class="cl"><b>${esc(c.name)}</b><span class="mut">${esc(c.address)}</span></div>`).join(''):'<div class="mut">No clients registered</div>';
  $('feed').innerHTML=s.notifications.length?s.notifications.map(n=>{
   const pct=n.expected?Math.round(100*n.acknowledged/n.expected):0;
   return `<div class="n ${n.type}"><div class="top"><div><b>#${n.id} ${n.type}</b> <span class="mut">${esc(n.time)} · retries ${n.retries}</span></div><span class="b ${n.status}">${n.status}</span></div>
   <div class="msg">${esc(n.message)}</div><div class="bar"><i style="width:${pct}%"></i></div>
   <div class="mut">${n.acknowledged}/${n.expected} ACKs</div>
   <div>${n.acks.map(a=>`<span class="chip">✓ ${esc(a)}</span>`).join('')}${n.missing.map(a=>`<span class="chip miss">… ${esc(a)}</span>`).join('')}</div></div>`}).join(''):'<div class="empty">No notifications sent yet</div>';
 }catch(e){$('dot').className='dot off';$('conn').textContent='disconnected'}
}
$('send').onclick=async()=>{
 const type=document.querySelector('input[name=t]:checked').value,message=$('m').value.trim();
 $('err').textContent='';if(!message){$('err').textContent='Enter a message.';return}
 $('send').disabled=true;
 try{const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,message})});
  const j=await r.json();if(!r.ok)$('err').textContent=j.error;else{$('m').value='';refresh()}}
 catch(e){$('err').textContent='Request failed'}$('send').disabled=false};
refresh();setInterval(refresh,1000);
</script></body></html>"""


def build_state(server: NotificationServer, log: dict):
    with server.lock:
        clients = [{"name": n, "address": f"{a[0]}:{a[1]}"}
                   for n, a in sorted(server.clients.items())]
        ids = sorted(server.notifications, reverse=True)
        messages = {i: server.notifications[i]["message"] for i in ids}
    notes = []
    for i in ids:
        st = server.get_delivery_status(i)
        notes.append({"id": i, "type": st["type"], "message": messages[i],
                      "status": st["status"], "acknowledged": st["acknowledged"],
                      "expected": st["expected"], "retries": st["retries"],
                      "acks": st["acks"], "missing": st["missing"],
                      "time": log.get(i, "")})
    return {"port": server.udp_port, "clients": clients, "notifications": notes}


def make_handler(server: NotificationServer, log: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/state":
                self._json(200, build_state(server, log))
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/send":
                return self._json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(min(length, 8192)) or b"{}")
                mid = server.send_notification(str(data.get("type", "")), str(data.get("message", "")))
                log[mid] = time.strftime("%H:%M:%S")
                self._json(200, {"id": mid})
            except (ValueError, RuntimeError) as exc:
                self._json(400, {"error": str(exc)})

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Emergency notification web dashboard")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--udp-port", type=int, default=5000)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    server = NotificationServer(udp_port=args.udp_port)
    server.start()
    httpd = ThreadingHTTPServer((args.bind, args.http_port), make_handler(server, {}))
    print(f"UDP server on :{args.udp_port} | dashboard on http://{args.bind}:{args.http_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        httpd.server_close()
        server.stop()


if __name__ == "__main__":
    main()
