#!/usr/bin/env bash
# Start the packaged HEXRDGUI with its launcher and check that it is still
# running after WAIT_SECS (i.e., it did not crash on startup).
#
# Usage: smoke_test_launcher.sh <launcher_path> [wait_secs=30]
set -uo pipefail

LAUNCHER="${1:?usage: $0 <launcher_path> [wait_secs]}"
WAIT_SECS="${2:-30}"
LOG="$(mktemp)"

# Log to a file so a leftover process can't hold this step's output open
"$LAUNCHER" --ignore-settings > "$LOG" 2>&1 &
PID=$!
sleep "$WAIT_SECS"

if kill -0 "$PID" 2>/dev/null; then
  echo "OK: hexrdgui is running after ${WAIT_SECS}s"
  if [ -r "/proc/$PID/winpid" ]; then
    # Windows: the launcher .exe runs python.exe as a child, so kill the tree
    taskkill //F //T //PID "$(cat "/proc/$PID/winpid")" > /dev/null
  else
    kill "$PID"
  fi
  STATUS=0
else
  wait "$PID"
  echo "FAIL: hexrdgui exited early with code $?"
  STATUS=1
fi

echo "--- hexrdgui output ---"
cat "$LOG"
exit "$STATUS"
