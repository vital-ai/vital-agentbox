"""sort, uniq — sort and deduplicate lines."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class SortExec(BuiltinExec):
    """Sort lines of text.

    Supports: -r (reverse), -n (numeric), -u (unique), -k N (key field),
    -t SEP (field separator).
    """

    name = "sort"

    async def run(self) -> ShellResult:
        flags, paths = self.split_flags_and_paths(
            known_flags={"-r", "-n", "-u", "-f"},
            value_flags={"-k", "-t"},
        )
        reverse = "r" in flags
        numeric = "n" in flags
        unique = "u" in flags
        ignore_case = "f" in flags
        key_field = flags.get("k")
        separator = flags.get("t")

        text = ""
        if paths:
            parts = []
            for p in paths:
                content = await self.read_file(p)
                if content is None:
                    return self.fail(f"sort: {p}: No such file or directory\n")
                parts.append(content)
            text = "".join(parts)
        elif self.stdin:
            text = self.stdin

        if not text:
            return self.ok("")

        lines = text.splitlines()

        def sort_key(line):
            val = line
            if separator and key_field:
                parts = line.split(separator)
                idx = int(key_field.split(",")[0]) - 1
                val = parts[idx] if 0 <= idx < len(parts) else line
            elif key_field:
                parts = line.split()
                idx = int(key_field.split(",")[0]) - 1
                val = parts[idx] if 0 <= idx < len(parts) else line
            if ignore_case:
                val = val.lower()
            if numeric:
                try:
                    return (0, float(val))
                except ValueError:
                    return (1, val)
            return val

        lines.sort(key=sort_key, reverse=reverse)

        if unique:
            seen = set()
            deduped = []
            for line in lines:
                k = line.lower() if ignore_case else line
                if k not in seen:
                    seen.add(k)
                    deduped.append(line)
            lines = deduped

        return self.ok("\n".join(lines) + "\n")


class UniqExec(BuiltinExec):
    """Filter adjacent duplicate lines.

    Supports: -c (count), -d (only duplicates), -i (ignore case).
    """

    name = "uniq"

    async def run(self) -> ShellResult:
        flags, paths = self.split_flags_and_paths(
            known_flags={"-c", "-d", "-i", "-u"},
        )
        count = "c" in flags
        only_dupes = "d" in flags
        ignore_case = "i" in flags
        only_unique = "u" in flags

        text = ""
        if paths:
            content = await self.read_file(paths[0])
            if content is None:
                return self.fail(f"uniq: {paths[0]}: No such file or directory\n")
            text = content
        elif self.stdin:
            text = self.stdin

        if not text:
            return self.ok("")

        lines = text.splitlines()
        groups = []
        for line in lines:
            key = line.lower() if ignore_case else line
            if groups and groups[-1][0] == key:
                groups[-1] = (key, groups[-1][1] + 1, line)
            else:
                groups.append((key, 1, line))

        output = []
        for _key, cnt, line in groups:
            if only_dupes and cnt < 2:
                continue
            if only_unique and cnt > 1:
                continue
            if count:
                output.append(f"{cnt:>4} {line}")
            else:
                output.append(line)

        return self.ok("\n".join(output) + "\n" if output else "")
