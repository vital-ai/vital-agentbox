"""
Test GitBox: isomorphic-git integration with shell commands.
Tests Tier 1 git operations (init, add, commit, log, status, branch, checkout).
"""

import asyncio
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
    print("TEST: GitBox (isomorphic-git integration)")
    print("=" * 60)

    async with GitBox() as box:

        # --- git init (already done by GitBox.start) ---
        print("\n--- git init (auto) ---")
        r = await box.run_shell("ls /workspace/.git")
        check("repo initialized", r["exit_code"] == 0)
        check(".git has contents", len(r["stdout"].strip()) > 0)

        # --- create files + git add + commit ---
        print("\n--- add + commit ---")
        r = await box.run_shell('echo "# Hello" > /workspace/readme.md')
        check("create file", r["exit_code"] == 0)

        r = await box.run_shell("cd /workspace && git add readme.md")
        check("git add", r["exit_code"] == 0, r["stderr"])

        r = await box.run_shell('cd /workspace && git commit -m "Initial commit"')
        check("git commit", r["exit_code"] == 0, r["stderr"])
        check("commit output has sha", r["stdout"].strip() != "")

        # --- git log ---
        print("\n--- git log ---")
        r = await box.run_shell("cd /workspace && git log --oneline")
        check("git log", r["exit_code"] == 0, r["stderr"])
        check("log has commit", "Initial commit" in r["stdout"])

        r = await box.run_shell("cd /workspace && git log")
        check("git log full", r["exit_code"] == 0)
        check("log has author", "Author:" in r["stdout"])

        # --- git status ---
        print("\n--- git status ---")
        r = await box.run_shell("cd /workspace && git status")
        check("status clean", r["exit_code"] == 0)
        check("nothing to commit", "nothing to commit" in r["stdout"])

        # Modify file
        await box.run_shell('echo "more content" >> /workspace/readme.md')
        r = await box.run_shell("cd /workspace && git status")
        check("status shows modified", "M" in r["stdout"] and "readme.md" in r["stdout"],
              r["stdout"])

        # Add new untracked file
        await box.run_shell('echo "data" > /workspace/data.txt')
        r = await box.run_shell("cd /workspace && git status")
        check("status shows untracked", "??" in r["stdout"] and "data.txt" in r["stdout"],
              r["stdout"])

        # --- second commit ---
        print("\n--- second commit ---")
        await box.run_shell("cd /workspace && git add readme.md && git add data.txt")
        r = await box.run_shell('cd /workspace && git commit -m "Add data"')
        check("second commit", r["exit_code"] == 0, r["stderr"])

        r = await box.run_shell("cd /workspace && git log --oneline")
        check("log has 2 commits", r["stdout"].strip().count("\n") == 1)  # 2 lines = 1 newline

        # --- git branch ---
        print("\n--- git branch ---")
        r = await box.run_shell("cd /workspace && git branch")
        check("branch lists main", "main" in r["stdout"])
        check("main is current", "* main" in r["stdout"])

        r = await box.run_shell("cd /workspace && git branch feature")
        check("create branch", r["exit_code"] == 0, r["stderr"])

        r = await box.run_shell("cd /workspace && git branch")
        check("feature in list", "feature" in r["stdout"])

        # --- git checkout ---
        print("\n--- git checkout ---")
        r = await box.run_shell("cd /workspace && git checkout feature")
        check("checkout feature", r["exit_code"] == 0, r["stderr"])
        check("checkout output", "feature" in r["stdout"])

        # Make a commit on feature branch
        await box.run_shell('echo "feature work" > /workspace/feature.txt')
        await box.run_shell("cd /workspace && git add feature.txt")
        r = await box.run_shell('cd /workspace && git commit -m "Feature work"')
        check("commit on feature", r["exit_code"] == 0, r["stderr"])

        # Switch back to main
        r = await box.run_shell("cd /workspace && git checkout main")
        check("checkout main", r["exit_code"] == 0, r["stderr"])

        # feature.txt should not exist on main
        r = await box.run_shell("cat /workspace/feature.txt")
        check("feature.txt gone on main", r["exit_code"] != 0)

        # --- git diff ---
        print("\n--- git diff ---")
        await box.run_shell('echo "changed" >> /workspace/readme.md')
        r = await box.run_shell("cd /workspace && git diff")
        check("diff shows changes", "readme.md" in r["stdout"])

        # --- git rm ---
        print("\n--- git rm ---")
        r = await box.run_shell("cd /workspace && git rm data.txt")
        check("git rm", r["exit_code"] == 0, r["stderr"])
        r = await box.run_shell("cat /workspace/data.txt")
        check("file removed from working tree", r["exit_code"] != 0)

        # --- git custom author ---
        print("\n--- custom author ---")
        await box.run_shell("export GIT_AUTHOR_NAME=TestUser")
        await box.run_shell("export GIT_AUTHOR_EMAIL=test@example.com")
        await box.run_shell('echo "authored" > /workspace/authored.txt')
        await box.run_shell("cd /workspace && git add authored.txt")
        r = await box.run_shell('cd /workspace && git commit -m "Custom author"')
        check("commit with custom author", r["exit_code"] == 0, r["stderr"])

        r = await box.run_shell("cd /workspace && git log -n1")
        check("log shows custom author", "TestUser" in r["stdout"], r["stdout"])

        # --- python + git integration ---
        print("\n--- python + git cross-boundary ---")
        r = await box.run_code("open('/workspace/from_python.txt', 'w').write('python data\\n')")
        check("python writes to workspace", r["exit_code"] == 0, r["stderr"])

        r = await box.run_shell("cd /workspace && git add from_python.txt")
        check("git add python file", r["exit_code"] == 0, r["stderr"])

        r = await box.run_shell('cd /workspace && git commit -m "From python"')
        check("commit python file", r["exit_code"] == 0, r["stderr"])

        # --- merge (fast-forward) ---
        print("\n--- merge (fast-forward) ---")
        # Create a branch from main, add a commit, merge back
        await box.run_shell("cd /workspace && git checkout main")
        await box.run_shell("cd /workspace && git branch ff-test")
        await box.run_shell("cd /workspace && git checkout ff-test")
        await box.run_shell('echo "ff content" > /workspace/ff.txt')
        await box.run_shell("cd /workspace && git add ff.txt")
        await box.run_shell('cd /workspace && git commit -m "FF commit"')
        await box.run_shell("cd /workspace && git checkout main")
        r = await box.run_shell("cd /workspace && git merge ff-test")
        check("ff merge succeeds", r["exit_code"] == 0, r.get("stderr", ""))
        check("ff merge output", "Fast-forward" in r["stdout"], r["stdout"])
        r = await box.run_shell("cat /workspace/ff.txt")
        check("ff file present after merge", "ff content" in r["stdout"])

        # --- merge (conflict) ---
        print("\n--- merge (conflict) ---")
        # Set up diverging branches that both modify the same file
        await box.run_shell("cd /workspace && git checkout main")
        await box.run_shell('echo "line1\nline2\nline3" > /workspace/conflict.txt')
        await box.run_shell("cd /workspace && git add conflict.txt")
        await box.run_shell('cd /workspace && git commit -m "Add conflict.txt"')

        # Create feature branch and change the file
        await box.run_shell("cd /workspace && git branch conflict-branch")
        await box.run_shell("cd /workspace && git checkout conflict-branch")
        await box.run_shell('echo "line1\nCHANGED_BY_FEATURE\nline3" > /workspace/conflict.txt')
        await box.run_shell("cd /workspace && git add conflict.txt")
        await box.run_shell('cd /workspace && git commit -m "Feature change"')

        # Go back to main and make a different change to the same file
        await box.run_shell("cd /workspace && git checkout main")
        await box.run_shell('echo "line1\nCHANGED_BY_MAIN\nline3" > /workspace/conflict.txt')
        await box.run_shell("cd /workspace && git add conflict.txt")
        await box.run_shell('cd /workspace && git commit -m "Main change"')

        # Attempt merge — should conflict
        r = await box.run_shell("cd /workspace && git merge conflict-branch")
        check("merge conflict detected", r["exit_code"] == 1, r["stdout"] + r.get("stderr", ""))
        check("conflict output mentions file",
              "CONFLICT" in r["stdout"] or "conflict" in r["stdout"].lower(),
              r["stdout"])
        check("tells user to fix",
              "fix conflicts" in r["stdout"].lower() or "resolve" in r["stdout"].lower(),
              r["stdout"])

        # Check that conflict markers are in the working tree
        r = await box.run_shell("cat /workspace/conflict.txt")
        has_markers = "<<<<<<" in r["stdout"] or "======" in r["stdout"]
        check("conflict markers in file", has_markers, r["stdout"][:200])

        # --- merge --abort ---
        print("\n--- merge --abort ---")
        r = await box.run_shell("cd /workspace && git merge --abort")
        check("merge abort succeeds", r["exit_code"] == 0, r.get("stderr", ""))

        # File should be restored to main's version
        r = await box.run_shell("cat /workspace/conflict.txt")
        check("file restored after abort",
              "CHANGED_BY_MAIN" in r["stdout"] and "<<<<<<" not in r["stdout"],
              r["stdout"][:200])

        # --- merge + resolve + --continue ---
        print("\n--- merge + resolve + continue ---")
        r = await box.run_shell("cd /workspace && git merge conflict-branch")
        check("conflict again", r["exit_code"] == 1)

        # Resolve by writing the merged content
        await box.run_shell('echo "line1\nMERGED_RESULT\nline3" > /workspace/conflict.txt')
        r = await box.run_shell("cd /workspace && git merge --continue")
        check("merge continue succeeds", r["exit_code"] == 0, r.get("stderr", ""))
        check("merge commit created", "Merge commit" in r["stdout"] or "merge" in r["stdout"].lower(),
              r["stdout"])

        # Verify the merged content is committed
        r = await box.run_shell("cat /workspace/conflict.txt")
        check("merged content persisted", "MERGED_RESULT" in r["stdout"], r["stdout"][:200])

        r = await box.run_shell("cd /workspace && git log --oneline -n1")
        check("log shows merge commit", "Merge" in r["stdout"] or "merge" in r["stdout"].lower(),
              r["stdout"])

        # --- error cases ---
        print("\n--- error cases ---")
        r = await box.run_shell("cd /workspace && git commit -m")
        check("commit without message", r["exit_code"] == 1)

        r = await box.run_shell("cd /workspace && git checkout nonexistent")
        check("checkout nonexistent", r["exit_code"] == 1)

        r = await box.run_shell("cd /workspace && git add")
        check("add without args", r["exit_code"] == 1)

        r = await box.run_shell("cd /workspace && git push")
        check("push without repo_id fails", r["exit_code"] == 1)
        check("push stderr", "repo_id" in r["stderr"] or "not configured" in r["stderr"],
              r["stderr"])

    # --- MemBox rejects git ---
    print("\n--- MemBox rejects git ---")
    from agentbox.box.code_exec_box import CodeExecutorBox
    async with CodeExecutorBox() as membox:
        r = await membox.run_shell("git init /test")
        check("membox rejects git", r["exit_code"] == 1)
        check("membox git stderr", "not available" in r["stderr"])

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
