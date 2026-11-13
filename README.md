# edge-vision-core

Real-time object detection on a Raspberry Pi 5 running **Ubuntu Core 24**, packaged as
a strictly confined snap. An [Edge Impulse](https://edgeimpulse.com) model looks at a
USB camera, and **Ubuntu Frame** shows the live result full screen on the Pi's HDMI
display. The same page opens in any browser on the network.

```
USB camera ──► edge-vision-core snap ──► http://<pi>:8000 ──┬─► wpe-webkit-mir-kiosk ─► Ubuntu Frame ─► HDMI
               (OpenCV + model.eim)                         └─► any browser on the LAN
```

Works out of the box: a YOLOv5 COCO model ships alongside the app as a snap component (80 everyday objects such as
person, cup, bottle and phone). Measured on a Pi 5 (320×320, int8, CPU only):
**~15 FPS, ~60 ms per frame**.

---

## What you need

| Item | Notes |
| --- | --- |
| Raspberry Pi 5 | 4 GB or 8 GB, official 27 W USB-C supply |
| microSD card | 16 GB or more |
| USB webcam | Any UVC webcam. A Pi Camera Module (CSI ribbon) is **not** supported, because this snap uses V4L2, not libcamera |
| HDMI display + micro-HDMI cable | Plug into HDMI0, the port next to the USB-C power |
| Ethernet cable | Simplest for first boot. WiFi can be added later (step 3) |
| A Mac or Linux laptop | For building the snap |
| Accounts | [Ubuntu One](https://login.ubuntu.com) with an SSH key uploaded, plus [Edge Impulse](https://studio.edgeimpulse.com) (free) |

---

## Step 1: Flash Ubuntu Core 24 on the Pi

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. **Choose device:** Raspberry Pi 5. **Choose OS:** Other general-purpose OS → Ubuntu →
   **Ubuntu Core 24 (64-bit)**. Choose the SD card, then write.
3. Put the card in the Pi, connect Ethernet, HDMI and a keyboard, and power on.
4. Follow the first-boot console: choose the network, then enter your **Ubuntu One
   email**. It imports your SSH key and prints the Pi's IP address.
5. From your laptop:

   ```
   ssh <ubuntu-one-username>@<pi-ip>
   ```

> **"REMOTE HOST IDENTIFICATION HAS CHANGED"?** The Pi has an IP address your laptop
> previously used for another device. Run `ssh-keygen -R <pi-ip>` and connect again.

## Step 2: Set up the build machine (Mac)

Snaps are built in Linux. On a Mac, use a Multipass VM with your project folder mounted
into it.

```
brew install --cask multipass
multipass launch 24.04 --name snapbuild --cpus 4 --memory 8G --disk 40G
multipass mount ~/snaps snapbuild:/home/ubuntu/snaps
multipass exec snapbuild -- sudo snap install snapcraft --classic
multipass exec snapbuild -- sudo snap install lxd
multipass exec snapbuild -- sudo lxd init --auto
multipass exec snapbuild -- sudo usermod -aG lxd ubuntu
```

On an Apple Silicon Mac the VM is arm64, so it builds the Pi's arm64 snap natively.

Clone this repo into the mounted folder:

```
cd ~/snaps
git clone https://github.com/salmanfarisvp/edge-vision-core.git
```

## Step 3 (optional): WiFi on the Pi

Ubuntu Core has no NetworkManager by default. To add WiFi alongside Ethernet:

```
sudo snap install network-manager --channel=24/stable
sudo network-manager.nmcli device wifi connect "YourSSID" password "YourPassword"
network-manager.nmcli device status        # eth0 and wlan0 both "connected"
ip -4 -br addr                             # one IP per interface
```

Both connections reconnect on boot. NetworkManager takes over Ethernet too, so your
Ethernet IP may change once. Set a DHCP reservation for the Pi in your router so it
stays the same.

## Step 4 (optional): Get your own model from Edge Impulse

**You can skip this step.** The snap ships with a ready-to-use YOLOv5 COCO model
([`models/`](models/)) that detects 80 everyday objects. Do this step only to use a
different model.

1. Open the public project
   [YOLOv5 COCO Pretrained](https://studio.edgeimpulse.com/public/382356/live) and click
   **Clone this project**. It's a YOLOv5 model pretrained on COCO's 80 everyday
   classes: person, cup, bottle, cell phone, laptop, book, chair, and so on.
2. In your clone: **Deployment** → search **Linux (AARCH64)** → **Quantized (int8)** →
   **Build**. You get a `.eim` file of about 15 MB.

Any Edge Impulse **image** project works: object detection (YOLO, FOMO, SSD) or image
classification. Your own trained model is a drop-in replacement.

> That public project names its classes `class 1` … `class 80`. The app detects this
> and shows the COCO names (`person`, `cup`, ...) instead.

## Step 5: Build the snap

```
multipass exec snapbuild -- bash -lc 'cd ~/snaps/edge-vision-core && snapcraft pack'
```

This produces two files in the project folder:

| File | Contents |
| --- | --- |
| `edge-vision-core_0.1_arm64.snap` | The app: camera capture, inference and the display page |
| `edge-vision-core+model_12.comp` | The **model component**: the YOLOv5 COCO `.eim` (about 15 MB) |

The model ships as a [snap component](https://snapcraft.io/docs/explanation/how-snaps-work/snap-components/),
so the app and the model are installed and updated as separate pieces. The first build
takes a few minutes; later builds are quicker.

## Step 6: Install on the Pi

From the laptop:

```
scp edge-vision-core_0.1_arm64.snap edge-vision-core+model_12.comp <user>@<pi-ip>:
```

On the Pi (snap components need **snapd 2.67 or newer**; check with `snap version` and
run `sudo snap refresh snapd` if it's older):

```
sudo snap install --dangerous ./edge-vision-core_0.1_arm64.snap ./edge-vision-core+model_12.comp
sudo snap connect edge-vision-core:camera                 # camera is not auto-connected
sudo snap set edge-vision-core threshold=0.45
snap logs -f edge-vision-core.server
```

You should see:

```
Serving on http://0.0.0.0:8000  (camera /dev/video0, threshold 0.45)
Loaded model (model component): ... (object_detection, 320x320x3, 80 labels: ...)
Camera /dev/video0 opened
```

**Using your own model from step 4** (optional): copy it over, and it takes priority over
the model component within about 3 seconds:

```
scp ~/Downloads/<your-model>-linux-aarch64-*.eim <user>@<pi-ip>:model.eim
ssh <user>@<pi-ip> 'sudo cp model.eim /var/snap/edge-vision-core/common/model.eim'
```

Delete `/var/snap/edge-vision-core/common/model.eim` to go back to the component's model.

### Updating the model without touching the app

To ship a new model version as a component, replace the file in `models/`, bump `version`
under `components: model:` in `snap/snapcraft.yaml`, rebuild, and install only the new
`.comp`:

```
sudo snap install --dangerous ./edge-vision-core+model_13.comp
snap components edge-vision-core
```

The app picks up the new model within about 3 seconds, without reinstalling or rebuilding
the app. Snap Store uploads currently pair each app revision with its components, so
store users get the new model with the next app release.

Open `http://<pi-ip>:8000` on your laptop to check it works.

## Step 7: Show it on the display with Ubuntu Frame

On the Pi:

```
sudo snap install ubuntu-frame
sudo snap install wpe-webkit-mir-kiosk
sudo snap set wpe-webkit-mir-kiosk url="http://localhost:8000/?kiosk=1"
sudo snap restart wpe-webkit-mir-kiosk
```

On Ubuntu Core, both run as services and start at boot, and the kiosk's `wayland` plug
connects to Frame automatically. From now on the Pi boots straight into the demo. `?kiosk=1`
hides the mouse cursor.

---

## Running the demo (on stage)

**Before the talk (10 minutes)**

1. Power on the Pi with camera, HDMI and network connected. The demo page appears on its
   own after about a minute.
2. From the laptop, check everything is up:

   ```
   ssh <user>@<pi-ip> 'snap services edge-vision-core ubuntu-frame wpe-webkit-mir-kiosk'
   ```

   All three should be `active`.
3. Point the camera at where you'll hold objects, not at a ceiling light. Light the scene
   well; confidence rises a lot with good lighting.
4. Have props ready: a cup, a bottle, a phone, a book.
5. Keep a terminal open with `ssh <user>@<pi-ip>` for the live steps below.

**Live, about 5 minutes**

1. **Show the detection.** Walk into view (`person`), then hold up a cup, a bottle and a
   phone. Point at the FPS and ms/frame numbers: everything runs on the Pi's CPU, offline.
2. **Show it's a confined snap.**

   ```
   snap connections edge-vision-core
   ```

   The app can only use the camera and the network, nothing else on the device.
3. **Swap the model live, without reinstalling.** Copy a different `.eim` (for example
   a FOMO model you trained) over the old one:

   ```
   sudo cp other-model.eim /var/snap/edge-vision-core/common/model.eim
   ```

   The screen switches to the new model within about 3 seconds.
4. **Tune it remotely.**

   ```
   sudo snap set edge-vision-core threshold=0.7
   ```

   Fewer, more confident boxes appear after a short restart.
5. **Show the same page from the audience's side.** Open `http://<pi-ip>:8000` on the
   laptop or a phone on the same network.

**If something goes wrong on stage**

| Symptom | Quick fix |
| --- | --- |
| Screen black or grey | `sudo snap restart ubuntu-frame wpe-webkit-mir-kiosk` |
| "No camera at /dev/video0" | Re-plug the USB camera; check `ls /dev/video*` and `snap connections edge-vision-core` |
| "Model error" after copying your own model | Make sure it's the **Linux (AARCH64)** build; `sudo rm /var/snap/edge-vision-core/common/model.eim` falls back to the bundled model |
| Nothing detected | Add light, move closer, or `sudo snap set edge-vision-core threshold=0.35` |
| Page doesn't load from the laptop | Laptop and Pi must be on the same network; check the IP with `ip -4 -br addr` |

---

## Configuration

| Option | Default | Meaning |
| --- | --- | --- |
| `port` | `8000` | HTTP port |
| `camera` | `0` | Camera to open (`/dev/videoN`) |
| `threshold` | `0.6` | Minimum confidence to show a box or label (0.45 suits the COCO model) |
| `model-url` | unset | Download `model.eim` from this URL at start, instead of copying it |

```
sudo snap set edge-vision-core camera=1 threshold=0.5
snap get edge-vision-core
```

Each change restarts the service with the new values.

## How it works

- **Capture:** OpenCV reads 640×480 frames from `/dev/videoN` through V4L2.
- **Inference:** the `.eim` file is a standalone Linux executable built by Edge Impulse.
  The app starts it with a Unix socket path and sends each frame as JSON. Frames are
  centre-cropped to the model's aspect ratio, resized, and packed as RGB pixels. The
  model replies with boxes or class scores. The app speaks this protocol directly, so it
  doesn't need the `edge_impulse_linux` SDK or its PyAudio dependency.
- **Display:** a small HTTP server serves the page, `/frame.jpg` (one frame, with boxes
  drawn) and `/api/status` (JSON results). The page draws frames onto a canvas instead
  of using an MJPEG `<img>`, which flickers in WebKit, the engine the kiosk uses.
- **Model selection and hot-swap:** every 3 seconds the app checks for
  `$SNAP_COMMON/model.eim` (yours), and otherwise uses `default.eim` from the `model`
  component (`$SNAP_COMPONENTS/model/`). It reloads when either file appears, changes or
  is removed.

| Path | Purpose |
| --- | --- |
| `snap/snapcraft.yaml` | Snap definition: core24, strict confinement, `camera`/`network`/`network-bind` plugs |
| `snap/hooks/install`, `snap/hooks/configure` | Default options, validation, and a restart when options change |
| `src/app/edge_vision.py` | Capture, inference and the HTTP server |
| `src/www/index.html` | The live display page |
| `models/` | The YOLOv5 COCO model, packed into the `model` component; see [models/README.md](models/README.md) for its source and license |
| `requirements.txt` | `opencv-python-headless`, `numpy` |

## Developing on a Mac

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
CAMERA=0 .venv/bin/python src/app/edge_vision.py      # then open http://localhost:8000
```

The camera view and page work on macOS. The `.eim` won't run there because it's an
aarch64 Linux binary, so test the model on the Pi.

## Roadmap

- Physical AI: switch an LED or buzzer through the `gpio` interface when a chosen object
  is detected.
- Publish to the Snap Store (`snapcraft register edge-vision-core`) so it installs with
  `sudo snap install edge-vision-core`.
