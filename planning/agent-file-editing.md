# Agent File Editing — Planning Document

> How should AI agents running inside AgentBox sandboxes edit files?

---

## Problem Statement

Agents in AgentBox currently edit files using:

1. **`echo "..." > file`** — full overwrite, error-prone for large files
2. **`cat << 'EOF' > file`** — heredoc, same full-overwrite problem
3. **`sed -i 's/old/new/g' file`** — our sed builtin only supports `s///`,
   no multi-line, no line addressing, no append/insert/delete commands
4. **`python -c "..."`** — works but verbose, awkward escaping

These all fail in predictable ways for AI agents:

- **Whitespace mismatches**: LLM output differs in indentation from file
- **Ambiguous matches**: `old_str` appears multiple times in the file
- **Placeholder hallucinations**: LLM writes `# rest stays the same` instead
  of actual code
- **Large file context blow-up**: rewriting 500-line files wastes tokens and
  introduces drift
- **Escaping hell**: shell quoting for multi-line Python/JSON is fragile

**Goal**: Provide agents with a robust, token-efficient file editing tool
that handles the common failure modes gracefully.

---

## Industry Research

### How Leading AI Coding Agents Edit Files

| System | Format | Matching Strategy | Key Innovation |
|--------|--------|-------------------|----------------|
| **OpenAI Codex** | V4A Patch (`*** Begin/End Patch`) | Exact → trim endings → trim all WS | `@@` anchor lines (no line numbers), structured JSON error feedback |
| **Aider** | Search/Replace blocks (`<<<<<<< SEARCH` / `>>>>>>> REPLACE`) | Exact → stripped → flexible WS | Pluggable format architecture, per-model format selection |
| **Gemini CLI** | `smart-edit` tool (`old_string`/`new_string` + `instruction`) | Exact → flexible WS → regex → **LLM self-correction** | Falls back to a second LLM call with `instruction` to fix mismatches |
| **RooCode** | Search/Replace + optional `:start_line:` hint | Middle-out Levenshtein fuzzy | Sophisticated indentation preservation (capture original + apply relative) |
| **Cursor** | Two-step: Sketch → Apply model | Specialized fine-tuned apply model | Separates *what* to change from *how* to integrate it |
| **OpenHands** | Multiple (unified diff, git diff, ed scripts, str_replace) | Pattern detection + whitespace normalization | Optional "draft editor" LLM for complex rewrites |
| **Q CLI (AWS)** | `fs_write` with modes: `create`, `str_replace`, `insert`, `append` | Exact match only (error if 0 or >1 matches) | Simple but effective; clear error feedback drives retry |

### Key Learnings

1. **Avoid line numbers** — LLMs are bad at counting lines; content-based
   anchoring (search strings, `@@` markers) is far more reliable.

2. **Fuzzy matching is essential** — Exact match alone fails ~15-20% of the
   time due to whitespace drift. A 3-tier fallback (exact → trimmed → regex)
   dramatically improves first-pass success.

3. **Indentation preservation matters** — Especially for Python. The tool
   should detect the original indentation style and re-apply it to
   replacement text.

4. **Actionable error messages** — "old_str not found" is useless.
   "old_str not found; closest match at line 42 (similarity 0.92)" lets the
   agent self-correct.

5. **Token efficiency** — `str_replace(old, new)` is far cheaper than
   "rewrite the whole file". Agents should never need to output unchanged code.

6. **Fewer tools > more tools** — Per Anthropic's guidance, one well-designed
   `edit` tool with modes is better than separate `insert`, `delete`,
   `replace`, `rewrite` tools.

### Sources

- [Code Surgery: How AI Assistants Make Precise Edits](https://fabianhertwig.com/blog/coding-assistants-file-edits/) — comprehensive comparison of Codex, Aider, RooCode, Cursor
- [The hidden sophistication behind how AI agents edit files](https://sumitgouthaman.com/posts/file-editing-for-llms/) — Q CLI vs Gemini CLI deep dive
- [Anthropic: Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) — tool design principles
- [codex-apply-patch (PyPI)](https://pypi.org/project/codex-apply-patch/) — Python library for OpenAI V4A patch format

---

## Open Source Libraries We Can Use

### 1. ⭐ OpenHands `OHEditor` (Best Pattern — Use as Reference)

- **Original repo**: [All-Hands-AI/openhands-aci](https://github.com/All-Hands-AI/openhands-aci)
  — **archived Sep 2025**, code frozen but readable
- **New SDK**: [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk)
  (`FileEditorTool`) — active, but now a thin tool wrapper that delegates
  to a sandbox/terminal. The original self-contained `OHEditor` with
  embedded `str_replace` logic was **not carried over**.
- **License**: MIT
- **Language**: Pure Python (the archived `OHEditor`)
- **Status**: ⚠️ No maintained, standalone, pip-installable `str_replace`
  editor library exists. The archived `openhands-aci` `editor/editor.py`
  is the best reference implementation available.
- **Recommendation**: Use the archived `OHEditor` source as a **design
  reference** and implement our own ~100-line MemFS-native version.
  The core `str_replace` logic is simple (exact match → strip fallback →
  uniqueness check → replace). We don't need the filesystem, tree-sitter,
  or `binaryornot` deps.
- **Commands**: `view`, `create`, `str_replace`, `insert`, `undo_edit`
- **Matching**: Exact match → strip whitespace fallback → error with line numbers
- **Features**:
  - `str_replace(old_str, new_str)` with uniqueness enforcement
  - `insert(line_number, text)` for targeted insertion
  - `view(path, range)` with line-numbered output + truncation
  - `undo_edit` via per-file edit history stack
  - Tree-sitter based linting after edits (optional)
  - Binary file detection, encoding auto-detection
  - Context snippet shown after every edit (configurable window)
  - Max file size enforcement
  - Error messages include line numbers of duplicate matches
  - Originally based on Anthropic's reference implementation
- **Pros**: Battle-tested (#1 on SWE-bench), comprehensive feature set,
  actively maintained (60+ contributors), MIT license, pure Python,
  already designed for AI agent use, includes undo
- **Cons**: Filesystem-based (reads/writes real files) — would need
  adaptation for MemFS. Has external deps (`binaryornot`, tree-sitter).
  The core `str_replace` logic is simple enough to extract.

> **This is the gold standard for AI agent file editing.** Used by
> OpenHands (formerly OpenDevin), which consistently tops SWE-bench.
> The `str_replace` + `view` pattern is proven to work across all
> major LLMs (Claude, GPT, Gemini, Llama).

### 2. ⭐ `apply-patch-py` (Best Active Library — Feb 2026)

- **Repo**: [marcius-llmus/apply-patch-py](https://github.com/marcius-llmus/apply-patch-py)
- **PyPI**: `pip install apply-patch-py` (v0.4.1, **released Feb 17, 2026**)
- **License**: MIT
- **Language**: Pure Python (99.1%), async API
- **Format**: Codex-style V4A patch blocks (`*** Begin Patch` / `*** End Patch`)
- **Operations**: Add File, Delete File, Update File, Rename/Move
- **4-tier fuzzy matching**:
  1. Exact match
  2. Right-stripped (`rstrip`)
  3. Trimmed (`strip`)
  4. **Normalized** (Unicode punctuation + whitespace normalization)
- **Plus**: Anchor line fallback for malformed hunks
- **API**:
  ```python
  from apply_patch_py import apply_patch
  result = await apply_patch(patch_text)  # async
  assert result.success
  ```
- **Extras**: CLI, PydanticAI tool example, LLM integration tests
- **Pros**: Actively maintained (5 days old!), purpose-built for LLM
  imperfections, more forgiving than OpenAI's own `apply_diff`, async,
  pure Python, zero heavy deps, MIT
- **Cons**: V4A format only (OpenAI models produce this natively, others
  may need prompting). Filesystem-based (would need adaptation for MemFS).
  New/small project.

> **This is the most promising library found.** A forgiving Python port
> of the Codex Rust patcher, explicitly designed to handle the kinds of
> errors LLMs actually make (whitespace drift, Unicode quotes, malformed
> hunks). Can serve as the V4A backend, or as a reference for our own
> `str_replace` implementation.

### 3. OpenAI Agents SDK — `apply_diff` (V4A Format)

- **Repo**: [github.com/openai/openai-agents-python](https://github.com/openai/openai-agents-python)
- **File**: `src/agents/apply_diff.py` (~250 lines, pure Python)
- **License**: MIT
- **Install**: `pip install openai-agents` (or vendor the single file)
- **API**: `apply_diff(input_text, diff_text, mode="default"|"create") → str`
- **Matching**: 3-tier fuzzy context (exact → rstrip → strip), fuzz scoring
- **Features**: `@@` anchor lines, chunk-based application, CRLF/LF
  normalization, create + update modes, clear error messages
- **Pros**: Official OpenAI reference implementation, actively maintained
  (Feb 2026 releases), pure Python, zero external dependencies,
  GPT-4.1+ / GPT-5+ trained on V4A format
- **Cons**: V4A format more complex than str_replace, non-OpenAI LLMs
  may not produce V4A reliably

> **Note**: The `codex-apply-patch` PyPI package is a stale third-party
> wrapper (~9 months unmaintained). Use the official Agents SDK instead.

### 4. Gemini CLI `replace` (Edit Tool)

- **Repo**: [github.com/google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli)
- **File**: `packages/core/src/tools/edit.ts` (TypeScript)
- **License**: Apache 2.0
- **Approach**: `old_string`/`new_string` replacement with multi-stage
  self-correction — if exact match fails, calls the LLM again to fix
  the `old_string` to match actual file content
- **Pros**: Highest reliability through LLM self-correction loop
- **Cons**: TypeScript, not Python. Self-correction requires LLM calls
  (adds latency/cost). Tightly coupled to Gemini.

### 5. Aider's `editblock_coder.py` (Apache 2.0)

- **What**: Search/replace block parser + fuzzy matching
- **Repo**: `paul-gauthier/aider`, file `aider/coders/editblock_coder.py`
- **Pros**: Proven at scale, handles edge cases well
- **Cons**: Tightly coupled to Aider's coder framework; would need extraction

### 6. `diff-match-patch` (Google) — Fuzzy Patch Engine

- **Repo**: [google/diff-match-patch](https://github.com/google/diff-match-patch)
- **PyPI**: `pip install diff-match-patch` (last release Oct 2024, stable since 2006)
- **License**: Apache 2.0
- **Language**: Pure Python (also C++, Java, JS, etc.)
- **API**: String-in, string-out — perfect for MemFS
  ```python
  dmp = diff_match_patch()
  patches = dmp.patch_make(old_text, new_text)  # generate
  result, flags = dmp.patch_apply(patches, text)  # best-effort apply
  ```
- **Key feature**: `patch_apply` uses **Bitap fuzzy matching** to apply
  patches even when the underlying text has shifted. Built to power Google
  Docs collaborative editing.
- **Also has**: `match_main(text, pattern, loc)` — fuzzy string search
  weighted for both accuracy and location.
- **Pros**: Battle-tested (Google Docs since 2006), mature/stable, pure
  Python, works on plain text strings, best-effort fuzzy apply built-in
- **Cons**: Not LLM-specific, no str_replace mode (patch-based only),
  not line-based (character-level diffs)

> **This is the strongest fuzzy patching engine available.** Can serve as
> the fallback layer when exact `str_replace` fails.

### 7. Unified Diff Libraries (Parse + Apply)

| Library | PyPI | Status | Notes |
|---------|------|--------|-------|
| **`patch`** (techtonik) | `pip install patch` | Stable, single file | Auto-corrects linefeeds, stripped whitespace, a/b prefixes. Forgiving of LLM formatting errors. |
| **`patch-ng`** | `pip install patch-ng` | Fork of above | Same auto-correction, CI badge. |
| **`patchpy`** | `pip install patchpy` | Modern | Parse + validate + apply/reverse. Can reject broken hunks before applying. |
| **`unidiff`** | `pip install unidiff` | Active | Parsing only (no apply). Good for inspection/validation. |
| **`whatthepatch`** | `pip install whatthepatch` | Stable | Parses many diff formats. |

These are useful if LLMs generate unified diffs, but `str_replace` is
generally more reliable than asking LLMs for correct diff format.

### 8. LLM-Specific Diff Tools

| Library | PyPI | Status | Notes |
|---------|------|--------|-------|
| **`gptdiff`** | `pip install gptdiff` (v0.5.2, Jan 2026) | Active | CLI + API. "smartapply" falls back to an LLM call if `git apply` fails. Requires LLM API key — **adds cost/latency**. |
| **`patch-fixer`** | Not found on PyPI | Unknown | Claimed to fix malformed LLM patches. May not be published. |

### 9. CST/AST Structured Edits (Python-Only)

| Library | Use | Limitation |
|---------|-----|------------|
| **LibCST** | Concrete syntax tree transforms, preserves formatting | Python files only |
| **Bowler** | Refactoring framework over lib2to3/fissix | Python files only |
| **Baron/RedBaron** | Full Syntax Tree, round-trips formatting | Python files only |
| **rope** | Rename/move/extract refactoring | Python files only |

These are powerful for Python-specific transforms but **don't help with
general file editing** (JSON, YAML, Markdown, JS, etc.).

### 10. `RapidFuzz` / `difflib` (Fuzzy Matching Primitives)

- **`RapidFuzz`**: C++ core, MIT, fast Levenshtein/Jaro-Winkler. External dep.
- **`difflib`** (stdlib): `SequenceMatcher`, `get_close_matches`. Zero deps,
  available in Pyodide. Slower but sufficient for file editing.

### Library Comparison Matrix

| Library | LLM Agnostic | Pure Python | Zero Deps | Fuzzy Match | Undo | Linting | Battle-tested |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **OpenHands ACI** | ✅ | ✅ | ❌ | strip | ✅ | ✅ | SWE-bench #1 |
| **apply-patch-py** | ❌ (V4A) | ✅ | ✅ | **4-tier + anchor** | ❌ | ❌ | LLM integration tests |
| **OpenAI apply_diff** | ❌ (V4A) | ✅ | ✅ | 3-tier | ❌ | ❌ | Codex CLI |
| **Gemini CLI** | ❌ | ❌ (TS) | ❌ | LLM loop | ❌ | ❌ | Gemini CLI |
| **Aider** | ✅ | ✅ | ✅ | multi-tier | ❌ | ❌ | Aider |
| **difflib** | ✅ | ✅ | ✅ | basic | ❌ | ❌ | stdlib |

---

## Proposed Design

### Approach: OpenHands-style `str_replace` Editor (Adapted for MemFS)

The OpenHands `OHEditor` is the proven gold standard (#1 SWE-bench). We
adapt its `str_replace` / `view` / `insert` / `create` pattern for our
MemFS-based sandboxes. The core `str_replace` logic is ~60 lines — the
rest is MemFS integration and error formatting.

### Tool: `edit` Shell Builtin

```
edit <file> [mode] [options]
```

#### Modes

| Mode | Usage | Description |
|------|-------|-------------|
| `str_replace` | `edit file --old "..." --new "..."` | Find and replace a unique block of text (default mode) |
| `insert` | `edit file --after "anchor" --insert "text"` | Insert text after a matching line |
| `create` | `edit file --create --content "..."` | Create a new file with content |
| `view` | `edit file --view [--range 10:20]` | View file with line numbers (for context) |

#### `str_replace` Mode (Default) — The Core Operation

```bash
# Simple replacement
edit /workspace/calc.py --old "def add(a, b):
    return a + b" --new "def add(a, b):
    \"\"\"Add two numbers.\"\"\"
    return a + b"

# With heredoc for cleaner multi-line (shell handles quoting)
edit /workspace/calc.py --old <<'SEARCH'
def add(a, b):
    return a + b
SEARCH
--new <<'REPLACE'
def add(a, b):
    """Add two numbers."""
    return a + b
REPLACE
```

#### Matching Strategy (3-tier)

1. **Exact match** — literal string comparison
2. **Flexible match** — strip leading/trailing whitespace per line,
   normalize line endings (same as OpenHands `OHEditor`)
3. **Fuzzy match** — use `diff-match-patch` Bitap algorithm
   (`match_main(text, pattern, loc)`) to find the closest match even
   when text has shifted. Falls back to `difflib.SequenceMatcher` if
   `diff-match-patch` is not installed.

Each tier is tried in order. If fuzzy match is used, the output includes
a warning: `edit: fuzzy match used (line 42)`.

#### Error Feedback (Critical for Agent Self-Correction)

| Scenario | Error Message |
|----------|---------------|
| Not found, no close match | `edit: old_str not found in file.py (247 lines). Use 'edit file --view' to see contents.` |
| Not found, close match exists | `edit: old_str not found (exact). Closest match at lines 42-45 (similarity 0.88):\n> def add(a, b):\n>     return a+b` |
| Multiple exact matches | `edit: old_str matches 3 locations (lines 12, 45, 89). Add more context to make it unique.` |
| File not found | `edit: /workspace/calc.py: No such file` |
| No change | `edit: old_str and new_str are identical. No changes made.` |

#### Indentation Preservation

When using fuzzy match, the tool captures the indentation of the matched
block and re-applies it to the replacement:

1. Detect the base indentation of the matched block (leading whitespace
   of first line)
2. Detect the base indentation of the replacement block
3. Re-indent the replacement to match the original's base + relative offsets

#### Implementation Location

```
agentbox/box/patch/                        # Patch module (MemFS-native)
agentbox/box/outline/                      # Outline module (Aider RepoMap)
```

The patch module provides the core `str_replace` / `view` / `insert` /
`create` operations on MemFS strings. The outline module provides
tree-sitter-based symbol extraction via Aider's RepoMap.

### Alternative Considered: V4A Patch Format via `apply_diff`

The OpenAI Agents SDK provides `apply_diff()` — a pure Python, ~250-line
V4A diff parser that we could vendor directly. It has 3-tier fuzzy matching
built in and is the official reference implementation.

- **Pro**: GPT-4.1+ / GPT-5+ models are trained on V4A, producing reliable
  patches. Pure Python, no binary deps. MIT license, easy to vendor.
- **Con**: V4A format is more complex than simple str_replace, and non-OpenAI
  models (Claude, Gemini, Llama) may not produce V4A reliably.
- **Decision**: Start with simple `str_replace` tool (works with all LLMs).
  Add V4A `apply_patch` as an optional second builtin for OpenAI-powered
  agents. The `apply_diff()` function maps cleanly to MemFS (takes/returns
  strings, no filesystem access needed).

### Alternative Considered: Aider Search/Replace Blocks

The `<<<<<<< SEARCH` / `>>>>>>> REPLACE` format is well-known but:

- Requires parsing a structured block format from shell output
- More suited for LLM-to-tool communication protocols than shell commands
- Our Deep Agents `BaseSandbox.execute()` interface means the agent sends
  shell commands, not structured blocks

The `edit --old/--new` approach is more natural for shell execution.

---

## Integration with Deep Agents

### Current Flow (Inefficient)

```
Agent → execute("cat file.py")           → read full file
Agent → execute("cat > file.py << 'EOF'  → rewrite full file
         ...500 lines...
         EOF")
```

### Proposed Flow (Efficient)

```
Agent → execute("edit file.py --view")           → see file with line numbers
Agent → execute("edit file.py --old '...' --new '...'")  → targeted edit
```

### Impact on BaseSandbox

The `BaseSandbox.edit()` method in Deep Agents could be updated to use
the `edit` builtin instead of raw `execute("sed ...")` or file rewrites.
This is a downstream change in `agentbox/deepagents/sandbox.py`.

---

## Conclusion

After extensive research across the AI code editing landscape, we conclude:

1. **No maintained, standalone Python library exists** for robust LLM file
   editing with MemFS support. Every major tool (OpenHands, Aider, Codex,
   Gemini CLI, Cursor) implements their own.

2. **`apply-patch-py`** (v0.4.1, Feb 2026, MIT) is the best active library
   found. It is a forgiving Python port of the Codex Rust patcher with
   4-tier matching, anchor fallback, and fuzzy search. We have reviewed
   its source code in detail (see `/patch` directory).

3. **For patching, we will not use an external library.** Instead, we will
   write new original code in our project, taking the best ideas from
   multiple projects (apply-patch-py, Aider editblock, OpenHands OHEditor).
   For outline, we will use Aider as a dependency and call into its
   RepoMap functionality. Reasons for building our own patcher:
   - Our sandbox uses **MemFS** (in-browser Pyodide), not a real filesystem.
     All existing libraries assume `open(path)` / `aiofiles.open()`.
   - We need a **shell builtin** interface (`edit file --old ... --new ...`),
     not a Python API or V4A patch format.
   - We need **zero external dependencies** — the edit tool runs inside
     the Pyodide sandbox where only stdlib is available.
   - `apply-patch-py` requires Python 3.13+ and `aiofiles`.
   - We want `str_replace` + `view` + `insert` modes (OpenHands pattern),
     not just V4A patch application.

### Ideas We Draw From (New Original Code)

Our patch module is **new code** inspired by multiple projects. We are not
vendoring or forking any of these — we write our own implementation
tailored to our MemFS constraints.

**Inspired by `apply-patch-py`** (MIT, source in `/patch`):

| Idea | Reference | Our Adaptation |
|------|-----------|----------------|
| 4-tier matching (exact → rstrip → strip → normalize) | `search.py` | Core of our `str_replace` matching |
| Unicode normalization (smart quotes, em dashes, NBSP) | `search.py:normalise()` | Similar approach, ~30 lines |
| Anchor-based fuzzy search with rare-line candidates | `applier.py:_fuzzy_find()` | Inspired our fuzzy fallback |
| Smart scoring (code lines weighted 1.0, comments 0.1) | `applier.py:_smart_fuzzy_score()` | Prevents false fuzzy matches |
| Bounded search (timeout + eval limit) | `applier.py` constants | Prevents pathological cases |
| Ambiguity detection with actionable errors | `applier.py:_apply_chunks()` | Our error messages |

**Inspired by Aider `editblock_coder.py`** (Apache 2.0, source in `/aider`):

| Idea | Reference | Our Adaptation |
|------|-----------|----------------|
| Indent-offset matching | `replace_part_with_missing_leading_whitespace()` | Handles uniform indent differences |
| `...` elision handling | `try_dotdotdots()` | Lets LLM skip unchanged lines |
| Closest-match error hints | `find_similar_lines()` | Shows agent what it should have matched |
| **Note**: Aider's fuzzy matching is disabled (dead code). `apply-patch-py` has better fuzzy logic. |

**Inspired by OpenHands `OHEditor`** (MIT, archived):

| Idea | Reference | Our Adaptation |
|------|-----------|----------------|
| `str_replace` + `view` + `insert` + `create` command set | OHEditor API | Our edit modes |
| Uniqueness enforcement (reject 0 or >1 matches) | OHEditor | Core safety check |
| Context snippet after edit | OHEditor | Agent feedback |

---

## Implementation Plan

### Phase 1: Core `edit` Builtin

1. Implement in `agentbox/box/patch/`
   - Core patch operations: `str_replace`, `insert`, `create`, `view` modes
   - 4-tier matching adapted from `apply-patch-py` search.py:
     exact → rstrip → strip → Unicode-normalized
   - Anchor-based fuzzy fallback with smart scoring (code vs comments)
   - Uniqueness enforcement (reject 0 or >1 matches)
   - Rich error messages with closest-match hints + line numbers
   - Context snippet shown after successful edit
   - All operations on MemFS strings — no filesystem I/O
   - Zero external dependencies (stdlib only)
2. Register in `BUILTINS`
3. Tests: `test/test_edit_builtin.py`
   - Exact match, rstrip match, strip match, normalized match
   - Fuzzy match with anchor fallback
   - Multiple matches (rejected), not found (with hint)
   - Multi-line replacement, create mode, view mode
   - Insert mode, error message quality
   - Unicode normalization edge cases

### Phase 2: `outline` Host Command ✅ IMPLEMENTED

Tier 3 host command for AST-based symbol extraction. Uses **`ast-grep-py`**
(Rust core, Python bindings via PyO3) instead of Aider's RepoMap — actively
maintained, bundles tree-sitter grammars for 50+ languages, works on strings.

- **Host-side dependencies**: `ast-grep-py>=0.41.0`, `markdown-it-py>=3.0`,
  `mdit-py-plugins>=0.4`
- **Implementation**: `agentbox/box/outline/outliner.py`
- **Host command**: `agentbox/box/shell/host_commands/outline_cmd.py`
- **Agent usage**: `outline file.py` → condensed outline with ⋮ elision
- **Flags**: `--symbols` (compact list), `--language <lang>` (override)
- **Languages**: Python, JS, TS, TSX, Rust, Go, Java, Kotlin, Ruby, C,
  C++, C#, Swift, PHP, Scala, Lua, Elixir, **Markdown** (headers, code
  blocks, LaTeX math)
- **Markdown support**: Uses `markdown-it-py` + `mdit-py-plugins` for
  heading extraction, fenced code blocks, `$$` math blocks, inline `$` math.
  Regex fallback when markdown-it-py is not installed.
- **Integration**: `edit --info` now uses ast-grep for accurate class/function
  extraction (falls back to regex if ast-grep-py not installed)
- **Tests**: 56 passing (code outline + markdown + edge cases)
- **Decision against Aider**: `grep-ast` (Aider's tree-sitter wrapper) is
  outdated. Aider's RepoMap is heavily coupled to its I/O, tokenizer, and
  caching systems. `ast-grep-py` is a cleaner, actively maintained alternative.

### Phase 2.5: AST-Aware Patching via `ast-grep` Transform (Exploration)

Explore using `ast-grep-py` for **AST-aware code matching and rewriting**
in the patch module. This would add a new matching tier beyond the current
text-based approach (exact → strip → fuzzy).

**Reference**: https://ast-grep.github.io/guide/rewrite/transform.html

**What ast-grep transform provides:**
- **Pattern matching** with meta-variables: `def $NAME($$$ARGS):` matches
  any Python function definition, capturing name and args
- **Structural rewriting**: `fix` templates use captured meta-variables to
  produce new code
- **Transform operations**: `replace` (regex on captures), `substring`,
  `convert` (case conversion), `rewrite` (recursive sub-node rewriting)
- **Sequential transforms**: Chain operations — e.g., capture → regex
  replace → case convert → emit

**Potential use cases for the patch module:**

| Use Case | How ast-grep Helps |
|----------|-------------------|
| **AST-aware matching tier** | When text `str_replace` fails, try matching `old_str` as an AST pattern against the file. Handles whitespace/comment differences that break text matching. |
| **Structural search for `old_str`** | `node.find(pattern=old_str_as_pattern)` can locate code by structure, not text — survives reformatting. |
| **Safe replacement validation** | Verify that `old_str` corresponds to a complete AST node (not a partial match that would break syntax). |
| **Scope-aware insert** | `edit file --after-def foo --insert "..."` — insert after a specific function by AST node, not line number. |
| **Refactoring primitives** | Rename a function/variable across a file using AST pattern match + rewrite. |
| **Smart diff** | Show structural diff (what AST nodes changed) rather than line diff. |

**Key constraint**: ast-grep-py is a compiled Rust extension — it runs on
the **host Python only** (Tier 3), not in Pyodide. The current text-based
str_replace runs in-sandbox (Tier 1). AST-aware matching would be an
optional enhancement invoked when text matching fails, delegated to the host.

**Python API availability** (as of ast-grep-py 0.41.0):
- ✅ `SgRoot(source, lang)` — parse from string
- ✅ `node.find(pattern=...)` / `node.find_all(...)` — pattern search
- ✅ `node.find(kind=...)` — kind-based search
- ✅ `node.range()` — get line/column/offset
- ✅ `node.text()` — get matched text
- ❌ `fix` / `transform` — **not yet exposed in Python API** (YAML rules
  only, or CLI). Would need to use the CLI or implement rewriting ourselves
  using the match positions.

**Implementation approaches** (when ready):

**Option A: Python API + text surgery** (simplest)
1. Agent's `str_replace` fails text matching
2. Host-side fallback: parse file with `SgRoot`, use `node.find(pattern=...)`
3. Use match `range()` to locate the code, perform text replacement manually
4. Return result with warning: `edit: AST match used (line 42)`

**Option B: CLI (`sg`) for full transform/fix** (most powerful)
1. Shell out to the `sg` CLI from the host command
2. Write a temporary YAML rule with the pattern + fix + transform
3. Run `sg scan --rule rule.yaml --json` or `sg run` on the content
4. Full access to `replace`, `substring`, `convert`, `rewrite` transforms
5. Install: `cargo install ast-grep` or `npm i @ast-grep/cli -g`

Option B gives access to the complete transform pipeline (regex capture
groups, case conversion, recursive rewriting) without waiting for Python
API support. The CLI accepts stdin and outputs JSON — clean for integration.

**Status**: Exploration / future work. Either approach is viable. Option A
for simple AST-aware matching, Option B when structural rewriting is needed.

### Phase 3: V4A `apply_patch` Builtin (Optional)

For OpenAI-powered agents that natively produce V4A patches:
- Adapt `apply-patch-py` parser + applier for MemFS
- Accept V4A format via stdin or heredoc
- GPT-4.1+ / GPT-5+ models produce reliable V4A patches

### Phase 4: Evaluation

Build an eval harness to measure:
- First-pass edit success rate (target: >90%)
- Token usage per edit operation
- Agent task completion rate with `edit` vs `cat > file`

---

## Open Questions

1. **Heredoc support**: Does our tree-sitter-bash parser handle heredocs
   (`<< 'EOF'`) correctly? If not, agents will need to use `--old "..."` with
   shell escaping, which is less clean.

2. **Binary files**: Should `edit` refuse binary files? Probably yes —
   redirect to `boxcp` for binary operations.

3. **Undo**: Should `edit` support `--undo` (restore previous version)?
   Git already provides this via `git checkout -- file`, so probably not
   needed for GitBox. Could be useful for MemBox.

4. **Max file size**: Should `edit --view` paginate or truncate large files?
   Anthropic recommends truncation with helpful messages. Default to first
   200 lines with a note.
