"""
Git sync: push/pull between MemFS and a StorageBackend.

These functions read/write git objects and working tree files between
the in-browser MemFS (via page.evaluate) and a permanent store.
They are called by the git push/pull/clone host commands.
"""

import base64


async def push_to_store(page, dir, repo_id, storage):
    """Push all files from MemFS repo to storage backend.

    Reads every file under {dir}/ from MemFS and writes to storage.
    Incremental sync could be added later by tracking dirty objects.

    Returns:
        (files_pushed, errors)
    """
    # Get full recursive listing of all files in the repo
    file_list = await page.evaluate("""([dir]) => {
        const FS = window.pyodide._module.FS;
        const results = [];

        function walk(path) {
            try {
                const entries = FS.readdir(path).filter(e => e !== '.' && e !== '..');
                for (const entry of entries) {
                    const full = path + '/' + entry;
                    try {
                        const stat = FS.stat(full);
                        const isDir = (stat.mode & 0o170000) === 0o040000;
                        if (isDir) {
                            walk(full);
                        } else {
                            results.push(full);
                        }
                    } catch(e) { /* skip unreadable */ }
                }
            } catch(e) { /* skip unreadable dirs */ }
        }

        walk(dir);
        return results;
    }""", [dir])

    files_pushed = 0
    errors = []

    for memfs_path in file_list:
        # Read file as base64 (handles binary files like git objects)
        b64_data = await page.evaluate("""([path]) => {
            const FS = window.pyodide._module.FS;
            try {
                const data = FS.readFile(path);
                // Convert Uint8Array to base64
                let binary = '';
                for (let i = 0; i < data.length; i++) {
                    binary += String.fromCharCode(data[i]);
                }
                return btoa(binary);
            } catch(e) {
                return null;
            }
        }""", [memfs_path])

        if b64_data is None:
            errors.append(f"Failed to read: {memfs_path}")
            continue

        file_bytes = base64.b64decode(b64_data)

        # Compute relative path from repo dir
        rel_path = memfs_path[len(dir):].lstrip("/")
        await storage.write_file(repo_id, rel_path, file_bytes)
        files_pushed += 1

    return files_pushed, errors


async def pull_from_store(page, dir, repo_id, storage, prefix_filter=None):
    """Pull files from storage backend into MemFS.

    Downloads files from the store and writes into MemFS at {dir}/.
    If prefix_filter is set (e.g. ".git/"), only files matching that prefix
    are pulled — used by git fetch to sync objects without touching working tree.

    Returns:
        (files_pulled, errors)
    """
    file_list = await storage.list_files(repo_id)
    if prefix_filter:
        file_list = [f for f in file_list if f.startswith(prefix_filter)]

    files_pulled = 0
    errors = []

    for rel_path in file_list:
        file_bytes = await storage.read_file(repo_id, rel_path)
        if file_bytes is None:
            errors.append(f"Failed to read from store: {rel_path}")
            continue

        b64_data = base64.b64encode(file_bytes).decode("ascii")
        memfs_path = f"{dir}/{rel_path}"

        ok = await page.evaluate("""([path, b64]) => {
            const FS = window.pyodide._module.FS;
            try {
                // Ensure parent directory exists
                const parts = path.split('/').filter(Boolean);
                let current = '';
                for (let i = 0; i < parts.length - 1; i++) {
                    current += '/' + parts[i];
                    try { FS.mkdir(current); } catch(e) {}
                }

                // Decode base64 to Uint8Array
                const binary = atob(b64);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) {
                    bytes[i] = binary.charCodeAt(i);
                }
                FS.writeFile(path, bytes);
                return true;
            } catch(e) {
                return false;
            }
        }""", [memfs_path, b64_data])

        if ok:
            files_pulled += 1
        else:
            errors.append(f"Failed to write to MemFS: {memfs_path}")

    return files_pulled, errors
