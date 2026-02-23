# Shell Builtins Reference

AgentBox provides 30+ virtual shell builtins implemented in Python. These
operate directly on MemFS — no real filesystem or bash process involved.

## File operations

### `cat` — concatenate and display files

```bash
cat /file.txt                    # display file
cat /a.txt /b.txt                # concatenate multiple files
cat -n /file.txt                 # show line numbers
cat << 'EOF' > /file.txt         # write via heredoc
content here
EOF
```

### `cp` — copy files

```bash
cp /src.txt /dst.txt             # copy file
cp -r /srcdir /dstdir            # copy directory recursively
```

### `mv` — move/rename files

```bash
mv /old.txt /new.txt             # rename file
mv /file.txt /dir/               # move into directory
```

### `rm` — remove files

```bash
rm /file.txt                     # remove file
rm -r /dir                       # remove directory recursively
rm -f /maybe.txt                 # force (no error if missing)
```

### `touch` — create empty file or update timestamp

```bash
touch /newfile.txt
```

### `mkdir` — create directories

```bash
mkdir /newdir                    # create directory
mkdir -p /a/b/c                  # create parent dirs
```

### `rmdir` — remove empty directories

```bash
rmdir /emptydir
```

## File viewing

### `head` — display first lines

```bash
head /file.txt                   # first 10 lines
head -n 5 /file.txt              # first 5 lines
```

### `tail` — display last lines

```bash
tail /file.txt                   # last 10 lines
tail -n 5 /file.txt              # last 5 lines
```

### `wc` — word/line/character count

```bash
wc /file.txt                     # lines, words, chars
wc -l /file.txt                  # line count only
wc -w /file.txt                  # word count only
```

## Search

### `grep` — search file contents

```bash
grep "pattern" /file.txt         # search in file
grep -r "TODO" /src              # recursive search
grep -i "error" /log.txt         # case-insensitive
grep -n "def " /app.py           # show line numbers
grep -l "import" /src/*.py       # list matching files
grep -c "test" /file.txt         # count matches
grep -v "comment" /file.txt      # invert match
```

### `find` — search for files

```bash
find /src -name "*.py"           # find by name
find / -name "*.txt"             # search everywhere
find /src -type f                # files only
find /src -type d                # directories only
find /src -maxdepth 2            # limit depth
```

## Text processing

### `echo` — print text

```bash
echo "hello world"
echo -n "no newline"             # suppress trailing newline
echo -e "tab\there"              # interpret escapes
echo $HOME                       # expand variables
```

### `printf` — formatted output

```bash
printf "Name: %s, Age: %d\n" "Alice" 30
```

### `sed` — stream editor

```bash
sed 's/old/new/' /file.txt       # replace first occurrence per line
sed 's/old/new/g' /file.txt      # replace all occurrences
sed -i 's/old/new/g' /file.txt   # in-place edit
```

### `tee` — write to file and stdout

```bash
echo "hello" | tee /file.txt     # write to file AND stdout
echo "more" | tee -a /file.txt   # append mode
```

## Environment

### `cd` — change directory

```bash
cd /workspace/src
cd ..                            # parent directory
cd                               # go to /
```

### `pwd` — print working directory

```bash
pwd                              # /workspace/src
```

### `export` — set environment variable

```bash
export PATH="/usr/bin:$PATH"
export DEBUG=1
```

### `env` — display environment

```bash
env                              # show all variables
```

## Info commands

### `which` — locate a command

```bash
which python                     # /usr/bin/python (virtual)
which nonexistent                # exit code 1
```

### `command` — check command existence

```bash
command -v git                   # prints path if found
```

### `type` — describe a command

```bash
type ls                          # ls is a shell builtin
```

### `test` / `[` — evaluate conditions

```bash
test -f /file.txt && echo "exists"
test -d /dir && echo "is directory"
[ -f /file.txt ] && echo "exists"
[ "$VAR" = "value" ] && echo "match"
```

### `true` / `false` — exit code constants

```bash
true                             # exit code 0
false                            # exit code 1
```

## Python and packages

### `python` / `python3` — run Python code

```bash
python3 /script.py               # run a file
python3 -c "print(42)"           # inline code
python3 -c "import sys; print(sys.version)"
```

Runs through Pyodide (CPython compiled to WASM) inside the sandbox.

### `pip` / `pip3` — install packages

```bash
pip install numpy                # install from PyPI (via micropip)
pip install pandas matplotlib
pip list                         # list installed packages
```

Uses Pyodide's `micropip` to install pure-Python wheels at runtime.

## File editing

### `edit` — AI-agent-friendly file editor

The `edit` builtin is purpose-built for LLM agents. It provides multiple
editing modes with fuzzy matching and helpful error messages.

**str_replace** (default):
```bash
edit /app.py --old 'print("hello")' --new 'print("world")'
```

Matching tiers (tried in order):
1. Exact text match
2. Line-stripped match (whitespace normalized)
3. Indent-offset match (Aider-inspired)
4. Fuzzy matching (scored similarity)
5. AST-aware match (ast-grep structural matching)

**view** — display file with line numbers:
```bash
edit /app.py --view
edit /app.py --view --range 10:20    # lines 10-20 only
```

**insert** — insert text after a line:
```bash
edit /app.py --insert 5 --text 'new_line = True'
```

**create** — create a new file:
```bash
edit /app.py --create --content 'def main(): pass'
```

**info** — file summary (size, format, definitions):
```bash
edit /app.py --info
```

**diff** — dry-run preview of str_replace:
```bash
edit /app.py --diff --old 'old code' --new 'new code'
```

### `apply_patch` — apply V4A patches

Reads OpenAI V4A format patches from stdin and applies them:

```bash
apply_patch << 'EOF'
*** Add File: /new.py
+def hello():
+    print("hello")
*** Update File: /existing.py
@@ def old_func():
 def old_func():
-    return 1
+    return 2
*** Delete File: /remove.py
*** End Patch
EOF
```

Supports `Add File`, `Update File`, and `Delete File` operations.

## Version control

### `git` — git operations

See [Git operations](git.md) for full documentation.

```bash
git init
git add .
git commit -m "message"
git log --oneline
git branch feature
git checkout feature
git merge main
git diff
git push                         # sync to S3 storage
```

## See also

- [Shell execution](shell.md) — how the shell works
- [Git operations](git.md) — git command details
