# Git Operations

AgentBox's **GitBox** mode provides in-sandbox git operations powered by
[isomorphic-git](https://isomorphic-git.org/) running on Emscripten MemFS
inside the Chromium sandbox.

## Creating a GitBox sandbox

```python
sandbox = client.create_sandbox_sync(box_type="git", repo_id="my-project")
```

The `repo_id` is optional. If provided and the repo exists in storage,
files are automatically restored on sandbox creation.

## Supported commands

### Tier 1 — in-sandbox (isomorphic-git)

These run entirely inside the Chromium sandbox with no host interaction:

| Command | Description |
|---------|-------------|
| `git init` | Initialize a new repository |
| `git add <paths>` | Stage files for commit |
| `git commit -m "msg"` | Create a commit |
| `git log [--oneline]` | View commit history |
| `git status` | Show working tree status |
| `git branch [name]` | List or create branches |
| `git checkout <branch>` | Switch branches |
| `git diff` | Show unstaged changes |
| `git rm <paths>` | Remove files from tracking |
| `git reset --hard` | Reset working tree to HEAD |
| `git merge <branch>` | Merge a branch into current |

### Tier 3 — host-delegated

These require network/storage access and are delegated to the worker process:

| Command | Description |
|---------|-------------|
| `git push` | Sync repository to S3/MinIO storage |
| `git pull` | Fetch latest state from storage |

## Basic workflow

```bash
# Initialize
git init

# Create files
echo '# My Project' > README.md
mkdir -p src
echo 'print("hello")' > src/main.py

# Stage and commit
git add .
git commit -m "Initial commit"

# View history
git log --oneline
# a1b2c3d Initial commit
```

## Branching

```bash
# Create and switch to a feature branch
git branch feature
git checkout feature

# Make changes
echo 'def new_feature(): pass' >> src/main.py
git add .
git commit -m "Add feature"

# Switch back
git checkout main
```

## Merge and conflict resolution

```bash
# Merge feature branch into main
git merge feature
```

If there are conflicts, AgentBox writes **conflict markers** to the working
tree (like standard git) instead of aborting:

```
<<<<<<< HEAD
original code
=======
conflicting code
>>>>>>> feature
```

The merge state is preserved so you can resolve conflicts:

```bash
# After resolving conflicts in the files:
git merge --continue

# Or abort the merge:
git merge --abort
```

### Merge workflow example

```bash
# Setup: divergent branches
git init
echo "line 1" > file.txt
git add . && git commit -m "initial"

git branch feature
echo "line 1 from main" > file.txt
git add . && git commit -m "main change"

git checkout feature
echo "line 1 from feature" > file.txt
git add . && git commit -m "feature change"

git checkout main
git merge feature
# CONFLICT in file.txt

# View conflict markers
cat file.txt
# <<<<<<< HEAD
# line 1 from main
# =======
# line 1 from feature
# >>>>>>> feature

# Resolve
echo "line 1 merged" > file.txt
git add file.txt
git merge --continue
```

## Diff

```bash
# Show unstaged changes
git diff

# Output format: standard unified diff
# diff --git a/file.txt b/file.txt
# --- a/file.txt
# +++ b/file.txt
# @@ -1 +1 @@
# -old line
# +new line
```

## Push and pull (storage sync)

Push syncs the repository to persistent storage (S3, MinIO, or local files).
Pull fetches the latest state from storage.

```bash
# Push to storage
git push

# Pull latest (from another sandbox with same repo_id)
git pull
```

### How storage works

- Each file is stored individually in S3 for direct asset access
- `HEAD` SHA is tracked in `.agentbox-push-ref` in storage
- Push skips if HEAD matches last push (idempotent)
- Pull does a force checkout of the remote state
- Multiple sandboxes can share the same `repo_id`

### Storage backends

Configure via environment variables:

| Backend | Config |
|---------|--------|
| **S3** | `AGENTBOX_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| **MinIO** | `AGENTBOX_S3_ENDPOINT=http://minio:9000`, `AGENTBOX_S3_BUCKET` |
| **Local** | `AGENTBOX_LOCAL_STORAGE_PATH=/data/repos` |

## Auto-restore

When creating a GitBox with a `repo_id` that exists in storage, the
sandbox automatically pulls all files and checks out the working tree:

```python
# First session
sandbox1 = client.create_sandbox_sync(box_type="git", repo_id="demo")
sandbox1.execute_sync("echo hello > file.txt && git add . && git commit -m init", language="shell")
sandbox1.execute_sync("git push", language="shell")
sandbox1.destroy_sync()

# Second session — files are automatically restored
sandbox2 = client.create_sandbox_sync(box_type="git", repo_id="demo")
result = sandbox2.execute_sync("cat file.txt", language="shell")
print(result.stdout)  # "hello\n"
```

## Custom author

```bash
git commit -m "message" --author "Name <email@example.com>"
```

Or set via environment:

```bash
export GIT_AUTHOR_NAME="Agent"
export GIT_AUTHOR_EMAIL="agent@example.com"
```

## Limitations

- **No remote URLs** — `git clone`, `git remote` are not supported.
  Use `git push`/`git pull` with the storage backend instead.
- **No SSH** — all storage operations use HTTP/S3 protocols.
- **No submodules** — isomorphic-git doesn't support submodules.
- **Shallow operations** — full history is maintained in-memory but
  storage sync transfers all files (not git packfiles).

## See also

- [Sandbox overview](overview.md) — MemBox vs GitBox
- [Storage backends](../operations/storage.md) — S3/MinIO configuration
- [Shell builtins](builtins.md) — all shell commands
