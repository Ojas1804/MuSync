"""Shared utilities for MuSync: constants, networking, time sync, player."""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import sounddevice as sd
from zeroconf import IPVersion, ServiceListener


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTROL_PORT = 51900   # TCP, JSON line-delimited control messages
TIMESYNC_PORT = 51901  # UDP, NTP-style clock offset
AUDIO_PORT = 51902     # TCP, int16 PCM stream (host -> peers)
SERVICE_TYPE = "_musync._tcp.local."

CHUNK_FRAMES = 4096
DEFAULT_LEAD_IN = 3.0
TIMESYNC_SAMPLES = 12


# ---------------------------------------------------------------------------
# Networking helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Time sync (NTP-style 4-timestamp)
# ---------------------------------------------------------------------------

class TimeSyncServer(threading.Thread):
    """Replies to UDP timesync probes. Uses local time.time() as reference."""

    def __init__(self):
        super().__init__(daemon=True)
        self._stop = threading.Event()

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", TIMESYNC_PORT))
        sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                continue
            except OSError:
                break
            t2 = time.time()
            if len(data) != 8:
                continue
            try:
                (t1,) = struct.unpack("!d", data)
            except struct.error:
                continue
            t3 = time.time()
            try:
                sock.sendto(struct.pack("!ddd", t1, t2, t3), addr)
            except OSError:
                pass
        sock.close()

    def stop(self) -> None:
        self._stop.set()


def measure_offset(host_ip: str, samples: int = TIMESYNC_SAMPLES,
                   timeout: float = 1.0) -> Optional[Tuple[float, float]]:
    """Return (rtt, offset) such that host_time ≈ local_time + offset.

    Picks the sample with the smallest round-trip time across `samples`
    probes (best-of-N filtering — common NTP heuristic).
    """
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


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Peer:
    name: str
    node_id: str
    ip: str
    control_port: int = CONTROL_PORT
    room_id: Optional[str] = None  # zeroconf-advertised room membership


@dataclass
class Room:
    """A persistent group of devices that play together.

    `code` is a non-expiring 6-digit join code. Any current member can
    validate it against incoming JOIN_REQUEST messages.
    """
    room_id: str
    code: str
    name: str = ""


@dataclass
class Session:
    session_id: str
    host_id: str
    host_ip: str
    sr: int
    channels: int
    total_frames: int
    start_host_time: float
    title: str
    room_id: str
    player: Optional["SyncPlayer"] = None
    audio_thread: Optional[threading.Thread] = None
    stop_flag: threading.Event = field(default_factory=threading.Event)


# ---------------------------------------------------------------------------
# Peer registry (Zeroconf listener)
# ---------------------------------------------------------------------------

class PeerRegistry(ServiceListener):
    def __init__(self, self_id: str):
        self.self_id = self_id
        self.peers: Dict[str, Peer] = {}
        self._lock = threading.Lock()

    def add_service(self, zc, type_, name):  # noqa: N802
        self._refresh(zc, type_, name)

    def update_service(self, zc, type_, name):  # noqa: N802
        self._refresh(zc, type_, name)

    def remove_service(self, zc, type_, name):  # noqa: N802, ARG002
        with self._lock:
            for nid, p in list(self.peers.items()):
                # zeroconf service name is "<display>-<id>.<SERVICE_TYPE>";
                # match by node_id substring as the safest signal.
                if nid in name:
                    del self.peers[nid]
                    print(f"[discovery] lost {p.name} ({p.ip})")
                    return

    def _refresh(self, zc, type_, name):
        info = zc.get_service_info(type_, name, timeout=1500)
        if not info:
            return
        props = {}
        for k, v in (info.properties or {}).items():
            try:
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
            except UnicodeDecodeError:
                continue
            props[key] = val
        node_id = props.get("id")
        display = props.get("name", name)
        room_id = props.get("room_id") or None
        if not node_id or node_id == self.self_id:
            return
        addrs = info.parsed_addresses(IPVersion.V4Only)
        if not addrs:
            return
        peer = Peer(name=display, node_id=node_id, ip=addrs[0],
                    control_port=info.port or CONTROL_PORT, room_id=room_id)
        with self._lock:
            new = node_id not in self.peers
            old_room = self.peers[node_id].room_id if not new else None
            self.peers[node_id] = peer
        if new:
            tag = f" [room {room_id}]" if room_id else ""
            print(f"[discovery] found {peer.name} @ {peer.ip}{tag}")
        elif old_room != room_id:
            print(f"[discovery] {peer.name} room: {old_room} -> {room_id}")

    def snapshot(self) -> List[Peer]:
        with self._lock:
            return list(self.peers.values())

    def in_room(self, room_id: str) -> List[Peer]:
        with self._lock:
            return [p for p in self.peers.values() if p.room_id == room_id]


# ---------------------------------------------------------------------------
# Synchronized player
# ---------------------------------------------------------------------------

class SyncPlayer:
    """Plays a fixed-length PCM buffer at a host-scheduled start time.

    The buffer is keyed by absolute frame index (0..total_frames). Frames may
    arrive in any order; missing frames render as silence.
    """

    def __init__(self, sr: int, channels: int, total_frames: int,
                 start_host_time: float, offset_to_host: float,
                 on_finished=None):
        self.sr = sr
        self.channels = channels
        self.total = total_frames
        self.start_host = start_host_time
        self.offset = offset_to_host  # host_time = local_time + offset
        self.on_finished = on_finished

        self.buf = np.zeros((total_frames, channels), dtype=np.float32)
        self._lock = threading.Lock()
        self._finished_fired = False

        self.stream = sd.OutputStream(
            samplerate=sr,
            channels=channels,
            dtype="float32",
            callback=self._cb,
            blocksize=0,
            latency="low",
        )

    def write(self, frame_offset: int, samples: np.ndarray) -> None:
        n = samples.shape[0]
        if n == 0 or frame_offset >= self.total:
            return
        end = min(self.total, frame_offset + n)
        with self._lock:
            self.buf[frame_offset:end] = samples[: end - frame_offset]

    def start(self) -> None:
        self.stream.start()

    def stop(self) -> None:
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass

    def _cb(self, outdata, frames, time_info, status):  # noqa: ARG002
        local_now = time.time()
        dac_local = local_now + (time_info.outputBufferDacTime - time_info.currentTime)
        dac_host = dac_local + self.offset
        first_frame = int(round((dac_host - self.start_host) * self.sr))

        outdata.fill(0)
        if first_frame + frames <= 0 or first_frame >= self.total:
            if first_frame >= self.total and not self._finished_fired:
                self._finished_fired = True
                if self.on_finished:
                    threading.Thread(target=self.on_finished, daemon=True).start()
            return

        start = max(0, first_frame)
        end = min(self.total, first_frame + frames)
        out_start = start - first_frame
        out_end = out_start + (end - start)
        with self._lock:
            outdata[out_start:out_end] = self.buf[start:end]
