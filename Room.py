from dataclasses import dataclass

@dataclass
class Room:
    room_id: str
    code: str
    name: str = ""