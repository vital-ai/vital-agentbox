"""du, df — virtual disk usage commands for MemFS."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult

# Virtual disk size: 5 GB
_TOTAL_BYTES = 5 * 1024 * 1024 * 1024
_BLOCK_SIZE = 4096


class DuExec(BuiltinExec):
    """Estimate file space usage.

    Supports: -s (summary), -h (human-readable), -b (bytes).
    """

    name = "du"

    async def run(self) -> ShellResult:
        flags, paths = self.split_flags_and_paths(
            known_flags={"-s", "-h", "-b", "-a"},
        )
        summary = "s" in flags
        human = "h" in flags
        show_bytes = "b" in flags

        if not paths:
            paths = ["."]

        output = []
        for path in paths:
            resolved = self.resolve(path)
            total = await self._calc_size(resolved, output, summary, human, show_bytes, path)
            if total is None:
                return self.fail(f"du: cannot access '{path}': No such file or directory\n")
            size_str = self._format(total, human, show_bytes)
            output.append(f"{size_str}\t{path}")

        return self.ok("\n".join(output) + "\n" if output else "")

    async def _calc_size(self, resolved, output, summary, human, show_bytes, display):
        st = await self.memfs.stat(resolved)
        if st is None:
            return None
        if st.get("type") == "file":
            return st.get("size", 0)

        entries = await self.memfs.list_dir(resolved, info=True)
        if not isinstance(entries, list):
            return 0

        total = 0
        for item in entries:
            name = item.get("name", "")
            size = item.get("size") or 0
            child_path = f"{display}/{name}"
            if item.get("type") == "dir":
                child_resolved = f"{resolved}/{name}"
                subtotal = await self._calc_size(
                    child_resolved, output, summary, human, show_bytes, child_path
                )
                size = subtotal or 0
            total += size
            if not summary:
                size_str = self._format(size, human, show_bytes)
                output.append(f"{size_str}\t{child_path}")
        return total

    @staticmethod
    def _format(size, human, show_bytes):
        if show_bytes:
            return str(size)
        if human:
            for unit in ("", "K", "M", "G"):
                if size < 1024:
                    return f"{size:.0f}{unit}" if unit else str(size)
                size /= 1024
            return f"{size:.1f}T"
        # Default: 1K blocks
        return str((size + 1023) // 1024)


class DfExec(BuiltinExec):
    """Report virtual filesystem disk space usage.

    Supports: -h (human-readable).
    """

    name = "df"

    async def run(self) -> ShellResult:
        human = "-h" in self.args

        used = await self._total_used()
        avail = _TOTAL_BYTES - used

        if human:
            header = "Filesystem      Size  Used Avail Use% Mounted on\n"
            line = f"{'memfs':<16}{'5.0G':>4}  {self._human(used):>4} {self._human(avail):>4}  {used * 100 // _TOTAL_BYTES:>2}% /\n"
        else:
            total_blocks = _TOTAL_BYTES // 1024
            used_blocks = used // 1024
            avail_blocks = avail // 1024
            header = "Filesystem     1K-blocks    Used Available Use% Mounted on\n"
            line = f"{'memfs':<15}{total_blocks:>9} {used_blocks:>7} {avail_blocks:>9}  {used * 100 // _TOTAL_BYTES:>2}% /\n"

        return self.ok(header + line)

    async def _total_used(self):
        """Walk MemFS and sum all file sizes."""
        return await self._walk_size("/")

    async def _walk_size(self, path):
        entries = await self.memfs.list_dir(path, info=True)
        if not isinstance(entries, list):
            return 0
        total = 0
        for item in entries:
            if item.get("type") == "file":
                total += item.get("size", 0)
            elif item.get("type") == "dir":
                name = item.get("name", "")
                child = f"{path}/{name}" if path != "/" else f"/{name}"
                total += await self._walk_size(child)
        return total

    @staticmethod
    def _human(size):
        for unit in ("B", "K", "M", "G"):
            if size < 1024:
                return f"{size:.1f}{unit}" if unit in ("M", "G") else f"{size}{unit}"
            size /= 1024
        return f"{size:.1f}T"
