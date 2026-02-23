# Shell Execution

AgentBox provides a virtual shell that parses and executes bash commands
against an in-memory filesystem (MemFS). There is no real bash process —
commands are parsed with tree-sitter-bash and dispatched to Python-implemented
builtins.

## How it works

```
Shell command string
        │
        ▼
┌───────────────────┐
│ tree-sitter-bash   │  Parse to concrete syntax tree (CST)
│ Parser             │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ CSTWalker          │  Walk CST nodes, resolve variables,
│                    │  handle pipes, redirects, &&, ||, ;
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ Builtin dispatch   │  Map command name → Python handler
│ (BUILTINS dict)    │  Execute against MemFS
└────────┬──────────┘
         │
         ▼
    ShellResult(stdout, stderr, exit_code)
```

1. **Parse**: The command string is parsed by `tree-sitter-bash` into a CST.
   This gives us full bash syntax support — pipes, redirects, command
   substitution, variable expansion, quoting, `&&`/`||`, semicolons, etc.

2. **Walk**: `CSTWalker` traverses the CST, resolving variables (`$VAR`),
   handling control flow (`&&`, `||`, `;`), and dispatching each command
   to its builtin handler.

3. **Execute**: Each command name is looked up in the `BUILTINS` dictionary.
   The matching handler runs against MemFS and returns a `ShellResult`.

## Supported bash features

| Feature | Example | Supported |
|---------|---------|-----------|
| Pipes | `ls \| grep foo` | Yes |
| Redirects | `echo hi > file.txt` | Yes |
| Append | `echo more >> file.txt` | Yes |
| Heredoc | `cat << 'EOF'\n...\nEOF` | Yes |
| And/or | `cmd1 && cmd2 \|\| cmd3` | Yes |
| Semicolons | `cmd1; cmd2; cmd3` | Yes |
| Variables | `$HOME`, `${VAR:-default}` | Yes |
| Export | `export FOO=bar` | Yes |
| Command substitution | `echo $(pwd)` | Yes |
| Quoting | `'literal'`, `"expand $VAR"` | Yes |
| Escaped quotes | `'it'\''s'` (bash idiom) | Yes |
| Subshell | `(cd /tmp && ls)` | Yes |
| Glob expansion | `ls *.py` | Limited |
| Background (`&`) | `cmd &` | No |
| Job control | `fg`, `bg`, `jobs` | No |
| Process substitution | `<(cmd)` | No |

## Environment

The shell maintains a persistent environment across commands within a
sandbox session:

```bash
# Variables persist
export PROJECT=/workspace
echo $PROJECT    # /workspace

# Working directory persists
cd /workspace/src
pwd              # /workspace/src

# Exit code of last command
echo $?          # 0
```

Environment variables are stored in the `Environment` object and survive
across multiple `execute()` calls on the same sandbox.

## Pipes and redirects

Pipes connect stdout of one command to stdin of the next:

```bash
echo -e "banana\napple\ncherry" | grep a | wc -l
# 2
```

Redirects write stdout to files:

```bash
echo "hello" > /output.txt        # overwrite
echo "world" >> /output.txt       # append
cat /output.txt
# hello
# world
```

Heredocs pass multi-line input via stdin:

```bash
cat << 'EOF' > /config.json
{
  "key": "value",
  "count": 42
}
EOF
```

## Error handling

Commands return exit codes. `&&` chains stop on first failure, `||` runs
the alternative:

```bash
# Only runs python if file exists
test -f /app.py && python /app.py

# Fallback on error
cat /missing.txt 2>/dev/null || echo "file not found"
```

## Tier system

| Tier | Description | Examples |
|------|-------------|---------|
| **Tier 1** | Virtual builtins (Python, in-process) | ls, cat, grep, edit, git |
| **Tier 2** | Pyodide execution (WASM) | python3 -c "..." |
| **Tier 3** | Host-delegated commands | git push, git pull, outline |

- **Tier 1** builtins are fast (no WASM overhead) and operate directly on MemFS.
- **Tier 2** runs Python code through Pyodide inside the WASM sandbox.
- **Tier 3** commands send a message to the host Python process via the
  `sendMessage` bridge for operations that need network or host resources.

## ShellResult

Every command returns a `ShellResult`:

```python
@dataclass
class ShellResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
```

## See also

- [Shell builtins reference](builtins.md) — complete list of all builtins
- [Python execution](python.md) — how Pyodide runs Python code
- [Git operations](git.md) — isomorphic-git integration
