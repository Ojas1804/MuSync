"""Shared utilities for MuSync: constants, networking, time sync, player."""

from __future__ import annotations

import json
import socket
import struct
import time
from typing import Optional, Tuple


CONTROL_PORT = 51900   # TCP, JSON line-delimited control messages
TIMESYNC_PORT = 51901  # UDP, NTP-style clock offset
AUDIO_PORT = 51902     # TCP, int16 PCM stream (host -> peers)
SERVICE_TYPE = "_musync._tcp.local."

CHUNK_FRAMES = 4096
DEFAULT_LEAD_IN = 3.0
TIMESYNC_SAMPLES = 12

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

def send_json(sock: socket.socket, msg: dict) -> None:
    data = (json.dumps(msg) + "\n").encode("utf-8")
    sock.sendall(data)

def recv_json_lines(sock: socket.socket):
    """Generator yielding JSON messages from a line-delimited TCP stream."""
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)

def request_response(ip: str, port: int, msg: dict, timeout: float = 3.0) -> Optional[dict]:
    """Open a TCP connection, send one JSON message, read one JSON reply."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            send_json(s, msg)
            s.settimeout(timeout)
            for reply in recv_json_lines(s):
                return reply
    except OSError:
        return None
    return None

def measure_offset(host_ip: str, samples: int = TIMESYNC_SAMPLES,
                   timeout: float = 1.0) -> Optional[Tuple[float, float]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    best: Optional[Tuple[float, float]] = None
    try:
        for _ in range(samples):
            t1 = time.time()
            try:
                sock.sendto(struct.pack("!d", t1), (host_ip, TIMESYNC_PORT))
                data, _ = sock.recvfrom(64)
            except OSError:
                continue
            t4 = time.time()
            if len(data) != 24:
                continue
            try:
                _t1, t2, t3 = struct.unpack("!ddd", data)
            except struct.error:
                continue
            rtt = (t4 - t1) - (t3 - t2)
            if rtt < 0:
                continue
            offset = ((t2 - t1) + (t3 - t4)) / 2.0
            if best is None or rtt < best[0]:
                best = (rtt, offset)
            time.sleep(0.03)
    finally:
        sock.close()
    return best