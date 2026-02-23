# Orchestrator REST API

> Auto-generated from OpenAPI schema. Do not edit manually.
> Regenerate with: `python scripts/generate_api_docs.py`

REST API for the AgentBox orchestrator. Handles worker registration,
request routing, and sandbox lifecycle across multiple workers.

**Version**: 0.1.0

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
| `timeout` | `integer | null` | No | Timeout |
| `metadata` | `object | null` | No | Metadata |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

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
| `timeout` | `integer | null` | No | Timeout |
| `metadata` | `object | null` | No | Metadata |

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
