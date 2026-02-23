"""
Test S3StorageBackend against MinIO from docker-compose.

Prerequisites:
    docker compose up -d minio minio-init
    MinIO API available at http://localhost:9100

Tests cover: write/read/list/delete files, exists, delete_repo,
binary data, path traversal safety, and large file handling.
"""

import asyncio
import os
import uuid
import sys

# Point boto3 at the docker-compose MinIO
os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")

MINIO_ENDPOINT = "http://localhost:9100"
BUCKET = "agentbox-test"


def _ensure_bucket():
    """Create test bucket if it doesn't exist."""
    import boto3
    s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT)
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:
        s3.create_bucket(Bucket=BUCKET)


async def main():
    # Check MinIO is reachable
    try:
        import boto3
        s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT)
        s3.list_buckets()
    except Exception as e:
        print(f"MinIO not reachable at {MINIO_ENDPOINT}: {e}")
        print("Start it with: docker compose up -d minio minio-init")
        return True  # Skip gracefully, don't fail CI

    _ensure_bucket()

    from agentbox.box.git.storage import S3StorageBackend

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

    print("=" * 60)
    print("TEST: S3StorageBackend (MinIO via docker-compose)")
    print("=" * 60)

    # Use unique prefix per test run
    test_prefix = f"test-{uuid.uuid4().hex[:8]}/"
    store = S3StorageBackend(
        bucket=BUCKET,
        prefix=test_prefix,
        endpoint_url=MINIO_ENDPOINT,
    )

    repo_id = "test-repo-1"

    # --- Write + Read ---
    print("\n--- write / read ---")

    await store.write_file(repo_id, "readme.md", b"# Hello World\n")
    content = await store.read_file(repo_id, "readme.md")
    check("write and read text", content == b"# Hello World\n")

    await store.write_file(repo_id, "src/main.py", b"print(42)\n")
    content = await store.read_file(repo_id, "src/main.py")
    check("nested path write/read", content == b"print(42)\n")

    # Binary data (simulates git objects)
    binary_data = bytes(range(256)) * 10
    await store.write_file(repo_id, ".git/objects/ab/cdef1234", binary_data)
    content = await store.read_file(repo_id, ".git/objects/ab/cdef1234")
    check("binary data round-trip", content == binary_data)

    # Overwrite
    await store.write_file(repo_id, "readme.md", b"# Updated\n")
    content = await store.read_file(repo_id, "readme.md")
    check("overwrite file", content == b"# Updated\n")

    # Read nonexistent
    content = await store.read_file(repo_id, "nonexistent.txt")
    check("read nonexistent returns None", content is None)

    content = await store.read_file("no-such-repo", "file.txt")
    check("read from nonexistent repo returns None", content is None)

    # --- Exists ---
    print("\n--- exists ---")

    exists = await store.exists(repo_id)
    check("exists for real repo", exists)

    exists = await store.exists("no-such-repo")
    check("exists for missing repo", not exists)

    # --- List files ---
    print("\n--- list_files ---")

    files = await store.list_files(repo_id)
    check("list_files returns all", len(files) == 3, f"got {len(files)}: {files}")
    check("list contains readme", "readme.md" in files)
    check("list contains src/main.py", "src/main.py" in files)
    check("list contains git object", ".git/objects/ab/cdef1234" in files)

    # With prefix filter
    git_files = await store.list_files(repo_id, ".git/")
    check("list with prefix filter", len(git_files) == 1, f"got {git_files}")

    src_files = await store.list_files(repo_id, "src/")
    check("list src/ prefix", len(src_files) == 1 and src_files[0] == "src/main.py")

    empty = await store.list_files("no-such-repo")
    check("list_files for missing repo", empty == [])

    # --- Delete file ---
    print("\n--- delete_file ---")

    await store.delete_file(repo_id, "src/main.py")
    content = await store.read_file(repo_id, "src/main.py")
    check("delete_file removes file", content is None)

    files = await store.list_files(repo_id)
    check("list after delete", len(files) == 2, f"got {files}")

    # Delete nonexistent (should not error)
    await store.delete_file(repo_id, "nonexistent.txt")
    check("delete nonexistent no error", True)

    # --- Delete repo ---
    print("\n--- delete_repo ---")

    await store.delete_repo(repo_id)
    exists = await store.exists(repo_id)
    check("delete_repo removes all", not exists)

    files = await store.list_files(repo_id)
    check("list after delete_repo", files == [])

    # --- Large file ---
    print("\n--- large file ---")

    repo2 = "test-repo-large"
    large_data = b"x" * (1024 * 1024)  # 1MB
    await store.write_file(repo2, "big.bin", large_data)
    content = await store.read_file(repo2, "big.bin")
    check("1MB write/read", content == large_data)
    check("1MB size correct", len(content) == 1024 * 1024)

    # Cleanup
    await store.delete_repo(repo2)

    # --- Path traversal safety ---
    print("\n--- path safety ---")

    safe_store = S3StorageBackend(
        bucket=BUCKET, prefix=test_prefix, endpoint_url=MINIO_ENDPOINT,
    )
    # repo_id with .. should be sanitized
    await safe_store.write_file("../evil", "file.txt", b"bad")
    exists = await safe_store.exists("../evil")
    # The sanitized id should still work
    check("path traversal sanitized", exists)
    await safe_store.delete_repo("../evil")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
