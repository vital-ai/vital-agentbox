"""
agentbox.box.patch — MemFS-native file patching for LLM agents.

Core operations: str_replace, insert, view, create.
"""

from agentbox.box.patch.patcher import (
    PatchResult,
    str_replace,
    insert,
    view,
    info,
    create,
    diff_preview,
)
from agentbox.box.patch.filetype import detect_file_type

__all__ = [
    "PatchResult", "str_replace", "insert", "view",
    "info", "create", "diff_preview", "detect_file_type",
]
