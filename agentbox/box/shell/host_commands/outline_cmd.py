"""
Tier 3 host-delegated command: outline

Extract symbol definitions from source files using ast-grep-py (tree-sitter).

Usage:
    outline <file>                  # outline a single file
    outline <file1> <file2> ...     # outline multiple files
    outline --symbols <file>        # compact symbol list only
    outline --language python <file> # override language detection
"""

from __future__ import annotations

from agentbox.box.shell.environment import ShellResult


def _ok(stdout: str) -> ShellResult:
    return ShellResult(exit_code=0, stdout=stdout, stderr="")


def _fail(stderr: str) -> ShellResult:
    return ShellResult(exit_code=1, stdout="", stderr=stderr)


async def host_outline(args, stdin, env, memfs) -> ShellResult:
    """Tier 3 host command: outline."""
    from agentbox.box.outline.outliner import outline, get_language

    # Parse arguments
    files = []
    symbols_only = False
    lang_override = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--symbols":
            symbols_only = True
        elif a == "--language" and i + 1 < len(args):
            i += 1
            lang_override = args[i]
        elif a.startswith("-"):
            return _fail(f"outline: unknown option: {a}\n")
        else:
            files.append(a)
        i += 1

    if not files:
        return _fail(
            "outline: missing file path\n"
            "Usage: outline <file> [--symbols] [--language <lang>]\n"
        )

    parts = []
    for filepath in files:
        resolved = env.resolve_path(filepath)

        # Read file content from MemFS
        content = await _read_file(memfs, resolved)
        if content is None:
            parts.append(f"outline: {filepath}: No such file\n")
            continue

        result = outline(content, path=filepath, language=lang_override)

        if symbols_only:
            if result.symbols_text:
                parts.append(f"{filepath}:\n{result.symbols_text}")
            else:
                parts.append(f"{filepath}: no symbols found\n")
        else:
            parts.append(result.outline_text)

    output = "\n".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
    return _ok(output)


async def _read_file(memfs, resolved: str) -> str | None:
    """Read a text file from MemFS."""
    content = await memfs.page.evaluate("""([path]) => {
        const FS = window.pyodide._module.FS;
        try {
            return FS.readFile(path, { encoding: 'utf8' });
        } catch(e) { return null; }
    }""", [resolved])
    return content
