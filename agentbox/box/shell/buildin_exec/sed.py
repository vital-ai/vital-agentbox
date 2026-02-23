"""sed — stream editor for filtering and transforming text."""

from __future__ import annotations

import re

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class SedExec(BuiltinExec):
    name = "sed"

    async def run(self) -> ShellResult:
        in_place = False
        expression: str | None = None
        filepath: str | None = None

        i = 0
        while i < len(self.args):
            a = self.args[i]
            if a == "-i":
                in_place = True
            elif a == "-e" and i + 1 < len(self.args):
                i += 1
                expression = self.args[i]
            elif expression is None and not a.startswith("-"):
                expression = a
            elif filepath is None and not a.startswith("-"):
                filepath = a
            i += 1

        if expression is None:
            return self.fail("sed: no expression provided\n")

        # Parse s/old/new/flags
        if expression.startswith("s") and len(expression) > 3:
            delim = expression[1]
            parts = expression[2:].split(delim)
            if len(parts) >= 2:
                old = parts[0]
                new = parts[1]
                flags_str = parts[2] if len(parts) > 2 else ""
                global_replace = "g" in flags_str

                text = ""
                if filepath:
                    content = await self.read_file(filepath)
                    if content is None:
                        return self.fail(f"sed: {filepath}: No such file or directory\n")
                    text = content
                elif self.stdin:
                    text = self.stdin
                else:
                    return self.fail("sed: no input\n")

                if global_replace:
                    result = re.sub(old, new, text)
                else:
                    result = re.sub(old, new, text, count=1)

                if in_place and filepath:
                    await self.write_file(filepath, result)
                    return self.ok()
                return self.ok(result)

        return self.fail(f"sed: invalid expression: {expression}\n")
