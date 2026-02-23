"""Tests for AST-aware matching fallback in the patcher."""

from agentbox.box.patch.ast_match import ast_find, ast_replace
from agentbox.box.patch.patcher import str_replace


# ---------------------------------------------------------------------------
# Unit tests: ast_find
# ---------------------------------------------------------------------------

def test_find_function_exact():
    content = """def hello():
    print("hello")

def goodbye():
    print("goodbye")
"""
    old_str = """def goodbye():
    print("goodbye")"""
    match = ast_find(content, old_str, path="test.py")
    assert match is not None
    assert match.node_kind == "function_definition"
    assert "goodbye" in match.matched_text


def test_find_function_whitespace_drift():
    """old_str has different indentation but same structure."""
    content = """class Foo:
    def bar(self):
        x = 1
        return x
"""
    # Agent's old_str has no class indentation
    old_str = """def bar(self):
    x = 1
    return x"""
    match = ast_find(content, old_str, path="test.py")
    assert match is not None
    assert match.node_kind == "function_definition"
    assert "bar" in match.matched_text
    assert match.similarity > 0.6


def test_find_class():
    content = """import os

class Calculator:
    def add(self, a, b):
        return a + b
"""
    old_str = """class Calculator:
    def add(self, a, b):
        return a + b"""
    match = ast_find(content, old_str, path="test.py")
    assert match is not None
    assert match.node_kind == "class_definition"


def test_find_no_match():
    content = """def hello():
    print("hello")
"""
    old_str = """def nonexistent():
    pass"""
    match = ast_find(content, old_str, path="test.py")
    assert match is None


def test_find_unsupported_language():
    content = "some text"
    old_str = "some"
    match = ast_find(content, old_str, path="test.txt")
    assert match is None


def test_find_multi_statement_rejected():
    """Multi-statement old_str should return None (not supported)."""
    content = """x = 1
y = 2
z = 3
"""
    old_str = """x = 1
y = 2"""
    match = ast_find(content, old_str, path="test.py")
    assert match is None


def test_find_javascript():
    content = """function greet(name) {
    console.log("hello " + name);
}

function farewell(name) {
    console.log("bye " + name);
}
"""
    old_str = """function farewell(name) {
    console.log("bye " + name);
}"""
    match = ast_find(content, old_str, path="test.js")
    assert match is not None
    assert "farewell" in match.matched_text


# ---------------------------------------------------------------------------
# Unit tests: ast_replace
# ---------------------------------------------------------------------------

def test_replace_function():
    content = """def hello():
    print("hello")

def goodbye():
    print("goodbye")
"""
    old_str = """def goodbye():
    print("goodbye")"""
    new_str = """def farewell():
    print("farewell")"""
    result = ast_replace(content, old_str, new_str, path="test.py")
    assert result is not None
    assert "farewell" in result
    assert "goodbye" not in result
    assert "hello" in result  # untouched


def test_replace_with_indent_offset():
    """Replacement should adjust indentation to match file context."""
    content = """class Foo:
    def bar(self):
        return 1
"""
    # Agent's old_str at wrong indent level
    old_str = """def bar(self):
    return 1"""
    new_str = """def bar(self):
    return 2"""
    result = ast_replace(content, old_str, new_str, path="test.py")
    assert result is not None
    assert "return 2" in result
    # Check indentation is preserved (4-space indent within class)
    for line in result.splitlines():
        if "return 2" in line:
            assert line.startswith("        ")  # 8 spaces (class + method)


def test_replace_no_match():
    content = """def hello():
    pass
"""
    result = ast_replace(content, "def missing(): pass", "def new(): pass", path="test.py")
    assert result is None


# ---------------------------------------------------------------------------
# Integration: str_replace falls through to AST tier
# ---------------------------------------------------------------------------

def test_str_replace_ast_fallback():
    """When text tiers fail, AST tier should catch whitespace-drifted code."""
    content = """class Service:
    def process(self):
        data = self.fetch()
        result = self.transform(data)
        return result
"""
    # Agent gives old_str without class indentation — text match fails
    old_str = """def process(self):
    data = self.fetch()
    result = self.transform(data)
    return result"""
    new_str = """def process(self):
    data = self.fetch()
    result = self.transform(data)
    self.log(result)
    return result"""

    result = str_replace(content, old_str, new_str, path="service.py")
    assert result.success, f"str_replace failed: {result.message}"
    assert "self.log(result)" in result.new_content


def test_str_replace_exact_takes_priority():
    """Exact text match should still work and take priority over AST."""
    content = """def hello():
    print("hello")
"""
    old_str = 'print("hello")'
    new_str = 'print("world")'
    result = str_replace(content, old_str, new_str, path="test.py")
    assert result.success
    assert 'print("world")' in result.new_content


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main():
    tests = [
        ("find function exact", test_find_function_exact),
        ("find function whitespace drift", test_find_function_whitespace_drift),
        ("find class", test_find_class),
        ("find no match", test_find_no_match),
        ("find unsupported language", test_find_unsupported_language),
        ("find multi-statement rejected", test_find_multi_statement_rejected),
        ("find javascript", test_find_javascript),
        ("replace function", test_replace_function),
        ("replace with indent offset", test_replace_with_indent_offset),
        ("replace no match", test_replace_no_match),
        ("str_replace AST fallback", test_str_replace_ast_fallback),
        ("str_replace exact priority", test_str_replace_exact_takes_priority),
    ]

    passed = 0
    failed = 0
    print("=" * 60)
    print("TEST: AST-aware matching fallback")
    print("=" * 60)

    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {e}")

    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
