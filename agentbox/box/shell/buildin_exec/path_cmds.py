"""basename, dirname, realpath — path manipulation commands."""

from __future__ import annotations

from posixpath import basename, dirname, normpath

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class BasenameExec(BuiltinExec):
    """Strip directory and optional suffix from a path."""

    name = "basename"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("basename: missing operand\n")
        path = self.args[0]
        suffix = self.args[1] if len(self.args) > 1 else None
        result = basename(path)
        if suffix and result.endswith(suffix):
            result = result[: -len(suffix)]
        return self.ok(result + "\n")


class DirnameExec(BuiltinExec):
    """Strip the last component from a path."""

    name = "dirname"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("dirname: missing operand\n")
        results = []
        for path in self.args:
            results.append(dirname(path) or ".")
        return self.ok("\n".join(results) + "\n")


class RealpathExec(BuiltinExec):
    """Resolve a path to its absolute canonical form."""

    name = "realpath"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("realpath: missing operand\n")
        results = []
        for path in self.args:
            resolved = self.resolve(path)
            results.append(normpath(resolved))
        return self.ok("\n".join(results) + "\n")
