"""edge-gw: public entry point for the storefront.

Terminates client traffic and forwards it to the backend services. The
gateway deliberately stays thin: route, bound concurrency, time out fast.
"""

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = int(os.environ.get("PORT", "8080"))

# Upstream addresses; production injects these via the environment.
AUTH_ADDR = os.environ.get("AUTH_ADDR", "http://localhost:8081")
CATALOG_ADDR = os.environ.get("CATALOG_ADDR", "http://localhost:8082")
PAYMENT_ADDR = os.environ.get("PAYMENT_ADDR", "http://localhost:8083")

# Size of the forwarding pool per instance. Requests beyond it wait briefly
# for a slot, then get shed with a 503 — the backends stay protected when the
# front door floods.
WORKER_THREADS = 32
SLOT_WAIT_S = 0.5
UPSTREAM_TIMEOUT_S = 2.5

ROUTES = {
    "/login": AUTH_ADDR,
    "/verify": AUTH_ADDR,
    "/products": CATALOG_ADDR,
    "/product": CATALOG_ADDR,
    "/checkout": PAYMENT_ADDR,
}

log = logging.getLogger("edge-gw")


class Gateway(BaseHTTPRequestHandler):
    server_version = "edge-gw/1.4"
    _slots = threading.BoundedSemaphore(WORKER_THREADS)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self) -> None:
        if self.path == "/healthz":
            self._reply(200, {"status": "ok"})
            return
        upstream = self._route()
        if upstream is None:
            self._reply(404, {"error": "no such route"})
            return
        if not self._slots.acquire(timeout=SLOT_WAIT_S):
            log.warning("worker pool exhausted, shedding %s", self.path)
            self._reply(503, {"error": "gateway busy"})
            return
        try:
            self._proxy(upstream)
        finally:
            self._slots.release()

    def _route(self) -> str | None:
        path = self.path.split("?", 1)[0]
        for prefix, upstream in ROUTES.items():
            if path == prefix or path.startswith(prefix + "/"):
                return upstream
        return None

    def _proxy(self, upstream: str) -> None:
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)
        req = urllib.request.Request(
            upstream + self.path,
            data=body,
            method=self.command,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        try:
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT_S) as resp:
                self._reply_raw(resp.status, resp.read())
        except urllib.error.HTTPError as err:
            self._reply_raw(err.code, err.read())
        except (urllib.error.URLError, TimeoutError):
            log.error("upstream %s timed out for %s", upstream, self.path)
            self._reply(504, {"error": "upstream timeout"})

    def _reply(self, status: int, obj: dict) -> None:
        self._reply_raw(status, json.dumps(obj).encode())

    def _reply_raw(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Gateway)
    log.info("listening on :%d (workers=%d)", LISTEN_PORT, WORKER_THREADS)
    server.serve_forever()


if __name__ == "__main__":
    main()
