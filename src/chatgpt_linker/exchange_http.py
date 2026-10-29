"""Authenticated producer transport for one owner's machines and exchange node."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .errors import BridgeError
from .fs import MAX_JSON, canonical, safe_read
from .http_server import BoundedHTTPServer, Handler
from .protocol import MAX_MESSAGE, RpcError, loads
from .store import Exchange, valid_rid

DEFAULT_PORTS = {"http": 80, "https": 443}


def read_token(path: Path) -> str:
    token = safe_read(path.expanduser().absolute(), 4096).decode().strip()
    if not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
        raise BridgeError("HTTP_CONFIG", "Use a private token file containing 32-256 ASCII characters.")
    return token


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_authority(value: str, default_port: int) -> tuple[str, int]:
    try:
        if not value.isascii() or any(c.isspace() or ord(c) < 32 or c in "/?#" for c in value):
            raise ValueError()
        parsed = urlsplit("//" + value)
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        port = parsed.port if parsed.port is not None else default_port
        if not 1 <= port <= 65535:
            raise ValueError()
        return parsed.hostname, port
    except ValueError as exc:
        raise BridgeError("HTTP_CONFIG", "Use a hostname with an optional valid port.") from exc


class RemoteExchange:
    def __init__(self, url: str, token_file: str, ca_file: str | None = None):
        try:
            if not isinstance(url, str) or not url.isascii() or any(c.isspace() or ord(c) < 32 for c in url):
                raise ValueError()
            parsed = urlsplit(url)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or
                    parsed.password is not None or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
                raise ValueError()
            self.host, self.port = normalize_authority(parsed.netloc, DEFAULT_PORTS[parsed.scheme])
            if parsed.scheme == "http" and not loopback(self.host):
                raise ValueError()
        except ValueError as exc:
            raise BridgeError("HTTP_CONFIG", "Use an HTTPS exchange origin; plain HTTP is allowed only on loopback.") from exc
        self.scheme = parsed.scheme
        host = f"[{self.host}]" if ":" in self.host else self.host
        port = f":{self.port}" if self.port != DEFAULT_PORTS[self.scheme] else ""
        self.url = f"{self.scheme}://{host}{port}"
        self.token_file = str(Path(token_file).expanduser().absolute())
        self.ca_file = str(Path(ca_file).expanduser().absolute()) if ca_file else None

    def config(self) -> dict:
        # Store credential paths, never their contents, beside the source-only provenance.
        return {"url": self.url, "token_file": self.token_file, "ca_file": self.ca_file}

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        token = read_token(Path(self.token_file))
        data = canonical(payload) if payload is not None else None
        if data is not None and len(data) > MAX_JSON:
            raise BridgeError("INPUT_LIMIT", "Exchange request exceeds the upload limit.")
        context = None
        if self.scheme == "https":
            try:
                context = ssl.create_default_context(cafile=self.ca_file)
            except OSError as exc:
                raise BridgeError("HTTP_CONFIG", "Could not load the configured exchange CA certificate.") from exc
        conn = None
        try:
            if self.scheme == "https":
                conn = http.client.HTTPSConnection(self.host, self.port, timeout=30, context=context)
            else:
                conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
            # http.client does not inherit proxy settings or follow credential-bearing redirects.
            conn.request(method, path, body=data, headers={"Authorization": "Bearer " + token,
                         "Content-Type": "application/json", "Accept": "application/json"})
            response = conn.getresponse()
            raw = response.read(MAX_MESSAGE + 1)
            if response.status != 200:
                if response.status in (400, 409):
                    error = loads(raw)
                    if isinstance(error.get("error"), str) and isinstance(error.get("message"), str):
                        # Preserve the code but do not echo remote text or proxy error pages.
                        raise BridgeError(error["error"], "The exchange rejected this operation.")
                raise BridgeError("EXCHANGE_HTTP", f"Exchange returned HTTP {response.status}; no local fallback was used.")
            return loads(raw)
        except ssl.SSLError as exc:
            raise BridgeError("EXCHANGE_TLS", "Exchange TLS verification or handshake failed; check the certificate and hostname.") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise BridgeError("EXCHANGE_UNREACHABLE", "Exchange connection failed; retry this task on the same node.") from exc
        except RpcError as exc:
            raise BridgeError("EXCHANGE_RESPONSE", "Exchange returned an invalid or oversized response.") from exc
        finally:
            if conn:
                conn.close()

    def publish(self, bundle: dict, ttl_hours: int, *, allow_submit: bool = True) -> dict:
        return self.request("POST", "/v1/tasks", {"bundle": bundle, "ttl_hours": ttl_hours, "allow_submit": allow_submit})

    def status(self, rid: str) -> dict:
        return self.request("GET", f"/v1/tasks/{valid_rid(rid)}")

    def result(self, rid: str) -> dict:
        return self.request("GET", f"/v1/tasks/{valid_rid(rid)}/result")

    def cancel(self, rid: str) -> dict:
        return self.request("POST", f"/v1/tasks/{valid_rid(rid)}/cancel", {})

    def import_result(self, rid: str, sha: str, markdown: str) -> dict:
        return self.request("POST", f"/v1/tasks/{valid_rid(rid)}/import",
                            {"bundle_sha256": sha, "markdown": markdown})


class ExchangeHTTPServer(BoundedHTTPServer):
    def __init__(self, address: tuple[str, int], exchange: Exchange, token: str, *,
                 allowed_hosts: list[str] | None = None, tls_context: ssl.SSLContext | None = None):
        if not loopback(address[0]) and tls_context is None:
            raise BridgeError("HTTP_CONFIG", "Non-loopback listeners require TLS; a local HTTPS proxy can use loopback.")
        self.exchange, self.tls_context = exchange, tls_context
        self.default_port = DEFAULT_PORTS["https" if tls_context else "http"]
        self.allowed_hosts = {normalize_authority(host, self.default_port) for host in allowed_hosts or ()}
        super().__init__(address, ExchangeHandler, token)
        # Uploads may contain tens of megabytes, unlike the small MCP messages.
        self.slots = threading.BoundedSemaphore(4)
        if not self.allowed_hosts:
            self.allowed_hosts.add(normalize_authority(f"{address[0]}:{self.server_port}", self.default_port))
        if address[0] == "127.0.0.1":
            self.allowed_hosts.add(("localhost", self.server_port))

    def get_request(self):
        conn, address = super().get_request()
        conn.settimeout(15)
        if self.tls_context:
            # Handshake in the bounded worker, so an idle TLS client cannot block accept().
            conn = self.tls_context.wrap_socket(conn, server_side=True, do_handshake_on_connect=False)
        return conn, address


class ExchangeHandler(Handler):
    server: ExchangeHTTPServer

    def authorized(self) -> bool:
        try:
            if len(self.headers.get_all("Host", [])) != 1:
                raise ValueError()
            host = normalize_authority(self.headers["Host"], self.server.default_port)
            if host not in self.server.allowed_hosts:
                raise ValueError()
        except (BridgeError, ValueError):
            self.reply(403, {"error": "host_rejected"})
            return False
        # Producer calls come from the CLI. No browser origin is part of this interface.
        if self.headers.get_all("Origin", []):
            self.reply(403, {"error": "origin_rejected"})
            return False
        return self.bearer_authorized()

    def read_body(self) -> dict:
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1 or
                self.headers.get_content_type() != "application/json"):
            raise BridgeError("INVALID_REQUEST", "Send bounded JSON with a single Content-Length.")
        size = int(lengths[0])
        if not 0 < size <= MAX_JSON:
            raise BridgeError("INPUT_LIMIT", "Exchange request exceeds the upload limit.")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise BridgeError("INVALID_REQUEST", "Incomplete request body.")
        return loads(raw, max_bytes=MAX_JSON)

    def dispatch(self, method: str):
        if not self.authorized():
            return
        try:
            fields = self.path.split("/")
            if fields[:3] != ["", "v1", "tasks"] or len(fields) not in (3, 4, 5):
                self.reply(404)
                return
            if method == "POST" and len(fields) == 3:
                body = self.read_body()
                if set(body) != {"bundle", "ttl_hours", "allow_submit"}:
                    raise BridgeError("INVALID_REQUEST", "Supply only a frozen bundle, TTL and submission grant.")
                result = self.server.exchange.publish(body["bundle"], body["ttl_hours"], allow_submit=body["allow_submit"])
            elif len(fields) >= 4:
                rid = valid_rid(fields[3])
                action = fields[4] if len(fields) == 5 else ""
                if method == "GET" and action == "":
                    result = self.server.exchange.status(rid)
                elif method == "GET" and action == "result":
                    result = self.server.exchange.result(rid)
                elif method == "POST" and action == "cancel":
                    if self.read_body() != {}:
                        raise BridgeError("INVALID_REQUEST", "Cancel accepts an empty object.")
                    result = self.server.exchange.cancel(rid)
                elif method == "POST" and action == "import":
                    body = self.read_body()
                    if set(body) != {"bundle_sha256", "markdown"}:
                        raise BridgeError("INVALID_REQUEST", "Supply a bundle hash and complete Markdown.")
                    result = self.server.exchange.submit(rid, body["bundle_sha256"], body["markdown"], source="manual_import")
                else:
                    self.reply(404)
                    return
            else:
                self.reply(404)
                return
            self.reply(200, result)
        except BridgeError as exc:
            self.reply(409, exc.as_dict())
        except (ValueError, TypeError, KeyError, RecursionError, RpcError, socket.timeout):
            self.reply(400, {"error": "INVALID_REQUEST", "message": "Invalid exchange request."})
        except OSError:
            self.reply(500, {"error": "EXCHANGE_IO"})

    def do_POST(self):
        self.dispatch("POST")

    def do_GET(self):
        self.dispatch("GET")
