# Files and MemFS

All sandbox file operations run against **MemFS** — Emscripten's in-memory
filesystem inside the Chromium page. There is no real disk I/O.

## How MemFS works

MemFS is Emscripten's virtual filesystem, backed by JavaScript objects in
the Chromium page's memory. It supports standard POSIX operations:
directories, files, symlinks, permissions (simulated).

```
┌─────────────────────────────┐
│  Chromium Page               │
│  ┌────────────────────────┐ │
│  │  Emscripten MemFS      │ │
│  │  /                      │ │
│  │  ├── workspace/         │ │
│  │  │   ├── src/           │ │
│  │  │   │   └── main.py   │ │
│  │  │   └── README.md     │ │
│  │  └── tmp/               │ │
│  └────────────────────────┘ │
└─────────────────────────────┘
```

Both Python (Pyodide) and shell builtins operate on the same MemFS
instance. A file written by Python is immediately visible to shell
commands and vice versa.

## File operations via SDK

```python
# Write
await sandbox.write_file("/data.txt", "hello world")

# Read
content = await sandbox.read_file("/data.txt")  # "hello world"

# Read returns None if file doesn't exist
content = await sandbox.read_file("/missing.txt")  # None

# List directory
entries = await sandbox.list_files("/")
# [{"name": "data.txt", "type": "file"}, {"name": "workspace", "type": "dir"}, ...]

# Create directory (mkdir -p)
await sandbox.mkdir("/workspace/src/utils")

# Remove file
await sandbox.remove_file("/data.txt")

# Copy file
await sandbox.copy_file("/src.txt", "/dst.txt")
```

## File operations via shell

```bash
# Create files
echo "hello" > /file.txt
cat << 'EOF' > /config.json
{"key": "value"}
EOF

# Read files
cat /file.txt
head -n 5 /file.txt
tail -n 10 /log.txt

# Edit files (LLM-friendly)
edit /file.txt --view
edit /file.txt --old "old text" --new "new text"

# Directory operations
mkdir -p /workspace/src
ls -la /workspace
find /workspace -name "*.py"

# Search
grep -rn "TODO" /workspace/src
```

## File operations via Python

```python
# Standard Python I/O works against MemFS
with open("/data.csv", "w") as f:
    f.write("name,age\nAlice,30\nBob,25\n")

with open("/data.csv") as f:
    for line in f:
        print(line.strip())

# os module works
import os
os.makedirs("/workspace/output", exist_ok=True)
os.listdir("/workspace")
os.path.exists("/data.csv")  # True
```

## File transfer (host ↔ sandbox)

Files are transferred between the host Python process and the Chromium
sandbox via base64 encoding through `page.evaluate()`.

```
Host Process              Chromium Page
     │                         │
     │  base64-encoded file    │
     ├────────────────────────►│  decode → write to MemFS
     │                         │
     │  base64-encoded file    │
     │◄────────────────────────┤  read from MemFS → encode
     │                         │
```

### Performance

- ~94ms round-trip for 1 MB file (encode + transfer + decode)
- Text files: UTF-8 encoded
- Binary files: base64 encoded transparently

### Upload files (host → sandbox)

Via the REST API:

```bash
curl -X POST http://localhost:8090/sandboxes/{id}/files/write \
  -H "Content-Type: application/json" \
  -d '{"path": "/data.txt", "content": "file contents"}'
```

Via the SDK:

```python
await sandbox.write_file("/data.txt", "file contents")
```

### Download files (sandbox → host)

Via the REST API:

```bash
curl http://localhost:8090/sandboxes/{id}/files/read?path=/data.txt
# {"path": "/data.txt", "content": "file contents", "exists": true}
```

Via the SDK:

```python
content = await sandbox.read_file("/data.txt")
```

### Binary files

Binary files (images, PDFs, etc.) are automatically detected by file
extension and transferred as base64. The detection uses common extensions:

- Images: `.png`, `.jpg`, `.gif`, `.bmp`, `.webp`, `.svg`
- Documents: `.pdf`
- Archives: `.zip`, `.tar`, `.gz`
- Data: `.pkl`, `.npy`, `.npz`

## File size limits

MemFS is bounded by the Chromium page's JavaScript heap. Practical limits:

- **Individual file**: ~100 MB (depends on available heap)
- **Total MemFS**: ~1–2 GB (WASM linear memory limit)
- **Transfer via API**: No hard limit, but large files increase latency

For large datasets, consider processing in chunks or using GitBox with
S3 storage for persistence.

## Ephemeral vs persistent

| Mode | Persistence | Details |
|------|-------------|---------|
| **MemBox** | None | Files lost when sandbox is destroyed |
| **GitBox** | Via git push | Files persisted to S3/MinIO on push |
| **GitBox auto-sync** | On every commit | Files automatically pushed after each commit |

## See also

- [Sandbox overview](overview.md) — MemBox vs GitBox
- [Shell builtins](builtins.md) — file manipulation commands
- [Python execution](python.md) — Python file I/O
- [Storage backends](../operations/storage.md) — persistent storage for GitBox
