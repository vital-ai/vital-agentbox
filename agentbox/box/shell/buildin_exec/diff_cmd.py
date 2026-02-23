"""diff — compare files line by line."""

from __future__ import annotations

import difflib

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class DiffExec(BuiltinExec):
    """Compare two files line by line.

    Supports: -u (unified), -c (context), --brief (just report if different),
    -q (same as --brief).
    """

    name = "diff"

    async def run(self) -> ShellResult:
        flags, paths = self.split_flags_and_paths(
            known_flags={"-u", "-c", "-q", "--brief", "--unified", "--context"},
        )
        unified = "u" in flags or "unified" in flags
        context = "c" in flags or "context" in flags
        brief = "q" in flags or "brief" in flags

        if len(paths) < 2:
            return self.fail("diff: missing operand\n")

        file1, file2 = paths[0], paths[1]
        content1 = await self.read_file(file1)
        if content1 is None:
            return self.fail(f"diff: {file1}: No such file or directory\n")
        content2 = await self.read_file(file2)
        if content2 is None:
            return self.fail(f"diff: {file2}: No such file or directory\n")

        lines1 = content1.splitlines(keepends=True)
        lines2 = content2.splitlines(keepends=True)

        if lines1 == lines2:
            return self.ok("")

        if brief:
            return ShellResult(
                exit_code=1,
                stdout=f"Files {file1} and {file2} differ\n",
            )

        if unified or (not context):
            result = difflib.unified_diff(
                lines1, lines2,
                fromfile=file1, tofile=file2,
            )
        else:
            result = difflib.context_diff(
                lines1, lines2,
                fromfile=file1, tofile=file2,
            )

        output = "".join(result)
        return ShellResult(exit_code=1 if output else 0, stdout=output)
