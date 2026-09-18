# Changelog

## Unreleased

Renamed the project from Plan Review Bridge to ChatGPT Linker. User-visible changes:

- CLI command `plan-review` -> `chatgpt-linker`; Python package `plan_review_bridge` -> `chatgpt_linker`.
- State override env var `PLAN_REVIEW_STATE` -> `CHATGPT_LINKER_STATE`; default state
  directory `~/.local/state/plan-review` -> `~/.local/state/chatgpt-linker`. Existing
  state directories are not migrated: pass `--state` or move the directory.
- MCP `serverInfo.name` is now `chatgpt-linker` / `chatgpt-linker-control`.
- The agent skill keeps its name `rethink-plan`.

## 0.1.0 — 2026-09-17

Initial implementation: selected-file preparation and offline scanning; immutable
publication grants; read-only evidence search/fetch; single-assignment Markdown
submission with atomic receipts; cancellation and TTL; local status/wait/result;
manual import fallback; limited stdio and local Streamable HTTP MCP; explicit
agent skill; Chinese setup/security/compliance guides; regression tests and CI.

No model API backend, no UI automation, no automatic ChatGPT initiation, no public
OAuth or multi-user service, no automatic code execution.
