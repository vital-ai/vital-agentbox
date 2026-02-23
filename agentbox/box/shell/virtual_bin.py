"""Virtual /bin and /usr/bin directories.

Makes the sandbox look like a real Linux environment by exposing
all registered builtins as virtual executables at /bin/<name>.
No real files are created in MemFS — the ls, cat, which, and
command builtins consult this module instead.
"""

from __future__ import annotations

_VIRTUAL_DIRS = ("/bin", "/usr/bin")


def is_virtual_bin_dir(path: str) -> bool:
    """Return True if *path* is a virtual bin directory."""
    return path.rstrip("/") in _VIRTUAL_DIRS


def _all_commands() -> dict:
    """Return merged dict of builtins + host commands."""
    from agentbox.box.shell.builtins import BUILTINS
    from agentbox.box.shell.host_commands import HOST_COMMANDS
    return {**BUILTINS, **HOST_COMMANDS}


def is_virtual_bin_file(path: str) -> bool:
    """Return True if *path* looks like /bin/<name> for a known command."""
    cmds = _all_commands()
    for d in _VIRTUAL_DIRS:
        prefix = d + "/"
        if path.startswith(prefix):
            name = path[len(prefix):]
            if name and "/" not in name and name in cmds:
                return True
    return False


def virtual_bin_names() -> list[str]:
    """Return sorted list of all command names (builtins + host commands)."""
    return sorted(_all_commands().keys())


def virtual_bin_path(name: str) -> str | None:
    """Return /bin/<name> if *name* is a known command, else None."""
    if name in _all_commands():
        return f"/bin/{name}"
    return None


def virtual_bin_stub(name: str) -> str:
    """Return a stub script for cat /bin/<name>."""
    return f"#!/bin/sh\n# builtin: {name}\nexec {name} \"$@\"\n"


def virtual_bin_list(info: bool = False) -> list:
    """Return entries for ls /bin.

    If *info* is True, returns list of dicts with name/type/size.
    Otherwise returns list of name strings.
    """
    names = virtual_bin_names()
    if info:
        return [{"name": n, "type": "file", "size": 0} for n in names]
    return names
