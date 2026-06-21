#!/usr/bin/env bash
#
# Drive the open-domain-mcp web app end-to-end.
#
# This is the agent/CI handle on the running app: it makes sure the FastAPI
# server is up, then exercises the JSON APIs that back the Dashboard ("首頁")
# and confirms the SPA shell is served. The Dashboard's Pipeline card and stat
# cards are pure projections of /api/stats + /api/sources + /api/settings, so
# asserting those endpoints return real data is the meaningful smoke for any
# change to that page.
#
# Usage (from anywhere):
#   .claude/skills/run-open-domain-mcp/smoke.sh
#
# It reuses an already-running server if one is reachable, otherwise launches
# `./run.sh web` (which sources .env -> ODM_WEB_HOST/ODM_WEB_PORT) and stops it
# again on exit. The port is read from .env (8088 in this repo); override the
# probe target with ODM_WEB_PORT only if you also changed it in .env.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PORT="${ODM_WEB_PORT:-8088}"
BASE="http://127.0.0.1:${PORT}"
LOG="${TMPDIR:-/tmp}/odm-web-smoke.log"

up() { curl -fsS -o /dev/null "$BASE/api/stats" 2>/dev/null; }

started=""
if up; then
  echo "[smoke] reusing server already listening on $BASE"
else
  echo "[smoke] launching ./run.sh web (logs -> $LOG) ..."
  cd "$ROOT"
  ./run.sh web >"$LOG" 2>&1 &
  started=$!
  for _ in $(seq 1 60); do up && break; sleep 1; done
  if ! up; then
    echo "[smoke] FAIL: server never became ready; last log lines:" >&2
    tail -20 "$LOG" >&2
    [ -n "$started" ] && kill "$started" 2>/dev/null || true
    exit 1
  fi
fi

cleanup() {
  if [ -n "$started" ]; then
    echo "[smoke] stopping server pid $started"
    kill "$started" 2>/dev/null || true
  fi
  return 0
}
trap cleanup EXIT

echo "[smoke] --- GET /api/stats ---"
curl -fsS "$BASE/api/stats"

echo; echo "[smoke] --- GET /api/sources ---"
curl -fsS "$BASE/api/sources"

echo; echo "[smoke] --- GET /api/settings ---"
curl -fsS "$BASE/api/settings"

echo; echo "[smoke] --- GET / (SPA shell title) ---"
curl -fsS "$BASE/" | grep -o '<title>[^<]*</title>' || { echo "[smoke] FAIL: SPA shell not served" >&2; exit 1; }

# Assert the Dashboard-backing fields are present and coherent.
curl -fsS "$BASE/api/stats" | python3 -c '
import sys, json
d = json.load(sys.stdin)
need = {"collection", "count", "embedder", "dim", "extract_knowledge"}
missing = need - d.keys()
assert not missing, "stats missing fields: %s" % missing
print("[smoke] stats OK: %s chunks in %r (embedder=%s, extract=%s)"
      % (d["count"], d["collection"], d["embedder"], d["extract_knowledge"]))
'
curl -fsS "$BASE/api/settings" | python3 -c '
import sys, json
e = json.load(sys.stdin).get("editable", {})
assert "search_mode" in e, "settings.editable.search_mode absent"
print("[smoke] settings OK: search_mode=%s rerank=%s"
      % (e["search_mode"], e.get("rerank_enabled")))
'

echo "[smoke] PASS"
