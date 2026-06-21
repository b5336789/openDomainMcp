---
name: run-open-domain-mcp
description: Build, launch, and drive the open-domain-mcp web app (FastAPI + React SPA). Use when asked to run, start, serve, smoke-test, or screenshot the dashboard / web UI, or to verify a change to the Dashboard, its APIs, or the SPA actually works in the running app.
---

# Run open-domain-mcp (web app)

A FastAPI backend (`opendomainmcp-web`) that serves JSON APIs **and** the built
React SPA from `src/opendomainmcp/api/static/`. The Dashboard ("首頁") is a pure
projection of `/api/stats`, `/api/sources`, and `/api/settings`, so the agent
handle on the app is **`smoke.sh`** — it ensures the server is up and asserts
those endpoints return real data plus the SPA shell is served.

There is no `chromium-cli` in this environment; for a **visual** check, drive the
running server with the Playwright MCP browser tools and screenshot it (see
"Visual check" below).

All paths below are relative to the repo root (the unit). The driver lives at
`.claude/skills/run-open-domain-mcp/smoke.sh`.

## Prerequisites

Already satisfied in this container (verified: venv Python 3.11, `web/node_modules`
present, static bundle built). On a clean machine the project's launcher
prescribes:

```bash
uv venv --python 3.11 .venv && uv pip install --python .venv -e ".[dev]"   # backend
( cd web && npm install )                                                  # frontend deps
cp .env.example .env   # then fill credentials; sets ODM_WEB_HOST/PORT (8088 here)
```

`./run.sh` sources `.env`, so credentials (OPENAI/ANTHROPIC/etc.) and the bind
port come from there.

## Build (only needed after editing the frontend under `web/src`)

The SPA is served from `src/opendomainmcp/api/static/`; rebuild it there:

```bash
( cd web && npm run build )
```

Output (verified): `src/opendomainmcp/api/static/{index.html,assets/*.js,*.css}`.

## Run + drive (agent path) — primary

```bash
.claude/skills/run-open-domain-mcp/smoke.sh
```

It reuses a server already listening on the configured port, otherwise launches
`./run.sh web`, waits for readiness, asserts the Dashboard-backing endpoints, and
stops the server it started. Expected tail:

```
[smoke] stats OK: 42 chunks in 'domain_knowledge' (embedder=openai:..., extract=True)
[smoke] settings OK: search_mode=hybrid rerank=False
[smoke] PASS
```

(The numbers reflect whatever is ingested into the active collection — the point
is the fields are present and real, not fixed.)

## Run (human path)

```bash
./run.sh web        # serves http://127.0.0.1:8088  (port from .env, NOT 8000)
```

Ctrl-C to stop. Open the URL in a browser for the dashboard. Headless, this only
proves the entrypoint resolves — use `smoke.sh` or the visual check to actually
verify behavior.

## Visual check (screenshot the Dashboard)

No `chromium-cli` here. With a server running (`./run.sh web`), drive it with the
Playwright MCP browser tools: `browser_navigate` to `http://127.0.0.1:8088/`, then
`browser_take_screenshot`, then `Read` the PNG. The Pipeline card and stat cards
should show the same live values `smoke.sh` printed (chunks, collection, embedder,
extraction on/off, search mode).

## Gotchas

- **Port is 8088, not 8000.** The README says 8000, but `.env` sets
  `ODM_WEB_PORT=8088` and `run.sh` sources `.env` (which wins over any exported
  `ODM_WEB_PORT`). The entrypoint's own default is 8000 only when `.env` is absent.
- **A second `./run.sh web` fails** with `[Errno 48] address already in use` if one
  is already running — the app *starts* fine, it just can't bind. `smoke.sh`
  avoids this by probing first and reusing a live server.
- **Frontend edits don't show until rebuilt.** The server serves the prebuilt
  `static/` dir from disk; run `npm run build` after touching `web/src`. A running
  server picks up the new files on the next request (no restart needed).
- **`static/` is a build artifact.** Rebuilding changes files under
  `src/opendomainmcp/api/static/` — expected, not a source edit to commit (check
  whether it's git-ignored before staging).
- **To launch on an alternate port** (e.g. when 8088 is taken), bypass the `.env`
  override by sourcing it yourself then overriding for the entrypoint:
  `set -a; source .env; set +a; ODM_WEB_PORT=8099 .venv/bin/opendomainmcp-web`
  (verified working).

## Troubleshooting

- `error: venv not found at .venv` (from `run.sh`) → run the Prerequisites venv line.
- `address already in use` → a server is already up; just point your checks at the
  existing port (`smoke.sh` does this automatically).
- Dashboard shows skeletons / blank values → an API (`/api/stats`, `/api/sources`,
  `/api/settings`) errored; `curl` it directly to see the failure (e.g. missing
  credentials in `.env`, or graph DB unreachable).
