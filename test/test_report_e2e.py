"""
End-to-end test: CSV → numpy analysis → matplotlib chart → markdown → reportgen → PDF

This test runs entirely inside a CodeExecutorBox sandbox (Chromium + Pyodide).
It exercises:
  1. Writing a CSV file to MemFS
  2. Running Python (Pyodide) to read CSV with numpy, generate a matplotlib chart PNG
  3. Writing a Markdown report referencing the chart image
  4. Running reportgen (Tier 3) to produce a PDF via pandoc + LaTeX
  5. Extracting all artifacts (CSV, PNG, MD, PDF) to test_reportgen/ on host

Requires: pandoc + LaTeX installed on host (Dockerfile.worker has them).
Run:  python test/test_report_e2e.py
"""

import asyncio
import os
import shutil
import base64

from agentbox.box.code_exec_box import CodeExecutorBox


OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test_reportgen",
)


async def main():
    print("=" * 60)
    print("E2E: CSV → numpy → matplotlib → markdown → reportgen → PDF")
    print("=" * 60)

    # Ensure output dir exists and is clean
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)

    box = CodeExecutorBox(timeout=120)
    await box.start()

    try:
        # ------------------------------------------------------------------
        # Step 1: Write CSV data into sandbox
        # ------------------------------------------------------------------
        print("\n[1/6] Writing CSV data to sandbox...")
        r = await box.run_shell("""mkdir -p /data && cat << 'EOF' > /data/sales.csv
month,revenue,expenses
Jan,12000,8500
Feb,15000,9200
Mar,18000,10100
Apr,16500,9800
May,21000,11500
Jun,24000,12800
Jul,22500,12200
Aug,26000,13500
Sep,28000,14200
Oct,25000,13000
Nov,30000,15500
Dec,35000,17000
EOF""")
        assert r["exit_code"] == 0, f"CSV write failed: {r['stderr']}"
        print("  ✓ /data/sales.csv written")

        # ------------------------------------------------------------------
        # Step 1b: Install numpy and matplotlib via pip (micropip)
        # ------------------------------------------------------------------
        print("\n[1b]  Installing numpy + matplotlib via pip...")
        r = await box.run_shell("pip install numpy matplotlib")
        assert r["exit_code"] == 0, f"pip install failed: {r['stderr']}"
        print("  ✓ numpy + matplotlib installed")

        # ------------------------------------------------------------------
        # Step 2: Analyze data with numpy in Pyodide
        # ------------------------------------------------------------------
        print("\n[2/6] Analyzing data with numpy...")
        r = await box.run_code("""
import csv
import numpy as np

with open('/data/sales.csv') as f:
    reader = csv.DictReader(f)
    data = list(reader)

months = [row['month'] for row in data]
revenue = np.array([float(row['revenue']) for row in data])
expenses = np.array([float(row['expenses']) for row in data])
profit = revenue - expenses

print(f"Revenue:  mean=${revenue.mean():,.0f}  total=${revenue.sum():,.0f}")
print(f"Expenses: mean=${expenses.mean():,.0f}  total=${expenses.sum():,.0f}")
print(f"Profit:   mean=${profit.mean():,.0f}  total=${profit.sum():,.0f}")
print(f"Best month: {months[np.argmax(revenue)]} (${revenue.max():,.0f})")
print(f"Growth: {((revenue[-1] - revenue[0]) / revenue[0] * 100):.1f}%")
""")
        assert r["exit_code"] == 0, f"numpy analysis failed: {r['stderr']}"
        print(f"  ✓ Analysis complete:")
        for line in r["stdout"].strip().split("\n"):
            print(f"    {line}")

        # ------------------------------------------------------------------
        # Step 3: Generate chart with matplotlib
        # ------------------------------------------------------------------
        print("\n[3/6] Generating chart with matplotlib...")
        r = await box.run_code("""
import csv
import numpy as np
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt

with open('/data/sales.csv') as f:
    reader = csv.DictReader(f)
    data = list(reader)

months = [row['month'] for row in data]
revenue = np.array([float(row['revenue']) for row in data])
expenses = np.array([float(row['expenses']) for row in data])
profit = revenue - expenses

x = np.arange(len(months))
width = 0.35

fig, ax = plt.subplots(figsize=(10, 6))
bars1 = ax.bar(x - width/2, revenue, width, label='Revenue', color='#2196F3')
bars2 = ax.bar(x + width/2, expenses, width, label='Expenses', color='#FF5722')
ax.plot(x, profit, 'g-o', linewidth=2, markersize=6, label='Profit', color='#4CAF50')

ax.set_xlabel('Month')
ax.set_ylabel('Amount ($)')
ax.set_title('Monthly Revenue, Expenses & Profit — 2025')
ax.set_xticks(x)
ax.set_xticklabels(months)
ax.legend()
ax.grid(axis='y', alpha=0.3)

# Format y-axis with dollar signs
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'${v:,.0f}'))

plt.tight_layout()
plt.savefig('/data/chart.png', dpi=150)
plt.close()
print("Chart saved to /data/chart.png")
""")
        assert r["exit_code"] == 0, f"matplotlib chart failed: {r['stderr']}"
        print(f"  ✓ {r['stdout'].strip()}")

        # ------------------------------------------------------------------
        # Step 4: Write Markdown report referencing the chart
        # ------------------------------------------------------------------
        print("\n[4/6] Writing Markdown report...")
        r = await box.run_shell("""cat << 'MDEOF' > /data/report.md
# Annual Sales Report — 2025

## Executive Summary

This report presents monthly revenue, expenses, and profit data for the
fiscal year 2025. Overall performance shows strong growth with revenue
increasing 191.7% from January to December.

## Financial Overview

![Monthly Revenue, Expenses & Profit](chart.png)

## Key Metrics

| Metric | Value |
|--------|-------|
| Total Revenue | \\$273,000 |
| Total Expenses | \\$147,300 |
| Total Profit | \\$125,700 |
| Average Monthly Revenue | \\$22,750 |
| Best Month | December (\\$35,000) |
| YoY Growth | 191.7% |

## Monthly Breakdown

| Month | Revenue | Expenses | Profit |
|-------|---------|----------|--------|
| Jan | \\$12,000 | \\$8,500 | \\$3,500 |
| Feb | \\$15,000 | \\$9,200 | \\$5,800 |
| Mar | \\$18,000 | \\$10,100 | \\$7,900 |
| Apr | \\$16,500 | \\$9,800 | \\$6,700 |
| May | \\$21,000 | \\$11,500 | \\$9,500 |
| Jun | \\$24,000 | \\$12,800 | \\$11,200 |
| Jul | \\$22,500 | \\$12,200 | \\$10,300 |
| Aug | \\$26,000 | \\$13,500 | \\$12,500 |
| Sep | \\$28,000 | \\$14,200 | \\$13,800 |
| Oct | \\$25,000 | \\$13,000 | \\$12,000 |
| Nov | \\$30,000 | \\$15,500 | \\$14,500 |
| Dec | \\$35,000 | \\$17,000 | \\$18,000 |

## Conclusion

The company demonstrated consistent growth throughout 2025, with
particularly strong performance in Q4. Profit margins remained healthy,
averaging 46% across all months.
MDEOF""")
        assert r["exit_code"] == 0, f"Markdown write failed: {r['stderr']}"
        print("  ✓ /data/report.md written")

        # ------------------------------------------------------------------
        # Step 5: Run reportgen to produce PDF
        # ------------------------------------------------------------------
        print("\n[5/6] Running reportgen (pandoc + LaTeX)...")

        has_pandoc = shutil.which("pandoc") is not None
        if not has_pandoc:
            print("  ⚠ pandoc not installed — skipping PDF generation")
            print("    Install with: brew install pandoc && brew install --cask mactex")
        else:
            r = await box.run_shell(
                'reportgen /data/report.md -o /data/report.pdf '
                '--title "Annual Sales Report" '
                '--author "AgentBox Analytics" '
                '--date "2025-12-31" '
                '--toc'
            )
            if r["exit_code"] == 0:
                print(f"  ✓ {r['stdout'].strip()}")
            else:
                print(f"  ✗ reportgen failed (exit {r['exit_code']}):")
                for line in r["stderr"].strip().split("\n"):
                    print(f"    {line}")

        # ------------------------------------------------------------------
        # Step 6: Extract artifacts from sandbox to host
        # ------------------------------------------------------------------
        print(f"\n[6/6] Extracting artifacts to {OUTPUT_DIR}/")

        artifacts = [
            ("/data/sales.csv", "sales.csv", False),
            ("/data/report.md", "report.md", False),
            ("/data/chart.png", "chart.png", True),
        ]
        if has_pandoc:
            artifacts.append(("/data/report.pdf", "report.pdf", True))

        for memfs_path, filename, is_binary in artifacts:
            if is_binary:
                data = await box.memfs.read_file_binary(memfs_path)
                if data:
                    host_path = os.path.join(OUTPUT_DIR, filename)
                    with open(host_path, "wb") as f:
                        f.write(data)
                    print(f"  ✓ {filename} ({len(data):,} bytes)")
                else:
                    print(f"  ✗ {filename} — not found in sandbox")
            else:
                content = await box.memfs.read_file(memfs_path)
                if content:
                    host_path = os.path.join(OUTPUT_DIR, filename)
                    with open(host_path, "w") as f:
                        f.write(content)
                    print(f"  ✓ {filename} ({len(content):,} bytes)")
                else:
                    print(f"  ✗ {filename} — not found in sandbox")

        print("\n" + "=" * 60)
        print(f"Done. Artifacts in: {OUTPUT_DIR}/")
        print("=" * 60)

    finally:
        await box.stop()


if __name__ == "__main__":
    asyncio.run(main())
