#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PORT=8080
NAME="${COMPUTERNAME:-$(hostname)}"

# Resolve LAN IP using Python (same method the app uses internally)
LAN_IP=$(python -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    print('127.0.0.1')
" 2>/dev/null)

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║              MuSync Web App              ║"
echo "  ╠══════════════════════════════════════════╣"
echo "  ║  Open on this PC  : http://127.0.0.1:$PORT ║"
echo "  ║  Open on phone    : http://$LAN_IP:$PORT    ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  On your phone: connect to the same Wi-Fi,"
echo "  then open the URL above in your browser."
echo ""
echo "  Press Ctrl+C to stop."
echo ""

python webapp.py --name "$NAME" --port "$PORT"
