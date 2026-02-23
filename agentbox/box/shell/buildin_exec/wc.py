"""wc — word, line, character count."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class WcExec(BuiltinExec):
    name = "wc"

    async def run(self) -> ShellResult:
        count_lines = False
        count_words = False
        count_chars = False
        paths: list[str] = []

        for a in self.args:
            if a == "-l":
                count_lines = True
            elif a == "-w":
                count_words = True
            elif a == "-c":
                count_chars = True
            elif not a.startswith("-"):
                paths.append(a)

        if not count_lines and not count_words and not count_chars:
            count_lines = count_words = count_chars = True

        output_rows: list[str] = []
        total_l = total_w = total_c = 0

        if not paths:
            paths = [None]

        for path in paths:
            if path:
                content = await self.read_file(path)
                if content is None:
                    return self.fail(f"wc: {path}: No such file or directory\n")
                text = content
            else:
                text = self.stdin or ""

            l = text.count("\n")
            w = len(text.split())
            c = len(text)
            total_l += l
            total_w += w
            total_c += c

            parts: list[str] = []
            if count_lines:
                parts.append(str(l))
            if count_words:
                parts.append(str(w))
            if count_chars:
                parts.append(str(c))
            if path:
                parts.append(path)
            output_rows.append(" ".join(parts))

        if len(paths) > 1 and paths[0] is not None:
            parts = []
            if count_lines:
                parts.append(str(total_l))
            if count_words:
                parts.append(str(total_w))
            if count_chars:
                parts.append(str(total_c))
            parts.append("total")
            output_rows.append(" ".join(parts))

        return self.ok("\n".join(output_rows) + "\n")
