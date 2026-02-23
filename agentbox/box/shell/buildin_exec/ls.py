"""ls — list directory contents."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


def _format_recursive(tree, prefix):
    """Format recursive listing dict into lines."""
    lines = []
    if isinstance(tree, dict):
        for name, value in sorted(tree.items()):
            path = f"{prefix}/{name}" if prefix else name
            if isinstance(value, dict):
                lines.append(path + "/")
                lines.extend(_format_recursive(value, path))
            else:
                lines.append(path)
    elif isinstance(tree, list):
        for item in tree:
            if isinstance(item, dict):
                name = item.get("name", "?")
                path = f"{prefix}/{name}" if prefix else name
                if item.get("type") == "dir":
                    lines.append(path + "/")
                    children = item.get("children", [])
                    lines.extend(_format_recursive(children, path))
                else:
                    lines.append(path)
            else:
                lines.append(str(item))
    return lines


class LsExec(BuiltinExec):
    name = "ls"

    async def run(self) -> ShellResult:
        recursive = False
        show_info = False
        path = None

        for arg in self.args:
            if arg == "-r" or arg == "-R":
                recursive = True
            elif arg == "-l" or arg == "-la" or arg == "-al":
                show_info = True
            elif arg == "-lr" or arg == "-rl" or arg == "-lR" or arg == "-Rl":
                show_info = True
                recursive = True
            elif not arg.startswith("-"):
                path = arg

        resolved = self.resolve(path) if path else self.env.cwd

        # Virtual /bin directory
        from agentbox.box.shell.virtual_bin import is_virtual_bin_dir, virtual_bin_list
        if is_virtual_bin_dir(resolved):
            result = virtual_bin_list(info=show_info)
        else:
            result = await self.memfs.list_dir(resolved, recursive=recursive, info=show_info)

        if isinstance(result, str) and result.startswith("Error"):
            # Might be a file path, not a directory — try stat
            st = await self.memfs.stat(resolved)
            if st and st.get("type") == "file":
                if show_info:
                    return self.ok(f"file\t{st.get('size', 0)}\t{path or resolved}\n")
                return self.ok(f"{path or resolved}\n")
            return ShellResult(exit_code=1, stderr=f"ls: {result}")

        if show_info and isinstance(result, list):
            lines = []
            for item in result:
                if isinstance(item, dict):
                    t = item.get("type", "?")
                    s = item.get("size", "-")
                    n = item.get("name", "?")
                    lines.append(f"{t}\t{s}\t{n}")
                else:
                    lines.append(str(item))
            return ShellResult(stdout="\n".join(lines) + "\n" if lines else "")

        if isinstance(result, list):
            return ShellResult(stdout="\n".join(str(x) for x in result) + "\n" if result else "")
        elif isinstance(result, dict):
            lines = _format_recursive(result, "")
            return ShellResult(stdout="\n".join(lines) + "\n" if lines else "")
        return ShellResult(stdout=str(result) + "\n")
