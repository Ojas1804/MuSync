import threading
import socket
from utils import TIMESYNC_PORT
import time
import struct

class TimeSyncServer(threading.Thread):
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
            # send t1, t2, and t3 to client to sync wrt t2-t1 (offset) and t3-t1 (roundtrip)
            try:
                sock.sendto(struct.pack("!ddd", t1, t2, t3), addr)
            except OSError:
                pass
        sock.close()

    def stop(self) -> None:
        self._stop.set()