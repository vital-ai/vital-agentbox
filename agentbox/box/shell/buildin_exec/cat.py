"""cat — concatenate and print files."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class CatExec(BuiltinExec):
    name = "cat"

    async def run(self) -> ShellResult:
        number = False
        paths = []
        for arg in self.args:
            if arg == "-n":
                number = True
            elif arg.startswith("-") and len(arg) > 1:
                # Handle combined flags like -n
                if "n" in arg[1:]:
                    number = True
            else:
                paths.append(arg)

        if not paths:
            text = self.stdin or ""
            if number:
                text = self._number_lines(text)
            return self.ok(text)

        from agentbox.box.shell.virtual_bin import is_virtual_bin_file, virtual_bin_stub

        output_parts = []
        for path in paths:
            resolved = self.resolve(path)
            if is_virtual_bin_file(resolved):
                name = resolved.rsplit("/", 1)[-1]
                output_parts.append(virtual_bin_stub(name))
            else:
                content = await self.read_file(resolved)
                if content is None:
                    return self.fail(f"cat: {path}: No such file or directory\n")
                output_parts.append(content)

        text = "".join(output_parts)
        if number:
            text = self._number_lines(text)
        return self.ok(text)

    @staticmethod
    def _number_lines(text):
        if not text:
            return text
        lines = text.splitlines(keepends=True)
        return "".join(f"     {i + 1}\t{line}" for i, line in enumerate(lines))
