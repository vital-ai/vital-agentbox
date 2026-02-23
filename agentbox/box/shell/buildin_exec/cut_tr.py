"""cut, tr — extract columns and translate characters."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class CutExec(BuiltinExec):
    """Extract fields or character ranges from lines.

    Supports: -d DELIM (delimiter), -f FIELDS (field list),
    -c CHARS (character positions), -s (suppress lines without delimiter).
    """

    name = "cut"

    async def run(self) -> ShellResult:
        flags, paths = self.split_flags_and_paths(
            known_flags={"-s"},
            value_flags={"-d", "-f", "-c"},
        )
        delim = flags.get("d", "\t")
        fields_spec = flags.get("f")
        chars_spec = flags.get("c")
        suppress = "s" in flags

        if not fields_spec and not chars_spec:
            return self.fail("cut: you must specify a list of bytes, characters, or fields\n")

        text = ""
        if paths:
            parts = []
            for p in paths:
                content = await self.read_file(p)
                if content is None:
                    return self.fail(f"cut: {p}: No such file or directory\n")
                parts.append(content)
            text = "".join(parts)
        elif self.stdin:
            text = self.stdin

        if not text:
            return self.ok("")

        indices = self._parse_spec(fields_spec or chars_spec)
        lines = text.splitlines()
        output = []

        for line in lines:
            if fields_spec:
                parts = line.split(delim)
                if suppress and delim not in line:
                    continue
                selected = []
                for idx in indices:
                    if 0 <= idx < len(parts):
                        selected.append(parts[idx])
                output.append(delim.join(selected))
            elif chars_spec:
                selected = []
                for idx in indices:
                    if 0 <= idx < len(line):
                        selected.append(line[idx])
                output.append("".join(selected))

        return self.ok("\n".join(output) + "\n" if output else "")

    @staticmethod
    def _parse_spec(spec):
        """Parse a field/char spec like '1,3', '1-3', '2-'."""
        indices = []
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                start = int(start) - 1 if start else 0
                end = int(end) - 1 if end else 999
                indices.extend(range(start, end + 1))
            else:
                indices.append(int(part) - 1)
        return sorted(set(indices))


class TrExec(BuiltinExec):
    """Translate or delete characters.

    Supports: tr SET1 SET2, tr -d SET1 (delete), tr -s SET1 (squeeze).
    """

    name = "tr"

    async def run(self) -> ShellResult:
        delete = False
        squeeze = False
        sets = []

        for arg in self.args:
            if arg == "-d":
                delete = True
            elif arg == "-s":
                squeeze = True
            elif not arg.startswith("-"):
                sets.append(self._expand_set(arg))

        text = self.stdin or ""
        if not text:
            return self.ok("")

        if delete:
            if not sets:
                return self.fail("tr: missing operand\n")
            chars_to_delete = set(sets[0])
            result = "".join(c for c in text if c not in chars_to_delete)
        elif squeeze and len(sets) >= 1:
            squeeze_chars = set(sets[0])
            result = []
            prev = None
            for c in text:
                if c in squeeze_chars and c == prev:
                    continue
                result.append(c)
                prev = c
            result = "".join(result)
        elif len(sets) >= 2:
            set1, set2 = sets[0], sets[1]
            # Pad set2 to length of set1 by repeating last char
            if len(set2) < len(set1) and set2:
                set2 = set2 + set2[-1] * (len(set1) - len(set2))
            table = str.maketrans(set1, set2[:len(set1)])
            result = text.translate(table)
        else:
            return self.fail("tr: missing operand\n")

        return self.ok(result)

    @staticmethod
    def _expand_set(spec):
        """Expand character set notation like 'a-z', 'A-Z', '[:lower:]'."""
        result = []
        i = 0
        while i < len(spec):
            if spec[i:].startswith("[:lower:]"):
                result.extend([chr(c) for c in range(ord("a"), ord("z") + 1)])
                i += 9
            elif spec[i:].startswith("[:upper:]"):
                result.extend([chr(c) for c in range(ord("A"), ord("Z") + 1)])
                i += 9
            elif spec[i:].startswith("[:digit:]"):
                result.extend([chr(c) for c in range(ord("0"), ord("9") + 1)])
                i += 9
            elif spec[i:].startswith("[:space:]"):
                result.extend([" ", "\t", "\n", "\r", "\f", "\v"])
                i += 9
            elif spec[i:].startswith("[:alpha:]"):
                result.extend([chr(c) for c in range(ord("a"), ord("z") + 1)])
                result.extend([chr(c) for c in range(ord("A"), ord("Z") + 1)])
                i += 9
            elif i + 2 < len(spec) and spec[i + 1] == "-":
                start = ord(spec[i])
                end = ord(spec[i + 2])
                result.extend([chr(c) for c in range(start, end + 1)])
                i += 3
            elif spec[i] == "\\":
                if i + 1 < len(spec):
                    esc = {"n": "\n", "t": "\t", "r": "\r"}.get(spec[i + 1], spec[i + 1])
                    result.append(esc)
                    i += 2
                else:
                    result.append("\\")
                    i += 1
            else:
                result.append(spec[i])
                i += 1
        return "".join(result)
