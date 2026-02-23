"""
Top-level shell executor: parse bash commands with tree-sitter-bash,
walk the CST, dispatch to builtins against MemFS.
"""

import tree_sitter_bash as tsbash
from tree_sitter import Language, Parser

from agentbox.box.shell.environment import Environment, ShellResult
from agentbox.box.shell.cst_walker import CSTWalker


BASH_LANGUAGE = Language(tsbash.language())


class ShellExecutor:
    """
    Parse and execute shell commands against a MemFS instance.

    Usage:
        executor = ShellExecutor(memfs)
        result = await executor.run("ls -la / && cat /file.txt")
        print(result.stdout, result.stderr, result.exit_code)
    """

    def __init__(self, memfs):
        self.memfs = memfs
        self.env = Environment()
        self.parser = Parser(BASH_LANGUAGE)

    async def run(self, command_string):
        """Parse and execute a shell command string. Returns ShellResult."""
        if not command_string or not command_string.strip():
            return ShellResult()

        tree = self.parser.parse(command_string.encode("utf-8"))
        root = tree.root_node

        # Check for parse errors
        if root.has_error:
            # Still try to execute — tree-sitter recovers from errors
            pass

        walker = CSTWalker(self.env, self.memfs)
        result = await walker.walk(root)
        self.env.last_exit_code = result.exit_code
        return result
