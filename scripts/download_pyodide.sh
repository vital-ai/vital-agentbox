#!/usr/bin/env bash
# Download the Pyodide distribution for local bundling.
# Usage: ./scripts/download_pyodide.sh [version]
#
# Downloads to pyodide-bundle/ in the project root.
# In Docker, set AGENTBOX_PYODIDE_URL=http://localhost:8000/static/pyodide/pyodide.js

set -euo pipefail

VERSION="${1:-0.29.3}"
DEST="pyodide-bundle"
URL="https://github.com/pyodide/pyodide/releases/download/${VERSION}/pyodide-${VERSION}.tar.bz2"

echo "Downloading Pyodide v${VERSION}..."

rm -rf "${DEST}"
mkdir -p "${DEST}"

curl -L "${URL}" | tar xj -C "${DEST}" --strip-components=1

# Remove packages we don't need to shrink the bundle
# Keep only the core runtime files
echo "Cleaning up unnecessary packages..."
find "${DEST}" -name "*.tar" -delete 2>/dev/null || true

SIZE=$(du -sh "${DEST}" | cut -f1)
echo "Pyodide v${VERSION} downloaded to ${DEST}/ (${SIZE})"
echo ""
echo "To use locally, set:"
echo "  export AGENTBOX_PYODIDE_URL=http://localhost:8000/static/pyodide/pyodide.js"
