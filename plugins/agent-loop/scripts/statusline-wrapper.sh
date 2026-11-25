#!/bin/sh
# Saves the status line input (it carries plan rate limits) for report.py, then runs
# the real status line command given as arguments.
# Usage in settings.json: sh /path/to/statusline-wrapper.sh <your existing statusLine command>
input=$(cat)
out="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agent-loop-statusline.json"
printf '%s' "$input" > "$out.tmp" && mv "$out.tmp" "$out"
[ $# -gt 0 ] && printf '%s' "$input" | "$@"
