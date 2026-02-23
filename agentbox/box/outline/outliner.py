"""
Outline extraction using ast-grep-py (tree-sitter).

Parses source code from strings (MemFS-native), extracts symbol definitions
(classes, functions, methods, structs, interfaces, etc.), and renders
condensed outlines with ⋮ elision.

Runs on the host Python — not in Pyodide.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ast_grep_py import SgRoot, SgNode


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Symbol:
    """A definition extracted from source code."""
    name: str
    kind: str           # "class", "function", "method", "struct", etc.
    line: int           # 0-indexed line number
    end_line: int       # 0-indexed end line
    signature: str      # first line(s) of the definition
    children: List[Symbol] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)


@dataclass
class OutlineResult:
    """Result of an outline extraction."""
    symbols: List[Symbol]
    language: str
    total_lines: int
    outline_text: str   # rendered condensed view
    symbols_text: str   # compact symbol list


# ---------------------------------------------------------------------------
# Language → definition node kinds
# ---------------------------------------------------------------------------

# Maps tree-sitter node kinds to our normalized kind names.
# Each entry: (ts_node_kind, our_kind, name_child_kind_or_None)
_LANG_DEFS: dict[str, list[tuple[str, str, Optional[str]]]] = {
    "python": [
        ("class_definition", "class", "identifier"),
        ("function_definition", "function", "identifier"),
        ("decorated_definition", "decorated", None),
    ],
    "javascript": [
        ("class_declaration", "class", "identifier"),
        ("function_declaration", "function", "identifier"),
        ("method_definition", "method", "property_identifier"),
        ("lexical_declaration", "variable", None),
        ("export_statement", "export", None),
    ],
    "typescript": [
        ("class_declaration", "class", "type_identifier"),
        ("function_declaration", "function", "identifier"),
        ("interface_declaration", "interface", "type_identifier"),
        ("type_alias_declaration", "type", "type_identifier"),
        ("method_definition", "method", "property_identifier"),
        ("enum_declaration", "enum", "identifier"),
        ("export_statement", "export", None),
    ],
    "tsx": [
        ("class_declaration", "class", "type_identifier"),
        ("function_declaration", "function", "identifier"),
        ("interface_declaration", "interface", "type_identifier"),
        ("type_alias_declaration", "type", "type_identifier"),
        ("method_definition", "method", "property_identifier"),
        ("export_statement", "export", None),
    ],
    "rust": [
        ("struct_item", "struct", "type_identifier"),
        ("enum_item", "enum", "type_identifier"),
        ("function_item", "function", "identifier"),
        ("impl_item", "impl", "type_identifier"),
        ("trait_item", "trait", "type_identifier"),
        ("type_item", "type", "type_identifier"),
        ("mod_item", "module", "identifier"),
        ("const_item", "const", "identifier"),
        ("static_item", "static", "identifier"),
    ],
    "go": [
        ("type_declaration", "type", None),
        ("function_declaration", "function", "identifier"),
        ("method_declaration", "method", "field_identifier"),
    ],
    "java": [
        ("class_declaration", "class", "identifier"),
        ("interface_declaration", "interface", "identifier"),
        ("method_declaration", "method", "identifier"),
        ("enum_declaration", "enum", "identifier"),
        ("record_declaration", "record", "identifier"),
    ],
    "kotlin": [
        ("class_declaration", "class", "type_identifier"),
        ("function_declaration", "function", "simple_identifier"),
        ("object_declaration", "object", "type_identifier"),
    ],
    "ruby": [
        ("class", "class", "constant"),
        ("method", "method", "identifier"),
        ("module", "module", "constant"),
        ("singleton_method", "method", "identifier"),
    ],
    "c": [
        ("function_definition", "function", "identifier"),
        ("struct_specifier", "struct", "type_identifier"),
        ("enum_specifier", "enum", "type_identifier"),
        ("type_definition", "typedef", "type_identifier"),
    ],
    "cpp": [
        ("function_definition", "function", "identifier"),
        ("class_specifier", "class", "type_identifier"),
        ("struct_specifier", "struct", "type_identifier"),
        ("enum_specifier", "enum", "type_identifier"),
        ("namespace_definition", "namespace", "identifier"),
    ],
    "csharp": [
        ("class_declaration", "class", "identifier"),
        ("interface_declaration", "interface", "identifier"),
        ("method_declaration", "method", "identifier"),
        ("struct_declaration", "struct", "identifier"),
        ("enum_declaration", "enum", "identifier"),
        ("namespace_declaration", "namespace", "identifier"),
    ],
    "swift": [
        ("class_declaration", "class", "type_identifier"),
        ("function_declaration", "function", "simple_identifier"),
        ("struct_declaration", "struct", "type_identifier"),
        ("protocol_declaration", "protocol", "type_identifier"),
        ("enum_declaration", "enum", "type_identifier"),
    ],
    "php": [
        ("class_declaration", "class", "name"),
        ("function_definition", "function", "name"),
        ("method_declaration", "method", "name"),
        ("interface_declaration", "interface", "name"),
        ("trait_declaration", "trait", "name"),
    ],
    "scala": [
        ("class_definition", "class", "identifier"),
        ("object_definition", "object", "identifier"),
        ("function_definition", "function", "identifier"),
        ("trait_definition", "trait", "identifier"),
    ],
    "lua": [
        ("function_declaration", "function", "identifier"),
    ],
    "elixir": [
        ("call", "def", None),
    ],
}

# Extension → ast-grep language name
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python", ".pyi": "python", ".pyx": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".php": "php",
    ".scala": "scala",
    ".lua": "lua",
    ".ex": "elixir", ".exs": "elixir",
    ".md": "markdown", ".mdx": "markdown",
    ".rst": "restructuredtext",
    ".adoc": "asciidoc",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_language(path: str) -> Optional[str]:
    """Detect the ast-grep language name from a file path."""
    _, ext = os.path.splitext(path)
    return _EXT_TO_LANG.get(ext.lower())


def outline(
    content: str,
    path: str = "",
    language: Optional[str] = None,
) -> OutlineResult:
    """Extract an outline from source code.

    Args:
        content: Source code string (from MemFS or disk).
        path: File path (used for language detection if *language* is None).
        language: ast-grep language name override.

    Returns:
        OutlineResult with symbols, rendered outline, and symbol list.
    """
    lang = language or get_language(path)
    if not lang:
        return OutlineResult(
            symbols=[],
            language="unknown",
            total_lines=len(content.splitlines()),
            outline_text=f"# {path or 'file'}: unsupported language\n",
            symbols_text="",
        )

    lines = content.splitlines()
    total_lines = len(lines)

    # Dispatch to markdown outliner for document formats
    if lang == "markdown":
        return _outline_markdown(content, path, lines, total_lines)

    try:
        root = SgRoot(content, lang).root()
    except Exception as e:
        return OutlineResult(
            symbols=[],
            language=lang,
            total_lines=total_lines,
            outline_text=f"# {path or 'file'}: parse error: {e}\n",
            symbols_text="",
        )

    symbols = _extract_symbols(root, lang, lines)
    outline_text = _render_outline(symbols, lines, path)
    symbols_text = _render_symbols_list(symbols, path)

    return OutlineResult(
        symbols=symbols,
        language=lang,
        total_lines=total_lines,
        outline_text=outline_text,
        symbols_text=symbols_text,
    )


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------

def _extract_symbols(
    root: SgNode,
    lang: str,
    lines: list[str],
) -> List[Symbol]:
    """Walk the AST and extract definition symbols."""
    defs = _LANG_DEFS.get(lang, [])
    if not defs:
        return []

    kind_map = {ts_kind: (our_kind, name_kind) for ts_kind, our_kind, name_kind in defs}
    symbols = []

    for node in root.children():
        sym = _node_to_symbol(node, kind_map, lang, lines)
        if sym:
            symbols.append(sym)

    return symbols


def _node_to_symbol(
    node: SgNode,
    kind_map: dict[str, tuple[str, Optional[str]]],
    lang: str,
    lines: list[str],
) -> Optional[Symbol]:
    """Convert a tree-sitter node to a Symbol if it's a definition."""
    ts_kind = node.kind()

    # Handle decorated definitions (Python)
    if ts_kind == "decorated_definition":
        decorators = []
        inner = None
        for child in node.children():
            if child.kind() == "decorator":
                decorators.append(child.text().strip())
            elif child.kind() in ("class_definition", "function_definition"):
                inner = child
        if inner:
            sym = _node_to_symbol(inner, kind_map, lang, lines)
            if sym:
                sym.decorators = decorators
                sym.line = node.range().start.line
                return sym
        return None

    # Handle export statements (JS/TS) — unwrap to inner declaration
    if ts_kind == "export_statement":
        for child in node.children():
            if child.kind() in kind_map:
                sym = _node_to_symbol(child, kind_map, lang, lines)
                if sym:
                    return sym
        return None

    if ts_kind not in kind_map:
        return None

    our_kind, name_child_kind = kind_map[ts_kind]
    rng = node.range()

    # Extract name
    name = _extract_name(node, name_child_kind, our_kind)

    # Extract signature (first line of definition)
    sig = _extract_signature(node, lines)

    sym = Symbol(
        name=name,
        kind=our_kind,
        line=rng.start.line,
        end_line=rng.end.line,
        signature=sig,
    )

    # Extract children (methods, nested classes, etc.)
    sym.children = _extract_children(node, kind_map, lang, lines)

    return sym


def _extract_name(
    node: SgNode,
    name_child_kind: Optional[str],
    our_kind: str,
) -> str:
    """Extract the name of a definition node."""
    if name_child_kind:
        name_node = node.find(kind=name_child_kind)
        if name_node:
            return name_node.text()

    # Fallback: try common name kinds
    for kind in ("identifier", "type_identifier", "property_identifier", "name"):
        name_node = node.find(kind=kind)
        if name_node:
            return name_node.text()

    # Last resort: first line truncated
    text = node.text().split("\n")[0][:40]
    return f"<{our_kind}: {text}>"


def _extract_signature(node: SgNode, lines: list[str]) -> str:
    """Extract the signature (declaration line) of a definition."""
    start_line = node.range().start.line
    if start_line >= len(lines):
        return node.text().split("\n")[0]

    sig = lines[start_line].rstrip()

    # For multi-line signatures (e.g. Python function with long params),
    # include continuation lines that are part of the signature
    end_line = node.range().end.line
    line_idx = start_line + 1
    while line_idx <= min(end_line, start_line + 5):
        if line_idx >= len(lines):
            break
        next_line = lines[line_idx].rstrip()
        # Heuristic: signature continues if it has unclosed parens/brackets
        # or if it's a continuation line
        if _is_signature_continuation(sig, next_line):
            sig += "\n" + next_line
            line_idx += 1
        else:
            break

    return sig


def _is_signature_continuation(sig_so_far: str, next_line: str) -> bool:
    """Check if next_line continues a multi-line signature."""
    open_parens = sig_so_far.count("(") - sig_so_far.count(")")
    open_brackets = sig_so_far.count("[") - sig_so_far.count("]")
    open_braces = sig_so_far.count("{") - sig_so_far.count("}")

    if open_parens > 0 or open_brackets > 0:
        return True

    # Don't continue past opening brace
    stripped = next_line.strip()
    if stripped == "{" or stripped == "":
        return False

    return False


def _extract_children(
    node: SgNode,
    kind_map: dict[str, tuple[str, Optional[str]]],
    lang: str,
    lines: list[str],
) -> List[Symbol]:
    """Extract child definitions (methods, nested classes, etc.)."""
    children = []

    def walk(n: SgNode):
        for child in n.children():
            # Skip the node itself
            if child.range().start.line == node.range().start.line and child.kind() == node.kind():
                continue

            sym = _node_to_symbol(child, kind_map, lang, lines)
            if sym:
                # Reclassify top-level functions inside classes as methods
                if node.kind() in (
                    "class_definition", "class_declaration", "class_specifier",
                    "class", "impl_item",
                ) and sym.kind == "function":
                    sym.kind = "method"
                children.append(sym)
            elif child.kind() in ("block", "class_body", "declaration_list",
                                   "field_declaration_list", "body",
                                   "program", "statement_block"):
                walk(child)

    walk(node)
    return children


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_outline(
    symbols: List[Symbol],
    lines: list[str],
    path: str,
) -> str:
    """Render a condensed outline with ⋮ elision.

    Shows definition signatures with bodies replaced by ⋮.
    """
    if not symbols:
        return f"{path or 'file'}: no definitions found\n"

    parts = [f"{path or 'file'}:\n"]
    _render_symbols_tree(symbols, parts, indent=0)
    return "".join(parts)


def _render_symbols_tree(
    symbols: List[Symbol],
    parts: list[str],
    indent: int,
) -> None:
    """Recursively render symbols with indentation."""
    prefix = "│" + " " * 3 if indent > 0 else ""
    indent_str = "│   " * max(0, indent - 1) + prefix if indent > 0 else ""

    for sym in symbols:
        # Decorators
        for dec in sym.decorators:
            parts.append(f"{indent_str}{dec}\n")

        # Signature
        sig_lines = sym.signature.split("\n")
        parts.append(f"{indent_str}{sig_lines[0]}\n")
        for extra in sig_lines[1:]:
            parts.append(f"{indent_str}{extra}\n")

        if sym.children:
            child_indent = indent + 1
            # Show elision before children if there's likely setup code
            if sym.kind in ("class", "struct", "impl", "module", "namespace"):
                pass  # children are the content
            _render_symbols_tree(sym.children, parts, child_indent)
            parts.append(f"{indent_str}⋮\n")
        else:
            # Leaf definition — just show ⋮
            parts.append(f"{indent_str}    ⋮\n")


def _render_symbols_list(
    symbols: List[Symbol],
    path: str,
    indent: int = 0,
) -> str:
    """Render a compact symbol list with line numbers."""
    if not symbols:
        return ""

    parts = []
    prefix = "  " * indent

    for sym in symbols:
        line_num = sym.line + 1  # 1-indexed for display
        kind_tag = sym.kind
        deco = ""
        if sym.decorators:
            deco = f" [{', '.join(sym.decorators)}]"

        parts.append(f"{prefix}{line_num:>5}  {kind_tag:10s}  {sym.name}{deco}\n")

        if sym.children:
            parts.append(_render_symbols_list(sym.children, path, indent + 1))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Markdown outliner (using markdown-it-py)
# ---------------------------------------------------------------------------

def _outline_markdown(
    content: str,
    path: str,
    lines: list[str],
    total_lines: int,
) -> OutlineResult:
    """Extract outline from Markdown using markdown-it-py.

    Extracts: headings (nested by level), fenced code blocks, math blocks,
    and LaTeX ($$...$$ and $...$).
    """
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        # Fallback: regex-based heading extraction
        return _outline_markdown_regex(content, path, lines, total_lines)

    md = MarkdownIt()

    # Enable LaTeX math plugin if available
    try:
        from mdit_py_plugins.dollarmath import dollarmath_plugin
        dollarmath_plugin(md)
    except ImportError:
        pass

    tokens = md.parse(content)

    # Collect structural elements
    headings: list[tuple[int, str, int]] = []  # (level, text, line)
    code_blocks: list[tuple[str, str, int, int]] = []  # (lang, info, start, end)
    math_blocks: list[tuple[str, int, int]] = []  # (content_preview, start, end)
    math_inline_count = 0

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        if tok.type == "heading_open":
            level = int(tok.tag[1])  # h1 → 1, h2 → 2, etc.
            line = tok.map[0] if tok.map else 0
            # Next token is the inline content
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                text = tokens[i + 1].content
                # Count inline math in headings too
                if tokens[i + 1].children:
                    for child in tokens[i + 1].children:
                        if child.type in ("math_inline", "math_inline_dollar"):
                            math_inline_count += 1
            else:
                text = ""
            headings.append((level, text, line))

        elif tok.type == "fence":
            lang = tok.info.strip().split()[0] if tok.info else ""
            start = tok.map[0] if tok.map else 0
            end = tok.map[1] if tok.map else 0
            code_blocks.append((lang, tok.info.strip(), start, end))

        elif tok.type in ("math_block", "math_block_dollar"):
            start = tok.map[0] if tok.map else 0
            end = tok.map[1] if tok.map else 0
            preview = tok.content.strip().split("\n")[0][:50]
            math_blocks.append((preview, start, end))

        elif tok.type == "inline" and tok.children:
            for child in tok.children:
                if child.type in ("math_inline", "math_inline_dollar"):
                    math_inline_count += 1

        i += 1

    # Build symbols — headings form a hierarchy
    symbols = _build_heading_tree(headings)

    # Add code blocks and math blocks as flat symbols
    for lang, info, start, end in code_blocks:
        name = f"```{lang}" if lang else "```"
        if info and info != lang:
            name = f"```{info}"
        symbols.append(Symbol(
            name=name,
            kind="code_block",
            line=start,
            end_line=end - 1,
            signature=f"```{info}" if info else "```",
        ))

    for preview, start, end in math_blocks:
        symbols.append(Symbol(
            name=f"$$ {preview}",
            kind="math_block",
            line=start,
            end_line=end - 1,
            signature=f"$$ {preview} $$",
        ))

    # Sort all symbols by line
    symbols.sort(key=lambda s: s.line)

    # Render
    outline_text = _render_markdown_outline(headings, code_blocks, math_blocks,
                                            math_inline_count, path, total_lines)
    symbols_text = _render_symbols_list(symbols, path)

    return OutlineResult(
        symbols=symbols,
        language="markdown",
        total_lines=total_lines,
        outline_text=outline_text,
        symbols_text=symbols_text,
    )


def _build_heading_tree(
    headings: list[tuple[int, str, int]],
) -> List[Symbol]:
    """Build a nested symbol tree from flat heading list."""
    if not headings:
        return []

    # Simple approach: create flat list with level info
    # (nesting is shown in the outline renderer, not in the symbol tree)
    symbols = []
    for level, text, line in headings:
        symbols.append(Symbol(
            name=text,
            kind=f"h{level}",
            line=line,
            end_line=line,
            signature="#" * level + " " + text,
        ))
    return symbols


def _render_markdown_outline(
    headings: list[tuple[int, str, int]],
    code_blocks: list[tuple[str, str, int, int]],
    math_blocks: list[tuple[str, int, int]],
    math_inline_count: int,
    path: str,
    total_lines: int,
) -> str:
    """Render a markdown outline showing document structure."""
    parts = [f"{path or 'file'}: ({total_lines} lines)\n"]

    if not headings and not code_blocks and not math_blocks:
        parts.append("  (no structure found)\n")
        return "".join(parts)

    # Headings with indentation by level
    for level, text, line in headings:
        indent = "  " * (level - 1)
        parts.append(f"{indent}{'#' * level} {text}  (line {line + 1})\n")

    # Summary of code blocks and math
    if code_blocks:
        langs = [lang for lang, _, _, _ in code_blocks if lang]
        if langs:
            unique = sorted(set(langs))
            parts.append(f"\n  code blocks: {len(code_blocks)} ({', '.join(unique)})\n")
        else:
            parts.append(f"\n  code blocks: {len(code_blocks)}\n")

    if math_blocks or math_inline_count:
        math_parts = []
        if math_blocks:
            math_parts.append(f"{len(math_blocks)} block(s)")
        if math_inline_count:
            math_parts.append(f"{math_inline_count} inline")
        parts.append(f"  math/LaTeX: {', '.join(math_parts)}\n")

    return "".join(parts)


def _outline_markdown_regex(
    content: str,
    path: str,
    lines: list[str],
    total_lines: int,
) -> OutlineResult:
    """Fallback regex-based markdown outline when markdown-it-py is not installed."""
    import re

    symbols = []
    code_block_count = 0
    math_block_count = 0
    in_code = False
    in_math = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                in_code = False
            else:
                in_code = True
                code_block_count += 1
                lang = stripped[3:].strip().split()[0] if len(stripped) > 3 else ""
                symbols.append(Symbol(
                    name=f"```{lang}" if lang else "```",
                    kind="code_block",
                    line=i,
                    end_line=i,
                    signature=stripped,
                ))
            continue

        if stripped.startswith("$$"):
            if in_math:
                in_math = False
            else:
                in_math = True
                math_block_count += 1
                symbols.append(Symbol(
                    name="$$ ...",
                    kind="math_block",
                    line=i,
                    end_line=i,
                    signature="$$",
                ))
            continue

        if in_code or in_math:
            continue

        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            symbols.append(Symbol(
                name=text,
                kind=f"h{level}",
                line=i,
                end_line=i,
                signature=m.group(0),
            ))

    # Build headings list for renderer
    headings = [(int(s.kind[1]), s.name, s.line) for s in symbols if s.kind.startswith("h")]
    code_blocks_info = [(s.name.lstrip("`"), "", s.line, s.end_line) for s in symbols if s.kind == "code_block"]
    math_blocks_info = [(s.name, s.line, s.end_line) for s in symbols if s.kind == "math_block"]

    outline_text = _render_markdown_outline(headings, code_blocks_info, math_blocks_info, 0, path, total_lines)
    symbols_text = _render_symbols_list(symbols, path)

    return OutlineResult(
        symbols=symbols,
        language="markdown",
        total_lines=total_lines,
        outline_text=outline_text,
        symbols_text=symbols_text,
    )
