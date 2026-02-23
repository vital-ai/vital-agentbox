"""
Tier 3 host-delegated command: boxcp

Copy files between the sandbox (MemFS) and external services.

Usage:
    boxcp s3://bucket/key /local/path          # import from S3
    boxcp /local/path s3://bucket/key          # export to S3
    boxcp local:///data/shared/file /dest      # import from host (restricted)
    boxcp /src local:///data/shared/file       # export to host (restricted)

URI schemes:
    /path           — MemFS (current sandbox)
    s3://bucket/key — AWS S3 or S3-compatible (MinIO)
    local://path    — Host filesystem (restricted to allowlisted dirs)

Security:
    - Credentials (AWS keys) stored on host — never in sandbox.
    - local:// restricted to AGENTBOX_BOXCP_LOCAL_ALLOW dirs.
    - Rate limits and size limits enforced.
"""

import base64
import os
from pathlib import Path, PurePosixPath

from agentbox.box.shell.environment import ShellResult


# Max file size for a single boxcp transfer (default 100MB)
MAX_FILE_SIZE = int(os.environ.get("AGENTBOX_BOXCP_MAX_SIZE", str(100 * 1024 * 1024)))

# Allowlisted host directories for local:// scheme (comma-separated)
LOCAL_ALLOW = [
    p.strip() for p in
    os.environ.get("AGENTBOX_BOXCP_LOCAL_ALLOW", "").split(",")
    if p.strip()
]


# ---------------------------------------------------------------------------
# URI parsing
# ---------------------------------------------------------------------------

def _parse_uri(uri: str) -> tuple[str, str]:
    """Parse a URI into (scheme, path).

    Returns:
        ("memfs", "/path")       for bare paths
        ("s3", "bucket/key")     for s3://bucket/key
        ("local", "/host/path")  for local:///host/path
    """
    if uri.startswith("s3://"):
        return "s3", uri[5:]
    if uri.startswith("local://"):
        return "local", uri[8:]
    # Bare path = MemFS
    return "memfs", uri


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

async def _read_memfs(memfs, env, path: str) -> tuple[bytes | None, str | None]:
    """Read a file from MemFS. Returns (data, error)."""
    resolved = env.resolve_path(path)
    b64 = await memfs.page.evaluate("""([path]) => {
        const FS = window.pyodide._module.FS;
        try {
            const data = FS.readFile(path);
            let binary = '';
            for (let i = 0; i < data.length; i++) {
                binary += String.fromCharCode(data[i]);
            }
            return btoa(binary);
        } catch(e) { return null; }
    }""", [resolved])
    if b64 is None:
        return None, f"boxcp: {path}: No such file\n"
    data = base64.b64decode(b64)
    if len(data) > MAX_FILE_SIZE:
        return None, f"boxcp: {path}: File too large ({len(data)} bytes, max {MAX_FILE_SIZE})\n"
    return data, None


async def _write_memfs(memfs, env, path: str, data: bytes) -> str | None:
    """Write a file to MemFS. Returns error string or None."""
    resolved = env.resolve_path(path)
    b64 = base64.b64encode(data).decode("ascii")
    ok = await memfs.page.evaluate("""([path, b64]) => {
        const FS = window.pyodide._module.FS;
        try {
            const parts = path.split('/').filter(Boolean);
            let current = '';
            for (let i = 0; i < parts.length - 1; i++) {
                current += '/' + parts[i];
                try { FS.mkdir(current); } catch(e) {}
            }
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }
            FS.writeFile(path, bytes);
            return true;
        } catch(e) { return false; }
    }""", [resolved, b64])
    if not ok:
        return f"boxcp: failed to write {path}\n"
    return None


def _s3_client():
    """Get a boto3 S3 client using env vars for configuration."""
    try:
        import boto3
    except ImportError:
        return None, "boxcp: boto3 not installed. pip install boto3\n"

    kwargs = {}
    endpoint = os.environ.get("AGENTBOX_S3_ENDPOINT") or os.environ.get("AGENTBOX_GIT_S3_ENDPOINT")
    region = os.environ.get("AGENTBOX_S3_REGION") or os.environ.get("AGENTBOX_GIT_S3_REGION")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs), None


def _parse_s3_path(path: str) -> tuple[str, str] | tuple[None, None]:
    """Parse 'bucket/key' into (bucket, key)."""
    parts = path.split("/", 1)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None, None
    return parts[0], parts[1]


async def _read_s3(path: str) -> tuple[bytes | None, str | None]:
    """Read a file from S3. Returns (data, error)."""
    bucket, key = _parse_s3_path(path)
    if not bucket:
        return None, f"boxcp: invalid S3 path: s3://{path} (expected s3://bucket/key)\n"

    client, err = _s3_client()
    if err:
        return None, err

    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
        if len(data) > MAX_FILE_SIZE:
            return None, f"boxcp: s3://{path}: File too large ({len(data)} bytes, max {MAX_FILE_SIZE})\n"
        return data, None
    except client.exceptions.NoSuchKey:
        return None, f"boxcp: s3://{path}: Not found\n"
    except Exception as e:
        return None, f"boxcp: s3://{path}: {e}\n"


async def _write_s3(path: str, data: bytes) -> str | None:
    """Write data to S3. Returns error string or None."""
    bucket, key = _parse_s3_path(path)
    if not bucket:
        return f"boxcp: invalid S3 path: s3://{path} (expected s3://bucket/key)\n"

    client, err = _s3_client()
    if err:
        return err

    try:
        client.put_object(Bucket=bucket, Key=key, Body=data)
        return None
    except Exception as e:
        return f"boxcp: s3://{path}: {e}\n"


def _validate_local_path(path: str) -> str | None:
    """Validate a local:// path against the allowlist. Returns error or None."""
    if not LOCAL_ALLOW:
        return "boxcp: local:// not configured. Set AGENTBOX_BOXCP_LOCAL_ALLOW.\n"

    resolved = str(Path(path).resolve())
    for allowed in LOCAL_ALLOW:
        allowed_resolved = str(Path(allowed).resolve())
        if resolved == allowed_resolved or resolved.startswith(allowed_resolved + os.sep):
            return None

    return f"boxcp: {path}: not in allowlisted directories\n"


async def _read_local(path: str) -> tuple[bytes | None, str | None]:
    """Read a file from the host filesystem. Returns (data, error)."""
    err = _validate_local_path(path)
    if err:
        return None, err

    p = Path(path)
    if not p.is_file():
        return None, f"boxcp: local://{path}: No such file\n"

    data = p.read_bytes()
    if len(data) > MAX_FILE_SIZE:
        return None, f"boxcp: local://{path}: File too large ({len(data)} bytes, max {MAX_FILE_SIZE})\n"
    return data, None


async def _write_local(path: str, data: bytes) -> str | None:
    """Write data to the host filesystem. Returns error or None."""
    err = _validate_local_path(path)
    if err:
        return err

    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return None
    except Exception as e:
        return f"boxcp: local://{path}: {e}\n"


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

async def host_boxcp(args, stdin, env, memfs):
    """boxcp: copy files between sandbox and external services."""
    if len(args) < 2:
        return ShellResult(
            exit_code=1,
            stderr=(
                "Usage: boxcp <src> <dst>\n"
                "  src/dst can be: /memfs/path, s3://bucket/key, local:///host/path\n"
            ),
        )

    src_uri = args[0]
    dst_uri = args[1]

    src_scheme, src_path = _parse_uri(src_uri)
    dst_scheme, dst_path = _parse_uri(dst_uri)

    # Both can't be external
    if src_scheme != "memfs" and dst_scheme != "memfs":
        return ShellResult(
            exit_code=1,
            stderr="boxcp: at least one of src/dst must be a sandbox path\n",
        )

    # Read source
    if src_scheme == "memfs":
        data, err = await _read_memfs(memfs, env, src_path)
    elif src_scheme == "s3":
        data, err = await _read_s3(src_path)
    elif src_scheme == "local":
        data, err = await _read_local(src_path)
    else:
        return ShellResult(exit_code=1, stderr=f"boxcp: unsupported scheme: {src_scheme}://\n")

    if err:
        return ShellResult(exit_code=1, stderr=err)

    # Write destination
    if dst_scheme == "memfs":
        err = await _write_memfs(memfs, env, dst_path, data)
    elif dst_scheme == "s3":
        err = await _write_s3(dst_path, data)
    elif dst_scheme == "local":
        err = await _write_local(dst_path, data)
    else:
        return ShellResult(exit_code=1, stderr=f"boxcp: unsupported scheme: {dst_scheme}://\n")

    if err:
        return ShellResult(exit_code=1, stderr=err)

    return ShellResult(
        exit_code=0,
        stdout=f"{src_uri} -> {dst_uri} ({len(data)} bytes)\n",
    )
