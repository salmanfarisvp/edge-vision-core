#!/usr/bin/env python3
"""Edge Impulse live camera demo for Ubuntu Core.

Grabs frames from a V4L2 camera, runs them through an Edge Impulse .eim
model, and serves the annotated video (MJPEG) plus JSON results over HTTP.
Ubuntu Frame shows the page full screen via wpe-webkit-mir-kiosk; any
browser on the network can open it too.

The .eim is a standalone executable. We start it with a Unix socket path and
exchange JSON messages with it, which is what the edge_impulse_linux SDK does
under the hood, without pulling in the SDK's audio dependencies.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.environ.get("SNAP", os.path.dirname(HERE))
COMMON = os.environ.get("SNAP_COMMON", os.getcwd())
MODEL_PATH = os.path.join(COMMON, "model.eim")  # user's model, wins over the bundled one


def _component_dir(name):
    """Mount point of one of this snap's components (snapd 2.67+)."""
    if "SNAP_COMPONENTS" in os.environ:  # snapd 2.78+
        return os.path.join(os.environ["SNAP_COMPONENTS"], name)
    return os.path.join(os.environ["SNAP"], "..", "components",
                        os.environ.get("SNAP_REVISION", ""), name)


# Default model: the snap's `model` component, or models/ in a repo checkout.
DEFAULT_MODEL = (os.path.join(_component_dir("model"), "default.eim") if "SNAP" in os.environ
                 else os.path.join(os.path.dirname(os.path.dirname(HERE)), "models",
                                   "yolov5-coco-320-int8-linux-aarch64.eim"))
WEB_DIR = os.path.join(SNAP, "www")


# COCO's 80 classes in training order. Some public Edge Impulse YOLO projects
# ship with placeholder labels ("class 1" ... "class 80"); we map those back.
COCO_LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


def coco_label_map(labels):
    """{"class 1": "person", ...} when a model has 80 placeholder labels, else {}."""
    if len(labels) != len(COCO_LABELS):
        return {}
    mapping = {}
    for label in labels:
        parts = str(label).split()
        if len(parts) != 2 or parts[0].lower() != "class" or not parts[1].isdigit():
            return {}
        idx = int(parts[1]) - 1
        if not 0 <= idx < len(COCO_LABELS):
            return {}
        mapping[label] = COCO_LABELS[idx]
    return mapping


def log(*args):
    print(*args, flush=True)


def snap_get(key, default):
    """Read a snap option; outside a snap, fall back to an env var (PORT, ...)."""
    try:
        out = subprocess.run(["snapctl", "get", key], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return out or default
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return os.environ.get(key.upper().replace("-", "_"), default)


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

def fetch_model():
    """Download model.eim from `model-url` if set and not fetched already."""
    url = snap_get("model-url", "")
    marker = MODEL_PATH + ".url"
    current = open(marker).read().strip() if os.path.exists(marker) else ""
    if url and (url != current or not os.path.exists(MODEL_PATH)):
        log(f"Downloading model from {url}")
        tmp = MODEL_PATH + ".part"
        urllib.request.urlretrieve(url, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, MODEL_PATH)
        with open(marker, "w") as f:
            f.write(url)
    if os.path.exists(MODEL_PATH):
        # scp/cp often drops the exec bit; the .eim must be executable.
        os.chmod(MODEL_PATH, 0o755)


class EimRunner:
    def __init__(self, path):
        self._dir = tempfile.mkdtemp()
        sock_path = os.path.join(self._dir, "runner.sock")
        self.proc = subprocess.Popen([path, sock_path])
        deadline = time.time() + 30
        while not os.path.exists(sock_path):
            if self.proc.poll() is not None:
                raise RuntimeError(f"model exited with code {self.proc.returncode} "
                                   "(is it the Linux AARCH64 build?)")
            if time.time() > deadline:
                raise RuntimeError("timed out waiting for the model to start")
            time.sleep(0.1)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(sock_path)
        self.sock.settimeout(15)
        self._id = 0

        hello = self._send({"hello": 1})
        self.params = hello["model_parameters"]
        project = hello.get("project", {})
        self.name = (f"{project.get('owner', '')} / {project.get('name', '')} "
                     f"v{project.get('deploy_version', '?')}").strip(" /")
        self.width = int(self.params["image_input_width"])
        self.height = int(self.params["image_input_height"])
        self.channels = int(self.params.get("image_channel_count", 3))
        self.kind = self.params.get("model_type", "classification")
        if not self.width or not self.height:
            raise RuntimeError("this model has no image input; use an image project")
        self.label_map = coco_label_map(self.params.get("labels", []))
        if self.label_map:
            log("Model has placeholder labels 'class 1..80'; showing COCO names instead")

    def _send(self, msg):
        self._id += 1
        msg["id"] = self._id
        self.sock.sendall(json.dumps(msg).encode())
        buf = b""
        while True:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("model closed the connection")
            buf += chunk
            try:
                resp = json.loads(buf.rstrip(b"\x00").decode())
                break
            except ValueError:
                continue  # response not complete yet
        if not resp.get("success", False):
            raise RuntimeError(resp.get("error", "model returned an error"))
        return resp

    def classify(self, frame):
        """Classify a BGR frame. Box coordinates come back in frame pixels."""
        fh, fw = frame.shape[:2]
        # Centre-crop to the model's aspect ratio, as Studio does, then resize.
        target = self.width / self.height
        if fw / fh > target:
            cw, ch = int(fh * target), fh
        else:
            cw, ch = fw, int(fw / target)
        ox, oy = (fw - cw) // 2, (fh - ch) // 2
        crop = frame[oy:oy + ch, ox:ox + cw]
        small = cv2.resize(crop, (self.width, self.height), interpolation=cv2.INTER_AREA)

        if self.channels == 1:
            g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.uint32)
            feats = (g << 16) | (g << 8) | g
        else:
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.uint32)
            feats = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]

        result = self._send({"classify": feats.flatten().tolist()})["result"]
        sx, sy = cw / self.width, ch / self.height
        name = lambda label: self.label_map.get(label, label)
        boxes = [{
            "label": name(b["label"]), "value": float(b["value"]),
            "x": int(ox + b["x"] * sx), "y": int(oy + b["y"] * sy),
            "w": int(b["width"] * sx), "h": int(b["height"] * sy),
        } for b in result.get("bounding_boxes", [])]
        classes = {name(k): float(v) for k, v in result.get("classification", {}).items()}
        return classes, boxes, (ox, oy, cw, ch)

    def close(self):
        try:
            self.sock.close()
        finally:
            self.proc.kill()
            self.proc.wait()
            shutil.rmtree(self._dir, ignore_errors=True)


# --------------------------------------------------------------------------
# Capture + inference loop
# --------------------------------------------------------------------------

class Pipeline:
    def __init__(self, camera, threshold):
        self.camera = camera
        self.threshold = threshold
        self.cond = threading.Condition()
        self.jpeg = None
        self.seq = 0
        self.status = {"state": "starting", "message": "Starting..."}

    def _publish(self, jpeg, status):
        with self.cond:
            if jpeg is not None:
                self.jpeg = jpeg
                self.seq += 1
            self.status = status
            self.cond.notify_all()

    @staticmethod
    def _model_key():
        """(path, mtime) of the model to use: the user's copy wins over the bundled one."""
        for path in (MODEL_PATH, DEFAULT_MODEL):
            try:
                return path, os.path.getmtime(path)
            except OSError:
                continue
        return None

    @staticmethod
    def _load_model(path):
        if path == MODEL_PATH:
            os.chmod(path, 0o755)  # scp/cp often drops the exec bit
        runner = EimRunner(path)
        labels = runner.params.get("labels", [])
        source = "model component" if path == DEFAULT_MODEL else path
        log(f"Loaded model ({source}): {runner.name} ({runner.kind}, "
            f"{runner.width}x{runner.height}x{runner.channels}, {len(labels)} labels: "
            f"{', '.join(map(str, labels[:8]))}{' ...' if len(labels) > 8 else ''})")
        return runner

    def run(self):
        cap, runner, loaded_key, model_error = None, None, None, None
        last_model_check = 0.0
        fps, last_frame = 0.0, time.time()

        while True:
            # (Re)load on start, when model.eim changes, or when it's added/removed.
            now = time.time()
            if now - last_model_check > 3:
                last_model_check = now
                key = self._model_key()
                if key != loaded_key:
                    if runner:
                        runner.close()
                        runner = None
                    loaded_key = key  # set even on failure, so a bad file isn't retried in a loop
                    model_error = None
                    if key:
                        try:
                            runner = self._load_model(key[0])
                        except Exception as e:  # keep streaming video without a model
                            model_error = str(e)
                            log(f"Model failed to load: {e}")

            if cap is None or not cap.isOpened():
                # V4L2 on Linux (the Pi); the default backend elsewhere (macOS dev).
                backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
                cap = cv2.VideoCapture(self.camera, backend)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                if not cap.isOpened():
                    self._publish(None, {"state": "error", "message":
                        f"No camera at /dev/video{self.camera}. "
                        "Is it plugged in and is the camera interface connected?"})
                    cap = None
                    time.sleep(2)
                    continue
                log(f"Camera /dev/video{self.camera} opened")

            ok, frame = cap.read()
            if not ok:
                cap.release()
                cap = None
                time.sleep(0.5)
                continue

            status = {"state": "ok", "model": None, "kind": None,
                      "top": None, "classes": {}, "boxes": [], "latency_ms": None}
            if runner:
                t0 = time.time()
                try:
                    classes, boxes, (ox, oy, cw, ch) = runner.classify(frame)
                except Exception as e:
                    log(f"Inference failed, reloading model: {e}")
                    runner.close()
                    runner, loaded_key = None, None  # reload on the next check
                    continue
                latency = (time.time() - t0) * 1000
                boxes = [b for b in boxes if b["value"] >= self.threshold]
                # Show the region the model actually sees.
                cv2.rectangle(frame, (ox, oy), (ox + cw - 1, oy + ch - 1), (90, 90, 90), 1)
                for b in boxes:
                    cv2.rectangle(frame, (b["x"], b["y"]),
                                  (b["x"] + b["w"], b["y"] + b["h"]), (60, 220, 120), 2)
                    cv2.putText(frame, f"{b['label']} {b['value']:.2f}",
                                (b["x"], max(14, b["y"] - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                                0.5, (60, 220, 120), 1, cv2.LINE_AA)
                top = None
                if boxes:
                    best = max(boxes, key=lambda b: b["value"])
                    top = {"label": best["label"], "value": best["value"]}
                elif classes:
                    label, value = max(classes.items(), key=lambda kv: kv[1])
                    if value >= self.threshold:
                        top = {"label": label, "value": value}
                status.update(model=runner.name, kind=runner.kind, top=top,
                              classes=classes, boxes=boxes,
                              latency_ms=round(latency, 1))
            elif model_error:
                status.update(state="warn", message=f"Model error: {model_error}")
            else:
                status.update(state="warn", message=
                    f"No model. Install the model component, or copy a Linux (AARCH64) .eim to {MODEL_PATH}")

            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - last_frame, 1e-6))
            last_frame = now
            status["fps"] = round(fps, 1)
            status["threshold"] = self.threshold

            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            self._publish(jpeg.tobytes() if ok else None, status)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def make_handler(pipeline):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # keep `snap logs` readable

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/frame.jpg":
                # One JPEG per request. ?after=<seq> waits for a newer frame, so
                # the page pulls at the camera's pace without duplicates.
                try:
                    after = int(dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                                .get("after", -1))
                except ValueError:
                    after = -1
                with pipeline.cond:
                    pipeline.cond.wait_for(
                        lambda: pipeline.jpeg is not None and pipeline.seq != after, timeout=2)
                    jpeg, seq = pipeline.jpeg, pipeline.seq
                if jpeg is None:
                    self._send(503, "text/plain", b"no frame yet")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Seq", str(seq))
                self.end_headers()
                self.wfile.write(jpeg)
            elif path == "/":
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    self._send(200, "text/html; charset=utf-8", f.read())
            elif path == "/api/status":
                with pipeline.cond:
                    body = json.dumps(pipeline.status).encode()
                self._send(200, "application/json", body)
            elif path == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                seen = -1
                try:
                    while True:
                        with pipeline.cond:
                            pipeline.cond.wait_for(lambda: pipeline.seq != seen, timeout=5)
                            jpeg, seen = pipeline.jpeg, pipeline.seq
                        if jpeg is None:
                            continue
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                         b"Content-Length: " + str(len(jpeg)).encode() +
                                         b"\r\n\r\n" + jpeg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self._send(404, "text/plain", b"not found")

    return Handler


def main():
    port = int(snap_get("port", "8000"))
    camera = int(snap_get("camera", "0"))
    threshold = float(snap_get("threshold", "0.6"))

    try:
        fetch_model()
    except Exception as e:
        log(f"Model download failed: {e}")

    pipeline = Pipeline(camera, threshold)
    threading.Thread(target=pipeline.run, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(pipeline))
    server.daemon_threads = True
    log(f"Serving on http://0.0.0.0:{port}  (camera /dev/video{camera}, threshold {threshold})")
    server.serve_forever()


if __name__ == "__main__":
    main()
