#!/bin/bash
set -e

echo "=== AgentBox Worker ==="
echo "Date: $(date)"
echo "Python: $(python --version 2>&1)"
echo "MAX_SESSIONS: ${MAX_SESSIONS:-3}"
echo ""

# Start Xvfb (required for Camoufox which runs in non-headless mode)
echo "=== Starting Xvfb ==="
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
XVFB_PID=$!
sleep 2
if kill -0 $XVFB_PID 2>/dev/null; then
  echo "Xvfb OK (PID $XVFB_PID)"
else
  echo "Xvfb FAILED to start"
  exit 1
fi
export DISPLAY=:99
echo ""

# Quick Chrome sanity check
echo "=== Chrome sanity check ==="
if command -v google-chrome &>/dev/null; then
  echo "Chrome: $(google-chrome --version 2>&1)"
  timeout 10 google-chrome --no-sandbox --disable-gpu --disable-dev-shm-usage \
    --headless=new --dump-dom about:blank > /dev/null 2>&1 && echo "Chrome OK" || echo "Chrome check failed (non-fatal)"
else
  echo "Chrome not installed (using Playwright Chromium)"
fi
echo ""

# Start FastAPI worker
echo "=== Starting Worker ==="
exec uvicorn agentbox.api.app:app --host 0.0.0.0 --port 8000 --log-level info
