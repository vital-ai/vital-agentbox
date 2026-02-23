"""pip / pip3 — install and manage Python packages via Pyodide micropip."""

from __future__ import annotations

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class PipExec(BuiltinExec):
    """Handle pip install, pip list, pip show, pip freeze.

    Delegates to micropip (Pyodide's package installer) for installs
    and importlib.metadata for introspection.
    """

    name = "pip"

    async def run(self) -> ShellResult:
        if not self.args:
            return self.fail("Usage: pip <command> [options]\n")

        subcmd = self.args[0]

        if subcmd == "install":
            return await self._install()
        elif subcmd == "list":
            return await self._list()
        elif subcmd == "show":
            return await self._show()
        elif subcmd == "freeze":
            return await self._freeze()
        elif subcmd == "uninstall":
            return self.fail("pip uninstall is not supported in this environment\n")
        elif subcmd in ("--version", "-V"):
            return await self._version()
        else:
            return self.fail(f"pip: unknown command '{subcmd}'\n")

    async def _install(self) -> ShellResult:
        packages = []
        quiet = False
        i = 1
        while i < len(self.args):
            arg = self.args[i]
            if arg in ("-q", "--quiet"):
                quiet = True
            elif arg in ("-r", "--requirement"):
                if i + 1 < len(self.args):
                    i += 1
                    req_path = self.resolve(self.args[i])
                    content = await self.read_file(req_path)
                    if content is None:
                        return self.fail(f"pip: No such file: {self.args[i]}\n")
                    for line in content.strip().split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # Strip version specifiers for micropip
                            pkg = line.split(">=")[0].split("<=")[0].split("==")[0].split("!=")[0].split("<")[0].split(">")[0].strip()
                            if pkg:
                                packages.append(pkg)
            elif arg.startswith("-"):
                pass  # ignore other flags
            else:
                packages.append(arg)
            i += 1

        if not packages:
            return self.fail("pip install: no packages specified\n")

        result = await self.memfs.page.evaluate(
            _PIP_INSTALL_JS,
            [packages, quiet],
        )
        return ShellResult(
            exit_code=result.get("exit_code", 1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    async def _list(self) -> ShellResult:
        result = await self.memfs.page.evaluate(_PIP_LIST_JS, [])
        return ShellResult(
            exit_code=result.get("exit_code", 1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    async def _show(self) -> ShellResult:
        packages = [a for a in self.args[1:] if not a.startswith("-")]
        if not packages:
            return self.fail("pip show: no packages specified\n")
        result = await self.memfs.page.evaluate(_PIP_SHOW_JS, packages)
        return ShellResult(
            exit_code=result.get("exit_code", 1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    async def _freeze(self) -> ShellResult:
        result = await self.memfs.page.evaluate(_PIP_FREEZE_JS, [])
        return ShellResult(
            exit_code=result.get("exit_code", 1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    async def _version(self) -> ShellResult:
        result = await self.memfs.page.evaluate("""async () => {
            const pyodide = window.pyodide;
            try {
                const ver = pyodide.runPython("import micropip; micropip.__version__");
                return { exit_code: 0, stdout: "pip (micropip " + ver + ", pyodide)\\n", stderr: "" };
            } catch(e) {
                return { exit_code: 0, stdout: "pip (micropip, pyodide)\\n", stderr: "" };
            }
        }""", [])
        return ShellResult(
            exit_code=result.get("exit_code", 0),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )


_PIP_INSTALL_JS = """async ([packages, quiet]) => {
    const pyodide = window.pyodide;
    try {
        let out = "";
        for (const pkg of packages) {
            if (!quiet) out += "Collecting " + pkg + "\\n";
            try {
                await pyodide.runPythonAsync("import micropip; await micropip.install('" + pkg + "')");
                if (!quiet) out += "Successfully installed " + pkg + "\\n";
            } catch (e) {
                const msg = String(e.message || e);
                return {
                    exit_code: 1,
                    stdout: out,
                    stderr: "ERROR: Could not install " + pkg + ": " + msg + "\\n"
                };
            }
        }
        return { exit_code: 0, stdout: out, stderr: "" };
    } catch(e) {
        return { exit_code: 1, stdout: "", stderr: String(e) + "\\n" };
    }
}"""


_PIP_LIST_JS = """async () => {
    const pyodide = window.pyodide;
    try {
        const result = pyodide.runPython(`
import importlib.metadata
pkgs = sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower())
lines = []
for d in pkgs:
    name = d.metadata['Name']
    ver = d.metadata['Version']
    lines.append(f"{name:30s} {ver}")
header = f"{'Package':30s} {'Version'}"
sep = '-' * 30 + ' ' + '-' * 15
'\\n'.join([header, sep] + lines) + '\\n'
`);
        return { exit_code: 0, stdout: result, stderr: "" };
    } catch(e) {
        return { exit_code: 1, stdout: "", stderr: String(e) + "\\n" };
    }
}"""


_PIP_SHOW_JS = """async (packages) => {
    const pyodide = window.pyodide;
    try {
        let out = "";
        for (const pkg of packages) {
            try {
                const info = pyodide.runPython(`
import importlib.metadata
try:
    d = importlib.metadata.distribution('${pkg}')
    m = d.metadata
    lines = [
        'Name: ' + m['Name'],
        'Version: ' + m['Version'],
        'Summary: ' + (m.get('Summary') or ''),
        'Home-page: ' + (m.get('Home-page') or ''),
        'Author: ' + (m.get('Author') or ''),
        'License: ' + (m.get('License') or ''),
        'Location: /lib/python3.13/site-packages',
    ]
    '\\n'.join(lines) + '\\n'
except importlib.metadata.PackageNotFoundError:
    ''
`);
                if (info) {
                    out += info;
                } else {
                    return { exit_code: 1, stdout: out, stderr: "WARNING: Package(s) not found: " + pkg + "\\n" };
                }
            } catch(e) {
                return { exit_code: 1, stdout: out, stderr: "WARNING: Package(s) not found: " + pkg + "\\n" };
            }
        }
        return { exit_code: 0, stdout: out, stderr: "" };
    } catch(e) {
        return { exit_code: 1, stdout: "", stderr: String(e) + "\\n" };
    }
}"""


_PIP_FREEZE_JS = """async () => {
    const pyodide = window.pyodide;
    try {
        const result = pyodide.runPython(`
import importlib.metadata
pkgs = sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower())
'\\n'.join(f"{d.metadata['Name']}=={d.metadata['Version']}" for d in pkgs) + '\\n'
`);
        return { exit_code: 0, stdout: result, stderr: "" };
    } catch(e) {
        return { exit_code: 1, stdout: "", stderr: String(e) + "\\n" };
    }
}"""
