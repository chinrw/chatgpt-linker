# Changelog

## Unreleased

Renamed the project from Plan Review Bridge to ChatGPT Linker. User-visible changes:

- CLI command `plan-review` -> `chatgpt-linker`; Python package `plan_review_bridge` -> `chatgpt_linker`.
- State override env var `PLAN_REVIEW_STATE` -> `CHATGPT_LINKER_STATE`; default state
  directory `~/.local/state/plan-review` -> `~/.local/state/chatgpt-linker`. Existing
  state directories are not migrated: pass `--state` or move the directory.
- MCP `serverInfo.name` is now `chatgpt-linker` / `chatgpt-linker-control`.
- The agent skill keeps its name `rethink-plan`.

Waiting covers a full Pro reasoning pass:

- The skill's default polling budget is 90 minutes (was 20); the invocation can
  name a different one. CLI `wait --timeout` defaults to 5400 seconds (was 1200).
- The skill no longer assumes Codex: waiting is sliced under the host's tool
  timeout, and docs list install paths for Claude Code, pi, and opencode.

Selection is more automatic:

- `prepare --auto` freezes every policy-allowed text file; `--glob` narrows it.
  Binary, oversized, lock, cache, and scanner-rejected files are skipped and reported;
  explicit `--file` failures now name the file.
- Policy gains `denied_globs`, `max_files` (default 512, ceiling 2048) and
  `max_bundle_bytes` (default 8 MB, ceiling 32 MB); `policy-init --deny` writes the deny list.
- `~/.config/chatgpt-linker/sensitive.toml` (or `CHATGPT_LINKER_SENSITIVE`) is merged
  into every policy: global redactions and block literals, never wider scope.
- The `rethink-plan` skill proposes the policy on first use in a project and
  writes it only after an explicit confirmation in the conversation.

Waiting is more automatic:

- `review_wait` accepts `timeout_seconds` up to 300 (was 25) and still returns as soon as
  the result exists. Set the host MCP `tool_timeout_sec` above the value you pass.
- The `rethink-plan` skill now polls for 20 minutes by default after the hand-off
  instead of yielding after one short check.

## 0.1.0 — 2026-09-17

Initial implementation: selected-file preparation and offline scanning; immutable
publication grants; read-only evidence search/fetch; single-assignment Markdown
submission with atomic receipts; cancellation and TTL; local status/wait/result;
manual import fallback; limited stdio and local Streamable HTTP MCP; explicit
agent skill; Chinese setup/security/compliance guides; regression tests and CI.

No model API backend, no UI automation, no automatic ChatGPT initiation, no public
OAuth or multi-user service, no automatic code execution.
