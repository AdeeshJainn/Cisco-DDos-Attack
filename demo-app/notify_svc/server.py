"""notify-svc: receipt and alert delivery.

Wraps the mail/push providers behind one /send endpoint. Recent deliveries
are kept for the on-call debugging view (/recent) in a bounded ring, so
retention can never grow with traffic.
"""

import json
import logging
import os
import random
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = int(os.environ.get("PORT", "8084"))
PROVIDER_COST_S = 0.03  # measured p50 of a provider handoff
PROVIDER_FLAKE_RATE = 0.01  # transient provider failures, weekly average

# The on-call view only ever needs the tail; the ring bounds memory.
RECENT_LIMIT = 2000
RECENT: deque[dict] = deque(maxlen=RECENT_LIMIT)

log = logging.getLogger("notify-svc")


class ProviderError(Exception):
    pass


def deliver(message: dict) -> str:
    """Hand the message to the provider; returns the provider message id."""
    time.sleep(PROVIDER_COST_S)
    if random.random() < PROVIDER_FLAKE_RATE:
        raise ProviderError("provider rejected the handoff")
    return f"msg_{int(time.time() * 1000):x}"


class NotifyHandler(BaseHTTPRequestHandler):
    server_version = "notify-svc/1.2"

    def do_POST(self):
        if self.path != "/send":
            self._reply(404, {"error": "no such route"})
            return
        message = self._body()
        to = message.get("to", "")
        kind = message.get("kind", "generic")
        if not to:
            self._reply(400, {"error": "recipient required"})
            return
        try:
            msg_id = deliver(message)
        except ProviderError as err:
            log.warning("delivery to %s failed: %s", to, err)
            self._reply(502, {"error": "provider unavailable"})
            return
        RECENT.append({"ts": time.time(), "to": to, "kind": kind, "msg_id": msg_id})
        self._reply(200, {"msg_id": msg_id, "status": "sent"})

    def do_GET(self):
        if self.path == "/healthz":
            self._reply(200, {"status": "ok"})
            return
        if self.path != "/recent":
            self._reply(404, {"error": "no such route"})
            return
        self._reply(200, {"recent": list(RECENT)[-50:]})

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
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), NotifyHandler)
    log.info("listening on :%d (recent ring=%d)", LISTEN_PORT, RECENT_LIMIT)
    server.serve_forever()


if __name__ == "__main__":
    main()
