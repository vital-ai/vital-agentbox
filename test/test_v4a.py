"""Tests for V4A diff parser/applier and apply_patch shell builtin."""

import asyncio
from agentbox.box.patch.v4a import apply_v4a_diff, parse_v4a_patch


def test_create_file():
    diff = "+line1\n+line2\n+line3"
    result = apply_v4a_diff("", diff, mode="create")
    assert result == "line1\nline2\nline3"


def test_simple_update():
    content = "line1\nline2\nline3"
    diff = " line1\n-line2\n+LINE2\n line3"
    result = apply_v4a_diff(content, diff)
    assert result == "line1\nLINE2\nline3"


def test_update_with_anchor():
    content = "alpha\nbeta\ngamma\ndelta\nepsilon"
    diff = "@@ gamma\n delta\n-epsilon\n+EPSILON"
    result = apply_v4a_diff(content, diff)
    assert result == "alpha\nbeta\ngamma\ndelta\nEPSILON"


def test_multi_hunk_update():
    content = "a\nb\nc\nd\ne\nf"
    diff = " a\n-b\n+B\n c\n@@ d\n e\n-f\n+F"
    result = apply_v4a_diff(content, diff)
    assert result == "a\nB\nc\nd\ne\nF"


def test_insert_lines():
    content = "line1\nline2"
    diff = " line1\n+inserted\n line2"
    result = apply_v4a_diff(content, diff)
    assert result == "line1\ninserted\nline2"


def test_delete_lines():
    content = "line1\nline2\nline3"
    diff = " line1\n-line2\n line3"
    result = apply_v4a_diff(content, diff)
    assert result == "line1\nline3"


def test_fuzzy_match_rstrip():
    content = "line1  \nline2\nline3  "
    diff = " line1\n-line2\n+LINE2\n line3"
    result = apply_v4a_diff(content, diff)
    assert "LINE2" in result


def test_fuzzy_match_strip():
    content = "  line1\n  line2\n  line3"
    diff = " line1\n-line2\n+LINE2\n line3"
    result = apply_v4a_diff(content, diff)
    assert "LINE2" in result


def test_parse_v4a_patch_add():
    patch = """*** Add File: /new.py
+def hello():
+    print("hello")
*** End Patch"""
    ops = parse_v4a_patch(patch)
    assert len(ops) == 1
    assert ops[0].type == "add"
    assert ops[0].path == "/new.py"
    assert "+def hello():" in ops[0].diff


def test_parse_v4a_patch_update():
    patch = """*** Update File: /existing.py
@@ def old():
-def old():
+def new():
*** End Patch"""
    ops = parse_v4a_patch(patch)
    assert len(ops) == 1
    assert ops[0].type == "update"
    assert ops[0].path == "/existing.py"


def test_parse_v4a_patch_delete():
    patch = """*** Delete File: /remove.py
*** End Patch"""
    ops = parse_v4a_patch(patch)
    assert len(ops) == 1
    assert ops[0].type == "delete"
    assert ops[0].path == "/remove.py"


def test_parse_v4a_patch_multi():
    patch = """*** Add File: /a.py
+print("a")
*** Update File: /b.py
 line1
-old
+new
*** Delete File: /c.py
*** End Patch"""
    ops = parse_v4a_patch(patch)
    assert len(ops) == 3
    assert ops[0].type == "add"
    assert ops[1].type == "update"
    assert ops[2].type == "delete"


def test_eof_marker():
    content = "header\nbody\nfooter"
    diff = " body\n-footer\n+FOOTER\n*** End of File"
    result = apply_v4a_diff(content, diff)
    assert result == "header\nbody\nFOOTER"


# ---------------------------------------------------------------------------
# Shell builtin integration tests
# ---------------------------------------------------------------------------

async def test_apply_patch_builtin():
    from agentbox.box.code_exec_box import CodeExecutorBox

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
    print("TEST: apply_patch builtin (V4A)")
    print("=" * 60)

    async with CodeExecutorBox() as box:
        # --- Create file via V4A ---
        print("\n--- add file ---")
        r = await box.run_shell("""apply_patch << 'EOF'
*** Add File: /hello.py
+def hello():
+    print("hello world")
+
+hello()
*** End Patch
EOF""")
        check("add file succeeds", r["exit_code"] == 0, r.get("stderr", ""))
        check("add output", "ADD: /hello.py" in r["stdout"], r["stdout"])

        r = await box.run_shell("cat /hello.py")
        check("file created", 'print("hello world")' in r["stdout"], r["stdout"][:200])

        # --- Update file via V4A ---
        print("\n--- update file ---")
        r = await box.run_shell("""apply_patch << 'EOF'
*** Update File: /hello.py
 def hello():
-    print("hello world")
+    print("goodbye world")
*** End Patch
EOF""")
        check("update succeeds", r["exit_code"] == 0, r.get("stderr", ""))
        check("update output", "UPDATE: /hello.py" in r["stdout"], r["stdout"])

        r = await box.run_shell("cat /hello.py")
        check("file updated", 'print("goodbye world")' in r["stdout"], r["stdout"][:200])

        # --- Delete file via V4A ---
        print("\n--- delete file ---")
        r = await box.run_shell("""apply_patch << 'EOF'
*** Delete File: /hello.py
*** End Patch
EOF""")
        check("delete succeeds", r["exit_code"] == 0, r.get("stderr", ""))
        check("delete output", "DELETE: /hello.py" in r["stdout"], r["stdout"])

        r = await box.run_shell("cat /hello.py")
        check("file deleted", r["exit_code"] != 0)

        # --- Multi-file patch ---
        print("\n--- multi-file patch ---")
        r = await box.run_shell("""apply_patch << 'EOF'
*** Add File: /a.txt
+alpha
*** Add File: /b.txt
+beta
*** End Patch
EOF""")
        check("multi add succeeds", r["exit_code"] == 0, r.get("stderr", ""))
        check("multi add output", "2/2 operations succeeded" in r["stdout"], r["stdout"])

        r = await box.run_shell("cat /a.txt")
        check("a.txt created", "alpha" in r["stdout"])
        r = await box.run_shell("cat /b.txt")
        check("b.txt created", "beta" in r["stdout"])

        # --- Error: update missing file ---
        print("\n--- error: update missing file ---")
        r = await box.run_shell("""apply_patch << 'EOF'
*** Update File: /nonexistent.py
 line1
-old
+new
*** End Patch
EOF""")
        check("update missing fails", r["exit_code"] == 1)
        check("error mentions file", "file not found" in r["stdout"].lower(), r["stdout"])

        # --- Error: no input ---
        print("\n--- error: no input ---")
        r = await box.run_shell("apply_patch")
        check("no input fails", r["exit_code"] == 1)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


def main():
    print("=" * 60)
    print("TEST: V4A diff parser/applier (unit)")
    print("=" * 60)

    tests = [
        ("create file", test_create_file),
        ("simple update", test_simple_update),
        ("update with anchor", test_update_with_anchor),
        ("multi-hunk update", test_multi_hunk_update),
        ("insert lines", test_insert_lines),
        ("delete lines", test_delete_lines),
        ("fuzzy rstrip", test_fuzzy_match_rstrip),
        ("fuzzy strip", test_fuzzy_match_strip),
        ("parse add", test_parse_v4a_patch_add),
        ("parse update", test_parse_v4a_patch_update),
        ("parse delete", test_parse_v4a_patch_delete),
        ("parse multi", test_parse_v4a_patch_multi),
        ("eof marker", test_eof_marker),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {e}")

    total = passed + failed
    print(f"\nUnit: {passed}/{total} passed")

    # Integration tests
    print()
    builtin_ok = asyncio.run(test_apply_patch_builtin())

    return failed == 0 and builtin_ok


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
