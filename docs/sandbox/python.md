# Python Execution

AgentBox runs Python code inside [Pyodide](https://pyodide.org/) — a full
CPython 3.11 interpreter compiled to WebAssembly. This runs inside the
Chromium sandbox, providing complete isolation from the host system.

## How it works

```
Python code string
        │
        ▼
┌───────────────────────┐
│  Playwright            │  page.evaluate()
│  (host process)        │
└────────┬──────────────┘
         │
         ▼
┌───────────────────────┐
│  Chromium Page         │
│  ┌──────────────────┐ │
│  │  Pyodide (WASM)  │ │
│  │  runPythonAsync() │ │
│  └──────────────────┘ │
└───────────────────────┘
         │
         ▼
    { stdout, stderr, exit_code }
```

1. Python code is passed to `page.evaluate()` as a string
2. Pyodide's `runPythonAsync()` executes it inside WASM linear memory
3. stdout/stderr are captured via `StringIO` redirection
4. Results are returned as a dict

## Running Python

### Via the client SDK

```python
# Python (default language)
result = sandbox.execute_sync("print(2 + 2)")
print(result.stdout)  # "4\n"

# Explicit language parameter
result = sandbox.execute_sync("print('hello')", language="python")
```

### Via shell

```bash
# Run inline code
python3 -c "print(42)"

# Run a file
echo 'print("hello from file")' > /script.py
python3 /script.py
```

The `python` and `python3` shell builtins execute code through Pyodide.

## Package installation

Pyodide uses `micropip` to install pure-Python wheels at runtime:

```bash
pip install numpy
pip install pandas matplotlib
pip list
```

Or from Python:

```python
import micropip
await micropip.install("requests")
import requests
```

### What packages work

- **Pure Python packages**: Most work out of the box via micropip
- **Pyodide built-in packages**: numpy, pandas, matplotlib, scipy, scikit-learn,
  PIL/Pillow, and [many more](https://pyodide.org/en/stable/usage/packages-in-pyodide.html)
- **C extension packages**: Only if pre-compiled for Pyodide (Emscripten/WASM).
  Standard pip wheels with C code won't work.

### Pre-loaded packages

Pyodide comes with these packages available immediately (no install needed):

- `numpy`, `pandas`, `matplotlib`
- `scipy`, `scikit-learn`
- `PIL` (Pillow)
- `json`, `re`, `math`, `os`, `sys`, `io` (stdlib)
- Full Python 3.11 standard library

## State persistence

Variables, imports, and installed packages persist across executions within
the same sandbox session:

```python
# Call 1
sandbox.execute_sync("x = 42")

# Call 2 — x is still defined
result = sandbox.execute_sync("print(x)")
# stdout: "42\n"

# Call 3 — imported modules persist
sandbox.execute_sync("import math")
result = sandbox.execute_sync("print(math.pi)")
# stdout: "3.141592653589793\n"
```

## Timeout handling

Each execution has a timeout (default: 30 seconds):

```python
# Specify timeout per call
result = await sandbox.execute("long_computation()", timeout=120)
```

If execution exceeds the timeout, it returns:
- `exit_code`: 124
- `stderr`: `"TimeoutError: execution exceeded timeout\n"`

## stdout / stderr capture

stdout and stderr are captured separately:

```python
result = sandbox.execute_sync("""
import sys
print("to stdout")
print("to stderr", file=sys.stderr)
""")
print(result.stdout)   # "to stdout\n"
print(result.stderr)   # "to stderr\n"
```

Exceptions are captured in stderr:

```python
result = sandbox.execute_sync("1/0")
print(result.exit_code)  # 1
print(result.stderr)     # "ZeroDivisionError: division by zero\n"
```

## File system access

Python code can read/write files on MemFS:

```python
sandbox.execute_sync("""
# Write a file
with open('/data.txt', 'w') as f:
    f.write('hello from Python')

# Read it back
with open('/data.txt') as f:
    print(f.read())
""")
```

Files written by Python are visible to shell commands and vice versa —
they share the same MemFS.

## Limitations

- **No network access**: Pyodide runs inside the Chromium sandbox. No
  outbound HTTP requests, sockets, or DNS resolution from Python code.
- **No subprocess**: `os.system()`, `subprocess.run()`, etc. don't work.
  Use the shell executor for command execution.
- **No threading**: WASM is single-threaded. `threading` module has limited
  functionality. `asyncio` works.
- **C extensions**: Only pre-compiled Pyodide packages work. Regular pip
  wheels with C code will fail to install.
- **Memory**: Bounded by WASM linear memory (typically ~2GB). Large
  datasets may cause out-of-memory errors.

## Pyodide version

AgentBox uses Pyodide **0.29.3** (CPython 3.11). The version can be
configured via `AGENTBOX_PYODIDE_URL` environment variable.

## See also

- [Shell execution](shell.md) — shell builtins and commands
- [Shell builtins](builtins.md) — `python` and `pip` builtins
- [Files and MemFS](files.md) — filesystem details
