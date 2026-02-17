#!/bin/bash
export PLAYWRIGHT_BROWSERS_PATH="/tmp/pw-browsers"

PW_DRIVER=".pythonlibs/lib/python3.11/site-packages/playwright/driver"
if [ ! -f "$PW_DRIVER/node" ]; then
  echo "[startup] Downloading Node.js runtime for Playwright driver..."
  NODE_VERSION="v24.13.0"
  curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz" \
    | tar -xJ --strip-components=2 -C "$PW_DRIVER" "node-${NODE_VERSION}-linux-x64/bin/node"
  chmod +x "$PW_DRIVER/node"
  echo "[startup] Node.js driver ready."
fi

if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-1208" ]; then
  echo "[startup] Installing Playwright Chromium headless shell..."
  playwright install chromium
  rm -rf "$PLAYWRIGHT_BROWSERS_PATH/chromium-1208"
  echo "[startup] Browser installed."
fi

echo "[startup] Starting server..."
exec python main.py
