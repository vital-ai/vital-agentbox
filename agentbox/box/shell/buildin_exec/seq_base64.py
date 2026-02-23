"""seq, base64, md5sum, sha256sum, nl, rev — utility builtins."""

from __future__ import annotations

import base64 as _base64
import hashlib

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class SeqExec(BuiltinExec):
    """Print a sequence of numbers.

    Supports: seq LAST, seq FIRST LAST, seq FIRST INCREMENT LAST,
    -s SEP (separator, default newline).
    """

    name = "seq"

    async def run(self) -> ShellResult:
        sep = "\n"
        nums = []
        i = 0
        while i < len(self.args):
            if self.args[i] == "-s" and i + 1 < len(self.args):
                sep = self.args[i + 1]
                i += 2
            elif not self.args[i].startswith("-") or self.args[i].lstrip("-").replace(".", "").isdigit():
                nums.append(self.args[i])
                i += 1
            else:
                i += 1

        try:
            if len(nums) == 1:
                first, inc, last = 1, 1, int(nums[0])
            elif len(nums) == 2:
                first, inc, last = int(nums[0]), 1, int(nums[1])
            elif len(nums) >= 3:
                first, inc, last = int(nums[0]), int(nums[1]), int(nums[2])
            else:
                return self.fail("seq: missing operand\n")
        except ValueError:
            return self.fail("seq: invalid number\n")

        if inc == 0:
            return self.fail("seq: zero increment\n")

        result = []
        n = first
        if inc > 0:
            while n <= last:
                result.append(str(n))
                n += inc
        else:
            while n >= last:
                result.append(str(n))
                n += inc

        return self.ok(sep.join(result) + "\n" if result else "")


class Base64Exec(BuiltinExec):
    """Encode or decode base64.

    Supports: base64 [FILE] (encode), base64 -d [FILE] (decode).
    """

    name = "base64"

    async def run(self) -> ShellResult:
        decode = False
        paths = []
        for arg in self.args:
            if arg in ("-d", "--decode"):
                decode = True
            elif not arg.startswith("-"):
                paths.append(arg)

        text = ""
        if paths:
            content = await self.read_file(paths[0])
            if content is None:
                return self.fail(f"base64: {paths[0]}: No such file or directory\n")
            text = content
        elif self.stdin:
            text = self.stdin

        try:
            if decode:
                result = _base64.b64decode(text.strip()).decode("utf-8", errors="replace")
            else:
                result = _base64.b64encode(text.encode("utf-8")).decode("ascii") + "\n"
        except Exception as e:
            return self.fail(f"base64: {e}\n")

        return self.ok(result)


class Md5sumExec(BuiltinExec):
    """Compute MD5 hash of files or stdin."""

    name = "md5sum"

    async def run(self) -> ShellResult:
        return await self._hash("md5")

    async def _hash(self, algo):
        paths = [a for a in self.args if not a.startswith("-")]
        if paths:
            output = []
            for p in paths:
                content = await self.read_file(p)
                if content is None:
                    return self.fail(f"{self.name}: {p}: No such file or directory\n")
                h = hashlib.new(algo, content.encode("utf-8")).hexdigest()
                output.append(f"{h}  {p}")
            return self.ok("\n".join(output) + "\n")
        elif self.stdin:
            h = hashlib.new(algo, self.stdin.encode("utf-8")).hexdigest()
            return self.ok(h + "  -\n")
        return self.ok("")


class Sha256sumExec(Md5sumExec):
    """Compute SHA-256 hash of files or stdin."""

    name = "sha256sum"

    async def run(self) -> ShellResult:
        return await self._hash("sha256")


class NlExec(BuiltinExec):
    """Number lines of files."""

    name = "nl"

    async def run(self) -> ShellResult:
        paths = [a for a in self.args if not a.startswith("-")]
        text = ""
        if paths:
            parts = []
            for p in paths:
                content = await self.read_file(p)
                if content is None:
                    return self.fail(f"nl: {p}: No such file or directory\n")
                parts.append(content)
            text = "".join(parts)
        elif self.stdin:
            text = self.stdin

        if not text:
            return self.ok("")

        lines = text.splitlines()
        output = []
        num = 1
        for line in lines:
            if line.strip():
                output.append(f"     {num}\t{line}")
                num += 1
            else:
                output.append(f"       \t{line}")
        return self.ok("\n".join(output) + "\n")


class RevExec(BuiltinExec):
    """Reverse lines character-wise."""

    name = "rev"

    async def run(self) -> ShellResult:
        paths = [a for a in self.args if not a.startswith("-")]
        text = ""
        if paths:
            content = await self.read_file(paths[0])
            if content is None:
                return self.fail(f"rev: {paths[0]}: No such file or directory\n")
            text = content
        elif self.stdin:
            text = self.stdin

        if not text:
            return self.ok("")

        lines = text.splitlines()
        output = [line[::-1] for line in lines]
        return self.ok("\n".join(output) + "\n")
