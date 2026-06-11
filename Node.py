from client import ClientMixin
from host import HostMixin
from utils import (
    CONTROL_PORT,
    SERVICE_TYPE,
    get_local_ip,
    recv_json_lines,
    request_response,
    send_json,
)
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
from typing import Optional
import random
import threading
import uuid
import socket

from TimeSyncServer import TimeSyncServer
from PeerRegistry import PeerRegistry
from Peer import Peer
from Room import Room
from Session import Session

class Node(HostMixin, ClientMixin):
    def __init__(self, display_name: str):
        self.node_id = uuid.uuid4().hex[:12]
        self.display_name = display_name
        self.local_ip = get_local_ip()

        self.zc = Zeroconf()
        self.registry = PeerRegistry(self.node_id)
        self._service_info: Optional[ServiceInfo] = None
        self._browser: Optional[ServiceBrowser] = None

        self._timesync = TimeSyncServer()
        self._control_sock: Optional[socket.socket] = None
        self._control_thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()

        # Room + session state.
        self.room: Optional[Room] = None
        self._session_lock = threading.Lock()
        self.session: Optional[Session] = None

    def start(self) -> None:
        self._timesync.start()
        self._start_control_server()
        self._register_zeroconf()
        self._browser = ServiceBrowser(self.zc, SERVICE_TYPE, self.registry)
        print(f"[node] {self.display_name} ({self.node_id}) up at {self.local_ip}")

    def shutdown(self) -> None:
        self._stopping.set()
        self.stop_session()
        try:
            if self._service_info:
                self.zc.unregister_service(self._service_info)
        except Exception:
            pass
        try:
            self.zc.close()
        except Exception:
            pass
        self._timesync.stop()
        if self._control_sock:
            try:
                self._control_sock.close()
            except Exception:
                pass

    #  zeroconf 
    def _zeroconf_properties(self) -> dict:
        props = {"id": self.node_id, "name": self.display_name}
        if self.room:
            props["room_id"] = self.room.room_id
            if self.room.name:
                props["room_name"] = self.room.name
        return props

    def _register_zeroconf(self) -> None:
        info = ServiceInfo(
            SERVICE_TYPE,
            f"{self.display_name}-{self.node_id}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(self.local_ip)],
            port=CONTROL_PORT,
            properties=self._zeroconf_properties(),
            server=f"{self.node_id}.local.",
        )
        self.zc.register_service(info)
        self._service_info = info

    def _republish_zeroconf(self) -> None:
        """Update our Zeroconf TXT (e.g. after creating/joining/leaving a room)."""
        if not self._service_info:
            return
        new_info = ServiceInfo(
            SERVICE_TYPE,
            self._service_info.name,
            addresses=[socket.inet_aton(self.local_ip)],
            port=CONTROL_PORT,
            properties=self._zeroconf_properties(),
            server=self._service_info.server,
        )
        try:
            self.zc.update_service(new_info)
            self._service_info = new_info
        except Exception as e:
            print(f"[discovery] failed to republish: {e}")

    # control plane 
    def _start_control_server(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", CONTROL_PORT))
        sock.listen(8)
        self._control_sock = sock

        def loop():
            while not self._stopping.is_set():
                try:
                    client, addr = sock.accept()
                except OSError:
                    return
                threading.Thread(
                    target=self._handle_control_client,
                    args=(client, addr),
                    daemon=True,
                ).start()

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        self._control_thread = t

    def _handle_control_client(self, client: socket.socket, addr) -> None:
        try:
            for msg in recv_json_lines(client):
                reply = self._on_control_msg(msg, addr[0])
                if reply is not None:
                    try:
                        send_json(client, reply)
                    except OSError:
                        break
        except OSError:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _on_control_msg(self, msg: dict, src_ip: str) -> Optional[dict]:
        kind = msg.get("type")
        if kind == "SESSION_START":
            self._handle_session_start(msg, src_ip)
            return None
        if kind == "SESSION_STOP":
            sid = msg.get("session_id")
            with self._session_lock:
                if self.session and (sid is None or self.session.session_id == sid):
                    print("[session] stop requested by host")
                    self._teardown_session_locked()
            return None
        if kind == "JOIN_REQUEST":
            return self._handle_join_request(msg, src_ip)
        return None

    def _send_to_peer(self, peer: Peer, msg: dict) -> bool:
        try:
            with socket.create_connection((peer.ip, peer.control_port),
                                          timeout=2.0) as s:
                send_json(s, msg)
            return True
        except OSError as e:
            print(f"[net] failed to reach {peer.name}: {e}")
            return False

    # session teardown
    def _teardown_session_locked(self) -> None:
        sess = self.session
        if not sess:
            return
        sess.stop_flag.set()
        if sess.player:
            sess.player.stop()
        # Host-side audio listener cleanup (no-op for non-hosts).
        if sess.host_id == self.node_id:
            self._close_host_audio()
        self.session = None

    def stop_session(self) -> None:
        was_host = False
        sid = None
        with self._session_lock:
            if self.session:
                was_host = self.session.host_id == self.node_id
                sid = self.session.session_id
                self._teardown_session_locked()
        if was_host and self.room:
            for p in self.registry.in_room(self.room.room_id):
                self._send_to_peer(p, {"type": "SESSION_STOP", "session_id": sid})

    # rooms
    @staticmethod
    def _gen_code() -> str:
        return f"{random.randint(0, 999_999):06d}"

    def create_room(self, name: str = "") -> Room:
        if self.room:
            print(f"[room] already in room {self.room.room_id} "
                  f"(code {self.room.code}); leave first")
            return self.room
        room = Room(
            room_id=uuid.uuid4().hex[:8],
            code=self._gen_code(),
            name=name or f"{self.display_name}'s room",
        )
        self.room = room
        self._republish_zeroconf()
        print(f"[room] created '{room.name}'  id={room.room_id}  "
              f"code={room.code}  (share this code to invite devices)")
        return room

    def leave_room(self) -> None:
        if not self.room:
            print("[room] not in a room")
            return
        # Tear down any active session we were part of.
        self.stop_session()
        rid = self.room.room_id
        self.room = None
        self._republish_zeroconf()
        print(f"[room] left {rid}")

    def list_rooms(self) -> list:
        """Return a list of (room_id, member_count, sample_member_name)."""
        rooms: dict[str, list[Peer]] = {}
        for p in self.registry.snapshot():
            if p.room_id:
                rooms.setdefault(p.room_id, []).append(p)
        out = []
        for rid, members in rooms.items():
            out.append((rid, len(members), members[0].name))
        return out

    def join_room(self, room_id: str, code: str) -> bool:
        if self.room and self.room.room_id == room_id:
            print(f"[room] already in {room_id}")
            return True
        members = self.registry.in_room(room_id)
        if not members:
            print(f"[room] no peers found in room {room_id}; "
                  "make sure the host is online and discovered")
            return False

        msg = {
            "type": "JOIN_REQUEST",
            "room_id": room_id,
            "code": code,
            "node_id": self.node_id,
            "name": self.display_name,
        }
        for peer in members:
            reply = request_response(peer.ip, peer.control_port, msg, timeout=3.0)
            if reply is None:
                continue
            if reply.get("ok"):
                # We're in. If we were in a different room, leave it first.
                if self.room and self.room.room_id != room_id:
                    self.stop_session()
                self.room = Room(
                    room_id=room_id,
                    code=code,
                    name=reply.get("room_name", ""),
                )
                self._republish_zeroconf()
                print(f"[room] joined {room_id} via {peer.name}")
                return True
            else:
                print(f"[room] {peer.name} denied join: "
                      f"{reply.get('reason', 'unknown')}")
                return False
        print(f"[room] no member of {room_id} responded")
        return False

    def _handle_join_request(self, msg: dict, src_ip: str) -> dict:
        rid = msg.get("room_id")
        code = msg.get("code")
        who = msg.get("name", src_ip)
        joining_id = msg.get("node_id")
        if not self.room or self.room.room_id != rid:
            return {"ok": False, "reason": "not a member of that room"}
        if code != self.room.code:
            print(f"[room] denied join from {who}: bad code")
            return {"ok": False, "reason": "invalid code"}
        print(f"[room] approved join from {who} ({src_ip})")
        if joining_id:
            self.registry.set_room(joining_id, rid)
        return {"ok": True, "room_name": self.room.name}
