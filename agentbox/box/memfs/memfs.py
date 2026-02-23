import json
import base64


class MemFS:
    """Interface to Emscripten's in-memory filesystem via a Playwright page.

    The page must have Pyodide loaded (window.pyodide). All FS operations
    execute as JavaScript inside the browser page via page.evaluate().
    """

    # Shared JS helper injected once per evaluate call via _eval.
    _JS_PREAMBLE = "const fs = window.pyodide._module.FS;"
    _IS_DIR = "(s.mode & 0o170000) === 0o040000"

    def __init__(self, page):
        self.page = page

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _eval(self, body, arg=None):
        """Evaluate a JS function body that uses `fs` (Emscripten FS).

        The preamble ``const fs = ...`` is prepended automatically.
        *body* should be a JS expression or block that returns a value.
        """
        wrapper = f"(arg) => {{ {self._JS_PREAMBLE} {body} }}"
        return await self.page.evaluate(wrapper, arg)

    @staticmethod
    def _join(parent, child):
        """Join two path segments (JS-side helper is inlined instead)."""
        if parent == "/":
            return "/" + child
        return parent + "/" + child

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    async def list_dir(self, directory="/", recursive=False, info=False):
        """List directory contents.

        Returns:
            - Default: list of name strings.
            - info=True: list of dicts with name, type, size.
            - recursive=True: nested dict (name→subtree|"file").
            - recursive+info: list of dicts with children for dirs.
            - On error: string starting with "Error".
        """
        return await self._eval("""
            function walk(path, recursive, info) {
                let entries;
                try { entries = fs.readdir(path).filter(e => e !== '.' && e !== '..'); }
                catch(e) { return "Error reading directory: " + e.message; }

                if (!recursive && !info) return entries;

                let result = info ? [] : {};
                for (const name of entries) {
                    const full = path === '/' ? '/' + name : path + '/' + name;
                    let s;
                    try { s = fs.stat(full); } catch(e) {
                        if (info) { result.push({name, error: e.message}); }
                        else      { result[name] = "Error: " + e.message; }
                        continue;
                    }
                    const isDir = """ + self._IS_DIR + """;
                    if (info) {
                        let item = {name, type: isDir ? 'dir' : 'file', size: isDir ? null : s.size};
                        if (recursive && isDir) item.children = walk(full, true, true);
                        result.push(item);
                    } else {
                        result[name] = isDir && recursive ? walk(full, true, false) : (isDir ? {} : 'file');
                    }
                }
                return result;
            }
            return walk(arg.dir, arg.rec, arg.info);
        """, {"dir": directory, "rec": recursive, "info": info})

    # ------------------------------------------------------------------
    # File read / write (text)
    # ------------------------------------------------------------------

    async def read_file(self, path):
        """Read a file as a UTF-8 string. Returns None if not found."""
        return await self._eval("""
            try { return fs.readFile(arg, {encoding: 'utf8'}); }
            catch(e) { return null; }
        """, path)

    async def write_file(self, path, content, append=False):
        """Write a UTF-8 string to a file. Returns True on success, False on error."""
        return await self._eval("""
            try {
                if (arg.append) {
                    let existing = '';
                    try { existing = fs.readFile(arg.path, {encoding: 'utf8'}); } catch(e) {}
                    fs.writeFile(arg.path, existing + arg.content);
                } else {
                    fs.writeFile(arg.path, arg.content);
                }
                return true;
            } catch(e) { return false; }
        """, {"path": path, "content": content, "append": append})

    # ------------------------------------------------------------------
    # File read / write (binary via base64)
    # ------------------------------------------------------------------

    async def read_file_binary(self, path):
        """Read a file as raw bytes. Returns bytes or None if not found."""
        b64 = await self._eval("""
            try {
                const data = fs.readFile(arg);
                let binary = '';
                for (let i = 0; i < data.length; i++) binary += String.fromCharCode(data[i]);
                return btoa(binary);
            } catch(e) { return null; }
        """, path)
        if b64 is None:
            return None
        return base64.b64decode(b64)

    async def write_file_binary(self, path, data):
        """Write raw bytes to a file via base64. Returns True on success."""
        b64 = base64.b64encode(data).decode("ascii")
        return await self._eval("""
            try {
                const binary = atob(arg.b64);
                const arr = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) arr[i] = binary.charCodeAt(i);
                fs.writeFile(arg.path, arr);
                return true;
            } catch(e) { return false; }
        """, {"path": path, "b64": b64})

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    async def mkdir(self, path):
        """Create a single directory. Returns True/False."""
        return await self._eval("""
            try { fs.mkdir(arg); return true; }
            catch(e) { return false; }
        """, path)

    async def mkdir_p(self, path):
        """Create a directory and all parent directories. Returns True/False."""
        return await self._eval("""
            try {
                const parts = arg.split('/').filter(Boolean);
                let cur = '';
                for (const p of parts) {
                    cur += '/' + p;
                    try { fs.mkdir(cur); } catch(e) { /* EEXIST ok */ }
                }
                return true;
            } catch(e) { return false; }
        """, path)

    async def rmdir(self, path):
        """Remove an empty directory. Returns True/False."""
        return await self._eval("""
            try { fs.rmdir(arg); return true; }
            catch(e) { return false; }
        """, path)

    # ------------------------------------------------------------------
    # File / path operations
    # ------------------------------------------------------------------

    async def remove_file(self, path):
        """Unlink a file. Returns True/False."""
        return await self._eval("""
            try { fs.unlink(arg); return true; }
            catch(e) { return false; }
        """, path)

    async def rename(self, old_path, new_path):
        """Rename / move a file or directory. Returns True/False."""
        return await self._eval("""
            try { fs.rename(arg.src, arg.dst); return true; }
            catch(e) { return false; }
        """, {"src": old_path, "dst": new_path})

    async def exists(self, path):
        """Check if a path exists. Returns True/False."""
        return await self._eval("""
            try { fs.stat(arg); return true; }
            catch(e) { return false; }
        """, path)

    async def stat(self, path):
        """Stat a path. Returns dict with type, size, mode, mtime or None."""
        return await self._eval("""
            try {
                const s = fs.stat(arg);
                const isDir = """ + self._IS_DIR + """;
                return {
                    type: isDir ? 'dir' : 'file',
                    size: s.size,
                    mode: s.mode,
                    mtime: s.mtime instanceof Date ? s.mtime.getTime() : s.mtime,
                };
            } catch(e) { return null; }
        """, path)

    async def copy(self, src, dest):
        """Copy a file or directory recursively.

        Returns True on success, or an error string on failure.
        """
        return await self._eval("""
            function cp(src, dest) {
                let s;
                try { s = fs.stat(src); }
                catch(e) { return "Error: " + src + ": " + e.message; }
                if ((s.mode & 0o170000) === 0o040000) {
                    try { fs.mkdir(dest); } catch(e) { if (e.errno !== 20) return "Error: mkdir " + dest + ": " + e.message; }
                    const entries = fs.readdir(src).filter(e => e !== '.' && e !== '..');
                    for (const name of entries) {
                        const r = cp(
                            src === '/' ? '/' + name : src + '/' + name,
                            dest === '/' ? '/' + name : dest + '/' + name
                        );
                        if (r !== true) return r;
                    }
                } else {
                    try {
                        const data = fs.readFile(src);
                        fs.writeFile(dest, data);
                    } catch(e) { return "Error: cp " + src + " -> " + dest + ": " + e.message; }
                }
                return true;
            }
            return cp(arg.src, arg.dst);
        """, {"src": src, "dst": dest})
