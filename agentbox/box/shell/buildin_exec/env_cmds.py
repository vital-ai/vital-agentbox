"""cd, pwd, export, env — environment and directory commands."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class CdExec(BuiltinExec):
    """Change working directory."""

    name = "cd"

    async def run(self) -> ShellResult:
        if not self.args:
            self.env.cwd = "/"
            return self.ok()
        path = self.resolve(self.args[0])
        # Verify directory exists via list_dir
        result = await self.memfs.list_dir(path, recursive=False)
        if isinstance(result, str) and "Error" in result:
            return self.fail(f"cd: {self.args[0]}: No such file or directory\n")
        self.env.cwd = path
        return self.ok()


class PwdExec(BuiltinExec):
    """Print working directory."""

    name = "pwd"

    async def run(self) -> ShellResult:
        return self.ok(self.env.cwd + "\n")


class ExportExec(BuiltinExec):
    """Set environment variables."""

    name = "export"

    async def run(self) -> ShellResult:
        for arg in self.args:
            if "=" in arg:
                name, value = arg.split("=", 1)
                self.env.set_variable(name, value)
        return self.ok()


class EnvExec(BuiltinExec):
    """Print all environment variables."""

    name = "env"

    async def run(self) -> ShellResult:
        lines = [f"{k}={v}" for k, v in sorted(self.env.variables.items())]
        return self.ok("\n".join(lines) + "\n" if lines else "")
