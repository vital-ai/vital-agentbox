"""
Unit tests for agentbox.box.patch — the MemFS-native file patcher.

These test the pure-Python logic directly (no browser/MemFS needed).
"""

import pytest
from agentbox.box.patch.search import (
    find_lines,
    count_matches,
    fuzzy_find,
    find_similar_lines,
    normalise,
)
from agentbox.box.patch.patcher import (
    str_replace,
    insert,
    view,
    info,
    create,
    diff_preview,
)
from agentbox.box.patch.filetype import detect_file_type


# ===================================================================
# search.py — normalise
# ===================================================================

class TestNormalise:
    def test_smart_quotes(self):
        assert normalise("\u201cHello\u201d") == '"Hello"'

    def test_em_dash(self):
        assert normalise("foo \u2014 bar") == "foo - bar"

    def test_non_breaking_space(self):
        assert normalise("a\u00a0b") == "a b"

    def test_strips(self):
        assert normalise("  hello  ") == "hello"

    def test_combined(self):
        assert normalise("  \u2018test\u2019 \u2014 ") == "'test' -"


# ===================================================================
# search.py — find_lines (4-tier matching)
# ===================================================================

class TestFindLines:
    def test_exact_match(self):
        lines = ["aaa", "bbb", "ccc", "ddd"]
        assert find_lines(lines, ["bbb", "ccc"]) == 1

    def test_exact_no_match(self):
        lines = ["aaa", "bbb"]
        assert find_lines(lines, ["xxx"]) is None

    def test_rstrip_match(self):
        lines = ["aaa  ", "bbb  ", "ccc"]
        assert find_lines(lines, ["aaa", "bbb"]) == 0

    def test_strip_match(self):
        lines = ["  aaa  ", "  bbb  ", "ccc"]
        assert find_lines(lines, ["aaa", "bbb"]) == 0

    def test_normalized_match(self):
        lines = ['\u201cHello\u201d', "world"]
        assert find_lines(lines, ['"Hello"', "world"]) == 0

    def test_start_offset(self):
        lines = ["aaa", "bbb", "aaa", "bbb"]
        assert find_lines(lines, ["aaa", "bbb"], start=1) == 2

    def test_empty_pattern(self):
        assert find_lines(["a", "b"], []) == 0

    def test_pattern_longer_than_lines(self):
        assert find_lines(["a"], ["a", "b"]) is None


# ===================================================================
# search.py — count_matches
# ===================================================================

class TestCountMatches:
    def test_single_match(self):
        lines = ["aaa", "bbb", "ccc"]
        assert count_matches(lines, ["bbb"]) == 1

    def test_multiple_matches(self):
        lines = ["aaa", "bbb", "aaa", "bbb"]
        assert count_matches(lines, ["aaa"]) == 2

    def test_no_match(self):
        lines = ["aaa", "bbb"]
        assert count_matches(lines, ["xxx"]) == 0


# ===================================================================
# search.py — find_similar_lines
# ===================================================================

class TestFindSimilarLines:
    def test_finds_close_match(self):
        content = ["def foo():", "    return 1", "", "def bar():", "    return 2"]
        search = ["def foo():", "    return 11"]
        result = find_similar_lines(search, content)
        assert result is not None
        idx, ratio, _ = result
        assert idx == 0
        assert ratio > 0.6

    def test_no_match_below_threshold(self):
        content = ["completely", "different", "content"]
        search = ["nothing", "alike", "at", "all"]
        assert find_similar_lines(search, content) is None


# ===================================================================
# search.py — fuzzy_find
# ===================================================================

class TestFuzzyFind:
    def test_fuzzy_with_comment_difference(self):
        """Matches when a comment line differs but code lines are the same."""
        lines = [
            "# Display Settings",
            "WIDTH = 320",
            "HEIGHT = 224",
            "SCALE = 3",
        ]
        pattern = [
            "# Level Constants",   # different comment
            "WIDTH = 320",
            "HEIGHT = 224",
            "SCALE = 3",
        ]
        result = fuzzy_find(lines, pattern, ext=".py")
        assert result is not None
        idx, length = result
        assert idx == 0
        assert length == 4

    def test_fuzzy_rejects_corrupted_code(self):
        """Rejects when code lines are corrupted."""
        lines = [
            "# Settings",
            "WIDTH = 320",
            "HEIGHT = 224",
            "SCALE = 3",
        ]
        pattern = [
            "# Settings",
            "WIDTH = 999",          # wrong
            "HEIGHT = 999",         # wrong
            "SCALE = 999",          # wrong
        ]
        result = fuzzy_find(lines, pattern, ext=".py")
        assert result is None


# ===================================================================
# patcher.py — str_replace
# ===================================================================

class TestStrReplace:
    def test_exact_replace(self):
        content = "line1\nline2\nline3\n"
        r = str_replace(content, "line2", "replaced")
        assert r.success
        assert "replaced" in r.new_content
        assert "line2" not in r.new_content

    def test_multiline_replace(self):
        content = "aaa\nbbb\nccc\nddd\n"
        r = str_replace(content, "bbb\nccc", "xxx\nyyy")
        assert r.success
        assert "xxx\nyyy" in r.new_content

    def test_multiple_matches_rejected(self):
        content = "aaa\nbbb\naaa\n"
        r = str_replace(content, "aaa", "xxx")
        assert not r.success
        assert "2 locations" in r.message

    def test_not_found(self):
        content = "aaa\nbbb\n"
        r = str_replace(content, "xxx", "yyy")
        assert not r.success
        assert "not found" in r.message

    def test_identical_old_new(self):
        content = "aaa\n"
        r = str_replace(content, "aaa", "aaa")
        assert not r.success
        assert "identical" in r.message

    def test_whitespace_flexible_match(self):
        content = "    def foo():\n        pass\n"
        r = str_replace(content, "def foo():\n    pass", "def bar():\n    pass")
        assert r.success
        assert "bar" in r.new_content

    def test_snippet_in_result(self):
        content = "line1\nline2\nline3\nline4\nline5\n"
        r = str_replace(content, "line3", "replaced")
        assert r.success
        assert r.snippet  # Should have a context snippet

    def test_closest_match_hint_on_failure(self):
        content = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        r = str_replace(content, "def foo():\n    return 11", "xxx")
        assert not r.success
        assert "Closest match" in r.message or "not found" in r.message

    def test_unicode_normalized_match(self):
        content = 'print("Hello")\n'
        # Smart quotes
        r = str_replace(content, 'print(\u201cHello\u201d)', 'print("World")')
        assert r.success
        assert "World" in r.new_content


# ===================================================================
# patcher.py — insert
# ===================================================================

class TestInsert:
    def test_insert_after_line(self):
        content = "line1\nline2\nline3\n"
        r = insert(content, 2, "inserted")
        assert r.success
        lines = r.new_content.splitlines()
        assert lines[2] == "inserted"
        assert len(lines) == 4

    def test_insert_at_beginning(self):
        content = "line1\nline2\n"
        r = insert(content, 0, "first")
        assert r.success
        assert r.new_content.startswith("first\n")

    def test_insert_at_end(self):
        content = "line1\nline2\n"
        r = insert(content, 2, "last")
        assert r.success
        assert r.new_content.strip().endswith("last")

    def test_insert_out_of_range(self):
        content = "line1\n"
        r = insert(content, 99, "oops")
        assert not r.success
        assert "out of range" in r.message

    def test_insert_multiline(self):
        content = "line1\nline2\n"
        r = insert(content, 1, "a\nb\nc")
        assert r.success
        lines = r.new_content.splitlines()
        assert len(lines) == 5


# ===================================================================
# patcher.py — view
# ===================================================================

class TestView:
    def test_view_all(self):
        content = "line1\nline2\nline3"
        r = view(content, path="test.py")
        assert r.success
        assert "1\t" in r.snippet
        assert "line1" in r.snippet
        assert "line3" in r.snippet

    def test_view_range(self):
        content = "\n".join(f"line{i}" for i in range(1, 11))
        r = view(content, start=3, end=5, path="test.py")
        assert r.success
        assert "line3" in r.snippet
        assert "line5" in r.snippet
        assert "line6" not in r.snippet

    def test_view_with_line_numbers(self):
        content = "aaa\nbbb\nccc"
        r = view(content, path="test.py")
        assert "1\taaa" in r.snippet or "1\t" in r.snippet

    def test_view_truncation_message(self):
        content = "\n".join(f"line{i}" for i in range(1, 500))
        r = view(content, start=1, path="test.py")
        assert "more line(s)" in r.snippet

    def test_view_empty_file(self):
        r = view("", path="empty.py")
        assert r.success

    def test_view_start_beyond_end(self):
        content = "aaa\nbbb"
        r = view(content, start=99, path="test.py")
        assert r.success
        assert "2 lines" in r.message


# ===================================================================
# patcher.py — create
# ===================================================================

class TestCreate:
    def test_create_with_content(self):
        r = create("hello world\n", path="new.txt")
        assert r.success
        assert r.new_content == "hello world\n"

    def test_create_empty(self):
        r = create("", path="empty.txt")
        assert r.success
        assert r.new_content == ""

    def test_create_message(self):
        r = create("x", path="foo.py")
        assert "foo.py" in r.message


# ===================================================================
# patcher.py — info
# ===================================================================

class TestInfo:
    def test_basic_python_info(self):
        content = (
            "import os\n"
            "import sys\n"
            "\n"
            "class Foo:\n"
            "    def bar(self):\n"
            "        return 1\n"
            "\n"
            "def main():\n"
            "    pass\n"
        )
        r = info(content, path="example.py")
        assert r.success
        assert "Python" in r.message
        assert "9 lines" in r.message
        assert "functions:" in r.message or "classes:" in r.message

    def test_info_line_count(self):
        content = "a\nb\nc\n"
        r = info(content, path="test.txt")
        assert "3 lines" in r.message

    def test_info_size(self):
        content = "hello world\n"
        r = info(content, path="small.txt")
        assert "B" in r.message  # small file, should show bytes

    def test_info_indent_spaces(self):
        content = "def foo():\n    pass\n    return\n"
        r = info(content, path="test.py")
        assert "indent:" in r.message
        assert "spaces" in r.message

    def test_info_indent_tabs(self):
        content = "def foo():\n\tpass\n\treturn\n"
        r = info(content, path="test.py")
        assert "tabs" in r.message

    def test_info_trailing_newline(self):
        r1 = info("hello\n", path="a.txt")
        assert "trailing newline: yes" in r1.message
        r2 = info("hello", path="b.txt")
        assert "trailing newline: no" in r2.message

    def test_info_blank_lines(self):
        content = "a\n\nb\n\nc\n"
        r = info(content, path="test.txt")
        assert "blank lines: 2" in r.message

    def test_info_python_definitions(self):
        content = (
            "import os\n"
            "from sys import argv\n"
            "\n"
            "class MyClass:\n"
            "    def method(self):\n"
            "        pass\n"
            "\n"
            "def helper():\n"
            "    pass\n"
        )
        r = info(content, path="defs.py")
        assert "classes: 1" in r.message
        assert "MyClass" in r.message
        # ast-grep separates methods from functions
        assert "methods: 1" in r.message or "functions:" in r.message
        assert "helper" in r.message

    def test_info_unknown_extension(self):
        r = info("data\n", path="file.xyz")
        assert r.success
        assert "XYZ" in r.message

    def test_info_no_extension(self):
        r = info("data\n", path="Makefile")
        assert r.success

    def test_info_large_file_kb(self):
        content = "x" * 5000 + "\n"
        r = info(content, path="big.txt")
        assert "KB" in r.message

    def test_info_line_endings_lf(self):
        r = info("a\nb\n", path="unix.txt")
        assert "line endings: LF" in r.message

    def test_info_line_endings_crlf(self):
        r = info("a\r\nb\r\n", path="win.txt")
        assert "line endings: CRLF" in r.message


# ===================================================================
# filetype.py — detect_file_type
# ===================================================================

class TestFileType:
    def test_python_by_extension(self):
        name, ext, _ = detect_file_type("x = 1\n", "test.py")
        assert name == "Python"
        assert ext == ".py"

    def test_javascript_by_extension(self):
        name, ext, _ = detect_file_type("var x;\n", "app.js")
        assert name == "JavaScript"

    def test_typescript_by_extension(self):
        name, ext, _ = detect_file_type("const x: number = 1;\n", "app.ts")
        assert name == "TypeScript"

    def test_makefile_by_name(self):
        name, _, _ = detect_file_type("all:\n\techo hello\n", "Makefile")
        assert "Makefile" in name

    def test_dockerfile_by_name(self):
        name, _, _ = detect_file_type("FROM ubuntu:22.04\n", "Dockerfile")
        assert "Dockerfile" in name

    def test_gitignore_by_name(self):
        name, _, _ = detect_file_type("*.pyc\n__pycache__/\n", ".gitignore")
        assert "Git Ignore" in name

    def test_shebang_python(self):
        name, ext, _ = detect_file_type("#!/usr/bin/env python3\nprint('hi')\n", "script")
        assert name == "Python"
        assert ext == ".py"

    def test_shebang_bash(self):
        name, ext, _ = detect_file_type("#!/bin/bash\necho hi\n", "run")
        assert ext == ".sh"

    def test_shebang_node(self):
        name, ext, _ = detect_file_type("#!/usr/bin/env node\nconsole.log('hi')\n", "cli")
        assert ext == ".js"

    def test_json_by_content(self):
        name, ext, _ = detect_file_type('{"key": "value"}\n', "data")
        assert name == "JSON"
        assert ext == ".json"

    def test_json_array_by_content(self):
        name, ext, _ = detect_file_type('[1, 2, 3]\n', "list")
        assert name == "JSON"

    def test_xml_by_content(self):
        name, ext, _ = detect_file_type('<?xml version="1.0"?>\n<root/>\n', "data")
        assert name == "XML"

    def test_html_by_content(self):
        name, ext, _ = detect_file_type('<!DOCTYPE html>\n<html></html>\n', "page")
        assert name == "HTML"

    def test_yaml_by_content(self):
        name, ext, _ = detect_file_type("name: test\nversion: 1\n", "config")
        assert name == "YAML"

    def test_unknown_fallback(self):
        name, _, _ = detect_file_type("random binary stuff\x00\x01", "blob")
        # Should not crash, returns something
        assert name is not None

    def test_pyproject_toml(self):
        name, _, _ = detect_file_type("[tool.pytest]\n", "pyproject.toml")
        assert "TOML" in name

    def test_package_json(self):
        name, _, _ = detect_file_type('{"name": "foo"}\n', "package.json")
        assert "Node" in name or "JSON" in name

    def test_info_uses_filetype(self):
        """info() now uses detect_file_type for richer output."""
        content = "#!/usr/bin/env python3\ndef main():\n    pass\n"
        r = info(content, path="script")
        assert r.success
        assert "Python" in r.message

    def test_info_shows_mime_when_magic_available(self):
        """If python-magic is installed, info shows MIME type."""
        try:
            import magic
            has_magic = True
        except ImportError:
            has_magic = False

        content = "import os\nprint('hello')\n"
        r = info(content, path="test.py")
        if has_magic:
            assert "mime:" in r.message
        # Either way, should work
        assert r.success


# ===================================================================
# patcher.py — diff_preview
# ===================================================================

class TestDiffPreview:
    def test_basic_diff(self):
        content = "line1\nline2\nline3\nline4\nline5\n"
        r = diff_preview(content, "line3", "replaced", path="test.py")
        assert r.success
        assert "-line3" in r.snippet
        assert "+replaced" in r.snippet
        assert "No changes written" in r.message

    def test_diff_shows_context(self):
        content = "a\nb\nc\nd\ne\nf\ng\n"
        r = diff_preview(content, "d", "D", path="test.py")
        assert r.success
        # Should show surrounding context (default 3 lines)
        assert "a" in r.snippet or "b" in r.snippet  # context before
        assert "e" in r.snippet or "f" in r.snippet  # context after

    def test_diff_multiline_change(self):
        content = "aaa\nbbb\nccc\nddd\n"
        r = diff_preview(content, "bbb\nccc", "xxx\nyyy\nzzz", path="test.py")
        assert r.success
        assert "2 line(s) removed" in r.message
        assert "3 line(s) added" in r.message

    def test_diff_not_found(self):
        content = "aaa\nbbb\n"
        r = diff_preview(content, "xxx", "yyy", path="test.py")
        assert not r.success
        assert "not found" in r.message

    def test_diff_multiple_matches(self):
        content = "aaa\nbbb\naaa\n"
        r = diff_preview(content, "aaa", "xxx", path="test.py")
        assert not r.success
        assert "2 locations" in r.message

    def test_diff_does_not_modify(self):
        content = "original\n"
        r = diff_preview(content, "original", "changed", path="test.py")
        assert r.success
        # new_content is set on the internal str_replace, but
        # diff_preview message says "No changes written"
        assert "No changes written" in r.message

    def test_diff_unified_format(self):
        content = "line1\nline2\nline3\n"
        r = diff_preview(content, "line2", "new2", path="test.py")
        assert r.success
        # Should have unified diff headers
        assert "--- a/test.py" in r.snippet
        assert "+++ b/test.py" in r.snippet
        assert "@@" in r.snippet


# ===================================================================
# Long-line file handling (minified JS/CSS, JSON blobs)
# ===================================================================

class TestLongLines:
    def _minified(self, n=2000):
        return "a" * n

    def test_str_replace_long_line(self):
        """str_replace works on single-long-line files."""
        content = "var x=" + "a" * 1000 + ";" + "b" * 1000
        r = str_replace(content, "a" * 1000, "c" * 50)
        assert r.success
        assert "c" * 50 in r.new_content

    def test_view_truncates_long_line(self):
        content = self._minified(5000)
        r = view(content, path="app.min.js")
        assert r.success
        assert "long lines detected" in r.message
        assert "chars total]" in r.snippet  # line was truncated

    def test_view_single_line_file(self):
        content = self._minified(3000)
        r = view(content, path="bundle.js")
        assert r.success
        assert "1 lines" in r.message
        assert len(r.snippet) < 1000  # not dumping 3000 chars

    def test_info_reports_long_lines(self):
        content = self._minified(5000)
        r = info(content, path="styles.min.css")
        assert "long lines" in r.message
        assert "5000 chars" in r.message

    def test_info_minified_warning(self):
        content = self._minified(5000) + "\n"
        r = info(content, path="app.min.js")
        assert "minified" in r.message or "long lines" in r.message

    def test_diff_truncates_long_lines(self):
        content = "prefix" + "x" * 2000 + "suffix"
        r = diff_preview(content, "prefix", "PREFIX", path="data.json")
        assert r.success
        # Diff output shouldn't dump 2000+ chars
        assert len(r.snippet) < 1500

    def test_snippet_truncates_long_line(self):
        content = "short\n" + "x" * 2000 + "\nshort\n"
        r = str_replace(content, "short\n" + "x" * 2000, "short\n" + "y" * 50)
        assert r.success
        # Snippet should truncate the long line
        if r.snippet:
            assert "chars total]" in r.snippet or len(r.snippet) < 1500


# ===================================================================
# Integration: str_replace with indent-offset
# ===================================================================

class TestIndentOffset:
    def test_indent_offset_match(self):
        """LLM sends code with wrong indentation level."""
        content = "class Foo:\n    def bar(self):\n        return 1\n"
        # LLM sends with 0-indent
        r = str_replace(content, "def bar(self):\n    return 1", "def bar(self):\n    return 2")
        assert r.success
        assert "return 2" in r.new_content
        # Should preserve the original 4-space indent
        lines = r.new_content.splitlines()
        bar_line = [l for l in lines if "def bar" in l][0]
        assert bar_line.startswith("    ")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
