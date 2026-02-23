"""echo / printf — output text."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


def _interpret_escapes(text):
    """Interpret C-style escape sequences: \\n, \\t, \\\\, etc."""
    result = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            c = text[i + 1]
            if c == "n":
                result.append("\n")
            elif c == "t":
                result.append("\t")
            elif c == "r":
                result.append("\r")
            elif c == "\\":
                result.append("\\")
            elif c == "0":
                result.append("\0")
            elif c == "a":
                result.append("\a")
            elif c == "b":
                result.append("\b")
            elif c == "f":
                result.append("\f")
            elif c == "v":
                result.append("\v")
            else:
                result.append("\\")
                result.append(c)
            i += 2
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


class EchoExec(BuiltinExec):
    """Print arguments to stdout. Supports -n and -e flags."""

    name = "echo"

    async def run(self) -> ShellResult:
        no_newline = False
        interpret = False
        start = 0
        # Parse flags (echo accepts -n, -e, -ne, -en, etc.)
        while start < len(self.args) and self.args[start].startswith("-") and len(self.args[start]) > 1:
            flag = self.args[start]
            if all(c in "ne" for c in flag[1:]):
                if "n" in flag:
                    no_newline = True
                if "e" in flag:
                    interpret = True
                start += 1
            else:
                break
        text = " ".join(self.args[start:])
        if interpret:
            text = _interpret_escapes(text)
        if not no_newline:
            text += "\n"
        return self.ok(text)


class PrintfExec(BuiltinExec):
    """printf FORMAT [ARGUMENTS...] — formatted output."""

    name = "printf"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.ok()
        fmt = self.args[0]
        fmt_args = self.args[1:]
        # Interpret escape sequences in the format string
        fmt = _interpret_escapes(fmt)
        # Simple %s and %d substitution
        output = ""
        if not fmt_args:
            output = fmt
        else:
            for arg in fmt_args:
                output += fmt.replace("%s", arg).replace("%d", arg)
        return self.ok(output)
