"""
Base class for shell builtin commands.

Subclasses implement ``run()`` and use helpers from ``BuiltinExec``
for path resolution, file I/O, and result construction.

Register in the BUILTINS dict via ``MyCommand.as_builtin()``.
"""

from __future__ import annotations

import re
from typing import Any

from agentbox.box.shell.environment import ShellResult


class BuiltinExec:
    """Base class for shell builtin commands.

    Subclass contract:
        - Set ``name`` to the command name (used in error messages).
        - Implement ``async def run(self) -> ShellResult``.
        - Call ``self.parse_args()`` in ``run()`` or do manual parsing.

    Usage in BUILTINS dict::

        from agentbox.box.shell.buildin_exec.grep import GrepExec
        BUILTINS["grep"] = GrepExec.as_builtin()
    """

    name: str = ""

    def __init__(self, args: list[str], stdin: str | None, env, memfs):
        self.args = args
        self.stdin = stdin
        self.env = env
        self.memfs = memfs

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def resolve(self, path: str) -> str:
        """Resolve *path* relative to the shell cwd."""
        return self.env.resolve_path(path)

    async def read_file(self, path: str) -> str | None:
        """Read a file from MemFS (resolved). Returns None if missing."""
        return await self.memfs.read_file(self.resolve(path))

    async def write_file(self, path: str, content: str) -> bool:
        """Write content to a file in MemFS (resolved)."""
        return await self.memfs.write_file(self.resolve(path), content)

    async def list_dir(self, path: str, *, recursive: bool = False):
        """List directory entries from MemFS (resolved)."""
        return await self.memfs.list_dir(self.resolve(path), recursive=recursive)

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    @staticmethod
    def ok(stdout: str = "") -> ShellResult:
        return ShellResult(stdout=stdout)

    @staticmethod
    def fail(msg: str = "", *, code: int = 1) -> ShellResult:
        return ShellResult(exit_code=code, stderr=msg)

    # ------------------------------------------------------------------
    # Arg-parsing helpers
    # ------------------------------------------------------------------

    def split_flags_and_paths(
        self,
        *,
        known_flags: set[str] | None = None,
        value_flags: set[str] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Simple POSIX-style flag + positional splitter.

        Args:
            known_flags: Boolean flags like ``{"-v", "-i", "-n"}``.
            value_flags: Flags that consume the next arg, e.g. ``{"-A", "-B"}``.

        Returns:
            ``(flags_dict, positionals)`` where *flags_dict* maps each flag
            (without ``-``) to ``True`` or the consumed value string.
        """
        known_flags = known_flags or set()
        value_flags = value_flags or set()
        flags: dict[str, Any] = {}
        positionals: list[str] = []

        i = 0
        while i < len(self.args):
            a = self.args[i]
            if a in value_flags and i + 1 < len(self.args):
                flags[a.lstrip("-")] = self.args[i + 1]
                i += 2
            elif a in known_flags:
                flags[a.lstrip("-")] = True
                i += 1
            elif a.startswith("-") and len(a) > 1:
                # Try combined short flags like -in
                for c in a[1:]:
                    flag = f"-{c}"
                    if flag in known_flags:
                        flags[c] = True
                    elif flag in value_flags and i + 1 < len(self.args):
                        flags[c] = self.args[i + 1]
                        i += 1
                i += 1
            else:
                positionals.append(a)
                i += 1

        return flags, positionals

    # ------------------------------------------------------------------
    # Abstract entry point
    # ------------------------------------------------------------------

    async def run(self) -> ShellResult:
        """Execute the command. Subclasses must override."""
        raise NotImplementedError(f"{self.name}: run() not implemented")

    # ------------------------------------------------------------------
    # Adapter — turns a class into an async function for BUILTINS dict
    # ------------------------------------------------------------------

    @classmethod
    def as_builtin(cls):
        """Return an ``async def(args, stdin, env, memfs)`` handler."""
        async def _handler(args, stdin, env, memfs):
            return await cls(args, stdin, env, memfs).run()
        _handler.__doc__ = cls.__doc__ or cls.name
        _handler.__name__ = f"builtin_{cls.name}"
        return _handler
