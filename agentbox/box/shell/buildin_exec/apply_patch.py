"""apply_patch — V4A patch application builtin.

Reads a V4A patch from stdin (typically via heredoc) and applies
file operations (add, update, delete) against MemFS.

Usage:
    apply_patch << 'EOF'
    *** Add File: /path/to/new.py
    +line1
    +line2
    *** Update File: /path/to/existing.py
    @@ anchor_line
     context
    -old_line
    +new_line
    *** Delete File: /path/to/remove.py
    *** End Patch
    EOF
"""

from __future__ import annotations

from agentbox.box.patch.v4a import apply_v4a_diff, parse_v4a_patch
from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class ApplyPatchExec(BuiltinExec):
    name = "apply_patch"

    async def run(self) -> ShellResult:
        # Read patch from stdin (heredoc) or from a file argument
        patch_text = None

        if self.stdin:
            patch_text = self.stdin
        elif self.args:
            # apply_patch <file> — read patch from a file
            path = self.resolve(self.args[0])
            patch_text = await self.memfs.read_file(path)
            if patch_text is None:
                return self.fail(f"apply_patch: {path}: No such file\n")

        if not patch_text or not patch_text.strip():
            return self.fail(
                "apply_patch: no patch input.\n"
                "Usage: apply_patch << 'EOF'\n"
                "*** Update File: /path\n"
                "@@ anchor\n"
                " context\n"
                "-old\n"
                "+new\n"
                "*** End Patch\n"
                "EOF\n"
            )

        # Parse the V4A patch into operations
        try:
            ops = parse_v4a_patch(patch_text)
        except Exception as e:
            return self.fail(f"apply_patch: parse error: {e}\n")

        if not ops:
            return self.fail("apply_patch: no operations found in patch\n")

        # Apply each operation
        results: list[str] = []
        errors: list[str] = []

        for op in ops:
            path = self.resolve(op.path)

            if op.type == "add":
                # Check if file already exists
                existing = await self.memfs.read_file(path)
                if existing is not None:
                    errors.append(f"  FAIL: {op.path} already exists")
                    continue
                try:
                    content = apply_v4a_diff("", op.diff, mode="create")
                    # Ensure parent directory exists
                    parent = "/".join(path.split("/")[:-1])
                    if parent:
                        await self.memfs.mkdir_p(parent)
                    await self.memfs.write_file(path, content)
                    results.append(f"  ADD: {op.path}")
                except Exception as e:
                    errors.append(f"  FAIL: {op.path}: {e}")

            elif op.type == "update":
                current = await self.memfs.read_file(path)
                if current is None:
                    errors.append(f"  FAIL: {op.path}: file not found")
                    continue
                try:
                    new_content = apply_v4a_diff(current, op.diff)
                    await self.memfs.write_file(path, new_content)
                    results.append(f"  UPDATE: {op.path}")
                except Exception as e:
                    errors.append(f"  FAIL: {op.path}: {e}")

            elif op.type == "delete":
                existing = await self.memfs.read_file(path)
                if existing is None:
                    errors.append(f"  FAIL: {op.path}: file not found")
                    continue
                try:
                    await self.memfs.remove_file(path)
                    results.append(f"  DELETE: {op.path}")
                except Exception as e:
                    errors.append(f"  FAIL: {op.path}: {e}")

        # Build output
        stdout_parts = []
        if results:
            stdout_parts.extend(results)
        if errors:
            stdout_parts.extend(errors)

        total = len(results) + len(errors)
        ok = len(results)
        stdout_parts.append(f"apply_patch: {ok}/{total} operations succeeded")

        stdout = "\n".join(stdout_parts) + "\n"

        if errors:
            return ShellResult(exit_code=1, stdout=stdout)
        return ShellResult(exit_code=0, stdout=stdout)
