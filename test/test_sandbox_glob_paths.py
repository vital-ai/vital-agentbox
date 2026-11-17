"""Unit tests for AgentBoxSandbox glob matching and AgentCore path normalization."""

from types import SimpleNamespace

import pytest

from agentbox.langchain.sandbox import AgentBoxSandbox, _glob_regex


@pytest.mark.parametrize("pattern,path,expected", [
    ("*.py", "a.py", True),
    ("*.py", "src/a.py", False),
    ("**/*.py", "a.py", True),
    ("**/*.py", "src/pkg/a.py", True),
    ("src/*.py", "src/a.py", True),
    ("src/*.py", "src/pkg/a.py", False),
    ("src/**", "src/pkg/a.py", True),
    ("report?.txt", "report1.txt", True),
    ("[!a]*.md", "b.md", True),
    ("[!a]*.md", "a.md", False),
    ("a.py", "a_py", False),
])
def test_glob_regex(pattern, path, expected):
    assert bool(_glob_regex(pattern).match(path)) is expected


def _sandbox(engine, find_output):
    sb = AgentBoxSandbox(engine=engine)
    calls = []

    def execute(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(exit_code=0, output=find_output)

    sb.execute = execute
    return sb, calls


def test_agentcore_root_path_maps_to_cwd():
    sb, calls = _sandbox("agentcore", "./a.py\n./src/b.py\n./src/c.txt\n")
    result = sb.glob("**/*.py", "/")
    assert calls == ["find . -type f 2>/dev/null"]
    assert [m["path"] for m in result.matches] == ["./a.py", "./src/b.py"]


def test_pyodide_keeps_absolute_paths():
    sb, calls = _sandbox(None, "/workspace/a.py\n/workspace/src/b.py\n")
    result = sb.glob("*.py", "/workspace")
    assert calls == ["find /workspace -type f 2>/dev/null"]
    assert [m["path"] for m in result.matches] == ["/workspace/a.py"]


def test_normalize_path():
    assert AgentBoxSandbox(engine="agentcore")._normalize_path("/") == "."
    assert AgentBoxSandbox(engine="agentcore")._normalize_path("/report.txt") == "report.txt"
    assert AgentBoxSandbox()._normalize_path("/workspace/report.txt") == "/workspace/report.txt"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
