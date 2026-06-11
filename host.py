"""Host-side behaviour: loading audio, announcing a session, streaming PCM."""

from __future__ import annotations

import socket
import struct
import threading
import time
import traceback
import uuid
from typing import Optional

import numpy as np
import soundfile as sf

from Session import Session
from SyncPlayer import SyncPlayer
from utils import (
    AUDIO_PORT,
    CHUNK_FRAMES,
    DEFAULT_LEAD_IN,
    recv_exact,
)


class HostMixin:
    """Mixin providing host-role behaviour for `Node`.

    The owning `Node` must provide:
      - self.node_id, self.local_ip, self.display_name
      - self._session_lock, self.session, self._teardown_session_locked()
      - self.room (Optional[Room])
      - self.registry (PeerRegistry)
      - self._send_to_peer(peer, msg) -> bool
      - self._on_playback_finished()
    """
    _audio_listener: Optional[socket.socket] = None
    _audio_listener_thread: Optional[threading.Thread] = None
    _audio_data: Optional[np.ndarray] = None  # int16 [N, ch], pre-quantized

    def play_file(self, path: str, lead_in: float = DEFAULT_LEAD_IN) -> None:
        if not getattr(self, "room", None):
            print("[host] you must create or join a room first "
                  "(use `create-room` or `join <id> <code>`)")
            return

        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as e:
            print(f"[host] failed to load '{path}': {e}")
            return

        channels = data.shape[1]
        total = data.shape[0]
        title = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        sid = uuid.uuid4().hex[:12]
        with self._session_lock:
            if self.session:
                self._teardown_session_locked()

        start_host = time.time() + lead_in
        room_peers = self.registry.in_room(self.room.room_id)

        sess = Session(
            session_id=sid, host_id=self.node_id, host_ip=self.local_ip,
            sr=sr, channels=channels, total_frames=total,
            start_host_time=start_host, title=title,
            room_id=self.room.room_id,
        )
        with self._session_lock:
            self.session = sess

        self._start_audio_listener(sid, total, channels, sr, data)

        msg = {
            "type": "SESSION_START",
            "session_id": sid,
            "host_id": self.node_id,
            "host_ip": self.local_ip,
            "sample_rate": sr,
            "channels": channels,
            "total_frames": total,
            "start_host_time": start_host,
            "title": title,
            "audio_port": AUDIO_PORT,
            "room_id": self.room.room_id,
        }
        if not room_peers:
            print("[host] warning: no peers in room registry yet; SESSION_START not sent. " +
                  "Ensure the peer has joined and Zeroconf has propagated (~2s).")
        for p in room_peers:
            self._send_to_peer(p, msg)

        # Local playback (offset = 0 since we are the host).
        sess.player = SyncPlayer(
            sr=sr, channels=channels, total_frames=total,
            start_host_time=start_host, offset_to_host=0.0,
            on_finished=self._on_playback_finished,
        )
        sess.player.write(0, data)  # host already has the whole buffer
        sess.player.start()
        print(f"[host] playing '{title}' to {len(room_peers)} peer(s); "
              f"start in {lead_in:.1f}s")
    
    def _start_audio_listener(self, session_id: str, total: int,
                              channels: int, sr: int, data: np.ndarray) -> None:
        # Pre-quantize float32 -> int16 once for streaming.
        i16 = np.clip(data, -1.0, 1.0)
        self._audio_data = (i16 * 32767.0).astype("<i2")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", AUDIO_PORT))
        sock.listen(16)
        sock.settimeout(0.5)
        self._audio_listener = sock

        def loop():
            while True:
                with self._session_lock:
                    if not self.session or self.session.session_id != session_id:
                        return
                try:
                    client, addr = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                threading.Thread(
                    target=self._serve_audio_client,
                    args=(client, addr, session_id, total, channels, sr),
                    daemon=True,
                ).start()

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        self._audio_listener_thread = t

    def _serve_audio_client(self, client: socket.socket, addr,
                            session_id: str, total: int,
                            channels: int, sr: int) -> None:
        try:
            client.settimeout(5.0)
            hdr = recv_exact(client, 4)
            if hdr is None:
                return
            (slen,) = struct.unpack("!I", hdr)
            sid_bytes = recv_exact(client, slen)
            if sid_bytes is None or sid_bytes.decode(errors="ignore") != session_id:
                return
            client.settimeout(None)
            print(f"[host] peer connected for audio: {addr[0]}")

            data = self._audio_data
            if data is None:
                return
            offset = 0
            while offset < total:
                with self._session_lock:
                    if not self.session or self.session.session_id != session_id:
                        return
                n = min(CHUNK_FRAMES, total - offset)
                chunk = data[offset:offset + n]
                header = struct.pack("!QI", offset, n)
                try:
                    client.sendall(header + chunk.tobytes())
                except OSError:
                    return
                offset += n
            try:
                client.sendall(struct.pack("!QI", total, 0))  # EOS
            except OSError:
                pass
        except Exception:
            traceback.print_exc()
        finally:
            try:
                client.close()
            except Exception:
                pass
    
    def _close_host_audio(self) -> None:
        """Called by Node._teardown_session_locked when the local node is host."""
        sock = self._audio_listener
        self._audio_listener = None
        self._audio_data = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
