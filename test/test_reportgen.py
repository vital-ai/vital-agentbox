"""
Test Tier 3 host-delegated command: reportgen

Tests argument validation, LaTeX security scanning, file resolution,
and (if pandoc is installed) actual PDF generation.
"""

import asyncio
import shutil
from playwright.async_api import async_playwright
from agentbox.box.memfs.memfs import MemFS
from agentbox.box.shell import ShellExecutor


PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js"


async def setup():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(f'data:text/html,<script src="{PYODIDE_CDN}"></script>')
    await page.evaluate("async () => { window.pyodide = await loadPyodide(); }")
    memfs = MemFS(page)
    executor = ShellExecutor(memfs)
    return pw, browser, executor, memfs


async def main():
    passed = 0
    failed = 0
    pw, browser, executor, memfs = await setup()

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            if detail:
                print(f"      {detail}")

    async def run(cmd):
        return await executor.run(cmd)

    print("=" * 60)
    print("TEST: reportgen (Tier 3 host-delegated command)")
    print("=" * 60)

    # --- Argument validation ---
    print("\n--- argument validation ---")

    r = await run("reportgen")
    check("no args → error", r.exit_code == 1)
    check("no args stderr", "no input files" in r.stderr)

    r = await run("reportgen /doc.md")
    check("no output → error", r.exit_code == 1)
    check("no output stderr", "--output is required" in r.stderr)

    r = await run("reportgen /doc.md -o /out.txt")
    check("non-pdf output → error", r.exit_code == 1)
    check("non-pdf stderr", ".pdf" in r.stderr)

    r = await run("reportgen /doc.md -o /out.pdf --filter dangerous")
    check("unknown flag → error", r.exit_code == 1)
    check("unknown flag stderr", "unknown option: --filter" in r.stderr)

    r = await run("reportgen /doc.md -o /out.pdf --toc-depth 9")
    check("toc-depth out of range", r.exit_code == 1)
    check("toc-depth stderr", "1-6" in r.stderr)

    r = await run("reportgen /doc.md -o /out.pdf --highlight-style evil")
    check("bad highlight style", r.exit_code == 1)
    check("bad highlight stderr", "unknown highlight style" in r.stderr)

    # --- File not found ---
    print("\n--- file resolution ---")

    r = await run("reportgen /nonexistent.md -o /out.pdf")
    check("missing file → error", r.exit_code == 1)
    check("missing file stderr", "No such file" in r.stderr)

    # --- LaTeX security scanning ---
    print("\n--- LaTeX security scan ---")

    # Create a file with blocked LaTeX pattern
    await memfs.write_file("/unsafe.md", "# Title\n\nSome text with \\write18{rm -rf /}\n")
    r = await run("reportgen /unsafe.md -o /out.pdf")
    check("write18 blocked", r.exit_code == 1)
    check("write18 stderr", "blocked unsafe LaTeX" in r.stderr and "write18" in r.stderr)

    await memfs.write_file("/unsafe2.md", "# Title\n\n\\directlua{os.execute('id')}\n")
    r = await run("reportgen /unsafe2.md -o /out.pdf")
    check("directlua blocked", r.exit_code == 1)
    check("directlua stderr", "directlua" in r.stderr)

    await memfs.write_file("/unsafe3.tex", "\\usepackage{bashful}\n\\begin{document}\\end{document}\n")
    await memfs.write_file("/safe.md", "# Safe doc\n\nJust text.\n")
    r = await run("reportgen /safe.md -o /out.pdf --template /unsafe3.tex")
    check("template scan blocks bashful", r.exit_code == 1)
    check("template scan stderr", "bashful" in r.stderr)

    # Safe content should pass scan
    await memfs.write_file("/clean.md", "# Clean\n\nSafe markdown content.\n")

    # --- Glob resolution ---
    print("\n--- glob resolution ---")

    await memfs.mkdir_p("/chapters")
    await memfs.write_file("/chapters/ch1.md", "# Chapter 1\n\nFirst.\n")
    await memfs.write_file("/chapters/ch2.md", "# Chapter 2\n\nSecond.\n")

    # Test glob with no pandoc available — still validates args and scans
    r = await run("reportgen /chapters/nonexistent_*.md -o /out.pdf")
    check("glob no match → error", r.exit_code == 1)
    check("glob no match stderr", "no files match" in r.stderr)

    # --- Actual pandoc execution (skip if pandoc not installed) ---
    has_pandoc = shutil.which("pandoc") is not None

    if has_pandoc:
        print("\n--- pandoc execution ---")
        r = await run("reportgen /clean.md -o /report.pdf")
        check("reportgen success", r.exit_code == 0, r.stderr)
        check("stdout has output path", "/report.pdf" in r.stdout)

        # Verify PDF exists in MemFS
        exists = await memfs.exists("/report.pdf")
        check("PDF exists in MemFS", exists)

        if exists:
            stat = await memfs.stat("/report.pdf")
            check("PDF has non-zero size", stat and stat.get("size", 0) > 0,
                  f"stat: {stat}")

        # With glob
        r = await run('reportgen /chapters/ch1.md /chapters/ch2.md -o /multi.pdf --title "Test Report"')
        check("multi-file reportgen", r.exit_code == 0, r.stderr)

        # With toc
        r = await run("reportgen /clean.md -o /toc.pdf --toc")
        check("reportgen with --toc", r.exit_code == 0, r.stderr)
    else:
        print("\n--- pandoc not installed, skipping execution tests ---")
        print("  (install pandoc to run full reportgen tests)")

    await browser.close()
    await pw.stop()

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    if not has_pandoc:
        print("  (pandoc not installed — execution tests skipped)")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
