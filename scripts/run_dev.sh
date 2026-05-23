#!/usr/bin/env bash
set -euo pipefail

APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
APP_RELOAD="${APP_RELOAD:-1}"

args=(backend.app.main:app --host "$APP_HOST" --port "$APP_PORT")

if [[ "$APP_RELOAD" == "1" ]]; then
  args+=(--reload)
fi

exec uvicorn "${args[@]}"
