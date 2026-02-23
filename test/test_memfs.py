import json
import asyncio

from agentbox.box.memfs.memfs import MemFS


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Load Pyodide via CDN; ensure it's attached to window.pyodide
        await page.goto('data:text/html,<script src="https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js"></script>')
        await page.evaluate('''async () => {
            window.pyodide = await loadPyodide();
        }''')

        memfs = MemFS(page)

        # Create a directory, write a file, and list its contents.
        success_mkdir = await memfs.mkdir("/testdir")
        print("Created /testdir:", success_mkdir)

        success_write = await memfs.write_file("/testdir/hello.txt", "Hello, World!")
        print("Wrote /testdir/hello.txt:", success_write)

        content = await memfs.read_file("/testdir/hello.txt")
        print("Content of /testdir/hello.txt:", content)

        # List directory non-recursively.
        listing = await memfs.list_dir("/testdir", recursive=False)
        print("Listing of /testdir:", listing)

        # List directory recursively.
        recursive_listing = await memfs.list_dir("/", recursive=True)
        print("Recursive listing of memfs:", recursive_listing)

        # Remove the file and directory.
        removed_file = await memfs.remove_file("/testdir/hello.txt")
        print("Removed /testdir/hello.txt:", removed_file)

        removed_dir = await memfs.rmdir("/testdir")
        print("Removed /testdir:", removed_dir)

        # Create directory "/testdir" and write a file inside it.
        mkdir_result = await memfs.mkdir("/testdir")
        print("Created /testdir:", mkdir_result)
        write_result = await memfs.write_file("/testdir/hello.txt", "Hello, World!")
        print("Wrote /testdir/hello.txt:", write_result)
        listing = await memfs.list_dir("/testdir", recursive=False)
        print("Listing of /testdir:", listing)

        # Use the copy command to copy "/testdir" to "/copydir".
        cp_result = await memfs.copy("/testdir", "/copydir")
        print("Copy result:", cp_result)
        copied_listing = await memfs.list_dir("/copydir", recursive=True)
        print("Recursive listing of /copydir:", copied_listing)

        # Clean up by removing the files and directories.
        await memfs.remove_file("/testdir/hello.txt")
        await memfs.rmdir("/testdir")
        await memfs.remove_file("/copydir/hello.txt")
        await memfs.rmdir("/copydir")

        source_path = "/source.txt"
        dest_path = "/dest.txt"
        content = "This is a test file for copying."

        # Write the source file.
        write_ok = await memfs.write_file(source_path, content)
        print("Write result:", write_ok, "\nContent:", content, "\nPath:", source_path)

        copy_result = await memfs.copy(source_path, dest_path)
        print("Copy result:", copy_result)

        copied_content = await memfs.read_file(dest_path)
        print("Copied content:", copied_content)

        file_path = "/append.txt"
        initial_content = "Hello"
        appended_content = ", World!"

        write_ok = await memfs.write_file(file_path, initial_content, append=False)
        print("Write result:", write_ok)

        append_ok = await memfs.write_file(file_path, appended_content, append=True)
        print("Append result:", append_ok)

        final_content = await memfs.read_file(file_path)
        expected = initial_content + appended_content
        print("Final content:", final_content, "\nExpected:", expected)

        await memfs.remove_file(file_path)

        await browser.close()

# Run the example if this module is executed directly.
if __name__ == "__main__":
    asyncio.run(main())
