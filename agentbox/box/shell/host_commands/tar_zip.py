"""tar, zip, unzip — host-delegated archive commands.

These extract files from MemFS to a temp dir, run the native binary,
and write results back to MemFS.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from agentbox.box.shell.environment import ShellResult


async def host_tar(args, stdin, env, memfs) -> ShellResult:
    """Run tar on the host, bridging files to/from MemFS."""
    tar_path = shutil.which("tar")
    if not tar_path:
        return ShellResult(exit_code=1, stderr="tar: not installed on host\n")

    # Parse key args to understand intent
    create = False
    extract = False
    archive_file = None
    directory = None
    verbose = False
    compress_flag = ""
    file_args = []

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-c", "--create"):
            create = True
        elif a in ("-x", "--extract"):
            extract = True
        elif a in ("-v", "--verbose"):
            verbose = True
        elif a in ("-z", "--gzip"):
            compress_flag = "-z"
        elif a in ("-j", "--bzip2"):
            compress_flag = "-j"
        elif a in ("-f", "--file") and i + 1 < len(args):
            archive_file = args[i + 1]
            i += 1
        elif a in ("-C", "--directory") and i + 1 < len(args):
            directory = args[i + 1]
            i += 1
        elif a.startswith("-") and "f" in a and not a.startswith("--"):
            # Combined flags like -czf archive.tar.gz
            if "c" in a:
                create = True
            if "x" in a:
                extract = True
            if "v" in a:
                verbose = True
            if "z" in a:
                compress_flag = "-z"
            if "j" in a:
                compress_flag = "-j"
            # The next arg is the archive file
            if i + 1 < len(args):
                archive_file = args[i + 1]
                i += 1
        elif not a.startswith("-"):
            file_args.append(a)
        i += 1

    if not archive_file:
        return ShellResult(exit_code=1, stderr="tar: no archive file specified (-f)\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        if create:
            # Extract source files from MemFS to tmp
            for fp in file_args:
                resolved = env.resolve_path(fp)
                content = await memfs.read_file_binary(resolved)
                if content is None:
                    return ShellResult(exit_code=1, stderr=f"tar: {fp}: No such file or directory\n")
                local = os.path.join(tmp_dir, fp.lstrip("/"))
                os.makedirs(os.path.dirname(local), exist_ok=True)
                with open(local, "wb") as f:
                    f.write(content)

            # Build tar command
            cmd = [tar_path]
            if compress_flag:
                cmd.append(compress_flag)
            cmd.extend(["-cf", os.path.join(tmp_dir, "_archive.tar")])
            cmd.extend(["-C", tmp_dir] + [fp.lstrip("/") for fp in file_args])

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return ShellResult(exit_code=proc.returncode, stderr=stderr.decode())

            # Write archive back to MemFS
            archive_resolved = env.resolve_path(archive_file)
            with open(os.path.join(tmp_dir, "_archive.tar"), "rb") as f:
                await memfs.write_file_binary(archive_resolved, f.read())
            return ShellResult(exit_code=0, stdout=f"tar: created {archive_file}\n")

        elif extract:
            # Read archive from MemFS
            archive_resolved = env.resolve_path(archive_file)
            data = await memfs.read_file_binary(archive_resolved)
            if data is None:
                return ShellResult(exit_code=1, stderr=f"tar: {archive_file}: No such file or directory\n")
            local_archive = os.path.join(tmp_dir, "archive.tar")
            with open(local_archive, "wb") as f:
                f.write(data)

            extract_dir = os.path.join(tmp_dir, "extracted")
            os.makedirs(extract_dir)

            cmd = [tar_path]
            if compress_flag:
                cmd.append(compress_flag)
            cmd.extend(["-xf", local_archive, "-C", extract_dir])

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return ShellResult(exit_code=proc.returncode, stderr=stderr.decode())

            # Write extracted files back to MemFS
            target_dir = env.resolve_path(directory) if directory else env.cwd
            count = 0
            for root, dirs, files in os.walk(extract_dir):
                for fname in files:
                    local = os.path.join(root, fname)
                    rel = os.path.relpath(local, extract_dir)
                    memfs_path = f"{target_dir}/{rel}"
                    with open(local, "rb") as f:
                        await memfs.write_file_binary(memfs_path, f.read())
                    count += 1
            return ShellResult(exit_code=0, stdout=f"tar: extracted {count} files\n")

        else:
            return ShellResult(exit_code=1, stderr="tar: must specify -c (create) or -x (extract)\n")


async def host_zip(args, stdin, env, memfs) -> ShellResult:
    """Run zip on the host, bridging files to/from MemFS."""
    zip_path = shutil.which("zip")
    if not zip_path:
        return ShellResult(exit_code=1, stderr="zip: not installed on host\n")

    # zip archive.zip file1 file2 ...
    if len(args) < 2:
        return ShellResult(exit_code=1, stderr="zip: usage: zip archive.zip file1 [file2 ...]\n")

    archive_file = args[0]
    file_args = args[1:]

    with tempfile.TemporaryDirectory() as tmp_dir:
        for fp in file_args:
            resolved = env.resolve_path(fp)
            content = await memfs.read_file_binary(resolved)
            if content is None:
                return ShellResult(exit_code=1, stderr=f"zip: {fp}: No such file or directory\n")
            local = os.path.join(tmp_dir, fp.lstrip("/"))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(content)

        local_zip = os.path.join(tmp_dir, "_out.zip")
        cmd = [zip_path, "-j", local_zip] + [
            os.path.join(tmp_dir, fp.lstrip("/")) for fp in file_args
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return ShellResult(exit_code=proc.returncode, stderr=stderr.decode())

        archive_resolved = env.resolve_path(archive_file)
        with open(local_zip, "rb") as f:
            await memfs.write_file_binary(archive_resolved, f.read())
        return ShellResult(exit_code=0, stdout=f"zip: created {archive_file}\n")


async def host_unzip(args, stdin, env, memfs) -> ShellResult:
    """Run unzip on the host, bridging files to/from MemFS."""
    unzip_path = shutil.which("unzip")
    if not unzip_path:
        return ShellResult(exit_code=1, stderr="unzip: not installed on host\n")

    # Parse args
    archive_file = None
    dest_dir = None
    i = 0
    while i < len(args):
        if args[i] == "-d" and i + 1 < len(args):
            dest_dir = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            archive_file = args[i]
            i += 1
        else:
            i += 1

    if not archive_file:
        return ShellResult(exit_code=1, stderr="unzip: usage: unzip archive.zip [-d dir]\n")

    archive_resolved = env.resolve_path(archive_file)
    data = await memfs.read_file_binary(archive_resolved)
    if data is None:
        return ShellResult(exit_code=1, stderr=f"unzip: {archive_file}: No such file or directory\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_zip = os.path.join(tmp_dir, "archive.zip")
        with open(local_zip, "wb") as f:
            f.write(data)

        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir)

        proc = await asyncio.create_subprocess_exec(
            unzip_path, "-o", local_zip, "-d", extract_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return ShellResult(exit_code=proc.returncode, stderr=stderr.decode())

        target = env.resolve_path(dest_dir) if dest_dir else env.cwd
        count = 0
        for root, dirs, files in os.walk(extract_dir):
            for fname in files:
                local = os.path.join(root, fname)
                rel = os.path.relpath(local, extract_dir)
                memfs_path = f"{target}/{rel}"
                with open(local, "rb") as f:
                    await memfs.write_file_binary(memfs_path, f.read())
                count += 1
        return ShellResult(exit_code=0, stdout=f"unzip: extracted {count} files\n")
