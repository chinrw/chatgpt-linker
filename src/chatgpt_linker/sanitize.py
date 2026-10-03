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
MAX_LINE_BYTES = 12_000
# Hard ceilings enforced on both sides of the exchange; a policy may only lower them.
MAX_FILES = 2048
MAX_BUNDLE_BYTES = 32_000_000
DEFAULT_MAX_FILES = 512
DEFAULT_MAX_BUNDLE_BYTES = 8_000_000

DENIED_PARTS = {".git", ".ssh", ".aws", ".azure", ".gnupg", "node_modules", ".venv",
                "venv", "__pycache__", "dist", "build", "target", ".terraform"}
DENIED_NAMES = {"auth.json", "credentials", "credentials.json", "id_rsa", "id_ed25519",
                ".netrc", ".npmrc", ".pypirc", ".git-credentials", "kubeconfig"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db",
                   ".sql", ".log", ".csv", ".parquet", ".zip", ".gz", ".tar", ".7z"}
# Skipped by automatic selection only; an explicit --file may still name them.
AUTO_SKIP_PARTS = {".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", ".eggs",
                   ".cache", ".idea", ".vscode"}
AUTO_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock",
                   "cargo.lock", "gemfile.lock", "composer.lock", "go.sum"}

# Lookarounds instead of \b: "_" is a word character, so \bapi_key\b never matched
# environment-style names such as OPENAI_API_KEY or DB_PASSWORD.
CREDENTIAL_NAME = (r"(?:api[_-]?(?:key|token|secret)|access[_-]?(?:key|token)|auth[_-]?token|refresh[_-]?token|"
                   r"bearer[_-]?token|client[_-]?secret|secret[_-]?(?:access[_-]?)?key|private[_-]?key|"
                   r"password|passwd|secret|token)")

# The scanner reports only category names, never matched bytes.
SECRET_RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("sk-api-key", re.compile(r"\bsk-(?:proj-|svcacct-|ant-)?[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}")),
    ("slack-webhook", re.compile(r"hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/[A-Za-z0-9]{16,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}")),
    ("gitlab-token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi-token", re.compile(r"\bpypi-AgE[A-Za-z0-9_-]{50,}")),
    ("azure-account-key", re.compile(r"\bAccountKey=[A-Za-z0-9+/]{20,}", re.I)),
    # The digit lookahead keeps prose such as "Bearer token-based-authentication" out.
    ("bearer-token", re.compile(r"\bBearer\s+(?=[A-Za-z._~+/-]*\d)[A-Za-z0-9._~+/-]{20,}", re.I)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("url-credentials", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]{1,128}:[^\s/@]{1,256}@")),
    ("signed-url", re.compile(r"[?&](?:x-amz-signature|x-goog-signature|sig|access_token|api_key)=[^\s&#]+", re.I)),
    ("credential-assignment", re.compile(
        r'''(?im)(?<![A-Za-z0-9])''' + CREDENTIAL_NAME +
        # Group 2 is a quoted value. Group 3 is an unquoted value, which also stops at
        # code punctuation so calls, subscripts, and generic types can be recognized.
        r'''(?![A-Za-z0-9])["']?\s*[:=]\s*(?:(["'])([^\s"',;\x60]{4,})|([^\s"',;\x60()\[\]{}<>&*]{4,}))''')),
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PRIVATE_IP = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
PLACEHOLDERS = {"none", "null", "true", "false", "changeme", "example", "placeholder", "redacted"}
# A value containing one of these words as a separate token is a fixture, canary,
# or template ("test-password", "CANARY_KEY", "your-api-key-here"), not a live credential.
PLACEHOLDER_WORDS = {"canary", "changeme", "dummy", "example", "fake", "fixture", "leak", "mock", "placeholder",
                     "redacted", "sample", "secret", "sentinel", "synthetic", "test", "your"}
IDENTIFIER_CHAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
LETTERS_ONLY = re.compile(r"[A-Za-z_]+\Z")
# Upper-case words joined by "_" or "-" name a constant. Generated credentials are not word
# lists. Three letters per segment keeps recovery-code formats such as AB12-CD34 flagged.
WORD_CONSTANT = re.compile(r"[A-Z]{3,}[0-9]*(?:[_-][A-Z]{3,}[0-9]*)+\Z")


def _is_reference(match: re.Match, text: str) -> bool:
    """True when an assignment's value is a placeholder or code, not a literal secret."""
    quoted, value = match.group(1), match.group(2) or match.group(3)
    lower = value.lower()
    if (lower in PLACEHOLDERS or value.startswith(("<", "$", "%", "os.environ", "process.env")) or
            PLACEHOLDER_WORDS & set(re.split(r"[^a-z0-9]+", lower)) or len(set(lower)) <= 2 or
            "..." in value or "0123456789" in value or WORD_CONSTANT.match(value)):
        return True
    if quoted:
        return False
    # Unquoted values in source code are usually expressions: calls, subscripts,
    # generic types, attribute chains, or variable names.
    if text[match.end():match.end() + 1] in ("(", "[", "<") or IDENTIFIER_CHAIN.match(value):
        return True
    if not LETTERS_ONLY.match(value):
        return False
    # A letters-only value is a variable in code ("let token = match", "bot_token: String,")
    # but a passphrase on a config line, where the key starts the line and the value ends it.
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    prefix = text[line_start:match.start()].strip()
    rest = text[match.end():len(text) if line_end < 0 else line_end].strip()
    return not (prefix in ("", "-", "export") and (not rest or rest.startswith("#")))


def scan(text: str) -> list[str]:
    hits = set()
    for label, rule in SECRET_RULES:
        for match in rule.finditer(text):
            if label == "credential-assignment" and _is_reference(match, text):
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


def sensitive_path() -> Path:
    """Global sensitive-literal file, merged into every policy when present."""
    override = os.environ.get("CHATGPT_LINKER_SENSITIVE")
    if override:
        return Path(override).expanduser()
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return config / "chatgpt-linker" / "sensitive.toml"


def _trusted_toml(path: Path, allowed_keys: set[str]) -> dict:
    raw, _ = read_source(path.parent.resolve(), path.name, 65536)
    st = path.lstat()
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        raise BridgeError("UNSAFE_POLICY", "Policy must be owned by you and not writable by other users.")
    obj = tomllib.loads(raw.decode("utf-8"))
    if set(obj) - allowed_keys or obj.get("version") != 1:
        raise ValueError()
    return obj


def _globs(value: object, *, required: bool) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if (not isinstance(value, list) or (required and not value) or len(value) > 128 or
            any(not isinstance(s, str) or not s or len(s) > 256 or s.startswith("/") or ".." in s.split("/") for s in value)):
        raise ValueError()
    return tuple(value)


def _redactions(obj: dict) -> list[tuple[str, str]]:
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
    return pairs


def _blocks(obj: dict) -> list[str]:
    blocks = obj.get("block_literals", [])
    if not isinstance(blocks, list) or len(blocks) > 128 or any(not isinstance(s, str) or not s or len(s) > 1024 for s in blocks):
        raise ValueError()
    return blocks


def _bounded_int(value: object, default: int, ceiling: int) -> int:
    if value is None:
        return default
    if type(value) is not int or not 1 <= value <= ceiling:
        raise ValueError()
    return value


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
    denied_globs: tuple[str, ...] = ()
    max_files: int = DEFAULT_MAX_FILES
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES

    @classmethod
    def load(cls, path: Path) -> "Policy":
        path = path.expanduser().absolute()
        try:
            obj = _trusted_toml(path, {"version", "project_root", "allowed_globs", "denied_globs", "auto_publish",
                                       "redact_emails", "redact_private_ips", "redactions", "block_literals",
                                       "ttl_hours", "max_files", "max_bundle_bytes"})
            root_value = obj["project_root"]
            if not isinstance(root_value, str) or not Path(root_value).expanduser().is_absolute():
                raise ValueError()
            root = Path(root_value).expanduser().resolve(strict=True)
            if not root.is_dir() or path.resolve().is_relative_to(root):
                raise BridgeError("UNTRUSTED_POLICY", "Keep the policy outside the project root.")
            globs = _globs(obj["allowed_globs"], required=True)
            denied = _globs(obj.get("denied_globs"), required=False)
            opts = {k: obj.get(k, default) for k, default in
                    (("auto_publish", False), ("redact_emails", True), ("redact_private_ips", True))}
            if any(type(v) is not bool for v in opts.values()):
                raise ValueError()
            ttl = obj.get("ttl_hours", 24)
            if type(ttl) is not int or not 1 <= ttl <= 168:
                raise ValueError()
            pairs, blocks = _redactions(obj), _blocks(obj)
            extra = sensitive_path()
            if extra.is_file() or extra.is_symlink():
                shared = _trusted_toml(extra, {"version", "block_literals", "redactions"})
                pairs, blocks = pairs + _redactions(shared), blocks + _blocks(shared)
            return cls(root, globs, **opts, replacements=tuple(pairs), block_literals=tuple(blocks), ttl_hours=ttl,
                       denied_globs=denied,
                       max_files=_bounded_int(obj.get("max_files"), DEFAULT_MAX_FILES, MAX_FILES),
                       max_bundle_bytes=_bounded_int(obj.get("max_bundle_bytes"), DEFAULT_MAX_BUNDLE_BYTES, MAX_BUNDLE_BYTES))
        except (KeyError, ValueError, TypeError, OSError, UnicodeError) as exc:
            raise BridgeError("INVALID_POLICY", "Invalid policy; check the documented TOML schema.") from exc

    def check_path(self, name: str) -> None:
        parts = relative_parts(name)
        lower = [p.lower() for p in parts]
        if (any(p in DENIED_PARTS for p in lower) or lower[-1] in DENIED_NAMES or
                lower[-1].startswith(".env") or Path(lower[-1]).suffix in DENIED_SUFFIXES):
            raise BridgeError("EXCLUDED_FILE", "A selected file is excluded by the built-in policy.")
        if any(fnmatch.fnmatchcase(name, g) for g in self.denied_globs):
            raise BridgeError("EXCLUDED_FILE", "A selected file is excluded by the policy deny list.")
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

    def check(self, text: str) -> str:
        """Gate text that is public or headed to a public repository, without rewriting it.

        Aliasing such text would show the reviewer different bytes from the ones that
        get pushed, while credentials and block_literals would still leak on push.
        """
        assert_no_secrets(text)
        if any(s in text for s in self.policy.block_literals):
            raise BridgeError("SENSITIVE_LITERAL", "Publication blocked by a configured sensitive literal.")
        return valid_text(text.encode("utf-8"))

    def clean(self, text: str) -> str:
        self.check(text)  # A configured rewrite cannot hide a credential hit.
        for old, new in self.policy.replacements:
            text = text.replace(old, new)
        if self.policy.redact_emails:
            text = EMAIL.sub(lambda m: self._alias(m.group(), "EMAIL"), text)
        if self.policy.redact_private_ips:
            text = PRIVATE_IP.sub(lambda m: self._alias(m.group(), "PRIVATE_IP"), text)
        assert_no_secrets(text)
        return valid_text(text.encode("utf-8"))


def select_files(policy: Policy, globs: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Every policy-allowed text file under the root, optionally narrowed by globs.

    Returns (sorted relative paths, skipped entries). Files outside the policy are
    omitted silently; allowed files that cannot be published are reported.
    """
    narrow = _globs(list(globs or []), required=False)
    root = policy.project_root
    sanitizer = Sanitizer(policy)  # Throwaway: only asks "would this file publish?"; aliases are not kept.
    names, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in DENIED_PARTS and d.lower() not in AUTO_SKIP_PARTS
                             and not d.lower().endswith(".egg-info") and not (here / d).is_symlink())
        prefix = here.relative_to(root).as_posix()
        for filename in sorted(filenames):
            name = filename if prefix == "." else f"{prefix}/{filename}"
            if filename.lower() in AUTO_SKIP_NAMES or (here / filename).is_symlink():
                continue
            if narrow and not any(fnmatch.fnmatchcase(name, g) for g in narrow):
                continue
            try:
                policy.check_path(name)
            except BridgeError:
                continue
            try:
                raw, _ = read_source(root, name, MAX_FILE_BYTES)
                sanitizer.clean(valid_text(raw))
            except BridgeError as exc:
                reason = {"FILE_TOO_LARGE": "too_large", "NON_TEXT": "not_text", "LINE_TOO_LONG": "not_text",
                          "SECRET_DETECTED": "secret_detected", "SENSITIVE_LITERAL": "sensitive_literal"}
                skipped.append({"path": name, "reason": reason.get(exc.code, "unreadable")})
                continue
            names.append(name)
    return sorted(names), skipped
