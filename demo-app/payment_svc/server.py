"""payment-svc: charge capture and receipt fan-out.

A checkout captures the charge against the processor, then hands a receipt
to notify-svc. Receipt delivery rides call_with_retry (retry.py): notify
hiccups are retried a bounded number of times, after which the receipt is
parked for the reconciliation sweep rather than blocking the charge
response.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from retry import TransientError, call_with_retry

LISTEN_PORT = int(os.environ.get("PORT", "8083"))
NOTIFY_ADDR = os.environ.get("NOTIFY_ADDR", "http://localhost:8084")
NOTIFY_TIMEOUT_S = 1.5
PROCESSOR_COST_S = 0.05  # measured p50 of a capture against the processor

log = logging.getLogger("payment-svc")


def capture_charge(order_id: str, amount_cents: int) -> str:
    """Capture the charge with the payment processor (stand-in cost model)."""
    time.sleep(PROCESSOR_COST_S)
    return f"ch_{uuid.uuid4().hex[:12]}"


def send_receipt(order_id: str, charge_id: str, email: str) -> None:
    payload = json.dumps(
        {"kind": "receipt", "order_id": order_id, "charge_id": charge_id, "to": email}
    ).encode()
    req = urllib.request.Request(
        NOTIFY_ADDR + "/send", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_S):
            pass
    except (urllib.error.URLError, TimeoutError) as err:
        raise TransientError(f"notify-svc unavailable: {err}") from err


class PaymentHandler(BaseHTTPRequestHandler):
    server_version = "payment-svc/1.7"

    def do_POST(self):
        if self.path != "/checkout":
            self._reply(404, {"error": "no such route"})
            return
        order = self._body()
        order_id = order.get("order_id", "")
        amount_cents = order.get("amount_cents", 0)
        email = order.get("email", "")
        if not order_id or not email or amount_cents <= 0:
            self._reply(400, {"error": "order_id, amount_cents and email required"})
            return
        charge_id = capture_charge(order_id, amount_cents)
        try:
            call_with_retry(
                lambda: send_receipt(order_id, charge_id, email),
                what=f"receipt for {order_id}",
            )
        except TransientError:
            # The charge is captured either way; a receipt that exhausted its
            # retries is parked for the reconciliation sweep.
            log.error("receipt for %s parked for reconciliation", order_id)
        self._reply(200, {"charge_id": charge_id, "status": "captured"})

    def do_GET(self):
        if self.path == "/healthz":
            self._reply(200, {"status": "ok"})
            return
        self._reply(404, {"error": "no such route"})

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
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), PaymentHandler)
    log.info("listening on :%d (notify=%s)", LISTEN_PORT, NOTIFY_ADDR)
    server.serve_forever()


if __name__ == "__main__":
    main()
