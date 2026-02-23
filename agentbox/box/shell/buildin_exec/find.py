"""find — search for files in a directory hierarchy."""

from __future__ import annotations

import fnmatch

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class FindExec(BuiltinExec):
    name = "find"

    async def run(self) -> ShellResult:
        search_path: str | None = None
        name_pattern: str | None = None
        type_filter: str | None = None  # 'f' for file, 'd' for directory
        max_depth: int | None = None

        i = 0
        while i < len(self.args):
            a = self.args[i]
            if a == "-name" and i + 1 < len(self.args):
                i += 1
                name_pattern = self.args[i]
            elif a == "-type" and i + 1 < len(self.args):
                i += 1
                type_filter = self.args[i]
            elif a == "-maxdepth" and i + 1 < len(self.args):
                i += 1
                try:
                    max_depth = int(self.args[i])
                except ValueError:
                    pass
            elif not a.startswith("-") and search_path is None:
                search_path = a
            i += 1

        if search_path is None:
            search_path = "."
        resolved = self.resolve(search_path)

        output_lines: list[str] = []

        async def _walk(path: str, depth: int = 0) -> None:
            if max_depth is not None and depth > max_depth:
                return
            entries = await self.memfs.list_dir(path, recursive=False)
            if isinstance(entries, str):
                return
            for entry in entries:
                entry_name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
                entry_path = path.rstrip("/") + "/" + entry_name
                is_dir = entry.get("is_dir", False) if isinstance(entry, dict) else False

                # Check type filter
                show = True
                if type_filter == "f" and is_dir:
                    show = False
                elif type_filter == "d" and not is_dir:
                    show = False

                if show:
                    if name_pattern is None or fnmatch.fnmatch(entry_name, name_pattern):
                        if resolved == "/":
                            display = entry_path
                        else:
                            display = search_path.rstrip("/") + entry_path[len(resolved):]
                        output_lines.append(display)

                if is_dir:
                    await _walk(entry_path, depth + 1)

        await _walk(resolved)
        if output_lines:
            return self.ok("\n".join(output_lines) + "\n")
        return ShellResult(exit_code=0)
