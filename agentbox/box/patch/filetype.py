"""
File type detection using libmagic (python-magic) with graceful fallback.

Runs on the host Python — not in Pyodide. Uses python-magic when available,
falls back to extension + content heuristics when it's not installed.
"""

from __future__ import annotations

import mimetypes
import os
import re
from typing import Tuple

# ---------------------------------------------------------------------------
# Try to import python-magic (optional dependency)
# ---------------------------------------------------------------------------

_magic = None
try:
    import magic as _magic_mod
    _magic = _magic_mod
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Extension → human name (primary lookup)
# ---------------------------------------------------------------------------

_FORMAT_NAMES = {
    ".py": "Python", ".pyi": "Python Stub", ".pyx": "Cython",
    ".js": "JavaScript", ".mjs": "JavaScript (ESM)", ".cjs": "JavaScript (CJS)",
    ".ts": "TypeScript", ".mts": "TypeScript (ESM)",
    ".tsx": "TypeScript (React)", ".jsx": "JavaScript (React)",
    ".java": "Java", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".c": "C", ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".h": "C Header", ".hpp": "C++ Header", ".hxx": "C++ Header",
    ".cs": "C#", ".fs": "F#", ".vb": "Visual Basic",
    ".sh": "Shell", ".bash": "Bash", ".zsh": "Zsh", ".fish": "Fish",
    ".html": "HTML", ".htm": "HTML", ".xhtml": "XHTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".json": "JSON", ".jsonl": "JSON Lines", ".json5": "JSON5",
    ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".ini": "INI", ".cfg": "Config",
    ".xml": "XML", ".xsl": "XSLT", ".xsd": "XML Schema",
    ".md": "Markdown", ".rst": "reStructuredText", ".adoc": "AsciiDoc",
    ".txt": "Text", ".log": "Log",
    ".sql": "SQL", ".r": "R", ".R": "R", ".jl": "Julia",
    ".swift": "Swift", ".kt": "Kotlin", ".kts": "Kotlin Script",
    ".scala": "Scala", ".clj": "Clojure",
    ".php": "PHP", ".lua": "Lua", ".pl": "Perl", ".pm": "Perl Module",
    ".ex": "Elixir", ".exs": "Elixir Script", ".erl": "Erlang",
    ".zig": "Zig", ".nim": "Nim", ".d": "D", ".dart": "Dart",
    ".proto": "Protocol Buffers", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".tf": "Terraform", ".hcl": "HCL",
    ".dockerfile": "Dockerfile", ".containerfile": "Containerfile",
    ".cmake": "CMake",
    ".gradle": "Gradle", ".sbt": "SBT",
    ".vue": "Vue", ".svelte": "Svelte",
}


# ---------------------------------------------------------------------------
# Well-known filenames (no extension or special name)
# ---------------------------------------------------------------------------

_KNOWN_FILENAMES = {
    "Makefile": ("Makefile", ""),
    "GNUmakefile": ("Makefile", ""),
    "Dockerfile": ("Dockerfile", ".dockerfile"),
    "Containerfile": ("Dockerfile", ".dockerfile"),
    "Vagrantfile": ("Vagrantfile (Ruby)", ".rb"),
    "Gemfile": ("Gemfile (Ruby)", ".rb"),
    "Rakefile": ("Rakefile (Ruby)", ".rb"),
    "CMakeLists.txt": ("CMake", ".cmake"),
    "Justfile": ("Justfile", ""),
    "Procfile": ("Procfile", ""),
    ".gitignore": ("Git Ignore", ""),
    ".gitattributes": ("Git Attributes", ""),
    ".dockerignore": ("Docker Ignore", ""),
    ".editorconfig": ("EditorConfig", ".ini"),
    ".env": ("Environment", ".ini"),
    ".env.local": ("Environment", ".ini"),
    ".eslintrc": ("ESLint Config", ".json"),
    ".prettierrc": ("Prettier Config", ".json"),
    ".babelrc": ("Babel Config", ".json"),
    "pyproject.toml": ("Python Project (TOML)", ".toml"),
    "setup.py": ("Python Setup", ".py"),
    "setup.cfg": ("Python Config", ".cfg"),
    "requirements.txt": ("Python Requirements", ".txt"),
    "package.json": ("Node.js Package", ".json"),
    "tsconfig.json": ("TypeScript Config", ".json"),
    "Cargo.toml": ("Rust Project (TOML)", ".toml"),
    "go.mod": ("Go Module", ""),
    "go.sum": ("Go Checksum", ""),
    "pom.xml": ("Maven POM", ".xml"),
    "docker-compose.yml": ("Docker Compose", ".yaml"),
    "docker-compose.yaml": ("Docker Compose", ".yaml"),
}


# ---------------------------------------------------------------------------
# Shebang → (format_name, ext_for_patterns)
# ---------------------------------------------------------------------------

_SHEBANG_MAP = {
    "python": ("Python", ".py"),
    "python3": ("Python", ".py"),
    "bash": ("Bash", ".sh"),
    "sh": ("Shell", ".sh"),
    "zsh": ("Zsh", ".sh"),
    "node": ("JavaScript", ".js"),
    "ruby": ("Ruby", ".rb"),
    "perl": ("Perl", ".pl"),
    "php": ("PHP", ".php"),
    "lua": ("Lua", ".lua"),
}


# ---------------------------------------------------------------------------
# MIME → human name (for libmagic output)
# ---------------------------------------------------------------------------

_MIME_TO_NAME = {
    "text/x-python": "Python",
    "text/x-script.python": "Python",
    "text/javascript": "JavaScript",
    "application/javascript": "JavaScript",
    "application/x-javascript": "JavaScript",
    "text/html": "HTML",
    "text/css": "CSS",
    "application/json": "JSON",
    "text/json": "JSON",
    "text/xml": "XML",
    "application/xml": "XML",
    "text/markdown": "Markdown",
    "text/x-markdown": "Markdown",
    "text/x-c": "C",
    "text/x-c++": "C++",
    "text/x-csrc": "C",
    "text/x-c++src": "C++",
    "text/x-chdr": "C Header",
    "text/x-c++hdr": "C++ Header",
    "text/x-java": "Java",
    "text/x-java-source": "Java",
    "text/x-shellscript": "Shell",
    "text/x-sh": "Shell",
    "text/x-ruby": "Ruby",
    "text/x-perl": "Perl",
    "text/x-lua": "Lua",
    "text/x-sql": "SQL",
    "application/x-yaml": "YAML",
    "text/yaml": "YAML",
    "application/toml": "TOML",
    "text/x-go": "Go",
    "text/x-rustsrc": "Rust",
    "text/x-swift": "Swift",
    "text/x-kotlin": "Kotlin",
    "text/x-scala": "Scala",
    "text/x-php": "PHP",
    "text/x-dockerfile": "Dockerfile",
    "text/x-makefile": "Makefile",
    "text/x-cmake": "CMake",
    "text/x-diff": "Diff/Patch",
    "text/x-asm": "Assembly",
    "text/x-fortran": "Fortran",
    "text/x-lisp": "Lisp",
    "text/x-haskell": "Haskell",
    "text/x-erlang": "Erlang",
    "application/x-elixir": "Elixir",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_file_type(
    content: str,
    path: str = "",
) -> Tuple[str, str, str]:
    """Detect the type of a file from its content and path.

    Uses python-magic (libmagic) when available, with fallback to
    extension + content heuristics.

    Returns:
        ``(format_name, effective_ext, mime_type)``
        - *format_name*: Human-readable like "Python", "JavaScript", etc.
        - *effective_ext*: Extension to use for pattern matching (e.g. ".py")
        - *mime_type*: MIME type string (e.g. "text/x-python") or ""
    """
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    basename = path.rsplit("/", 1)[-1] if "/" in path else path
    mime = ""

    # 1. Try python-magic (libmagic) on the content bytes
    if _magic is not None:
        try:
            content_bytes = content.encode("utf-8")
            mime = _magic.from_buffer(content_bytes, mime=True)
            desc = _magic.from_buffer(content_bytes)
        except Exception:
            mime = ""
            desc = ""

        if mime:
            # Check MIME → name mapping
            name = _MIME_TO_NAME.get(mime)
            if name:
                eff_ext = ext if ext else _name_to_ext(name)
                return name, eff_ext, mime

            # libmagic may return generic "text/plain" — fall through
            if mime not in ("text/plain", "application/octet-stream"):
                # Use the description from libmagic
                fmt = desc.split(",")[0] if desc else mime
                eff_ext = ext if ext else ""
                return fmt, eff_ext, mime

    # 2. Known filenames (Makefile, Dockerfile, etc.)
    if basename in _KNOWN_FILENAMES:
        name, eff_ext = _KNOWN_FILENAMES[basename]
        return name, eff_ext or ext, mime

    # 3. Extension lookup
    if ext and ext in _FORMAT_NAMES:
        # Try to get MIME from stdlib mimetypes
        if not mime:
            mime = mimetypes.guess_type(path)[0] or ""
        return _FORMAT_NAMES[ext], ext, mime

    # 4. Shebang detection
    first_line = content.split("\n", 1)[0] if content else ""
    if first_line.startswith("#!"):
        shebang = first_line.lower()
        for interpreter, (name, eff_ext) in _SHEBANG_MAP.items():
            if interpreter in shebang:
                return name, eff_ext, mime

    # 5. Content heuristics
    detected = _content_heuristics(content, first_line)
    if detected:
        name, eff_ext = detected
        return name, eff_ext, mime

    # 6. stdlib mimetypes as last resort
    if ext:
        mt = mimetypes.guess_type(path)[0]
        if mt and mt in _MIME_TO_NAME:
            return _MIME_TO_NAME[mt], ext, mt

    # 7. Fallback
    if ext:
        return ext.lstrip(".").upper(), ext, mime
    return "Unknown", "", mime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _name_to_ext(name: str) -> str:
    """Reverse lookup: format name → extension."""
    for ext, fmt in _FORMAT_NAMES.items():
        if fmt == name:
            return ext
    return ""


def _content_heuristics(content: str, first_line: str) -> Tuple[str, str] | None:
    """Detect file type from content patterns."""
    stripped = content.lstrip()
    if not stripped:
        return None

    # JSON
    if stripped[0] in ("{", "["):
        tail = stripped.rstrip()
        if (tail.endswith("}") or tail.endswith("]")):
            try:
                import json
                json.loads(content)
                return "JSON", ".json"
            except (json.JSONDecodeError, ValueError):
                pass

    # XML / HTML
    if stripped.startswith("<?xml") or stripped.startswith("<!DOCTYPE"):
        if "html" in stripped[:300].lower():
            return "HTML", ".html"
        return "XML", ".xml"
    if stripped.lower().startswith(("<html", "<!doctype html")):
        return "HTML", ".html"

    # YAML
    if re.match(r"^---\s*$", first_line) or re.match(r"^\w[\w-]*\s*:", first_line):
        yaml_lines = sum(
            1 for l in content.splitlines()[:10]
            if re.match(r"^\s*[\w-]+\s*:", l) or l.strip() == "---" or l.strip().startswith("- ")
        )
        if yaml_lines >= 2:
            return "YAML", ".yaml"

    # INI / Config
    if re.match(r"^\[[\w.-]+\]", first_line):
        return "INI/Config", ".ini"

    # SQL
    sql_kw = ("SELECT ", "INSERT ", "CREATE ", "ALTER ", "DROP ", "UPDATE ", "DELETE ")
    if any(stripped.upper().startswith(kw) for kw in sql_kw):
        return "SQL", ".sql"

    return None
