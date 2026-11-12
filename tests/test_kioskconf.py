import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "stage-kiosk", "02-kiosk", "files", "rootfs", "usr", "lib", "rds-pi-kiosk")
TMP = tempfile.mkdtemp(prefix="kc-test-")
os.environ["RDS_KIOSK_TXT"] = os.path.join(TMP, "kiosk.txt")
os.environ["RDS_KIOSK_STATE"] = os.path.join(TMP, "state")
sys.path.insert(0, LIB)
import kioskconf as kc  # noqa: E402


def write(text, raw=False):
    with open(kc.KIOSK_TXT, "wb" if raw else "w") as f:
        f.write(text)


class Parse(unittest.TestCase):
    def setUp(self):
        for p in (kc.KIOSK_TXT, kc.LAST_GOOD):
            if os.path.exists(p):
                os.unlink(p)

    def test_defaults_when_missing(self):
        s, w = kc.effective()
        self.assertEqual(s["MODE"], "free")
        self.assertEqual(s["URL"], "")
        self.assertTrue(w)                      # "cannot read"

    def test_url_with_fragment_and_quotes(self):
        write('URL="https://example.com/a?b=1#frag"\nROTATION=90\n')
        s, w = kc.effective()
        self.assertEqual(s["URL"], "https://example.com/a?b=1#frag")
        self.assertEqual(s["ROTATION"], "90")
        self.assertEqual(w, [])

    def test_bom_crlf_case(self):
        write(b"\xef\xbb\xbfurl=https://x.example\r\nmode=RDS\r\n", raw=True)
        s, _ = kc.effective()
        self.assertEqual(s["URL"], "https://x.example")
        self.assertEqual(s["MODE"], "rds")

    def test_invalid_keeps_last_good_absent_resets(self):
        write("URL=https://good.example\n")
        s, _ = kc.effective()
        kc.save_last_good(s)
        write("URL=ftp://bad\n")
        s, w = kc.effective()
        self.assertEqual(s["URL"], "https://good.example")
        self.assertTrue(any("URL" in x for x in w))
        write("# nothing\n")
        s, _ = kc.effective()
        self.assertEqual(s["URL"], "")          # deleting the line resets it

    def test_rejects(self):
        bad = {"URL": "javascript:alert(1)", "ROTATION": "45", "ZOOM": "9",
               "WIFI_PASSWORD": "short", "WIFI_COUNTRY": "spain", "TIMEZONE": "../../etc/passwd",
               "HOSTNAME": "-bad", "SETUP_CODE": "abc", "SSH_AUTHORIZED_KEY": "hello",
               "RDS_SERVER": "http://insecure.example", "MODE": "other"}
        for k, v in bad.items():
            self.assertIsNotNone(kc.validate(k, v), k)
        self.assertIsNotNone(kc.validate("URL", "https://a.example/\x07"))
        self.assertIsNotNone(kc.validate("NOPE", "x"))

    def test_accepts(self):
        good = {"URL": "http://10.0.0.5:8080/board", "ZOOM": "1.25", "TIMEZONE": "America/Argentina/Cordoba",
                "HOSTNAME": "lobby-1", "SETUP_CODE": "ABCD2345", "RDS_SERVER": "https://rds.example:8443",
                "SSH_AUTHORIZED_KEY": "ssh-ed25519 " + "A" * 68 + " me@host"}
        for k, v in good.items():
            self.assertIsNone(kc.validate(k, v), k)

    def test_set_values_keeps_comments_and_dedups(self):
        write("# note\nURL=https://a.example\nMODE=free\nURL=https://dup.example\n")
        kc.set_values({"URL": "https://b.example", "ROTATION": "180"}, comment="changed")
        text = open(kc.KIOSK_TXT).read()
        self.assertIn("# note", text)
        self.assertEqual(text.count("URL="), 1)
        self.assertIn("URL=https://b.example", text)
        self.assertIn("ROTATION=180", text)
        s, w = kc.effective()
        self.assertEqual((s["URL"], s["ROTATION"], s["MODE"]), ("https://b.example", "180", "free"))
        with self.assertRaises(ValueError):
            kc.set_values({"URL": "nope"})

    def test_auto_notes_do_not_pile_up(self):
        write("URL=https://a.example\n")
        for n in range(3):
            kc.set_values({"URL": "https://n%d.example" % n}, comment="changed %d" % n)
        text = open(kc.KIOSK_TXT).read()
        self.assertEqual(text.count(kc.AUTO_NOTE), 1)
        self.assertIn("changed 2", text)

    def test_secrets_never_in_public_or_last_good(self):
        write("WIFI_SSID=net\nWIFI_PASSWORD=supersecret\nSETUP_CODE=ABCDEFGH\n")
        s, _ = kc.effective()
        kc.save_last_good(s)
        self.assertNotIn("supersecret", open(kc.LAST_GOOD).read())
        self.assertNotIn("WIFI_PASSWORD", kc.public_view(s))
        self.assertNotIn("SETUP_CODE", kc.public_view(s))

    def test_default_file_parses_clean(self):
        p = os.path.join(LIB, "..", "..", "share", "rds-pi-kiosk", "kiosk.txt.default")
        with open(p) as f:
            vals, warnings, invalid = kc.parse_text(f.read())
        self.assertEqual(warnings, [])
        self.assertEqual(vals["MODE"], "free")


if __name__ == "__main__":
    unittest.main()
