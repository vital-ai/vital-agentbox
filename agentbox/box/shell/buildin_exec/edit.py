"""edit — AI-agent-friendly file editing builtin.

Usage:
    edit <file> --old "..." --new "..."     # str_replace (default)
    edit <file> --view [--range N:M]        # view with line numbers
    edit <file> --insert N --text "..."     # insert after line N
    edit <file> --create --content "..."    # create new file
    edit <file> --info                      # file summary
    edit <file> --diff --old "..." --new "..." # dry-run diff preview
"""

from __future__ import annotations

from agentbox.box.patch.patcher import str_replace, insert, view, info, create, diff_preview
from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class EditExec(BuiltinExec):
    name = "edit"

    async def run(self) -> ShellResult:
        # --- Parse arguments ---
        args = list(self.args)
        if not args:
            return self.fail(
                "edit: usage: edit <file> --old '...' --new '...'\n"
                "       edit <file> --view [--range N:M]\n"
                "       edit <file> --insert N --text '...'\n"
                "       edit <file> --create --content '...'\n"
            )

        filepath = None
        old_str = None
        new_str = None
        is_view = False
        view_range = None
        insert_line = None
        insert_text = None
        is_create = False
        create_content = None
        is_info = False
        is_diff = False

        i = 0
        while i < len(args):
            a = args[i]
            if a == "--old" and i + 1 < len(args):
                i += 1
                old_str = args[i]
            elif a == "--new" and i + 1 < len(args):
                i += 1
                new_str = args[i]
            elif a == "--view":
                is_view = True
            elif a == "--range" and i + 1 < len(args):
                i += 1
                view_range = args[i]
            elif a == "--insert" and i + 1 < len(args):
                i += 1
                try:
                    insert_line = int(args[i])
                except ValueError:
                    return self.fail(f"edit: --insert requires a line number, got: {args[i]}\n")
            elif a == "--text" and i + 1 < len(args):
                i += 1
                insert_text = args[i]
            elif a == "--create":
                is_create = True
            elif a == "--info":
                is_info = True
            elif a == "--diff":
                is_diff = True
            elif a == "--content" and i + 1 < len(args):
                i += 1
                create_content = args[i]
            elif not a.startswith("-") and filepath is None:
                filepath = a
            i += 1

        if filepath is None:
            return self.fail("edit: missing file path\n")

        resolved = self.resolve(filepath)

        # --- Dispatch to mode ---

        if is_create:
            return await self._do_create(resolved, filepath, create_content or "")

        if is_info:
            return await self._do_info(resolved, filepath)

        if is_view:
            return await self._do_view(resolved, filepath, view_range)

        if insert_line is not None:
            if insert_text is None:
                return self.fail("edit: --insert requires --text\n")
            return await self._do_insert(resolved, filepath, insert_line, insert_text)

        if old_str is not None:
            if new_str is None:
                return self.fail("edit: --old requires --new\n")
            if is_diff:
                return await self._do_diff(resolved, filepath, old_str, new_str)
            return await self._do_str_replace(resolved, filepath, old_str, new_str)

        return self.fail(
            "edit: no operation specified. Use --old/--new, --view, --insert, --create, --info, or --diff.\n"
        )

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    async def _do_str_replace(
        self, resolved: str, filepath: str, old_str: str, new_str: str
    ) -> ShellResult:
        content = await self.read_file(resolved)
        if content is None:
            return self.fail(f"edit: {filepath}: No such file\n")

        result = str_replace(content, old_str, new_str, path=filepath)
        if not result.success:
            return self.fail(result.message + "\n")

        await self.memfs.write_file(resolved, result.new_content)
        output = result.message
        if result.snippet:
            output += "\n" + result.snippet
        return self.ok(output + "\n")

    async def _do_view(
        self, resolved: str, filepath: str, view_range: str | None
    ) -> ShellResult:
        content = await self.read_file(resolved)
        if content is None:
            return self.fail(f"edit: {filepath}: No such file\n")

        start = 1
        end = None
        if view_range:
            parts = view_range.split(":")
            try:
                start = int(parts[0]) if parts[0] else 1
                end = int(parts[1]) if len(parts) > 1 and parts[1] else None
            except ValueError:
                return self.fail(f"edit: invalid range: {view_range}\n")

        result = view(content, start=start, end=end, path=filepath)
        output = result.message
        if result.snippet:
            output += "\n" + result.snippet
        return self.ok(output + "\n")

    async def _do_insert(
        self, resolved: str, filepath: str, line_number: int, text: str
    ) -> ShellResult:
        content = await self.read_file(resolved)
        if content is None:
            return self.fail(f"edit: {filepath}: No such file\n")

        result = insert(content, line_number, text, path=filepath)
        if not result.success:
            return self.fail(result.message + "\n")

        await self.memfs.write_file(resolved, result.new_content)
        output = result.message
        if result.snippet:
            output += "\n" + result.snippet
        return self.ok(output + "\n")

    async def _do_diff(
        self, resolved: str, filepath: str, old_str: str, new_str: str
    ) -> ShellResult:
        content = await self.read_file(resolved)
        if content is None:
            return self.fail(f"edit: {filepath}: No such file\n")

        result = diff_preview(content, old_str, new_str, path=filepath)
        if not result.success:
            return self.fail(result.message + "\n")

        output = result.message
        if result.snippet:
            output += "\n" + result.snippet
        return self.ok(output + "\n")

    async def _do_info(
        self, resolved: str, filepath: str
    ) -> ShellResult:
        content = await self.read_file(resolved)
        if content is None:
            return self.fail(f"edit: {filepath}: No such file\n")

        result = info(content, path=filepath)
        return self.ok(result.message + "\n")

    async def _do_create(
        self, resolved: str, filepath: str, content: str
    ) -> ShellResult:
        existing = await self.read_file(resolved)
        if existing is not None:
            return self.fail(f"edit: {filepath} already exists. Use --old/--new to edit.\n")

        # Ensure parent directories exist
        parent = resolved.rsplit("/", 1)[0] if "/" in resolved else "/"
        if parent and parent != "/":
            await self.memfs.mkdir_p(parent)

        result = create(content, path=filepath)
        await self.memfs.write_file(resolved, result.new_content)
        return self.ok(result.message + "\n")
