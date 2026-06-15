#!/usr/bin/env bash
# Navigate to the directory containing this script
cd "$(dirname "$0")"

PORT=8080
NAME="${COMPUTERNAME:-$(hostname)}"

# Detect LAN IP
LAN_IP=$(python -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "127.0.0.1")

echo ""
echo "  MuSync Web App"
echo "  =================================="
echo "  This PC : http://127.0.0.1:$PORT"
echo "  Phone   : http://$LAN_IP:$PORT"
echo "  =================================="
echo "  Open the Phone URL in your browser"
echo "  (phone must be on the same Wi-Fi)"
echo "  Press Ctrl+C to stop."
echo ""

python webapp.py --name "$NAME" --port "$PORT"
