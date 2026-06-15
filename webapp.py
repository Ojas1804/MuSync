from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from Node import Node


AUDIO_EXTENSIONS = {
    ".aiff",
    ".aif",
    ".flac",
    ".oga",
    ".ogg",
    ".wav",
}


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MuSync</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <main class="shell">
    <section class="topbar">
      <div>
        <h1>MuSync</h1>
        <p id="nodeLine">Starting...</p>
      </div>
      <button id="refreshButton" class="icon-button" title="Refresh status">Refresh</button>
    </section>

    <section class="grid">
      <article class="panel">
        <div class="panel-heading">
          <h2>Room</h2>
          <span id="roomBadge" class="badge">No room</span>
        </div>
        <div class="split">
          <label>
            Room name
            <input id="roomName" type="text" placeholder="Living room" />
          </label>
          <button id="createRoomButton">Create</button>
        </div>
        <div class="split">
          <label>
            Room ID
            <input id="joinRoomId" type="text" placeholder="ab12cd34" />
          </label>
          <label>
            Code
            <input id="joinCode" type="text" inputmode="numeric" placeholder="472913" />
          </label>
          <button id="joinRoomButton">Join</button>
        </div>
        <button id="leaveRoomButton" class="quiet">Leave room</button>
      </article>

      <article class="panel">
        <div class="panel-heading">
          <h2>Playback</h2>
          <span id="sessionBadge" class="badge">Idle</span>
        </div>
        <label>
          Music folder on this computer
          <input id="folderInput" type="text" placeholder="C:\\Users\\yoyoo\\Music" />
        </label>
        <div class="actions">
          <button id="scanButton">Scan</button>
          <button id="stopButton" class="danger">Stop</button>
        </div>
        <div id="fileList" class="file-list"></div>
      </article>

      <article class="panel">
        <div class="panel-heading">
          <h2>LAN</h2>
          <span id="peerCount" class="badge">0 peers</span>
        </div>
        <div id="roomList" class="stack"></div>
        <div id="peerList" class="stack muted-list"></div>
      </article>

      <article class="panel">
        <div class="panel-heading">
          <h2>Activity</h2>
        </div>
        <pre id="log"></pre>
      </article>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
"""


STYLES_CSS = """
:root {
  color-scheme: light;
  font-family: "Segoe UI", Arial, sans-serif;
  background: #f5f3ee;
  color: #1f2328;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  background: #f5f3ee;
}

button,
input {
  font: inherit;
}

button {
  border: 0;
  border-radius: 8px;
  background: #22577a;
  color: #fff;
  cursor: pointer;
  min-height: 42px;
  padding: 0 16px;
}

button:hover {
  background: #17415e;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

input {
  width: 100%;
  min-height: 42px;
  border: 1px solid #c8c2b7;
  border-radius: 8px;
  background: #fff;
  color: #1f2328;
  padding: 0 12px;
}

label {
  display: grid;
  gap: 8px;
  color: #555b61;
  font-size: 0.92rem;
  font-weight: 600;
}

.shell {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0;
}

.topbar {
  align-items: center;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 20px;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  font-size: 2.1rem;
  line-height: 1.1;
}

h2 {
  font-size: 1.05rem;
}

.topbar p {
  color: #596069;
  margin-top: 6px;
}

.grid {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
}

.panel {
  background: #fffdfa;
  border: 1px solid #ded8ce;
  border-radius: 8px;
  display: grid;
  gap: 16px;
  padding: 18px;
}

.panel-heading,
.actions,
.split {
  align-items: end;
  display: flex;
  gap: 10px;
}

.panel-heading {
  align-items: center;
  justify-content: space-between;
}

.split label {
  flex: 1;
}

.badge {
  background: #e5efe8;
  border-radius: 999px;
  color: #1c5c3c;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 5px 10px;
}

.quiet {
  background: #e7e1d8;
  color: #28313b;
}

.quiet:hover {
  background: #d8d0c4;
}

.danger {
  background: #b33a3a;
}

.danger:hover {
  background: #882828;
}

.file-list,
.stack {
  display: grid;
  gap: 8px;
}

.file-row,
.list-row {
  align-items: center;
  background: #f7f4ee;
  border: 1px solid #e2dcd2;
  border-radius: 8px;
  display: flex;
  gap: 10px;
  justify-content: space-between;
  min-height: 46px;
  padding: 8px 10px;
}

.file-row span,
.list-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-row button {
  min-height: 34px;
  padding: 0 12px;
}

.muted-list {
  color: #606872;
}

#log {
  background: #20242a;
  border-radius: 8px;
  color: #e9edf2;
  font-family: Consolas, "Courier New", monospace;
  font-size: 0.9rem;
  min-height: 180px;
  margin: 0;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
}

@media (max-width: 760px) {
  .grid,
  .split,
  .topbar {
    display: grid;
    grid-template-columns: 1fr;
  }

  .panel-heading,
  .actions {
    align-items: stretch;
  }
}
"""


APP_JS = """
const els = {
  createRoomButton: document.querySelector("#createRoomButton"),
  fileList: document.querySelector("#fileList"),
  folderInput: document.querySelector("#folderInput"),
  joinCode: document.querySelector("#joinCode"),
  joinRoomButton: document.querySelector("#joinRoomButton"),
  joinRoomId: document.querySelector("#joinRoomId"),
  leaveRoomButton: document.querySelector("#leaveRoomButton"),
  log: document.querySelector("#log"),
  nodeLine: document.querySelector("#nodeLine"),
  peerCount: document.querySelector("#peerCount"),
  peerList: document.querySelector("#peerList"),
  refreshButton: document.querySelector("#refreshButton"),
  roomBadge: document.querySelector("#roomBadge"),
  roomList: document.querySelector("#roomList"),
  roomName: document.querySelector("#roomName"),
  scanButton: document.querySelector("#scanButton"),
  sessionBadge: document.querySelector("#sessionBadge"),
  stopButton: document.querySelector("#stopButton"),
};

function log(message) {
  const timestamp = new Date().toLocaleTimeString();
  els.log.textContent += `[${timestamp}] ${message}\\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function row(text, extra = "") {
  const div = document.createElement("div");
  div.className = "list-row";
  const span = document.createElement("span");
  span.textContent = text;
  div.append(span);
  if (extra) {
    const small = document.createElement("small");
    small.textContent = extra;
    div.append(small);
  }
  return div;
}

async function refreshStatus() {
  const status = await api("/api/status");
  els.nodeLine.textContent = `${status.name} at ${status.ip}:${status.web_port}`;
  els.roomBadge.textContent = status.room
    ? `${status.room.name || "Room"} · ${status.room.room_id} · code ${status.room.code}`
    : "No room";
  els.sessionBadge.textContent = status.session
    ? `Playing ${status.session.title}`
    : "Idle";
  els.peerCount.textContent = `${status.peers.length} peer${status.peers.length === 1 ? "" : "s"}`;

  els.roomList.replaceChildren();
  if (status.rooms.length === 0) {
    els.roomList.append(row("No rooms discovered"));
  } else {
    status.rooms.forEach((room) => {
      els.roomList.append(row(room.room_id, `${room.member_count} member(s), e.g. ${room.sample_member}`));
    });
  }

  els.peerList.replaceChildren();
  if (status.peers.length === 0) {
    els.peerList.append(row("No peers discovered"));
  } else {
    status.peers.forEach((peer) => {
      els.peerList.append(row(peer.name, `${peer.ip}${peer.room_id ? ` · room ${peer.room_id}` : ""}`));
    });
  }
}

async function createRoom() {
  const payload = await api("/api/rooms/create", {
    method: "POST",
    body: JSON.stringify({name: els.roomName.value.trim()}),
  });
  log(`Created room ${payload.room.room_id} with code ${payload.room.code}`);
  await refreshStatus();
}

async function joinRoom() {
  await api("/api/rooms/join", {
    method: "POST",
    body: JSON.stringify({
      room_id: els.joinRoomId.value.trim(),
      code: els.joinCode.value.trim(),
    }),
  });
  log(`Joined room ${els.joinRoomId.value.trim()}`);
  await refreshStatus();
}

async function leaveRoom() {
  await api("/api/rooms/leave", {method: "POST", body: "{}"});
  log("Left room");
  await refreshStatus();
}

async function scanFolder() {
  els.fileList.replaceChildren();
  const folder = els.folderInput.value.trim();
  const payload = await api(`/api/files?folder=${encodeURIComponent(folder)}`);
  if (payload.files.length === 0) {
    els.fileList.append(row("No supported audio files found"));
    return;
  }
  payload.files.forEach((file) => {
    const div = document.createElement("div");
    div.className = "file-row";
    const span = document.createElement("span");
    span.textContent = file.name;
    span.title = file.path;
    const button = document.createElement("button");
    button.textContent = "Play";
    button.addEventListener("click", () => playFile(file.path));
    div.append(span, button);
    els.fileList.append(div);
  });
  log(`Found ${payload.files.length} audio file(s)`);
}

async function playFile(path) {
  await api("/api/play", {
    method: "POST",
    body: JSON.stringify({path}),
  });
  log(`Playback requested: ${path}`);
  await refreshStatus();
}

async function stopPlayback() {
  await api("/api/stop", {method: "POST", body: "{}"});
  log("Stop requested");
  await refreshStatus();
}

async function run(action) {
  try {
    await action();
  } catch (error) {
    log(error.message);
  }
}

els.createRoomButton.addEventListener("click", () => run(createRoom));
els.joinRoomButton.addEventListener("click", () => run(joinRoom));
els.leaveRoomButton.addEventListener("click", () => run(leaveRoom));
els.refreshButton.addEventListener("click", () => run(refreshStatus));
els.scanButton.addEventListener("click", () => run(scanFolder));
els.stopButton.addEventListener("click", () => run(stopPlayback));

run(refreshStatus);
setInterval(() => run(refreshStatus), 3000);

// ── Browser Audio (Web Audio API + SSE) ────────────────────────────────────
// Mobile browsers (especially iOS Safari) block AudioContext until a user
// gesture. We show a banner that must be tapped; this also handles joining
// a track that is already mid-play when the page first opens.

let _audioCtx = null;
let _clockOffset = 0;      // host_seconds - browser_seconds
let _currentSource = null;
let _audioUnlocked = false;

// ── Inject "tap to enable" banner ──
(function () {
  const b = document.createElement("div");
  b.id = "mu-audio-banner";
  b.textContent = "\uD83D\uDD0A Tap here to enable audio on this device";
  b.style.cssText = [
    "position:fixed", "top:0", "left:0", "right:0", "z-index:9999",
    "background:#1565c0", "color:#fff", "padding:14px 16px",
    "text-align:center", "font-size:16px", "font-weight:bold",
    "cursor:pointer", "user-select:none",
  ].join(";");
  document.body.appendChild(b);
})();

function _ensureCtx() {
  if (!_audioCtx) {
    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (_audioCtx.state === "suspended") _audioCtx.resume();
  return _audioCtx;
}

function _unlockAudio() {
  _ensureCtx();
  if (!_audioUnlocked) {
    _audioUnlocked = true;
    const b = document.getElementById("mu-audio-banner");
    if (b) b.style.display = "none";
    log("[audio] audio enabled on this device");
    run(_joinCurrentSession);  // catch up if a session is already playing
  }
}

document.addEventListener("click", _unlockAudio, {capture: true});

async function _syncClock() {
  let best = {rtt: Infinity, offset: 0};
  for (let i = 0; i < 8; i++) {
    const t1 = Date.now();
    try {
      const r = await fetch("/api/timesync", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({t1}),
      });
      const t4 = Date.now();
      const {t2, t3} = await r.json();
      const rtt = (t4 - t1) - (t3 - t2);
      if (rtt < best.rtt && rtt >= 0) {
        best = {rtt, offset: ((t2 - t1) + (t3 - t4)) / 2};
      }
    } catch (_) {}
    await new Promise(res => setTimeout(res, 40));
  }
  _clockOffset = best.offset / 1000;
}

function _stopBrowserAudio() {
  if (_currentSource) {
    try { _currentSource.stop(); } catch (_) {}
    try { _currentSource.disconnect(); } catch (_) {}
    _currentSource = null;
  }
}

async function _startBrowserAudio(msg) {
  if (!_audioUnlocked) {
    log("[audio] tap the blue banner at the top to enable audio, then play again");
    return;
  }
  _stopBrowserAudio();
  try {
    await _syncClock();
    const ctx = _ensureCtx();

    const resp = await fetch("/audio/" + msg.session_id);
    if (!resp.ok) { log("[audio] could not download audio (" + resp.status + ")"); return; }
    const arrayBuf = await resp.arrayBuffer();
    const audioBuf = await ctx.decodeAudioData(arrayBuf);

    const hostNow = Date.now() / 1000 + _clockOffset;
    const delay = msg.start_host_time - hostNow;

    _currentSource = ctx.createBufferSource();
    _currentSource.buffer = audioBuf;
    _currentSource.connect(ctx.destination);

    if (delay > 0.05) {
      // Still ahead of start time — schedule normally
      _currentSource.start(ctx.currentTime + delay);
      log("[audio] '" + msg.title + "' starts in " + delay.toFixed(2) + "s");
    } else {
      // Start time already passed — jump to the correct position in the track
      const elapsed = Math.min(-delay, audioBuf.duration - 0.1);
      if (elapsed >= 0) {
        _currentSource.start(ctx.currentTime + 0.05, elapsed);
        log("[audio] joining '" + msg.title + "' at " + elapsed.toFixed(1) + "s (late join)");
      } else {
        log("[audio] track already finished");
      }
    }
  } catch (err) {
    log("[audio] error: " + err.message);
  }
}

async function _joinCurrentSession() {
  try {
    const status = await api("/api/status");
    if (status && status.session && status.session.session_id
        && typeof status.session.start_host_time === "number") {
      await _startBrowserAudio({
        session_id: status.session.session_id,
        start_host_time: status.session.start_host_time,
        title: status.session.title || "",
      });
    }
  } catch (_) {}
}

function _subscribeEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "SESSION_START") run(() => _startBrowserAudio(msg));
    if (msg.type === "SESSION_STOP")  _stopBrowserAudio();
  };
  es.onerror = () => setTimeout(_subscribeEvents, 3000);
}

_subscribeEvents();
"""


class MuSyncWebApp:
    def __init__(self, node: Node, port: int):
        self.node = node
        self.port = port
        self.lock = threading.Lock()
        self._sse_lock = threading.Lock()
        self._sse_clients: list = []
        self._session_audio: dict = {}

    def status(self) -> dict[str, Any]:
        peers = [
            {
                "id": p.node_id,
                "name": p.name,
                "ip": p.ip,
                "room_id": p.room_id,
                "control_port": p.control_port,
            }
            for p in self.node.registry.snapshot()
        ]
        rooms = [
            {"room_id": rid, "member_count": count, "sample_member": sample}
            for rid, count, sample in self.node.list_rooms()
        ]
        session = None
        if self.node.session:
            session = {
                "session_id": self.node.session.session_id,
                "title": self.node.session.title,
                "host_id": self.node.session.host_id,
                "room_id": self.node.session.room_id,
                "start_host_time": self.node.session.start_host_time,
            }
        room = None
        if self.node.room:
            room = {
                "room_id": self.node.room.room_id,
                "code": self.node.room.code,
                "name": self.node.room.name,
            }
        return {
            "ok": True,
            "id": self.node.node_id,
            "name": self.node.display_name,
            "ip": self.node.local_ip,
            "web_port": self.port,
            "room": room,
            "rooms": rooms,
            "peers": peers,
            "session": session,
        }

    def create_room(self, name: str = "") -> dict[str, Any]:
        with self.lock:
            room = self.node.create_room(name=name)
        return {
            "ok": True,
            "room": {"room_id": room.room_id, "code": room.code, "name": room.name},
        }

    def join_room(self, room_id: str, code: str) -> dict[str, Any]:
        if not room_id or not code:
            raise ValueError("Room ID and code are required")
        with self.lock:
            joined = self.node.join_room(room_id, code)
        if not joined:
            raise RuntimeError("Could not join that room")
        return {"ok": True}

    def leave_room(self) -> dict[str, Any]:
        with self.lock:
            self.node.leave_room()
        return {"ok": True}

    def play(self, path: str) -> dict[str, Any]:
        audio_path = Path(path).expanduser()
        if not audio_path.is_file():
            raise ValueError("Audio file does not exist")
        if audio_path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError("Unsupported audio file type")
        with self.lock:
            self.node.play_file(str(audio_path))
        sess = self.node.session
        if sess:
            self._session_audio[sess.session_id] = str(audio_path)
            self._push_sse({
                "type": "SESSION_START",
                "session_id": sess.session_id,
                "start_host_time": sess.start_host_time,
                "title": sess.title,
            })
        return {"ok": True}

    def stop(self) -> dict[str, Any]:
        with self.lock:
            self.node.stop_session()
        self._push_sse({"type": "SESSION_STOP"})
        return {"ok": True}

    def list_files(self, folder: str) -> dict[str, Any]:
        root = Path(folder).expanduser()
        if not root.is_dir():
            raise ValueError("Folder does not exist on the MuSync host computer")
        files = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                files.append({"name": path.name, "path": str(path)})
        return {"ok": True, "folder": str(root), "files": files[:500]}

    def _push_sse(self, event: dict) -> None:
        data = json.dumps(event)
        with self._sse_lock:
            dead = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(data)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)

    def timesync(self, t1_ms: float) -> dict[str, Any]:
        t2 = time.time() * 1000
        t3 = time.time() * 1000
        return {"ok": True, "t1": t1_ms, "t2": t2, "t3": t3}

    def audio_data(self, session_id: str):
        path = self._session_audio.get(session_id)
        if not path or not Path(path).is_file():
            raise FileNotFoundError("Audio not available for this session")
        data = Path(path).read_bytes()
        suffix = Path(path).suffix.lower()
        mime = {
            ".wav": "audio/wav", ".flac": "audio/flac",
            ".ogg": "audio/ogg", ".oga": "audio/ogg",
            ".aiff": "audio/aiff", ".aif": "audio/aiff",
        }.get(suffix, "application/octet-stream")
        return mime, data


def make_handler(app: MuSyncWebApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MuSyncWeb/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[web] {self.address_string()} - {fmt % args}")

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            try:
                if parsed.path == "/":
                    self._send_text(INDEX_HTML, "text/html; charset=utf-8")
                elif parsed.path == "/static/styles.css":
                    self._send_text(STYLES_CSS, "text/css; charset=utf-8")
                elif parsed.path == "/static/app.js":
                    self._send_text(APP_JS, "text/javascript; charset=utf-8")
                elif parsed.path == "/api/status":
                    self._send_json(app.status())
                elif parsed.path == "/api/files":
                    query = urllib.parse.parse_qs(parsed.query)
                    folder = query.get("folder", [""])[0]
                    self._send_json(app.list_files(folder))
                elif parsed.path == "/api/events":
                    self._handle_sse(app)
                elif parsed.path.startswith("/audio/"):
                    session_id = parsed.path[len("/audio/"):]
                    mime, data = app.audio_data(session_id)
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)
            except Exception as exc:
                self._send_error(exc)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            body = self._read_json()
            try:
                if parsed.path == "/api/rooms/create":
                    self._send_json(app.create_room(body.get("name", "")))
                elif parsed.path == "/api/rooms/join":
                    self._send_json(app.join_room(body.get("room_id", ""), body.get("code", "")))
                elif parsed.path == "/api/rooms/leave":
                    self._send_json(app.leave_room())
                elif parsed.path == "/api/play":
                    self._send_json(app.play(body.get("path", "")))
                elif parsed.path == "/api/stop":
                    self._send_json(app.stop())
                elif parsed.path == "/api/timesync":
                    self._send_json(app.timesync(body.get("t1", 0)))
                else:
                    self.send_error(404)
            except Exception as exc:
                self._send_error(exc)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def _send_text(self, content: str, content_type: str) -> None:
            payload = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_error(self, exc: Exception) -> None:
            self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_sse(self, app) -> None:
            q: queue.Queue = queue.Queue()
            with app._sse_lock:
                app._sse_clients.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    try:
                        data = q.get(timeout=15)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with app._sse_lock:
                    try:
                        app._sse_clients.remove(q)
                    except ValueError:
                        pass

    return Handler


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> int:
    parser = argparse.ArgumentParser(description="MuSync LAN web controller")
    parser.add_argument("--name", default=socket.gethostname(), help="display name for this device")
    parser.add_argument("--host", default="0.0.0.0", help="web server bind host")
    parser.add_argument("--port", type=int, default=8080, help="web server port")
    args = parser.parse_args()

    node = Node(display_name=args.name)
    node.start()

    app = MuSyncWebApp(node=node, port=args.port)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))

    lan_ip = get_lan_ip()
    print(f"[web] open locally: http://127.0.0.1:{args.port}")
    print(f"[web] open on LAN: http://{lan_ip}:{args.port}")
    print("[web] press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        node.shutdown()
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
