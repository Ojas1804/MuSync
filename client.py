from __future__ import annotations

import socket
import struct
import threading
import numpy as np
from Session import Session
from SyncPlayer import SyncPlayer
from utils import (
    AUDIO_PORT,
    measure_offset,
    recv_exact,
)


class ClientMixin:
    def _handle_session_start(self, msg: dict, src_ip: str) -> None:
        try:
            sid = msg["session_id"]
            host_id = msg["host_id"]
            sr = int(msg["sample_rate"])
            channels = int(msg["channels"])
            total = int(msg["total_frames"])
            start_host = float(msg["start_host_time"])
            title = msg.get("title", "")
            audio_port = int(msg.get("audio_port", AUDIO_PORT))
            room_id = msg.get("room_id")
        except (KeyError, ValueError, TypeError) as e:
            print(f"[session] malformed SESSION_START: {e}")
            return
        # Reject sessions from outside our room.
        room = getattr(self, "room", None)
        if not room or room_id != room.room_id:
            print(f"[session] ignoring SESSION_START from {src_ip} "
                  f"(room mismatch: {room_id})")
            return

        # Tear down any existing session first.
        with self._session_lock:
            if self.session:
                self._teardown_session_locked()

        host_ip = msg.get("host_ip") or src_ip
        print(f"[session] joining '{title}' from {host_ip} "
              f"({sr}Hz x{channels}, {total/sr:.1f}s)")
        meas = measure_offset(host_ip)
        if meas is None:
            print("[session] could not measure clock offset; aborting")
            return
        rtt, offset = meas
        print(f"[timesync] rtt={rtt*1000:.1f}ms offset={offset*1000:.1f}ms")

        sess = Session(
            session_id=sid, host_id=host_id, host_ip=host_ip,
            sr=sr, channels=channels, total_frames=total,
            start_host_time=start_host, title=title, room_id=room_id,
        )
        sess.player = SyncPlayer(
            sr=sr, channels=channels, total_frames=total,
            start_host_time=start_host, offset_to_host=offset,
            on_finished=self._on_playback_finished,
        )
        with self._session_lock:
            self.session = sess
        sess.player.start()
        t = threading.Thread(
            target=self._audio_receive_loop,
            args=(sess, host_ip, audio_port),
            daemon=True,
        )
        sess.audio_thread = t
        t.start()
    
    def _audio_receive_loop(self, sess: Session, host_ip: str,
                            audio_port: int) -> None:
        try:
            with socket.create_connection((host_ip, audio_port), timeout=5.0) as s:
                s.sendall(struct.pack("!I", len(sess.session_id))
                          + sess.session_id.encode())
                while not sess.stop_flag.is_set():
                    header = recv_exact(s, 12)
                    if header is None:
                        break
                    frame_offset, num_frames = struct.unpack("!QI", header)
                    if num_frames == 0:
                        break  # end-of-stream marker
                    nbytes = num_frames * sess.channels * 2  # int16
                    payload = recv_exact(s, nbytes)
                    if payload is None:
                        break
                    samples = np.frombuffer(payload, dtype="<i2").reshape(
                        num_frames, sess.channels)
                    samples_f = samples.astype(np.float32) / 32768.0
                    if sess.player:
                        sess.player.write(int(frame_offset), samples_f)
        except OSError as e:
            print(f"[audio] receiver error: {e}")
        finally:
            print("[audio] stream closed")

    def _on_playback_finished(self) -> None:
        with self._session_lock:
            if self.session:
                print(f"[session] '{self.session.title}' finished")
                self._teardown_session_locked()
