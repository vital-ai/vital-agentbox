# Orchestrator REST API

> Auto-generated from OpenAPI schema. Do not edit manually.
> Regenerate with: `python scripts/generate_api_docs.py`

REST API for the AgentBox orchestrator. Handles worker registration,
request routing, and sandbox lifecycle across multiple workers.

**Version**: 0.1.3

> **Note**: Endpoints under `/internal/*` are exempt from JWT authentication
> and are used for worker-to-orchestrator communication.

## Other

### `GET /health`

Health

**Responses:**

- **200**: Successful Response

---

### `GET /metrics`

Metrics

**Responses:**

- **200**: Successful Response

---

## admin

### `GET /admin/sandboxes`

Admin List Sandboxes

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `state` | query | `string | null` | No |  |
| `tenant` | query | `string | null` | No |  |
| `box_type` | query | `string | null` | No |  |
| `offset` | query | `integer` | No |  |
| `limit` | query | `integer` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /admin/sandboxes/bulk-destroy`

Admin Bulk Destroy

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `state` | `string | null` | No | State |
| `tenant` | `string | null` | No | Tenant |
| `sandbox_ids` | `array[string] | null` | No | Sandbox Ids |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /admin/sandboxes/{sandbox_id}`

Admin Get Sandbox

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `DELETE /admin/sandboxes/{sandbox_id}`

Admin Destroy Sandbox

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /admin/sandboxes/{sandbox_id}/files`

Admin Browse Files

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /admin/sandboxes/{sandbox_id}/files/read`

Admin Read File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /admin/tenants`

Admin Tenant Summary

**Responses:**

- **200**: Successful Response

---

## sandboxes

### `POST /sandboxes`

Create Sandbox

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `box_type` | `string` | No | Box Type (default: `mem`) |
| `repo_id` | `string | null` | No | Repo Id |
| `engine` | `string | null` | No | Execution engine: `pyodide` (default) or `agentcore` |
| `data_path` | `string | null` | No | S3 data path (Mode 2/3 only) |
| `s3_credentials` | `S3Credentials | null` | No | Caller-provided STS creds (Mode 3 only) |
| `credential_webhook_url` | `string | null` | No | Webhook URL for credential expiry notifications (Mode 3) |
| `webhook_secret` | `string | null` | No | HMAC secret for signing webhook payloads (Mode 3) |
| `timeout` | `integer | null` | No | Timeout |
| `metadata` | `object | null` | No | Metadata |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `PATCH /sandboxes/{sandbox_id}/credentials`

Update Credentials

Refresh S3 credentials for a running Mode 3 sandbox. Resets the credential
expiry timer. Proxied to the worker hosting the sandbox.

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-----------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `s3_credentials` | `S3Credentials` | Yes | Fresh STS credentials |

**Responses:**

- **200**: Successful Response
- **404**: Sandbox not found
- **422**: Validation Error

---

### `GET /sandboxes`

List Sandboxes

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `state_filter` | query | `string | null` | No |  |
| `box_type` | query | `string | null` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /sandboxes/{sandbox_id}`

Get Sandbox

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `DELETE /sandboxes/{sandbox_id}`

Destroy Sandbox

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /sandboxes/{sandbox_id}/execute`

Execute

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | `string` | Yes | Code |
| `language` | `string` | No | Language (default: `python`) |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /sandboxes/{sandbox_id}/files`

List Files

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `DELETE /sandboxes/{sandbox_id}/files`

Remove File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /sandboxes/{sandbox_id}/files/copy`

Copy File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `src` | `string` | Yes | Src |
| `dst` | `string` | Yes | Dst |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /sandboxes/{sandbox_id}/files/mkdir`

Mkdir

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Path |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /sandboxes/{sandbox_id}/files/read`

Read File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No |  |
| `binary` | query | `boolean` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /sandboxes/{sandbox_id}/files/write`

Write File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Path |
| `content` | `string` | Yes | Content |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /sandboxes/{sandbox_id}/shell`

Shell

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | `string` | Yes | Command |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

## browsers

### `POST /browsers`

Create Browser Session

Creates a new Playwright browser session on a browser-capable worker.

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `viewport_width` | `integer` | No | Browser width (default: `1280`) |
| `viewport_height` | `integer` | No | Browser height (default: `720`) |
| `user_agent` | `string | null` | No | Custom user agent |

**Responses:**

- **200**: Successful Response — `{"session_id": "...", "ws_url": "ws://..."}`
- **503**: No browser-capable workers available

---

### `DELETE /browsers/{session_id}`

Close Browser Session

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-----------|
| `session_id` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **404**: Session not found

---

### `WebSocket /browsers/{session_id}/ws`

Browser Command WebSocket

Real-time browser control via JSON messages.

**Messages (client → server):**

| Field | Type | Description |
|-------|------|-------------|
| `action` | `string` | Command: `navigate`, `click`, `type`, `screenshot`, `evaluate`, etc. |
| `params` | `object` | Action-specific parameters |

**Messages (server → client):**

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `ok` or `error` |
| `result` | `any` | Action result (screenshot base64, page content, etc.) |

---

## workers

### `POST /internal/workers/deregister`

Deregister Worker

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `worker_id` | `string` | Yes | Worker Id |
| `active_sandboxes` | `integer` | No | Active Sandboxes (default: `0`) |
| `state` | `string` | No | State (default: `active`) |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /internal/workers/heartbeat`

Worker Heartbeat

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `worker_id` | `string` | Yes | Worker Id |
| `active_sandboxes` | `integer` | No | Active Sandboxes (default: `0`) |
| `state` | `string` | No | State (default: `active`) |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /internal/workers/register`

Register Worker

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `worker_id` | `string` | Yes | Worker Id |
| `endpoint` | `string` | Yes | Endpoint |
| `max_sandboxes` | `integer` | No | Max Sandboxes (default: `50`) |
| `active_sandboxes` | `integer` | No | Active Sandboxes (default: `0`) |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /workers`

List Workers

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `state_filter` | query | `string | null` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

## Schemas

### BulkDestroyRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `state` | `string | null` | No | State |
| `tenant` | `string | null` | No | Tenant |
| `sandbox_ids` | `array[string] | null` | No | Sandbox Ids |

### CopyRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `src` | `string` | Yes | Src |
| `dst` | `string` | Yes | Dst |

### CreateSandboxRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `box_type` | `string` | No | Box Type (default: `mem`) |
| `repo_id` | `string | null` | No | Repo Id |
| `engine` | `string | null` | No | `pyodide` (default) or `agentcore` |
| `data_path` | `string | null` | No | S3 data path (Mode 2/3) |
| `s3_credentials` | `S3Credentials | null` | No | Caller STS creds (Mode 3) |
| `credential_webhook_url` | `string | null` | No | Webhook for credential expiry |
| `webhook_secret` | `string | null` | No | HMAC secret for webhook |
| `timeout` | `integer | null` | No | Timeout |
| `metadata` | `object | null` | No | Metadata |

### S3Credentials

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `access_key_id` | `string` | Yes | AWS access key ID |
| `secret_access_key` | `string` | Yes | AWS secret access key |
| `session_token` | `string` | Yes | STS session token |
| `region` | `string | null` | No | AWS region |
| `endpoint_url` | `string | null` | No | Custom S3 endpoint |
| `expires_at` | `string | null` | No | ISO 8601 expiry timestamp |

### UpdateCredentialsRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `s3_credentials` | `S3Credentials` | Yes | Fresh STS credentials |

### ExecuteRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | `string` | Yes | Code |
| `language` | `string` | No | Language (default: `python`) |

### HTTPValidationError

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

### MkdirRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Path |

### ShellRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | `string` | Yes | Command |

### ValidationError

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `loc` | `array[string | integer]` | Yes | Location |
| `msg` | `string` | Yes | Message |
| `type` | `string` | Yes | Error Type |
| `input` | `any` | No | Input |
| `ctx` | `object` | No | Context |

### WorkerHeartbeatRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `worker_id` | `string` | Yes | Worker Id |
| `active_sandboxes` | `integer` | No | Active Sandboxes (default: `0`) |
| `state` | `string` | No | State (default: `active`) |

### WorkerRegisterRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `worker_id` | `string` | Yes | Worker Id |
| `endpoint` | `string` | Yes | Endpoint |
| `max_sandboxes` | `integer` | No | Max Sandboxes (default: `50`) |
| `active_sandboxes` | `integer` | No | Active Sandboxes (default: `0`) |

### WriteFileRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Path |
| `content` | `string` | Yes | Content |
