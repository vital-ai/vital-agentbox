"""
Test git push/pull/clone with LocalStorageBackend.

Tests the full round-trip: create files in GitBox, commit, push to local store,
destroy sandbox, create new sandbox, pull/clone from store, verify files.
"""

import asyncio
import os
import shutil
import tempfile

from agentbox.box.git_box import GitBox


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

    print("=" * 60)
    print("TEST: Git Sync (push/pull/clone with LocalStorageBackend)")
    print("=" * 60)

    # Set up temp storage directory
    store_dir = tempfile.mkdtemp(prefix="agentbox-test-store-")
    os.environ["AGENTBOX_GIT_STORE"] = "local"
    os.environ["AGENTBOX_GIT_STORE_PATH"] = store_dir

    try:
        # --- Push ---
        print("\n--- git push ---")

        async with GitBox(repo_id="test-repo-1") as box:
            # Create files and commit
            await box.run_shell('echo "# Test Repo" > /workspace/readme.md')
            await box.run_shell('echo "data content" > /workspace/data.txt')
            await box.run_shell("mkdir -p /workspace/src")
            await box.run_shell('echo "print(42)" > /workspace/src/main.py')
            await box.run_shell("cd /workspace && git add readme.md data.txt src/main.py")
            r = await box.run_shell('cd /workspace && git commit -m "First commit"')
            check("commit before push", r["exit_code"] == 0, r["stderr"])

            # Push
            r = await box.run_shell("cd /workspace && git push")
            check("git push succeeds", r["exit_code"] == 0, r["stderr"])
            check("push output has file count", "files" in r["stdout"])

            # Verify files in store
            from agentbox.box.git.storage import LocalStorageBackend
            store = LocalStorageBackend(store_dir)
            exists = await store.exists("test-repo-1")
            check("repo exists in store", exists)

            files = await store.list_files("test-repo-1")
            check("store has files", len(files) > 0, f"files: {files}")

            # Check specific files exist (stored relative to workspace dir)
            readme = await store.read_file("test-repo-1", "readme.md")
            check("readme in store", readme is not None)
            check("readme content", readme and b"# Test Repo" in readme)

            data = await store.read_file("test-repo-1", "data.txt")
            check("data.txt in store", data is not None)

            main_py = await store.read_file("test-repo-1", "src/main.py")
            check("src/main.py in store", main_py is not None)

            # Check .git objects are stored
            git_files = await store.list_files("test-repo-1", ".git/")
            check("git objects in store", len(git_files) > 0)

            # Second commit + push
            await box.run_shell('echo "more" >> /workspace/data.txt')
            await box.run_shell("cd /workspace && git add data.txt")
            await box.run_shell('cd /workspace && git commit -m "Update data"')
            r = await box.run_shell("cd /workspace && git push")
            check("second push succeeds", r["exit_code"] == 0, r["stderr"])

        # --- Pull into new sandbox ---
        print("\n--- git pull ---")

        async with GitBox(repo_id="test-repo-1") as box2:
            # New sandbox has empty repo — pull from store
            r = await box2.run_shell("cd /workspace && git pull")
            check("git pull succeeds", r["exit_code"] == 0, r["stderr"])
            check("pull output has file count", "files" in r["stdout"])

            # Verify files are restored
            r = await box2.run_shell("cat /workspace/readme.md")
            check("readme restored", r["exit_code"] == 0 and "# Test Repo" in r["stdout"],
                  r["stdout"])

            r = await box2.run_shell("cat /workspace/src/main.py")
            check("src/main.py restored", r["exit_code"] == 0 and "print(42)" in r["stdout"],
                  r["stdout"])

            # Verify git history is preserved
            r = await box2.run_shell("cd /workspace && git log --oneline")
            check("git log has commits", r["exit_code"] == 0, r["stderr"])
            check("log has both commits",
                  "First commit" in r["stdout"] and "Update data" in r["stdout"],
                  r["stdout"])

        # --- Clone into different path ---
        print("\n--- git clone ---")

        async with GitBox() as box3:
            r = await box3.run_shell("git clone test-repo-1 /cloned")
            check("git clone succeeds", r["exit_code"] == 0, r["stderr"])
            check("clone output", "test-repo-1" in r["stdout"])

            # Verify cloned files
            r = await box3.run_shell("cat /cloned/readme.md")
            check("cloned readme", r["exit_code"] == 0 and "# Test Repo" in r["stdout"],
                  r["stdout"])

            r = await box3.run_shell("cat /cloned/src/main.py")
            check("cloned src/main.py", r["exit_code"] == 0 and "print(42)" in r["stdout"],
                  r["stdout"])

        # --- Error cases ---
        print("\n--- error cases ---")

        async with GitBox() as box4:
            # Push without repo_id
            r = await box4.run_shell("cd /workspace && git push")
            check("push without repo_id fails", r["exit_code"] == 1)
            check("push error message", "no repo_id" in r["stderr"], r["stderr"])

            # Pull without repo_id
            r = await box4.run_shell("cd /workspace && git pull")
            check("pull without repo_id fails", r["exit_code"] == 1)

            # Clone nonexistent repo
            r = await box4.run_shell("git clone nonexistent-repo /target")
            check("clone nonexistent fails", r["exit_code"] == 1)
            check("clone error message", "not found" in r["stderr"], r["stderr"])

        # --- Storage backend directly ---
        print("\n--- storage backend ---")

        store = LocalStorageBackend(store_dir)

        # Delete repo
        await store.delete_repo("test-repo-1")
        exists = await store.exists("test-repo-1")
        check("delete_repo works", not exists)

        # Non-existent repo
        files = await store.list_files("nonexistent")
        check("list_files empty for missing repo", files == [])

        content = await store.read_file("nonexistent", "file.txt")
        check("read_file None for missing", content is None)

    finally:
        # Clean up
        shutil.rmtree(store_dir, ignore_errors=True)
        os.environ.pop("AGENTBOX_GIT_STORE", None)
        os.environ.pop("AGENTBOX_GIT_STORE_PATH", None)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
