import threading
import numpy as np
import time
import sounddevice as sd

class SyncPlayer:
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