"""
Tier 3: Host-delegated commands.

These commands require host-native binaries (pandoc, git, etc.) that cannot
run inside WASM. They execute as validated, sandboxed subprocesses on the host.

Each host command is an async function with the same signature as builtins:
    async def cmd(args, stdin, env, memfs) -> ShellResult

The registry is checked by CSTWalker after Tier 1 builtins and Tier 2
(python) but before "command not found".
"""

from agentbox.box.shell.host_commands.reportgen import host_reportgen
from agentbox.box.shell.host_commands.git_sync import (
    host_git_push,
    host_git_pull,
    host_git_fetch,
    host_git_clone,
)
from agentbox.box.shell.host_commands.boxcp import host_boxcp
from agentbox.box.shell.host_commands.outline_cmd import host_outline
from agentbox.box.shell.host_commands.tar_zip import host_tar, host_zip, host_unzip
from agentbox.box.shell.host_commands.awk_cmd import host_awk


HOST_COMMANDS = {
    "reportgen": host_reportgen,
    "boxcp": host_boxcp,
    "outline": host_outline,
    "git-push": host_git_push,
    "git-pull": host_git_pull,
    "git-fetch": host_git_fetch,
    "git-clone": host_git_clone,
    "tar": host_tar,
    "zip": host_zip,
    "unzip": host_unzip,
    "awk": host_awk,
    "gawk": host_awk,
}
