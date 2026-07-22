#!/usr/bin/env bash
cd "$(dirname "$0")/.."
nohup .venv/bin/python -m uvicorn tokenmaxxr.serve:app --host 127.0.0.1 --port 8765 >/tmp/webui.log 2>&1 &
echo $! > /tmp/webui.pid
disown
