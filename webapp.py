"""MuSync Web Interface — rewritten for reliable phone playback over LAN.

Run on the laptop that has the music:
    python webapp.py --name MyLaptop --folder /path/to/music

Then open the printed URL on any phone/browser on the same Wi-Fi.
The laptop auto-creates a room; CLI peers can join with the displayed code.
Phone browsers just open the page, tap the banner once, and hear the music.
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from Node import Node

# ── Audio format support ──────────────────────────────────────────────────────

# Extensions listed in the UI and served to browsers.
# MP3/M4A are included: the browser decodes them natively, and the Node's
# host.py converts them to WAV for local sounddevice playback automatically.
AUDIO_EXTENSIONS = {".aiff", ".aif", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".wav"}

MIME_TYPES: dict[str, str] = {
    ".mp3":  "audio/mpeg",
    ".m4a":  "audio/mp4",
    ".wav":  "audio/wav",
    ".flac": "audio/flac",
    ".ogg":  "audio/ogg",
    ".oga":  "audio/ogg",
    ".aiff": "audio/aiff",
    ".aif":  "audio/aiff",
}

# ── Embedded front-end ────────────────────────────────────────────────────────

INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MuSync</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>

  <!-- Sticky banner — must be tapped on iOS/Android before audio can play -->
  <div id="audioBanner" class="audio-banner">
    🔊 Tap here to enable audio on this device
  </div>

  <div class="container">
    <header class="app-header">
      <div>
        <h1>🎵 MuSync</h1>
        <div id="deviceInfo" class="device-info">Connecting…</div>
      </div>
      <button class="btn btn-ghost" onclick="refreshUI()" title="Refresh">↻</button>
    </header>

    <!-- Room info: shows code that CLI peers use to join -->
    <section class="card">
      <div class="card-title">Room</div>
      <div id="roomInfo" class="room-info">Creating room…</div>
      <div id="peerList" class="peer-list"></div>
    </section>

    <!-- Now Playing: shown only when a session is active -->
    <section class="card now-playing hidden" id="nowPlaying">
      <div class="card-title">Now Playing</div>
      <div id="npTrack" class="np-track">—</div>
      <div class="np-actions">
        <div id="npStatus" class="np-status"></div>
        <button class="btn btn-danger" onclick="stopPlayback()">⏹ Stop</button>
      </div>
    </section>

    <!-- Music library -->
    <section class="card">
      <div class="card-header">
        <div class="card-title">Music Library</div>
        <div class="scan-controls">
          <input id="folderInput" class="folder-input" type="text"
                 placeholder="Folder path (on the host computer)"
                 onkeydown="if(event.key==='Enter') scanFolder()">
          <button class="btn" onclick="scanFolder()">Scan</button>
        </div>
      </div>
      <div id="fileList" class="file-list">
        <div class="empty-state">
          Enter a folder path and click <strong>Scan</strong>,<br>
          or start the server with <code>--folder /path/to/music</code>
        </div>
      </div>
    </section>

    <!-- Log -->
    <section class="card">
      <div class="card-title">Log</div>
      <pre id="log" class="log"></pre>
    </section>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
"""

STYLES_CSS = """\
:root {
  --bg:         #0d1117;
  --surface:    #161b22;
  --surface2:   #1c2128;
  --border:     #30363d;
  --accent:     #388bfd;
  --accent-h:   #2f74d0;
  --danger:     #da3633;
  --danger-h:   #b72e2e;
  --text:       #e6edf3;
  --text-muted: #7d8590;
  --green:      #3fb950;
  --radius:     10px;
}

*, *::before, *::after { box-sizing: border-box; }

html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 15px;
  line-height: 1.6;
}

.container {
  max-width: 700px;
  margin: 0 auto;
  padding: 16px 16px 48px;
  display: grid;
  gap: 14px;
}

/* ── Header ── */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 4px;
}
h1 { font-size: 1.45rem; margin: 0; }
.device-info { font-size: 0.8rem; color: var(--text-muted); margin-top: 2px; }

/* ── Cards ── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  display: grid;
  gap: 12px;
}
.card-title {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
}
.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
  flex-wrap: wrap;
}

/* ── Room ── */
.room-info { font-size: 0.95rem; word-break: break-all; }
.room-info .code {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 10px;
  font-family: "SF Mono", Consolas, monospace;
  font-size: 1.15em;
  color: var(--accent);
  letter-spacing: 0.1em;
}
.peer-list { display: grid; gap: 5px; }
.peer-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: var(--text-muted);
}
.peer-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
}

/* ── Now Playing ── */
.now-playing { border-color: var(--accent); }
.now-playing.hidden { display: none; }
.np-track { font-size: 1.05rem; font-weight: 600; word-break: break-word; }
.np-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.np-status { font-size: 0.85rem; color: var(--text-muted); }

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 9px 16px;
  font: 600 0.9rem/1 inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s;
  -webkit-tap-highlight-color: transparent;
}
.btn:hover  { background: var(--accent-h); }
.btn:active { opacity: 0.8; }
.btn-danger { background: var(--danger); }
.btn-danger:hover { background: var(--danger-h); }
.btn-ghost  {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 1.1rem;
  padding: 6px 10px;
}
.btn-ghost:hover { background: var(--surface2); }
.btn-sm     { padding: 6px 11px; font-size: 0.82rem; }

/* ── Scan controls ── */
.scan-controls { display: flex; gap: 8px; flex: 1; min-width: 0; }
.folder-input {
  flex: 1; min-width: 0;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font: inherit;
  padding: 7px 12px;
}
.folder-input::placeholder { color: var(--text-muted); }
.folder-input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }

/* ── File list ── */
.file-list {
  display: grid;
  gap: 6px;
  max-height: 380px;
  overflow-y: auto;
}
.file-list::-webkit-scrollbar { width: 4px; }
.file-list::-webkit-scrollbar-track { background: transparent; }
.file-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 99px; }

.file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 12px;
  transition: border-color 0.15s;
}
.file-row.playing { border-color: var(--accent); background: rgba(56,139,253,0.07); }
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9rem;
}

.empty-state {
  text-align: center;
  color: var(--text-muted);
  padding: 28px 12px;
  font-size: 0.9rem;
  line-height: 1.8;
}
.empty-state code {
  background: var(--bg);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: monospace;
  color: var(--accent);
}

/* ── Log ── */
.log {
  background: var(--bg);
  border-radius: 8px;
  color: #58a6ff;
  font-family: "SF Mono", Consolas, "Courier New", monospace;
  font-size: 0.78rem;
  line-height: 1.65;
  max-height: 180px;
  overflow-y: auto;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}
.log::-webkit-scrollbar { width: 4px; }
.log::-webkit-scrollbar-track { background: transparent; }
.log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 99px; }

/* ── Audio banner ── */
.audio-banner {
  position: sticky;
  top: 0;
  z-index: 999;
  background: #1565c0;
  color: #fff;
  text-align: center;
  padding: 14px 16px;
  font-weight: 700;
  font-size: 1rem;
  cursor: pointer;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.audio-banner.hidden { display: none; }

/* ── Responsive ── */
@media (max-width: 500px) {
  .card-header  { flex-direction: column; align-items: stretch; }
  .scan-controls { flex-direction: column; }
  .np-actions   { flex-direction: column; align-items: flex-start; }
}
"""

APP_JS = """\
// ── State ────────────────────────────────────────────────────────────────────
let audioUnlocked  = false;
let currentAudio   = null;   // HTMLAudioElement currently playing
let currentSession = null;   // {session_id, start_host_time, title}
let clockOffsetSec = 0;      // (host_time_seconds) - (Date.now()/1000)
let _autoScanned   = false;  // only auto-scan the folder once on first load

// ── Logging ───────────────────────────────────────────────────────────────────
const logEl = document.getElementById('log');
function log(msg) {
  const ts = new Date().toLocaleTimeString();
  logEl.textContent += '[' + ts + '] ' + msg + '\\n';
  logEl.scrollTop = logEl.scrollHeight;
}

// ── HTML escape ───────────────────────────────────────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Fetch/API helper ──────────────────────────────────────────────────────────
async function api(path, opts) {
  const r = await fetch(path, {
    headers: {'Content-Type': 'application/json'},
    ...opts,
  });
  const d = await r.json();
  if (!r.ok || d.ok === false) throw new Error(d.error || 'Request failed');
  return d;
}

// ── Audio unlock (iOS / Android autoplay policy) ──────────────────────────────
// Any interaction unlocks; banner is there to prompt the tap.
const banner = document.getElementById('audioBanner');
banner.addEventListener('click', _doUnlock);
document.addEventListener('pointerdown', _doUnlock, {passive: true});

function _doUnlock() {
  if (audioUnlocked) return;
  audioUnlocked = true;
  banner.classList.add('hidden');
  log('Audio enabled on this device');
  // If a session is already running when the user first taps, join it.
  api('/api/status').then(s => {
    if (s && s.session) _startAudio(s.session);
  }).catch(() => {});
}

// ── NTP-style clock sync ──────────────────────────────────────────────────────
// Estimates the offset so we can schedule audio relative to the host clock.
async function syncClock() {
  const samples = [];
  for (let i = 0; i < 6; i++) {
    const t1 = Date.now();
    try {
      const r = await fetch('/api/timesync', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({t1}),
      });
      const t4 = Date.now();
      const {t2, t3} = await r.json();
      samples.push(((t2 - t1) + (t3 - t4)) / 2 / 1000); // seconds
    } catch (_) {}
    if (i < 5) await _sleep(25);
  }
  if (samples.length > 0) {
    samples.sort((a, b) => a - b);
    clockOffsetSec = samples[Math.floor(samples.length / 2)];
    log('Clock offset: ' + (clockOffsetSec * 1000).toFixed(1) + ' ms');
  }
}

function _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Browser audio playback via HTML5 <audio> ──────────────────────────────────
// Why <audio> instead of Web Audio API:
//   - Streaming: no need to buffer the entire file before playback starts
//   - HTTP Range requests allow seeking to the right position for late joins
//   - Works with all formats the browser supports natively (MP3, AAC, OGG…)
async function _startAudio(session) {
  if (!audioUnlocked) {
    log('Tap the blue banner to enable audio, then the track will start');
    return;
  }
  // Already playing this exact session
  if (currentSession && currentSession.session_id === session.session_id) return;

  _stopAudio();
  currentSession = session;
  _updateNowPlaying(session, 'Syncing clock…');

  await syncClock();

  const audio = new Audio();
  // Add a cache-buster so browser doesn't serve a stale cached partial response
  audio.src = '/audio/' + session.session_id + '?_=' + Date.now();
  audio.preload = 'auto';

  audio.addEventListener('error', () => {
    const e = audio.error;
    log('[audio] load error ' + (e ? e.code + ': ' + e.message : ''));
  });

  // 'canplay' fires when the browser has buffered enough to start
  audio.addEventListener('canplay', () => {
    if (!currentSession || currentSession.session_id !== session.session_id) return;

    const hostNow = Date.now() / 1000 + clockOffsetSec;
    const elapsed = hostNow - session.start_host_time;

    if (elapsed < -0.2) {
      // Track hasn't started yet — wait, then play from the beginning
      const waitMs = (-elapsed - 0.1) * 1000;
      log('"' + session.title + '" starts in ' + (-elapsed).toFixed(1) + 's');
      _updateNowPlaying(session, 'Starting in ' + (-elapsed).toFixed(0) + 's…');
      setTimeout(() => {
        if (!currentSession || currentSession.session_id !== session.session_id) return;
        audio.play().catch(e => log('[audio] play() failed: ' + e.message));
        _updateNowPlaying(session, 'Playing');
      }, Math.max(0, waitMs));

    } else if (elapsed < audio.duration - 0.5) {
      // Late join — seek into the track to stay in sync
      const target = Math.min(elapsed + 0.15, audio.duration - 0.1);
      audio.currentTime = target;
      audio.play().catch(e => log('[audio] play() failed: ' + e.message));
      log('Joined "' + session.title + '" at ' + elapsed.toFixed(1) + 's');
      _updateNowPlaying(session, 'Playing');

    } else {
      log('"' + session.title + '" has already finished');
      _clearNowPlaying();
    }
  }, {once: true});

  currentAudio = audio;
  audio.load();
}

function _stopAudio() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.removeAttribute('src');
    currentAudio.load(); // abort pending network requests
    currentAudio = null;
  }
  currentSession = null;
}

// ── Server-Sent Events (real-time session notifications) ──────────────────────
function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'SESSION_START') {
        _updateNowPlaying(msg, 'Starting…');
        _startAudio(msg);
      } else if (msg.type === 'SESSION_STOP') {
        _stopAudio();
        _clearNowPlaying();
        log('Playback stopped');
      }
    } catch (_) {}
  };
  es.onerror = () => setTimeout(connectEvents, 3000);
}

// ── UI: Now Playing ───────────────────────────────────────────────────────────
function _updateNowPlaying(session, statusText) {
  document.getElementById('npTrack').textContent  = session.title || '(unknown)';
  document.getElementById('npStatus').textContent = statusText || '';
  document.getElementById('nowPlaying').classList.remove('hidden');
  // Highlight the active row in the file list
  document.querySelectorAll('.file-row').forEach(row => {
    row.classList.toggle('playing', row.dataset.path === session.path);
  });
}

function _clearNowPlaying() {
  document.getElementById('nowPlaying').classList.add('hidden');
  document.querySelectorAll('.file-row.playing')
    .forEach(r => r.classList.remove('playing'));
}

// ── UI: Refresh status ────────────────────────────────────────────────────────
async function refreshUI() {
  let s;
  try { s = await api('/api/status'); } catch (_) { return; }

  document.getElementById('deviceInfo').textContent =
    s.name + ' \u00b7 ' + s.ip + ':' + s.port;

  if (s.room) {
    document.getElementById('roomInfo').innerHTML =
      '<strong>' + esc(s.room.name || 'Room') + '</strong> &nbsp; ' +
      'Join code:&nbsp;<span class="code">' + esc(s.room.code) + '</span>' +
      '&nbsp; <small style="color:var(--text-muted)">' + esc(s.room.room_id) + '</small>';
  } else {
    document.getElementById('roomInfo').textContent = 'No room';
  }

  const peerEl = document.getElementById('peerList');
  if (s.peers && s.peers.length > 0) {
    peerEl.innerHTML = s.peers.map(p =>
      '<div class="peer-item"><span class="peer-dot"></span>' +
      esc(p.name) + ' <small>' + esc(p.ip) + '</small></div>'
    ).join('');
  } else {
    peerEl.innerHTML = '';
  }

  if (s.session) {
    _updateNowPlaying(s.session, 'Playing');
  } else {
    _clearNowPlaying();
  }

  // Auto-scan the configured folder once on first load
  if (!_autoScanned && s.folder) {
    _autoScanned = true;
    document.getElementById('folderInput').value = s.folder;
    scanFolder(s.folder);
  }
}

// ── UI: File list ─────────────────────────────────────────────────────────────
async function scanFolder(folderOverride) {
  const folder = folderOverride || document.getElementById('folderInput').value.trim();
  if (!folder) { log('Enter a folder path first'); return; }

  const listEl = document.getElementById('fileList');
  listEl.innerHTML = '<div class="empty-state">Scanning…</div>';

  let data;
  try {
    data = await api('/api/files?folder=' + encodeURIComponent(folder));
  } catch (e) {
    log('Scan failed: ' + e.message);
    listEl.innerHTML = '<div class="empty-state">Scan failed: ' + esc(e.message) + '</div>';
    return;
  }

  if (!data.files || data.files.length === 0) {
    listEl.innerHTML = '<div class="empty-state">No supported audio files found.</div>';
    return;
  }

  listEl.innerHTML = data.files.map(f =>
    '<div class="file-row" data-path="' + esc(f.path) + '">' +
    '<span class="file-name" title="' + esc(f.path) + '">' + esc(f.name) + '</span>' +
    '<button class="btn btn-sm play-btn" type="button">&#9654; Play</button>' +
    '</div>'
  ).join('');


  log('Found ' + data.files.length + ' file(s) in ' + data.folder);
}

async function playFile(path) {
  const name = path.replace(/.*[\\/\\\\]/, '');
  log('Requesting: ' + name);
  try {
    await api('/api/play', {method: 'POST', body: JSON.stringify({path})});
  } catch (e) {
    log('Play failed: ' + e.message);
  }
}

async function stopPlayback() {
  _stopAudio();
  _clearNowPlaying();
  try {
    await api('/api/stop', {method: 'POST', body: '{}'});
  } catch (_) {}
}

// ── Initialise ────────────────────────────────────────────────────────────────
// Delegated click handler for Play buttons — attached once so it survives re-scans
document.getElementById('fileList').addEventListener('click', e => {
  const btn = e.target.closest('.play-btn');
  if (!btn) return;
  const row = btn.closest('[data-path]');
  if (row) playFile(row.dataset.path);
});

connectEvents();
refreshUI();
setInterval(refreshUI, 5000);
"""


# ── Web-app logic ─────────────────────────────────────────────────────────────

class MuSyncWebApp:
    def __init__(self, node: Node, port: int, music_folder: Optional[str] = None):
        self.node = node
        self.port = port
        self.music_folder: Optional[Path] = (
            Path(music_folder).expanduser().resolve() if music_folder else None
        )
        self._sse_lock = threading.Lock()
        self._sse_clients: list[queue.Queue] = []
        # session_id → original file path (served to browser, not the converted WAV)
        self._session_audio: dict[str, str] = {}
        self._op_lock = threading.Lock()  # serialises Node mutations

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        peers = [
            {"id": p.node_id, "name": p.name, "ip": p.ip, "room_id": p.room_id}
            for p in self.node.registry.snapshot()
        ]
        session: Optional[dict[str, Any]] = None
        if self.node.session:
            s = self.node.session
            session = {
                "session_id": s.session_id,
                "title": s.title,
                "start_host_time": s.start_host_time,
            }
        room: Optional[dict[str, Any]] = None
        if self.node.room:
            r = self.node.room
            room = {"room_id": r.room_id, "code": r.code, "name": r.name}
        return {
            "ok": True,
            "name": self.node.display_name,
            "ip": self.node.local_ip,
            "port": self.port,
            "room": room,
            "session": session,
            "peers": peers,
            "folder": str(self.music_folder) if self.music_folder else None,
        }

    # ── File listing ──────────────────────────────────────────────────────────

    def list_files(self, folder_override: Optional[str] = None) -> dict[str, Any]:
        if folder_override:
            folder = Path(folder_override).expanduser().resolve()
        elif self.music_folder:
            folder = self.music_folder
        else:
            return {"ok": True, "files": [], "folder": None}
        if not folder.is_dir():
            raise ValueError(f"Folder not found: {folder}")
        files = [
            {"name": p.name, "path": str(p)}
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
        ]
        return {"ok": True, "folder": str(folder), "files": files[:500]}

    # ── Playback ──────────────────────────────────────────────────────────────

    def play(self, path: str) -> dict[str, Any]:
        audio_path = Path(path).expanduser().resolve()
        if not audio_path.is_file():
            raise ValueError(f"File not found: {path}")
        if audio_path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"Unsupported format: {audio_path.suffix}")
        original_path = str(audio_path)
        with self._op_lock:
            self.node.play_file(original_path)
        sess = self.node.session
        if sess:
            # Store the original path; the browser gets this file directly.
            # (Node's host.py converts MP3→WAV internally for sounddevice playback,
            # but the browser decodes the original format itself.)
            self._session_audio[sess.session_id] = original_path
            self._push_sse({
                "type": "SESSION_START",
                "session_id": sess.session_id,
                "start_host_time": sess.start_host_time,
                "title": sess.title,
            })
        return {"ok": True}

    def stop(self) -> dict[str, Any]:
        with self._op_lock:
            self.node.stop_session()
        self._push_sse({"type": "SESSION_STOP"})
        return {"ok": True}

    # ── Clock sync ────────────────────────────────────────────────────────────

    def timesync(self, t1_ms: float) -> dict[str, Any]:
        t2 = time.time() * 1000
        t3 = time.time() * 1000
        return {"ok": True, "t2": t2, "t3": t3}

    # ── Audio serving with HTTP Range support ─────────────────────────────────
    # Range support is required so that:
    #   1. The browser's <audio> element can seek (needed for late-join sync)
    #   2. Mobile Safari and Chrome don't stall on large files

    def serve_audio(
        self,
        session_id: str,
        range_header: Optional[str],
    ) -> tuple[int, dict[str, str], Any]:
        """Return (http_status, headers, body_chunk_iterator)."""
        file_path_str = self._session_audio.get(session_id)
        if not file_path_str:
            raise FileNotFoundError("No audio registered for this session")
        file_path = Path(file_path_str)
        if not file_path.is_file():
            raise FileNotFoundError("Audio file no longer available on disk")

        suffix = file_path.suffix.lower()
        mime   = MIME_TYPES.get(suffix, "application/octet-stream")
        total  = file_path.stat().st_size
        start, end = 0, total - 1
        status = 200

        if range_header:
            try:
                unit, ranges_str = range_header.split("=", 1)
                if unit.strip() == "bytes":
                    first = ranges_str.split(",")[0].strip()
                    s_str, e_str = first.split("-", 1)
                    start = int(s_str) if s_str.strip() else 0
                    end   = int(e_str) if e_str.strip() else total - 1
                    start = max(0, min(start, total - 1))
                    end   = max(start, min(end, total - 1))
                    status = 206
            except Exception:
                pass  # malformed Range → fall back to full 200 response

        length = end - start + 1
        headers: dict[str, str] = {
            "Content-Type":   mime,
            "Content-Length": str(length),
            "Accept-Ranges":  "bytes",
            "Cache-Control":  "no-store",
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"

        _path = file_path_str  # capture for closure

        def _body():
            chunk = 65536
            remaining = length
            with open(_path, "rb") as fh:
                fh.seek(start)
                while remaining > 0:
                    data = fh.read(min(chunk, remaining))
                    if not data:
                        break
                    yield data
                    remaining -= len(data)

        return status, headers, _body()

    # ── SSE broadcast ─────────────────────────────────────────────────────────

    def _push_sse(self, event: dict) -> None:
        payload = json.dumps(event)
        with self._sse_lock:
            dead = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(payload)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)


# ── HTTP request handler ──────────────────────────────────────────────────────

def make_handler(app: MuSyncWebApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MuSyncWeb/2.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
            # Suppress 200/206 to keep the console clean; log everything else.
            if args and str(args[1]) not in ("200", "206"):
                print(f"[web] {self.address_string()} {fmt % args}")

        # ── GET ──────────────────────────────────────────────────────────────

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            p = parsed.path
            try:
                if p == "/":
                    self._text(INDEX_HTML, "text/html; charset=utf-8")
                elif p == "/static/styles.css":
                    self._text(STYLES_CSS, "text/css; charset=utf-8")
                elif p == "/static/app.js":
                    self._text(APP_JS, "text/javascript; charset=utf-8")
                elif p == "/api/status":
                    self._json(app.get_status())
                elif p == "/api/files":
                    qs = urllib.parse.parse_qs(parsed.query)
                    folder = qs.get("folder", [None])[0]
                    self._json(app.list_files(folder))
                elif p == "/api/events":
                    self._sse_loop(app)
                elif p.startswith("/audio/"):
                    # Strip any query-string cache-buster
                    session_id = p[len("/audio/"):].split("?")[0]
                    range_hdr  = self.headers.get("Range")
                    status, headers, body = app.serve_audio(session_id, range_hdr)
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    for chunk in body:
                        self.wfile.write(chunk)
                else:
                    self.send_error(404)
            except FileNotFoundError as exc:
                self._json({"ok": False, "error": str(exc)}, 404)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

        # ── POST ─────────────────────────────────────────────────────────────

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            p    = parsed.path
            body = self._read_json()
            try:
                if p == "/api/play":
                    self._json(app.play(body.get("path", "")))
                elif p == "/api/stop":
                    self._json(app.stop())
                elif p == "/api/timesync":
                    self._json(app.timesync(body.get("t1", 0)))
                else:
                    self.send_error(404)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

        # ── Helpers ──────────────────────────────────────────────────────────

        def _read_json(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

        def _text(self, content: str, ct: str) -> None:
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _sse_loop(self, app: MuSyncWebApp) -> None:
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
                        # Keepalive comment so mobile browsers don't time out
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


# ── Entry point ───────────────────────────────────────────────────────────────

def _get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MuSync web interface — play music in sync across LAN devices"
    )
    parser.add_argument("--name",   default=socket.gethostname(),
                        help="display name for this device (default: hostname)")
    parser.add_argument("--port",   type=int, default=8080,
                        help="web server port (default: 8080)")
    parser.add_argument("--host",   default="0.0.0.0",
                        help="bind address (default: 0.0.0.0)")
    parser.add_argument("--folder", default=None,
                        help="music folder to auto-scan and show on page load")
    args = parser.parse_args()

    node = Node(display_name=args.name)
    node.start()

    # Auto-create a room so play_file() works immediately (it requires a room).
    # CLI peers on other laptops can join using the displayed code.
    room = node.create_room(name=args.name)
    print(f"[room] id={room.room_id}  join code={room.code}")

    app    = MuSyncWebApp(node=node, port=args.port, music_folder=args.folder)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))

    lan_ip = _get_lan_ip()
    print(f"[web] local  → http://127.0.0.1:{args.port}")
    print(f"[web] LAN    → http://{lan_ip}:{args.port}   ← open this on your phone")
    print("[web] Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        node.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
