"""Local task lifecycle and server entry points. No model-provider requests."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

from . import __version__
from .errors import BridgeError
from .fs import canonical, private_dir, read_source, safe_read, write_new
from .protocol import MCPApplication, serve_stdio
from .sanitize import MAX_FILE_BYTES
from .store import Exchange, LocalStore


def default_state() -> Path:
    override = os.environ.get("CHATGPT_LINKER_STATE")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "chatgpt-linker"


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Review plans through ChatGPT's user-initiated MCP connection.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--state", type=Path, default=default_state(), help="Private state directory, outside the source repo")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create private task storage")
    policy = sub.add_parser("policy-init", help="Create a USER-approved publication policy outside the repo")
    policy.add_argument("--repo", type=Path, required=True)
    policy.add_argument("--output", type=Path, required=True)
    policy.add_argument("--allow", action="append", required=True, help="Approved relative path glob; repeatable")
    policy.add_argument("--deny", action="append", default=[], help="Relative path glob excluded even when allowed; repeatable")
    policy.add_argument("--auto-publish", action="store_true", help="Authorize future selected inputs within this scope")
    prep = sub.add_parser("prepare", help="Scan and freeze explicitly selected evidence")
    prep.add_argument("--policy", type=Path, required=True)
    plan = prep.add_mutually_exclusive_group(required=True)
    plan.add_argument("--plan", help="Existing relative plan path inside the approved project")
    plan.add_argument("--draft-stdin", action="store_true", help="Read an agent-generated draft from stdin; never write it to the repo")
    prep.add_argument("--file", action="append", default=[], help="Exact approved relative file; repeatable")
    prep.add_argument("--auto", action="store_true", help="Also select every policy-allowed text file under the project")
    prep.add_argument("--glob", action="append", default=[], help="Narrow --auto to matching relative paths; repeatable")
    prep.add_argument("--goal", required=True)
    prep.add_argument("--publish", action="store_true", help="Publish only if policy auto_publish is true")
    pub = sub.add_parser("publish", help="Publish a frozen task and grant the private MCP access")
    pub.add_argument("request_id")
    pub.add_argument("--approve", action="store_true", help="Explicit one-time approval of this task's upload scope")
    pub.add_argument("--read-only", action="store_true", help="Do not grant remote submit_review for this task")
    for name in ("status", "prompt", "result", "check", "cancel"):
        s = sub.add_parser(name)
        s.add_argument("request_id")
    wait = sub.add_parser("wait", help="Wait only on local storage; exit 3 on timeout")
    wait.add_argument("request_id")
    # 90 min: one ChatGPT Pro reasoning pass can run close to an hour.
    wait.add_argument("--timeout", type=float, default=5400)
    wait.add_argument("--interval", type=float, default=1)
    imp = sub.add_parser("import", help="Manual fallback when ChatGPT cannot call the write tool")
    imp.add_argument("request_id")
    imp.add_argument("--file", type=Path, required=True)
    imp.add_argument("--bundle-sha256", required=True)
    serve = sub.add_parser("serve", help="Remote evidence MCP: search, fetch, and narrowly scoped submit_review")
    serve.add_argument("--exchange", type=Path, required=True, help="Only the exchange directory, NOT source/private state")
    serve.add_argument("--request", help="Optionally pin this connection to one exact task")
    serve.add_argument("--read-only", action="store_true", help="Omit submit_review from tools/list entirely")
    serve.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--token-file", type=Path, help="Required for local HTTP; private file containing a local bearer token")
    sub.add_parser("serve-control", help="LOCAL agent stdio MCP: review_status, review_result, review_wait")
    token = sub.add_parser("http-token", help="Create a private LOCAL HTTP token, never a model API key")
    token.add_argument("--output", type=Path, required=True)
    sub.add_parser("doctor", help="Report environment and state; does not contact ChatGPT")
    return p


def run(args: argparse.Namespace) -> int:
    if args.command == "policy-init":
        from .sanitize import Policy
        repo, output = args.repo.expanduser().resolve(strict=True), args.output.expanduser().absolute()
        if not repo.is_dir() or output.resolve().is_relative_to(repo):
            raise BridgeError("UNTRUSTED_POLICY", "Policy must be outside the source project.")
        private_dir(output.parent)
        content = ("version = 1\n" + f"project_root = {json.dumps(str(repo))}\n" +
                   f"allowed_globs = {json.dumps(args.allow)}\n" +
                   f"denied_globs = {json.dumps(args.deny)}\n" +
                   f"auto_publish = {str(args.auto_publish).lower()}\n" +
                   "redact_emails = true\nredact_private_ips = true\nttl_hours = 24\nblock_literals = []\n")
        try:
            write_new(output, content.encode())
        except FileExistsError as exc:
            raise BridgeError("POLICY_EXISTS", "Refusing to overwrite an existing policy.") from exc
        try:
            Policy.load(output)
        except BaseException:
            output.unlink()
            raise
        emit({"policy_path": str(output), "auto_publish": args.auto_publish,
              "notice": "Use only for data you have permission to send to ChatGPT. Scanning is not a guarantee."})
        return 0
    if args.command == "http-token":
        output = args.output.expanduser().absolute()
        private_dir(output.parent)
        try:
            write_new(output, (secrets.token_urlsafe(48) + "\n").encode())
        except FileExistsError as exc:
            raise BridgeError("TOKEN_EXISTS", "Refusing to overwrite an existing token file.") from exc
        emit({"token_file": str(output), "purpose": "local HTTP transport only; value not printed"})
        return 0
    if args.command == "serve":
        exchange = Exchange(args.exchange, args.request)
        app = MCPApplication(exchange, read_only=args.read_only)
        if args.transport == "stdio":
            serve_stdio(app)
        else:
            from .http_server import LocalHTTPServer
            if args.token_file is None or not 1 <= args.port <= 65535:
                raise BridgeError("HTTP_CONFIG", "Local HTTP requires --token-file and a valid port.")
            if args.token_file.expanduser().resolve().is_relative_to(args.exchange.expanduser().resolve()):
                raise BridgeError("HTTP_CONFIG", "Keep the HTTP token outside the published exchange directory.")
            token = safe_read(args.token_file.expanduser().absolute(), 4096).decode().strip()
            if not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
                raise BridgeError("HTTP_CONFIG", "Invalid local HTTP token.")
            server = LocalHTTPServer(args.port, app, token)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        return 0
    if args.command == "prepare":
        # Validate placement BEFORE creating state; an incorrect --state must not
        # write directories into the very source project we promised to leave alone.
        from .sanitize import Policy
        policy = Policy.load(args.policy)
        if args.state.expanduser().resolve().is_relative_to(policy.project_root):
            raise BridgeError("STATE_IN_PROJECT", "Keep bridge state outside the source project.")
    store = LocalStore(args.state, create=args.command in ("init", "prepare"))
    if args.command == "init":
        emit({"state": str(store.root), "exchange": str(store.exchange.root)})
    elif args.command == "prepare":
        draft = None
        if args.draft_stdin:
            try:
                raw = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError()
                draft = raw.decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise BridgeError("INVALID_PLAN", "Draft must be bounded UTF-8 text.") from exc
        prepared = store.prepare(args.policy, args.plan, args.file, args.goal, draft=draft, auto=args.auto, globs=args.glob)
        if args.publish:
            try:
                prepared = {**prepared, **store.publish(prepared["request_id"])}  # keep files/skipped visible
            except BridgeError as exc:
                emit({**prepared, **exc.as_dict()})
                return 2
        emit(prepared)
    elif args.command == "publish":
        emit(store.publish(args.request_id, approve=args.approve, allow_submit=not args.read_only))
    elif args.command == "status":
        emit(store.status(args.request_id))
    elif args.command == "prompt":
        print(store.prompt(args.request_id))
    elif args.command == "result":
        emit(store.result(args.request_id))
    elif args.command == "check":
        check = store.check_source(args.request_id)
        emit(check)
        return 0 if check["unchanged"] else 4
    elif args.command == "cancel":
        emit(store.cancel(args.request_id))
    elif args.command == "wait":
        if not 0 <= args.timeout <= 86400 or not 0.1 <= args.interval <= 60:
            raise BridgeError("INVALID_WAIT", "Timeout must be 0-86400 seconds; interval 0.1-60 seconds.")
        deadline = time.monotonic() + args.timeout
        while True:
            status = store.status(args.request_id)
            if status["status"] == "completed":
                emit(store.result(args.request_id))
                return 0
            if status["status"] in ("cancelled", "expired"):
                emit(status)
                return 4
            if time.monotonic() >= deadline:
                emit({**status, "wait_timed_out": True})
                return 3
            time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
    elif args.command == "import":
        f = args.file.expanduser().absolute()
        raw, _ = read_source(f.parent.resolve(), f.name, 256000)
        try:
            markdown = raw.decode("utf-8")
        except UnicodeError as exc:
            raise BridgeError("INVALID_SUBMISSION", "Manual result must be UTF-8 Markdown.") from exc
        emit(store.exchange.submit(args.request_id, args.bundle_sha256, markdown, source="manual_import"))
    elif args.command == "serve-control":
        serve_stdio(MCPApplication(local=store))
    elif args.command == "doctor":
        emit({"version": __version__, "python": sys.version.split()[0], "platform": sys.platform,
              "state": str(store.root), "exchange": str(store.exchange.root),
              "model_api_backend": False, "browser_automation": False,
              "chatgpt_live_connection_verified": False,
              "next_check": "Use a synthetic request to verify the selected ChatGPT Pro session and submit_review."})
    return 0


def main() -> int:
    if os.name != "posix":
        print('{"error":"UNSUPPORTED_OS","message":"Use Linux, macOS, or WSL2."}', file=sys.stderr)
        return 2
    try:
        return run(parser().parse_args())
    except BridgeError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        # Do not include input content or filesystem paths in machine-readable error logs.
        print(json.dumps({"error": "LOCAL_ERROR", "message": type(exc).__name__ + ": check local files and permissions."}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
