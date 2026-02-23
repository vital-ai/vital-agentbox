from dataclasses import dataclass, field
import re


@dataclass
class ShellResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


class Environment:
    """Shell state: cwd, variables, last exit code."""

    def __init__(self):
        self.cwd = "/"
        self.variables = {}
        self.last_exit_code = 0

    def resolve_path(self, path):
        """Resolve a path relative to cwd. Returns absolute path."""
        if not path:
            return self.cwd
        if path.startswith("/"):
            return self._normalize(path)
        return self._normalize(self.cwd.rstrip("/") + "/" + path)

    def _normalize(self, path):
        """Normalize a path: resolve . and .., collapse slashes."""
        parts = path.split("/")
        result = []
        for part in parts:
            if part == "" or part == ".":
                continue
            elif part == "..":
                if result:
                    result.pop()
            else:
                result.append(part)
        return "/" + "/".join(result)

    def expand(self, text):
        """Expand shell variables in text: $VAR, ${VAR}, $?"""
        def replace_var(match):
            name = match.group(1) or match.group(2)
            if name == "?":
                return str(self.last_exit_code)
            return self.variables.get(name, "")

        # ${VAR} form
        text = re.sub(r'\$\{([^}]+)\}', replace_var, text)
        # $VAR form (word characters)
        text = re.sub(r'\$([A-Za-z_?][A-Za-z0-9_]*)', lambda m: replace_var(type('M', (), {'group': lambda self, n: (m.group(1), None)[n-1]})()), text)
        # Simpler approach for $VAR
        return text

    def expand_variable(self, name):
        """Get a single variable value."""
        if name == "?":
            return str(self.last_exit_code)
        return self.variables.get(name, "")

    def set_variable(self, name, value):
        """Set a shell variable."""
        self.variables[name] = value
