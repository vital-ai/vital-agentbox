"""
Tier 1 virtual shell builtins mapped to MemFS operations.

Each builtin is an async function with signature:
    async def cmd(args, stdin, env, memfs) -> ShellResult

All implementations live in agentbox/box/shell/buildin_exec/.
"""

from agentbox.box.shell.buildin_exec.ls import LsExec
from agentbox.box.shell.buildin_exec.cat import CatExec
from agentbox.box.shell.buildin_exec.echo import EchoExec, PrintfExec
from agentbox.box.shell.buildin_exec.fileops import (
    CpExec, MvExec, RmExec, MkdirExec, RmdirExec, TouchExec,
)
from agentbox.box.shell.buildin_exec.env_cmds import (
    CdExec, PwdExec, ExportExec, EnvExec,
)
from agentbox.box.shell.buildin_exec.misc import TeeExec, TrueExec, FalseExec
from agentbox.box.shell.buildin_exec.head_tail import HeadExec, TailExec
from agentbox.box.shell.buildin_exec.wc import WcExec
from agentbox.box.shell.buildin_exec.grep import GrepExec
from agentbox.box.shell.buildin_exec.find import FindExec
from agentbox.box.shell.buildin_exec.sed import SedExec
from agentbox.box.shell.buildin_exec.python_exec import PythonExec
from agentbox.box.shell.buildin_exec.pip import PipExec
from agentbox.box.shell.buildin_exec.shell_info import (
    WhichExec, CommandExec, TypeExec, TestExec,
)
from agentbox.box.shell.buildin_exec.edit import EditExec
from agentbox.box.shell.buildin_exec.apply_patch import ApplyPatchExec
from agentbox.box.git.builtin_git import builtin_git

BUILTINS = {
    "ls": LsExec.as_builtin(),
    "cat": CatExec.as_builtin(),
    "echo": EchoExec.as_builtin(),
    "printf": PrintfExec.as_builtin(),
    "cp": CpExec.as_builtin(),
    "mv": MvExec.as_builtin(),
    "rm": RmExec.as_builtin(),
    "mkdir": MkdirExec.as_builtin(),
    "rmdir": RmdirExec.as_builtin(),
    "touch": TouchExec.as_builtin(),
    "head": HeadExec.as_builtin(),
    "tail": TailExec.as_builtin(),
    "wc": WcExec.as_builtin(),
    "grep": GrepExec.as_builtin(),
    "cd": CdExec.as_builtin(),
    "pwd": PwdExec.as_builtin(),
    "export": ExportExec.as_builtin(),
    "env": EnvExec.as_builtin(),
    "tee": TeeExec.as_builtin(),
    "true": TrueExec.as_builtin(),
    "false": FalseExec.as_builtin(),
    "python": PythonExec.as_builtin(),
    "python3": PythonExec.as_builtin(),
    "find": FindExec.as_builtin(),
    "sed": SedExec.as_builtin(),
    "pip": PipExec.as_builtin(),
    "pip3": PipExec.as_builtin(),
    "git": builtin_git,
    "which": WhichExec.as_builtin(),
    "command": CommandExec.as_builtin(),
    "type": TypeExec.as_builtin(),
    "test": TestExec.as_builtin(),
    "[": TestExec.as_builtin(),
    "edit": EditExec.as_builtin(),
    "apply_patch": ApplyPatchExec.as_builtin(),
}
