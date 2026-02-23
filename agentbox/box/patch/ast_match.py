"""AST-aware matching fallback for str_replace using ast-grep-py.

When text-based matching fails (exact, strip, fuzzy), this module
attempts to locate ``old_str`` structurally using tree-sitter AST
pattern matching. It runs on the **host Python** (Tier 3) since
ast-grep-py is a compiled Rust extension that cannot run in Pyodide.

The approach (Option A from the planning doc):
1. Parse both the file content and old_str with ast-grep
2. Extract the top-level AST node kind from old_str
3. Find all nodes of that kind in the file
4. Compare by structure similarity (normalized text)
5. Return the byte range for text-surgery replacement

Limitations:
- Only works for single AST node matches (one function, class,
  assignment — not arbitrary multi-statement code blocks)
- Requires ast-grep-py to be installed (graceful fallback if not)
- Language must be detectable from the file extension
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional


@dataclass
class ASTMatch:
    """Result of an AST-aware match."""

    start_offset: int
    end_offset: int
    matched_text: str
    similarity: float
    node_kind: str


def ast_find(
    content: str,
    old_str: str,
    path: str = "",
    threshold: float = 0.6,
) -> Optional[ASTMatch]:
    """Try to find ``old_str`` in ``content`` using AST structural matching.

    Returns an ``ASTMatch`` if a sufficiently similar AST node is found,
    otherwise ``None``.

    Args:
        content: The full file content.
        old_str: The code fragment to locate.
        path: File path (used to detect language).
        threshold: Minimum similarity ratio (0.0–1.0) to accept a match.

    Returns:
        ``ASTMatch`` with byte offsets and matched text, or ``None``.
    """
    try:
        from ast_grep_py import SgRoot
    except ImportError:
        return None

    lang = _detect_language(path)
    if not lang:
        return None

    # Parse the old_str to find its top-level AST node kind
    try:
        old_root = SgRoot(old_str, lang)
    except Exception:
        return None

    old_node = old_root.root()
    old_top_nodes = [c for c in old_node.children() if c.is_named()]
    if not old_top_nodes:
        return None

    # ast-grep only supports single-node patterns
    if len(old_top_nodes) > 1:
        return None

    old_top = old_top_nodes[0]
    target_kind = old_top.kind()
    old_normalized = _normalize_code(old_str)

    # Parse the file content
    try:
        file_root = SgRoot(content, lang)
    except Exception:
        return None

    file_node = file_root.root()

    # Find all nodes of the same kind in the file
    candidates = file_node.find_all(kind=target_kind)
    if not candidates:
        return None

    # Score each candidate by structural similarity
    best: Optional[ASTMatch] = None
    best_score = threshold

    for candidate in candidates:
        candidate_text = candidate.text()
        candidate_normalized = _normalize_code(candidate_text)

        # Quick length check — skip wildly different sizes
        len_ratio = min(len(old_normalized), len(candidate_normalized)) / max(
            len(old_normalized), len(candidate_normalized), 1
        )
        if len_ratio < 0.3:
            continue

        # Compute similarity on normalized text
        ratio = SequenceMatcher(
            None, old_normalized, candidate_normalized
        ).ratio()

        # Also check structural similarity: compare child node kinds
        old_children = [c.kind() for c in old_top.children() if c.is_named()]
        cand_children = [c.kind() for c in candidate.children() if c.is_named()]
        if old_children and cand_children:
            struct_ratio = SequenceMatcher(
                None, old_children, cand_children
            ).ratio()
            # Weight: 70% text similarity, 30% structure similarity
            ratio = 0.7 * ratio + 0.3 * struct_ratio

        # Name mismatch penalty: if old_str has identifiers (function/class
        # name) that don't appear in the candidate, apply heavy penalty
        old_name = _extract_name(old_top)
        cand_name = _extract_name(candidate)
        if old_name and cand_name and old_name != cand_name:
            ratio *= 0.5  # Heavy penalty for name mismatch

        if ratio > best_score:
            best_score = ratio
            r = candidate.range()
            best = ASTMatch(
                start_offset=r.start.index,
                end_offset=r.end.index,
                matched_text=candidate_text,
                similarity=ratio,
                node_kind=target_kind,
            )

    return best


def ast_replace(
    content: str,
    old_str: str,
    new_str: str,
    path: str = "",
    threshold: float = 0.6,
) -> Optional[str]:
    """Try AST-aware str_replace: find ``old_str`` by AST structure, replace with ``new_str``.

    Returns the new file content if a match was found, otherwise ``None``.
    """
    match = ast_find(content, old_str, path=path, threshold=threshold)
    if match is None:
        return None

    # Text surgery: replace the matched range with new_str
    # Preserve the indentation of the matched code.
    #
    # Key insight: content[:start_offset] already includes the leading
    # whitespace for the first line (the AST node offset is past indent).
    # So the first line of new_str needs NO extra indent — only lines 2+
    # need to be adjusted by the indent offset.
    new_lines = new_str.splitlines()

    if len(new_lines) > 1:
        # Detect indentation by looking at the content line at match start
        line_start = content.rfind("\n", 0, match.start_offset) + 1
        leading = content[line_start:match.start_offset]
        match_indent = len(leading) if leading.isspace() or leading == "" else 0
        old_indent = len(old_str.splitlines()[0]) - len(old_str.splitlines()[0].lstrip())
        indent_offset = match_indent - old_indent

        if indent_offset != 0:
            adjusted = [new_lines[0]]  # First line — no adjustment (indent in content prefix)
            for line in new_lines[1:]:
                if line.strip():
                    if indent_offset > 0:
                        adjusted.append(" " * indent_offset + line)
                    else:
                        remove = min(-indent_offset, len(line) - len(line.lstrip()))
                        adjusted.append(line[remove:])
                else:
                    adjusted.append(line)
            new_str = "\n".join(adjusted)

    return content[:match.start_offset] + new_str + content[match.end_offset:]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Extension → ast-grep language name (subset of outliner's map)
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin", ".kts": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".scala": "scala",
    ".lua": "lua",
}


def _detect_language(path: str) -> Optional[str]:
    """Detect ast-grep language from file path."""
    import os
    _, ext = os.path.splitext(path)
    return _EXT_TO_LANG.get(ext.lower())


def _extract_name(node) -> Optional[str]:
    """Extract the primary identifier name from an AST node.

    For function_definition → function name, class_definition → class name, etc.
    Returns None if no name can be extracted.
    """
    # Look for a direct 'name' field (works for most definition nodes)
    name_node = node.field("name")
    if name_node:
        return name_node.text()
    # Fallback: look for first identifier child
    for child in node.children():
        if child.kind() == "identifier":
            return child.text()
    return None


def _normalize_code(text: str) -> str:
    """Normalize code for comparison: collapse whitespace, strip comments."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)
