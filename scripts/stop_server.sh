#!/usr/bin/env bash
[ -f /tmp/webui.pid ] && kill "$(cat /tmp/webui.pid)" 2>/dev/null
rm -f /tmp/webui.pid
