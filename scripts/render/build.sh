#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

# Both guards run before installing dependencies or building any artifact.
python scripts/operations/release_guard.py --stage build
python scripts/operations/ci_preflight.py --scope all
node -e 'if (Number(process.versions.node.split(".")[0]) !== 24) { console.error("Node 24 is required"); process.exit(2); }'
python -m pip install --require-hashes -r backend/requirements.txt
(
  cd frontend
  npm ci --include=dev
  npm run typecheck
  npm test -- --run
  npm run build
)
python scripts/operations/release_guard.py --stage record
# Deliberately NO database migrations, seeds, service creation or deployment.
