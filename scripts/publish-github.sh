#!/usr/bin/env bash
# Create a NEW PRIVATE repository from a source-only snapshot. Never force-push.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-chinrw/chatgpt-linker}"
if [[ $# -gt 1 || ! "$TARGET" =~ ^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo 'Usage: bash scripts/publish-github.sh [owner/new-repository-name]' >&2; exit 2
fi
for executable in gh git "${PYTHON:-python3}"; do
  command -v "$executable" >/dev/null || { echo "Required command missing: $executable" >&2; exit 2; }
done
export GH_HOST=github.com GH_PROMPT_DISABLED=1
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  echo 'Authenticate locally first: gh auth login --hostname github.com' >&2; exit 2
fi
LOGIN="$(gh api user --jq .login)"
if [[ "${TARGET%%/*}" != "$LOGIN" ]]; then
  echo 'Target owner must match the currently authenticated GitHub user. No organization writes are attempted.' >&2
  exit 2
fi
ACCOUNT_ID="$(gh api user --jq .id)"
[[ "$ACCOUNT_ID" =~ ^[0-9]+$ ]] || { echo 'Invalid authenticated account metadata.' >&2; exit 2; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/chatgpt-linker-publish.XXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT
if gh api "repos/$TARGET" >"$TMP/repo.json" 2>"$TMP/lookup.err"; then
  echo 'Refusing: target repository already exists. Nothing was pushed or overwritten.' >&2; exit 2
fi
if ! grep -Eq '(HTTP 404|\(404\))' "$TMP/lookup.err"; then
  echo 'Repository lookup failed for a reason other than 404; refusing to create blindly.' >&2; exit 2
fi
mkdir -m 700 "$TMP/source"
"${PYTHON:-python3}" "$ROOT/scripts/snapshot_source.py" "$ROOT" "$TMP/source"
# Validate the exact snapshot before creating any remote repository.
(cd "$TMP/source" && PYTHONPATH=src "${PYTHON:-python3}" -m unittest discover -s tests -q)
git -C "$TMP/source" init --initial-branch=main --quiet
git -C "$TMP/source" add -- .
git -C "$TMP/source" -c core.hooksPath=/dev/null -c user.name="$LOGIN" \
  -c user.email="$ACCOUNT_ID+$LOGIN@users.noreply.github.com" \
  -c commit.gpgsign=false commit --quiet -m 'Initial implementation: ChatGPT subscription plan review bridge'
if ! gh repo create "$TARGET" --private --description \
  'User-initiated ChatGPT plan review: sanitized read-only evidence MCP, constrained Markdown outbox, and agent skill.' \
  --source "$TMP/source" --remote origin --push; then
  echo 'Creation/push failed. Inspect GitHub: a repository may have been created before a push failure. This script never deletes or force-pushes.' >&2
  exit 2
fi
gh repo view "$TARGET" --json url,isPrivate --jq '{url: .url, private: .isPrivate}'
echo 'Published. Clone the new repository for future development; the original source directory was not changed.'
