"""chmod, sleep, uuidgen, mktemp — utility/no-op builtins for sandbox."""

from __future__ import annotations

import uuid

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class ChmodExec(BuiltinExec):
    """No-op chmod — permissions are not enforced in MemFS."""

    name = "chmod"

    async def run(self) -> ShellResult:
        # Silently succeed — MemFS has no permission model
        return self.ok()


class SleepExec(BuiltinExec):
    """No-op sleep — returns immediately in sandbox."""

    name = "sleep"

    async def run(self) -> ShellResult:
        return self.ok()


class CurlExec(BuiltinExec):
    """curl — blocked by sandbox isolation."""

    name = "curl"

    async def run(self) -> ShellResult:
        return self.fail(
            "curl: network access is not available inside the sandbox.\n"
            "Use Python's httpx or requests via pip install if needed.\n"
        )


class WgetExec(BuiltinExec):
    """wget — blocked by sandbox isolation."""

    name = "wget"

    async def run(self) -> ShellResult:
        return self.fail(
            "wget: network access is not available inside the sandbox.\n"
            "Use Python's httpx or requests via pip install if needed.\n"
        )


class UuidgenExec(BuiltinExec):
    """Generate a new UUID."""

    name = "uuidgen"

    async def run(self) -> ShellResult:
        return self.ok(str(uuid.uuid4()) + "\n")


class PsExec(BuiltinExec):
    """Stub ps — report a single sandbox process."""

    name = "ps"

    async def run(self) -> ShellResult:
        return self.ok(
            "  PID TTY          TIME CMD\n"
            "    1 ?        00:00:00 sandbox\n"
        )


class KillExec(BuiltinExec):
    """Stub kill — no processes to kill in sandbox."""

    name = "kill"

    async def run(self) -> ShellResult:
        return self.ok()


class WhoamiExec(BuiltinExec):
    """Return sandbox user identity."""

    name = "whoami"

    async def run(self) -> ShellResult:
        return self.ok("sandbox\n")


class IdExec(BuiltinExec):
    """Return sandbox user identity."""

    name = "id"

    async def run(self) -> ShellResult:
        return self.ok("uid=1000(sandbox) gid=1000(sandbox) groups=1000(sandbox)\n")


class HostnameExec(BuiltinExec):
    """Return sandbox hostname."""

    name = "hostname"

    async def run(self) -> ShellResult:
        return self.ok("sandbox\n")


class UnameExec(BuiltinExec):
    """Return system info stub."""

    name = "uname"

    async def run(self) -> ShellResult:
        if "-a" in self.args:
            return self.ok("Linux sandbox 6.1.0 #1 SMP PREEMPT_DYNAMIC x86_64 GNU/Linux\n")
        return self.ok("Linux\n")


class UptimeExec(BuiltinExec):
    """Stub uptime."""

    name = "uptime"

    async def run(self) -> ShellResult:
        return self.ok(" 00:00:00 up 0 min,  1 user,  load average: 0.00, 0.00, 0.00\n")


class FreeExec(BuiltinExec):
    """Stub free — report virtual memory."""

    name = "free"

    _TOTAL = 8 * 1024 * 1024  # 8 GB in KB

    async def run(self) -> ShellResult:
        human = "-h" in self.args
        if human:
            return self.ok(
                "              total        used        free\n"
                "Mem:          8.0G        0.1G        7.9G\n"
                "Swap:            0           0           0\n"
            )
        t = self._TOTAL
        return self.ok(
            "              total        used        free\n"
            f"Mem:      {t:>9} {t // 80:>11} {t - t // 80:>11}\n"
            f"Swap:     {'0':>9} {'0':>11} {'0':>11}\n"
        )


class LsofExec(BuiltinExec):
    """Stub lsof — no open file descriptors in sandbox."""

    name = "lsof"

    async def run(self) -> ShellResult:
        return self.ok("")


class NohupExec(BuiltinExec):
    """Stub nohup — just run the command (no background support)."""

    name = "nohup"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("nohup: missing operand\n")
        from agentbox.box.shell import ShellExecutor
        executor = ShellExecutor(self.memfs)
        executor.env = self.env
        cmd_str = " ".join(self.args)
        return await executor.run(cmd_str)


class JobsExec(BuiltinExec):
    """Stub jobs/bg/fg — no job control in sandbox."""

    name = "jobs"

    async def run(self) -> ShellResult:
        return self.ok("")


class ManExec(BuiltinExec):
    """Stub man — suggest --help instead."""

    name = "man"

    async def run(self) -> ShellResult:
        topic = self.args[0] if self.args else ""
        return self.fail(f"man: no manual entry for {topic}\nTry: {topic} --help\n")


class SudoExec(BuiltinExec):
    """Stub sudo — just run the command (no privilege model)."""

    name = "sudo"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("sudo: missing command\n")
        from agentbox.box.shell import ShellExecutor
        executor = ShellExecutor(self.memfs)
        executor.env = self.env
        cmd_str = " ".join(self.args)
        return await executor.run(cmd_str)


class ChownExec(BuiltinExec):
    """No-op chown — no ownership model in MemFS."""

    name = "chown"

    async def run(self) -> ShellResult:
        return self.ok()


class LnExec(BuiltinExec):
    """ln — not available in sandbox (MemFS has no symlinks or hard links)."""

    name = "ln"

    async def run(self) -> ShellResult:
        return self.fail("ln: links are not supported in the sandbox filesystem.\nUse cp to create a copy instead.\n")


class MktempExec(BuiltinExec):
    """Create a temporary file or directory in MemFS.

    Supports: mktemp [-d] [-p DIR] [TEMPLATE]
    """

    name = "mktemp"

    async def run(self) -> ShellResult:
        make_dir = False
        parent = "/tmp"
        template = None

        i = 0
        while i < len(self.args):
            a = self.args[i]
            if a == "-d":
                make_dir = True
            elif a == "-p" and i + 1 < len(self.args):
                parent = self.args[i + 1]
                i += 1
            elif not a.startswith("-"):
                template = a
            i += 1

        name = template.replace("XXXXXX", uuid.uuid4().hex[:6]) if template else f"tmp.{uuid.uuid4().hex[:8]}"
        path = f"{parent}/{name}"
        resolved = self.resolve(path)

        if make_dir:
            await self.memfs.mkdir_p(resolved)
        else:
            await self.memfs.mkdir_p(self.resolve(parent))
            await self.memfs.write_file(resolved, "")

        return self.ok(resolved + "\n")
