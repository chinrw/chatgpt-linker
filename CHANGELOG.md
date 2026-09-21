# Changelog

## Unreleased

Renamed the project from Plan Review Bridge to ChatGPT Linker. User-visible changes:

- CLI command `plan-review` -> `chatgpt-linker`; Python package `plan_review_bridge` -> `chatgpt_linker`.
- State override env var `PLAN_REVIEW_STATE` -> `CHATGPT_LINKER_STATE`; default state
  directory `~/.local/state/plan-review` -> `~/.local/state/chatgpt-linker`. Existing
  state directories are not migrated: pass `--state` or move the directory.
- MCP `serverInfo.name` is now `chatgpt-linker` / `chatgpt-linker-control`.
- The agent skill is renamed from `rethink-plan` to `ultraplan`; its default
  installation directory is now `~/.agents/skills/ultraplan`. Existing skill
  installations are not migrated automatically.

Packaging:

- `flake.nix`: `packages.default`, `checks` (unit tests), `devShells.default`.
- `homeManagerModules.default` installs the CLI and ultraplan through
  `programs.chatgpt-linker.enable`. The module owns the shared agent and Claude
  skill paths; consumers select `skillTargets` instead of copying source paths.
  Source snapshots include the flake and its Home Manager module.
- `programs.chatgpt-linker.skillDirectories.agents` and `.claude` override
  installation parent directories independently; the module appends `/ultraplan`.

Waiting uses a bounded review budget:

- The skill's default polling budget is 90 minutes (was 20); the invocation can
  name a different one. CLI `wait --timeout` defaults to 5400 seconds (was 1200).
- The skill no longer assumes Codex: waiting is sliced under the host's tool
  timeout, and docs list install paths for Claude Code, pi, and opencode.
- `review_wait` accepts `timeout_seconds` up to 300 (was 25) and returns as soon
  as the result exists. Set the host MCP `tool_timeout_sec` above each call's timeout.

Selection is more automatic:

- `prepare --auto` freezes every policy-allowed text file; `--glob` narrows it.
  Binary, oversized, lock, cache, and scanner-rejected files are skipped and reported;
  explicit `--file` failures now name the file.
- Policy gains `denied_globs`, `max_files` (default 512, ceiling 2048) and
  `max_bundle_bytes` (default 8 MB, ceiling 32 MB); `policy-init --deny` writes the deny list.
- `~/.config/chatgpt-linker/sensitive.toml` (or `CHATGPT_LINKER_SENSITIVE`) is merged
  into every policy: global redactions and block literals, never wider scope.
- `repo-info` verifies an anonymous public GitHub baseline. `prepare --public-repo`
  sends the context/plan, commit-pinned source reference, and current local changes
  instead of duplicating unchanged public code. Deletions, modes, and omitted
  evidence are recorded; source checks also detect changes to HEAD and the overlay.
- An explicit `ultraplan` invocation authorizes that review's preparation and
  publication without a second confirmation. Initial policies use the task's
  scope; standing approval and expansions of existing policies remain separate.
- After validating a completed review, ultraplan resumes implementation and
  tests when the original task already authorized them. Review-only requests
  still end with the plan; unverified model provenance is not a stop condition.
- Ultraplan carries effective user-scope and project rules in the draft context,
  including README/docs, comment, and commit-message requirements. Existing
  plans remain separate evidence files; global rule files are not uploaded whole.

## 0.1.0 — 2026-09-17

Initial implementation: selected-file preparation and offline scanning; immutable
publication grants; read-only evidence search/fetch; single-assignment Markdown
submission with atomic receipts; cancellation and TTL; local status/wait/result;
manual import fallback; limited stdio and local Streamable HTTP MCP; explicit
agent skill; Chinese setup/security/compliance guides; regression tests and CI.

No model API backend, no UI automation, no automatic ChatGPT initiation, no public
OAuth or multi-user service, no automatic code execution.
