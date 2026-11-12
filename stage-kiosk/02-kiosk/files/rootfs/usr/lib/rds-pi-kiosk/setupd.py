"""RDS Pi Kiosk local setup page (free mode only).

Runs as the unprivileged "kiosk-setup" user (rds-kiosk-setup.service), port 80.
It never changes the system itself: it validates a request, drops it as a JSON
file into /var/lib/rds-pi-kiosk/requests, and a root path unit applies it.

  /start         the on-screen start page (welcome / waiting for network)
  /              the setup page for a phone or PC on the same network
  /api/local     loopback only: setup code, addresses, state (for /start)
  /api/qr.svg    loopback only: QR code for the setup page
  /api/netcheck  loopback only: can the configured URL's host be reached?
  /api/settings  POST {code[, values]}  read / change URL, ROTATION, ZOOM
  /api/pair      POST {code}             Pair with RDS
  /api/reload    POST {code}             restart the browser
  /healthz       200 "ok"

Every POST needs the setup code, which is shown only on the screen itself.
Requests must be JSON (so a web page elsewhere cannot post a plain form here)
and must name this device in Host: (so DNS rebinding gets nowhere).
SETUP_PAGE=off in kiosk.txt listens on loopback only.
"""

import hmac
import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.environ.get("RDS_KIOSK_LIB", "/usr/lib/rds-pi-kiosk"))
import kioskconf as kc  # noqa: E402

WWW = os.environ.get("RDS_KIOSK_WWW", "/usr/share/rds-pi-kiosk/www")
RUN = os.environ.get("RDS_KIOSK_RUN", "/run/rds-pi-kiosk")
REQUESTS = kc.STATE_DIR + "/requests"
CODE_FILE = kc.STATE_DIR + "/setup-code"
PORT = int(os.environ.get("RDS_KIOSK_SETUP_PORT", "80"))
MAX_BODY = 8192

LOCK = threading.Lock()
FAILS = []                 # monotonic times of wrong codes from the network
LOCKOUT_UNTIL = 0.0
MAX_FAILS, WINDOW, LOCKOUT = 10, 600, 600


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_code():
    try:
        with open(CODE_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def addresses():
    """IPv4 addresses that a phone on the LAN could use."""
    out = []
    try:
        r = subprocess.run(["ip", "-j", "-4", "addr", "show", "scope", "global"],
                           capture_output=True, text=True, timeout=3)
        for link in json.loads(r.stdout or "[]"):
            for a in link.get("addr_info", []):
                if a.get("local"):
                    out.append(a["local"])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return out


def qr_svg(text):
    try:
        r = subprocess.run(["qrencode", "-t", "SVG", "-m", "2", "-l", "M", "-o", "-", text],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return b""


def host_reachable(url):
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((u.hostname, port), timeout=3):
            return True
    except (OSError, ValueError, TypeError):
        return False


def queue(kind, **payload):
    os.makedirs(REQUESTS, exist_ok=True)
    name = "%d-%s.json" % (time.time_ns(), os.urandom(4).hex())
    tmp = os.path.join(REQUESTS, "." + name)
    with open(tmp, "w") as f:
        json.dump(dict(type=kind, **payload), f)
    os.replace(tmp, os.path.join(REQUESTS, name))   # the path unit fires on this


class Handler(BaseHTTPRequestHandler):
    server_version = "rds-pi-kiosk"
    sys_version = ""
    timeout = 15                                   # per connection: no slow-loris

    def log_message(self, fmt, *args):            # to the journal, without query strings
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ── helpers ──
    def loopback(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        return ip.is_loopback

    def host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):
            host = host[1:].split("]", 1)[0]
        else:
            host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if host in ("localhost", "127.0.0.1", "::1"):
            return True
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            pass
        name = socket.gethostname().lower()
        return host in (name, name + ".local")

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def static(self, name, ctype):
        try:
            with open(os.path.join(WWW, name), "rb") as f:
                self.send(200, f.read(), ctype)
        except OSError:
            self.send(404, {"error": "not found"})

    def check_code(self, given):
        global LOCKOUT_UNTIL
        now = time.monotonic()
        local = self.loopback()
        with LOCK:
            if not local and now < LOCKOUT_UNTIL:
                return "locked"
            code = read_code()
            if code and isinstance(given, str) and hmac.compare_digest(
                    given.strip().upper().replace("-", "").replace(" ", "").encode(),
                    code.upper().encode()):
                return "ok"
            if not local:
                FAILS[:] = [t for t in FAILS if now - t < WINDOW] + [now]
                if len(FAILS) >= MAX_FAILS:
                    LOCKOUT_UNTIL = now + LOCKOUT
                    FAILS.clear()
            return "bad"

    def settings_view(self):
        st = read_json(RUN + "/state.json", {})
        return {
            "url": st.get("URL", ""),
            "rotation": st.get("ROTATION", "0"),
            "zoom": st.get("ZOOM", "1.0"),
            "mode": st.get("mode", "free"),
            "hostname": st.get("hostname", ""),
            "version": st.get("version", ""),
            "warnings": st.get("warnings", []),
            "pair": read_json(RUN + "/pair.json", {"state": "idle", "message": ""}),
        }

    # ── GET ──
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.host_ok():
            return self.send(421, {"error": "wrong host"})
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            return self.send(200, "ok\n", "text/plain")
        if path in ("/", "/index.html"):
            return self.static("setup.html", "text/html; charset=utf-8")
        if path == "/start":
            return self.static("start.html", "text/html; charset=utf-8")
        if path in ("/app.css", "/setup.js", "/start.js"):
            ctype = "text/css" if path.endswith(".css") else "text/javascript"
            return self.static(path[1:], ctype + "; charset=utf-8")
        if path.startswith("/api/") and not self.loopback():
            return self.send(403, {"error": "only on the screen itself"})
        if path == "/api/local":
            v = self.settings_view()
            ips = addresses()
            v.update({"code": read_code(), "ips": ips,
                      "setup_urls": ["http://%s/" % ip for ip in ips],
                      "setup_page": read_json(RUN + "/state.json", {}).get("SETUP_PAGE", "on")})
            return self.send(200, v)
        if path == "/api/qr.svg":
            ips = addresses()
            if not ips:
                return self.send(404, {"error": "no network"})
            svg = qr_svg("http://%s/#code=%s" % (ips[0], read_code()))
            return self.send(200 if svg else 500, svg or b"", "image/svg+xml")
        if path == "/api/netcheck":
            url = read_json(RUN + "/state.json", {}).get("URL", "")
            return self.send(200, {"ok": bool(url) and host_reachable(url)})
        return self.send(404, {"error": "not found"})

    # ── POST ──
    def do_POST(self):
        if not self.host_ok():
            return self.send(421, {"error": "wrong host"})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self.send(415, {"error": "JSON only"})
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            return self.send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send(400, {"error": "bad JSON"})
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("/api/settings", "/api/pair", "/api/reload"):
            return self.send(404, {"error": "not found"})
        verdict = self.check_code(body.get("code"))
        if verdict == "locked":
            return self.send(429, {"error": "Too many wrong codes. Wait 10 minutes."})
        if verdict != "ok":
            return self.send(403, {"error": "Wrong setup code. It is shown on the screen."})

        if path == "/api/pair":
            queue("pair")
            return self.send(202, {"ok": True})
        if path == "/api/reload":
            queue("reload")
            return self.send(202, {"ok": True})
        vals = body.get("values")
        if vals is not None:
            if not isinstance(vals, dict):
                return self.send(400, {"error": "values must be an object"})
            clean, errors = {}, {}
            for k, v in vals.items():
                if k not in kc.WEB_EDITABLE or not isinstance(v, str):
                    errors[k] = "cannot be changed here"
                    continue
                v = kc._normalise(k, v.strip())
                why = kc.validate(k, v)
                if why:
                    errors[k] = why
                else:
                    clean[k] = v
            if errors:
                return self.send(400, {"error": "Invalid settings", "fields": errors})
            if clean:
                queue("settings", values=clean)
            return self.send(202, dict(self.settings_view(), ok=True, queued=bool(clean)))
        return self.send(200, self.settings_view())


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def main():
    st = read_json(RUN + "/state.json", {})
    lan = st.get("SETUP_PAGE", "on") != "off"
    if lan:
        srv = Server(("::", PORT), Handler)
    else:
        ThreadingHTTPServer.allow_reuse_address = True
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.timeout = 10
    print("rds-kiosk-setup: listening on %s port %d" % ("all addresses" if lan else "loopback only", PORT),
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
