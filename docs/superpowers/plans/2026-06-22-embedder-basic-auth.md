# Embedder HTTP Basic Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the `openai` embedder backend attach HTTP Basic Auth credentials to its requests, for self-hosted OpenAI-compatible servers behind a proxy/gateway.

**Architecture:** Two new credential settings carry a `"user:password"` and the target header name. `OpenAIEmbedder` base64-encodes the credential and injects it as a header via the OpenAI SDK's `default_headers`. Default header name `Authorization` overrides the SDK's Bearer; a custom name coexists with Bearer.

**Tech Stack:** Python ≥3.11, pydantic-settings, openai SDK (lazy import), pytest.

## Global Constraints

- Settings use the `ODM_` prefix (pydantic `BaseSettings`, `env_prefix="ODM_"`).
- New settings are **credentials** → MUST NOT be added to `EDITABLE_FIELDS` in `config.py`.
- Fail Loud: malformed credentials raise, never silently send a broken header.
- Tests are fully offline — no network, no model download, no real `openai` SDK call.
- Backward compatible: empty `embedder_basic_auth` → zero behavior change.
- Match existing code style in `cloud.py` (lazy SDK import, `RuntimeError` for missing deps/keys).

---

### Task 1: Add config settings

**Files:**
- Modify: `src/opendomainmcp/config.py:65-67` (the Embedding block)
- Modify: `.env.example:17-20` and `.env.example:101-103`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.embedder_basic_auth: str = ""` and `Settings.embedder_basic_auth_header: str = "Authorization"`.

- [ ] **Step 1: Add the two settings to the Embedding block**

In `src/opendomainmcp/config.py`, the current block at lines 65-67 is:

```python
    # Embedding
    embedder_backend: str = "local"  # local | openai | voyage
    embedder_model: str = "BAAI/bge-small-en-v1.5"
```

Replace it with:

```python
    # Embedding
    embedder_backend: str = "local"  # local | openai | voyage
    embedder_model: str = "BAAI/bge-small-en-v1.5"
    # Optional HTTP Basic Auth for a self-hosted OpenAI-compatible embedding
    # server behind a proxy/gateway. "user:password"; empty disables it.
    # Credentials -> deliberately NOT in EDITABLE_FIELDS. The header name is
    # configurable: "Authorization" (default) overrides the SDK's Bearer header;
    # a custom name (e.g. "X-Proxy-Authorization") coexists with the Bearer key.
    embedder_basic_auth: str = ""
    embedder_basic_auth_header: str = "Authorization"
```

- [ ] **Step 2: Document the vars in `.env.example`**

After line 20 (`ODM_EMBEDDER_MODEL=...`), add:

```bash
# Optional HTTP Basic Auth for a self-hosted OpenAI-compatible embedding server
# behind a proxy. "user:password"; empty disables it. Header name defaults to
# Authorization (overrides the Bearer key); set a custom header to keep both.
# ODM_EMBEDDER_BASIC_AUTH=user:password
# ODM_EMBEDDER_BASIC_AUTH_HEADER=Authorization
```

- [ ] **Step 3: Verify it loads**

Run: `.venv/bin/python -c "from opendomainmcp.config import Settings, EDITABLE_FIELDS; s=Settings(); print(repr(s.embedder_basic_auth), repr(s.embedder_basic_auth_header)); assert 'embedder_basic_auth' not in EDITABLE_FIELDS"`
Expected: prints `'' 'Authorization'` and no AssertionError.

- [ ] **Step 4: Commit**

```bash
git add src/opendomainmcp/config.py .env.example
git commit -m "feat(config): add embedder_basic_auth settings"
```

---

### Task 2: Basic Auth header helper

**Files:**
- Modify: `src/opendomainmcp/embedding/cloud.py` (add `import base64` at top; add `_basic_auth_value` near the top-level, before `OpenAIEmbedder`)
- Test: `tests/test_openai_embedder.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_basic_auth_value(spec: str) -> str` — returns `"Basic <base64(spec)>"`. Splits `spec` on the **first** `:` to validate it has a user and password; raises `ValueError` if there is no `:`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_openai_embedder.py`:

```python
from opendomainmcp.embedding.cloud import _basic_auth_value


def test_basic_auth_value_encodes_user_password():
    # base64("user:pass") == "dXNlcjpwYXNz"
    assert _basic_auth_value("user:pass") == "Basic dXNlcjpwYXNz"


def test_basic_auth_value_splits_on_first_colon_only():
    # Password may contain a colon; base64("user:pa:ss") == "dXNlcjpwYTpzcw=="
    assert _basic_auth_value("user:pa:ss") == "Basic dXNlcjpwYTpzcw=="


def test_basic_auth_value_rejects_missing_colon():
    with pytest.raises(ValueError):
        _basic_auth_value("nocolon")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_openai_embedder.py -k basic_auth_value -v`
Expected: FAIL with ImportError / `cannot import name '_basic_auth_value'`.

- [ ] **Step 3: Implement the helper**

At the top of `src/opendomainmcp/embedding/cloud.py`, add `import base64` next to `import os`. Then add, above `class OpenAIEmbedder`:

```python
def _basic_auth_value(spec: str) -> str:
    """Build an HTTP Basic Auth header value from a "user:password" spec.

    Fails loud on a malformed spec rather than sending a broken header.
    """
    if ":" not in spec:
        raise ValueError(
            "embedder_basic_auth must be 'user:password' (missing ':')"
        )
    encoded = base64.b64encode(spec.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_openai_embedder.py -k basic_auth_value -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opendomainmcp/embedding/cloud.py tests/test_openai_embedder.py
git commit -m "feat(embedder): add _basic_auth_value helper"
```

---

### Task 3: Inject the header in OpenAIEmbedder

**Files:**
- Modify: `src/opendomainmcp/embedding/cloud.py:25-43` (`OpenAIEmbedder.__init__`)
- Test: `tests/test_openai_embedder.py`

**Interfaces:**
- Consumes: `_basic_auth_value` (Task 2).
- Produces: `OpenAIEmbedder.__init__(self, model_name="text-embedding-3-small", client=None, basic_auth: str | None = None, basic_auth_header: str = "Authorization")`. When `client is None` and `basic_auth` is truthy, the real `OpenAI(...)` is constructed with `default_headers={basic_auth_header: _basic_auth_value(basic_auth)}`.

- [ ] **Step 1: Write the failing tests**

The real-client path imports `OpenAI` lazily via `from openai import OpenAI` *inside* `__init__`, so tests patch it through the `openai` module. Add to `tests/test_openai_embedder.py`:

```python
import sys
import types


def _install_fake_openai(monkeypatch):
    """Install a fake `openai` module whose OpenAI() records its kwargs."""
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.embeddings = None

    fake = types.ModuleType("openai")
    fake.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake)
    return captured


def test_openai_embedder_injects_basic_auth_default_header(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    captured = _install_fake_openai(monkeypatch)

    OpenAIEmbedder("text-embedding-3-small", basic_auth="user:pass")

    assert captured["default_headers"] == {"Authorization": "Basic dXNlcjpwYXNz"}


def test_openai_embedder_injects_basic_auth_custom_header(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    captured = _install_fake_openai(monkeypatch)

    OpenAIEmbedder(
        "text-embedding-3-small",
        basic_auth="user:pass",
        basic_auth_header="X-Proxy-Authorization",
    )

    assert captured["default_headers"] == {
        "X-Proxy-Authorization": "Basic dXNlcjpwYXNz"
    }


def test_openai_embedder_no_basic_auth_passes_no_default_headers(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    captured = _install_fake_openai(monkeypatch)

    OpenAIEmbedder("text-embedding-3-small")

    assert "default_headers" not in captured
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_openai_embedder.py -k injects_basic_auth -v`
Expected: FAIL — `OpenAIEmbedder` does not accept `basic_auth` (TypeError: unexpected keyword argument).

- [ ] **Step 3: Update `__init__`**

The current `OpenAIEmbedder.__init__` (lines 25-43) is:

```python
class OpenAIEmbedder(Embedder):
    def __init__(self, model_name: str = "text-embedding-3-small", client=None):
        self.name = f"openai:{model_name}"
        self._model_name = model_name
        # Known OpenAI models have a fixed dimension; for anything else (e.g. a
        # local model served via OPENAI_BASE_URL) it's learned from the first
        # response, mirroring LocalEmbedder.
        self._dim: int | None = _OPENAI_DIMS.get(model_name)
        # ``client`` is injectable for tests; otherwise built from the env.
        # OpenAI() reads OPENAI_API_KEY / OPENAI_BASE_URL.
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is required for the openai embedder backend")
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - optional dep
                raise RuntimeError("Install the 'openai' package to use the openai backend") from exc
            client = OpenAI()
        self._client = client
```

Replace it with:

```python
class OpenAIEmbedder(Embedder):
    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        client=None,
        basic_auth: str | None = None,
        basic_auth_header: str = "Authorization",
    ):
        self.name = f"openai:{model_name}"
        self._model_name = model_name
        # Known OpenAI models have a fixed dimension; for anything else (e.g. a
        # local model served via OPENAI_BASE_URL) it's learned from the first
        # response, mirroring LocalEmbedder.
        self._dim: int | None = _OPENAI_DIMS.get(model_name)
        # ``client`` is injectable for tests; otherwise built from the env.
        # OpenAI() reads OPENAI_API_KEY / OPENAI_BASE_URL.
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is required for the openai embedder backend")
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - optional dep
                raise RuntimeError("Install the 'openai' package to use the openai backend") from exc
            # Optional HTTP Basic Auth for a server behind a proxy/gateway. The
            # SDK merges default_headers after its Bearer auth header, so the
            # "Authorization" default overrides Bearer; a custom name coexists.
            if basic_auth:
                client = OpenAI(
                    default_headers={basic_auth_header: _basic_auth_value(basic_auth)}
                )
            else:
                client = OpenAI()
        self._client = client
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_openai_embedder.py -k injects_basic_auth -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opendomainmcp/embedding/cloud.py tests/test_openai_embedder.py
git commit -m "feat(embedder): inject Basic Auth header into OpenAI client"
```

---

### Task 4: Wire settings through the factory

**Files:**
- Modify: `src/opendomainmcp/embedding/__init__.py:15-18` (the `openai` branch)
- Test: `tests/test_openai_embedder.py`

**Interfaces:**
- Consumes: `Settings.embedder_basic_auth`, `Settings.embedder_basic_auth_header` (Task 1); `OpenAIEmbedder(..., basic_auth=, basic_auth_header=)` (Task 3).
- Produces: `get_embedder(settings)` passes the basic-auth settings to `OpenAIEmbedder` for the `openai` backend.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_openai_embedder.py`:

```python
from opendomainmcp.config import Settings
from opendomainmcp.embedding import get_embedder


def test_get_embedder_passes_basic_auth_to_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    captured = _install_fake_openai(monkeypatch)
    settings = Settings(
        embedder_backend="openai",
        embedder_model="text-embedding-3-small",
        embedder_basic_auth="user:pass",
        embedder_basic_auth_header="X-Proxy-Authorization",
    )

    get_embedder(settings)

    assert captured["default_headers"] == {
        "X-Proxy-Authorization": "Basic dXNlcjpwYXNz"
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_openai_embedder.py::test_get_embedder_passes_basic_auth_to_openai -v`
Expected: FAIL — `default_headers` not in captured (factory does not pass basic auth yet).

- [ ] **Step 3: Update the factory**

The current `openai` branch in `src/opendomainmcp/embedding/__init__.py` (lines 15-18) is:

```python
    if backend == "openai":
        from .cloud import OpenAIEmbedder

        return OpenAIEmbedder(settings.embedder_model)
```

Replace it with:

```python
    if backend == "openai":
        from .cloud import OpenAIEmbedder

        return OpenAIEmbedder(
            settings.embedder_model,
            basic_auth=settings.embedder_basic_auth or None,
            basic_auth_header=settings.embedder_basic_auth_header,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_openai_embedder.py::test_get_embedder_passes_basic_auth_to_openai -v`
Expected: 1 passed.

- [ ] **Step 5: Run the full embedder test file + full suite**

Run: `.venv/bin/pytest tests/test_openai_embedder.py -v && .venv/bin/pytest -q`
Expected: all pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/opendomainmcp/embedding/__init__.py tests/test_openai_embedder.py
git commit -m "feat(embedder): wire basic_auth settings through get_embedder"
```

---

## Self-Review

**Spec coverage:**
- Two credential settings, not runtime-editable → Task 1 (and constraint check that `embedder_basic_auth` not in `EDITABLE_FIELDS`).
- Configurable header name, default `Authorization` → Task 1 default + Task 3 tests (default + custom header).
- `_basic_auth_value` pure helper, base64, Fail Loud on missing `:` → Task 2.
- Inject via `default_headers`, real-client path only, injected-client path unchanged → Task 3 (existing dim tests still use `client=`).
- `OPENAI_API_KEY` kept required → unchanged in Task 3; tests set a dummy key.
- Factory passes settings through → Task 4.
- `.env.example` documented → Task 1 Step 2.
- Backward compat (no basic_auth → no default_headers) → Task 3 test `..._no_basic_auth_passes_no_default_headers`.
- Offline tests → fake `openai` module + injected clients; no network.

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `_basic_auth_value(spec: str) -> str` used consistently across Tasks 2/3; `basic_auth` / `basic_auth_header` param names consistent across Tasks 3/4; settings names `embedder_basic_auth` / `embedder_basic_auth_header` consistent across Tasks 1/4.
