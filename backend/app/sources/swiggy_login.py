"""Log in to Swiggy Scenes once for the local backend: phone number + OTP in your browser.

    cd backend && uv run python -m app.sources.swiggy_login

Runs the OAuth 2.1 + PKCE flow against mcp.swiggy.com and writes SWIGGY_SCENES_TOKEN to backend/.env. The
token lasts 5 days and Swiggy issues no refresh tokens, so run this again when events fall back to samples.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

AUTH = "https://mcp.swiggy.com/auth"
PORT = 8765
REDIRECT = f"http://localhost:{PORT}/callback"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def main() -> int:
    client_id = _register()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = f"{AUTH}/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "code_challenge": challenge,
        "code_challenge_method": "S256", "redirect_uri": REDIRECT, "state": state,
    })

    got: dict = {}
    done = threading.Event()

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>Swiggy login done. You can close this tab.</h3>")
            done.set()

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("localhost", PORT), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Opening Swiggy login in your browser. If it doesn't open, visit:\n\n" + url + "\n")
    webbrowser.open(url)
    if not done.wait(timeout=300):
        print("Timed out waiting for the login redirect.")
        return 1
    server.shutdown()
    if got.get("state") != state or "code" not in got:
        print(f"Login failed: {got.get('error_description') or got.get('error') or 'state mismatch'}")
        return 1

    resp = httpx.post(f"{AUTH}/token", json={
        "grant_type": "authorization_code", "code": got["code"], "code_verifier": verifier,
        "redirect_uri": REDIRECT, "client_id": client_id,
    }, timeout=20)
    if resp.status_code != 200 or "access_token" not in resp.json():
        print(f"Token exchange failed: HTTP {resp.status_code} {resp.text[:200]}")
        return 1
    token = resp.json()
    expires = datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 432000)))
    _write_env({"SWIGGY_SCENES_TOKEN": token["access_token"], "SWIGGY_SCENES_TOKEN_EXPIRES": expires.isoformat(timespec="minutes")})
    print(f"Saved SWIGGY_SCENES_TOKEN to {ENV_FILE} (valid until {expires:%d %b %H:%M} UTC). Restart the backend.")
    return 0


def _register() -> str:
    """Dynamic client registration; Swiggy returns its shared public client for localhost redirects."""
    try:
        resp = httpx.post(f"{AUTH}/register", json={
            "client_name": "perfect-saturday-local", "redirect_uris": [REDIRECT], "grant_types": ["authorization_code"],
            "response_types": ["code"], "token_endpoint_auth_method": "none",
        }, timeout=15)
        return resp.json().get("client_id") or "swiggy-mcp"
    except (httpx.HTTPError, ValueError):
        return "swiggy-mcp"


def _write_env(values: dict[str, str]) -> None:
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in values]
    ENV_FILE.write_text("\n".join(keep + [f"{k}={v}" for k, v in values.items()]) + "\n")


if __name__ == "__main__":
    sys.exit(main())
