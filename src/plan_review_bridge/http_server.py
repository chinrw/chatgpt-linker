"""Loopback-only stateless Streamable HTTP, for a local trusted client.

Authentication is a local bearer token. This is NOT a public OAuth server.
For ChatGPT, prefer the official tunnel's stdio transport instead.
"""
from __future__ import annotations

import hmac
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .protocol import MAX_MESSAGE, VERSIONS, MCPApplication, RpcError, encode, loads, rpc_error


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    allow_reuse_address = True

    def __init__(self, port: int, app: MCPApplication, token: str):
        if not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("HTTP token must be at least 32 characters")
        self.app, self.token = app, token
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(("127.0.0.1", port), Handler)


    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Never print a traceback containing transport secrets or tool inputs.
        pass


class Handler(BaseHTTPRequestHandler):
    server: LocalHTTPServer
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        pass  # Request bodies/paths/tokens are never access-logged.

    def reply(self, status: int, payload: dict | None = None):
        body = encode(payload) if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self) -> bool:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if len(self.headers.get_all("Host", [])) != 1 or self.headers.get("Host") not in hosts:
            self.reply(403, {"error": "host_rejected"})
            return False
        origin = self.headers.get("Origin")
        if len(self.headers.get_all("Origin", [])) > 1 or (origin is not None and origin not in {"http://" + h for h in hosts}):
            self.reply(403, {"error": "origin_rejected"})
            return False
        authorization = self.headers.get("Authorization", "")
        if (len(self.headers.get_all("Authorization", [])) != 1 or not authorization.isascii() or
                not hmac.compare_digest(authorization, "Bearer " + self.server.token)):
            self.reply(401, {"error": "unauthorized"})
            return False
        return True

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/mcp":
            self.reply(404)
            return
        if self.headers.get("MCP-Protocol-Version", "2025-03-26") not in VERSIONS:
            self.reply(400, {"error": "unsupported_protocol"})
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415)
            return
        accepts = self.headers.get("Accept", "")
        if "application/json" not in accepts or "text/event-stream" not in accepts:
            self.reply(406, {"error": "accept_json_and_event_stream"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1:
            self.reply(411)
            return
        try:
            size = int(lengths[0])
            if not 0 < size <= MAX_MESSAGE:
                self.reply(413)
                return
            raw = self.rfile.read(size)
            if len(raw) != size:
                self.reply(400)
                return
            request = loads(raw)
            response = self.server.app.handle(request)
            self.reply(202 if response is None else 200, response)
        except (ValueError, socket.timeout):
            self.reply(400)
        except RpcError as exc:
            self.reply(400, rpc_error(exc.code, exc.message))

    def do_GET(self):
        if self.authorized():
            # Stateless mode: no server-initiated SSE stream or implicit sessions.
            self.reply(405 if self.path == "/mcp" else 404)

    def do_DELETE(self):
        if self.authorized():
            self.reply(405)
