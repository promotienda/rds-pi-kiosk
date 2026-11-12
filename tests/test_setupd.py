import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "stage-kiosk", "02-kiosk", "files", "rootfs")
LIB = os.path.join(ROOT, "usr", "lib", "rds-pi-kiosk")
TMP = tempfile.mkdtemp(prefix="setupd-test-")
os.environ.update({
    "RDS_KIOSK_TXT": os.path.join(TMP, "kiosk.txt"),
    "RDS_KIOSK_STATE": os.path.join(TMP, "state"),
    "RDS_KIOSK_RUN": os.path.join(TMP, "run"),
    "RDS_KIOSK_WWW": os.path.join(ROOT, "usr", "share", "rds-pi-kiosk", "www"),
    "RDS_KIOSK_LIB": LIB,
})
sys.path.insert(0, LIB)
import setupd  # noqa: E402

os.makedirs(setupd.RUN, exist_ok=True)
os.makedirs(setupd.REQUESTS, exist_ok=True)
with open(setupd.CODE_FILE, "w") as f:
    f.write("ABCD2345\n")
with open(os.path.join(setupd.RUN, "state.json"), "w") as f:
    json.dump({"URL": "https://example.com", "ROTATION": "0", "ZOOM": "1.0", "mode": "free",
               "SETUP_PAGE": "on", "hostname": "rds-kiosk", "version": "test"}, f)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
SRV = setupd.Server(("::", PORT), setupd.Handler)
threading.Thread(target=SRV.serve_forever, daemon=True).start()


def req(method, path, body=None, host="127.0.0.1", ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    h = {"Host": host}
    if data is not None:
        h["Content-Type"] = ctype
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw


def queued():
    return sorted(x for x in os.listdir(setupd.REQUESTS) if x.endswith(".json"))


class Setupd(unittest.TestCase):
    def setUp(self):
        for x in os.listdir(setupd.REQUESTS):
            os.unlink(os.path.join(setupd.REQUESTS, x))

    def test_pages(self):
        for p in ("/", "/start", "/app.css", "/start.js", "/setup.js", "/healthz"):
            self.assertEqual(req("GET", p)[0], 200, p)

    def test_dns_rebinding_refused(self):
        self.assertEqual(req("GET", "/api/local", host="evil.example")[0], 421)
        self.assertEqual(req("POST", "/api/pair", {"code": "ABCD2345"}, host="evil.example:80")[0], 421)

    def test_local_api_on_loopback(self):
        st, v = req("GET", "/api/local", host="localhost")
        self.assertEqual(st, 200)
        self.assertEqual(v["code"], "ABCD2345")
        self.assertEqual(v["url"], "https://example.com")

    def test_form_post_refused(self):
        st, _ = req("POST", "/api/pair", b"code=ABCD2345", ctype="application/x-www-form-urlencoded")
        self.assertEqual(st, 415)
        self.assertEqual(queued(), [])

    def test_wrong_code(self):
        st, _ = req("POST", "/api/settings", {"code": "WRONG000"})
        self.assertEqual(st, 403)

    def test_settings_roundtrip_and_validation(self):
        st, v = req("POST", "/api/settings", {"code": "abcd-2345"})
        self.assertEqual(st, 200)
        self.assertEqual(v["url"], "https://example.com")
        st, v = req("POST", "/api/settings", {"code": "ABCD2345", "values": {"URL": "javascript:x"}})
        self.assertEqual(st, 400)
        st, v = req("POST", "/api/settings", {"code": "ABCD2345", "values": {"WIFI_SSID": "x"}})
        self.assertEqual(st, 400)
        self.assertEqual(queued(), [])
        st, v = req("POST", "/api/settings", {"code": "ABCD2345",
                                              "values": {"URL": "https://new.example", "ROTATION": "90"}})
        self.assertEqual(st, 202)
        q = queued()
        self.assertEqual(len(q), 1)
        with open(os.path.join(setupd.REQUESTS, q[0])) as f:
            self.assertEqual(json.load(f), {"type": "settings",
                                            "values": {"URL": "https://new.example", "ROTATION": "90"}})

    def test_pair(self):
        st, _ = req("POST", "/api/pair", {"code": "ABCD2345"})
        self.assertEqual(st, 202)
        self.assertEqual(len(queued()), 1)

    def test_body_limit(self):
        st, _ = req("POST", "/api/settings", {"code": "ABCD2345", "pad": "x" * 9000})
        self.assertEqual(st, 413)

    def test_lockout_not_for_loopback(self):
        # Loopback is the screen itself: never locked out.
        for _ in range(15):
            req("POST", "/api/settings", {"code": "WRONG000"})
        self.assertEqual(req("POST", "/api/settings", {"code": "ABCD2345"})[0], 200)


if __name__ == "__main__":
    unittest.main()
