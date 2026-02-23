"""V4A diff parser and applier for MemFS.

Adapted from the OpenAI Agents SDK ``apply_diff.py`` (MIT License).
Pure Python, stdlib only, operates on strings (no filesystem access).

V4A format overview:
    *** Add File: path/to/new.py
    +line1
    +line2
    *** Update File: path/to/existing.py
    @@ anchor_line
     context_line
    -old_line
    +new_line
    *** Delete File: path/to/remove.py
    *** End Patch

Usage:
    from agentbox.box.patch.v4a import apply_v4a_diff, parse_v4a_patch

    # Single-file diff application
    new_content = apply_v4a_diff(old_content, diff_text)
    new_content = apply_v4a_diff("", diff_text, mode="create")

    # Multi-file patch parsing
    ops = parse_v4a_patch(patch_text)
    for op in ops:
        print(op.type, op.path, op.diff)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class PatchOperation:
    """A single file operation parsed from a V4A patch."""

    type: Literal["add", "update", "delete"]
    path: str
    diff: str = ""


@dataclass
class PatchResult:
    """Result of applying a single patch operation."""

    path: str
    success: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Multi-file patch parser
# ---------------------------------------------------------------------------

def parse_v4a_patch(patch_text: str) -> list[PatchOperation]:
    """Parse a V4A patch into a list of file operations.

    Handles ``*** Add File:``, ``*** Update File:``, ``*** Delete File:``,
    and ``*** End Patch`` markers.
    """
    lines = patch_text.split("\n")
    ops: list[PatchOperation] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):].strip()
            i += 1
            diff_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("***"):
                diff_lines.append(lines[i])
                i += 1
            ops.append(PatchOperation(type="add", path=path, diff="\n".join(diff_lines)))

        elif line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):].strip()
            i += 1
            diff_lines = []
            while i < len(lines) and not lines[i].startswith("***"):
                diff_lines.append(lines[i])
                i += 1
            ops.append(PatchOperation(type="update", path=path, diff="\n".join(diff_lines)))

        elif line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: "):].strip()
            ops.append(PatchOperation(type="delete", path=path))
            i += 1

        elif line.startswith("*** End Patch"):
            break

        else:
            i += 1

    return ops


# ---------------------------------------------------------------------------
# Single-file diff application (core V4A algorithm)
# ---------------------------------------------------------------------------

ApplyDiffMode = Literal["default", "create"]


@dataclass
class _Chunk:
    orig_index: int
    del_lines: list[str]
    ins_lines: list[str]


@dataclass
class _ParserState:
    lines: list[str]
    index: int = 0
    fuzz: int = 0


@dataclass
class _ParsedUpdateDiff:
    chunks: list[_Chunk]
    fuzz: int


@dataclass
class _ReadSectionResult:
    next_context: list[str]
    section_chunks: list[_Chunk]
    end_index: int
    eof: bool


@dataclass
class _ContextMatch:
    new_index: int
    fuzz: int


_END_PATCH = "*** End Patch"
_END_FILE = "*** End of File"
_SECTION_TERMINATORS = [
    _END_PATCH,
    "*** Update File:",
    "*** Delete File:",
    "*** Add File:",
]
_END_SECTION_MARKERS = [*_SECTION_TERMINATORS, _END_FILE]


def apply_v4a_diff(
    content: str,
    diff: str,
    mode: ApplyDiffMode = "default",
) -> str:
    """Apply a V4A diff to content and return the result.

    Args:
        content: Current file content (empty string for new files).
        diff: The V4A diff text (lines prefixed with +, -, or space).
        mode: ``"create"`` for new files (all lines must be ``+`` prefixed),
              ``"default"`` for updates with context hunks.

    Returns:
        The patched file content.

    Raises:
        ValueError: If the diff is malformed or context cannot be matched.
    """
    newline = _detect_newline(content, diff, mode)
    diff_lines = _normalize_diff_lines(diff)
    if mode == "create":
        return _parse_create_diff(diff_lines, newline=newline)

    normalized = _normalize_text_newlines(content)
    parsed = _parse_update_diff(diff_lines, normalized)
    return _apply_chunks(normalized, parsed.chunks, newline=newline)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_diff_lines(diff: str) -> list[str]:
    lines = [line.rstrip("\r") for line in re.split(r"\r?\n", diff)]
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _detect_newline_from_text(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _detect_newline(content: str, diff: str, mode: ApplyDiffMode) -> str:
    if mode != "create" and "\n" in content:
        return _detect_newline_from_text(content)
    return _detect_newline_from_text(diff)


def _normalize_text_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _is_done(state: _ParserState, prefixes: Sequence[str]) -> bool:
    if state.index >= len(state.lines):
        return True
    return any(state.lines[state.index].startswith(p) for p in prefixes)


def _read_str(state: _ParserState, prefix: str) -> str:
    if state.index >= len(state.lines):
        return ""
    current = state.lines[state.index]
    if current.startswith(prefix):
        state.index += 1
        return current[len(prefix):]
    return ""


def _parse_create_diff(lines: list[str], newline: str) -> str:
    parser = _ParserState(lines=[*lines, _END_PATCH])
    output: list[str] = []

    while not _is_done(parser, _SECTION_TERMINATORS):
        if parser.index >= len(parser.lines):
            break
        line = parser.lines[parser.index]
        parser.index += 1
        if not line.startswith("+"):
            raise ValueError(f"Invalid Add File Line: {line}")
        output.append(line[1:])

    return newline.join(output)


def _parse_update_diff(lines: list[str], content: str) -> _ParsedUpdateDiff:
    parser = _ParserState(lines=[*lines, _END_PATCH])
    input_lines = content.split("\n")
    chunks: list[_Chunk] = []
    cursor = 0

    while not _is_done(parser, _END_SECTION_MARKERS):
        anchor = _read_str(parser, "@@ ")
        has_bare_anchor = (
            anchor == ""
            and parser.index < len(parser.lines)
            and parser.lines[parser.index] == "@@"
        )
        if has_bare_anchor:
            parser.index += 1

        if not (anchor or has_bare_anchor or cursor == 0):
            current_line = (
                parser.lines[parser.index]
                if parser.index < len(parser.lines)
                else ""
            )
            raise ValueError(f"Invalid Line:\n{current_line}")

        if anchor.strip():
            cursor = _advance_cursor_to_anchor(anchor, input_lines, cursor, parser)

        section = _read_section(parser.lines, parser.index)
        find_result = _find_context(input_lines, section.next_context, cursor, section.eof)
        if find_result.new_index == -1:
            ctx_text = "\n".join(section.next_context)
            if section.eof:
                raise ValueError(f"Invalid EOF Context {cursor}:\n{ctx_text}")
            raise ValueError(f"Invalid Context {cursor}:\n{ctx_text}")

        cursor = find_result.new_index + len(section.next_context)
        parser.fuzz += find_result.fuzz
        parser.index = section.end_index

        for ch in section.section_chunks:
            chunks.append(
                _Chunk(
                    orig_index=ch.orig_index + find_result.new_index,
                    del_lines=list(ch.del_lines),
                    ins_lines=list(ch.ins_lines),
                )
            )

    return _ParsedUpdateDiff(chunks=chunks, fuzz=parser.fuzz)


def _advance_cursor_to_anchor(
    anchor: str,
    input_lines: list[str],
    cursor: int,
    parser: _ParserState,
) -> int:
    found = False

    if not any(line == anchor for line in input_lines[:cursor]):
        for i in range(cursor, len(input_lines)):
            if input_lines[i] == anchor:
                cursor = i + 1
                found = True
                break

    if not found and not any(
        line.strip() == anchor.strip() for line in input_lines[:cursor]
    ):
        for i in range(cursor, len(input_lines)):
            if input_lines[i].strip() == anchor.strip():
                cursor = i + 1
                parser.fuzz += 1
                found = True
                break

    return cursor


def _read_section(lines: list[str], start_index: int) -> _ReadSectionResult:
    context: list[str] = []
    del_lines: list[str] = []
    ins_lines: list[str] = []
    section_chunks: list[_Chunk] = []
    mode: Literal["keep", "add", "delete"] = "keep"
    index = start_index

    while index < len(lines):
        raw = lines[index]
        if (
            raw.startswith("@@")
            or raw.startswith(_END_PATCH)
            or raw.startswith("*** Update File:")
            or raw.startswith("*** Delete File:")
            or raw.startswith("*** Add File:")
            or raw.startswith(_END_FILE)
        ):
            break
        if raw == "***":
            break
        if raw.startswith("***"):
            raise ValueError(f"Invalid Line: {raw}")

        index += 1
        last_mode = mode
        line = raw if raw else " "
        prefix = line[0]
        if prefix == "+":
            mode = "add"
        elif prefix == "-":
            mode = "delete"
        elif prefix == " ":
            mode = "keep"
        else:
            raise ValueError(f"Invalid Line: {line}")

        line_content = line[1:]
        switching_to_context = mode == "keep" and last_mode != mode
        if switching_to_context and (del_lines or ins_lines):
            section_chunks.append(
                _Chunk(
                    orig_index=len(context) - len(del_lines),
                    del_lines=list(del_lines),
                    ins_lines=list(ins_lines),
                )
            )
            del_lines = []
            ins_lines = []

        if mode == "delete":
            del_lines.append(line_content)
            context.append(line_content)
        elif mode == "add":
            ins_lines.append(line_content)
        else:
            context.append(line_content)

    if del_lines or ins_lines:
        section_chunks.append(
            _Chunk(
                orig_index=len(context) - len(del_lines),
                del_lines=list(del_lines),
                ins_lines=list(ins_lines),
            )
        )

    if index < len(lines) and lines[index] == _END_FILE:
        return _ReadSectionResult(context, section_chunks, index + 1, True)

    if index == start_index:
        next_line = lines[index] if index < len(lines) else ""
        raise ValueError(f"Nothing in this section - index={index} {next_line}")

    return _ReadSectionResult(context, section_chunks, index, False)


def _find_context(
    lines: list[str],
    context: list[str],
    start: int,
    eof: bool,
) -> _ContextMatch:
    if eof:
        end_start = max(0, len(lines) - len(context))
        end_match = _find_context_core(lines, context, end_start)
        if end_match.new_index != -1:
            return end_match
        fallback = _find_context_core(lines, context, start)
        return _ContextMatch(new_index=fallback.new_index, fuzz=fallback.fuzz + 10000)
    return _find_context_core(lines, context, start)


def _find_context_core(
    lines: list[str],
    context: list[str],
    start: int,
) -> _ContextMatch:
    if not context:
        return _ContextMatch(new_index=start, fuzz=0)

    # Tier 1: exact match
    for i in range(start, len(lines)):
        if _equals_slice(lines, context, i, lambda v: v):
            return _ContextMatch(new_index=i, fuzz=0)
    # Tier 2: rstrip match
    for i in range(start, len(lines)):
        if _equals_slice(lines, context, i, lambda v: v.rstrip()):
            return _ContextMatch(new_index=i, fuzz=1)
    # Tier 3: strip match
    for i in range(start, len(lines)):
        if _equals_slice(lines, context, i, lambda v: v.strip()):
            return _ContextMatch(new_index=i, fuzz=100)

    return _ContextMatch(new_index=-1, fuzz=0)


def _equals_slice(
    source: list[str],
    target: list[str],
    start: int,
    map_fn: Callable[[str], str],
) -> bool:
    if start + len(target) > len(source):
        return False
    for offset, target_value in enumerate(target):
        if map_fn(source[start + offset]) != map_fn(target_value):
            return False
    return True


def _apply_chunks(content: str, chunks: list[_Chunk], newline: str) -> str:
    orig_lines = content.split("\n")
    dest_lines: list[str] = []
    cursor = 0

    for chunk in chunks:
        if chunk.orig_index > len(orig_lines):
            raise ValueError(
                f"applyDiff: chunk.origIndex {chunk.orig_index} > "
                f"input length {len(orig_lines)}"
            )
        if cursor > chunk.orig_index:
            raise ValueError(
                f"applyDiff: overlapping chunk at {chunk.orig_index} "
                f"(cursor {cursor})"
            )

        dest_lines.extend(orig_lines[cursor:chunk.orig_index])
        cursor = chunk.orig_index

        if chunk.ins_lines:
            dest_lines.extend(chunk.ins_lines)

        cursor += len(chunk.del_lines)

    dest_lines.extend(orig_lines[cursor:])
    return newline.join(dest_lines)
