"""
Tier 3 host-delegated command: reportgen

Safe wrapper around pandoc + LaTeX for PDF generation.
Validates arguments, scans for unsafe LaTeX patterns, extracts files
from MemFS to a temp directory, runs pandoc, and writes the output
PDF back into MemFS.

Usage:
    reportgen /chapters/*.md -o /output/report.pdf
    reportgen /doc.md -o /out.pdf --template /tpl.tex --title "My Report"
    reportgen /doc.md -o /out.pdf --toc --author "Agent" --date "2025-02-22"
"""

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from agentbox.box.shell.environment import ShellResult


# --- Argument spec ---

ALLOWED_FLAGS = {
    "-o", "--output",
    "--template",
    "--title",
    "--author",
    "--date",
    "--toc",
    "--toc-depth",
    "--highlight-style",
    "--margin",
}

FLAGS_WITH_VALUE = {
    "-o", "--output",
    "--template",
    "--title",
    "--author",
    "--date",
    "--toc-depth",
    "--highlight-style",
    "--margin",
}

ALLOWED_HIGHLIGHT_STYLES = {
    "pygments", "tango", "espresso", "zenburn", "kate",
    "monochrome", "breezedark", "haddock",
}

# --- LaTeX security scan ---

BLOCKED_LATEX_PATTERNS = [
    re.compile(p) for p in [
        r'\\write18',
        r'\\immediate\s*\\write',
        r'\\input\s*\{',
        r'\\include\s*\{',
        r'\\input\s*\|\s*"',
        r'\\openin',
        r'\\openout',
        r'\\newread',
        r'\\newwrite',
        r'\\directlua',
        r'\\latelua',
        r'\\catcode',
        r'\\usepackage\s*\{bashful\}',
        r'\\usepackage\s*\{shellesc\}',
    ]
]

# Execution timeout for pandoc subprocess
REPORTGEN_TIMEOUT = int(os.environ.get("AGENTBOX_REPORTGEN_TIMEOUT", "120"))


def _parse_args(args):
    """Parse reportgen arguments. Returns (input_paths, options, error)."""
    input_paths = []
    options = {}
    i = 0

    while i < len(args):
        arg = args[i]

        if arg.startswith("-"):
            if arg not in ALLOWED_FLAGS:
                return None, None, f"reportgen: unknown option: {arg}\n"

            if arg in FLAGS_WITH_VALUE:
                if i + 1 >= len(args):
                    return None, None, f"reportgen: {arg} requires a value\n"
                value = args[i + 1]

                # Normalize -o to --output
                key = "--output" if arg == "-o" else arg
                options[key] = value
                i += 2
            else:
                # Boolean flag (e.g., --toc)
                options[arg] = True
                i += 1
        else:
            input_paths.append(arg)
            i += 1

    if not input_paths:
        return None, None, "reportgen: no input files specified\n"

    if "--output" not in options:
        return None, None, "reportgen: -o/--output is required\n"

    output = options["--output"]
    if not output.endswith(".pdf"):
        return None, None, f"reportgen: output must end in .pdf, got: {output}\n"

    # Validate toc-depth
    if "--toc-depth" in options:
        try:
            depth = int(options["--toc-depth"])
            if depth < 1 or depth > 6:
                raise ValueError
        except ValueError:
            return None, None, "reportgen: --toc-depth must be 1-6\n"

    # Validate highlight-style
    if "--highlight-style" in options:
        style = options["--highlight-style"]
        if style not in ALLOWED_HIGHLIGHT_STYLES:
            return None, None, (
                f"reportgen: unknown highlight style: {style}\n"
                f"  allowed: {', '.join(sorted(ALLOWED_HIGHLIGHT_STYLES))}\n"
            )

    return input_paths, options, None


# Image extensions that pandoc may reference
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".pdf"}

_MD_IMAGE_RE = re.compile(
    r'!\[(?:[^\]]*)\]\(([^)]+)\)'   # ![alt](path)
)
_HTML_IMG_RE = re.compile(
    r'<img\s[^>]*src=["\']([^"\']+)["\']',  # <img src="path">
    re.IGNORECASE,
)


def _extract_asset_refs(content):
    """Extract image/asset paths referenced in Markdown content.

    Finds both Markdown image syntax ![...](path) and HTML <img src="path">.
    Skips URLs (http://, https://, data:).
    Returns a set of relative or absolute paths.
    """
    refs = set()
    for match in _MD_IMAGE_RE.finditer(content):
        path = match.group(1).split(" ")[0].strip()  # strip title after space
        if not path.startswith(("http://", "https://", "data:")):
            refs.add(path)
    for match in _HTML_IMG_RE.finditer(content):
        path = match.group(1).strip()
        if not path.startswith(("http://", "https://", "data:")):
            refs.add(path)
    return refs


def _scan_content(content, filename):
    """Scan file content for blocked LaTeX patterns. Returns error string or None."""
    for line_num, line in enumerate(content.splitlines(), 1):
        for pattern in BLOCKED_LATEX_PATTERNS:
            match = pattern.search(line)
            if match:
                return (
                    f"reportgen: blocked unsafe LaTeX command: "
                    f"{match.group(0)} (in {filename}, line {line_num})\n"
                )
    return None


async def _resolve_glob(pattern, env, memfs):
    """Resolve a glob pattern against MemFS. Returns list of paths."""
    if "*" not in pattern and "?" not in pattern:
        return [env.resolve_path(pattern)]

    # Get the directory and glob pattern
    p = PurePosixPath(env.resolve_path(pattern))
    parent = str(p.parent)
    glob_pattern = p.name

    # List the directory
    entries = await memfs.list_dir(parent, recursive=False, info=False)
    if isinstance(entries, str) and entries.startswith("Error"):
        return []

    if not isinstance(entries, list):
        return []

    # Simple glob matching
    import fnmatch
    matched = []
    for entry in entries:
        name = entry if isinstance(entry, str) else str(entry)
        if fnmatch.fnmatch(name, glob_pattern):
            matched.append(f"{parent}/{name}" if parent != "/" else f"/{name}")

    return sorted(matched)


_HELP_TEXT = """\
reportgen — generate PDF from Markdown

Usage:
  reportgen INPUT [INPUT...] -o OUTPUT.pdf [OPTIONS]

Required:
  INPUT             One or more .md files (globs supported)
  -o, --output      Output PDF path (must end in .pdf)

Options:
  --title TITLE     Document title
  --author AUTHOR   Document author
  --date DATE       Document date
  --toc             Include table of contents
  --toc-depth N     TOC depth (1-6, default 3)
  --template FILE   Custom LaTeX template
  --highlight-style STYLE  Code highlight style (pygments, tango, etc.)
  --margin SIZE     Page margin (e.g. 1in, 2cm)

Examples:
  reportgen /workspace/report.md -o /workspace/report.pdf
  reportgen /workspace/report.md -o /workspace/report.pdf --title 'My Report' --author 'Agent' --toc
  reportgen /workspace/chapters/*.md -o /workspace/book.pdf --toc --toc-depth 2
"""


async def host_reportgen(args, stdin, env, memfs):
    """Execute reportgen: validate args, scan files, run pandoc, return PDF."""

    # Handle --help / -h
    if not args or "--help" in args or "-h" in args:
        return ShellResult(exit_code=0, stdout=_HELP_TEXT)

    # 1. Parse and validate arguments
    input_patterns, options, error = _parse_args(args)
    if error:
        return ShellResult(exit_code=1, stderr=error)

    # 2. Resolve glob patterns to actual files
    input_paths = []
    for pattern in input_patterns:
        resolved = await _resolve_glob(pattern, env, memfs)
        if not resolved:
            return ShellResult(
                exit_code=1,
                stderr=f"reportgen: no files match: {pattern}\n"
            )
        input_paths.extend(resolved)

    output_path = env.resolve_path(options["--output"])
    template_path = env.resolve_path(options["--template"]) if "--template" in options else None

    # 3. Read all input files from MemFS and scan for security issues
    file_contents = {}  # memfs_path → content

    for path in input_paths:
        content = await memfs.read_file(path)
        if content is None:
            return ShellResult(exit_code=1, stderr=f"reportgen: {path}: No such file\n")
        scan_error = _scan_content(content, path)
        if scan_error:
            return ShellResult(exit_code=1, stderr=scan_error)
        file_contents[path] = content

    if template_path:
        content = await memfs.read_file(template_path)
        if content is None:
            return ShellResult(exit_code=1, stderr=f"reportgen: {template_path}: No such file\n")
        scan_error = _scan_content(content, template_path)
        if scan_error:
            return ShellResult(exit_code=1, stderr=scan_error)
        file_contents[template_path] = content

    # 4. Check that pandoc is available on the host
    pandoc_path = shutil.which("pandoc")
    if pandoc_path is None:
        return ShellResult(
            exit_code=1,
            stderr="reportgen: pandoc not found on host. Install pandoc to use reportgen.\n"
        )

    # 5. Collect referenced assets (images) from markdown content
    asset_refs = set()
    for path, content in file_contents.items():
        asset_refs.update(_extract_asset_refs(content))

    # Resolve asset paths relative to the input file directories
    asset_paths = set()  # absolute MemFS paths
    for ref in asset_refs:
        if ref.startswith("/"):
            asset_paths.add(ref)
        else:
            # Resolve relative to each input file's directory
            for inp in input_paths:
                parent = str(PurePosixPath(inp).parent)
                abs_path = str(PurePosixPath(parent) / ref)
                asset_paths.add(abs_path)

    # Read binary assets from MemFS
    asset_binaries = {}  # memfs_path → bytes
    for asset_path in asset_paths:
        data = await memfs.read_file_binary(asset_path)
        if data is not None:
            asset_binaries[asset_path] = data
        # Missing assets are not fatal — pandoc will warn

    # 6. Extract files to host temp directory
    tmp_dir = tempfile.mkdtemp(prefix="agentbox-reportgen-")
    try:
        # Write input files (text) preserving directory structure
        host_input_paths = []
        for memfs_path, content in file_contents.items():
            # Map /chapters/ch1.md → tmp_dir/chapters/ch1.md
            rel = memfs_path.lstrip("/")
            host_path = os.path.join(tmp_dir, rel)
            os.makedirs(os.path.dirname(host_path), exist_ok=True)
            with open(host_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Only add actual input files (not template) to pandoc args
            if memfs_path in [p for p in input_paths]:
                host_input_paths.append(host_path)

        # Write binary assets (images)
        for memfs_path, data in asset_binaries.items():
            rel = memfs_path.lstrip("/")
            host_path = os.path.join(tmp_dir, rel)
            os.makedirs(os.path.dirname(host_path), exist_ok=True)
            with open(host_path, "wb") as f:
                f.write(data)

        # Prepare output path
        out_rel = output_path.lstrip("/")
        host_output = os.path.join(tmp_dir, out_rel)
        os.makedirs(os.path.dirname(host_output), exist_ok=True)

        # 7. Build pandoc command
        cmd = [pandoc_path]
        cmd.extend(host_input_paths)
        cmd.extend(["-o", host_output])

        if template_path:
            tpl_rel = template_path.lstrip("/")
            cmd.append(f"--template={os.path.join(tmp_dir, tpl_rel)}")

        # Metadata
        if "--title" in options:
            cmd.append(f"--metadata=title:{options['--title']}")
        if "--author" in options:
            cmd.append(f"--metadata=author:{options['--author']}")
        if "--date" in options:
            cmd.append(f"--metadata=date:{options['--date']}")

        # TOC
        if "--toc" in options:
            cmd.append("--toc")
        if "--toc-depth" in options:
            cmd.extend(["--toc-depth", options["--toc-depth"]])

        # Highlight style
        if "--highlight-style" in options:
            cmd.extend(["--highlight-style", options["--highlight-style"]])

        # Margin (via geometry variable)
        if "--margin" in options:
            cmd.append(f"--variable=geometry:margin={options['--margin']}")

        # PDF engine + security flags
        cmd.extend([
            "--pdf-engine=latexmk",
            "--pdf-engine-opt=-pdf",
        ])

        # 8. Run pandoc
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmp_dir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=REPORTGEN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ShellResult(
                exit_code=124,
                stderr=f"reportgen: pandoc timed out after {REPORTGEN_TIMEOUT}s\n",
            )

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            return ShellResult(
                exit_code=proc.returncode,
                stderr=f"reportgen: pandoc failed (exit {proc.returncode}):\n{stderr_text}",
            )

        # 9. Read output PDF and write back to MemFS
        if not os.path.exists(host_output):
            return ShellResult(
                exit_code=1,
                stderr="reportgen: pandoc succeeded but output file not found\n",
            )

        with open(host_output, "rb") as f:
            pdf_bytes = f.read()

        # Write as binary to MemFS
        import base64
        wrote = await memfs.write_file_binary(output_path, pdf_bytes)
        if not wrote:
            return ShellResult(exit_code=1, stderr="reportgen: failed to write PDF to MemFS\n")

        return ShellResult(
            exit_code=0,
            stdout=f"reportgen: {output_path} ({len(pdf_bytes)} bytes)\n",
        )

    finally:
        # 10. Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
