"""
API client — connects to NekoPi backend at https://localhost:8080
Self-signed cert → verify=False. Timeout 2s.
Returns parsed JSON or None on any error.
"""

import urllib.request
import urllib.error
import urllib.parse
import ssl
import json

_BASE = "https://localhost:8080"
_TIMEOUT = 5

# Disable SSL verification for self-signed cert
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def get(path: str, params: dict = None):
    """GET request to the API. Returns dict/list or None on error."""
    try:
        url = _BASE + path
        if params:
            qs = urllib.parse.urlencode(params)
            url += ("&" if "?" in url else "?") + qs
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def post(path: str, body: dict = None):
    """POST request to the API. Returns dict/list or None on error."""
    try:
        url = _BASE + path
        data = json.dumps(body).encode() if body else b""
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX) as resp:
            return json.loads(resp.read())
    except Exception:
        return None
