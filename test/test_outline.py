"""Tests for agentbox.box.outline — AST-based symbol extraction."""

import pytest
from agentbox.box.outline.outliner import (
    outline,
    get_language,
    Symbol,
    OutlineResult,
)


# ===================================================================
# Language detection
# ===================================================================

class TestGetLanguage:
    def test_python(self):
        assert get_language("foo.py") == "python"

    def test_typescript(self):
        assert get_language("app.ts") == "typescript"

    def test_tsx(self):
        assert get_language("App.tsx") == "tsx"

    def test_javascript(self):
        assert get_language("index.js") == "javascript"

    def test_rust(self):
        assert get_language("lib.rs") == "rust"

    def test_go(self):
        assert get_language("main.go") == "go"

    def test_java(self):
        assert get_language("Main.java") == "java"

    def test_c(self):
        assert get_language("main.c") == "c"

    def test_cpp(self):
        assert get_language("main.cpp") == "cpp"

    def test_ruby(self):
        assert get_language("app.rb") == "ruby"

    def test_header(self):
        assert get_language("util.h") == "c"

    def test_unknown(self):
        assert get_language("data.xyz") is None

    def test_no_extension(self):
        assert get_language("Makefile") is None


# ===================================================================
# Python outline
# ===================================================================

class TestPythonOutline:
    def test_basic_class(self):
        code = "class Foo:\n    def bar(self):\n        pass\n"
        r = outline(code, "test.py")
        assert r.language == "python"
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Foo"
        assert r.symbols[0].kind == "class"
        assert len(r.symbols[0].children) == 1
        assert r.symbols[0].children[0].name == "bar"
        assert r.symbols[0].children[0].kind == "method"

    def test_standalone_function(self):
        code = "def helper(x, y):\n    return x + y\n"
        r = outline(code, "test.py")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "helper"
        assert r.symbols[0].kind == "function"

    def test_async_function(self):
        code = "async def fetch():\n    pass\n"
        r = outline(code, "test.py")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "fetch"
        assert "async" in r.symbols[0].signature

    def test_decorated_function(self):
        code = "@staticmethod\ndef create():\n    pass\n"
        r = outline(code, "test.py")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "create"
        assert "@staticmethod" in r.symbols[0].decorators

    def test_multiple_classes(self):
        code = (
            "class Foo:\n    pass\n\n"
            "class Bar:\n    pass\n"
        )
        r = outline(code, "test.py")
        assert len(r.symbols) == 2
        assert r.symbols[0].name == "Foo"
        assert r.symbols[1].name == "Bar"

    def test_nested_methods(self):
        code = (
            "class MyClass:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "    def run(self):\n"
            "        pass\n"
            "    def stop(self):\n"
            "        pass\n"
        )
        r = outline(code, "test.py")
        assert len(r.symbols) == 1
        methods = r.symbols[0].children
        assert len(methods) == 3
        names = [m.name for m in methods]
        assert "__init__" in names
        assert "run" in names
        assert "stop" in names

    def test_signature_preserved(self):
        code = "def process(x: int, y: str = 'hello') -> bool:\n    return True\n"
        r = outline(code, "test.py")
        sig = r.symbols[0].signature
        assert "x: int" in sig
        assert "y: str" in sig
        assert "-> bool" in sig

    def test_line_numbers(self):
        code = "# comment\n\ndef foo():\n    pass\n"
        r = outline(code, "test.py")
        assert r.symbols[0].line == 2  # 0-indexed
        assert r.total_lines == 4


# ===================================================================
# JavaScript outline
# ===================================================================

class TestJavaScriptOutline:
    def test_class_with_methods(self):
        code = (
            "class Foo {\n"
            "  constructor() {}\n"
            "  bar() { return 1; }\n"
            "}\n"
        )
        r = outline(code, "app.js")
        assert r.language == "javascript"
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Foo"
        assert len(r.symbols[0].children) >= 1

    def test_function_declaration(self):
        code = "function hello() {\n  console.log('hi');\n}\n"
        r = outline(code, "app.js")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "hello"


# ===================================================================
# TypeScript outline
# ===================================================================

class TestTypeScriptOutline:
    def test_interface(self):
        code = "interface Config {\n  name: string;\n  port: number;\n}\n"
        r = outline(code, "types.ts")
        assert r.language == "typescript"
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Config"
        assert r.symbols[0].kind == "interface"

    def test_type_alias(self):
        code = "type Result = { ok: boolean; value: string };\n"
        r = outline(code, "types.ts")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Result"
        assert r.symbols[0].kind == "type"

    def test_exported_class(self):
        code = "export class Service {\n  run(): void {}\n}\n"
        r = outline(code, "service.ts")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Service"


# ===================================================================
# Rust outline
# ===================================================================

class TestRustOutline:
    def test_struct(self):
        code = "pub struct Config {\n    name: String,\n    port: u16,\n}\n"
        r = outline(code, "lib.rs")
        assert r.language == "rust"
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Config"
        assert r.symbols[0].kind == "struct"

    def test_impl_with_methods(self):
        code = (
            "impl Config {\n"
            "    pub fn new() -> Self { Self {} }\n"
            "    pub fn validate(&self) -> bool { true }\n"
            "}\n"
        )
        r = outline(code, "lib.rs")
        assert len(r.symbols) == 1
        assert r.symbols[0].kind == "impl"
        assert len(r.symbols[0].children) == 2

    def test_enum(self):
        code = "pub enum Status {\n    Running,\n    Stopped,\n}\n"
        r = outline(code, "lib.rs")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Status"
        assert r.symbols[0].kind == "enum"

    def test_trait(self):
        code = "pub trait Service {\n    fn start(&self);\n    fn stop(&self);\n}\n"
        r = outline(code, "lib.rs")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Service"
        assert r.symbols[0].kind == "trait"

    def test_standalone_function(self):
        code = "fn main() {\n    println!(\"hello\");\n}\n"
        r = outline(code, "main.rs")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "main"


# ===================================================================
# Go outline
# ===================================================================

class TestGoOutline:
    def test_function(self):
        code = "func main() {\n\tfmt.Println(\"hello\")\n}\n"
        r = outline(code, "main.go")
        assert r.language == "go"
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "main"

    def test_struct(self):
        code = "type Config struct {\n\tName string\n\tPort int\n}\n"
        r = outline(code, "config.go")
        assert len(r.symbols) == 1
        assert r.symbols[0].name == "Config"


# ===================================================================
# Rendering
# ===================================================================

class TestRendering:
    def test_outline_text_contains_signatures(self):
        code = "class Foo:\n    def bar(self, x: int):\n        pass\n"
        r = outline(code, "test.py")
        assert "class Foo:" in r.outline_text
        assert "def bar(self, x: int):" in r.outline_text
        assert "⋮" in r.outline_text

    def test_outline_text_has_filename(self):
        code = "def foo():\n    pass\n"
        r = outline(code, "mymodule.py")
        assert "mymodule.py" in r.outline_text

    def test_symbols_text_has_line_numbers(self):
        code = "class A:\n    pass\n\ndef b():\n    pass\n"
        r = outline(code, "test.py")
        assert "1" in r.symbols_text  # line 1 for class A
        assert "4" in r.symbols_text  # line 4 for def b

    def test_symbols_text_has_kinds(self):
        code = "class A:\n    def m(self):\n        pass\n"
        r = outline(code, "test.py")
        assert "class" in r.symbols_text
        assert "method" in r.symbols_text

    def test_empty_file(self):
        r = outline("", "empty.py")
        assert r.symbols == []
        assert "no definitions" in r.outline_text

    def test_comments_only(self):
        code = "# just a comment\n# another\n"
        r = outline(code, "test.py")
        assert r.symbols == []


# ===================================================================
# Markdown outline
# ===================================================================

class TestMarkdownOutline:
    def test_basic_headings(self):
        md = "# Title\n\n## Section One\n\nText.\n\n## Section Two\n"
        r = outline(md, "doc.md")
        assert r.language == "markdown"
        assert len([s for s in r.symbols if s.kind.startswith("h")]) == 3
        names = [s.name for s in r.symbols if s.kind.startswith("h")]
        assert "Title" in names
        assert "Section One" in names
        assert "Section Two" in names

    def test_heading_levels(self):
        md = "# H1\n## H2\n### H3\n#### H4\n"
        r = outline(md, "doc.md")
        kinds = [s.kind for s in r.symbols if s.kind.startswith("h")]
        assert kinds == ["h1", "h2", "h3", "h4"]

    def test_outline_text_indented(self):
        md = "# Title\n## Sub\n### SubSub\n"
        r = outline(md, "doc.md")
        assert "# Title" in r.outline_text
        assert "## Sub" in r.outline_text
        assert "### SubSub" in r.outline_text

    def test_code_blocks(self):
        md = "# Code\n\n```python\ndef foo():\n    pass\n```\n\n```javascript\nconsole.log('hi');\n```\n"
        r = outline(md, "doc.md")
        code_syms = [s for s in r.symbols if s.kind == "code_block"]
        assert len(code_syms) == 2
        assert "python" in r.outline_text
        assert "code blocks: 2" in r.outline_text

    def test_math_blocks(self):
        md = "# Math\n\n$$\n\\int_0^1 f(x) dx\n$$\n"
        r = outline(md, "doc.md")
        math_syms = [s for s in r.symbols if s.kind == "math_block"]
        assert len(math_syms) == 1
        assert "math" in r.outline_text.lower()

    def test_inline_math(self):
        md = "# Formula\n\nThe equation $E = mc^2$ is famous. Also $a^2 + b^2 = c^2$.\n"
        r = outline(md, "doc.md")
        assert "inline" in r.outline_text.lower()

    def test_mixed_content(self):
        md = (
            "# Paper Title\n\n"
            "## Abstract\n\n"
            "This paper discusses $E = mc^2$.\n\n"
            "## Methods\n\n"
            "```python\nimport numpy as np\n```\n\n"
            "$$\n\\sum_{i=1}^{n} x_i\n$$\n\n"
            "## Results\n\n"
            "### Table 1\n\n"
            "Data here.\n"
        )
        r = outline(md, "paper.md")
        headings = [s for s in r.symbols if s.kind.startswith("h")]
        assert len(headings) == 5  # Paper Title, Abstract, Methods, Results, Table 1
        code_syms = [s for s in r.symbols if s.kind == "code_block"]
        assert len(code_syms) == 1
        math_syms = [s for s in r.symbols if s.kind == "math_block"]
        assert len(math_syms) == 1

    def test_empty_markdown(self):
        r = outline("", "empty.md")
        assert r.language == "markdown"
        assert r.symbols == [] or "no structure" in r.outline_text

    def test_no_headings(self):
        md = "Just plain text.\nMore text.\n"
        r = outline(md, "plain.md")
        assert r.language == "markdown"

    def test_symbols_text_has_lines(self):
        md = "# Title\n\n## Section\n"
        r = outline(md, "doc.md")
        assert "1" in r.symbols_text  # line 1 for # Title
        assert "3" in r.symbols_text  # line 3 for ## Section

    def test_mdx_extension(self):
        assert get_language("component.mdx") == "markdown"

    def test_code_block_languages_in_outline(self):
        md = "```rust\nfn main() {}\n```\n\n```sql\nSELECT 1;\n```\n"
        r = outline(md, "doc.md")
        assert "rust" in r.outline_text
        assert "sql" in r.outline_text


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:
    def test_unsupported_language(self):
        r = outline("data\n", "file.xyz")
        assert r.language == "unknown"
        assert "unsupported" in r.outline_text

    def test_syntax_error_still_parses(self):
        # tree-sitter is error-tolerant
        code = "def foo(\n    # incomplete\n"
        r = outline(code, "bad.py")
        # Should not crash — may or may not find symbols
        assert isinstance(r, OutlineResult)

    def test_large_file(self):
        funcs = [f"def func_{i}():\n    pass\n\n" for i in range(50)]
        code = "".join(funcs)
        r = outline(code, "big.py")
        assert len(r.symbols) == 50

    def test_language_override(self):
        code = "def foo():\n    pass\n"
        r = outline(code, "noext", language="python")
        assert r.language == "python"
        assert len(r.symbols) == 1

    def test_decorator_line_number(self):
        code = "@app.route('/api')\ndef handler():\n    pass\n"
        r = outline(code, "test.py")
        assert r.symbols[0].line == 0  # decorator starts at line 0
        assert "@app.route" in r.symbols[0].decorators[0]
