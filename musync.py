"""
MuSync — synchronized multi-device audio playback over LAN.

This is the entrypoint module: it ties together the host (`host.py`),
client (`client.py`) and shared utility (`utils.py`) layers into a
single `Node`, manages **rooms** (a persistent group of devices joined
by a non-expiring 6-digit code), and exposes a small CLI/REPL.

Run on each device:
    python musync.py --name <DeviceName>

Then in the prompt:
    create-room          # become a room and get a 6-digit join code
    rooms                # list rooms discovered on the network
    join <id> <code>     # join an existing room
    play <file>          # become host, play to all room members
    stop                 # stop the current session
    leave / quit
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

from Node import Node
import sounddevice as sd

HELP = """\
Commands:
  create-room [name]   create a new room and get a 6-digit join code
  rooms                list rooms discovered on the network
  join <id> <code>     join an existing room
  leave                leave the current room
  room                 show the current room and its code
  peers                list discovered devices
  play <file>          become host and play a local audio file to the room
  stop                 stop the current session
  devices              list local audio output devices
  help                 show this help
  quit / exit          shut down
"""
def __is_valid_command__(cmd):
    if cmd not in ("quit", "exit", "help", "create-room", "rooms", "join",
                   "leave", "room", "peers", "play", "stop", "devices"):
        return False
    return True

def repl(node: Node) -> None:
    print(HELP)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        cmd, _, rest = line.partition(" ")
        cmd = cmd.lower()
        if not __is_valid_command__(cmd):
            print(f"unknown command: {cmd}")
            continue

        # if not __is_valid_rest__(rest):
        #     print(f"invalid rest: {rest}")
        #     continue

        if cmd in ("quit", "exit"):
            break
        elif cmd == "help":
            print(HELP)
        elif cmd == "create-room":
            node.create_room(name=rest.strip())
        elif cmd == "rooms":
            rs = node.list_rooms()
            if not rs:
                print("(no rooms discovered)")
            for rid, n, sample in rs:
                print(f"  {rid}   members: {n:2d}   e.g. {sample}")
        elif cmd == "join":
            parts = rest.split()
            if len(parts) != 2:
                print("usage: join <room_id> <code>")
                continue
            node.join_room(parts[0], parts[1])
        elif cmd == "leave":
            node.leave_room()
        elif cmd == "room":
            if node.room:
                print(f"  id:   {node.room.room_id}")
                print(f"  code: {node.room.code}")
                print(f"  name: {node.room.name}")
                members = node.registry.in_room(node.room.room_id)
                print(f"  members ({len(members)} other):")
                for p in members:
                    print(f"    - {p.name} @ {p.ip}")
            else:
                print("(not in a room)")
        elif cmd == "peers":
            peers = node.registry.snapshot()
            if not peers:
                print("(no peers discovered yet)")
            for p in peers:
                tag = f" [room {p.room_id}]" if p.room_id else ""
                print(f"  {p.name:20s} {p.ip}{tag}")
        elif cmd == "devices":
            print(sd.query_devices())
        elif cmd == "play":
            path = rest.strip().strip('"').strip("'")
            if not path:
                print("usage: play <file>")
                continue
            node.play_file(path)
        elif cmd == "stop":
            node.stop_session()
        else:
            print(f"unknown command: {cmd}")

def main() -> int:
    parser = argparse.ArgumentParser(description="MuSync — synced LAN audio")
    parser.add_argument("--name", default=socket.gethostname(),
                        help="display name for this device")
    args = parser.parse_args()

    node = Node(display_name=args.name)
    node.start()
    try:
        repl(node)
    finally:
        node.shutdown()
        time.sleep(0.2)  # let zeroconf deregister
    return 0


if __name__ == "__main__":
    sys.exit(main())
