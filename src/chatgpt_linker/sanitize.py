"""Small deterministic backstop, NOT a proof that content is non-sensitive.

No network, token validation, repository-config regexes, or raw-secret logging.
LLMs handle semantic redaction first; known credential patterns fail closed.
"""
from __future__ import annotations

import fnmatch
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import BridgeError
from .fs import read_source, relative_parts

MAX_FILE_BYTES = 200_000
MAX_BUNDLE_BYTES = 1_000_000
MAX_FILES = 64
MAX_LINE_BYTES = 12_000

DENIED_PARTS = {".git", ".ssh", ".aws", ".azure", ".gnupg", "node_modules", ".venv",
                "venv", "__pycache__", "dist", "build", "target", ".terraform"}
DENIED_NAMES = {"auth.json", "credentials", "credentials.json", "id_rsa", "id_ed25519",
                ".netrc", ".npmrc", ".pypirc", ".git-credentials", "kubeconfig"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db",
                   ".sql", ".log", ".csv", ".parquet", ".zip", ".gz", ".tar", ".7z"}

# The scanner reports only category names, never matched bytes.
SECRET_RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("url-credentials", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]{1,128}:[^\s/@]{1,256}@")),
    ("signed-url", re.compile(r"[?&](?:x-amz-signature|x-goog-signature|sig|access_token|api_key)=[^\s&#]+", re.I)),
    ("credential-assignment", re.compile(
        r'''(?im)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|secret[_-]?key)\b["']?\s*[:=]\s*["']?([^\s"',;\x60]{4,})''')),
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PRIVATE_IP = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
PLACEHOLDERS = {"none", "null", "true", "false", "changeme", "example", "placeholder", "redacted"}


def scan(text: str) -> list[str]:
    hits = set()
    for label, rule in SECRET_RULES:
        for match in rule.finditer(text):
            if label == "credential-assignment":
                value = match.group(1)
                if (value.lower() in PLACEHOLDERS or value.startswith(("<", "[", "${", "$", "os.environ", "process.env"))):
                    continue
            hits.add(label)
    return sorted(hits)


def assert_no_secrets(text: str) -> None:
    hits = scan(text)
    if hits:
        raise BridgeError("SECRET_DETECTED", "Publication blocked by credential categories: " + ", ".join(hits))


def valid_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        raise BridgeError("NON_TEXT", "Only UTF-8 text inputs are supported.") from exc
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise BridgeError("NON_TEXT", "Binary/control-character input is not allowed.")
    if any(len(line.encode("utf-8")) > MAX_LINE_BYTES for line in text.splitlines()):
        raise BridgeError("LINE_TOO_LONG", "Split unusually long source lines before publication.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class Policy:
    project_root: Path
    allowed_globs: tuple[str, ...]
    auto_publish: bool = False
    redact_emails: bool = True
    redact_private_ips: bool = True
    replacements: tuple[tuple[str, str], ...] = ()
    block_literals: tuple[str, ...] = ()
    ttl_hours: int = 24

    @classmethod
    def load(cls, path: Path) -> "Policy":
        path = path.expanduser().absolute()
        try:
            raw, _ = read_source(path.parent.resolve(), path.name, 65536)
            st = path.lstat()
            if st.st_uid != os.getuid() or st.st_mode & 0o022:
                raise BridgeError("UNSAFE_POLICY", "Policy must be owned by you and not writable by other users.")
            obj = tomllib.loads(raw.decode("utf-8"))
            allowed = {"version", "project_root", "allowed_globs", "auto_publish", "redact_emails",
                       "redact_private_ips", "redactions", "block_literals", "ttl_hours"}
            if set(obj) - allowed or obj.get("version") != 1:
                raise ValueError()
            root_value = obj["project_root"]
            if not isinstance(root_value, str) or not Path(root_value).expanduser().is_absolute():
                raise ValueError()
            root = Path(root_value).expanduser().resolve(strict=True)
            if not root.is_dir() or path.resolve().is_relative_to(root):
                raise BridgeError("UNTRUSTED_POLICY", "Keep the policy outside the project root.")
            globs = obj["allowed_globs"]
            if (not isinstance(globs, list) or not globs or len(globs) > 128 or
                    any(not isinstance(s, str) or not s or len(s) > 256 or s.startswith("/") or ".." in s.split("/") for s in globs)):
                raise ValueError()
            opts = {k: obj.get(k, default) for k, default in
                    (("auto_publish", False), ("redact_emails", True), ("redact_private_ips", True))}
            if any(type(v) is not bool for v in opts.values()):
                raise ValueError()
            ttl = obj.get("ttl_hours", 24)
            if type(ttl) is not int or not 1 <= ttl <= 168:
                raise ValueError()
            redactions = obj.get("redactions", [])
            if not isinstance(redactions, list) or len(redactions) > 128:
                raise ValueError()
            pairs = []
            for r in redactions:
                if not isinstance(r, dict) or set(r) != {"literal", "replacement"}:
                    raise ValueError()
                a, b = r["literal"], r["replacement"]
                if (not isinstance(a, str) or not a or not isinstance(b, str) or not b or
                        "\n" in a + b or len(a + b) > 1024):
                    raise ValueError()
                pairs.append((a, b))
            blocks = obj.get("block_literals", [])
            if not isinstance(blocks, list) or len(blocks) > 128 or any(not isinstance(s, str) or not s or len(s) > 1024 for s in blocks):
                raise ValueError()
            return cls(root, tuple(globs), **opts, replacements=tuple(pairs),
                       block_literals=tuple(blocks), ttl_hours=ttl)
        except (KeyError, ValueError, TypeError, OSError, UnicodeError) as exc:
            raise BridgeError("INVALID_POLICY", "Invalid policy; check the documented TOML schema.") from exc

    def check_path(self, name: str) -> None:
        parts = relative_parts(name)
        lower = [p.lower() for p in parts]
        if (any(p in DENIED_PARTS for p in lower) or lower[-1] in DENIED_NAMES or
                lower[-1].startswith(".env") or Path(lower[-1]).suffix in DENIED_SUFFIXES):
            raise BridgeError("EXCLUDED_FILE", "A selected file is excluded by the built-in policy.")
        if not any(fnmatch.fnmatchcase(name, g) for g in self.allowed_globs):
            raise BridgeError("OUT_OF_SCOPE", "A selected file is outside the approved path scope.")


class Sanitizer:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.mapping: dict[str, str] = {}

    def _alias(self, value: str, category: str) -> str:
        if value not in self.mapping:
            self.mapping[value] = f"[{category}_{len(self.mapping) + 1:03d}]"
        return self.mapping[value]

    def clean(self, text: str) -> str:
        assert_no_secrets(text)  # A configured rewrite cannot hide a credential hit.
        if any(s in text for s in self.policy.block_literals):
            raise BridgeError("SENSITIVE_LITERAL", "Publication blocked by a configured sensitive literal.")
        for old, new in self.policy.replacements:
            text = text.replace(old, new)
        if self.policy.redact_emails:
            text = EMAIL.sub(lambda m: self._alias(m.group(), "EMAIL"), text)
        if self.policy.redact_private_ips:
            text = PRIVATE_IP.sub(lambda m: self._alias(m.group(), "PRIVATE_IP"), text)
        assert_no_secrets(text)
        return valid_text(text.encode("utf-8"))
