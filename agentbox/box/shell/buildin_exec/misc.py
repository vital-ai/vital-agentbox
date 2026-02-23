"""tee, true, false — miscellaneous builtins."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class TeeExec(BuiltinExec):
    """Write stdin to file and stdout."""

    name = "tee"

    async def run(self) -> ShellResult:
        append = False
        paths = []
        for arg in self.args:
            if arg == "-a":
                append = True
            elif not arg.startswith("-"):
                paths.append(arg)

        text = self.stdin or ""
        for path in paths:
            resolved = self.resolve(path)
            await self.memfs.write_file(resolved, text, append=append)
        return self.ok(text)


class TrueExec(BuiltinExec):
    name = "true"

    async def run(self) -> ShellResult:
        return self.ok()


class FalseExec(BuiltinExec):
    name = "false"

    async def run(self) -> ShellResult:
        return ShellResult(exit_code=1)
