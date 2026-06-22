# Embedder HTTP Basic Auth — Design

Date: 2026-06-22
Status: Approved (pending spec review)

## Problem

Users running a self-hosted, OpenAI-compatible embedding server (`openai`
backend + `OPENAI_BASE_URL`) may sit behind an HTTP layer that enforces **HTTP
Basic Auth** (a reverse proxy / API gateway). Today `OpenAIEmbedder` only sends
the SDK's default `Authorization: Bearer <OPENAI_API_KEY>` header, so requests to
such a server are rejected with 401.

We need a way to attach Basic Auth credentials to the embedder's outbound
requests.

## Key constraint

An HTTP request can carry only **one** `Authorization` header. The OpenAI SDK
already uses `Authorization: Bearer <api_key>`. Therefore Bearer and Basic cannot
both live on the standard `Authorization` header at the same endpoint.

Realistic deployments fall into:

1. **Reverse-proxy Basic Auth only** — the proxy checks Basic Auth; the backend
   does not check Bearer. Basic Auth goes on `Authorization` (overriding Bearer).
2. **Gateway reads a non-standard header** — Basic credentials live on a custom
   header (e.g. `X-Proxy-Authorization`); Bearer stays on `Authorization`. Both
   coexist.
3. **Forward proxy** — Basic Auth belongs on the HTTP proxy connection
   (`Proxy-Authorization` / httpx `proxy=`), not on the API request. **Out of
   scope (YAGNI)** until a concrete need appears.

This design covers cases 1 and 2 with one mechanism: a Basic Auth header whose
**name is configurable**.

## Approach

Inject a Basic Auth header into the OpenAI client via the SDK's
`default_headers`. Verified SDK behavior: user-supplied `default_headers` are
merged *after* the SDK's own auth headers, so a value set there overrides the
default `Authorization: Bearer`. Setting a different header name leaves Bearer
intact.

### Configuration (`config.py`)

Two new settings, both **credentials → NOT runtime-editable** (not added to
`EDITABLE_FIELDS`):

| Setting (env)                       | Field                       | Default          | Meaning |
|-------------------------------------|-----------------------------|------------------|---------|
| `ODM_EMBEDDER_BASIC_AUTH`           | `embedder_basic_auth`       | `""` (disabled)  | `"user:password"`. Empty = feature off. |
| `ODM_EMBEDDER_BASIC_AUTH_HEADER`    | `embedder_basic_auth_header`| `"Authorization"`| Header name the Basic credential is written to. |

- `embedder_basic_auth` empty → no behavior change (fully backward compatible).
- Default header `Authorization` → case 1 (overrides Bearer).
- Set header to `X-Proxy-Authorization` etc. → case 2 (coexists with Bearer).

The existing `OPENAI_API_KEY` requirement is **kept as-is** — the user confirmed
a Bearer key is still present in their setup. No relaxation of that check.

Documented in `.env.example` alongside the other embedder vars.

### Embedder (`embedding/cloud.py`)

Add two small, independently testable pieces:

1. `_basic_auth_value(spec: str) -> str` — pure helper. Splits `spec` on the
   first `:` into user/password, base64-encodes `user:password`, returns
   `"Basic <b64>"`. **Fail Loud**: raise `ValueError` if `spec` has no `:`
   (malformed credential), rather than silently sending a broken header.

2. `OpenAIEmbedder.__init__` gains optional params
   `basic_auth: str | None = None`, `basic_auth_header: str = "Authorization"`.
   When `client is None` and `basic_auth` is set, build
   `default_headers = {basic_auth_header: _basic_auth_value(basic_auth)}` and
   pass it to `OpenAI(default_headers=default_headers)`. When `basic_auth` is
   empty/None, construct `OpenAI()` exactly as today.

The injected-`client` path (used by tests and any custom wiring) is unchanged —
header injection only happens on the real-client construction path.

### Factory (`embedding/__init__.py`)

`get_embedder()` passes the new settings through for the `openai` backend:

```python
return OpenAIEmbedder(
    settings.embedder_model,
    basic_auth=settings.embedder_basic_auth or None,
    basic_auth_header=settings.embedder_basic_auth_header,
)
```

`local` and `voyage` backends are untouched.

## Data flow

```
Settings (env/.env)
  → get_embedder()  (openai branch)
    → OpenAIEmbedder(model, basic_auth, basic_auth_header)
      → _basic_auth_value("user:pass") → "Basic dXNlcjpwYXNz"
      → OpenAI(default_headers={header_name: "Basic ..."})
        → every embeddings.create() request carries the Basic Auth header
```

## Error handling (Fail Loud)

- Malformed `embedder_basic_auth` (no `:`) → `ValueError` at embedder
  construction with a clear message. No silent fallback.
- `OPENAI_API_KEY` still required for the `openai` backend (unchanged).
- Empty `embedder_basic_auth` → feature disabled, zero behavior change.

## Testing (business-logic, offline)

Add to `tests/test_openai_embedder.py` (no network; the SDK is not invoked for
the helper, and the construction test stubs/patches `OpenAI`):

1. `_basic_auth_value("user:pass")` returns the correct
   `"Basic " + base64("user:pass")`.
2. `_basic_auth_value` raises `ValueError` on a spec with no `:`.
3. `_basic_auth_value` handles a password containing `:` (split on first colon
   only).
4. Constructing `OpenAIEmbedder(..., basic_auth=..., basic_auth_header=...)`
   with `client=None` passes the expected `default_headers` to `OpenAI` (patch
   `openai.OpenAI` to capture kwargs; set a dummy `OPENAI_API_KEY`).
5. Default header name is `Authorization` when not overridden.
6. No `basic_auth` → `OpenAI` constructed without a `default_headers` Basic
   entry (backward compatibility).

## Scope / YAGNI

- No forward-proxy / `proxy=` support (case 3).
- No relaxation of the `OPENAI_API_KEY` requirement.
- No Basic Auth for `local` (no network) or `voyage` (its own SDK) backends.
- Not exposed in the web UI (credential).

## Files touched

- `src/opendomainmcp/config.py` — two new settings.
- `src/opendomainmcp/embedding/cloud.py` — helper + constructor params.
- `src/opendomainmcp/embedding/__init__.py` — pass settings through.
- `.env.example` — document the two vars.
- `tests/test_openai_embedder.py` — new tests.
