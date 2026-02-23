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
from agentbox.box.shell.buildin_exec.date import DateExec
from agentbox.box.shell.buildin_exec.sort_uniq import SortExec, UniqExec
from agentbox.box.shell.buildin_exec.cut_tr import CutExec, TrExec
from agentbox.box.shell.buildin_exec.diff_cmd import DiffExec
from agentbox.box.shell.buildin_exec.path_cmds import BasenameExec, DirnameExec, RealpathExec
from agentbox.box.shell.buildin_exec.xargs import XargsExec
from agentbox.box.shell.buildin_exec.noop_cmds import (
    ChmodExec, SleepExec, CurlExec, WgetExec, UuidgenExec, MktempExec,
    PsExec, KillExec, WhoamiExec, IdExec, HostnameExec, UnameExec,
    UptimeExec, FreeExec, LsofExec, NohupExec, JobsExec, ManExec,
    SudoExec, ChownExec, LnExec, FileExec,
)
from agentbox.box.shell.buildin_exec.seq_base64 import (
    SeqExec, Base64Exec, Md5sumExec, Sha256sumExec, NlExec, RevExec,
)
from agentbox.box.shell.buildin_exec.disk_cmds import DuExec, DfExec
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
    "date": DateExec.as_builtin(),
    "sort": SortExec.as_builtin(),
    "uniq": UniqExec.as_builtin(),
    "cut": CutExec.as_builtin(),
    "tr": TrExec.as_builtin(),
    "diff": DiffExec.as_builtin(),
    "basename": BasenameExec.as_builtin(),
    "dirname": DirnameExec.as_builtin(),
    "realpath": RealpathExec.as_builtin(),
    "xargs": XargsExec.as_builtin(),
    "chmod": ChmodExec.as_builtin(),
    "sleep": SleepExec.as_builtin(),
    "curl": CurlExec.as_builtin(),
    "wget": WgetExec.as_builtin(),
    "seq": SeqExec.as_builtin(),
    "base64": Base64Exec.as_builtin(),
    "md5sum": Md5sumExec.as_builtin(),
    "sha256sum": Sha256sumExec.as_builtin(),
    "nl": NlExec.as_builtin(),
    "rev": RevExec.as_builtin(),
    "du": DuExec.as_builtin(),
    "df": DfExec.as_builtin(),
    "uuidgen": UuidgenExec.as_builtin(),
    "mktemp": MktempExec.as_builtin(),
    "ps": PsExec.as_builtin(),
    "kill": KillExec.as_builtin(),
    "whoami": WhoamiExec.as_builtin(),
    "id": IdExec.as_builtin(),
    "hostname": HostnameExec.as_builtin(),
    "uname": UnameExec.as_builtin(),
    "uptime": UptimeExec.as_builtin(),
    "free": FreeExec.as_builtin(),
    "lsof": LsofExec.as_builtin(),
    "nohup": NohupExec.as_builtin(),
    "jobs": JobsExec.as_builtin(),
    "bg": JobsExec.as_builtin(),
    "fg": JobsExec.as_builtin(),
    "man": ManExec.as_builtin(),
    "sudo": SudoExec.as_builtin(),
    "su": SudoExec.as_builtin(),
    "chown": ChownExec.as_builtin(),
    "chgrp": ChownExec.as_builtin(),
    "ln": LnExec.as_builtin(),
    "file": FileExec.as_builtin(),
}
