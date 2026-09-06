"""Tiny status page served from inside the bot process (stdlib only, daemon thread).

GET /             the dashboard (web/index.html)
GET /status.json  latest tick snapshot + recent journal rows
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
from journal import log
from status import with_trades

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port silently, so a second
    # bot copy would hijack the page. Only Unix needs the flag (to skip TIME_WAIT after a restart).
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


class StatusServer:
    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or config.WEB_HOST
        self.port = port if port is not None else config.WEB_PORT
        self._status: dict = {"market_open": False, "positions": [], "traders": [],
                              "day": {}, "breaker": None, "uptime_seconds": 0, "symbols": []}
        self._lock = threading.Lock()
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> bool:
        server = self
        html_path = HTML_PATH

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):            # keep the bot log quiet
                pass

            def _send(self, code: int, body: bytes, ctype: str):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    try:
                        with open(html_path, "rb") as f:
                            self._send(200, f.read(), "text/html; charset=utf-8")
                    except OSError:
                        self._send(500, b"web/index.html missing", "text/plain")
                elif path == "/status.json":
                    self._send(200, server.payload(), "application/json")
                else:
                    self._send(404, b"not found", "text/plain")

        try:
            self._httpd = _Server((self.host, self.port), Handler)
        except OSError as e:
            log.error("status page NOT started on %s:%d (%s); bot continues without it",
                      self.host, self.port, e)
            return False
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="web", daemon=True)
        self._thread.start()
        log.info("status page at http://%s:%d/", self.host, self.port)
        return True

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def bound_port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else self.port

    # -- data ------------------------------------------------------------------
    def update(self, status: dict) -> None:
        with self._lock:
            self._status = status

    def payload(self) -> bytes:
        with self._lock:
            data = self._status
        return json.dumps(with_trades(data), default=str).encode("utf-8")
