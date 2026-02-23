"""xargs — build and execute commands from stdin."""

from __future__ import annotations

import shlex

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class XargsExec(BuiltinExec):
    """Build command lines from standard input.

    Supports: xargs CMD (append stdin items as args),
    xargs -I {} CMD {} (replace placeholder), -n N (max args per command).
    """

    name = "xargs"

    async def run(self) -> ShellResult:
        replace = None
        max_args = None
        cmd_parts = []

        i = 0
        while i < len(self.args):
            if self.args[i] == "-I" and i + 1 < len(self.args):
                replace = self.args[i + 1]
                i += 2
            elif self.args[i] == "-n" and i + 1 < len(self.args):
                max_args = int(self.args[i + 1])
                i += 2
            elif self.args[i].startswith("-"):
                i += 1
            else:
                cmd_parts = self.args[i:]
                break

        if not cmd_parts:
            cmd_parts = ["echo"]

        text = self.stdin or ""
        items = text.split()
        if not items:
            return self.ok("")

        from agentbox.box.shell import ShellExecutor

        executor = ShellExecutor(self.memfs)
        executor.env = self.env

        all_stdout = []
        all_stderr = []
        last_exit = 0

        if replace:
            for item in items:
                cmd_str = " ".join(
                    shlex.quote(p.replace(replace, item)) for p in cmd_parts
                )
                r = await executor.run(cmd_str)
                all_stdout.append(r.stdout)
                all_stderr.append(r.stderr)
                last_exit = r.exit_code
        elif max_args:
            for start in range(0, len(items), max_args):
                batch = items[start : start + max_args]
                cmd_str = " ".join(
                    shlex.quote(p) for p in cmd_parts
                ) + " " + " ".join(shlex.quote(b) for b in batch)
                r = await executor.run(cmd_str)
                all_stdout.append(r.stdout)
                all_stderr.append(r.stderr)
                last_exit = r.exit_code
        else:
            cmd_str = " ".join(
                shlex.quote(p) for p in cmd_parts
            ) + " " + " ".join(shlex.quote(b) for b in items)
            r = await executor.run(cmd_str)
            all_stdout.append(r.stdout)
            all_stderr.append(r.stderr)
            last_exit = r.exit_code

        return ShellResult(
            exit_code=last_exit,
            stdout="".join(all_stdout),
            stderr="".join(all_stderr),
        )
