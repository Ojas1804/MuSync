import threading
from zeroconf import IPVersion, ServiceListener
from utils import CONTROL_PORT
from typing import Dict, List
from Peer import Peer

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
                # zeroconf service name is "<display>-<id>.<SERVICE_TYPE>"
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