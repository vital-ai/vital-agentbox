"""Pydantic request/response schemas for the AgentBox API."""

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Sandbox
# ------------------------------------------------------------------

class CreateSandboxRequest(BaseModel):
    sandbox_id: str | None = Field(None, description="Optional ID. Auto-generated if omitted.")
    box_type: str = Field("mem", description="Sandbox type: 'mem' or 'git'.")
    repo_id: str | None = Field(None, description="Repository ID for git box (enables push/pull sync).")
    timeout: int | None = Field(None, description="Per-execution timeout override (seconds).")
    engine: str | None = Field(None, description="Execution engine: 'pyodide' (default) or 'agentcore' (future).")
    s3_credentials: dict | None = Field(None, description="Caller-provided S3 credentials (Mode 3: path_credentials).")


class SandboxResponse(BaseModel):
    sandbox_id: str
    state: str
    box_type: str
    engine: str = "pyodide"
    created_at: float
    last_used_at: float
    age_seconds: float
    idle_seconds: float


# ------------------------------------------------------------------
# Execute
# ------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    code: str = Field(..., description="Code or shell command to execute.")
    language: str = Field("shell", description="'python' or 'shell' (default).")
    timeout: int | None = Field(None, description="Optional timeout override.")


class ExecuteResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


# ------------------------------------------------------------------
# Files
# ------------------------------------------------------------------

class WriteFileRequest(BaseModel):
    path: str = Field(..., description="Absolute path in the sandbox filesystem.")
    content: str = Field(..., description="File content to write.")


class MkdirRequest(BaseModel):
    path: str = Field(..., description="Directory path to create.")


class CopyRequest(BaseModel):
    src: str = Field(..., description="Source path.")
    dst: str = Field(..., description="Destination path.")


class FileContentResponse(BaseModel):
    path: str
    content: str | None = None
    exists: bool = True


# ------------------------------------------------------------------
# Health / Metrics
# ------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    total: int = 0
    max_sandboxes: int = 0
    available: int = 0
    by_state: dict[str, int] = {}
