# MuSync

Play music on multiple devices on the same network in sync. Synchronized multi-device audio playback over LAN/Wi‑Fi in pure Python.

Any device on the network can become the **host** by playing a local audio
file; every other peer automatically pulls the PCM stream over TCP and plays
it in lock-step using an NTP-style clock offset measured against the host.

## Features

- Auto peer discovery with Zeroconf (`_musync._tcp.local.`).
- NTP-style 4-timestamp clock-offset estimation (best-of-N RTT samples).
- Sample-accurate scheduled playback via `sounddevice` callback timing.
- Host can change at any time — any peer can start a new song; the previous
  session is torn down and a new one is announced.
- Brief (configurable) lead-in time per session so all peers can buffer and
  re-sync before audio starts.

## Install

```bash
pip install -r requirements.txt
```

You also need an OS audio output. On Windows everything works out of the box.
On Linux install `libportaudio2` and `libsndfile1`.

Supported file formats: anything `libsndfile` reads — WAV, FLAC, OGG, AIFF,
etc. (MP3 is supported only on recent libsndfile builds; convert to WAV/FLAC
if needed.)

## Project layout

| File         | Role                                                         |
|--------------|--------------------------------------------------------------|
| `utils.py`   | constants, networking helpers, time-sync, `SyncPlayer`, peer registry, `Peer`/`Room`/`Session` dataclasses |
| `host.py`    | `HostMixin`: load audio, announce session, stream PCM        |
| `client.py`  | `ClientMixin`: handle `SESSION_START`, receive PCM, schedule playback |
| `musync.py`  | `Node` (composes the mixins), Zeroconf, **rooms**, CLI/REPL  |
| `webapp.py`  | Browser UI for room control, peer status, and synced playback |

## Run

On every device:

```bash
python musync.py --name LivingRoom
```

Or run the LAN web UI:

```bash
python webapp.py --name LivingRoom --port 8080
```

Open `http://127.0.0.1:8080` on the host computer, or use the LAN URL printed
by the app from another device on the same network. The music folder path you
enter in the UI is a folder on the computer running `webapp.py`.

### Rooms

A *room* is a persistent group of devices that play together. To play
synchronized audio you must first either create a room or join one:

```
> create-room                # generates a 6-digit code, you can share it
[room] created 'LivingRoom's room  id=ab12cd34  code=472913
```

On every other device:

```
> rooms                      # list rooms visible on the LAN
  ab12cd34   members:  1   e.g. LivingRoom
> join ab12cd34 472913       # enter the code
[room] joined ab12cd34 via LivingRoom
```

The code **does not expire** — anyone with it can join the room at any time.
Any current member of the room validates new join requests against the code.

### Playing

Once at least two devices share a room, on any of them:

```
> play song.flac             # this device becomes host for the room
> stop                       # stop the current session
> quit
```

The host role moves transparently each time some device runs `play` — only
members of the same room receive the stream.

## Network ports

| Purpose       | Proto | Port  |
|---------------|-------|-------|
| Control       | TCP   | 51900 |
| Time sync     | UDP   | 51901 |
| Audio stream  | TCP   | 51902 |
| Zeroconf mDNS | UDP   | 5353  |

Allow these through your firewall on the local network.

## Notes / limitations

- First-time sync after a host change takes ~2–3 s (default lead-in) while
  peers measure clock offset and pre-buffer.
- Quality of synchronization depends on Wi‑Fi jitter; wired LAN is best.
- This is a hobby project, not a hardened protocol.
