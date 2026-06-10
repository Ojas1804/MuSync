from dataclasses import dataclass
from utils import CONTROL_PORT
from typing import Optional

@dataclass
class Peer:
    name: str
    node_id: str
    ip: str
    control_port: int = CONTROL_PORT
    room_id: Optional[str] = None