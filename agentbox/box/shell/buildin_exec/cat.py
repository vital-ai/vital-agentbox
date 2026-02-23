"""cat — concatenate and print files."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class CatExec(BuiltinExec):
    name = "cat"

    async def run(self) -> ShellResult:
        if not self.args:
            # cat with no args reads from stdin
            return self.ok(self.stdin or "")

        from agentbox.box.shell.virtual_bin import is_virtual_bin_file, virtual_bin_stub

        output_parts = []
        for path in self.args:
            if path.startswith("-"):
                continue
            resolved = self.resolve(path)
            if is_virtual_bin_file(resolved):
                name = resolved.rsplit("/", 1)[-1]
                output_parts.append(virtual_bin_stub(name))
            else:
                content = await self.read_file(resolved)
                if content is None:
                    return self.fail(f"cat: {path}: No such file or directory\n")
                output_parts.append(content)
        return self.ok("".join(output_parts))
