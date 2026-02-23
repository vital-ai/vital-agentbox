"""awk — host-delegated text processing.

Extracts input from MemFS, runs host awk, returns output.
"""

from __future__ import annotations

import asyncio
import shutil

from agentbox.box.shell.environment import ShellResult


async def host_awk(args, stdin, env, memfs) -> ShellResult:
    """Run awk on the host with input from MemFS or stdin."""
    awk_path = shutil.which("awk") or shutil.which("gawk") or shutil.which("mawk")
    if not awk_path:
        return ShellResult(exit_code=1, stderr="awk: not installed on host\n")

    # Separate awk flags/program from file args
    # awk 'program' [file ...]
    # awk -F, 'program' [file ...]
    awk_args = []
    file_args = []
    program = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-F", "-v") and i + 1 < len(args):
            awk_args.extend([a, args[i + 1]])
            i += 2
        elif a.startswith("-F"):
            awk_args.append(a)
            i += 1
        elif program is None and not a.startswith("-"):
            program = a
            i += 1
        elif program is not None and not a.startswith("-"):
            file_args.append(a)
            i += 1
        else:
            awk_args.append(a)
            i += 1

    if program is None:
        return ShellResult(exit_code=1, stderr="awk: missing program\n")

    # Build input text
    input_text = ""
    if file_args:
        parts = []
        for fp in file_args:
            resolved = env.resolve_path(fp)
            content = await memfs.read_file(resolved)
            if content is None:
                return ShellResult(exit_code=1, stderr=f"awk: {fp}: No such file or directory\n")
            parts.append(content)
        input_text = "".join(parts)
    elif stdin:
        input_text = stdin

    cmd = [awk_path] + awk_args + [program]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=input_text.encode("utf-8"))

    return ShellResult(
        exit_code=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )
