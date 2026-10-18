#!/usr/bin/env bash
# GroveTheft — RAGE Engine Local Server & Browser Launcher
set -e

PORT=${1:-9127}
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== GroveTheft Launch Controller ==="
echo "Port: $PORT"
echo "Directory: $DIR"

# Check if server is already running on this port
if lsof -i :$PORT >/dev/null 2>&1; then
    echo "GroveTheft server is already running on port $PORT."
else
    echo "Starting GroveTheft server on port $PORT with data mirroring..."
    python3 "$DIR/server.py" "$PORT" --mirror-data &
    SERVER_PID=$!
    sleep 1
    echo "Server running (PID: $SERVER_PID)."
fi

echo "To play, open http://localhost:$PORT/ in Brave or Chrome."
