#!/usr/bin/env bash
# Refresh listings locally and (optionally) serve the site.
#   ./refresh.sh          -> fetch only
#   ./refresh.sh --serve  -> fetch, then serve http://localhost:8765 and open it
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -c "import requests" 2>/dev/null || $PY -m pip install --quiet requests
$PY fetch_jobs.py --workers 12
if [[ "${1:-}" == "--serve" ]]; then
  echo "Serving docs/ at http://localhost:8765  (Ctrl-C to stop)"
  (sleep 1; open "http://localhost:8765" 2>/dev/null || true) &
  $PY -m http.server 8765 --directory docs
fi
