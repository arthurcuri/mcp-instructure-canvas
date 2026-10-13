#!/usr/bin/env bash
# Read-only weekly snapshot. This script does not invoke an LLM or send messages.
set -euo pipefail
umask 077

CANVAS_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CANVAS_UV_COMMAND="${CANVAS_UV_BIN:-}"

if [[ -z "$CANVAS_UV_COMMAND" ]]; then
  CANVAS_UV_COMMAND="$(command -v uv || true)"
fi
if [[ -z "$CANVAS_UV_COMMAND" ]]; then
  for canvas_candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [[ -x "$canvas_candidate" ]]; then
      CANVAS_UV_COMMAND="$canvas_candidate"
      break
    fi
  done
fi
if [[ -z "$CANVAS_UV_COMMAND" || ! -x "$CANVAS_UV_COMMAND" ]]; then
  echo 'uv não encontrado. Defina CANVAS_UV_BIN com o caminho absoluto do executável.' >&2
  exit 1
fi

mkdir -p "$CANVAS_PROJECT_DIR/.local"
exec "$CANVAS_UV_COMMAND" run --locked --directory "$CANVAS_PROJECT_DIR" \
  canvas-weekly-check --env-file "$CANVAS_PROJECT_DIR/.env" \
  --output "$CANVAS_PROJECT_DIR/.local/weekly-report.json" "$@"
