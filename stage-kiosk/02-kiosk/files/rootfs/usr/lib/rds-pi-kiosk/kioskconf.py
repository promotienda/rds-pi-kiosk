"""kiosk.txt: the one settings file of RDS Pi Kiosk.

It lives on the FAT boot partition (/boot/firmware/kiosk.txt) so it can be
edited on any PC before the first boot. Format: KEY=VALUE, one per line.
A line whose first non-blank character is '#' is a comment. A '#' anywhere
else is part of the value, because URLs carry fragments.

Everything here is standard library only: the setup page imports it too and
runs with `python3 -I`.

Rule for bad input: a value that does not validate is IGNORED with a warning
and the last value that did validate is used (falling back to the default).
A typo in kiosk.txt must never take a working screen dark.
"""

import json
import os
import re
import tempfile

# The environment overrides exist for the tests only; systemd sets neither.
KIOSK_TXT = os.environ.get("RDS_KIOSK_TXT", "/boot/firmware/kiosk.txt")
STATE_DIR = os.environ.get("RDS_KIOSK_STATE", "/var/lib/rds-pi-kiosk")
LAST_GOOD = STATE_DIR + "/last-good.json"
DEFAULT_RDS_SERVER = "https://rds.digitalsignagerds.com"

DEFAULTS = {
    "URL": "",
    "MODE": "free",
    "ROTATION": "0",
    "ZOOM": "1.0",
    "WIFI_SSID": "",
    "WIFI_PASSWORD": "",
    "WIFI_COUNTRY": "",
    "TIMEZONE": "",
    "HOSTNAME": "",
    "SETUP_PAGE": "on",
    "SETUP_CODE": "",
    "SSH_AUTHORIZED_KEY": "",
    "AUTO_SECURITY_UPDATES": "yes",
    "RDS_SERVER": DEFAULT_RDS_SERVER,
}

# Keys the network setup page may change. Wi-Fi, SSH and the server are
# deliberately absent: changing them over the network can cut the device off
# the network or hand it to someone else. Those stay in kiosk.txt.
WEB_EDITABLE = ("URL", "ROTATION", "ZOOM")

SECRET_KEYS = ("WIFI_PASSWORD", "SETUP_CODE", "SSH_AUTHORIZED_KEY")

# Notes the Pi writes into kiosk.txt start with this, so the next change can
# replace them instead of piling them up.
AUTO_NOTE = "# (auto) "

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_URL = re.compile(r"^https?://[^\s/?#]+[^\s]*$", re.I)
_HOST_LABEL = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_TZ = re.compile(r"^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}$")
_SERVER = re.compile(r"^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?$")
_CODE = re.compile(r"^[A-Za-z0-9]{6,32}$")
_SSHKEY = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r" [A-Za-z0-9+/=]{40,}( [^\x00-\x1f]*)?$")


def _num(v, lo, hi):
    try:
        f = float(v)
    except ValueError:
        return False
    return lo <= f <= hi


def validate(key, value):
    """Return None if (key, value) is acceptable, else a short reason."""
    if key not in DEFAULTS:
        return "unknown setting"
    if _CTRL.search(value):
        return "contains control characters"
    if key == "URL":
        if value == "":
            return None
        if len(value) > 2048:
            return "longer than 2048 characters"
        if not _URL.match(value):
            return "must start with http:// or https://"
        return None
    if key == "MODE":
        return None if value in ("free", "rds") else "must be free or rds"
    if key == "ROTATION":
        return None if value in ("0", "90", "180", "270") else "must be 0, 90, 180 or 270"
    if key == "ZOOM":
        return None if _num(value, 0.25, 5) else "must be a number from 0.25 to 5"
    if key == "WIFI_SSID":
        return None if len(value.encode()) <= 32 else "longer than 32 bytes"
    if key == "WIFI_PASSWORD":
        return None if value == "" or 8 <= len(value) <= 63 else "must be 8 to 63 characters"
    if key == "WIFI_COUNTRY":
        return None if value == "" or re.match(r"^[A-Z]{2}$", value) else "must be two capital letters, e.g. ES"
    if key == "TIMEZONE":
        if value == "":
            return None
        if not _TZ.match(value) or ".." in value:
            return "not a time zone name"
        return None
    if key == "HOSTNAME":
        return None if value == "" or _HOST_LABEL.match(value) else "letters, digits and '-', at most 63"
    if key == "SETUP_PAGE":
        return None if value in ("on", "off") else "must be on or off"
    if key == "SETUP_CODE":
        return None if value == "" or _CODE.match(value) else "6 to 32 letters or digits"
    if key == "SSH_AUTHORIZED_KEY":
        if value == "":
            return None
        return None if len(value) <= 8192 and _SSHKEY.match(value) else "not an OpenSSH public key line"
    if key == "AUTO_SECURITY_UPDATES":
        return None if value in ("yes", "no") else "must be yes or no"
    if key == "RDS_SERVER":
        return None if _SERVER.match(value) else "must be https://host[:port]"
    return "unknown setting"


def _normalise(key, value):
    if key in ("MODE", "SETUP_PAGE", "AUTO_SECURITY_UPDATES"):
        return value.lower()
    if key == "WIFI_COUNTRY":
        return value.upper()
    if key == "RDS_SERVER":
        return value.rstrip("/")
    return value


def _read_text(path):
    with open(path, "rb") as f:
        raw = f.read(256 * 1024)
    if raw.startswith(b"\xef\xbb\xbf"):          # Notepad's BOM
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def parse_text(text):
    """Return (values, warnings, invalid).

    values holds only keys present in the text with a valid value; invalid
    is the set of keys that were present with a value that did not validate.
    """
    values, warnings, invalid = {}, [], set()
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            warnings.append("line %d: no '=' (ignored)" % n)
            continue
        k, v = s.split("=", 1)
        k = k.strip().upper()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k not in DEFAULTS:
            warnings.append("line %d: unknown setting %s (ignored)" % (n, k))
            continue
        v = _normalise(k, v)
        why = validate(k, v)
        if why:
            warnings.append("line %d: %s %s (ignored)" % (n, k, why))
            invalid.add(k)
            continue
        values[k] = v
    return values, warnings, invalid


def load_last_good():
    try:
        with open(LAST_GOOD) as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k in DEFAULTS and isinstance(v, str)
                and validate(k, v) is None}
    except (OSError, ValueError):
        return {}


def effective(path=KIOSK_TXT):
    """Settings in force, and warnings.

    kiosk.txt wins. A key whose line is present but invalid keeps its last
    good value; a key with no line at all is the default (deleting a line is
    how a user resets it). An unreadable file keeps every last good value.
    """
    out = dict(DEFAULTS)
    good = {k: v for k, v in load_last_good().items() if k not in SECRET_KEYS}
    try:
        vals, warnings, invalid = parse_text(_read_text(path))
    except OSError as e:
        out.update(good)
        return out, ["cannot read %s: %s (using the last good settings)" % (path, e.strerror)]
    for k in invalid:
        if k in good:
            out[k] = good[k]
    out.update(vals)
    return out, warnings


def save_last_good(settings):
    os.makedirs(STATE_DIR, exist_ok=True)
    keep = {k: v for k, v in settings.items() if k in DEFAULTS and k not in SECRET_KEYS}
    _atomic_write(LAST_GOOD, json.dumps(keep, indent=1, sort_keys=True) + "\n", 0o644)


def _atomic_write(path, text, mode=0o644):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".kiosk-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass                                   # FAT has no modes
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:                                           # make the rename durable
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def set_values(updates, path=KIOSK_TXT, comment=None):
    """Rewrite kiosk.txt with updates applied, keeping comments and order.

    The first uncommented KEY= line is replaced; a key that has none is
    appended. Raises ValueError on an invalid value - callers validate first.
    """
    for k, v in updates.items():
        why = validate(k, v)
        if why:
            raise ValueError("%s %s" % (k, why))
    try:
        lines = _read_text(path).splitlines()
    except FileNotFoundError:
        lines = []
    done = set()
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip().upper()
            if k in updates:
                if k in done:
                    continue                       # drop later duplicates
                done.add(k)
                if out and out[-1].startswith(AUTO_NOTE):
                    out.pop()                      # replace our own old note
                if comment:
                    out.append(AUTO_NOTE + comment)
                out.append("%s=%s" % (k, updates[k]))
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in done:
            if comment:
                out.append(AUTO_NOTE + comment)
            out.append("%s=%s" % (k, v))
    _atomic_write(path, "\n".join(out) + "\n")


def public_view(settings):
    """What may be shown outside root: never a secret."""
    return {k: v for k, v in settings.items() if k not in SECRET_KEYS}
