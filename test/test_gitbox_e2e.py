"""GitBox E2E test: git operations + S3 sync through the orchestrator.

Prerequisites:
    docker compose up --build -d
    Orchestrator at http://localhost:8090
    MinIO at http://localhost:9100

Tests:
     1. Create git sandbox, verify git status
     2. git push before any commits -> "Everything up-to-date"
     3. Create files, git add, git commit
     4. git log shows commit
     5. git push syncs to MinIO
     6. git push again (no new commits) -> "Everything up-to-date"
     7. git push with args -> rejected
     8. git clone -> "already in a git repository"
     9. Verify files in MinIO
    10. git reset --hard after modifying a file -> restores to last commit
    11. Second commit + push
    12. git pull with args -> rejected
    13. Destroy sandbox
    14. Create sandbox 2 with same repo_id -> auto-restore
    15. Verify files + git log (both commits)
    16. git pull on sandbox 2 -> "Already up to date"
    17. Create sandbox 3 with same repo_id (concurrent)
    18. Commit on sandbox 3 + push
    19. git fetch on sandbox 2 -> pulls objects without checkout
    20. git pull on sandbox 2 -> gets latest
    21. Cleanup
"""

import asyncio
import sys
import uuid

import httpx
import boto3
from botocore.config import Config as BotoConfig


ORCHESTRATOR_URL = "http://localhost:8090"
MINIO_ENDPOINT = "http://localhost:9100"
MINIO_BUCKET = "agentbox-repos"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
S3_PREFIX = "repos/"


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _list_s3_files(s3, repo_id):
    files = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Prefix=f"{S3_PREFIX}{repo_id}/"):
        for obj in page.get("Contents", []):
            files.append(obj["Key"])
    return files


async def _exec(client, sandbox_id, code):
    """Execute a shell command and return (exit_code, stdout, stderr)."""
    r = await client.post(f"/sandboxes/{sandbox_id}/execute", json={
        "code": code,
        "language": "shell",
    })
    if r.status_code != 200:
        return -1, "", f"HTTP {r.status_code}: {r.text}"
    result = r.json()
    return result.get("exit_code", -1), result.get("stdout", ""), result.get("stderr", "")


async def main():
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  \u2713 {name}")
        else:
            failed += 1
            print(f"  \u2717 {name}")
            if detail:
                print(f"      {detail}")

    test_id = uuid.uuid4().hex[:8]
    repo_id = f"e2e-gitbox-{test_id}"
    sandbox_ids = []

    print("=" * 60)
    print(f"GITBOX E2E TEST (repo_id={repo_id})")
    print("=" * 60)

    s3 = _s3_client()

    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=60.0) as client:

        # ========== 1. Create git sandbox ==========
        print("\n--- 1. Create Git Sandbox ---")
        r = await client.post("/sandboxes", json={
            "box_type": "git",
            "repo_id": repo_id,
        })
        check("create git sandbox", r.status_code == 200, f"got {r.status_code}: {r.text}")
        sb1 = r.json().get("sandbox_id", "unknown") if r.status_code == 200 else None
        sandbox_ids.append(sb1)
        print(f"      sandbox_id = {sb1}")

        if not sb1 or sb1 == "unknown":
            print("\n  FATAL: Could not create sandbox. Aborting.")
            return False
        await asyncio.sleep(2)

        ec, out, err = await _exec(client, sb1, "git status")
        check("git status works", ec == 0, f"ec={ec} out={out[:100]} err={err[:100]}")
        check("git status shows branch", "branch" in out.lower() or "nothing to commit" in out.lower(), out[:200])

        # ========== 2. git push before commits ==========
        print("\n--- 2. Git Push (no commits) ---")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git push")
        check("push no commits ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        check("push no commits up-to-date", "Everything up-to-date" in out, out[:200])

        # ========== 3. Create files + commit ==========
        print("\n--- 3. Create Files + Commit ---")
        await _exec(client, sb1, 'echo "# E2E GitBox Test" > /workspace/README.md')
        await _exec(client, sb1, 'echo "print(42)" > /workspace/main.py')
        ec, out, err = await _exec(client, sb1, "cd /workspace && git add README.md main.py")
        check("git add", ec == 0, f"ec={ec} err={err[:100]}")
        ec, out, err = await _exec(client, sb1, 'cd /workspace && git commit -m "Initial commit"')
        check("git commit", ec == 0, f"ec={ec} err={err[:100]}")
        check("commit output", "Initial commit" in out or "main" in out.lower(), out[:200])

        # ========== 4. Git log ==========
        print("\n--- 4. Git Log ---")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git log --oneline")
        check("git log", ec == 0, f"ec={ec} err={err[:100]}")
        check("log shows commit", "Initial commit" in out, out[:200])

        # ========== 5. Git push ==========
        print("\n--- 5. Git Push ---")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git push")
        check("git push ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        check("git push synced", "Pushed" in out and "files" in out, out[:200])

        # ========== 6. Git push again (no new commits) ==========
        print("\n--- 6. Git Push (duplicate) ---")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git push")
        check("push dup ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        check("push dup up-to-date", "Everything up-to-date" in out, out[:200])

        # ========== 7. Git push with args -> rejected ==========
        print("\n--- 7. Git Push With Args ---")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git push origin main")
        check("push args rejected", ec == 1, f"ec={ec}")
        check("push args error msg", "arguments not supported" in err, err[:200])

        # ========== 8. Git clone -> error ==========
        print("\n--- 8. Git Clone ---")
        ec, out, err = await _exec(client, sb1, "git clone some-repo")
        check("clone rejected", ec == 1, f"ec={ec}")
        check("clone error msg", "already in a git repository" in err, err[:200])

        # ========== 9. Verify MinIO ==========
        print("\n--- 9. Verify MinIO ---")
        s3_files = _list_s3_files(s3, repo_id)
        check("s3 has files", len(s3_files) > 0, f"got {len(s3_files)} files")
        check("s3 has README.md", any("README.md" in f for f in s3_files), str(s3_files[:10]))
        check("s3 has main.py", any("main.py" in f for f in s3_files), str(s3_files[:10]))
        check("s3 has .git objects", any(".git/" in f for f in s3_files), str(s3_files[:10]))
        check("s3 has push-ref", any(".agentbox-push-ref" in f for f in s3_files), str(s3_files[:10]))
        print(f"      S3 files: {len(s3_files)} total")

        # ========== 10. Git reset --hard ==========
        print("\n--- 10. Git Reset --hard ---")
        await _exec(client, sb1, 'echo "MODIFIED" > /workspace/README.md')
        ec, out, err = await _exec(client, sb1, "cat /workspace/README.md")
        check("file modified", "MODIFIED" in out, out[:200])

        ec, out, err = await _exec(client, sb1, "cd /workspace && git reset --hard HEAD")
        check("reset --hard ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        check("reset --hard output", "HEAD is now at" in out, out[:200])

        ec, out, err = await _exec(client, sb1, "cat /workspace/README.md")
        check("file restored", "E2E GitBox Test" in out, out[:200])
        check("modified gone", "MODIFIED" not in out, out[:200])

        # ========== 11. Second commit + push ==========
        print("\n--- 11. Second Commit + Push ---")
        await _exec(client, sb1, 'echo "v2" > /workspace/version.txt')
        ec, out, err = await _exec(client, sb1, "cd /workspace && git add version.txt")
        check("git add v2", ec == 0, f"ec={ec} err={err[:100]}")
        ec, out, err = await _exec(client, sb1, 'cd /workspace && git commit -m "Add version"')
        check("git commit v2", ec == 0, f"ec={ec} err={err[:100]}")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git push")
        check("git push v2", ec == 0 and "Pushed" in out, f"ec={ec} out={out[:100]} err={err[:100]}")

        # ========== 12. Git pull with args -> rejected ==========
        print("\n--- 12. Git Pull With Args ---")
        ec, out, err = await _exec(client, sb1, "cd /workspace && git pull origin main")
        check("pull args rejected", ec == 1, f"ec={ec}")
        check("pull args error msg", "arguments not supported" in err, err[:200])

        # ========== 13. Destroy sandbox 1 ==========
        print("\n--- 13. Destroy Sandbox 1 ---")
        r = await client.delete(f"/sandboxes/{sb1}")
        check("destroy sb1", r.status_code == 200, f"got {r.status_code}")

        # ========== 14. Create sandbox 2 (auto-restore) ==========
        print("\n--- 14. Create Sandbox 2 (auto-restore) ---")
        r = await client.post("/sandboxes", json={
            "box_type": "git",
            "repo_id": repo_id,
        })
        check("create sb2", r.status_code == 200, f"got {r.status_code}: {r.text}")
        sb2 = r.json().get("sandbox_id", "unknown") if r.status_code == 200 else None
        sandbox_ids.append(sb2)
        print(f"      sandbox_id_2 = {sb2}")

        if not sb2 or sb2 == "unknown":
            print("\n  FATAL: Could not create sandbox 2. Aborting.")
            return False
        await asyncio.sleep(2)

        # ========== 15. Verify auto-restore ==========
        print("\n--- 15. Verify Auto-Restore ---")
        ec, out, err = await _exec(client, sb2, "cat /workspace/README.md")
        check("README restored", "E2E GitBox Test" in out, out[:200])
        ec, out, err = await _exec(client, sb2, "cat /workspace/main.py")
        check("main.py restored", "print(42)" in out, out[:200])
        ec, out, err = await _exec(client, sb2, "cat /workspace/version.txt")
        check("version.txt restored", "v2" in out, out[:200])
        ec, out, err = await _exec(client, sb2, "cd /workspace && git log --oneline")
        check("log has both commits", "Initial commit" in out and "Add version" in out, out[:200])

        # ========== 16. Git pull (already up to date) ==========
        print("\n--- 16. Git Pull (up to date) ---")
        ec, out, err = await _exec(client, sb2, "cd /workspace && git pull")
        check("pull up-to-date ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        check("pull up-to-date msg", "Already up to date" in out, out[:200])

        # ========== 17. Create sandbox 3 (concurrent) ==========
        print("\n--- 17. Create Sandbox 3 (concurrent) ---")
        r = await client.post("/sandboxes", json={
            "box_type": "git",
            "repo_id": repo_id,
        })
        check("create sb3", r.status_code == 200, f"got {r.status_code}: {r.text}")
        sb3 = r.json().get("sandbox_id", "unknown") if r.status_code == 200 else None
        sandbox_ids.append(sb3)
        print(f"      sandbox_id_3 = {sb3}")

        if not sb3 or sb3 == "unknown":
            print("\n  FATAL: Could not create sandbox 3. Aborting.")
            return False
        await asyncio.sleep(2)

        # ========== 18. Commit on sb3 + push ==========
        print("\n--- 18. Commit on Sandbox 3 + Push ---")
        await _exec(client, sb3, 'echo "from sandbox 3" > /workspace/sb3.txt')
        ec, out, err = await _exec(client, sb3, "cd /workspace && git add sb3.txt")
        check("sb3 git add", ec == 0, f"ec={ec} err={err[:100]}")
        ec, out, err = await _exec(client, sb3, 'cd /workspace && git commit -m "From sandbox 3"')
        check("sb3 git commit", ec == 0, f"ec={ec} err={err[:100]}")
        ec, out, err = await _exec(client, sb3, "cd /workspace && git push")
        check("sb3 git push", ec == 0 and "Pushed" in out, f"ec={ec} out={out[:100]} err={err[:100]}")

        # ========== 19. Git fetch on sb2 ==========
        print("\n--- 19. Git Fetch on Sandbox 2 ---")
        ec, out, err = await _exec(client, sb2, "cd /workspace && git fetch")
        check("fetch ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        # fetch does not update working tree, sb3.txt should NOT exist yet
        ec, out, err = await _exec(client, sb2, "cat /workspace/sb3.txt")
        check("sb3.txt not in worktree after fetch", ec != 0 or "from sandbox 3" not in out,
              f"ec={ec} out={out[:100]}")

        # ========== 20. Git pull on sb2 ==========
        print("\n--- 20. Git Pull on Sandbox 2 ---")
        ec, out, err = await _exec(client, sb2, "cd /workspace && git pull")
        check("pull ec=0", ec == 0, f"ec={ec} err={err[:100]}")
        check("pull got files", "Pulled" in out and "files" in out, out[:200])
        ec, out, err = await _exec(client, sb2, "cat /workspace/sb3.txt")
        check("sb3.txt now in worktree", "from sandbox 3" in out, out[:200])

        # ========== 21. Cleanup ==========
        print("\n--- 21. Cleanup ---")
        for sid in sandbox_ids:
            if sid and sid != "unknown":
                r = await client.delete(f"/sandboxes/{sid}")
        check("destroyed all sandboxes", True)

        s3_files = _list_s3_files(s3, repo_id)
        for key in s3_files:
            s3.delete_object(Bucket=MINIO_BUCKET, Key=key)
        check("cleaned up MinIO", True)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"GITBOX E2E: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
