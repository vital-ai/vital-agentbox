"""
Multi-tier string matching for LLM-generated edits.

Matching tiers (tried in order):
    1. Exact match — literal string comparison
    2. Right-stripped — rstrip() each line
    3. Stripped — strip() each line
    4. Normalized — Unicode punctuation + whitespace normalization

Inspired by apply-patch-py (MIT) search.py and Aider editblock (Apache 2.0).
All functions operate on plain strings — no filesystem I/O.
"""

from __future__ import annotations

import difflib
import math
import time
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Unicode normalization table
# ---------------------------------------------------------------------------

_UNICODE_REPLACEMENTS = {
    # Dashes / hyphens
    "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    # Single quotes
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    # Double quotes
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    # Spaces (non-breaking, em/en spaces, etc.)
    "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ",
    "\u2005": " ", "\u2006": " ", "\u2007": " ", "\u2008": " ",
    "\u2009": " ", "\u200a": " ", "\u202f": " ", "\u205f": " ",
    "\u3000": " ",
}


def normalise(text: str) -> str:
    """Normalize Unicode punctuation and whitespace, then strip."""
    return "".join(_UNICODE_REPLACEMENTS.get(c, c) for c in text.strip())


# ---------------------------------------------------------------------------
# 4-tier line sequence matching
# ---------------------------------------------------------------------------

def find_lines(
    lines: List[str],
    pattern: List[str],
    start: int = 0,
) -> Optional[int]:
    """Find *pattern* lines within *lines*, starting from *start*.

    Tries four matching tiers in order:
        1. Exact   — ``lines[i] == pattern[j]``
        2. Rstrip  — ``lines[i].rstrip() == pattern[j].rstrip()``
        3. Strip   — ``lines[i].strip() == pattern[j].strip()``
        4. Normalize — ``normalise(lines[i]) == normalise(pattern[j])``

    Returns the index of the first match, or None.
    """
    if not pattern:
        return start

    plen = len(pattern)
    if plen > len(lines):
        return None

    max_start = len(lines) - plen

    # Tier 1: exact
    for i in range(start, max_start + 1):
        if lines[i: i + plen] == pattern:
            return i

    # Tier 2: rstrip
    for i in range(start, max_start + 1):
        if all(lines[i + j].rstrip() == pattern[j].rstrip() for j in range(plen)):
            return i

    # Tier 3: strip
    for i in range(start, max_start + 1):
        if all(lines[i + j].strip() == pattern[j].strip() for j in range(plen)):
            return i

    # Tier 4: normalized
    for i in range(start, max_start + 1):
        if all(normalise(lines[i + j]) == normalise(pattern[j]) for j in range(plen)):
            return i

    return None


def count_matches(
    lines: List[str],
    pattern: List[str],
    start: int = 0,
) -> int:
    """Count how many positions in *lines* match *pattern* (any tier)."""
    if not pattern:
        return 0
    plen = len(pattern)
    count = 0
    for i in range(start, len(lines) - plen + 1):
        if (
            all(lines[i + j].rstrip() == pattern[j].rstrip() for j in range(plen))
            or all(lines[i + j].strip() == pattern[j].strip() for j in range(plen))
            or all(normalise(lines[i + j]) == normalise(pattern[j]) for j in range(plen))
        ):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Comment / blank detection (for smart fuzzy scoring)
# ---------------------------------------------------------------------------

_COMMENT_PREFIXES = {
    ".py": "#", ".sh": "#", ".bash": "#", ".yaml": "#", ".yml": "#",
    ".rb": "#", ".pl": "#", ".r": "#", ".R": "#",
    ".js": "//", ".ts": "//", ".tsx": "//", ".jsx": "//",
    ".c": "//", ".cpp": "//", ".h": "//", ".hpp": "//",
    ".java": "//", ".rs": "//", ".go": "//", ".swift": "//",
    ".kt": "//", ".scala": "//", ".cs": "//", ".php": "//",
    ".sql": "--", ".lua": "--", ".hs": "--",
    ".html": "<!--", ".xml": "<!--", ".md": "<!--",
}


def _is_comment_or_blank(line: str, ext: str = "") -> bool:
    """Return True if *line* is blank or starts with a comment prefix."""
    stripped = line.strip()
    if not stripped:
        return True
    prefix = _COMMENT_PREFIXES.get(ext, "#")
    return stripped.startswith(prefix)


# ---------------------------------------------------------------------------
# Fuzzy matching (anchor-based, bounded)
# ---------------------------------------------------------------------------

_FUZZY_MAX_SECONDS = 1.0
_FUZZY_MAX_EVALUATIONS = 20_000
_FUZZY_MAX_CANDIDATES = 2_000


def fuzzy_find(
    lines: List[str],
    pattern: List[str],
    start: int = 0,
    ext: str = "",
) -> Optional[Tuple[int, int]]:
    """Find the best fuzzy match for *pattern* in *lines*.

    Uses anchor-based candidate selection (rarest code lines first) and
    smart scoring that weights code lines higher than comments.

    Returns ``(start_index, match_length)`` or ``None``.
    """
    if not pattern:
        return None

    pat_len = len(pattern)
    lines_len = len(lines)
    scale = 0.3
    min_len = max(1, math.floor(pat_len * (1 - scale)))
    max_len = math.ceil(pat_len * (1 + scale))
    if min_len == max_len:
        max_len += 1

    # Normalize all lines once
    pattern_norm = [normalise(line) for line in pattern]
    current_norm = [normalise(line) for line in lines]

    # Code-line sets for quick intersection checks
    pattern_code = {
        normalise(line) for line in pattern
        if not _is_comment_or_blank(line, ext)
    }
    if not pattern_code:
        return None

    # Build position index for current lines
    positions: dict[str, list[int]] = {}
    for idx, nline in enumerate(current_norm):
        positions.setdefault(nline, []).append(idx)

    # Find anchor candidates (rarest code lines in pattern)
    anchors: list[tuple[int, int, str]] = []
    for pat_idx, raw_line in enumerate(pattern):
        if _is_comment_or_blank(raw_line, ext):
            continue
        key = normalise(raw_line)
        freq = len(positions.get(key, []))
        if freq:
            anchors.append((freq, pat_idx, key))
    anchors.sort(key=lambda x: x[0])
    anchors = anchors[:3]

    # Build candidate start positions from anchors
    candidate_starts: set[int] = set()
    for _, pat_idx, key in anchors:
        for pos in positions.get(key, []):
            base = pos - pat_idx
            for offset in (-2, -1, 0, 1, 2):
                s = base + offset
                if start <= s <= lines_len:
                    candidate_starts.add(s)

    # Add fallback sequential starts
    fallback_end = min(lines_len, start + _FUZZY_MAX_CANDIDATES)
    candidate_starts.update(range(start, fallback_end))

    sorted_starts = sorted(candidate_starts)
    if len(sorted_starts) > _FUZZY_MAX_CANDIDATES:
        sorted_starts = sorted_starts[:_FUZZY_MAX_CANDIDATES]

    # Search with budget
    best_score = 0.0
    best_start = -1
    best_len = -1
    deadline = time.monotonic() + _FUZZY_MAX_SECONDS
    evals = 0

    # Try exact length first, then shorter, then longer
    lengths = [pat_len] + [l for l in range(min_len, max_len + 1) if l != pat_len]
    for length in lengths:
        if length <= 0:
            continue
        for i in sorted_starts:
            if time.monotonic() > deadline or evals >= _FUZZY_MAX_EVALUATIONS:
                break
            if i + length > lines_len:
                continue

            chunk = lines[i: i + length]
            chunk_code = {
                normalise(line) for line in chunk
                if not _is_comment_or_blank(line, ext)
            }
            if len(chunk_code & pattern_code) < 2:
                evals += 1
                continue

            # Coarse check with SequenceMatcher
            chunk_norm = current_norm[i: i + length]
            ratio = difflib.SequenceMatcher(None, chunk_norm, pattern_norm).ratio()
            evals += 1
            if ratio <= 0.6:
                continue

            # Smart score (code lines weighted higher)
            score = _smart_score(chunk, pattern, ext)
            if score > best_score:
                best_score = score
                best_start = i
                best_len = length

        if time.monotonic() > deadline or evals >= _FUZZY_MAX_EVALUATIONS:
            break

    if best_score >= 0.9:
        return best_start, best_len
    return None


def _smart_score(
    chunk_lines: List[str],
    pattern_lines: List[str],
    ext: str = "",
) -> float:
    """Weighted similarity: code lines 1.0, comment/blank lines 0.1."""
    # Safety gate: if >=3 code lines in pattern and zero match exactly, reject
    code_lines = [l for l in pattern_lines if not _is_comment_or_blank(l, ext)]
    if len(code_lines) >= 3:
        chunk_code_set = {
            normalise(l) for l in chunk_lines
            if not _is_comment_or_blank(l, ext)
        }
        if not any(normalise(l) in chunk_code_set for l in code_lines):
            return 0.0

    chunk_norm = [l.strip() for l in chunk_lines]
    pattern_norm = [l.strip() for l in pattern_lines]
    matcher = difflib.SequenceMatcher(None, chunk_norm, pattern_norm)

    total_weight = 0.0
    weighted_score = 0.0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                is_code = not _is_comment_or_blank(pattern_norm[j1 + k], ext)
                w = 1.0 if is_code else 0.1
                weighted_score += w
                total_weight += w
        elif tag == "replace":
            min_span = min(i2 - i1, j2 - j1)
            for k in range(min_span):
                is_code = not _is_comment_or_blank(pattern_norm[j1 + k], ext)
                w = 1.0 if is_code else 0.1
                total_weight += w
                if is_code:
                    if normalise(chunk_norm[i1 + k]) == normalise(pattern_norm[j1 + k]):
                        weighted_score += w
                else:
                    sim = difflib.SequenceMatcher(
                        None, chunk_norm[i1 + k], pattern_norm[j1 + k]
                    ).ratio()
                    weighted_score += sim * w
            # Extra unmatched pattern lines in replace block
            for k in range(min_span, j2 - j1):
                is_code = not _is_comment_or_blank(pattern_norm[j1 + k], ext)
                w = 1.0 if is_code else 0.1
                total_weight += w  # score stays 0 → penalizes
        elif tag == "insert":
            # Pattern lines not present in chunk — penalize
            for k in range(j2 - j1):
                is_code = not _is_comment_or_blank(pattern_norm[j1 + k], ext)
                w = 1.0 if is_code else 0.1
                total_weight += w  # score stays 0
        # 'delete' = extra chunk lines not in pattern — ignore (no penalty)

    return weighted_score / total_weight if total_weight > 0 else 0.0


# ---------------------------------------------------------------------------
# Closest-match hint (for error messages)
# ---------------------------------------------------------------------------

def find_similar_lines(
    search_lines: List[str],
    content_lines: List[str],
    threshold: float = 0.6,
) -> Optional[Tuple[int, float, List[str]]]:
    """Find the most similar block in *content_lines*.

    Returns ``(start_line_0indexed, similarity, matched_lines)`` or None.
    """
    if not search_lines or not content_lines:
        return None

    best_ratio = 0.0
    best_idx = 0
    slen = len(search_lines)

    for i in range(len(content_lines) - slen + 1):
        chunk = content_lines[i: i + slen]
        # Character-level comparison (join lines) for better granularity
        search_text = "\n".join(search_lines)
        chunk_text = "\n".join(chunk)
        ratio = difflib.SequenceMatcher(None, search_text, chunk_text).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_idx = i

    if best_ratio < threshold:
        return None

    # Include some surrounding context
    ctx = 3
    ctx_start = max(0, best_idx - ctx)
    ctx_end = min(len(content_lines), best_idx + slen + ctx)
    return best_idx, best_ratio, content_lines[ctx_start:ctx_end]
