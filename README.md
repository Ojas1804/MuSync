# MuSync

Synchronized multi-device audio playback over LAN/Wi-Fi in pure Python.

Any device on the network can become the **host** by playing a local audio file. Every other peer automatically pulls the raw PCM stream over TCP and plays it in lock-step using an NTP-style clock offset measured against the host.

As of now, CLI is working fine. Future work will involve working in Web UI and mp3 support.

> **The audio file only needs to exist on the host device.** Peers receive the stream over the network — no file copying required.

## Features

- Auto peer discovery via Zeroconf (`_musync._tcp.local.`).
- NTP-style 4-timestamp clock-offset estimation (best-of-N RTT samples).
- Sample-accurate scheduled playback via `sounddevice` callback timing.
- Room-based grouping — only devices in the same room hear the stream.
- Any peer can become the host at any time; the previous session tears down automatically.
- Configurable lead-in time so all peers buffer and sync before audio starts.
- Both a CLI/REPL (`musync.py`) and a browser UI (`webapp.py`).

## Requirements

- Python 3.9+
- An audio output device on every device

## Install

Run on **every device**:

```bash
pip install -r requirements.txt
```

On Linux you also need system libraries:

```bash
sudo apt install libportaudio2 libsndfile1
```

On Windows and macOS everything works out of the box.

### Supported audio formats

WAV, FLAC, OGG, AIFF. (MP3 requires a recent `libsndfile` build — use WAV/FLAC if unsure.)

---

## Running the CLI

Run on **every device** that should participate:

```bash
python musync.py --name <DeviceName>
```

Example:

```bash
# Device A
python musync.py --name LivingRoom

# Device B
python musync.py --name Bedroom
```

### Step-by-step (CLI)

**1. Create a room on one device (the future host)**

```
> create-room Living Room
[room] created 'Living Room'  id=ab12cd34  code=472913
```

Share the `id` and `code` with the other devices.

**2. Join the room on every other device**

```
> rooms                       # confirm the room is visible on the LAN
  ab12cd34   members:  1   e.g. LivingRoom

> join ab12cd34 472913        # use the id and code from step 1
[room] joined ab12cd34 via LivingRoom
```

**3. Play a file from the host device**

```
> play "C:\Users\You\Music\song.wav"
[host] playing 'song.wav' to 1 peer(s); start in 3.0s
```

All devices in the room will start playing in sync after the lead-in.

**4. Other useful commands**

```
> stop              # stop the current session
> room              # show current room details and connected members
> peers             # list all discovered devices on the network
> devices           # list local audio output devices
> leave             # leave the current room
> help              # show all commands
> quit              # shut down
```

---

## Running the Web App

### Quick start (recommended)

Two launcher scripts are provided so you don't need to type any Python command manually.

**Option A — Double-click (Windows)**

Double-click `start_webapp.bat`. It locates Git Bash automatically and starts the app.

**Option B — Git Bash**

```bash
bash start_webapp.sh
```

Either way the terminal prints the exact URL to open on your phone:

```
  ╔══════════════════════════════════════════╗
  ║              MuSync Web App              ║
  ╠══════════════════════════════════════════╣
  ║  Open on this PC  : http://127.0.0.1:8080 ║
  ║  Open on phone    : http://192.168.1.xx:8080 ║
  ╚══════════════════════════════════════════╝

  On your phone: connect to the same Wi-Fi,
  then open the URL above in your browser.
```

> **Phone access:** your phone must be on the **same Wi-Fi** as the PC. Open the `http://<LAN IP>:8080` URL in any mobile browser — no app install required.

### Manual start (alternative)

```bash
python webapp.py --name <DeviceName> --port 8080
```

### Step-by-step (Web App)

**1. Create a room on one device**

- Open the device's web UI (use the LAN URL on a phone).
- Under **Room**, type a room name and click **Create**.
- Note the room ID and code shown in the Room badge.

**2. Join the room on every other device**

- Open each device's web UI.
- Under **Room**, enter the **Room ID** and **Code** from step 1.
- Click **Join**.

**3. Scan and play a file from the host device**

- Under **Playback**, enter the path to a folder on *that computer* (e.g. `C:\Users\You\Music` or `test_source`).
- Click **Scan** to list supported audio files.
- Click **Play** next to any file.

All devices in the room will start playing in sync after the lead-in.

**4. Stop playback**

- Click **Stop** in the Playback panel.

> **Note:** The music folder path is resolved on the computer running `webapp.py`, not the browser. Audio files only need to exist on the machine that clicks **Play**.

---

## Network Ports

All ports must be reachable **inbound** on the host device from the local network.

| Purpose       | Protocol | Port  |
|---------------|----------|-------|
| Control       | TCP      | 51900 |
| Time sync     | UDP      | 51901 |
| Audio stream  | TCP      | 51902 |
| Zeroconf mDNS | UDP      | 5353  |

### Windows Firewall

If peers connect to a room but hear no audio, the firewall is the most likely cause. Run the following in an **Administrator PowerShell** on the **host** device:

```powershell
New-NetFirewallRule -DisplayName "MuSync Control"   -Direction Inbound -Protocol TCP -LocalPort 51900 -Action Allow
New-NetFirewallRule -DisplayName "MuSync TimeSync"  -Direction Inbound -Protocol UDP -LocalPort 51901 -Action Allow
New-NetFirewallRule -DisplayName "MuSync Audio"     -Direction Inbound -Protocol TCP -LocalPort 51902 -Action Allow
```

---

## Project Layout

| File              | Role                                                                 |
|-------------------|----------------------------------------------------------------------|
| `musync.py`       | CLI entry point and REPL                                             |
| `webapp.py`       | Browser UI entry point (HTTP server + JS frontend)                   |
| `Node.py`         | Core node: composes mixins, Zeroconf, control plane, rooms           |
| `host.py`         | `HostMixin`: load audio, announce session, stream PCM to peers       |
| `client.py`       | `ClientMixin`: handle `SESSION_START`, receive PCM, schedule playback |
| `SyncPlayer.py`   | `sounddevice`-based player with sample-accurate scheduled output     |
| `PeerRegistry.py` | Zeroconf `ServiceListener` that tracks discovered peers              |
| `TimeSyncServer.py` | UDP NTP-style time-sync responder (runs on host)                   |
| `utils.py`        | Shared constants, networking helpers, clock offset measurement       |
| `Peer.py`         | `Peer` dataclass                                                     |
| `Room.py`         | `Room` dataclass                                                     |
| `Session.py`      | `Session` dataclass                                                  |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Peers not discovered | mDNS/multicast blocked by router | Check router settings; try a wired connection |
| `could not reach timesync server` on client | UDP 51901 blocked on host | Add firewall rule (see above) |
| `receiver error` on client / silence | TCP 51902 blocked on host | Add firewall rule (see above) |
| `no peers in room registry yet` on host | Played too quickly after join | Wait ~2s after joining, then play |
| Audio out of sync | High Wi-Fi jitter | Use wired LAN for better sync |

## Notes

- Sync quality depends on network jitter; wired LAN gives the best results.
- The default lead-in is 3 seconds to allow all peers to buffer and sync.
- This is a hobby project, not a hardened production protocol.
