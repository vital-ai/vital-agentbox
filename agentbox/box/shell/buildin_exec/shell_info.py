"""which, command, type, test — shell introspection and test builtins."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class WhichExec(BuiltinExec):
    """Locate a command — reports /bin/<name> for known builtins."""

    name = "which"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("which: missing argument\n")
        from agentbox.box.shell.virtual_bin import virtual_bin_path
        output = []
        for name in self.args:
            path = virtual_bin_path(name)
            if path:
                output.append(f"{path}\n")
            else:
                return self.fail(f"{name}: not found\n")
        return self.ok("".join(output))


class CommandExec(BuiltinExec):
    """command -v NAME — check if command exists."""

    name = "command"

    async def run(self) -> ShellResult:
        if not self.args:
            return ShellResult(exit_code=1)
        from agentbox.box.shell.virtual_bin import virtual_bin_path
        names = []
        for a in self.args:
            if a == "-v" or a == "-V":
                pass
            elif not a.startswith("-"):
                names.append(a)
        if not names:
            return ShellResult(exit_code=1)
        output = []
        for name in names:
            path = virtual_bin_path(name)
            if path:
                output.append(f"{path}\n")
            else:
                return self.fail(f"command: {name}: not found\n")
        return self.ok("".join(output))


class TypeExec(BuiltinExec):
    """type NAME — describe a command."""

    name = "type"

    async def run(self) -> ShellResult:
        if not self.args:
            return ShellResult(exit_code=1)
        from agentbox.box.shell.virtual_bin import virtual_bin_path
        output = []
        for name in self.args:
            path = virtual_bin_path(name)
            if path:
                output.append(f"{name} is {path}\n")
            else:
                return self.fail(f"bash: type: {name}: not found\n")
        return self.ok("".join(output))


class TestExec(BuiltinExec):
    """test / [ — basic conditional expression (stub: always true)."""

    name = "test"

    async def run(self) -> ShellResult:
        return self.ok()
