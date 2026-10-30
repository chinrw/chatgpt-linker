"""Exercise the generated Home Manager service with synthetic runtime files."""

import http.client
import json
import secrets
import ssl
import subprocess
import sys
import time
from pathlib import Path

from chatgpt_linker.exchange_http import RemoteExchange
from chatgpt_linker.store import LocalStore
from support import Fixture, REVIEW


prepare, start, linker, directory = sys.argv[1:]
root = Path(directory)
token = root / "exchange token"
cert = root / "exchange cert.pem"
key = root / "exchange key.pem"
token.write_text(secrets.token_urlsafe(48))
token.chmod(0o400)
subprocess.run([
    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
    "-keyout", str(key), "-out", str(cert),
], check=True, capture_output=True)
key.chmod(0o400)
context = ssl.create_default_context(cafile=str(cert))


def launch():
    subprocess.run([prepare], check=True)
    for name in ("", "inbox", "outbox"):
        assert (root / "exchange with spaces" / name).stat().st_mode & 0o777 == 0o700
    process = subprocess.Popen([start])
    try:
        for _ in range(100):
            assert process.poll() is None, "The generated exchange service exited."
            connection = http.client.HTTPSConnection("localhost", 18767, context=context, timeout=1)
            try:
                connection.request("GET", "/v1/tasks/pr_000000000000000000000000")
                response = connection.getresponse()
                assert response.status == 401
                response.read()
                return process
            except ConnectionRefusedError:
                time.sleep(0.05)
            finally:
                connection.close()
        raise AssertionError("The generated exchange service did not become ready.")
    except BaseException:
        process.terminate()
        process.wait(timeout=5)
        raise


fixture = Fixture()
fixture.setUp()
process = None
try:
    process = launch()
    fixture.store.remote = RemoteExchange("https://localhost:18767", str(token), str(cert))
    rid, sha = fixture.published()
    first = fixture.store.status(rid)
    process.terminate()
    process.wait(timeout=5)
    process = None
    process = launch()
    resumed = LocalStore(fixture.store.root)
    assert resumed.publish(rid, approve=True) == first
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "submit_review", "arguments": {
                "request_id": rid, "bundle_sha256": sha, "markdown": REVIEW,
            },
        }},
    ]
    result = subprocess.run([
        linker, "serve", "--exchange", str(root / "exchange with spaces"),
    ], input="".join(json.dumps(m) + "\n" for m in messages), text=True,
        capture_output=True, check=True, timeout=10)
    response = json.loads(result.stdout.splitlines()[-1])
    assert response["result"]["structuredContent"]["status"] == "completed", response
    received = resumed.result(rid)
    assert Path(received["artifact_path"]).read_text() == REVIEW
    assert received["receipt"]["source"] == "mcp_submit"
    assert resumed.result(rid)["receipt"] == received["receipt"]
    assert received["source_check"]["unchanged"]
    assert not (fixture.store.exchange.inbox / rid).exists()
    print("Generated exchange service: TLS, authentication, restart, retry and MCP result retrieval passed.")
finally:
    if process is not None:
        process.terminate()
        process.wait(timeout=5)
    fixture.tearDown()
