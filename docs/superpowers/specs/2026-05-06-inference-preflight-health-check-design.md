# Inference Pre-Start Endpoint Health Check

**Status:** design — pending implementation plan
**Author:** takaki, w/ Claude (Opus 4.7)
**Scope:** Add a synchronous reachability probe to the VLA inference endpoint at the start of an inference session, so that an unreachable server fails the start-session HTTP call with a clear error rather than silently entering a permanent retry loop. Surface the failure prominently in the frontend.

## Problem

Inference mode currently defers VLA-server connectivity until the producer task issues its first `predict()` call after the session has already been spawned. When the endpoint is unreachable (server down, wrong port, DNS resolution failure, network partition), the producer publishes `inference_error` events and retries forever with exponential backoff (`backend/mimicrec/inference/producer.py:111-119`). The frontend treats those events as a silently-incrementing telemetry counter (`frontend/src/state/inference-store.ts:148-149`) — no toast, no banner, no modal. The user sees the session in the "ready" phase, the start button reported success, but no inference output ever arrives. They have no signal that anything is wrong.

The Record-mode entry path fails loudly because hardware reads are part of `sm.start()`, so a missing camera or robot raises before the HTTP response. Inference should match that contract: a failed pre-condition aborts the start with a real HTTP error.

## Goals (in scope)

1. **`POST /api/session/inference/start` returns a clear HTTP error when the VLA endpoint URL is unreachable**, before any session-level state is committed and before producer/control loops are spawned.
2. **Frontend displays the resulting error message prominently** (banner / inline error pane) on the inference start screen.
3. **Network-level failures only.** A 4xx or 5xx HTTP response from the endpoint counts as "server alive" — those will be re-surfaced via the existing `inference_error` channel during real predict calls. We do not try to validate auth, schema, or routing here.

## Non-goals

- Live monitoring of endpoint health after the session has started. Mid-session failures will continue to flow through the existing `inference_error` event path. (A separate design — case "B" in the prior conversation — would improve in-session error UX. Out of scope here.)
- Allowing the user to override `endpoint.url` from the UI. The contract YAML stays the source of truth.
- Auth-failure detection (401/403). The probe accepts any HTTP response code; auth errors will be surfaced via the existing `inference_error` channel during the first real `predict()` call.
- Replacing or restructuring `start_inference_session` in `lifecycle.py`. The probe lives at the route layer to keep the lifecycle module pure.
- Pre-flight on each config dropdown change (case "a" in the prior discussion — explicitly rejected for being too eager).
- Manual "Test connection" button (case "b" — explicitly rejected for being skippable).

## Design

### Probe placement

In `backend/mimicrec/api/routes/inference.py`, add a private async helper `_probe_endpoint(spec: ContractSpec) -> None` and call it from the `start` route handler immediately before invoking `sm.start_inference_session(...)`. The probe runs at the route layer, not inside the session-lifecycle module, so that:

- The session manager remains transport-agnostic.
- The probe only runs for HTTP-triggered starts (not for unit-test code paths that build sessions directly).
- The HTTPException maps cleanly to a real HTTP response.

### Probe implementation

```python
async def _probe_endpoint(spec: ContractSpec) -> None:
    """Raise HTTPException(502) if the VLA endpoint URL is network-unreachable.

    Accepts any HTTP response (including 4xx/5xx) as 'server alive' — only
    connection-level failures (refused, DNS, timeout) count as unreachable.
    Auth, method, and routing errors will surface via the existing
    inference_error event path during the first real predict() call.
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.get(spec.endpoint.url, headers=spec.endpoint.headers)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"VLA endpoint unreachable at {spec.endpoint.url}: {e}",
        )
```

Notes:

- **GET, not HEAD.** Some servers / proxies route POST endpoints under a path that returns 404 on HEAD. GET is more reliably routed; we don't read the body, so the cost is negligible. Either way, GPU activation does not happen because most VLA servers gate inference on POST.
- **2-second timeout** rather than the contract's `endpoint.timeout_s` (default 5s). The probe is run synchronously in the start path, and the user is waiting on the start button — 2s is generous for "is anything answering?" and aborts faster on a wrong-port mistake.
- **Headers preserved.** Sending the contract's headers (including the env-interpolated `Authorization`) means a server that requires auth on every request still responds (probably 401 — still counts as "alive"), and we don't accidentally trip an upstream WAF on header-policy mismatch.
- **Catch the union `(ConnectError, TimeoutException, RequestError)`.** `RequestError` is the parent of both, but listing the specific subclasses first makes the error-path intent legible. (If httpx's class hierarchy makes this redundant, the implementer can collapse to `httpx.RequestError`.)

### Frontend display

`frontend/src/components/InferencePage.tsx` (or wherever `startSession` is wired): the existing `useStartInference` mutation hook surfaces the error as `mutation.error` (an `ApiError` with `.message`). Add a banner like the existing 409 / error styling in `ExportDatasetModal`:

```tsx
{startMutation.isError && (
  <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-800">
    {startMutation.error.message}
  </div>
)}
```

Place it near the start button. The exact wording, color, and DOM position should match the existing error-banner conventions used elsewhere in the project (we are not introducing a new design language, just consuming the mutation error that previously was being swallowed or hidden).

If the existing component already has a generic mutation-error banner that covers this case, no frontend change is required — verify during implementation.

### Tests

**Backend** (`tests/api/test_inference_routes.py`):

1. **Endpoint unreachable → 502** — point the contract's `endpoint.url` at `http://127.0.0.1:1` (a port nothing listens on) and confirm `POST /api/session/inference/start` returns 502 with the URL in the error detail. The `start_inference_session` body must not run (verifiable by checking session state was not modified).
2. **Endpoint reachable → start proceeds** — use the existing `fake_vla_server` fixture (which is a real aiohttp server that handles POST `/predict`). A GET probe against it will return whatever aiohttp returns by default for an unmatched method/path (typically 404 or 405). Both count as "server alive" per our policy, so the start route should succeed. This single test simultaneously exercises both the reachable case AND the "4xx counts as alive" rule, so we don't need a separate 4xx-specific test.
3. **Probe respects the 2s timeout** — out of scope for the first cut. The unreachable-port test in case 1 covers the dominant failure mode. If a future bug suggests the timeout is mis-set (e.g., probe blocks the start request for >5s on a half-open TCP), add a slow-server test then. Keeping it out of scope avoids fixture complexity now.

**Frontend**: manual UI verification — start the backend, point a config at a known-down endpoint (e.g., `http://localhost:9999/predict`), click "Start", confirm the error banner appears with a message containing the URL.

## Implementation footprint

**Backend (1 file)**:
- `backend/mimicrec/api/routes/inference.py` — add `_probe_endpoint` helper + `await _probe_endpoint(contract)` call before `sm.start_inference_session`.

**Frontend (0-1 file)**:
- `frontend/src/components/InferencePage.tsx` (or wherever the start mutation lives) — add or verify error-banner rendering for `startMutation.error`.

**Tests (1 file)**:
- `tests/api/test_inference_routes.py` — 2-3 new test cases (cases 1-3 above; case 4 deferred unless trivial to implement).

No new modules, no new dependencies (`httpx` already in use throughout `inference/client.py`, `inference/producer.py`).
