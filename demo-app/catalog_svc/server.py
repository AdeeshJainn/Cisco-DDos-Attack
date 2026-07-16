"""catalog-svc: product listings and detail lookups.

Reads go through an in-process TTL cache (cache.py). Cache misses hit the
product database in batches — one round trip per request, however many ids
the page asks for.
"""

import json
import logging
import os
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cache import TTLCache

LISTEN_PORT = int(os.environ.get("PORT", "8082"))
MAX_IDS_PER_REQUEST = 50

# Stand-in for the product database client. Costs mirror production p50s:
# each round trip pays a fixed cost plus a small per-row cost.
DB_ROUND_TRIP_S = 0.004
DB_PER_ROW_S = 0.0003

log = logging.getLogger("catalog-svc")


class ProductDB:
    """Minimal product store with a batch read API."""

    def fetch_many(self, ids: list[str]) -> dict[str, dict]:
        time.sleep(DB_ROUND_TRIP_S + DB_PER_ROW_S * len(ids))
        return {pid: self._row(pid) for pid in ids}

    def fetch_one(self, pid: str) -> dict:
        time.sleep(DB_ROUND_TRIP_S + DB_PER_ROW_S)
        return self._row(pid)

    @staticmethod
    def _row(pid: str) -> dict:
        return {
            "id": pid,
            "name": f"Product {pid}",
            "price_cents": 999 + zlib.crc32(pid.encode()) % 9000,
            "in_stock": True,
        }


DB = ProductDB()
CACHE = TTLCache()


class CatalogHandler(BaseHTTPRequestHandler):
    server_version = "catalog-svc/3.2"

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/healthz":
            self._reply(200, {"status": "ok"})
            return
        if url.path.startswith("/product/"):
            pid = url.path.removeprefix("/product/")
            row = CACHE.get(pid, lambda: DB.fetch_one(pid))
            self._reply(200, {"product": row})
            return
        if url.path != "/products":
            self._reply(404, {"error": "no such route"})
            return
        raw = parse_qs(url.query).get("ids", [""])[0]
        ids = [pid.strip() for pid in raw.split(",") if pid.strip()]
        if not ids:
            self._reply(400, {"error": "ids required"})
            return
        if len(ids) > MAX_IDS_PER_REQUEST:
            self._reply(400, {"error": f"at most {MAX_IDS_PER_REQUEST} ids per request"})
            return
        self._reply(200, {"products": self._load(ids)})

    def _load(self, ids: list[str]) -> dict[str, dict]:
        """Serve each id from cache; fetch all misses in one batch round trip."""
        found: dict[str, dict] = {}
        missing: list[str] = []
        for pid in ids:
            row = CACHE.peek(pid)
            if row is None:
                missing.append(pid)
            else:
                found[pid] = row
        if missing:
            rows = DB.fetch_many(missing)
            for pid, row in rows.items():
                CACHE.put(pid, row)
            found.update(rows)
        return found

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
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), CatalogHandler)
    log.info("listening on :%d", LISTEN_PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
