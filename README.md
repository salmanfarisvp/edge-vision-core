# edge-vision-core

Real-time object detection on a Raspberry Pi 5 running **Ubuntu Core 24**, ready to demo.
A USB camera feeds an [Edge Impulse](https://edgeimpulse.com) YOLOv5 model, and
**Ubuntu Frame** shows the live result full screen on the Pi's HDMI display, with CPU,
RAM and temperature next to it. The same page opens in any browser on the network.

This repo is the **demo kit**: the model, the setup steps and a stage script. The app
itself is [**impulse-runner**](https://github.com/salmanfarisvp/impulse-runner), a snap
that runs any Edge Impulse model on Ubuntu Core.

```
USB camera ──► impulse-runner snap ──► http://<pi>:8000 ──┬─► wpe-webkit-mir-kiosk ─► Ubuntu Frame ─► HDMI
               (YOLOv5 COCO .eim)                         └─► any browser on the LAN
```

The model detects COCO's 80 everyday objects, such as person, cup, bottle, phone and
laptop. Measured on a Pi 5 (320×320, int8, CPU only): **~13–15 FPS, ~45–55 ms per frame**.

The whole setup, once Ubuntu Core is running, is:

```bash
sudo snap install impulse-runner --edge
sudo snap connect impulse-runner:camera
sudo snap connect impulse-runner:hardware-observe
sudo snap set impulse-runner threshold=0.45 \
  model-url=https://github.com/salmanfarisvp/edge-vision-core/raw/main/models/yolov5-coco-320-int8-linux-aarch64.eim
```

---

## What you need

| Item | Notes |
| --- | --- |
| Raspberry Pi 5 | 4 GB or 8 GB, official 27 W USB-C supply. **Use a cooler**: the model keeps the CPU busy and an uncooled Pi 5 runs at about 77 °C |
| microSD card | 16 GB or more |
| USB webcam | Any UVC webcam. A Pi Camera Module (CSI ribbon) isn't supported yet, because impulse-runner uses V4L2, not libcamera |
| HDMI display + micro-HDMI cable | Plug into HDMI0, the port next to the USB-C power |
| Ethernet cable | Simplest for first boot. Wi-Fi can be added later (step 2) |
| Accounts | [Ubuntu One](https://login.ubuntu.com) with an SSH key uploaded. [Edge Impulse](https://studio.edgeimpulse.com) only if you want your own model |

No build machine is needed: everything installs from the Snap Store.

---

## Step 1: Flash Ubuntu Core 24 on the Pi

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. **Choose device:** Raspberry Pi 5. **Choose OS:** Other general-purpose OS → Ubuntu →
   **Ubuntu Core 24 (64-bit)**. Choose the SD card, then write.
3. Put the card in the Pi, connect Ethernet, HDMI and a keyboard, and power on.
4. Follow the first-boot console: choose the network, then enter your **Ubuntu One
   email**. It imports your SSH key and prints the Pi's IP address.
5. From your laptop:

   ```bash
   ssh <ubuntu-one-username>@<pi-ip>
   ```

> **"REMOTE HOST IDENTIFICATION HAS CHANGED"?** The Pi has an IP address your laptop
> previously used for another device. Run `ssh-keygen -R <pi-ip>` and connect again.

## Step 2 (optional): Wi-Fi

```bash
sudo snap install network-manager
sudo nmcli d wifi connect "<SSID>" password "<password>"
```

Ethernet and Wi-Fi can be up at the same time, and Wi-Fi reconnects on boot. Your phone's
hotspot works too, and is handy at venues: put the laptop on the same hotspot to SSH in.

## Step 3: Install impulse-runner

```bash
sudo snap install impulse-runner --edge
sudo snap connect impulse-runner:camera
sudo snap connect impulse-runner:hardware-observe    # CPU temperature on screen
```

(Drop `--edge` once impulse-runner is on the stable channel.)

## Step 4: Load the model

Point impulse-runner at the model in this repo. The Pi downloads it itself, so there's
nothing to copy:

```bash
sudo snap set impulse-runner threshold=0.45 \
  model-url=https://github.com/salmanfarisvp/edge-vision-core/raw/main/models/yolov5-coco-320-int8-linux-aarch64.eim
```

Check it:

```bash
snap logs impulse-runner -n 5
# ... Loaded model: ... YOLOv5 COCO Pretrained v2 v12 (object_detection, sensor camera ...) -> input: camera
# ... Camera /dev/video0 opened
```

Open `http://<pi-ip>:8000` from your laptop to see it.

`threshold=0.45` suits this COCO model indoors. impulse-runner's default of 0.5 hides
some real detections in dim light.

## Step 5: Show it on the display with Ubuntu Frame

```bash
sudo snap install ubuntu-frame
sudo snap install wpe-webkit-mir-kiosk
sudo snap set wpe-webkit-mir-kiosk url="http://localhost:8000/?kiosk=1"
sudo snap restart wpe-webkit-mir-kiosk
```

On Ubuntu Core both run as services and start at boot, and the kiosk's `wayland` plug
connects to Frame automatically. From now on the Pi boots straight into the demo.
`?kiosk=1` hides the mouse pointer and the upload button.

The screen shows the live video with boxes on the left. On the right: the top detection,
per-object scores, **System** (CPU %, RAM, CPU temperature, load) and **Model** (results
per second, ms per inference, threshold).

---

## Running the demo (on stage)

**Before the talk (10 minutes)**

1. Power on the Pi with camera, HDMI and network connected. The demo page appears on its
   own after about a minute.
2. From the laptop, check everything is up:

   ```bash
   ssh <user>@<pi-ip> 'snap services impulse-runner ubuntu-frame wpe-webkit-mir-kiosk'
   ```

   All three should be `active`.
3. Point the camera at where you'll hold objects, not at a ceiling light. Light the scene
   well; confidence rises a lot with good lighting.
4. Have props ready: a cup, a bottle, a phone, a book.
5. Keep a terminal open with `ssh <user>@<pi-ip>` for the live steps below.

**Live, about 5 minutes**

1. **Show the detection.** Walk into view (`person`), then hold up a cup, a bottle and a
   phone. Point at the numbers on the right: everything runs on the Pi's CPU, offline,
   and you can see the CPU load and temperature it costs.
2. **Show it's a confined snap.**

   ```bash
   snap connections impulse-runner
   ```

   The app can only use what's connected: the camera, the network, and reading hardware
   info. Nothing else on the device.
3. **Swap the model live.** Open `http://<pi-ip>:8000` on the laptop, click **Load model**
   and drop in a different `.eim`, for example a FOMO or keyword-spotting model you
   trained. Paste the token from `sudo snap get impulse-runner upload-token`. The screen
   switches to the new model in a few seconds. An audio model switches the screen to
   the microphone view on its own (connect `impulse-runner:alsa` first).
4. **Tune it remotely.**

   ```bash
   sudo snap set impulse-runner threshold=0.7
   ```

   Fewer, more confident boxes appear after a short restart.
5. **Show the same page from the audience's side.** Open `http://<pi-ip>:8000` on a
   phone on the same network.
6. **Go back to the YOLO model:** upload `models/yolov5-coco-320-int8-linux-aarch64.eim`
   again from the page.

**If something goes wrong on stage**

| Symptom | Quick fix |
| --- | --- |
| Screen black or grey | `sudo snap restart ubuntu-frame wpe-webkit-mir-kiosk` |
| "No camera at /dev/video0" | Re-plug the USB camera; check `ls /dev/video*` and `snap connections impulse-runner` |
| "Model failed to load" after an upload | It must be the **Linux (AARCH64)** build. Upload the YOLO model again |
| Nothing detected | Add light, move closer, or `sudo snap set impulse-runner threshold=0.35` |
| Temperature above 80 °C, FPS dropping | The Pi is throttling. Add a cooler or a fan |
| Page doesn't load from the laptop | Laptop and Pi must be on the same network; check the IP with `ip -4 -br addr` |

---

## Using your own model

Any Edge Impulse **image** project works: classification, object detection, FOMO, or
visual anomaly detection. Audio and sensor models work too; see the
[impulse-runner README](https://github.com/salmanfarisvp/impulse-runner#readme).

1. In [Edge Impulse Studio](https://studio.edgeimpulse.com): **Deployment** →
   **Linux (AARCH64)** → **Quantized (int8)** → **Build**. You get a `.eim`.
2. Upload it from `http://<pi-ip>:8000` (**Load model**), or host it somewhere and use
   `sudo snap set impulse-runner model-url=<url>`.

## What's in this repo

| Path | What |
| --- | --- |
| `models/yolov5-coco-320-int8-linux-aarch64.eim` | The demo model: YOLOv5, COCO 80 classes, 320×320, int8, Linux AARCH64 |
| `models/README.md` | Where the model came from, and its license (AGPL-3.0) |

The model's classes are named `class 1` … `class 80` in its Edge Impulse project.
impulse-runner recognises this and shows COCO names (`person`, `cup`, ...) instead.

Before impulse-runner existed, this repo had its own snap. That version is kept under the
tag [`v0.1-standalone`](https://github.com/salmanfarisvp/edge-vision-core/tree/v0.1-standalone).

## Roadmap

- Physical AI: switch an LED or buzzer through the `gpio` interface when a chosen object
  is detected.
- Pi Camera Module (CSI) support through libcamera.
