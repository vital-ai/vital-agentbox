"""
End-to-end test against the full docker-compose stack.

Prerequisites:
    docker compose up --build -d

Tests hit the orchestrator at localhost:8000 and MinIO at localhost:9100.
Covers: health, worker registration, sandbox lifecycle, code execution,
file operations, S3 storage backend, and admin endpoints.
"""

import asyncio
import os
import time
import uuid

import httpx

ORCHESTRATOR_URL = "http://localhost:8090"
MINIO_ENDPOINT = "http://localhost:9100"
MINIO_BUCKET = "agentbox-repos"


async def main():
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            if detail:
                print(f"      {detail}")

    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=30.0) as client:

        print("=" * 60)
        print("E2E TEST: docker-compose stack")
        print("=" * 60)

        # --- Health ---
        print("\n--- Orchestrator Health ---")
        r = await client.get("/health")
        check("health status 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("redis connected", data.get("redis") == "connected", data)
        check("workers registered", data.get("workers_total", 0) >= 1,
              f"workers_total={data.get('workers_total')}")
        check("status healthy", data.get("status") == "healthy")

        # --- Metrics ---
        print("\n--- Metrics ---")
        r = await client.get("/metrics")
        check("metrics status 200", r.status_code == 200)
        metrics = r.json()
        check("metrics has workers_total", "workers_total" in metrics)
        check("metrics has sandboxes_capacity", "sandboxes_capacity" in metrics)

        # --- Worker List ---
        print("\n--- Worker List ---")
        r = await client.get("/workers")
        check("list workers 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        if r.status_code == 200:
            data = r.json()
            workers = data.get("workers", [])
            check("at least 1 worker", len(workers) >= 1, f"got {len(workers)}")
            if workers:
                w = workers[0]
                check("worker has endpoint", "endpoint" in w)
                check("worker has worker_id", "worker_id" in w)

        # --- Sandbox Lifecycle ---
        print("\n--- Sandbox Create ---")
        r = await client.post("/sandboxes", json={
            "box_type": "mem",
        })
        check("create sandbox 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        sandbox_id = r.json().get("sandbox_id", "unknown") if r.status_code == 200 else "unknown"
        print(f"      sandbox_id = {sandbox_id}")

        # Give it a moment to spin up
        await asyncio.sleep(2)

        # Get sandbox
        print("\n--- Sandbox Get ---")
        r = await client.get(f"/sandboxes/{sandbox_id}")
        check("get sandbox 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        if r.status_code == 200:
            sb = r.json()
            check("sandbox id matches", sb.get("sandbox_id") == sandbox_id or sb.get("id") == sandbox_id,
                  f"got {sb}")

        # List sandboxes
        r = await client.get("/sandboxes")
        check("list sandboxes 200", r.status_code == 200)
        if r.status_code == 200:
            sbs = r.json()
            sandbox_list = sbs.get("sandboxes", []) if isinstance(sbs, dict) else sbs
            check("sandbox in list", any(
                s.get("sandbox_id") == sandbox_id or s.get("id") == sandbox_id
                for s in sandbox_list
            ), f"got {sbs}")

        # --- Code Execution ---
        print("\n--- Execute Python ---")
        r = await client.post(f"/sandboxes/{sandbox_id}/execute", json={
            "code": "print(2 + 2)",
            "language": "python",
        })
        check("execute python 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        if r.status_code == 200:
            result = r.json()
            stdout = result.get("stdout", result.get("output", ""))
            check("python output is 4", "4" in str(stdout), f"got {result}")

        print("\n--- Execute Shell ---")
        r = await client.post(f"/sandboxes/{sandbox_id}/execute", json={
            "code": "echo hello-e2e",
            "language": "shell",
        })
        check("execute shell 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        if r.status_code == 200:
            result = r.json()
            stdout = result.get("stdout", result.get("output", ""))
            check("shell output", "hello-e2e" in str(stdout), f"got {result}")

        # --- File Operations ---
        print("\n--- File Mkdir ---")
        r = await client.post(f"/sandboxes/{sandbox_id}/files/mkdir", json={
            "path": "/workspace",
        })
        check("mkdir ok", r.status_code in (200, 201), f"got {r.status_code}: {r.text}")

        print("\n--- File Write ---")
        r = await client.post(f"/sandboxes/{sandbox_id}/files/write", json={
            "path": "/workspace/test.txt",
            "content": "hello from e2e test",
        })
        check("write file ok", r.status_code in (200, 201), f"got {r.status_code}: {r.text}")

        print("\n--- File Read ---")
        r = await client.get(f"/sandboxes/{sandbox_id}/files/read", params={
            "path": "/workspace/test.txt",
        })
        check("read file 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        if r.status_code == 200:
            data = r.json()
            check("file content matches", data.get("content") == "hello from e2e test",
                  f"got {data}")

        print("\n--- File List ---")
        r = await client.get(f"/sandboxes/{sandbox_id}/files", params={
            "path": "/workspace",
        })
        check("list files 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
        if r.status_code == 200:
            data = r.json()
            entries = data.get("entries", [])
            check("test.txt in listing", "test.txt" in str(entries), f"got {entries}")

        # --- Destroy Sandbox ---
        print("\n--- Sandbox Destroy ---")
        r = await client.delete(f"/sandboxes/{sandbox_id}")
        check("destroy sandbox", r.status_code in (200, 204), f"got {r.status_code}: {r.text}")

        # Verify state is destroyed (record persists in DB)
        r = await client.get(f"/sandboxes/{sandbox_id}")
        if r.status_code == 200:
            sb = r.json()
            check("sandbox state is destroyed", sb.get("state") == "destroyed", f"got {sb}")
        else:
            check("sandbox state is destroyed", r.status_code == 404, f"got {r.status_code}")

    # --- S3 Storage Backend (MinIO) ---
    print("\n--- S3StorageBackend (MinIO) ---")
    try:
        import boto3
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")

        s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT)
        s3.list_buckets()

        # Ensure test bucket exists
        try:
            s3.head_bucket(Bucket="agentbox-test-e2e")
        except Exception:
            s3.create_bucket(Bucket="agentbox-test-e2e")

        from agentbox.box.git.storage import S3StorageBackend

        test_prefix = f"e2e-{uuid.uuid4().hex[:8]}/"
        store = S3StorageBackend(
            bucket="agentbox-test-e2e",
            prefix=test_prefix,
            endpoint_url=MINIO_ENDPOINT,
        )

        repo_id = "test-repo"

        # Write + Read
        await store.write_file(repo_id, "readme.md", b"# E2E Test\n")
        content = await store.read_file(repo_id, "readme.md")
        check("s3 write/read text", content == b"# E2E Test\n")

        # Binary round-trip
        binary = bytes(range(256)) * 4
        await store.write_file(repo_id, ".git/objects/ab/cd1234", binary)
        content = await store.read_file(repo_id, ".git/objects/ab/cd1234")
        check("s3 binary round-trip", content == binary)

        # List
        files = await store.list_files(repo_id)
        check("s3 list_files", len(files) == 2, f"got {files}")

        # Exists
        check("s3 exists", await store.exists(repo_id))
        check("s3 not exists", not await store.exists("no-such-repo"))

        # Delete file
        await store.delete_file(repo_id, "readme.md")
        content = await store.read_file(repo_id, "readme.md")
        check("s3 delete_file", content is None)

        # Delete repo
        await store.delete_repo(repo_id)
        check("s3 delete_repo", not await store.exists(repo_id))

        # Cleanup bucket
        s3.delete_bucket(Bucket="agentbox-test-e2e")

    except ImportError:
        print("  (skipping S3 tests — boto3 not installed)")
    except Exception as e:
        check("s3 reachable", False, str(e))

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
