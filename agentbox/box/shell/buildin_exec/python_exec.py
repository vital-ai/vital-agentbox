"""python / python3 — execute Python code via Pyodide."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class PythonExec(BuiltinExec):
    """Execute Python code via Pyodide in the same browser page.

    Supports:
        python -c "code"        — inline code
        python -m module        — run module as script
        python script.py [args] — read script from MemFS
        echo "code" | python    — read code from stdin
    """

    name = "python"

    async def run(self) -> ShellResult:
        code = None
        script_args: list[str] = []

        i = 0
        while i < len(self.args):
            if self.args[i] == "-c" and i + 1 < len(self.args):
                code = self.args[i + 1]
                script_args = self.args[i + 2:]
                break
            elif self.args[i] == "-m" and i + 1 < len(self.args):
                module = self.args[i + 1]
                script_args = self.args[i + 2:]
                code = f"import runpy; runpy.run_module('{module}', run_name='__main__')"
                break
            elif self.args[i] == "-u":
                i += 1
            elif not self.args[i].startswith("-"):
                script_path = self.resolve(self.args[i])
                content = await self.memfs.read_file(script_path)
                if content is None:
                    return self.fail(
                        f"python: can't open file '{self.args[i]}': "
                        f"[Errno 2] No such file or directory\n",
                        code=2,
                    )
                code = content
                script_args = self.args[i + 1:]
                break
            else:
                i += 1

        if code is None:
            if self.stdin:
                code = self.stdin
            else:
                return self.ok()

        cwd = self.env.cwd

        result = await self.memfs.page.evaluate(
            _PYODIDE_EVAL_JS,
            [code, cwd, ["python"] + script_args, self.stdin or ""],
        )

        return ShellResult(
            exit_code=result.get("exit_code", 1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )


_PYODIDE_EVAL_JS = """async ([code, cwd, sysArgv, stdinText]) => {
    const pyodide = window.pyodide;
    try {
        // Set up stdout/stderr capture and sys.argv
        pyodide.runPython(`
import sys, os
from io import StringIO
sys.stdout = StringIO()
sys.stderr = StringIO()
`);
        pyodide.runPython(`sys.argv = ${JSON.stringify(sysArgv)}`);
        try {
            pyodide.runPython(`os.chdir(${JSON.stringify(cwd)})`);
        } catch(e) {}
        if (stdinText) {
            pyodide.runPython(`sys.stdin = StringIO(${JSON.stringify(stdinText)})`);
        }

        // Run user code directly — no wrapping
        await pyodide.runPythonAsync(code);

        // Success — capture output and restore
        let stdout = "";
        let stderr = "";
        try { stdout = pyodide.runPython("sys.stdout.getvalue()"); } catch(e) {}
        try { stderr = pyodide.runPython("sys.stderr.getvalue()"); } catch(e) {}
        try { pyodide.runPython("sys.stdout = sys.__stdout__; sys.stderr = sys.__stderr__"); } catch(e) {}
        return { exit_code: 0, stdout: stdout, stderr: stderr };

    } catch (error) {
        // Capture output produced before the error
        let stdout = "";
        let stderr = "";
        try { stdout = pyodide.runPython("sys.stdout.getvalue()"); } catch(e) {}
        try { stderr = pyodide.runPython("sys.stderr.getvalue()"); } catch(e) {}
        try { pyodide.runPython("sys.stdout = sys.__stdout__; sys.stderr = sys.__stderr__"); } catch(e) {}

        // Check if it was a SystemExit (e.g. unittest.main() calls sys.exit(0))
        let exitCode = 1;
        try {
            exitCode = pyodide.runPython(`
_ec = 1
if hasattr(sys, 'last_value') and isinstance(sys.last_value, SystemExit):
    _c = sys.last_value.code
    _ec = _c if isinstance(_c, int) else (0 if _c is None else 1)
_ec
`);
        } catch(e2) {}

        if (exitCode === 0) {
            // Clean exit — return stdout, discard traceback noise from stderr
            return { exit_code: 0, stdout: stdout, stderr: "" };
        }

        const errMsg = error.message || String(error);
        return {
            exit_code: exitCode,
            stdout: stdout,
            stderr: (stderr ? stderr : "") + errMsg + "\\n"
        };
    }
}"""
