"""
Walk a tree-sitter-bash CST and dispatch to builtins.

Handles: commands, pipelines, lists (&&, ||, ;), redirects,
variable assignment, variable expansion, command substitution,
quoting (single, double, ANSI-C).
"""

import fnmatch as _fnmatch

from agentbox.box.shell.environment import ShellResult
from agentbox.box.shell.builtins import BUILTINS
from agentbox.box.shell.host_commands import HOST_COMMANDS


class CSTWalker:
    """Walk a tree-sitter-bash CST against a MemFS instance."""

    def __init__(self, env, memfs):
        self.env = env
        self.memfs = memfs

    async def walk(self, node, stdin=None):
        """Walk a CST node and return a ShellResult."""
        handler = getattr(self, f"_visit_{node.type}", None)
        if handler:
            return await handler(node, stdin)
        # For unknown node types, try visiting children sequentially
        return await self._visit_children(node, stdin)

    async def _visit_children(self, node, stdin):
        """Visit children sequentially, return last result."""
        result = ShellResult()
        for child in node.children:
            if child.is_named:
                result = await self.walk(child, stdin)
                self.env.last_exit_code = result.exit_code
        return result

    # --- Top-level ---

    async def _visit_program(self, node, stdin):
        """Root node — execute statements sequentially, accumulating output."""
        all_stdout = []
        all_stderr = []
        exit_code = 0
        for child in node.children:
            if child.is_named:
                result = await self.walk(child, stdin)
                self.env.last_exit_code = result.exit_code
                exit_code = result.exit_code
                if result.stdout:
                    all_stdout.append(result.stdout)
                if result.stderr:
                    all_stderr.append(result.stderr)
        return ShellResult(
            exit_code=exit_code,
            stdout="".join(all_stdout),
            stderr="".join(all_stderr),
        )

    # --- Commands ---

    async def _visit_command(self, node, stdin):
        """Simple command: name + arguments."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            # Could be a variable assignment as a command prefix
            return await self._visit_children(node, stdin)

        cmd_name = self._get_text(name_node)

        # Collect arguments (with glob expansion for unquoted words)
        args = []
        for child in node.children:
            if child == name_node:
                continue
            if child.type in ("word", "string", "raw_string",
                              "simple_expansion", "expansion",
                              "concatenation", "string_content",
                              "command_substitution", "number"):
                arg = await self._resolve_value(child)
                # Glob expansion: only for unquoted words (not string/raw_string)
                if child.type in ("word", "concatenation") and \
                        any(c in arg for c in ("*", "?", "[")):
                    expanded = await self._expand_glob(arg)
                    args.extend(expanded)
                else:
                    args.append(arg)

        # Check for variable assignment prefix (e.g., FOO=bar cmd)
        # Handle it as part of the environment
        if "=" in cmd_name and not cmd_name.startswith("="):
            return await self._handle_assignment(cmd_name)

        # Tier 1: Look up builtin
        builtin_fn = BUILTINS.get(cmd_name)
        if builtin_fn:
            result = await builtin_fn(args, stdin, self.env, self.memfs)
            self.env.last_exit_code = result.exit_code
            return result

        # Tier 3: Look up host-delegated command
        host_fn = HOST_COMMANDS.get(cmd_name)
        if host_fn:
            result = await host_fn(args, stdin, self.env, self.memfs)
            self.env.last_exit_code = result.exit_code
            return result

        # Command not found
        self.env.last_exit_code = 127
        return ShellResult(
            exit_code=127,
            stderr=f"bash: {cmd_name}: command not found\n"
        )

    async def _visit_declaration_command(self, node, stdin):
        """Handle export, local, declare."""
        parts = []
        for child in node.children:
            text = self._get_text(child)
            parts.append(text)

        if not parts:
            return ShellResult()

        keyword = parts[0]
        if keyword == "export":
            for part in parts[1:]:
                if "=" in part:
                    name, value = part.split("=", 1)
                    # Strip quotes from value
                    value = self._strip_quotes(value)
                    self.env.set_variable(name, value)
            return ShellResult()

        return ShellResult()

    # --- Variable Assignment ---

    async def _visit_variable_assignment(self, node, stdin):
        """FOO=bar"""
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")

        name = self._get_text(name_node) if name_node else ""
        value = ""
        if value_node:
            value = await self._resolve_value(value_node)

        self.env.set_variable(name, value)
        return ShellResult()

    async def _handle_assignment(self, text):
        """Handle NAME=VALUE as a standalone assignment."""
        name, value = text.split("=", 1)
        value = self._strip_quotes(value)
        self.env.set_variable(name, value)
        return ShellResult()

    # --- Pipeline ---

    async def _visit_pipeline(self, node, stdin):
        """cmd1 | cmd2 | cmd3 — chain stdout between commands."""
        commands = [c for c in node.children if c.is_named]

        # Check for negation (! cmd)
        negate = False
        if node.children and self._get_text(node.children[0]) == "!":
            negate = True

        current_stdin = stdin
        result = ShellResult()

        for cmd_node in commands:
            result = await self.walk(cmd_node, current_stdin)
            current_stdin = result.stdout

        if negate:
            result.exit_code = 0 if result.exit_code != 0 else 1

        self.env.last_exit_code = result.exit_code
        return result

    # --- List (&&, ||, ;) ---

    async def _visit_list(self, node, stdin):
        """cmd1 && cmd2, cmd1 || cmd2, cmd1 ; cmd2"""
        result = ShellResult()

        i = 0
        children = node.children
        while i < len(children):
            child = children[i]

            if not child.is_named:
                # Operator: &&, ||, ;, &
                op = self._get_text(child)
                i += 1

                if op == "&&":
                    if result.exit_code != 0:
                        # Skip next command
                        if i < len(children):
                            i += 1
                        continue
                elif op == "||":
                    if result.exit_code == 0:
                        # Skip next command
                        if i < len(children):
                            i += 1
                        continue
                # ; and & just continue
                continue

            result = await self.walk(child, stdin)
            self.env.last_exit_code = result.exit_code
            i += 1

        return result

    # --- Redirects ---

    async def _visit_redirected_statement(self, node, stdin):
        """Handle redirections: >, >>, <, 2>, 2>> and heredocs."""
        body = node.child_by_field_name("body")
        if body is None:
            # Find first named child that isn't a redirect
            for child in node.children:
                if child.is_named and child.type != "file_redirect" and child.type != "heredoc_redirect":
                    body = child
                    break

        # Collect file redirects and heredoc stdin.
        # Note: tree-sitter-bash may nest file_redirect inside
        # heredoc_redirect (e.g. `cat << 'EOF' > file`), so we
        # must look inside heredoc_redirect children too.
        redirects = []
        heredoc_stdin = stdin
        for child in node.children:
            if child.type == "file_redirect":
                redirects.append(child)
            elif child.type == "heredoc_redirect":
                for hchild in child.children:
                    if hchild.type == "heredoc_body":
                        heredoc_stdin = self._get_text(hchild)
                    elif hchild.type == "file_redirect":
                        redirects.append(hchild)

        # Execute the body command
        result = ShellResult()
        if body:
            result = await self.walk(body, heredoc_stdin)
            self.env.last_exit_code = result.exit_code

        # Apply redirects
        for redirect in redirects:
            fd = None
            operator = None
            dest = None

            for rchild in redirect.children:
                text = self._get_text(rchild)
                if rchild.type == "file_descriptor":
                    fd = text
                elif text in (">", ">>", "<", "2>", "2>>", ">&"):
                    operator = text
                elif rchild.is_named:
                    dest = await self._resolve_value(rchild)

            if operator is None:
                # Try to detect operator from non-named children
                for rchild in redirect.children:
                    if not rchild.is_named:
                        text = self._get_text(rchild)
                        if text in (">", ">>", "<", ">&"):
                            operator = text
                            break

            if dest is None:
                dest_node = redirect.child_by_field_name("destination")
                if dest_node:
                    dest = await self._resolve_value(dest_node)

            if operator and dest:
                # Handle 2>&1 — merge stderr into stdout
                # tree-sitter may parse as (fd=2, op=">&", dest="1") or (fd=2, op=">", dest="&1")
                if fd == "2" and (dest in ("&1", "1") and operator in (">", ">&")):
                    merged = result.stdout + result.stderr
                    result = ShellResult(exit_code=result.exit_code, stdout=merged)
                    continue
                resolved = self.env.resolve_path(dest)
                if fd == "2" or operator in ("2>", "2>>"):
                    append = ">>" in operator
                    if resolved != "/dev/null":
                        await self.memfs.write_file(resolved, result.stderr, append=append)
                    # Clear stderr from result — it's been redirected
                    result = ShellResult(exit_code=result.exit_code, stdout=result.stdout)
                elif operator == "<":
                    content = await self.memfs.read_file(resolved)
                    if content is not None:
                        # Re-execute with stdin from file
                        if body:
                            result = await self.walk(body, content)
                elif operator == ">":
                    await self.memfs.write_file(resolved, result.stdout, append=False)
                    result = ShellResult(exit_code=result.exit_code, stderr=result.stderr)
                elif operator == ">>":
                    await self.memfs.write_file(resolved, result.stdout, append=True)
                    result = ShellResult(exit_code=result.exit_code, stderr=result.stderr)

        return result

    # --- Subshell / Command Substitution ---

    async def _visit_command_substitution(self, node, stdin):
        """$(...) or `...` — execute and capture stdout."""
        # The children include the program inside the substitution
        for child in node.children:
            if child.is_named:
                result = await self.walk(child, stdin)
                # Return stdout with trailing newline stripped (bash behavior)
                return ShellResult(
                    exit_code=result.exit_code,
                    stdout=result.stdout.rstrip("\n"),
                    stderr=result.stderr
                )
        return ShellResult()

    async def _visit_subshell(self, node, stdin):
        """( cmd1; cmd2 ) — execute in current environment."""
        result = ShellResult()
        for child in node.children:
            if child.is_named:
                result = await self.walk(child, stdin)
                self.env.last_exit_code = result.exit_code
        return result

    # --- If / While / For ---

    async def _visit_if_statement(self, node, stdin):
        """if condition; then body; [elif ...; then ...;] [else ...;] fi"""
        i = 0
        children = node.children
        while i < len(children):
            text = self._get_text(children[i])
            if text in ("if", "elif"):
                i += 1
                # Condition
                if i < len(children) and children[i].is_named:
                    cond_result = await self.walk(children[i], stdin)
                    i += 1
                    # Skip 'then'
                    if i < len(children) and self._get_text(children[i]) == "then":
                        i += 1
                    if cond_result.exit_code == 0:
                        # Execute body until 'elif', 'else', or 'fi'
                        result = ShellResult()
                        while i < len(children):
                            t = self._get_text(children[i])
                            if t in ("elif", "else", "fi"):
                                break
                            if children[i].is_named:
                                result = await self.walk(children[i], stdin)
                                self.env.last_exit_code = result.exit_code
                            i += 1
                        return result
                    else:
                        # Skip body until 'elif', 'else', or 'fi'
                        while i < len(children):
                            t = self._get_text(children[i])
                            if t in ("elif", "else", "fi"):
                                break
                            i += 1
                        continue
            elif text == "else":
                i += 1
                result = ShellResult()
                while i < len(children):
                    t = self._get_text(children[i])
                    if t == "fi":
                        break
                    if children[i].is_named:
                        result = await self.walk(children[i], stdin)
                        self.env.last_exit_code = result.exit_code
                    i += 1
                return result
            else:
                i += 1
        return ShellResult()

    # --- Value Resolution ---

    async def _resolve_value(self, node):
        """Resolve a CST node to a string value, handling expansions and quoting."""
        ntype = node.type

        if ntype == "word":
            text = self._get_text(node)
            # Check for child expansions
            if node.named_child_count > 0:
                parts = []
                for child in node.children:
                    parts.append(await self._resolve_value(child))
                return "".join(parts)
            # Handle backslash escapes in unquoted words (e.g. \' → ')
            if "\\" in text:
                text = self._unescape_word(text)
            return self.env.expand(text) if "$" in text else text

        elif ntype == "string":
            # Double-quoted string — preserve newlines, expand variables
            raw = self._get_text(node)
            # Strip outer double quotes
            if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
                inner = raw[1:-1]
            else:
                inner = raw

            if node.named_child_count == 0:
                # No expansions — return raw content (preserves newlines)
                return inner

            # Has named children (expansions) — resolve by replacing raw text
            for child in node.children:
                if child.is_named:
                    child_raw = self._get_text(child)
                    resolved = await self._resolve_value(child)
                    inner = inner.replace(child_raw, resolved, 1)
            return inner

        elif ntype == "string_content":
            text = self._get_text(node)
            if node.named_child_count > 0:
                parts = []
                for child in node.children:
                    if child.is_named:
                        parts.append(await self._resolve_value(child))
                    else:
                        parts.append(self._get_text(child))
                return "".join(parts)
            return text

        elif ntype == "raw_string":
            # Single-quoted string — no expansion
            text = self._get_text(node)
            return text[1:-1] if text.startswith("'") and text.endswith("'") else text

        elif ntype == "simple_expansion":
            # $VAR
            text = self._get_text(node)
            var_name = text[1:] if text.startswith("$") else text
            return self.env.expand_variable(var_name)

        elif ntype == "expansion":
            # ${VAR}, ${VAR:-default}, etc.
            text = self._get_text(node)
            # Strip ${ and }
            inner = text[2:-1] if text.startswith("${") and text.endswith("}") else text
            if ":-" in inner:
                name, default = inner.split(":-", 1)
                val = self.env.expand_variable(name)
                return val if val else default
            return self.env.expand_variable(inner)

        elif ntype == "command_substitution":
            result = await self._visit_command_substitution(node, None)
            return result.stdout

        elif ntype == "concatenation":
            parts = []
            for child in node.children:
                parts.append(await self._resolve_value(child))
            return "".join(parts)

        elif ntype == "number":
            return self._get_text(node)

        else:
            return self._get_text(node)

    # --- Glob Expansion ---

    async def _expand_glob(self, pattern):
        """Expand a glob pattern against MemFS.

        Returns a sorted list of matching paths, or ``[pattern]`` if no
        matches (bash default behaviour with failglob off).
        """
        is_abs = pattern.startswith("/")
        if is_abs:
            abs_pattern = pattern
        else:
            cwd = self.env.cwd
            abs_pattern = (cwd + "/" + pattern) if cwd != "/" else ("/" + pattern)
        # Normalise double slashes
        while "//" in abs_pattern:
            abs_pattern = abs_pattern.replace("//", "/")

        segments = [s for s in abs_pattern.split("/") if s]
        matches = await self._glob_match("", segments)

        if not matches:
            return [pattern]

        matches.sort()

        if not is_abs:
            # Convert back to relative paths
            cwd = self.env.cwd
            prefix = cwd if cwd.endswith("/") else cwd + "/"
            matches = [m[len(prefix):] if m.startswith(prefix) else m
                       for m in matches]
        return matches

    async def _glob_match(self, base, segments):
        """Recursively walk *segments*, expanding globs at each level."""
        if not segments:
            return [base] if base else ["/"]

        seg = segments[0]
        rest = segments[1:]

        if any(c in seg for c in ("*", "?", "[")):
            parent = base or "/"
            entries = await self.memfs.list_dir(parent)
            if not entries or isinstance(entries, str):
                return []
            names = list(entries.keys()) if isinstance(entries, dict) else list(entries)
            results = []
            for name in names:
                if _fnmatch.fnmatch(name, seg):
                    full = f"{base}/{name}"
                    if rest:
                        results.extend(await self._glob_match(full, rest))
                    else:
                        results.append(full)
            return results
        else:
            full = f"{base}/{seg}"
            if rest:
                return await self._glob_match(full, rest)
            else:
                exists = await self.memfs.exists(full)
                return [full] if exists else []

    # --- Helpers ---

    def _get_text(self, node):
        """Get the text of a CST node."""
        if node is None:
            return ""
        return node.text.decode("utf-8") if isinstance(node.text, bytes) else str(node.text)

    def _unescape_word(self, text):
        """Process backslash escapes in unquoted words.

        In bash, outside of quotes, a backslash preserves the literal
        value of the next character: \\' → ', \\\\ → \\, \\n → n, etc.
        """
        result = []
        i = 0
        while i < len(text):
            if text[i] == "\\" and i + 1 < len(text):
                result.append(text[i + 1])
                i += 2
            else:
                result.append(text[i])
                i += 1
        return "".join(result)

    def _strip_quotes(self, text):
        """Strip surrounding quotes from a string."""
        if len(text) >= 2:
            if (text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'"):
                return text[1:-1]
        return text
