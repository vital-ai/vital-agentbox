# Sandbox Tools Reference

You have access to a secure sandboxed environment for file editing, code execution, report generation, and version control. All commands run via `execute_code` with `language: shell` or `language: python`.

## File Editing

### `edit` — str_replace file editor

The primary tool for making precise, targeted edits to files. Uses exact string matching.

**Replace text in a file:**
```bash
edit /workspace/app.py --old "def hello():" --new "def hello(name):"
```

**View a file with line numbers:**
```bash
edit /workspace/app.py --view
edit /workspace/app.py --view --range 10:25
```

**Insert text after a specific line:**
```bash
edit /workspace/app.py --insert 5 --text "import os"
```

**Create a new file:**
```bash
edit /workspace/app.py --create --content "def main():\n    print('hello')"
```

**Preview a change without applying (dry-run diff):**
```bash
edit /workspace/app.py --diff --old "old code" --new "new code"
```

**Get file info (line count, size):**
```bash
edit /workspace/app.py --info
```

### `apply_patch` — multi-file patch

For larger multi-file changes, use V4A patch format via heredoc:

```bash
apply_patch << 'EOF'
*** Update File: /workspace/app.py
@@ def hello
 def hello():
-    return "hi"
+    return "hello world"

*** Add File: /workspace/utils.py
+def helper():
+    return 42

*** Delete File: /workspace/old_module.py

*** End Patch
EOF
```

### Writing files with heredoc

For creating files with substantial content, use `cat` with heredoc:
```bash
cat > /workspace/report.md << 'EOF'
# My Report
Content goes here...
EOF
```

## Python Execution

Run Python code directly. numpy, matplotlib, and other packages can be installed at runtime.

```bash
python3 -c "print('hello world')"
```

```bash
python3 << 'EOF'
import json
data = {"key": "value", "count": 42}
with open("/workspace/data.json", "w") as f:
    json.dump(data, f, indent=2)
print("Written data.json")
EOF
```

**Installing packages** (via micropip/Pyodide):
```bash
pip install numpy matplotlib
```

Then use them:
```bash
python3 << 'EOF'
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

x = np.linspace(0, 10, 100)
plt.plot(x, np.sin(x))
plt.savefig('/workspace/output/chart.png', dpi=150)
print("Chart saved")
EOF
```

## Report Generation

### `reportgen` — Markdown to PDF

Converts Markdown files to polished PDF reports using pandoc + LaTeX.

```bash
reportgen /workspace/report.md -o /workspace/report.pdf
```

**With metadata and table of contents:**
```bash
reportgen /workspace/report.md -o /workspace/report.pdf \
  --title "Quarterly Report" \
  --author "Analysis Team" \
  --date "2025-03-01" \
  --toc
```

**Multiple input files:**
```bash
reportgen /workspace/chapters/*.md -o /workspace/book.pdf --toc --toc-depth 2
```

**Full option list:** `reportgen --help`

**Typical workflow:**
1. Write Markdown to a file (with tables, headers, code blocks)
2. Generate any charts/images with Python and reference them in the Markdown
3. Run `reportgen` to produce the PDF

## Git Version Control

Git is pre-configured with author defaults. The repository is initialized at `/workspace`.

**Basic workflow:**
```bash
git add -A
git commit -m "Add analysis results"
git push
```

**Common commands:**
```bash
git status                    # Show changed files
git log --oneline             # Show commit history
git diff                      # Show unstaged changes
git branch feature-x          # Create a branch
git checkout feature-x        # Switch branches
git merge feature-x           # Merge a branch
```

**Configuration is pre-set** — no need to run `git config` unless you want to override:
```bash
git config user.name          # Shows "Agent" (default)
git config user.name "Custom Name"  # Override if needed
```

## Shell Builtins

Standard Linux commands are available. The working directory starts at `/workspace`.

**File operations:**
```bash
mkdir -p /workspace/output    # Create directories
cp source.txt dest.txt        # Copy files
mv old.txt new.txt            # Move/rename
rm file.txt                   # Remove files
touch file.txt                # Create empty file
ls -la /workspace/            # List with details
find /workspace -name "*.py"  # Find files
```

**Text processing:**
```bash
cat file.txt                  # Display file
head -n 20 file.txt           # First N lines
tail -n 10 file.txt           # Last N lines
grep "pattern" file.txt       # Search in files
sed 's/old/new/g' file.txt    # Stream editing
sort data.txt                 # Sort lines
uniq                          # Remove duplicates
wc -l file.txt                # Count lines
cut -d',' -f1,3 data.csv      # Extract CSV columns
awk -F',' '{print $1}' f.csv  # Field processing
diff file1.txt file2.txt      # Compare files
```

**Data utilities:**
```bash
base64 file.bin               # Encode to base64
md5sum file.txt               # MD5 checksum
sha256sum file.txt            # SHA-256 checksum
seq 1 10                      # Number sequences
date                          # Current date/time
uuidgen                       # Generate UUID
```

**Archive operations (host-delegated):**
```bash
tar czf archive.tar.gz /workspace/output/
tar xzf archive.tar.gz
zip -r output.zip /workspace/output/
unzip archive.zip
```

## Environment

- **Working directory:** `/workspace` (default)
- **Standard directories:** `/workspace`, `/data`, `/var`, `/etc`, `/tmp`
- **No network access:** `curl` and `wget` are blocked for security
- **No process management:** `ps`, `kill` are stubs (single-process sandbox)
- **File inspection:** `file /path` reports file type, `which cmd` locates commands
