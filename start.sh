#!/bin/bash
export PLAYWRIGHT_BROWSERS_PATH="/tmp/pw-browsers"

if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-1208" ]; then
  echo "[startup] Installing Playwright Chromium headless shell..."
  playwright install chromium
  rm -rf "$PLAYWRIGHT_BROWSERS_PATH/chromium-1208"
  echo "[startup] Browser installed, starting server..."
else
  echo "[startup] Browser already installed, starting server..."
fi
exec python main.py
