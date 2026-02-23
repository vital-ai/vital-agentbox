"""
Spike test: Binary file transfer + isomorphic-git on Emscripten MemFS

Tests:
1. Binary write/read via ArrayBuffer (zero-overhead if Playwright supports it)
2. Binary write/read via base64 (reliable fallback)
3. Round-trip integrity check at various sizes
4. isomorphic-git: init, add, commit, log — all on MemFS
"""

import asyncio
import base64
import hashlib
import os
import time


PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js"
ISOMORPHIC_GIT_CDN = "https://unpkg.com/isomorphic-git@1.27.1/index.umd.min.js"


async def setup_page():
    """Launch browser, load Pyodide + isomorphic-git, return (browser, page)."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    # Load both Pyodide and isomorphic-git
    html = (
        f'<script src="{PYODIDE_CDN}"></script>'
        f'<script src="{ISOMORPHIC_GIT_CDN}"></script>'
    )
    await page.goto(f"data:text/html,{html}")

    # Initialize Pyodide (gives us Emscripten FS)
    await page.evaluate("""async () => {
        window.pyodide = await loadPyodide();
    }""")

    return pw, browser, page


# ---------------------------------------------------------------------------
# Test 1: Binary transfer via base64
# ---------------------------------------------------------------------------

async def test_base64_write_read(page, size_bytes):
    """Write random bytes to MemFS via base64, read back, verify."""

    test_data = os.urandom(size_bytes)
    b64_data = base64.b64encode(test_data).decode('ascii')

    # Write: base64 string → decode in JS → MemFS
    t0 = time.perf_counter()
    await page.evaluate("""(b64) => {
        const fs = window.pyodide._module.FS;
        const binaryString = atob(b64);
        const arr = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            arr[i] = binaryString.charCodeAt(i);
        }
        fs.writeFile('/test_base64.bin', arr);
    }""", b64_data)
    write_time = time.perf_counter() - t0

    # Read: MemFS → base64 string → Python
    t0 = time.perf_counter()
    result_b64 = await page.evaluate("""() => {
        const fs = window.pyodide._module.FS;
        const data = fs.readFile('/test_base64.bin');
        let binary = '';
        for (let i = 0; i < data.length; i++) {
            binary += String.fromCharCode(data[i]);
        }
        return btoa(binary);
    }""")
    read_time = time.perf_counter() - t0

    result_bytes = base64.b64decode(result_b64)
    match = result_bytes == test_data
    return {
        "method": "base64",
        "size": size_bytes,
        "write_ms": round(write_time * 1000, 1),
        "read_ms": round(read_time * 1000, 1),
        "match": match,
        "hash_ok": hashlib.sha256(result_bytes).hexdigest() == hashlib.sha256(test_data).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Test 3: isomorphic-git on Emscripten MemFS
# ---------------------------------------------------------------------------

async def test_isomorphic_git(page):
    """
    Test isomorphic-git using an adapter that wraps Emscripten's FS
    to provide the Node.js fs.promises interface isomorphic-git expects.
    """

    # Create the FS adapter and run git operations
    result = await page.evaluate("""async () => {
        const FS = window.pyodide._module.FS;
        const git = window.git;  // isomorphic-git UMD attaches to window.git
        const results = [];

        if (!git) {
            return { error: "isomorphic-git not loaded (window.git is undefined)" };
        }

        // --- Adapter: wrap Emscripten FS as Node.js fs.promises ---
        // All methods are arrow functions to avoid 'this' binding issues
        // when isomorphic-git destructures or stores them.

        function makeStat(filepath) {
            const s = FS.stat(filepath);
            return {
                isFile: () => (s.mode & 0o170000) === 0o100000,
                isDirectory: () => (s.mode & 0o170000) === 0o040000,
                isSymbolicLink: () => (s.mode & 0o170000) === 0o120000,
                size: s.size,
                mode: s.mode,
                mtimeMs: s.mtime instanceof Date ? s.mtime.getTime() : (typeof s.mtime === 'number' ? s.mtime : 0),
                ctimeMs: s.ctime instanceof Date ? s.ctime.getTime() : (typeof s.ctime === 'number' ? s.ctime : 0),
                uid: 1,
                gid: 1,
                dev: s.dev || 0,
                ino: s.ino || 0,
            };
        }

        function makeError(e, code) {
            const err = new Error(e.message || String(e));
            err.code = code || 'ENOENT';
            return err;
        }

        // Recursively create parent directories (like mkdir -p)
        function mkdirp(filepath) {
            const parts = filepath.split('/').filter(Boolean);
            let current = '';
            for (const part of parts) {
                current += '/' + part;
                try { FS.mkdir(current); }
                catch (e) { /* ignore EEXIST */ }
            }
        }

        const fsAdapter = {
            promises: {
                readFile: async (filepath, options) => {
                    try {
                        if (options && (options.encoding === 'utf8' || options === 'utf8')) {
                            return FS.readFile(filepath, { encoding: 'utf8' });
                        }
                        return new Uint8Array(FS.readFile(filepath));
                    } catch (e) { throw makeError(e); }
                },
                writeFile: async (filepath, data) => {
                    try {
                        // Ensure parent directory exists
                        const parentDir = filepath.substring(0, filepath.lastIndexOf('/'));
                        if (parentDir) mkdirp(parentDir);
                        if (typeof data === 'string') {
                            FS.writeFile(filepath, data);
                        } else {
                            FS.writeFile(filepath, data);
                        }
                    } catch (e) { throw makeError(e, 'EIO'); }
                },
                unlink: async (filepath) => {
                    try { FS.unlink(filepath); }
                    catch (e) { throw makeError(e); }
                },
                readdir: async (filepath) => {
                    try {
                        return FS.readdir(filepath).filter(e => e !== '.' && e !== '..');
                    } catch (e) { throw makeError(e); }
                },
                mkdir: async (filepath) => {
                    try { FS.mkdir(filepath); }
                    catch (e) {
                        // Ignore EEXIST
                        if (e.errno !== 20) throw makeError(e, 'EIO');
                    }
                },
                rmdir: async (filepath) => {
                    try { FS.rmdir(filepath); }
                    catch (e) { throw makeError(e); }
                },
                stat: async (filepath) => {
                    try { return makeStat(filepath); }
                    catch (e) { throw makeError(e); }
                },
                lstat: async (filepath) => {
                    try { return makeStat(filepath); }
                    catch (e) { throw makeError(e); }
                },
                readlink: async (filepath) => {
                    try { return FS.readlink(filepath); }
                    catch (e) { throw makeError(e); }
                },
                symlink: async (target, filepath) => {
                    try { FS.symlink(target, filepath); }
                    catch (e) { throw makeError(e, 'EIO'); }
                },
                chmod: async (filepath, mode) => {
                    try { FS.chmod(filepath, mode); }
                    catch (e) { throw makeError(e, 'EIO'); }
                },
            }
        };

        try {
            // 1. git init
            const dir = '/workspace';
            FS.mkdir(dir);
            await git.init({ fs: fsAdapter, dir: dir, defaultBranch: 'main' });
            results.push({ step: 'git init', status: 'ok' });

            // Verify .git directory exists
            const gitDir = FS.readdir(dir + '/.git').filter(e => e !== '.' && e !== '..');
            results.push({ step: '.git contents', entries: gitDir });

            // 2. Create a file
            FS.writeFile(dir + '/readme.md', '# Hello from AgentBox\\nThis is a test.');
            results.push({ step: 'create readme.md', status: 'ok' });

            // 3. git add
            await git.add({ fs: fsAdapter, dir: dir, filepath: 'readme.md' });
            results.push({ step: 'git add readme.md', status: 'ok' });

            // 4. git commit
            const sha1 = await git.commit({
                fs: fsAdapter,
                dir: dir,
                message: 'Initial commit',
                author: { name: 'Agent', email: 'agent@agentbox' },
            });
            results.push({ step: 'git commit (1)', sha: sha1 });

            // 5. Create another file and commit
            FS.writeFile(dir + '/data.txt', 'Some analysis results: 42');
            await git.add({ fs: fsAdapter, dir: dir, filepath: 'data.txt' });
            const sha2 = await git.commit({
                fs: fsAdapter,
                dir: dir,
                message: 'Add data file',
                author: { name: 'Agent', email: 'agent@agentbox' },
            });
            results.push({ step: 'git commit (2)', sha: sha2 });

            // 6. git log
            const log = await git.log({ fs: fsAdapter, dir: dir });
            const logSummary = log.map(entry => ({
                sha: entry.oid.substring(0, 7),
                message: entry.commit.message.trim(),
                author: entry.commit.author.name,
            }));
            results.push({ step: 'git log', commits: logSummary });

            // 7. git status
            const status = await git.statusMatrix({ fs: fsAdapter, dir: dir });
            results.push({ step: 'git status', matrix: status });

            // 8. git branch
            const branches = await git.listBranches({ fs: fsAdapter, dir: dir });
            results.push({ step: 'git branch', branches: branches });

            // 9. Create a branch
            await git.branch({ fs: fsAdapter, dir: dir, ref: 'feature-x' });
            const branchesAfter = await git.listBranches({ fs: fsAdapter, dir: dir });
            results.push({ step: 'git branch feature-x', branches: branchesAfter });

            return { success: true, results: results };
        } catch (e) {
            results.push({ step: 'ERROR', error: e.message, stack: e.stack });
            return { success: false, results: results };
        }
    }""")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 70)
    print("SPIKE: Binary File Transfer + isomorphic-git on MemFS")
    print("=" * 70)

    pw, browser, page = await setup_page()

    try:
        # --- Binary transfer tests ---
        sizes = [1024, 10240, 102400, 1048576]  # 1KB, 10KB, 100KB, 1MB
        labels = ["1KB", "10KB", "100KB", "1MB"]

        print("\n--- Binary Transfer: Base64 ---")
        for size, label in zip(sizes, labels):
            r = await test_base64_write_read(page, size)
            status = "✓" if r["match"] else "✗"
            print(f"  {status} {label:>6}: write={r['write_ms']:>8.1f}ms  read={r['read_ms']:>8.1f}ms  match={r['match']}")

        # --- isomorphic-git test ---
        print("\n--- isomorphic-git on MemFS ---")
        git_result = await test_isomorphic_git(page)

        if git_result.get("success"):
            for step in git_result["results"]:
                name = step.get("step", "?")
                if "sha" in step:
                    print(f"  ✓ {name}: {step['sha'][:7]}")
                elif "commits" in step:
                    print(f"  ✓ {name}:")
                    for c in step["commits"]:
                        print(f"      {c['sha']} {c['message']} ({c['author']})")
                elif "branches" in step:
                    print(f"  ✓ {name}: {step['branches']}")
                elif "entries" in step:
                    print(f"  ✓ {name}: {step['entries']}")
                elif "matrix" in step:
                    print(f"  ✓ {name}: {len(step['matrix'])} files tracked")
                elif "error" in step:
                    print(f"  ✗ {name}: {step['error']}")
                else:
                    print(f"  ✓ {name}")
        else:
            print(f"  ✗ FAILED")
            for step in git_result.get("results", []):
                if "error" in step:
                    print(f"    Error at '{step['step']}': {step['error']}")
                    if "stack" in step:
                        # Print first few lines of stack
                        for line in step["stack"].split("\n")[:5]:
                            print(f"      {line}")
                else:
                    print(f"    ✓ {step.get('step', '?')}")

        print("\n" + "=" * 70)
        print("SPIKE COMPLETE")
        print("=" * 70)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
