"""
Reusable JavaScript FS adapter that wraps Emscripten FS for isomorphic-git.

isomorphic-git expects a Node.js `fs` module with `fs.promises.*` methods.
This adapter bridges Emscripten's synchronous FS API to that interface.

Injected into the browser page once when GitBox starts.
"""

# This JS code is evaluated in the browser page to set up window.fsAdapter
FS_ADAPTER_JS = """
(() => {
    if (window.fsAdapter) return;  // Already set up

    const FS = window.pyodide._module.FS;

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
            uid: 1, gid: 1,
            dev: s.dev || 0,
            ino: s.ino || 0,
        };
    }

    function makeError(e, code) {
        const err = new Error(e.message || String(e));
        err.code = code || 'ENOENT';
        return err;
    }

    function mkdirp(filepath) {
        const parts = filepath.split('/').filter(Boolean);
        let current = '';
        for (const part of parts) {
            current += '/' + part;
            try { FS.mkdir(current); }
            catch (e) { /* ignore EEXIST */ }
        }
    }

    window.fsAdapter = {
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
                    const parentDir = filepath.substring(0, filepath.lastIndexOf('/'));
                    if (parentDir) mkdirp(parentDir);
                    FS.writeFile(filepath, data);
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
            rename: async (oldpath, newpath) => {
                try { FS.rename(oldpath, newpath); }
                catch (e) { throw makeError(e, 'EIO'); }
            },
        }
    };
})();
"""


# Higher-level git helpers injected alongside fsAdapter.
# Provides reusable operations that compose isomorphic-git primitives.
GIT_HELPERS_JS = """
(() => {
    if (window.gitHelpers) return;

    window.gitHelpers = {
        /**
         * Read a file's content from the git object store at a given ref.
         * e.g. readFileAtRef(dir, 'HEAD', 'src/main.py') -> string
         */
        readFileAtRef: async (dir, ref, filepath) => {
            const git = window.git;
            const fs = window.fsAdapter;

            const oid = await git.resolveRef({ fs, dir, ref });
            const { commit } = await git.readCommit({ fs, dir, oid });
            const { tree } = await git.readTree({ fs, dir, oid: commit.tree });

            const parts = filepath.split('/').filter(Boolean);
            let currentTree = tree;

            // Walk intermediate directories
            for (let i = 0; i < parts.length - 1; i++) {
                const entry = currentTree.find(e => e.path === parts[i]);
                if (!entry || entry.type !== 'tree') return null;
                const sub = await git.readTree({ fs, dir, oid: entry.oid });
                currentTree = sub.tree;
            }

            const fileName = parts[parts.length - 1];
            const entry = currentTree.find(e => e.path === fileName);
            if (!entry) return null;

            const { blob } = await git.readBlob({ fs, dir, oid: entry.oid });
            return new TextDecoder().decode(blob);
        },
    };
})();
"""
