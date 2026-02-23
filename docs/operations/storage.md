# Storage Backends

GitBox sandboxes can persist repositories to external storage. When a
sandbox is created with a `repo_id`, files are automatically restored
from storage. On `git push`, files are synced back.

## Supported backends

| Backend | Use case | Config |
|---------|----------|--------|
| **S3** | Production (AWS) | `AGENTBOX_GIT_STORE=s3` |
| **MinIO** | Self-hosted / local dev | `AGENTBOX_GIT_STORE=s3` + custom endpoint |
| **Local files** | Development only | `AGENTBOX_GIT_STORE=local` |

## S3

```bash
AGENTBOX_GIT_STORE=s3
AGENTBOX_GIT_S3_BUCKET=agentbox-repos
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

### How files are stored

Each file is stored individually as an S3 object:

```
s3://agentbox-repos/
  {tenant}/{repo_id}/
    README.md
    src/main.py
    src/utils.py
    .agentbox-push-ref     # HEAD SHA of last push
```

This design allows:
- Direct access to individual files (no need to unpack archives)
- Incremental sync (only changed files)
- Easy browsing via S3 console or CLI

### Push tracking

The file `.agentbox-push-ref` stores the HEAD SHA of the last push.
Push is idempotent — if HEAD matches the stored ref, the push is skipped.

### Tenant scoping

When JWT auth is enabled, the orchestrator prefixes `repo_id` with the
tenant's `sub` claim:

```
s3://agentbox-repos/{tenant_sub}/{repo_id}/...
```

This prevents cross-tenant data access. The `repo_id` is validated to
contain only safe characters (alphanumeric, hyphens, underscores, dots, @).

## MinIO

MinIO is S3-compatible. Use the same S3 config with a custom endpoint:

```bash
AGENTBOX_GIT_STORE=s3
AGENTBOX_GIT_S3_BUCKET=agentbox-repos
AGENTBOX_GIT_S3_ENDPOINT=http://minio:9000
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
```

The Docker Compose stack includes MinIO with auto-created bucket:

```bash
docker compose up
# MinIO API:     http://localhost:9100
# MinIO Console: http://localhost:9101 (minioadmin / minioadmin)
```

## Local files

For development only. Files are stored on the worker's local filesystem:

```bash
AGENTBOX_GIT_STORE=local
AGENTBOX_LOCAL_STORAGE_PATH=/data/repos
```

Structure:

```
/data/repos/
  {repo_id}/
    README.md
    src/main.py
```

**Warning**: Local storage is not shared between workers. Only use for
single-worker development.

## Auto-restore

When creating a GitBox with an existing `repo_id`:

1. Worker checks if `repo_id` exists in storage
2. If yes, all files are downloaded into MemFS
3. A git working tree is checked out
4. The sandbox is ready with full repo contents

```python
# Session 1: create and push
sandbox = client.create_sandbox_sync(box_type="git", repo_id="demo")
sandbox.execute_sync("echo hello > file.txt && git add . && git commit -m init", language="shell")
sandbox.execute_sync("git push", language="shell")
sandbox.destroy_sync()

# Session 2: auto-restored
sandbox = client.create_sandbox_sync(box_type="git", repo_id="demo")
result = sandbox.execute_sync("cat file.txt", language="shell")
# stdout: "hello\n"
```

## Auto-sync

By default, every `git commit` automatically triggers a push to storage.
This ensures data is persisted without requiring explicit `git push`.

## Multi-sandbox collaboration

Multiple sandboxes can share the same `repo_id`:

```python
# Sandbox A pushes
sandbox_a.execute_sync("echo v2 > file.txt && git add . && git commit -m v2", language="shell")

# Sandbox B pulls the changes
sandbox_b.execute_sync("git pull", language="shell")
result = sandbox_b.execute_sync("cat file.txt", language="shell")
# stdout: "v2\n"
```

`git pull` does a force checkout of the remote state. It's designed for
sequential workflows, not concurrent editing.

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTBOX_GIT_STORE` | — | Storage backend: `s3` or `local` |
| `AGENTBOX_GIT_S3_BUCKET` | — | S3 bucket name |
| `AGENTBOX_GIT_S3_ENDPOINT` | — | Custom S3 endpoint (for MinIO) |
| `AGENTBOX_GIT_S3_REGION` | `us-east-1` | S3 region |
| `AGENTBOX_LOCAL_STORAGE_PATH` | — | Local storage directory |
| `AWS_ACCESS_KEY_ID` | — | AWS/MinIO access key |
| `AWS_SECRET_ACCESS_KEY` | — | AWS/MinIO secret key |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region |

## See also

- [Git operations](../sandbox/git.md) — git commands in the sandbox
- [Docker](docker.md) — docker-compose with MinIO
- [Scaling](scaling.md) — multi-worker deployment
