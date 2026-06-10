from dataclasses import dataclass, field
from typing import Optional
from SyncPlayer import SyncPlayer
import threading

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