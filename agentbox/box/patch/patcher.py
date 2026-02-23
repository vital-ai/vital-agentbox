"""
MemFS-native file patcher for LLM agent edits.

Operates entirely on strings — no filesystem I/O. The caller (shell builtin)
is responsible for reading/writing files via MemFS.

Modes:
    - str_replace(content, old_str, new_str) → new content
    - insert(content, after_line, text) → new content
    - view(content, range) → line-numbered excerpt
    - create(content) → validated content for new file

Inspired by OpenHands OHEditor (MIT), apply-patch-py (MIT), and
Aider editblock (Apache 2.0). New original code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from agentbox.box.patch.search import (
    count_matches,
    find_lines,
    find_similar_lines,
    fuzzy_find,
    normalise,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PatchResult:
    """Result of a patch operation."""
    success: bool
    new_content: Optional[str] = None
    message: str = ""
    snippet: str = ""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_VIEW_LINES = 300
SNIPPET_CONTEXT = 4
MAX_LINE_DISPLAY = 200
LONG_LINE_THRESHOLD = 500


# ---------------------------------------------------------------------------
# str_replace
# ---------------------------------------------------------------------------

def str_replace(
    content: str,
    old_str: str,
    new_str: str,
    path: str = "",
) -> PatchResult:
    """Replace *old_str* with *new_str* in *content*.

    Enforces uniqueness: exactly one match required. Uses 4-tier matching
    with indent-offset detection. Shows helpful error on failure.
    """
    if old_str == new_str:
        return PatchResult(
            success=False,
            message="edit: old_str and new_str are identical. No changes made.",
        )

    lines = content.splitlines(keepends=True)
    old_lines = old_str.splitlines(keepends=True)
    ext = _ext(path)

    # --- Try direct string match first (preserves exact formatting) ---
    occurrences = content.count(old_str)
    if occurrences == 1:
        new_content = content.replace(old_str, new_str, 1)
        return _success(new_content, old_str, new_str, path)

    if occurrences > 1:
        # Find line numbers of each occurrence
        match_lines = _find_occurrence_lines(content, old_str)
        return PatchResult(
            success=False,
            message=(
                f"edit: old_str matches {occurrences} locations "
                f"(lines {', '.join(str(l) for l in match_lines)}). "
                "Add more context to make it unique."
            ),
        )

    # --- Direct match failed (0 occurrences). Try line-based tiers. ---
    old_lines_stripped = old_str.splitlines()
    content_lines = content.splitlines()

    idx = find_lines(content_lines, old_lines_stripped, start=0)
    if idx is not None:
        # Count matches to enforce uniqueness
        n = count_matches(content_lines, old_lines_stripped, start=0)
        if n > 1:
            return PatchResult(
                success=False,
                message=(
                    f"edit: old_str matches {n} locations after whitespace "
                    "normalization. Add more context to make it unique."
                ),
            )
        # Apply with indent preservation
        new_content = _apply_line_replacement(
            content_lines, old_lines_stripped, new_str.splitlines(), idx
        )
        return _success(new_content, old_str, new_str, path, fuzzy=True)

    # --- Try indent-offset matching (Aider-inspired) ---
    result = _try_indent_offset(content_lines, old_lines_stripped, new_str.splitlines())
    if result is not None:
        return _success(result, old_str, new_str, path, fuzzy=True)

    # --- Try fuzzy matching ---
    fuzzy = fuzzy_find(content_lines, old_lines_stripped, start=0, ext=ext)
    if fuzzy is not None:
        fidx, flen = fuzzy
        new_lines = new_str.splitlines()
        replaced = content_lines[:fidx] + new_lines + content_lines[fidx + flen:]
        new_content = "\n".join(replaced)
        if content.endswith("\n"):
            new_content += "\n"
        return _success(new_content, old_str, new_str, path, fuzzy=True)

    # --- Try AST-aware matching (Tier 3, host-only, optional) ---
    if path:
        try:
            from agentbox.box.patch.ast_match import ast_replace
            ast_result = ast_replace(content, old_str, new_str, path=path)
            if ast_result is not None:
                return _success(ast_result, old_str, new_str, path, fuzzy=True)
        except Exception:
            pass  # ast-grep not available or parse error — fall through

    # --- All tiers failed. Build helpful error. ---
    return _not_found_error(content_lines, old_lines_stripped, path)


# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------

def insert(
    content: str,
    line_number: int,
    text: str,
    path: str = "",
) -> PatchResult:
    """Insert *text* after *line_number* (1-indexed). 0 = prepend."""
    lines = content.splitlines(keepends=True)
    total = len(lines)

    if line_number < 0 or line_number > total:
        return PatchResult(
            success=False,
            message=(
                f"edit: line_number {line_number} out of range "
                f"(file has {total} lines, valid: 0-{total})."
            ),
        )

    insert_lines = text.splitlines(keepends=True)
    # Ensure last insert line has newline
    if insert_lines and not insert_lines[-1].endswith("\n"):
        insert_lines[-1] += "\n"

    new_lines = lines[:line_number] + insert_lines + lines[line_number:]
    new_content = "".join(new_lines)

    snippet = _make_snippet_around(
        new_content.splitlines(), line_number, len(insert_lines)
    )
    return PatchResult(
        success=True,
        new_content=new_content,
        message=f"edit: inserted {len(insert_lines)} line(s) after line {line_number}.",
        snippet=snippet,
    )


# ---------------------------------------------------------------------------
# view
# ---------------------------------------------------------------------------

def view(
    content: str,
    start: int = 1,
    end: Optional[int] = None,
    path: str = "",
) -> PatchResult:
    """Return line-numbered excerpt of *content*.

    *start* and *end* are 1-indexed, inclusive.
    """
    lines = content.splitlines()
    total = len(lines)

    if end is None:
        end = min(total, start + MAX_VIEW_LINES - 1)
    end = min(end, total)

    if start < 1:
        start = 1
    if start > total:
        return PatchResult(
            success=True,
            message=f"edit: {path or 'file'} has {total} lines.",
            snippet="",
        )

    # Detect long-line files (minified JS/CSS, JSON blobs, etc.)
    max_len = max((len(l) for l in lines), default=0)
    is_long_line = max_len > LONG_LINE_THRESHOLD

    numbered = []
    for i in range(start - 1, end):
        numbered.append(f"{i + 1:>6}\t{_truncate_line(lines[i])}")
    output = "\n".join(numbered)

    truncated = ""
    if end < total:
        truncated = f"\n[... {total - end} more line(s). Use --range {end + 1}:{min(end + MAX_VIEW_LINES, total)} to see more.]"

    extra = ""
    if is_long_line:
        avg_len = sum(len(l) for l in lines) // max(total, 1)
        extra = f" [long lines detected: max {max_len} chars, avg {avg_len} chars]"

    return PatchResult(
        success=True,
        message=f"{path or 'file'} ({total} lines){extra}",
        snippet=output + truncated,
    )


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

# Regex patterns for common definitions by file extension
_DEF_PATTERNS = {
    ".py": [
        (r"^\s*class\s+(\w+)", "classes"),
        (r"^\s*def\s+(\w+)", "functions"),
        (r"^\s*(?:import|from)\s+", "imports"),
    ],
    ".js": [
        (r"^\s*class\s+(\w+)", "classes"),
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "functions"),
        (r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", "functions"),
        (r"^\s*(?:import|export)\s+", "imports"),
    ],
    ".ts": [
        (r"^\s*(?:export\s+)?class\s+(\w+)", "classes"),
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "functions"),
        (r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", "functions"),
        (r"^\s*(?:import|export)\s+", "imports"),
        (r"^\s*(?:export\s+)?interface\s+(\w+)", "interfaces"),
        (r"^\s*(?:export\s+)?type\s+(\w+)", "types"),
    ],
    ".java": [
        (r"^\s*(?:public|private|protected)?\s*class\s+(\w+)", "classes"),
        (r"^\s*(?:public|private|protected)?\s*\w+\s+(\w+)\s*\(", "methods"),
        (r"^\s*import\s+", "imports"),
    ],
    ".go": [
        (r"^\s*type\s+(\w+)\s+struct", "structs"),
        (r"^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(", "functions"),
        (r"^\s*import\s+", "imports"),
    ],
    ".rs": [
        (r"^\s*(?:pub\s+)?struct\s+(\w+)", "structs"),
        (r"^\s*(?:pub\s+)?fn\s+(\w+)", "functions"),
        (r"^\s*(?:pub\s+)?enum\s+(\w+)", "enums"),
        (r"^\s*use\s+", "imports"),
    ],
    ".rb": [
        (r"^\s*class\s+(\w+)", "classes"),
        (r"^\s*def\s+(\w+)", "methods"),
        (r"^\s*require\s+", "imports"),
    ],
    ".c": [
        (r"^\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{", "functions"),
        (r"^\s*#include\s+", "includes"),
        (r"^\s*typedef\s+struct\s+(\w+)", "structs"),
    ],
    ".cpp": [
        (r"^\s*class\s+(\w+)", "classes"),
        (r"^\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{", "functions"),
        (r"^\s*#include\s+", "includes"),
    ],
}

# Aliases
_DEF_PATTERNS[".tsx"] = _DEF_PATTERNS[".ts"]
_DEF_PATTERNS[".jsx"] = _DEF_PATTERNS[".js"]
_DEF_PATTERNS[".h"] = _DEF_PATTERNS[".c"]
_DEF_PATTERNS[".hpp"] = _DEF_PATTERNS[".cpp"]

def info(content: str, path: str = "") -> PatchResult:
    """Return a summary of the file: size, lines, format, definitions.

    Uses python-magic (libmagic) on the host for accurate type detection,
    with fallback to extension + content heuristics.
    """
    import re
    from collections import defaultdict
    from agentbox.box.patch.filetype import detect_file_type

    lines = content.splitlines()
    total_lines = len(lines)
    size_bytes = len(content.encode("utf-8"))

    fmt_name, ext, mime = detect_file_type(content, path)

    # Size formatting
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    # Line endings
    crlf = content.count("\r\n")
    lf = content.count("\n") - crlf
    if crlf and lf:
        endings = "mixed (CRLF + LF)"
    elif crlf:
        endings = "CRLF"
    else:
        endings = "LF"

    trailing_nl = "yes" if content.endswith("\n") else "no"

    # Common indentation
    indents = []
    for line in lines:
        if line and not line.isspace():
            leading = len(line) - len(line.lstrip())
            if leading > 0:
                if line[0] == "\t":
                    indents.append("tab")
                else:
                    indents.append(leading)
    if indents:
        tab_count = sum(1 for i in indents if i == "tab")
        if tab_count > len(indents) // 2:
            indent_str = "tabs"
        else:
            space_indents = [i for i in indents if isinstance(i, int)]
            if space_indents:
                # Find most common indent step (GCD-like)
                from math import gcd
                from functools import reduce
                step = reduce(gcd, space_indents)
                indent_str = f"{step} spaces"
            else:
                indent_str = "mixed"
    else:
        indent_str = "none"

    # Blank lines
    blank_count = sum(1 for line in lines if not line.strip())

    # Line length stats
    line_lengths = [len(l) for l in lines] if lines else [0]
    max_line_len = max(line_lengths)
    avg_line_len = sum(line_lengths) // max(len(line_lengths), 1)
    is_long_line = max_line_len > LONG_LINE_THRESHOLD

    # Build output
    ext_display = ext if ext else "(no ext)"
    header = f"{path or 'file'}: {fmt_name} ({ext_display}), {total_lines} lines, {size_str}"
    parts = [header]
    if mime:
        parts.append(f"  mime: {mime}")
    parts.append(f"  indent: {indent_str}")
    parts.append(f"  line endings: {endings}")
    parts.append(f"  trailing newline: {trailing_nl}")
    parts.append(f"  blank lines: {blank_count}")
    if is_long_line:
        parts.append(f"  ⚠ long lines: max {max_line_len} chars, avg {avg_line_len} chars")
        if total_lines <= 3:
            parts.append(f"  ⚠ likely minified/serialized — edits should use character offsets")

    # Definition extraction — prefer ast-grep (accurate AST), fall back to regex
    used_ast = False
    try:
        from agentbox.box.outline.outliner import outline as _outline
        result = _outline(content, path=path)
        if result.symbols:
            used_ast = True
            # Group symbols by kind
            by_kind: dict[str, list[tuple[str, int]]] = defaultdict(list)
            def _collect(syms, depth=0):
                for sym in syms:
                    kind_plural = _pluralize(sym.kind)
                    by_kind[kind_plural].append((sym.name, sym.line + 1))
                    if sym.children:
                        _collect(sym.children, depth + 1)
            _collect(result.symbols)

            for kind_name in by_kind:
                items = by_kind[kind_name]
                named = [f"{name}:{ln}" for name, ln in items]
                if len(named) <= 8:
                    parts.append(f"  {kind_name}: {len(items)} ({', '.join(named)})")
                else:
                    shown = ', '.join(named[:6])
                    parts.append(f"  {kind_name}: {len(items)} ({shown}, ...)")
    except ImportError:
        pass

    if not used_ast:
        # Regex fallback (when ast-grep-py is not available)
        patterns = _DEF_PATTERNS.get(ext, [])
        if patterns:
            defs: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for i, line in enumerate(lines):
                for pat, category in patterns:
                    m = re.match(pat, line)
                    if m:
                        name = m.group(1) if m.lastindex else ""
                        defs[category].append((name, i + 1))
                        break

            for category in dict.fromkeys(cat for _, cat in patterns):
                items = defs.get(category, [])
                if not items:
                    continue
                if all(name == "" for name, _ in items):
                    line_nums = [str(ln) for _, ln in items]
                    if len(line_nums) <= 5:
                        parts.append(f"  {category}: {len(items)} (lines {', '.join(line_nums)})")
                    else:
                        parts.append(f"  {category}: {len(items)} (lines {line_nums[0]}-{line_nums[-1]})")
                else:
                    named = [f"{name}:{ln}" for name, ln in items]
                    if len(named) <= 8:
                        parts.append(f"  {category}: {len(items)} ({', '.join(named)})")
                    else:
                        shown = ', '.join(named[:6])
                        parts.append(f"  {category}: {len(items)} ({shown}, ...)")

    output = "\n".join(parts)
    return PatchResult(success=True, message=output, snippet="")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def create(content: str, path: str = "") -> PatchResult:
    """Validate content for a new file creation."""
    if not content:
        content = ""
    return PatchResult(
        success=True,
        new_content=content,
        message=f"edit: created {path}" if path else "edit: file created.",
    )


# ---------------------------------------------------------------------------
# diff_preview
# ---------------------------------------------------------------------------

def diff_preview(
    content: str,
    old_str: str,
    new_str: str,
    path: str = "",
    context_lines: int = 3,
) -> PatchResult:
    """Dry-run preview: show what *str_replace* would change as a unified diff.

    Does NOT modify the file. Returns a diff snippet with ±N context lines
    around each changed section.
    """
    import difflib

    # First, run str_replace to get the new content (without writing)
    result = str_replace(content, old_str, new_str, path=path)
    if not result.success:
        return result  # Pass through the error

    old_lines = content.splitlines(keepends=True)
    new_lines = result.new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}" if path else "a/file",
        tofile=f"b/{path}" if path else "b/file",
        n=context_lines,
    )
    diff_text = "".join(diff)

    if not diff_text:
        return PatchResult(
            success=True,
            message="edit: no changes (files are identical).",
            snippet="",
        )

    # Truncate long lines in diff output
    diff_lines = diff_text.splitlines()
    truncated_lines = []
    for dl in diff_lines:
        if dl.startswith("---") or dl.startswith("+++") or dl.startswith("@@"):
            truncated_lines.append(dl)
        elif len(dl) > MAX_LINE_DISPLAY + 20:
            prefix = dl[0] if dl[0] in ("+", "-", " ") else ""
            truncated_lines.append(
                prefix + _truncate_line(dl[len(prefix):])
            )
        else:
            truncated_lines.append(dl)
    diff_text = "\n".join(truncated_lines)

    # Count additions/deletions
    adds = sum(1 for l in truncated_lines if l.startswith("+") and not l.startswith("+++"))
    dels = sum(1 for l in truncated_lines if l.startswith("-") and not l.startswith("---"))

    return PatchResult(
        success=True,
        message=f"edit: dry run — {dels} line(s) removed, {adds} line(s) added. No changes written.",
        snippet=diff_text.rstrip("\n"),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pluralize(kind: str) -> str:
    """Pluralize a symbol kind for display."""
    _PLURALS = {
        "class": "classes", "function": "functions", "method": "methods",
        "struct": "structs", "enum": "enums", "trait": "traits",
        "interface": "interfaces", "type": "types", "module": "modules",
        "impl": "impls", "const": "consts", "static": "statics",
        "namespace": "namespaces", "variable": "variables",
        "object": "objects", "record": "records", "protocol": "protocols",
        "typedef": "typedefs", "export": "exports", "decorated": "decorated",
    }
    return _PLURALS.get(kind, kind + "s")


def _ext(path: str) -> str:
    """Extract file extension including dot."""
    _, ext = os.path.splitext(path)
    return ext.lower()


def _find_occurrence_lines(content: str, old_str: str) -> List[int]:
    """Find 1-indexed line numbers where *old_str* starts in *content*."""
    result = []
    start = 0
    while True:
        idx = content.find(old_str, start)
        if idx == -1:
            break
        line_num = content[:idx].count("\n") + 1
        result.append(line_num)
        start = idx + 1
    return result


def _apply_line_replacement(
    content_lines: List[str],
    old_lines: List[str],
    new_lines: List[str],
    idx: int,
) -> str:
    """Replace lines at *idx* with *new_lines*, preserving indent."""
    # Detect indent offset between matched content and old_lines
    if content_lines[idx].strip() and old_lines[0].strip():
        content_indent = len(content_lines[idx]) - len(content_lines[idx].lstrip())
        old_indent = len(old_lines[0]) - len(old_lines[0].lstrip())
        offset = content_indent - old_indent
    else:
        offset = 0

    if offset != 0:
        adjusted = []
        for line in new_lines:
            if line.strip():
                if offset > 0:
                    adjusted.append(" " * offset + line)
                else:
                    # Remove leading whitespace (but don't go negative)
                    remove = min(-offset, len(line) - len(line.lstrip()))
                    adjusted.append(line[remove:])
            else:
                adjusted.append(line)
        new_lines = adjusted

    replaced = content_lines[:idx] + new_lines + content_lines[idx + len(old_lines):]
    return "\n".join(replaced) + "\n"


def _try_indent_offset(
    content_lines: List[str],
    old_lines: List[str],
    new_lines: List[str],
) -> Optional[str]:
    """Try matching with uniform indent offset (Aider-inspired).

    If old_lines match content after adjusting for a consistent leading
    whitespace difference, apply the replacement with that offset.
    """
    if not old_lines:
        return None

    # Strip all leading whitespace from old_lines
    leading = [len(l) - len(l.lstrip()) for l in old_lines if l.strip()]
    if not leading:
        return None
    min_lead = min(leading)
    stripped_old = [l[min_lead:] if l.strip() else l for l in old_lines]

    plen = len(stripped_old)
    for i in range(len(content_lines) - plen + 1):
        chunk = content_lines[i: i + plen]
        # Check if all non-blank lines match after lstrip
        if not all(chunk[j].lstrip() == stripped_old[j].lstrip() for j in range(plen)):
            continue

        # Compute the uniform offset
        offsets = set()
        for j in range(plen):
            if chunk[j].strip():
                c_lead = len(chunk[j]) - len(chunk[j].lstrip())
                o_lead = len(stripped_old[j]) - len(stripped_old[j].lstrip())
                offsets.add(c_lead - o_lead)

        if len(offsets) != 1:
            continue

        offset = offsets.pop()
        # Apply offset to new_lines
        adjusted = []
        for line in new_lines:
            if line.strip():
                # Remove min_lead from new_lines (same as we did to old) then add offset
                cur_lead = len(line) - len(line.lstrip())
                new_lead = max(0, cur_lead - min_lead + offset)
                adjusted.append(" " * new_lead + line.lstrip())
            else:
                adjusted.append(line)

        replaced = content_lines[:i] + adjusted + content_lines[i + plen:]
        return "\n".join(replaced) + "\n"

    return None


def _success(
    new_content: str,
    old_str: str,
    new_str: str,
    path: str,
    fuzzy: bool = False,
) -> PatchResult:
    """Build a success result with context snippet."""
    lines = new_content.splitlines()
    new_start_lines = new_str.splitlines()

    # Find where the replacement landed
    idx = find_lines(lines, new_start_lines) if new_start_lines else None
    snippet = ""
    if idx is not None:
        snippet = _make_snippet_around(lines, idx, len(new_start_lines))

    msg = "edit: applied."
    if fuzzy:
        msg = "edit: applied (fuzzy match)."

    return PatchResult(
        success=True,
        new_content=new_content,
        message=msg,
        snippet=snippet,
    )


def _not_found_error(
    content_lines: List[str],
    old_lines: List[str],
    path: str,
) -> PatchResult:
    """Build a helpful 'not found' error with closest-match hint."""
    fname = path or "file"
    total = len(content_lines)

    hint = find_similar_lines(old_lines, content_lines)
    if hint is not None:
        idx, ratio, context = hint
        context_str = "\n".join(f"  {l}" for l in context)
        return PatchResult(
            success=False,
            message=(
                f"edit: old_str not found in {fname} ({total} lines). "
                f"Closest match at line {idx + 1} "
                f"(similarity {ratio:.0%}):\n{context_str}\n"
                f"Use 'edit {fname} --view' to see full contents."
            ),
        )

    return PatchResult(
        success=False,
        message=(
            f"edit: old_str not found in {fname} ({total} lines). "
            f"Use 'edit {fname} --view' to see contents."
        ),
    )


def _truncate_line(line: str, max_len: int = MAX_LINE_DISPLAY) -> str:
    """Truncate a line if it exceeds *max_len*, showing char count."""
    if len(line) <= max_len:
        return line
    return line[:max_len] + f"... [{len(line)} chars total]"


def _make_snippet_around(
    lines: List[str],
    start: int,
    length: int,
) -> str:
    """Return a line-numbered snippet around the edited region."""
    ctx = SNIPPET_CONTEXT
    snippet_start = max(0, start - ctx)
    snippet_end = min(len(lines), start + length + ctx)
    numbered = []
    for i in range(snippet_start, snippet_end):
        numbered.append(f"{i + 1:>6}\t{_truncate_line(lines[i])}")
    return "\n".join(numbered)
