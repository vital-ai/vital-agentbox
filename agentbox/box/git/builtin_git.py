"""
Shell builtin: git

Dispatches git subcommands to isomorphic-git running in the browser page.
Tier 1 commands (init, add, commit, log, status, branch, checkout, diff, merge)
run entirely in-sandbox. Tier 3 commands (push, pull, clone) delegate to
host commands for network/storage operations.
"""

from agentbox.box.shell.environment import ShellResult


# JavaScript functions for each git subcommand.
# All assume window.git (isomorphic-git) and window.fsAdapter are available.

_GIT_INIT_JS = """async ([dir, branch]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    const FS = window.pyodide._module.FS;
    try {
        // Ensure dir exists
        try { FS.mkdir(dir); } catch(e) {}
        // Check if .git already exists (re-init is a no-op)
        let alreadyInit = false;
        try {
            FS.stat(dir + '/.git');
            alreadyInit = true;
        } catch(e) {}
        if (alreadyInit) {
            return { exit_code: 0, stdout: `Reinitialized existing Git repository in ${dir}/.git/\\n` };
        }
        await git.init({ fs, dir, defaultBranch: branch || 'main' });
        return { exit_code: 0, stdout: `Initialized empty Git repository in ${dir}/.git/\\n` };
    } catch(e) {
        return { exit_code: 1, stderr: `git init: ${e.message}\\n` };
    }
}"""

_GIT_ADD_JS = """async ([dir, filepaths]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        for (const fp of filepaths) {
            await git.add({ fs, dir, filepath: fp });
        }
        return { exit_code: 0, stdout: '' };
    } catch(e) {
        return { exit_code: 1, stderr: `git add: ${e.message}\\n` };
    }
}"""

_GIT_COMMIT_JS = """async ([dir, message, authorName, authorEmail]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const sha = await git.commit({
            fs, dir, message,
            author: { name: authorName, email: authorEmail },
        });
        const short = sha.substring(0, 7);
        return { exit_code: 0, stdout: `[${short}] ${message}\\n` };
    } catch(e) {
        return { exit_code: 1, stderr: `git commit: ${e.message}\\n` };
    }
}"""

_GIT_LOG_JS = """async ([dir, maxCount, oneline]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const depth = maxCount || 50;
        const log = await git.log({ fs, dir, depth });
        let output = '';
        for (const entry of log) {
            const sha = entry.oid.substring(0, 7);
            const msg = entry.commit.message.trim();
            if (oneline) {
                const firstLine = msg.split('\\n')[0];
                output += `${sha} ${firstLine}\\n`;
            } else {
                output += `commit ${entry.oid}\\n`;
                output += `Author: ${entry.commit.author.name} <${entry.commit.author.email}>\\n`;
                const d = new Date(entry.commit.author.timestamp * 1000);
                output += `Date:   ${d.toISOString()}\\n`;
                output += `\\n    ${msg}\\n\\n`;
            }
        }
        return { exit_code: 0, stdout: output };
    } catch(e) {
        return { exit_code: 1, stderr: `git log: ${e.message}\\n` };
    }
}"""

_GIT_STATUS_JS = """async ([dir]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const matrix = await git.statusMatrix({ fs, dir });
        let output = '';
        for (const [filepath, head, workdir, stage] of matrix) {
            // head: 0=absent, 1=present
            // workdir: 0=absent, 1=identical, 2=modified
            // stage: 0=absent, 1=identical, 2=added, 3=modified
            let status = '';
            if (head === 0 && workdir === 2 && stage === 0) status = '?? ';  // untracked
            else if (head === 0 && workdir === 2 && stage === 2) status = 'A  ';  // new staged
            else if (head === 1 && workdir === 2 && stage === 1) status = ' M ';  // modified unstaged
            else if (head === 1 && workdir === 2 && stage === 2) status = 'M  ';  // modified staged
            else if (head === 1 && workdir === 2 && stage === 3) status = 'MM ';  // modified both
            else if (head === 1 && workdir === 0 && stage === 0) status = 'D  ';  // deleted staged
            else if (head === 1 && workdir === 0 && stage === 1) status = ' D ';  // deleted unstaged
            else if (head === 1 && workdir === 1 && stage === 1) continue;  // unchanged
            else status = `${head}${workdir}${stage}`;

            output += `${status}${filepath}\\n`;
        }
        if (!output) output = 'nothing to commit, working tree clean\\n';
        return { exit_code: 0, stdout: output };
    } catch(e) {
        return { exit_code: 1, stderr: `git status: ${e.message}\\n` };
    }
}"""

_GIT_BRANCH_JS = """async ([dir, newBranch, deleteBranch]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        if (deleteBranch) {
            await git.deleteBranch({ fs, dir, ref: deleteBranch });
            return { exit_code: 0, stdout: `Deleted branch ${deleteBranch}\\n` };
        }
        if (newBranch) {
            await git.branch({ fs, dir, ref: newBranch });
            return { exit_code: 0, stdout: '' };
        }
        // List branches
        const branches = await git.listBranches({ fs, dir });
        const current = await git.currentBranch({ fs, dir });
        let output = '';
        for (const b of branches) {
            output += (b === current ? `* ${b}` : `  ${b}`) + '\\n';
        }
        return { exit_code: 0, stdout: output };
    } catch(e) {
        return { exit_code: 1, stderr: `git branch: ${e.message}\\n` };
    }
}"""

_GIT_CHECKOUT_JS = """async ([dir, ref]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        await git.checkout({ fs, dir, ref });
        return { exit_code: 0, stdout: `Switched to branch '${ref}'\\n` };
    } catch(e) {
        return { exit_code: 1, stderr: `git checkout: ${e.message}\\n` };
    }
}"""

_GIT_DIFF_JS = """async ([dir, cached, filterPaths]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    const FS = window.pyodide._module.FS;

    // Minimal unified diff between two texts
    function unifiedDiff(aLines, bLines, aName, bName) {
        let out = '--- a/' + aName + '\\n+++ b/' + bName + '\\n';
        // Simple: show all removed then all added for each contiguous change
        const max = Math.max(aLines.length, bLines.length);
        let i = 0;
        while (i < max) {
            // Find next difference
            if (i < aLines.length && i < bLines.length && aLines[i] === bLines[i]) { i++; continue; }
            // Start of a hunk
            const hunkStart = Math.max(0, i - 3);
            let ai = i, bi = i;
            // Scan forward to find end of differences
            let matchCount = 0;
            while (ai < aLines.length || bi < bLines.length) {
                if (ai < aLines.length && bi < bLines.length && aLines[ai] === bLines[bi]) {
                    matchCount++;
                    if (matchCount >= 3) break;
                    ai++; bi++;
                } else {
                    matchCount = 0;
                    if (ai < aLines.length) ai++;
                    if (bi < bLines.length) bi++;
                }
            }
            const hunkEndA = Math.min(ai + 1, aLines.length);
            const hunkEndB = Math.min(bi + 1, bLines.length);
            out += '@@ -' + (hunkStart+1) + ',' + (hunkEndA - hunkStart) +
                   ' +' + (hunkStart+1) + ',' + (hunkEndB - hunkStart) + ' @@\\n';
            // Context before
            for (let c = hunkStart; c < Math.min(i, hunkEndA); c++) {
                if (c < aLines.length) out += ' ' + aLines[c] + '\\n';
            }
            // Changed lines
            for (let c = i; c < hunkEndA; c++) {
                if (c < aLines.length) out += '-' + aLines[c] + '\\n';
            }
            for (let c = i; c < hunkEndB; c++) {
                if (c < bLines.length) out += '+' + bLines[c] + '\\n';
            }
            i = Math.max(hunkEndA, hunkEndB);
        }
        return out;
    }

    try {
        const matrix = await git.statusMatrix({ fs, dir });
        let output = '';
        for (const [filepath, head, workdir, stage] of matrix) {
            if (head === 1 && workdir === 1 && stage === 1) continue;
            if (filterPaths && filterPaths.length && !filterPaths.some(p => filepath === p || filepath.startsWith(p + '/'))) continue;

            let oldContent = '';
            let newContent = '';

            // Read HEAD version
            if (head === 1) {
                try {
                    oldContent = await window.gitHelpers.readFileAtRef(dir, 'HEAD', filepath) || '';
                } catch(e) {}
            }

            // Read working tree version
            if (workdir !== 0) {
                try {
                    newContent = FS.readFile(dir + '/' + filepath, { encoding: 'utf8' });
                } catch(e) {}
            }

            if (oldContent === newContent) continue;

            output += 'diff --git a/' + filepath + ' b/' + filepath + '\\n';
            if (head === 0) {
                output += 'new file\\n';
            } else if (workdir === 0) {
                output += 'deleted file\\n';
            }
            const aLines = oldContent.split('\\n');
            const bLines = newContent.split('\\n');
            output += unifiedDiff(aLines, bLines, filepath, filepath);
        }
        return { exit_code: 0, stdout: output };
    } catch(e) {
        return { exit_code: 1, stderr: 'git diff: ' + e.message + '\\n' };
    }
}"""

_GIT_RM_JS = """async ([dir, filepaths]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        for (const fp of filepaths) {
            await git.remove({ fs, dir, filepath: fp });
            // Also delete from working tree
            try {
                window.pyodide._module.FS.unlink(dir + '/' + fp);
            } catch(e) { /* file may not exist */ }
        }
        return { exit_code: 0, stdout: '' };
    } catch(e) {
        return { exit_code: 1, stderr: `git rm: ${e.message}\\n` };
    }
}"""


_GIT_MERGE_JS = """async ([dir, branch, authorName, authorEmail, noFF]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const ours = await git.currentBranch({ fs, dir });
        const result = await git.merge({
            fs, dir, ours, theirs: branch,
            author: { name: authorName, email: authorEmail },
            fastForward: !noFF,
            abortOnConflict: false,
        });
        if (result.alreadyMerged) {
            return { exit_code: 0, stdout: 'Already up to date.\\n' };
        }
        await git.checkout({ fs, dir, ref: ours, force: true });
        if (result.fastForward) {
            return { exit_code: 0, stdout: 'Fast-forward\\n' };
        }
        return { exit_code: 0, stdout: 'Merge made: ' + result.oid.slice(0,7) + '\\n' };
    } catch(e) {
        if (e.code === 'MergeConflictError') {
            const d = e.data || {};
            const files = d.filepaths || [];
            const list = files.map(f => '\\tCONFLICT: ' + f).join('\\n');
            return {
                exit_code: 1,
                stdout: 'Auto-merging...\\n'
                    + list + '\\n'
                    + 'Automatic merge failed; fix conflicts and then commit the result.\\n',
                stderr: '',
                conflicts: files,
                theirs: branch,
            };
        }
        return { exit_code: 1, stderr: 'git merge: ' + e.message + '\\n' };
    }
}"""

_GIT_MERGE_CONTINUE_JS = """async ([dir, theirsBranch, authorName, authorEmail]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const ours = await git.currentBranch({ fs, dir });
        // Resolve branch names to OIDs for the parent list
        const oursOid = await git.resolveRef({ fs, dir, ref: ours });
        const theirsOid = await git.resolveRef({ fs, dir, ref: theirsBranch });
        // Stage all files
        await git.add({ fs, dir, filepath: '.' });
        // Create merge commit with both parent OIDs
        const oid = await git.commit({
            fs, dir, ref: ours,
            message: "Merge branch '" + theirsBranch + "' into " + ours,
            author: { name: authorName, email: authorEmail },
            parent: [oursOid, theirsOid],
        });
        // Ensure branch ref points to the new merge commit
        await git.writeRef({ fs, dir, ref: 'refs/heads/' + ours, value: oid, force: true });
        return { exit_code: 0, stdout: 'Merge commit: ' + oid.slice(0,7) + '\\n' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git merge --continue: ' + e.message + '\\n' };
    }
}"""


_GIT_TAG_LIST_JS = """async ([dir]) => {
    try {
        const tags = await window.git.listTags({ fs: window.fsAdapter, dir });
        return { exit_code: 0, stdout: tags.join('\\n') + (tags.length ? '\\n' : '') };
    } catch(e) {
        return { exit_code: 1, stderr: 'git tag: ' + e.message + '\\n' };
    }
}"""

_GIT_TAG_CREATE_JS = """async ([dir, tagName, tagRef, annotate, message, authorName, authorEmail]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const opts = { fs, dir, ref: tagName };
        if (tagRef) opts.object = tagRef;
        if (annotate && message) {
            opts.message = message;
            opts.tagger = { name: authorName, email: authorEmail };
        }
        await git.tag(opts);
        return { exit_code: 0, stdout: '' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git tag: ' + e.message + '\\n' };
    }
}"""

_GIT_TAG_DELETE_JS = """async ([dir, tagName]) => {
    try {
        await window.git.deleteTag({ fs: window.fsAdapter, dir, ref: tagName });
        return { exit_code: 0, stdout: 'Deleted tag ' + tagName + '\\n' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git tag: ' + e.message + '\\n' };
    }
}"""

_GIT_REVPARSE_JS = """async ([dir, ref, short]) => {
    try {
        const oid = await window.git.resolveRef({ fs: window.fsAdapter, dir, ref });
        return { exit_code: 0, stdout: (short ? oid.slice(0,7) : oid) + '\\n' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git rev-parse: ' + e.message + '\\n' };
    }
}"""

_GIT_REVPARSE_ABBREV_JS = """async ([dir, ref]) => {
    try {
        const branch = await window.git.currentBranch({ fs: window.fsAdapter, dir });
        return { exit_code: 0, stdout: (branch || ref) + '\\n' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git rev-parse: ' + e.message + '\\n' };
    }
}"""

_GIT_CAT_FILE_JS = """async ([dir, objRef]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    try {
        const oid = await git.resolveRef({ fs, dir, ref: objRef });
        const { type, object } = await git.readObject({ fs, dir, oid });
        if (type === 'commit') {
            const { commit } = await git.readCommit({ fs, dir, oid });
            let out = 'tree ' + commit.tree + '\\n';
            if (commit.parent) {
                for (const p of commit.parent) out += 'parent ' + p + '\\n';
            }
            out += 'author ' + commit.author.name + ' <' + commit.author.email + '>\\n';
            out += '\\n' + commit.message;
            return { exit_code: 0, stdout: out };
        } else if (type === 'blob') {
            const content = new TextDecoder().decode(object);
            return { exit_code: 0, stdout: content };
        } else if (type === 'tree') {
            const { tree } = await git.readTree({ fs, dir, oid });
            let out = '';
            for (const e of tree) {
                out += e.mode + ' ' + e.type + ' ' + e.oid + '\\t' + e.path + '\\n';
            }
            return { exit_code: 0, stdout: out };
        }
        return { exit_code: 0, stdout: '[' + type + ' object]\\n' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git cat-file: ' + e.message + '\\n' };
    }
}"""

_GIT_MV_JS = """async ([dir, src, dest]) => {
    const git = window.git;
    const fs = window.fsAdapter;
    const FS = window.pyodide._module.FS;
    try {
        const srcPath = dir + '/' + src;
        const destPath = dir + '/' + dest;
        // Rename in working tree
        FS.rename(srcPath, destPath);
        // Update git index
        await git.remove({ fs, dir, filepath: src });
        await git.add({ fs, dir, filepath: dest });
        return { exit_code: 0, stdout: '' };
    } catch(e) {
        return { exit_code: 1, stderr: 'git mv: ' + e.message + '\\n' };
    }
}"""


async def builtin_git(args, stdin, env, memfs):
    """Dispatch git subcommands to isomorphic-git or host commands."""

    if not args:
        return ShellResult(exit_code=1, stderr="usage: git <command> [<args>]\n")

    # Check if isomorphic-git is loaded
    has_git = await memfs.page.evaluate("() => typeof window.git !== 'undefined'")
    if not has_git:
        return ShellResult(
            exit_code=1,
            stderr="git: not available in this sandbox. Use box_type='git' to enable.\n"
        )

    subcmd = args[0]
    rest = args[1:]

    # Resolve working directory (default /workspace or cwd)
    dir = env.cwd

    if subcmd == "init":
        branch = "main"
        target = None
        for i, a in enumerate(rest):
            if a == "-b" and i + 1 < len(rest):
                branch = rest[i + 1]
            elif not a.startswith("-"):
                target = env.resolve_path(a)
        if target:
            dir = target
        r = await memfs.page.evaluate(_GIT_INIT_JS, [dir, branch])

    elif subcmd == "add":
        # Support -A, -a, --all → treat as "git add ."
        add_all = any(a in ("-A", "-a", "--all") for a in rest)
        filepaths = [a for a in rest if not a.startswith("-")]
        if add_all and not filepaths:
            filepaths = ["."]
        if not filepaths:
            return ShellResult(exit_code=1, stderr="git add: nothing specified\n")
        # Resolve relative to dir, but isomorphic-git wants paths relative to repo root
        r = await memfs.page.evaluate(_GIT_ADD_JS, [dir, filepaths])

    elif subcmd == "commit":
        message = None
        i = 0
        while i < len(rest):
            if rest[i] == "-m" and i + 1 < len(rest):
                message = rest[i + 1]
                i += 2
            else:
                i += 1
        if not message:
            return ShellResult(exit_code=1, stderr="git commit: -m <message> required\n")
        author_name = env.variables.get("GIT_AUTHOR_NAME", "Agent")
        author_email = env.variables.get("GIT_AUTHOR_EMAIL", "agent@agentbox")
        r = await memfs.page.evaluate(_GIT_COMMIT_JS, [dir, message, author_name, author_email])

    elif subcmd == "log":
        oneline = "--oneline" in rest
        max_count = None
        for i, a in enumerate(rest):
            if a.startswith("-n") and len(a) > 2:
                max_count = int(a[2:])
            elif a == "-n" and i + 1 < len(rest):
                max_count = int(rest[i + 1])
        r = await memfs.page.evaluate(_GIT_LOG_JS, [dir, max_count, oneline])

    elif subcmd == "status":
        r = await memfs.page.evaluate(_GIT_STATUS_JS, [dir])

    elif subcmd == "branch":
        new_branch = None
        delete_branch = None
        for i, a in enumerate(rest):
            if a == "-d" and i + 1 < len(rest):
                delete_branch = rest[i + 1]
            elif a == "-D" and i + 1 < len(rest):
                delete_branch = rest[i + 1]
            elif not a.startswith("-"):
                new_branch = a
        r = await memfs.page.evaluate(_GIT_BRANCH_JS, [dir, new_branch, delete_branch])

    elif subcmd == "checkout":
        ref = None
        for a in rest:
            if not a.startswith("-"):
                ref = a
                break
        if not ref:
            return ShellResult(exit_code=1, stderr="git checkout: branch name required\n")
        r = await memfs.page.evaluate(_GIT_CHECKOUT_JS, [dir, ref])

    elif subcmd == "diff":
        cached = "--cached" in rest or "--staged" in rest
        diff_paths = [a for a in rest if not a.startswith("-")]
        r = await memfs.page.evaluate(_GIT_DIFF_JS, [dir, cached, diff_paths])

    elif subcmd == "rm":
        filepaths = [a for a in rest if not a.startswith("-")]
        if not filepaths:
            return ShellResult(exit_code=1, stderr="git rm: nothing specified\n")
        r = await memfs.page.evaluate(_GIT_RM_JS, [dir, filepaths])

    elif subcmd == "reset":
        hard = "--hard" in rest
        if not hard:
            return ShellResult(exit_code=1, stderr="git reset: only --hard is supported\n")
        # git reset --hard = checkout current branch with force to overwrite working tree
        r = await memfs.page.evaluate("""async ([dir]) => {
            const git = window.git;
            const fs = window.fsAdapter;
            try {
                const branch = await git.currentBranch({ fs, dir });
                const ref = branch || 'HEAD';
                await git.checkout({ fs, dir, ref, force: true });
                const sha = await git.resolveRef({ fs, dir, ref: 'HEAD' });
                return { exit_code: 0, stdout: 'HEAD is now at ' + sha.slice(0,7) + '\\n' };
            } catch(e) {
                return { exit_code: 1, stderr: 'git reset: ' + e.message + '\\n' };
            }
        }""", [dir])

    elif subcmd == "ls-files":
        r = await memfs.page.evaluate("""async ([dir]) => {
            const git = window.git;
            const fs = window.fsAdapter;
            try {
                const files = await git.listFiles({ fs, dir, ref: 'HEAD' });
                return { exit_code: 0, stdout: files.join('\\n') + (files.length ? '\\n' : '') };
            } catch(e) {
                return { exit_code: 1, stderr: 'git ls-files: ' + e.message + '\\n' };
            }
        }""", [dir])

    elif subcmd == "show":
        ref = "HEAD"
        name_only = "--name-only" in rest
        stat = "--stat" in rest
        file_path = None
        for a in rest:
            if not a.startswith("-"):
                ref = a
                break

        # Handle ref:path format (e.g. HEAD:calculator.py)
        if ":" in ref:
            ref_part, file_path = ref.split(":", 1)
            ref = ref_part or "HEAD"

        if file_path:
            # Show file content at ref — uses gitHelpers from fs_adapter
            r = await memfs.page.evaluate("""async ([dir, ref, filePath]) => {
                try {
                    const content = await window.gitHelpers.readFileAtRef(dir, ref, filePath);
                    if (content === null) {
                        return { exit_code: 1, stderr: 'git show: Could not find ' + ref + ':' + filePath + '\\n' };
                    }
                    return { exit_code: 0, stdout: content };
                } catch(e) {
                    return { exit_code: 1, stderr: 'git show: ' + e.message + '\\n' };
                }
            }""", [dir, ref, file_path])
        else:
            # Show commit info
            r = await memfs.page.evaluate("""async ([dir, ref, nameOnly, stat]) => {
                const git = window.git;
                const fs = window.fsAdapter;
                try {
                    const log = await git.log({ fs, dir, depth: 1, ref });
                    if (!log.length) return { exit_code: 1, stderr: 'git show: no commits\\n' };
                    const entry = log[0];
                    const sha = entry.oid;
                    const msg = entry.commit.message.trim();
                    const d = new Date(entry.commit.author.timestamp * 1000);
                    let output = `commit ${sha}\\n`;
                    output += `Author: ${entry.commit.author.name} <${entry.commit.author.email}>\\n`;
                    output += `Date:   ${d.toISOString()}\\n`;
                    output += `\\n    ${msg}\\n`;
                    if (nameOnly || stat) {
                        const files = await git.listFiles({ fs, dir, ref: sha });
                        output += '\\n';
                        for (const f of files) output += f + '\\n';
                    }
                    return { exit_code: 0, stdout: output };
                } catch(e) {
                    return { exit_code: 1, stderr: 'git show: ' + e.message + '\\n' };
                }
            }""", [dir, ref, name_only, stat])

    elif subcmd == "config":
        # Minimal config: set user.name / user.email in env vars
        is_global = "--global" in rest
        filtered = [a for a in rest if a not in ("--global", "--local")]
        if len(filtered) >= 2:
            key, value = filtered[0], filtered[1]
            if key == "user.name":
                env.set_variable("GIT_AUTHOR_NAME", value)
            elif key == "user.email":
                env.set_variable("GIT_AUTHOR_EMAIL", value)
            return ShellResult(exit_code=0)
        elif len(filtered) == 1:
            key = filtered[0]
            if key == "user.name":
                val = env.variables.get("GIT_AUTHOR_NAME", "Agent")
            elif key == "user.email":
                val = env.variables.get("GIT_AUTHOR_EMAIL", "agent@agentbox")
            else:
                val = ""
            return ShellResult(exit_code=0, stdout=val + "\n")
        return ShellResult(exit_code=0)

    elif subcmd == "merge":
        # git merge --abort: restore working tree and clear merge state
        if "--abort" in rest:
            env.set_variable("AGENTBOX_MERGE_HEAD", "")
            env.set_variable("AGENTBOX_MERGE_BRANCH", "")
            # Checkout current branch to restore working tree
            r = await memfs.page.evaluate("""async ([dir]) => {
                const git = window.git;
                const fs = window.fsAdapter;
                try {
                    const branch = await git.currentBranch({ fs, dir });
                    await git.checkout({ fs, dir, ref: branch, force: true });
                    return { exit_code: 0, stdout: 'Merge aborted.\\n' };
                } catch(e) {
                    return { exit_code: 1, stderr: 'git merge --abort: ' + e.message + '\\n' };
                }
            }""", [dir])
            return ShellResult(
                exit_code=r.get("exit_code", 1),
                stdout=r.get("stdout", ""),
                stderr=r.get("stderr", ""),
            )

        # git merge --continue: commit the resolved merge
        if "--continue" in rest:
            merge_branch = env.variables.get("AGENTBOX_MERGE_BRANCH", "")
            if not merge_branch:
                return ShellResult(exit_code=1, stderr="git merge: no merge in progress\n")
            # Delegate to git commit with merge parents
            author_name = env.variables.get("GIT_AUTHOR_NAME", "Agent")
            author_email = env.variables.get("GIT_AUTHOR_EMAIL", "agent@agentbox")
            r = await memfs.page.evaluate(_GIT_MERGE_CONTINUE_JS,
                [dir, merge_branch, author_name, author_email])
            if r.get("exit_code", 1) == 0:
                env.set_variable("AGENTBOX_MERGE_HEAD", "")
                env.set_variable("AGENTBOX_MERGE_BRANCH", "")
            return ShellResult(
                exit_code=r.get("exit_code", 1),
                stdout=r.get("stdout", ""),
                stderr=r.get("stderr", ""),
            )

        branch = None
        no_ff = "--no-ff" in rest
        for a in rest:
            if not a.startswith("-"):
                branch = a
                break
        if not branch:
            return ShellResult(exit_code=1, stderr="git merge: branch name required\n")
        author_name = env.variables.get("GIT_AUTHOR_NAME", "Agent")
        author_email = env.variables.get("GIT_AUTHOR_EMAIL", "agent@agentbox")
        r = await memfs.page.evaluate(_GIT_MERGE_JS, [dir, branch, author_name, author_email, no_ff])

        # On conflict, store merge state so --continue/--abort work
        if r.get("conflicts"):
            env.set_variable("AGENTBOX_MERGE_BRANCH", branch)
            env.set_variable("AGENTBOX_MERGE_HEAD", r.get("theirs", branch))

    elif subcmd == "tag":
        delete = False
        annotate = False
        message = None
        tag_name = None
        tag_ref = None
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "-d" and i + 1 < len(rest):
                delete = True
                tag_name = rest[i + 1]
                i += 2
            elif a == "-a":
                annotate = True
                i += 1
            elif a == "-m" and i + 1 < len(rest):
                message = rest[i + 1]
                i += 2
            elif not a.startswith("-"):
                if tag_name is None:
                    tag_name = a
                else:
                    tag_ref = a
                i += 1
            else:
                i += 1

        if delete and tag_name:
            r = await memfs.page.evaluate(_GIT_TAG_DELETE_JS, [dir, tag_name])
        elif tag_name:
            author_name = env.variables.get("GIT_AUTHOR_NAME", "Agent")
            author_email = env.variables.get("GIT_AUTHOR_EMAIL", "agent@agentbox")
            r = await memfs.page.evaluate(
                _GIT_TAG_CREATE_JS,
                [dir, tag_name, tag_ref, annotate, message, author_name, author_email],
            )
        else:
            r = await memfs.page.evaluate(_GIT_TAG_LIST_JS, [dir])

    elif subcmd == "rev-parse":
        show_toplevel = "--show-toplevel" in rest
        abbrev_ref = "--abbrev-ref" in rest
        short = "--short" in rest
        ref = None
        for a in rest:
            if not a.startswith("-"):
                ref = a
                break
        if show_toplevel:
            r = {"exit_code": 0, "stdout": dir + "\n"}
        elif abbrev_ref and ref:
            r = await memfs.page.evaluate(_GIT_REVPARSE_ABBREV_JS, [dir, ref])
        elif ref:
            r = await memfs.page.evaluate(_GIT_REVPARSE_JS, [dir, ref, short])
        else:
            return ShellResult(exit_code=1, stderr="git rev-parse: need a ref\n")

    elif subcmd == "cat-file":
        obj_ref = None
        for a in rest:
            if not a.startswith("-"):
                obj_ref = a
                break
        if not obj_ref:
            return ShellResult(exit_code=1, stderr="git cat-file: need an object\n")
        r = await memfs.page.evaluate(_GIT_CAT_FILE_JS, [dir, obj_ref])

    elif subcmd == "mv":
        paths = [a for a in rest if not a.startswith("-")]
        if len(paths) < 2:
            return ShellResult(exit_code=1, stderr="git mv: need source and destination\n")
        r = await memfs.page.evaluate(_GIT_MV_JS, [dir, paths[0], paths[1]])

    elif subcmd in ("push", "pull", "fetch", "clone"):
        # Tier 3 — delegate to host commands
        from agentbox.box.shell.host_commands import HOST_COMMANDS
        host_fn = HOST_COMMANDS.get(f"git-{subcmd}")
        if host_fn:
            return await host_fn(rest, stdin, env, memfs)
        return ShellResult(
            exit_code=1,
            stderr=f"git {subcmd}: host command not registered\n"
        )

    else:
        return ShellResult(
            exit_code=1,
            stderr=f"git: '{subcmd}' is not a git command\n"
        )

    return ShellResult(
        exit_code=r.get("exit_code", 1),
        stdout=r.get("stdout", ""),
        stderr=r.get("stderr", ""),
    )
