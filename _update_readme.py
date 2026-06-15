import re, pathlib

readme = pathlib.Path("README.md")
content = readme.read_text(encoding="utf-8")

OLD = """## Running the Web App

Run on **every device** that should participate:

```bash
python webapp.py --name <DeviceName> --port 8080
```

Example:

```bash
# Device A
python webapp.py --name LivingRoom --port 8080

# Device B
python webapp.py --name Bedroom --port 8080
```

On startup the app prints two URLs:

```
[web] open locally:  http://127.0.0.1:8080
[web] open on LAN:   http://192.168.1.10:8080
```

Open the **LAN URL** from any browser on the same network to control that device.

### Step-by-step (Web App)

**1. Create a room on one device**

- Open the device's web UI in a browser.
- Under **Room**, type a room name and click **Create**.
- Note the room ID and code shown in the Room badge.

**2. Join the room on every other device**

- Open each device's web UI.
- Under **Room**, enter the **Room ID** and **Code** from step 1.
- Click **Join**.

**3. Scan and play a file from the host device**

- Under **Playback**, enter the path to a folder on *that computer* (e.g. `C:\\Users\\You\\Music` or `test_source`).
- Click **Scan** to list supported audio files.
- Click **Play** next to any file.

All devices in the room will start playing in sync.

**4. Stop playback**

- Click **Stop** in the Playback panel.

> **Note:** The music folder path is resolved on the computer running `webapp.py`, not the browser. Devices only need the audio files on the machine acting as host."""

NEW = """## Running the Web App

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

- Under **Playback**, enter the path to a folder on *that computer* (e.g. `C:\\Users\\You\\Music` or `test_source`).
- Click **Scan** to list supported audio files.
- Click **Play** next to any file.

All devices in the room will start playing in sync after the lead-in.

**4. Stop playback**

- Click **Stop** in the Playback panel.

> **Note:** The music folder path is resolved on the computer running `webapp.py`, not the browser. Audio files only need to exist on the machine that clicks **Play**."""

if OLD in content:
    readme.write_text(content.replace(OLD, NEW), encoding="utf-8")
    print("README updated OK")
else:
    # Try normalising line endings and retry
    content_lf = content.replace("\r\n", "\n")
    old_lf = OLD.replace("\r\n", "\n")
    if old_lf in content_lf:
        readme.write_text(content_lf.replace(old_lf, NEW), encoding="utf-8")
        print("README updated OK (normalised CRLF)")
    else:
        print("ERROR: target section not found")
