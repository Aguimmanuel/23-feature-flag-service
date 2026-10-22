#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"
python scripts/operations/release_guard.py --stage start
PORT=${PORT:-10000}
if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PORT < 1 || 10#$PORT > 65535 )); then
  printf '%s\n' 'BLOCKED: invalid provider port' >&2
  exit 2
fi
cd backend
# The application mounts health/audit/static adapters and owns safe request logs.
# This script never invents an app, runs migrations/seeds, or enables mocks.
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1 --no-access-log
