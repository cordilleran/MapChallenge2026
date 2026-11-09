#!/usr/bin/env bash
# Serve the corpus geography app on localhost and the tailnet only (port 8790), not the LAN.
cd "$(dirname "$0")" || exit 1
PORT=${PORT:-8790}
trap 'kill 0 2>/dev/null' EXIT INT TERM   # stop both servers with the script
TS=$(tailscale ip -4 2>/dev/null | head -1)
python3 -m http.server "$PORT" --bind 127.0.0.1 &
[ -n "$TS" ] && python3 -m http.server "$PORT" --bind "$TS" &
echo "http://localhost:$PORT/  ${TS:+http://$TS:$PORT/}"
wait
