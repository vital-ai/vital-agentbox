"""grep — search for patterns in files or stdin."""

from __future__ import annotations

import re

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class GrepExec(BuiltinExec):
    name = "grep"

    async def run(self) -> ShellResult:
        pattern = None
        paths: list[str] = []
        invert = False
        count_only = False
        ignore_case = False
        line_numbers = False
        after_ctx = 0
        before_ctx = 0

        i = 0
        while i < len(self.args):
            a = self.args[i]
            if a == "-v":
                invert = True
            elif a == "-c":
                count_only = True
            elif a == "-i":
                ignore_case = True
            elif a == "-n":
                line_numbers = True
            elif a in ("-r", "-R"):
                pass  # recursive — accepted but not special yet
            elif a in ("-E", "-l"):
                pass  # accepted, no-op
            elif a == "-A" and i + 1 < len(self.args):
                i += 1
                try:
                    after_ctx = int(self.args[i])
                except ValueError:
                    pass
            elif a.startswith("-A") and len(a) > 2:
                try:
                    after_ctx = int(a[2:])
                except ValueError:
                    pass
            elif a == "-B" and i + 1 < len(self.args):
                i += 1
                try:
                    before_ctx = int(self.args[i])
                except ValueError:
                    pass
            elif a.startswith("-B") and len(a) > 2:
                try:
                    before_ctx = int(a[2:])
                except ValueError:
                    pass
            elif a.startswith("-") and len(a) > 1:
                for c in a[1:]:
                    if c == "v":
                        invert = True
                    elif c == "c":
                        count_only = True
                    elif c == "i":
                        ignore_case = True
                    elif c == "n":
                        line_numbers = True
            elif pattern is None:
                pattern = a
            else:
                paths.append(a)
            i += 1

        if pattern is None:
            return self.fail("grep: missing pattern\n", code=2)

        flags = re.IGNORECASE if ignore_case else 0

        # Gather input texts
        texts: list[tuple[str | None, str]] = []
        if paths:
            for p in paths:
                content = await self.read_file(p)
                if content is None:
                    return self.fail(f"grep: {p}: No such file or directory\n", code=2)
                texts.append((p, content))
        else:
            texts.append((None, self.stdin or ""))

        output_lines: list[str] = []
        match_found = False

        for filename, text in texts:
            lines = text.split("\n")
            matched_ranges: set[int] = set()

            for idx, line in enumerate(lines):
                hit = bool(re.search(pattern, line, flags))
                if invert:
                    hit = not hit
                if hit:
                    match_found = True
                    lo = max(0, idx - before_ctx)
                    hi = min(len(lines), idx + after_ctx + 1)
                    matched_ranges.update(range(lo, hi))

            if count_only:
                cnt = sum(
                    1 for idx, line in enumerate(lines)
                    if bool(re.search(pattern, line, flags)) != invert
                )
                output_lines.append(str(cnt))
                continue

            for idx in sorted(matched_ranges):
                prefix = ""
                if filename and len(texts) > 1:
                    prefix = f"{filename}:"
                if line_numbers:
                    prefix += f"{idx + 1}:"
                output_lines.append(f"{prefix}{lines[idx]}")

        if count_only:
            return ShellResult(
                stdout="\n".join(output_lines) + "\n",
                exit_code=0 if match_found else 1,
            )
        if output_lines:
            return self.ok("\n".join(output_lines) + "\n")
        return ShellResult(exit_code=1)
