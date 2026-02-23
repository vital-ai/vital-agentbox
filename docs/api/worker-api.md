# Worker REST API

> Auto-generated from OpenAPI schema. Do not edit manually.
> Regenerate with: `python scripts/generate_api_docs.py`

REST API for the AgentBox worker process. Handles sandbox lifecycle,
code execution, and file operations directly.

**Version**: 0.0.3

## execute

### `POST /sandboxes/{sandbox_id}/execute`

Execute

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | `string` | Yes | Code or shell command to execute. |
| `language` | `string` | No | 'python' or 'shell' (default). (default: `shell`) |
| `timeout` | `integer | null` | No | Optional timeout override. |

**Responses:**

- **200**: Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stdout` | `string` | No | Stdout (default: ``) |
| `stderr` | `string` | No | Stderr (default: ``) |
| `exit_code` | `integer` | No | Exit Code (default: `0`) |
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

## files

### `GET /sandboxes/{sandbox_id}/files`

List Dir

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No | Directory path |
| `recursive` | query | `boolean` | No |  |
| `info` | query | `boolean` | No |  |

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
| `path` | query | `string` | Yes | File path to remove |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /sandboxes/{sandbox_id}/files/copy`

Copy

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `src` | `string` | Yes | Source path. |
| `dst` | `string` | Yes | Destination path. |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `DELETE /sandboxes/{sandbox_id}/files/dir`

Remove Dir

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | Yes | Directory path to remove |

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
| `path` | `string` | Yes | Directory path to create. |

**Responses:**

- **201**: Successful Response
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
| `path` | query | `string` | Yes | File path to read |
| `binary` | query | `boolean` | No | Read as binary (base64) |

**Responses:**

- **200**: Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Path |
| `content` | `string | null` | No | Content |
| `exists` | `boolean` | No | Exists (default: `True`) |
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
| `path` | `string` | Yes | Absolute path in the sandbox filesystem. |
| `content` | `string` | Yes | File content to write. |

**Responses:**

- **201**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

## internal

### `GET /internal/health`

Health

**Responses:**

- **200**: Successful Response

---

### `GET /internal/metrics`

Metrics

**Responses:**

- **200**: Successful Response

---

### `GET /internal/sandboxes`

List Sandboxes

**Responses:**

- **200**: Successful Response

---

### `POST /internal/sandboxes`

Create Sandbox

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sandbox_id` | `string | null` | No | Optional ID. Auto-generated if omitted. |
| `box_type` | `string` | No | Sandbox type: 'mem' or 'git'. (default: `mem`) |
| `repo_id` | `string | null` | No | Repository ID for git box (enables push/pull sync). |
| `timeout` | `integer | null` | No | Per-execution timeout override (seconds). |

**Responses:**

- **201**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /internal/sandboxes/{sandbox_id}`

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

### `DELETE /internal/sandboxes/{sandbox_id}`

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

### `POST /internal/sandboxes/{sandbox_id}/execute`

Execute

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | `string` | Yes | Code or shell command to execute. |
| `language` | `string` | No | 'python' or 'shell' (default). (default: `shell`) |
| `timeout` | `integer | null` | No | Optional timeout override. |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /internal/sandboxes/{sandbox_id}/files`

List Dir

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | No |  |
| `recursive` | query | `boolean` | No |  |
| `info` | query | `boolean` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `DELETE /internal/sandboxes/{sandbox_id}/files`

Remove File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /internal/sandboxes/{sandbox_id}/files/copy`

Copy

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `src` | `string` | Yes | Source path. |
| `dst` | `string` | Yes | Destination path. |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /internal/sandboxes/{sandbox_id}/files/mkdir`

Mkdir

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Directory path to create. |

**Responses:**

- **201**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `GET /internal/sandboxes/{sandbox_id}/files/read`

Read File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |
| `path` | query | `string` | Yes |  |
| `binary` | query | `boolean` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

### `POST /internal/sandboxes/{sandbox_id}/files/write`

Write File

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `sandbox_id` | path | `string` | Yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Absolute path in the sandbox filesystem. |
| `content` | `string` | Yes | File content to write. |

**Responses:**

- **201**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

## sandboxes

### `GET /sandboxes`

List Sandboxes

**Responses:**

- **200**: Successful Response

Type: `array[SandboxResponse]`

---

### `POST /sandboxes`

Create Sandbox

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sandbox_id` | `string | null` | No | Optional ID. Auto-generated if omitted. |
| `box_type` | `string` | No | Sandbox type: 'mem' or 'git'. (default: `mem`) |
| `repo_id` | `string | null` | No | Repository ID for git box (enables push/pull sync). |
| `timeout` | `integer | null` | No | Per-execution timeout override (seconds). |

**Responses:**

- **201**: Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sandbox_id` | `string` | Yes | Sandbox Id |
| `state` | `string` | Yes | State |
| `box_type` | `string` | Yes | Box Type |
| `created_at` | `number` | Yes | Created At |
| `last_used_at` | `number` | Yes | Last Used At |
| `age_seconds` | `number` | Yes | Age Seconds |
| `idle_seconds` | `number` | Yes | Idle Seconds |
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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sandbox_id` | `string` | Yes | Sandbox Id |
| `state` | `string` | Yes | State |
| `box_type` | `string` | Yes | Box Type |
| `created_at` | `number` | Yes | Created At |
| `last_used_at` | `number` | Yes | Last Used At |
| `age_seconds` | `number` | Yes | Age Seconds |
| `idle_seconds` | `number` | Yes | Idle Seconds |
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

- **204**: Successful Response
- **422**: Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

---

## system

### `GET /health`

Health

**Responses:**

- **200**: Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | No | Status (default: `ok`) |
| `total` | `integer` | No | Total (default: `0`) |
| `max_sandboxes` | `integer` | No | Max Sandboxes (default: `0`) |
| `available` | `integer` | No | Available (default: `0`) |
| `by_state` | `object` | No | By State (default: `{}`) |

---

### `GET /metrics`

Metrics

**Responses:**

- **200**: Successful Response

---

## Schemas

### CopyRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `src` | `string` | Yes | Source path. |
| `dst` | `string` | Yes | Destination path. |

### CreateSandboxRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sandbox_id` | `string | null` | No | Optional ID. Auto-generated if omitted. |
| `box_type` | `string` | No | Sandbox type: 'mem' or 'git'. (default: `mem`) |
| `repo_id` | `string | null` | No | Repository ID for git box (enables push/pull sync). |
| `timeout` | `integer | null` | No | Per-execution timeout override (seconds). |

### ExecuteRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | `string` | Yes | Code or shell command to execute. |
| `language` | `string` | No | 'python' or 'shell' (default). (default: `shell`) |
| `timeout` | `integer | null` | No | Optional timeout override. |

### ExecuteResponse

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stdout` | `string` | No | Stdout (default: ``) |
| `stderr` | `string` | No | Stderr (default: ``) |
| `exit_code` | `integer` | No | Exit Code (default: `0`) |

### FileContentResponse

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Path |
| `content` | `string | null` | No | Content |
| `exists` | `boolean` | No | Exists (default: `True`) |

### HTTPValidationError

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` | No | Detail |

### HealthResponse

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | No | Status (default: `ok`) |
| `total` | `integer` | No | Total (default: `0`) |
| `max_sandboxes` | `integer` | No | Max Sandboxes (default: `0`) |
| `available` | `integer` | No | Available (default: `0`) |
| `by_state` | `object` | No | By State (default: `{}`) |

### MkdirRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Directory path to create. |

### SandboxResponse

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sandbox_id` | `string` | Yes | Sandbox Id |
| `state` | `string` | Yes | State |
| `box_type` | `string` | Yes | Box Type |
| `created_at` | `number` | Yes | Created At |
| `last_used_at` | `number` | Yes | Last Used At |
| `age_seconds` | `number` | Yes | Age Seconds |
| `idle_seconds` | `number` | Yes | Idle Seconds |

### ValidationError

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `loc` | `array[string | integer]` | Yes | Location |
| `msg` | `string` | Yes | Message |
| `type` | `string` | Yes | Error Type |
| `input` | `any` | No | Input |
| `ctx` | `object` | No | Context |

### WriteFileRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | `string` | Yes | Absolute path in the sandbox filesystem. |
| `content` | `string` | Yes | File content to write. |
