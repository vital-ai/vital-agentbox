"""head / tail — print first or last N lines of a file."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class HeadExec(BuiltinExec):
    name = "head"

    async def run(self) -> ShellResult:
        n = 10
        path = None

        i = 0
        while i < len(self.args):
            if self.args[i] == "-n" and i + 1 < len(self.args):
                try:
                    n = int(self.args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif not self.args[i].startswith("-"):
                path = self.args[i]
                i += 1
            else:
                i += 1

        text = self.stdin or ""
        if path:
            content = await self.read_file(path)
            if content is None:
                return self.fail(f"head: {path}: No such file or directory\n")
            text = content

        lines = text.split("\n")
        selected = lines[:n]
        return self.ok("\n".join(selected) + "\n" if selected else "")


class TailExec(BuiltinExec):
    name = "tail"

    async def run(self) -> ShellResult:
        n = 10
        path = None

        i = 0
        while i < len(self.args):
            if self.args[i] == "-n" and i + 1 < len(self.args):
                try:
                    n = int(self.args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif not self.args[i].startswith("-"):
                path = self.args[i]
                i += 1
            else:
                i += 1

        text = self.stdin or ""
        if path:
            content = await self.read_file(path)
            if content is None:
                return self.fail(f"tail: {path}: No such file or directory\n")
            text = content

        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        selected = lines[-n:]
        return self.ok("\n".join(selected) + "\n" if selected else "")
