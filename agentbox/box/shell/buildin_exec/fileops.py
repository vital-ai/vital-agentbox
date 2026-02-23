"""cp, mv, rm, mkdir, rmdir, touch — file/directory operations."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class CpExec(BuiltinExec):
    """Copy files or directories."""

    name = "cp"

    async def run(self) -> ShellResult:
        recursive = False
        paths = []
        for arg in self.args:
            if arg == "-r" or arg == "-R":
                recursive = True
            elif not arg.startswith("-"):
                paths.append(arg)

        if len(paths) < 2:
            return self.fail("cp: missing operand\n")

        src = self.resolve(paths[0])
        dst = self.resolve(paths[1])
        result = await self.memfs.copy(src, dst)
        if result is True or result == True:
            return self.ok()
        return self.fail(f"cp: {result}\n")


class MvExec(BuiltinExec):
    """Move (rename) files or directories."""

    name = "mv"

    async def run(self) -> ShellResult:
        paths = [a for a in self.args if not a.startswith("-")]
        if len(paths) < 2:
            return self.fail("mv: missing operand\n")

        src = self.resolve(paths[0])
        dst = self.resolve(paths[1])

        copy_result = await self.memfs.copy(src, dst)
        if copy_result is not True and copy_result != True:
            return self.fail(f"mv: {copy_result}\n")

        remove_result = await self.memfs.remove_file(src)
        if not remove_result:
            # Try rmdir if it was a directory
            remove_result = await self.memfs.rmdir(src)
        return self.ok()


class RmExec(BuiltinExec):
    """Remove files."""

    name = "rm"

    async def run(self) -> ShellResult:
        recursive = False
        force = False
        paths = []
        for arg in self.args:
            if arg in ("-r", "-R", "-rf", "-fr"):
                recursive = True
                force = True
            elif arg == "-f":
                force = True
            elif not arg.startswith("-"):
                paths.append(arg)

        if not paths:
            return self.fail("rm: missing operand\n")

        for path in paths:
            resolved = self.resolve(path)
            result = await self.memfs.remove_file(resolved)
            if not result and not force:
                return self.fail(f"rm: cannot remove '{path}': No such file or directory\n")
        return self.ok()


class MkdirExec(BuiltinExec):
    """Create directories."""

    name = "mkdir"

    async def run(self) -> ShellResult:
        parents = False
        paths = []
        for arg in self.args:
            if arg == "-p":
                parents = True
            elif not arg.startswith("-"):
                paths.append(arg)

        if not paths:
            return self.fail("mkdir: missing operand\n")

        for path in paths:
            resolved = self.resolve(path)
            if parents:
                parts = resolved.split("/")
                current = ""
                for part in parts:
                    if not part:
                        continue
                    current += "/" + part
                    await self.memfs.mkdir(current)
            else:
                result = await self.memfs.mkdir(resolved)
                if not result:
                    return self.fail(f"mkdir: cannot create directory '{path}'\n")
        return self.ok()


class RmdirExec(BuiltinExec):
    """Remove empty directories."""

    name = "rmdir"

    async def run(self) -> ShellResult:
        paths = [a for a in self.args if not a.startswith("-")]
        if not paths:
            return self.fail("rmdir: missing operand\n")

        for path in paths:
            resolved = self.resolve(path)
            result = await self.memfs.rmdir(resolved)
            if not result:
                return self.fail(f"rmdir: failed to remove '{path}'\n")
        return self.ok()


class TouchExec(BuiltinExec):
    """Create empty file or update timestamp."""

    name = "touch"

    async def run(self) -> ShellResult:
        paths = [a for a in self.args if not a.startswith("-")]
        if not paths:
            return self.fail("touch: missing operand\n")

        for path in paths:
            resolved = self.resolve(path)
            content = await self.read_file(resolved)
            if content is None:
                await self.memfs.write_file(resolved, "")
        return self.ok()
