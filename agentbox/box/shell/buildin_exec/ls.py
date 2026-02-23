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
        paths = []

        for arg in self.args:
            if arg == "-r" or arg == "-R":
                recursive = True
            elif arg == "-l" or arg == "-la" or arg == "-al":
                show_info = True
            elif arg == "-lr" or arg == "-rl" or arg == "-lR" or arg == "-Rl":
                show_info = True
                recursive = True
            elif not arg.startswith("-"):
                paths.append(arg)

        if not paths:
            paths = [None]  # default: cwd

        all_lines = []
        multi = len(paths) > 1
        errors = []

        for path in paths:
            resolved = self.resolve(path) if path else self.env.cwd
            display = path or resolved

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
                        all_lines.append(f"file\t{st.get('size', 0)}\t{display}")
                    else:
                        all_lines.append(display)
                    continue
                errors.append(f"ls: cannot access '{display}': No such file or directory\n")
                continue

            if multi:
                all_lines.append(f"{display}:")

            if show_info and isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        t = item.get("type", "?")
                        s = item.get("size", "-")
                        n = item.get("name", "?")
                        all_lines.append(f"{t}\t{s}\t{n}")
                    else:
                        all_lines.append(str(item))
            elif isinstance(result, list):
                for x in result:
                    all_lines.append(str(x))
            elif isinstance(result, dict):
                all_lines.extend(_format_recursive(result, ""))

        stdout = "\n".join(all_lines) + "\n" if all_lines else ""
        stderr = "".join(errors)
        exit_code = 1 if (errors and not all_lines) else 0
        return ShellResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
