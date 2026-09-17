#!/usr/bin/env bash
# Copy OUTSIDE the source project; edit fixed absolute paths; chmod 700.
# Point tunnel-client's --mcp-command at that copied launcher.
set -euo pipefail
PYTHON_BIN=/absolute/path/to/plan-review-bridge/.venv/bin/python
EXCHANGE=/absolute/path/to/private-state/exchange
SAFE_HOME=/absolute/path/to/empty-private-home
[[ -x "$PYTHON_BIN" && -d "$EXCHANGE" && -d "$SAFE_HOME" ]] || {
  echo 'Configure this launcher with real absolute paths before use.' >&2; exit 2;
}
# The tunnel process retains its runtime key. The evidence child inherits none of it.
exec env -i PATH=/usr/bin:/bin HOME="$SAFE_HOME" PYTHONUTF8=1 \
  "$PYTHON_BIN" -m plan_review_bridge serve --exchange "$EXCHANGE"
