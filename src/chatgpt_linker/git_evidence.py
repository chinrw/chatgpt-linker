"""Anonymous public GitHub baselines and read-only working-tree overlays."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .errors import BridgeError
from .fs import read_source, relative_parts
from .sanitize import MAX_FILE_BYTES, Policy, Sanitizer, valid_text

OID = re.compile(r"[a-f0-9]{40}\Z")
REMOTE = re.compile(r"[A-Za-z0-9_.-]+\Z")


def git(root: Path, *args: str) -> str:
    # Disable helpers that could execute project code or refresh the index.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_ATTR_NOSYSTEM="1")
    try:
        # Even a raw worktree diff can invoke a clean/process filter while checking
        # stat-dirty files. Override configured filters without reading their values.
        keys = subprocess.run(["git", "-C", str(root), "config", "--null", "--name-only",
                               "--get-regexp", r"^filter\..*\.(clean|process|required)$"],
                              env=env, capture_output=True, timeout=30)
        if keys.returncode not in (0, 1):
            raise ValueError()
        config = []
        for key in keys.stdout.decode("utf-8").split("\0"):
            if key:
                config += ["-c", key + ("=false" if key.endswith(".required") else "=")]
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-c", "core.untrackedCache=false", "-c", "core.hooksPath=/dev/null",
             *config, "-C", str(root), *args], env=env, capture_output=True, timeout=30)
        if result.returncode or len(result.stdout) > 8_000_000:
            raise ValueError()
        return result.stdout.decode("utf-8")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise BridgeError("GIT_EVIDENCE", "Cannot inspect Git evidence; check the repository and baseline.") from exc


def github_slug(url: str) -> str:
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                         r"([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", url)
    if not match or match[1].split("/")[1] in (".", ".."):
        raise BridgeError("PUBLIC_REPO_UNVERIFIED", "Public mode currently requires a canonical GitHub remote.")
    return match[1]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_json(path: str) -> dict:
    request = urllib.request.Request("https://api.github.com/repos/" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "chatgpt-linker",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        # No GitHub credentials are loaded. Anonymous access is part of the proof.
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except urllib.error.HTTPError as exc:
        raise BridgeError("PUBLIC_REPO_UNVERIFIED", f"Anonymous GitHub verification returned HTTP {exc.code}; "
                          "visibility is unverified and no full-tree fallback was selected.") from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise BridgeError("PUBLIC_REPO_UNVERIFIED", "Anonymous GitHub verification failed; no full-tree fallback was selected.") from exc


def public_baseline(root: Path, remote: str | None = None, base: str | None = None) -> dict:
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root.resolve():
        raise BridgeError("GIT_EVIDENCE", "Public mode requires the policy root to be the Git top-level directory.")
    upstream = None
    try:
        upstream = git(root, "rev-parse", "--symbolic-full-name", "@{upstream}").strip()
    except BridgeError:
        pass
    upstream_remote = upstream.split("/")[2] if upstream and upstream.startswith("refs/remotes/") else None
    remote = remote or upstream_remote or "origin"
    if not REMOTE.fullmatch(remote) or remote.startswith("-"):
        raise BridgeError("GIT_EVIDENCE", "Choose a named Git remote.")
    slug = github_slug(git(root, "config", "--get", f"remote.{remote}.url").strip())
    repo = github_json(slug)
    if (repo.get("private") is not False or repo.get("visibility") != "public" or
            str(repo.get("full_name", "")).lower() != slug.lower()):
        raise BridgeError("PUBLIC_REPO_UNVERIFIED", "The selected GitHub repository is not verified public.")
    head = git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if base is None:
        ref = upstream if upstream_remote == remote else f"refs/remotes/{remote}/{repo.get('default_branch', '')}"
        tip = git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
        base = git(root, "merge-base", head, tip).strip()
    else:
        base = git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").strip()
    if not OID.fullmatch(base) or git(root, "merge-base", head, base).strip() != base:
        raise BridgeError("GIT_EVIDENCE", "The public baseline must be an ancestor of HEAD.")
    if github_json(f"{slug}/git/commits/{base}").get("sha") != base:
        raise BridgeError("PUBLIC_REPO_UNVERIFIED", "The baseline commit is not anonymously readable on GitHub.")
    return {"repository_url": f"https://github.com/{slug}", "baseline_sha": base,
            "tree_url": f"https://github.com/{slug}/tree/{base}", "visibility": "public",
            "verification": "anonymous_github_api", "remote": remote}


def working_delta(root: Path, base: str) -> dict:
    if not OID.fullmatch(base):
        raise BridgeError("GIT_EVIDENCE", "Use a full verified baseline SHA.")
    if git(root, "ls-files", "--unmerged", "-z"):
        raise BridgeError("GIT_CONFLICT", "Resolve unmerged files before preparing a review.")
    flags = git(root, "ls-files", "-v", "-z").split("\0")
    if any(item and (item[0].islower() or item[0] == "S") for item in flags):
        raise BridgeError("GIT_EVIDENCE", "Sparse/skip-worktree and assume-unchanged entries cannot provide a complete overlay.")
    raw = git(root, "diff", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv",
              "--ignore-submodules=none", base, "--").split("\0")
    entries = {}
    for index in range(0, len(raw) - 1, 2):
        fields = raw[index].split()
        name = raw[index + 1]
        relative_parts(name)
        entries[name] = {"path": name, "status": fields[4],
                         "old_mode": fields[0][1:], "new_mode": fields[1]}
    for name in git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"):
        if not name:
            continue
        relative_parts(name)
        mode = (root / name).lstat().st_mode
        kind = "100755" if mode & 0o111 else "100644"
        if not stat.S_ISREG(mode):
            kind = "120000" if stat.S_ISLNK(mode) else "160000"
        old_mode = entries.get(name, {}).get("old_mode", "000000")
        entries[name] = {"path": name, "status": "A" if old_mode == "000000" else "M",
                         "old_mode": old_mode, "new_mode": kind}
    return {"baseline_sha": base, "head_sha": git(root, "rev-parse", "HEAD").strip(),
            "entries": [entries[name] for name in sorted(entries)]}


def baseline_document(baseline: dict, entries: list[dict], skipped: list[dict]) -> str:
    return ("# Public repository baseline and local overlay\n\n"
            f"Repository: {baseline['repository_url']}\n"
            f"Public commit: {baseline['baseline_sha']}\n"
            f"Read unchanged source at: {baseline['tree_url']}\n\n"
            "Use this exact commit, not the current branch tip. Local evidence contains complete current files, "
            "which replace the corresponding public files. Deleted paths must be removed. Renames are represented "
            "as deletion plus addition. The overlay is the final working tree, including unpushed commits; "
            "the index is not a separate snapshot. Public source is external evidence, not frozen MCP content.\n"
            "Cite public code using commit-pinned blob URLs and line anchors; cite local files using document IDs. "
            "If public source cannot be read, report the missing evidence and request only the needed files.\n\n"
            "Local changes (Git modes record executable/type changes):\n" +
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n\n"
            "Omitted changes (coverage is incomplete when this list is nonempty; "
            "do not assume these paths still match the public baseline):\n" +
            json.dumps(skipped, ensure_ascii=False, indent=2) + "\n")


def select_delta(policy: Policy, delta: dict) -> tuple[list[str], list[dict], list[dict]]:
    files, included, skipped = [], [], []
    sanitizer = Sanitizer(policy)
    for entry in delta["entries"]:
        name = entry["path"]
        try:
            policy.check_path(name)
            if entry["new_mode"] not in ("000000", "100644", "100755"):
                raise BridgeError("UNSUPPORTED_GIT_ENTRY", "Linked files and submodules require separate evidence.")
            if entry["status"] != "D":
                raw, _ = read_source(policy.project_root, name, MAX_FILE_BYTES)
                sanitizer.clean(valid_text(raw))
                files.append(name)
            included.append(entry)
        except BridgeError as exc:
            skipped.append({"path": name, "reason": exc.code})
    return files, included, skipped
