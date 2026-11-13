# Bundled model

`yolov5-coco-320-int8-linux-aarch64.eim` is the snap's default model. It's packed into
the snap's **`model` component** (`edge-vision-core+model_<version>.comp`) as
`default.eim`, and used whenever no `/var/snap/edge-vision-core/common/model.eim` is
present.

| | |
| --- | --- |
| Architecture | YOLOv5, pretrained on COCO (80 classes) |
| Input | 320×320 RGB |
| Quantization | int8 |
| Target | Edge Impulse Linux (AARCH64) `.eim`, built with Edge Impulse Studio |
| Source project | Clone of [YOLOv5 COCO Pretrained](https://studio.edgeimpulse.com/public/382356/live), deploy version 12 |
| Measured speed | ~15 FPS, ~60 ms per frame on a Raspberry Pi 5 CPU |
| Size | ~15 MB |

The project's classes are named `class 1` … `class 80`. The app maps them to COCO names
(`person`, `bicycle`, ... `toothbrush`) automatically.

## License

YOLOv5 and its COCO-pretrained weights are released by Ultralytics under the
[AGPL-3.0 license](https://github.com/ultralytics/yolov5/blob/master/LICENSE). That
license applies to this model file. To use it commercially without the AGPL, you need an
Ultralytics license, or swap in a model you trained yourself (see below).

## Using your own model

Build any Edge Impulse **image** project for **Linux (AARCH64)** and copy it to the Pi:

```
sudo cp your-model.eim /var/snap/edge-vision-core/common/model.eim
```

The app picks it up within about 3 seconds. Delete that file to go back to the component's
model.
