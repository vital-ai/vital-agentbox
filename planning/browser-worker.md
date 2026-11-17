# BrowserWorker Integration Plan

Add a **BrowserWorker** to the AgentBox fleet — a new worker type that provides remote browser automation alongside the existing CodeWorker (Pyodide sandbox). The BrowserWorker is accessed via WebSocket for persistent sessions, routed through the orchestrator.

---

## Motivation

Agents need browser control in two modes:

1. **Agent-as-tool**: The agent calls a "browse" tool; the orchestrator routes to a BrowserWorker.
2. **Code-that-browses**: Agent writes automation scripts in the sandbox; the code bridges to a BrowserWorker via Tier 3 host commands.

Both require a managed browser service with session lifecycle, idle timeouts, capacity limits, and tenant isolation — the same operational model as CodeWorkers.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Orchestrator (ECS)                 │
│  FastAPI • Redis • JWT auth • proxy/routing          │
│                                                     │
│  Routes by worker_type:                             │
│    "code"    → CodeWorkers (Pyodide)                │
│    "browser" → BrowserWorkers (Playwright)          │
│                                                     │
│  WebSocket proxy: /browsers/{id}/ws → BrowserWorker │
│  REST proxy:      /browsers/{id}/*  → BrowserWorker │
└──────────┬──────────────────────────┬───────────────┘
           │                          │
    ┌──────▼──────┐          ┌────────▼────────┐
    │ CodeWorker  │          │ BrowserWorker   │
    │ Chromium    │          │ Chromium/Firefox │
    │ Pyodide     │          │ Playwright      │
    │ MemFS       │          │ SessionPool     │
    │ Port 8091+  │          │ Port 8070+      │
    └─────────────┘          └─────────────────┘
```

---

## BrowserWorker Design

### Session Lifecycle

| State | Description |
|-------|-------------|
| `creating` | Launching browser context |
| `ready` | Connected, accepting commands |
| `busy` | Executing a command |
| `idle` | No active WebSocket, awaiting reconnect |
| `destroyed` | Closed and cleaned up |

### Capacity Model

- Each BrowserWorker supports N concurrent sessions (default: 3, configurable).
- Each session = one Playwright persistent context + one page.
- All sessions share one Playwright instance (same as existing `browser-service`).
- Workers self-register with orchestrator on startup: `{type: "browser", capacity: N}`.

### Browser Engines

| Engine | Use Case |
|--------|----------|
| Chrome (headed, Xvfb) | Standard automation, captcha solving |
| Camoufox (Firefox) | Anti-fingerprinting, stealth scraping |

Engine selection is per-session via `SessionConfig.browser_type`.

---

## API Design

### Orchestrator Routes (new)

```
POST   /browsers                          → Create browser session
GET    /browsers                          → List browser sessions
GET    /browsers/{id}                     → Get session info
DELETE /browsers/{id}                     → Destroy session
WS     /browsers/{id}/ws                  → WebSocket command channel
```

The orchestrator proxies WebSocket connections to the appropriate BrowserWorker.

### WebSocket Protocol

Client connects to `ws://orchestrator/browsers/{id}/ws`. Messages are JSON:

**Client → Server (commands):**
```json
{"action": "navigate", "url": "https://example.com", "wait_until": "domcontentloaded"}
{"action": "click", "selector": "#submit-btn"}
{"action": "fill", "selector": "input[name='q']", "value": "search term"}
{"action": "get_content"}
{"action": "screenshot"}
{"action": "evaluate", "expression": "document.title"}
{"action": "solve_captcha"}
{"action": "close"}
```

**Server → Client (responses):**
```json
{
  "status": "ok",
  "action": "navigate",
  "data": "Page Title",
  "page": {"url": "https://...", "title": "...", "html_length": 12345, "content_hash": "a1b2c3d4e5f6"}
}
```

Every response includes `page` state (URL, title, content hash) for client-side change detection.

**Actions:**

| Action | Fields | Returns |
|--------|--------|---------|
| `navigate` | `url`, `wait_until?`, `timeout?` | Page title |
| `fill` | `selector`, `value` | — |
| `click` | `selector` | — |
| `select` | `selector`, `value` | — |
| `get_content` | — | Page HTML |
| `get_title` | — | Page title |
| `get_url` | — | Current URL |
| `wait` | `timeout` (ms) | — |
| `wait_for_selector` | `selector`, `timeout?` | `true`/`false` |
| `wait_for_load_state` | `state?`, `timeout?` | — |
| `click_and_wait` | `selector`, `wait_until?`, `timeout?` | New page title |
| `screenshot` | — | Base64 PNG |
| `evaluate` | `expression` | JS result |
| `solve_captcha` | — | `{solved, method, message}` |
| `close` | — | Closes session |

### Session Configuration

Provided at creation time (`POST /browsers`):

```json
{
  "browser_type": "chrome",
  "proxy": {"server": "http://proxy:8080", "username": "...", "password": "..."},
  "viewport_width": 1280,
  "viewport_height": 720,
  "user_agent": "...",
  "locale": "en-US",
  "timezone_id": "America/New_York",
  "geolocation": {"latitude": 40.7, "longitude": -74.0, "accuracy": 100}
}
```

---

## Integration with CodeWorker (WebSocket-Native)

For "code that browses" — agent writes Python that controls a browser from
inside the Pyodide sandbox using the browser's native WebSocket API.

### Why WebSocket-Native (not Tier 3 Bridge)

Pyodide runs inside a Chromium page. The page has access to the browser's
`WebSocket` API. Python code can use it directly via `js` interop — no
sendMessage bridge needed.

| | Tier 3 Bridge | WebSocket-Native |
|---|---|---|
| **Path** | Pyodide → sendMessage → host → HTTP/WS → BrowserWorker | Pyodide → browser WebSocket → orchestrator → BrowserWorker |
| **Hops** | 3 (sendMessage + host + WS) | 1 (single WS from page) |
| **Latency** | Higher (serialization at each hop) | Lower (direct WS) |
| **Streaming** | Awkward (poll for updates) | Natural (WS is bidirectional) |
| **Security** | Host controls access | CSP restricts to orchestrator only |
| **Complexity** | Bridge handler code in host | Just a Python WS wrapper |
| **Portability** | Needs reimplementation for AgentCore | Works as-is (real Python, real network) |

### Security: CSP as Network Firewall

The Pyodide sandbox page is served with a Content Security Policy that restricts
all network access to the orchestrator only:

```http
Content-Security-Policy:
  default-src 'self' 'unsafe-eval' blob: data:;
  connect-src ws://{ORCHESTRATOR_HOST} wss://{ORCHESTRATOR_HOST};
  script-src 'self' 'unsafe-eval' blob:;
```

This means:
- ✅ WebSocket to orchestrator — **allowed**
- ❌ WebSocket to arbitrary hosts — **blocked by Chrome**
- ❌ fetch/XHR to external APIs — **blocked by Chrome**

Chrome enforces CSP at the network layer. No code in Pyodide can bypass it.
The orchestrator remains the single gateway for both code execution and browser control.

### In-Sandbox Client Library

**Target API** (for agent use — not yet implemented):

```python
# agentbox/browser_client — runs inside Pyodide or AgentCore
from agentbox.browser_client import Browser

b = await Browser.create()
await b.goto("https://example.com")
title = await b.title()
html = await b.content()
await b.click("#login-btn")
await b.fill("input[name='email']", "user@example.com")
await b.fill("input[name='password']", "secret")
await b.click("button[type='submit']")
screenshot_b64 = await b.screenshot()
await b.close()
```

**Current implementation — sendMessage bridge** (working):

The Pyodide page is served from `https://cdn.jsdelivr.net`, so `js.WebSocket` to
Docker services is blocked (mixed content). Instead, browser operations go through
the `sendMessage` bridge (Playwright `exposeFunction`):

```python
# agentbox/browser/bridge.py — runs on the HOST (code worker), not in Pyodide
# Handles two message types from Pyodide:
#   browser_request → HTTP proxy to orchestrator /browsers endpoints
#   browser_command → WS round-trip to orchestrator /browsers/{id}/ws

# In Pyodide, agent code currently uses:
result = await messaging.send({
    "type": "browser_request",
    "method": "POST",
    "path": "/browsers",
    "body": {}
})
session_id = result["data"]["session_id"]

result = await messaging.send({
    "type": "browser_command",
    "session_id": session_id,
    "command": {"action": "navigate", "url": "https://example.com"}
})
title = result["data"]["data"]  # page title
```

**Target implementation** (the `Browser` class wraps the bridge):

```python
# agentbox/browser_client/__init__.py — runs in Pyodide or AgentCore
class Browser:
    """High-level browser client. Uses sendMessage bridge in Pyodide,
    websockets library in AgentCore."""

    def __init__(self, session_id):
        self.session_id = session_id

    @classmethod
    async def create(cls):
        # Pyodide: messaging.send({"type": "browser_request", ...})
        # AgentCore: httpx.post(orchestrator_url + "/browsers")
        ...

    async def goto(self, url, wait_until="domcontentloaded"):
        return await self._cmd({"action": "navigate", "url": url, "wait_until": wait_until})

    async def click(self, selector):
        return await self._cmd({"action": "click", "selector": selector})

    async def fill(self, selector, value):
        return await self._cmd({"action": "fill", "selector": selector, "value": value})

    async def content(self):
        return await self._cmd({"action": "get_content"})

    async def screenshot(self):
        return await self._cmd({"action": "screenshot"})

    async def title(self):
        return await self._cmd({"action": "get_title"})

    async def evaluate(self, expression):
        return await self._cmd({"action": "evaluate", "expression": expression})

    async def solve_captcha(self):
        return await self._cmd({"action": "solve_captcha"})

    async def close(self):
        await self._cmd({"action": "close"})
        # Pyodide: messaging.send({"type": "browser_request", "method": "DELETE", ...})
        # AgentCore: httpx.delete(orchestrator_url + "/browsers/{id}")

    async def _cmd(self, command):
        # Pyodide: messaging.send({"type": "browser_command", ...})
        # AgentCore: ws.send(json.dumps(command)) on persistent WS
        ...
```

### Runtime Detection

```python
# agentbox/browser_client/__init__.py
try:
    from js import WebSocket as JSWebSocket  # Pyodide
    _RUNTIME = "pyodide"
except ImportError:
    _RUNTIME = "native"  # AgentCore / real Python
```

In Pyodide, `Browser._cmd()` uses `messaging.send()` (sendMessage bridge).
In AgentCore, `Browser._cmd()` uses a persistent `websockets` connection to the
orchestrator's `/browsers/{id}/ws` proxy.

### Data Flow

```
Pyodide Page                          Orchestrator              BrowserWorker
(CSP: connect-src ws://orch)          (WS proxy)
─────────────────────────────         ───────────────           ─────────────
Browser.create()
  → POST /browsers           ──────►  route to BrowserWorker
                                       create session   ──────► new context + page
                             ◄──────  {session_id}     ◄────── ready
  ← Browser(session_id)

  → open WS /browsers/{id}/ws ─────►  proxy WS frames  ──────► accept

b.goto(url)
  → ws.send({navigate, url}) ──────►  relay             ──────► page.goto(url)
                             ◄──────  relay             ◄────── {ok, title, page}
  ← "Page Title"

b.screenshot()
  → ws.send({screenshot})    ──────►  relay             ──────► page.screenshot()
                             ◄──────  relay             ◄────── {ok, base64_png}
  ← base64 PNG

b.solve_captcha()
  → ws.send({solve_captcha}) ──────►  relay             ──────► detect + solve
                             ◄──────  relay (progress)  ◄────── {info, "clicking..."}
                             ◄──────  relay (progress)  ◄────── {info, "solving..."}
                             ◄──────  relay (done)      ◄────── {ok, {solved: true}}
  ← {solved: true, method: "hcaptcha_solver"}
```

### CSP Configuration in CodeWorker

When the CodeWorker serves the Pyodide sandbox page, it injects the CSP:

```python
# In CodeWorker sandbox page setup
ORCHESTRATOR_URL = os.environ.get("AGENTBOX_ORCHESTRATOR_URL", "http://localhost:8090")
orch_host = ORCHESTRATOR_URL.split("//")[1]  # "localhost:8090"

csp = (
    "default-src 'self' 'unsafe-eval' blob: data:; "
    f"connect-src ws://{orch_host} wss://{orch_host} http://{orch_host} https://{orch_host}; "
    "script-src 'self' 'unsafe-eval' blob:; "
)
# Set as HTTP header or <meta> tag on sandbox.html
```

### AgentCore Portability

When running under AgentCore (real Linux VM), the same `agentbox.browser` module
works without modification — real Python has real WebSocket libraries (websockets,
aiohttp). The orchestrator URL is provided as an environment variable. No Pyodide
`js` interop needed; the module detects the runtime and uses the appropriate
WebSocket implementation:

```python
# Runtime detection in agentbox/browser.py
try:
    from js import WebSocket as JSWebSocket  # Pyodide
    _RUNTIME = "pyodide"
except ImportError:
    import websockets  # AgentCore / real Python
    _RUNTIME = "native"
```

---

## Orchestrator Changes

### Worker Registry

Extend Redis worker registry to include `type`:

```
agentbox:worker:{worker_id} → {
  "endpoint": "http://browser-1:8070",
  "type": "browser",          // NEW
  "capacity": 3,
  "active": 1,
  "state": "active"
}
```

### Routing

- `POST /sandboxes` (existing) → routes to `type=code` workers
- `POST /browsers` (new) → routes to `type=browser` workers
- Routing logic is the same: find worker with available capacity, prefer least-loaded.

### WebSocket Proxy

The orchestrator proxies WebSocket connections from clients to BrowserWorkers:

```python
@router.websocket("/browsers/{session_id}/ws")
async def browser_ws_proxy(ws: WebSocket, session_id: str):
    # Look up which BrowserWorker owns this session
    # Open WS to that worker, relay frames bidirectionally
```

This is a standard WebSocket reverse proxy — relay frames in both directions.

### Session Tracking

Browser sessions tracked in Redis (same pattern as sandboxes):

```
agentbox:browser:{session_id} → {
  "worker_id": "browser-1",
  "tenant": "user-123",
  "created_at": 1718...,
  "state": "ready"
}
```

---

## Unified Worker Internal Design

### Package Layout (single codebase)

```
agentbox/
├── worker/                          # Shared worker infrastructure
│   ├── main.py                      # FastAPI app, mode-aware startup
│   ├── register.py                  # Self-registration with orchestrator
│   ├── health.py                    # Health endpoint (capacity, mode)
│   └── auth.py                      # JWT middleware (shared)
├── box/                             # Code execution (WORKER_MODE=code)
│   ├── box.py                       # Abstract Box base
│   ├── code_executor_box.py         # Pyodide sandbox (MemBox)
│   ├── git_box.py                   # GitBox
│   └── ...
├── browser/                         # Browser automation (WORKER_MODE=browser)
│   ├── session.py                   # BrowserSession (Playwright context)
│   ├── pool.py                      # SessionPool (capacity, idle cleanup)
│   ├── models.py                    # Pydantic models (commands, responses)
│   ├── captcha.py                   # hCaptcha/Cloudflare solver (isolated)
│   ├── ws_handler.py                # WebSocket command dispatch
│   └── routes.py                    # Internal REST + WS endpoints
└── browser_client/                  # In-sandbox client (runs in Pyodide or AgentCore)
    └── __init__.py                  # Browser class (WebSocket-native)
```

### Mode-Aware Startup

```python
# agentbox/worker/main.py
WORKER_MODE = os.environ.get("WORKER_MODE", "both")

app = FastAPI()

# Always register health + registration
app.include_router(health_router)

if WORKER_MODE in ("code", "both"):
    from agentbox.worker.routes_code import router as code_router
    app.include_router(code_router)
    # Start BoxManager

if WORKER_MODE in ("browser", "both"):
    from agentbox.browser.routes import router as browser_router
    app.include_router(browser_router)
    # Start SessionPool + Xvfb
```

### Key Differences from browser-service

| Aspect | browser-service (standalone) | Unified Worker (new) |
|--------|------------------------------|----------------------|
| Auth | None | JWT (shared `agentbox/worker/auth.py`) |
| Registration | Standalone | Self-registers with orchestrator (shared) |
| Session creation | Via WS first message | Via REST `POST /internal/browsers` |
| WS connect | Creates session implicitly | Connects to existing session |
| Captcha solver | Built into session class | Extracted to `agentbox/browser/captcha.py` |
| Tenant isolation | None | Scoped by JWT `sub` claim |
| Code execution | N/A | Same process when `WORKER_MODE=both` |

### Internal API (orchestrator → worker, not public)

```
# Code endpoints (WORKER_MODE=code or both)
POST   /internal/sandboxes             → Create sandbox
DELETE /internal/sandboxes/{id}        → Destroy sandbox
GET    /internal/sandboxes/{id}        → Sandbox status
POST   /internal/sandboxes/{id}/execute → Execute code/shell

# Browser endpoints (WORKER_MODE=browser or both)
POST   /internal/browsers              → Create session
DELETE /internal/browsers/{id}         → Destroy session
GET    /internal/browsers/{id}         → Session status
WS     /internal/browsers/{id}/ws     → Command channel

# Shared
GET    /internal/health                → Health + capacity (by type)
POST   /internal/register             → Self-register with orchestrator
```

---

## Deployment

### Single Unified Image

One Docker image supports all modes via `WORKER_MODE` environment variable:

```
agentbox-worker:latest (~2.0 GB):
  - Python 3.12
  - Playwright + Chromium (headless, for Pyodide sandbox)
  - Google Chrome (headed) + Xvfb (for browser automation)
  - Camoufox (optional anti-fingerprint Firefox)
  - Pyodide WASM bundle
  - FastAPI + uvicorn
  - hcaptcha-challenger
  - Shared: auth, registration, capacity management
```

### Mode Flag

| `WORKER_MODE` | Registers as | Capabilities |
|---------------|--------------|--------------|
| `code` | `type=code` | Pyodide sandboxes only |
| `browser` | `type=browser` | Browser sessions only |
| `both` | `type=code` + `type=browser` | Both (dev / small deployments) |

### Dockerfile (unified)

```dockerfile
FROM python:3.12-slim

# Shared deps
RUN apt-get update && apt-get install -y xvfb fonts-liberation ...

# Chrome (for browser automation — headed mode)
RUN wget -q ... && apt-get install -y google-chrome-stable

# Playwright Chromium (for Pyodide sandbox — headless)
RUN pip install playwright && playwright install chromium && playwright install-deps

# Camoufox (optional anti-detect)
RUN pip install camoufox && python -m camoufox fetch

# Python deps (shared)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (unified)
COPY agentbox/ agentbox/
COPY entrypoint.sh .

ENV WORKER_MODE=both
CMD ["./entrypoint.sh"]
```

### ECS Deployment (Production)

Same image, different config, independent scaling:

```json
// Code workers — more instances, lighter workload
{
  "family": "agentbox-code-worker",
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [{
    "name": "worker",
    "image": "agentbox-worker:latest",
    "environment": [
      {"name": "WORKER_MODE", "value": "code"},
      {"name": "MAX_SANDBOXES", "value": "50"},
      {"name": "AGENTBOX_ORCHESTRATOR_URL", "value": "http://orchestrator:8090"}
    ]
  }]
}

// Browser workers — fewer instances, heavier per-session
{
  "family": "agentbox-browser-worker",
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [{
    "name": "worker",
    "image": "agentbox-worker:latest",
    "environment": [
      {"name": "WORKER_MODE", "value": "browser"},
      {"name": "MAX_SESSIONS", "value": "3"},
      {"name": "SESSION_IDLE_TIMEOUT", "value": "300"},
      {"name": "AGENTBOX_ORCHESTRATOR_URL", "value": "http://orchestrator:8090"},
      {"name": "GEMINI_API_KEY", "value": "..."}
    ]
  }]
}
```

### Dev / Single-Instance Deployment

```bash
# One container does everything
docker run -e WORKER_MODE=both -p 8091:8091 agentbox-worker:latest
```

### Localhost Optimization

When running in `both` mode, sandbox code connects to browser sessions
on localhost without going through the orchestrator:

```
Pyodide Page → ws://localhost:8070/browsers/{id}/ws → same process
```

CSP allows both orchestrator and localhost in `both` mode:

```http
connect-src ws://localhost:8070 ws://orchestrator:8090 wss://orchestrator:8090;
```

This eliminates the orchestrator WS proxy hop for co-located workloads.

### Scaling

- **Code workers**: Scale based on sandbox count (50 per instance, lightweight)
- **Browser workers**: Scale based on session count (3 per instance, heavyweight)
- Same image in both ECS services — only env vars differ
- Orchestrator launches tasks via `ecs:RunTask` when capacity is full
- `both` mode useful for dev, demos, and low-traffic single-instance setups

---

## Security

| Concern | Mitigation |
|---------|------------|
| Open web access | URL allowlist/blocklist per tenant (configurable) |
| Data exfiltration | Sessions are tenant-scoped; no cross-tenant access |
| Resource exhaustion | Max sessions per worker; idle timeout; orchestrator rate limiting |
| Malicious pages | Chrome runs with `--no-sandbox` inside container (container IS the sandbox) |
| Credential leaking | Proxy credentials stored in session config, not logged |
| Captcha solver costs | Rate limit solve_captcha per tenant; meter Gemini API usage |

---

## Implementation Phases

### Phase 1: Browser Package in Unified Worker (Week 1)

- [x] Create `agentbox/browser/` package (session, pool, models, ws_handler, routes)
- [x] Implement `BrowserSession` (adapted from `browser-service/app/browser_session.py`)
- [x] Implement `SessionPool` with capacity + idle cleanup
- [x] Add `WORKER_MODE` flag to worker `main.py` (code / browser / both)
- [x] Mode-aware router inclusion (browser routes loaded only when mode includes browser)
- [x] Unified Dockerfile (add Chrome + Xvfb + Camoufox to existing worker image)
- [x] Basic tests (session lifecycle, navigate, click, screenshot) — 29 tests pass

### Phase 2: Orchestrator Integration (Week 2)

- [x] Add `POST /browsers` to orchestrator (routes to browser-capable workers)
- [x] Add `GET/DELETE /browsers/{id}` to orchestrator
- [x] WebSocket proxy: `/browsers/{id}/ws` → worker
- [x] Redis session tracking (`browser_route:{id}` same pattern as sandboxes)
- [x] Worker registration includes `type` field (code, browser, both)
- [x] Orchestrator `pick_worker(worker_type)` routes by type
- [x] docker-compose with browser-worker service (`WORKER_MODE=browser`)
- [x] JWT auth on browser routes (via existing JWTMiddleware)

### Phase 3: In-Sandbox Browser Client (Week 3)

**Bridge layer (complete):**

- [x] `agentbox/browser/bridge.py` — `sendMessage` handler for browser operations
  - Handles `browser_request` messages: proxies HTTP to orchestrator `/browsers` endpoints
  - Handles `browser_command` messages: opens WS to orchestrator, sends command, returns response
  - Used by Pyodide sandbox code via `messaging.send({"type": "browser_request", ...})`
- [x] `agentbox/api/routes/internal.py` — wired `browser_message_handler` into sandbox creation
  so all sandboxes can use `messaging.send()` to control browsers
- [x] Integration tests: 5/5 passing — sandbox code creates browser sessions, navigates
  Wikipedia/HN/GitHub, takes screenshots, clicks links, evaluates JS, reads page content.
  Full path: Pyodide → sendMessage → host → HTTP/WS → orchestrator → browser-worker → Chromium

**Design note — sendMessage bridge vs WebSocket-native:**

The plan originally called for `js.WebSocket` from the Pyodide page directly to the
orchestrator. This doesn't work because the Pyodide page is served from
`https://cdn.jsdelivr.net` (HTTPS), so `ws://` connections to Docker services are
blocked as mixed content. The `sendMessage` bridge (Playwright `exposeFunction`)
bypasses this — it's a JavaScript function call, not a network request.

To enable the WebSocket-native path in the future:
1. Serve the Pyodide sandbox page from the worker itself (HTTP, not CDN HTTPS)
2. Set `AGENTBOX_PYODIDE_URL` to a local HTTP URL
3. Then `js.WebSocket` to orchestrator works (no mixed content)
4. CSP `connect-src` restricts WS targets to orchestrator only

For now, the sendMessage bridge is functionally equivalent and works with the current
CDN-based Pyodide setup. Each `browser_cmd()` call opens a new WS connection (one
round-trip per command). A persistent WS connection would be more efficient but
requires the WebSocket-native path or a long-lived WS in the bridge.

**In-sandbox client library (complete):**

- [x] `agentbox/browser_client/__init__.py` — high-level `Browser` class for agent use
  - `b = await Browser.create(config={"browser_type": "camoufox"})` — creates session via bridge
  - `await b.goto(url)`, `await b.click(sel)`, `await b.fill(sel, val)`
  - `await b.click_and_wait_for_navigation(sel)` — click + wait for page nav
  - `await b.screenshot()`, `await b.content()`, `await b.title()`
  - `await b.evaluate(expr)`, `await b.solve_captcha()`, `await b.close()`
  - `Browser.create(config=...)` passes session config (browser_type, proxy, etc.) to orchestrator
  - Runtime detection: Pyodide uses `messaging.send()`, AgentCore uses `websockets`
- [x] Pre-install `Browser` in Pyodide sandbox (available as `from agentbox.browser_client import Browser`)
  - `PyodideEngine._inject_browser_client()` reads source and registers in `sys.modules`
  - Called during `start()` — available immediately for agent code
- [ ] Add CSP header to sandbox page (`connect-src` → orchestrator + localhost)
- [ ] Localhost optimization for `both` mode (skip orchestrator hop)
- [ ] Persistent WS in bridge (optional optimization — keep one WS per session instead of per-command)

### Phase 4: Captcha & Stealth (Week 3-4)

- [x] Extract captcha solver to `agentbox/browser/captcha.py`
- [x] Add Camoufox support (anti-fingerprinting)
  - `Dockerfile.worker`: added `camoufox`, `xvfb`, Firefox libs, `worker-entrypoint.sh`
  - `Browser.create(config={"browser_type": "camoufox"})` → orchestrator → browser-worker
  - Verified working: Camoufox bypasses Cloudflare on NYSCEF ("Just a moment..." challenge)
- [ ] Per-tenant captcha usage metering
- [ ] URL allowlist/blocklist configuration

### Phase 4.5: Browser Tools Adaptation ✅ COMPLETE

Adapted `browser-service/nyscef` and `browser-service/web` tool packages to use
`agentbox.browser_client.Browser` instead of the old `BrowserClient`.

**Pyodide tool injection** (`agentbox/engine/pyodide_engine.py`):
- [x] `_inject_tools()` — writes `agentbox/tools/` source files to Emscripten FS at startup
  - Skips `*_tool.py` files (depend on kgraphplanner/langchain, unavailable in Pyodide)
  - Files written to `/agentbox_lib/agentbox/tools/...`, added to `sys.path`
  - Extends `agentbox.__path__` so sub-package imports work naturally
  - Agent installs deps via micropip (`pydantic`, `beautifulsoup4`), then imports normally

**NYSCEF tools** (`agentbox/tools/nyscef/`):
- [x] `models.py` — Pydantic models
- [x] `html_parser.py` — HTML parsers
- [x] `session_manager.py` — uses `Browser.create(config=...)` + `click_and_wait_for_navigation`
- [x] `nyscef_case_search_tool.py` — adapted imports (host-only, not injected into Pyodide)
- [x] `nyscef_case_detail_tool.py` — adapted imports (host-only, not injected into Pyodide)

**Web tools** (`agentbox/tools/web/`):
- [x] `models.py` — Pydantic models
- [x] `html_helpers.py` — extracted from `web_extract_tool.py` (avoids kgraphplanner dep)
- [x] `session_store.py` — singleton `Browser` session management
- [x] `web_navigate_tool.py` — adapted to Browser API (host-only)
- [x] `web_interact_tool.py` — adapted to Browser API (host-only)
- [x] `web_extract_tool.py` — adapted to Browser API (host-only)
- [x] `web_close_tool.py` — adapted to Browser API (host-only)

**Tests:**
- [x] `test/test_nyscef_tools.py` — 18 passed (models + parsers + skip guards for kgraphplanner)
- [x] `test/test_web_tools.py` — 18 passed (models + parsers + skip guards)
- [x] `test/test_nyscef_e2e.py` — 2 passed (**runs inside Pyodide sandbox**)
  - Pyodide → sendMessage → host → orchestrator → browser-worker (camoufox) → NYSCEF
  - micropip installs pydantic + bs4 → imports NyscefSessionManager + html_parser
  - Search "Cardiff" → 25 cases, ~150 total (14–16s)
  - Docket page fetch + parse (1.1s)
- [x] `test/test_browser_service_e2e.py` — 6 passed (raw HTTP/WS against browser-worker)
- [x] `test/test_tools_e2e.py` — Browser client + html_helpers + session_store live tests
- [x] `test/test_browser_pool.py` — 12 passed (Browser client inside Pyodide sandbox)

### Phase 5: Deep Agents Skill (Week 4)

- [ ] `BrowserSkill` for `create_deep_agent(skills=["browser"])`
- [ ] Or: LangChain tools (`NavigateTool`, `ClickTool`, `ScreenshotTool`, etc.)
- [ ] Integration test: deep agent with both sandbox + browser
- [ ] Test `both` mode: agent code writes scraper → runs it → browser executes

---

## Success Criteria

- [x] Unified worker image supports `WORKER_MODE=code`, `browser`, and `both`
- [x] Worker self-registers with orchestrator (includes type in registration)
- [x] `POST /browsers` creates a session, returns `session_id`
- [x] WebSocket `/browsers/{id}/ws` accepts commands and returns results
- [x] navigate, click, fill, screenshot, get_content all work (29 unit tests)
- [x] Idle sessions cleaned up after timeout
- [x] Tenant isolation via JWT
- [x] Sandbox code can drive browser via sendMessage bridge (5/5 integration tests)
  - Full path: Pyodide → sendMessage → host → orchestrator → browser-worker → Chromium
  - `agentbox/browser/bridge.py` handles `browser_request` and `browser_command` messages
- [x] docker-compose stack runs orchestrator + code workers + browser-worker
- [x] High-level `Browser` client class for agent convenience (`await Browser.create(config=...)`)
  - Supports `config` dict (browser_type, proxy, viewport, etc.) passed to orchestrator/worker
  - Added `click_and_wait_for_navigation()` for form submissions
- [ ] `Browser` pre-installed in Pyodide sandbox for agent import
- [ ] WebSocket-native path (requires serving Pyodide page from worker, not CDN)
- [ ] `both` mode: localhost optimization bypasses orchestrator for WS
- [x] Camoufox anti-detection browser works end-to-end (NYSCEF Cloudflare bypass verified)
- [x] Browser tools adapted from browser-service (NYSCEF + web tools, 44+ tests passing)
- [ ] Existing code sandbox tests still pass with unified image

---

## Open Questions

1. **WS proxy vs. direct connect**: Should clients always go through orchestrator, or can they connect directly to the worker once they have the endpoint? (Orchestrator proxy is simpler for auth but adds latency. In `both` mode, localhost is used.)

2. **Session persistence**: Should browser sessions survive worker restarts? (Probably no — they're ephemeral like MemBox. Persistent state = cookies/storage in S3 if needed later.)

3. **File sharing**: Should downloads in the browser land in a code sandbox's filesystem? (In `both` mode, this is simpler — same process can write to sandbox MemFS directly. In split mode, need shared S3 path.)

4. **Multi-page**: Should a session support multiple pages/tabs, or strictly one page per session? (Start with one; multi-tab adds complexity.)

5. **Streaming screenshots**: Should the WS support a "stream" mode where screenshots are sent periodically (e.g., for human-in-the-loop monitoring)?

6. **Resource budgeting in `both` mode**: How to allocate memory between code sandboxes and browser sessions when co-located? (Separate capacity counters, e.g., `MAX_SANDBOXES=50` + `MAX_SESSIONS=2` with total memory cap.)
