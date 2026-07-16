"""auth-svc: login and session verification.

Sessions are HMAC-signed tokens; credential lookups go through a fixed-size
database connection pool so a login burst cannot pile unbounded connections
onto the user store.
"""

import hashlib
import hmac
import json
import logging
import os
import queue
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LISTEN_PORT = int(os.environ.get("PORT", "8081"))
SIGNING_KEY = os.environ.get("AUTH_SIGNING_KEY", "dev-only-signing-key").encode()
TOKEN_TTL_S = 3600

# Pool sizing: a credentials lookup holds a connection ~20 ms, so 50
# connections ride out login bursts well past the planned peak (see
# topology.yaml capacity notes) without queueing.
POOL_SIZE = 50
CHECKOUT_TIMEOUT_S = 0.25
QUERY_COST_S = 0.02  # measured p50 of the credentials lookup

log = logging.getLogger("auth-svc")


def _password_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# The demo user table; production reads the same shape from the user store.
USERS = {
    "ava": _password_hash("hunter2"),
    "sam": _password_hash("correct-horse"),
    "kai": _password_hash("battery-staple"),
}


class PoolExhausted(Exception):
    pass


class ConnectionPool:
    """Fixed-size pool of handles into the user store.

    The stand-in cost model (one sleep per query) mirrors the production
    lookup's p50, so saturation behaviour under load is faithful.
    """

    def __init__(self, size: int) -> None:
        self._conns: queue.Queue[int] = queue.Queue(maxsize=size)
        for conn_id in range(size):
            self._conns.put(conn_id)

    def query_password_hash(self, user: str) -> str | None:
        try:
            conn = self._conns.get(timeout=CHECKOUT_TIMEOUT_S)
        except queue.Empty:
            raise PoolExhausted("no database connection available") from None
        try:
            time.sleep(QUERY_COST_S)
            return USERS.get(user)
        finally:
            self._conns.put(conn)


POOL = ConnectionPool(POOL_SIZE)


def issue_token(user: str) -> str:
    payload = f"{user}:{int(time.time()) + TOKEN_TTL_S}"
    sig = hmac.new(SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_token(token: str) -> bool:
    try:
        user, expires, sig = token.rsplit(":", 2)
    except ValueError:
        return False
    expect = hmac.new(SIGNING_KEY, f"{user}:{expires}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expect) and int(expires) > time.time()


class AuthHandler(BaseHTTPRequestHandler):
    server_version = "auth-svc/2.1"

    def do_POST(self):
        if self.path != "/login":
            self._reply(404, {"error": "no such route"})
            return
        creds = self._body()
        user = creds.get("user", "")
        password = creds.get("password", "")
        if not user or not password:
            self._reply(400, {"error": "user and password required"})
            return
        try:
            stored = POOL.query_password_hash(user)
        except PoolExhausted:
            log.error("connection pool exhausted during login for %r", user)
            self._reply(503, {"error": "auth store unavailable"})
            return
        if stored is None or not hmac.compare_digest(_password_hash(password), stored):
            self._reply(401, {"error": "invalid credentials"})
            return
        self._reply(200, {"token": issue_token(user)})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/healthz":
            self._reply(200, {"status": "ok"})
            return
        if url.path != "/verify":
            self._reply(404, {"error": "no such route"})
            return
        token = parse_qs(url.query).get("token", [""])[0]
        if not verify_token(token):
            self._reply(401, {"valid": False})
            return
        self._reply(200, {"valid": True})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _reply(self, status: int, obj: dict) -> None:
        payload = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), AuthHandler)
    log.info("listening on :%d (pool=%d)", LISTEN_PORT, POOL_SIZE)
    server.serve_forever()


if __name__ == "__main__":
    main()
