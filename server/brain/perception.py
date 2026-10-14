"""Perception: what Rocky notices on camera, worked out on this computer.

A background thread watches the robot's camera stream (a few frames a second) with three small open models:

  RF-DETR Nano (Apache-2.0, Roboflow)      everyday objects: cup, phone, laptop, scissors... (80 kinds)
  MediaPipe gesture recognizer (Apache-2.0) hands and what they're doing: thumbs up/down, open hand, fist,
                                            peace sign, pointing; a wave from an open hand moving side to side
  MediaPipe face landmarker (Apache-2.0)    faces: smiling, mouth open, eyes closed, looking at Rocky or away,
                                            roughly how far
  SigLIP (Apache-2.0, Google)               names what the detector found, and what's in your hand, from a word
                                            list (WORDS below, plus your own from the dashboard), so a pen is a pen
                                            and not "toothbrush", the nearest of the detector's 80 kinds

and keeps a short running note ("one person about 1 m away, looking at you, smiling, holding a cup; also in view:
laptop, keyboard") that goes to the model with every question, plus gesture events for quick reactions (a wave
wakes him). It also stands aside while your words are being turned into text, so they come back sooner. Nothing
leaves this computer; only the note and, when asked, the picture go to the model provider.

While Rocky is asleep only the hands are watched, a few times a second (a wave is all that matters then): the
object, face and naming models cost about a second of CPU time every second, the hand model a twentieth of that.

The models download on first use into server/models/ (git-ignored), pinned to fixed versions and checked against
their SHA-256. If anything fails, perception switches itself off and Rocky carries on without it.
"""

from __future__ import annotations

import hashlib
import math
import ssl
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import config

MODELS = Path(__file__).resolve().parent.parent / "models"
DOWNLOADS = {  # file: (url, sha256)
    "rfdetr_nano_int8.onnx": (
        "https://huggingface.co/onnx-community/rfdetr_nano-ONNX/resolve/eae21cee0687a91bcf9fa071605c48d7705d2d91/onnx/model_int8.onnx",
        "b7ac65b911fdb07b2f3f17b4a4e3bfada76e202f8b9c536b91159945c9fea7e1"),
    "gesture_recognizer.task": (
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
        "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
    "siglip_vision_q.onnx": (
        "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/4649052661e53c7000355844105f8a1792088239/onnx/vision_model_quantized.onnx",
        "ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058"),
    "siglip_text_q.onnx": (
        "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/4649052661e53c7000355844105f8a1792088239/onnx/text_model_quantized.onnx",
        "ad0329b1f35acc66d8953ff2559ce358da8eb0a7011794cf951523d63a4dbce2"),
    "siglip_tokenizer.json": (
        "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/4649052661e53c7000355844105f8a1792088239/tokenizer.json",
        "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08"),
}


# RF-DETR's classes (COCO ids) and how Rocky should say them.
LABELS = {1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane", 6: "bus", 7: "train", 8: "truck",
          9: "boat", 10: "traffic light", 11: "fire hydrant", 13: "stop sign", 14: "parking meter", 15: "bench",
          16: "bird", 17: "cat", 18: "dog", 19: "horse", 20: "sheep", 21: "cow", 22: "elephant", 23: "bear",
          24: "zebra", 25: "giraffe", 27: "backpack", 28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase",
          34: "frisbee", 35: "skis", 36: "snowboard", 37: "ball", 38: "kite", 39: "baseball bat",
          40: "baseball glove", 41: "skateboard", 42: "surfboard", 43: "tennis racket", 44: "bottle",
          46: "wine glass", 47: "cup", 48: "fork", 49: "knife", 50: "spoon", 51: "bowl", 52: "banana", 53: "apple",
          54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza", 60: "donut",
          61: "cake", 62: "chair", 63: "couch", 64: "plant", 65: "bed", 67: "table", 70: "toilet", 72: "screen",
          73: "laptop", 74: "mouse", 75: "remote", 76: "keyboard", 77: "phone", 78: "microwave", 79: "oven",
          80: "toaster", 81: "sink", 82: "refrigerator", 84: "book", 85: "clock", 86: "vase", 87: "scissors",
          88: "teddy bear", 89: "hair dryer", 90: "toothbrush"}
NOT_HELD = {"person", "chair", "couch", "bed", "table", "toilet", "screen", "microwave", "oven", "sink",
            "refrigerator", "bench", "car", "bus", "train", "truck", "boat", "motorcycle", "airplane"}
GESTURES = {"Thumb_Up": "thumbs up", "Thumb_Down": "thumbs down", "Victory": "peace sign",
            "Pointing_Up": "pointing", "Open_Palm": "open hand", "Closed_Fist": "fist", "ILoveYou": "I-love-you sign"}
OBJECT_SCORE = 0.5
RECENT = 2.5          # seconds a sighting counts as "now"
FACE_HALF_WIDTH_M = 0.07

# What SigLIP can call a thing. The detector's own names are in here too, so the two can agree. Add your own in the
# dashboard (Settings > Vision); a specific name ("Rocky's head board") works as long as it describes what it looks
# like.
WORDS = sorted(set(LABEL for LABEL in (
    # desk, computer, electronics bench
    "pen", "pencil", "marker", "highlighter", "notebook", "book", "sticky note", "piece of paper", "envelope",
    "laptop", "keyboard", "mouse", "computer monitor", "phone", "tablet", "headphones", "earbuds", "smartwatch",
    "USB cable", "charger", "power strip", "game controller", "remote", "calculator", "stapler", "tape", "ruler",
    "scissors", "glue stick", "paper clip", "desk lamp", "speaker", "microphone", "webcam", "camera",
    "circuit board", "breadboard", "Arduino board", "Raspberry Pi", "microcontroller board", "computer chip",
    "jumper wires", "wire", "battery", "multimeter", "soldering iron", "solder", "screwdriver", "pliers",
    "wire cutters", "wrench", "hammer", "tape measure", "utility knife", "hot glue gun", "3D printed part",
    "servo motor", "motor", "LED", "sensor", "robot", "toy robot",
    # kitchen, food, drink
    "cup", "coffee mug", "water bottle", "bottle", "can of soda", "glass", "wine glass", "bowl", "plate", "fork",
    "knife", "spoon", "banana", "apple", "orange", "sandwich", "pizza", "donut", "cake", "cookie", "snack bag",
    "candy bar", "coffee",
    # personal
    "glasses", "sunglasses", "keys", "wallet", "watch", "ring", "hat", "cap", "hoodie", "jacket", "backpack",
    "bag", "handbag", "umbrella", "tie", "shoe", "sock", "toothbrush", "comb", "hair dryer", "tissue box",
    "face mask", "credit card", "coin", "money",
    # around the room
    "chair", "couch", "bed", "table", "desk", "shelf", "plant", "vase", "clock", "picture frame", "poster",
    "window", "door", "lamp", "screen", "television", "fan", "box", "cardboard box", "pillow", "blanket",
    "trash can", "light bulb", "candle",
    # play, animals
    "ball", "frisbee", "teddy bear", "stuffed animal", "toy car", "Lego bricks", "Rubik's cube", "playing cards",
    "dice", "guitar", "drumsticks", "skateboard", "cat", "dog", "bird", "fish",
) + tuple(LABELS.values())))
# Things that mean "nothing in particular": a hand crop that looks most like these isn't holding anything.
NOTHING = ["hand", "empty hand", "fingers", "arm", "face", "person", "shirt", "wall", "ceiling", "blurry photo"]
NAME_MIN = 0.055      # SigLIP similarity needed to trust a name (below it, keep the detector's)
NAME_EVERY = 0.6      # seconds between naming passes (each is ~75 ms per crop)
ASLEEP_FPS = 5.0      # looks per second while he's asleep: hands only, enough to catch a wave


def ensure_models() -> None:
    """Download any missing model (once), checking its SHA-256."""
    MODELS.mkdir(exist_ok=True)
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for name, (url, sha) in DOWNLOADS.items():
        path = MODELS / name
        if path.exists():
            continue
        print(f"perception: downloading {name} (first run only)...")
        req = urllib.request.Request(url, headers={"User-Agent": "desk-robot"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError(f"{name}: download doesn't match its checksum")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / max(1.0, aw * ah + bw * bh - inter)


def _iou_part(a, b) -> float:
    """How much of box b (x, y, w, h) lies inside box a."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy / max(1.0, bw * bh)


class Perception:
    def __init__(self, eyes, on_gesture: Callable[[str], None] | None = None) -> None:
        self.eyes = eyes
        self.on_gesture = on_gesture       # called (from this thread) with "wave", "thumbs up", "thumbs down"
        self.awake: Callable[[], bool] = lambda: True   # main.py: is Rocky awake? Asleep = hands only
        self.paused: Callable[[], bool] = lambda: False  # main.py: hold off (your words are being transcribed)
        self.enabled = True
        self.ready = False
        self.error = ""
        self.boxes: list[tuple[str, int, int, int, int]] = []   # newest frame, for the live view overlay
        self._lock = threading.Lock()
        self._objects: dict[str, deque] = {}    # label -> times seen
        self._people: deque = deque(maxlen=40)  # (time, count)
        self._face: dict | None = None
        self._gesture: tuple[str, float] = ("", 0.0)
        self._holding: tuple[str, float] = ("", 0.0)
        self._waved_at = 0.0
        self._palm: deque = deque(maxlen=20)    # (time, wrist x 0..1) while an open hand is up
        self._streak: tuple[str, int] = ("", 0)
        self._event_at: dict[str, float] = {}
        self._frame_at = 0.0
        self._looks = 0
        self._extra_words: list[str] = []
        self._words_dirty = True
        self._vocab: list[str] = []
        self._text: np.ndarray | None = None    # unit text embeddings for _vocab
        self._named: list[tuple[tuple, str, float, float]] = []   # (box, name, score, time) from recent passes
        self._named_at = 0.0
        self._held_name: tuple[str, float] = ("", 0.0)

    def set_words(self, extra: list[str]) -> None:
        """Your own words for things (dashboard); they're added to WORDS on the next look."""
        extra = [w.strip() for w in extra if w.strip()][:100]
        if extra != self._extra_words:
            self._extra_words = extra
            self._words_dirty = True

    def start(self) -> None:
        threading.Thread(target=self._run, name="perception", daemon=True).start()

    # ── the models ──
    def _load(self) -> None:
        import onnxruntime as ort
        from mediapipe.tasks.python import BaseOptions, vision
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2          # leave the rest of the CPU to speech-to-text
        opts.log_severity_level = 3
        self._det = ort.InferenceSession(str(MODELS / "rfdetr_nano_int8.onnx"), opts, providers=["CPUExecutionProvider"])
        self._gest = vision.GestureRecognizer.create_from_options(vision.GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(MODELS / "gesture_recognizer.task")), num_hands=2,
            min_hand_detection_confidence=0.5))
        self._faces = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODELS / "face_landmarker.task")), num_faces=2,
            output_face_blendshapes=True, output_facial_transformation_matrixes=True))
        self._sig = ort.InferenceSession(str(MODELS / "siglip_vision_q.onnx"), opts, providers=["CPUExecutionProvider"])
        self._opts = opts

    def _update_words(self) -> None:
        """Text embeddings for the word list: worked out once per list and kept in server/models/ (the text model
        is only loaded when the list changes)."""
        self._words_dirty = False
        vocab = sorted(set(WORDS) | set(self._extra_words))
        allwords = vocab + [w for w in NOTHING if w not in vocab]
        key = hashlib.sha256(("\n".join(allwords) + DOWNLOADS["siglip_text_q.onnx"][1]).encode()).hexdigest()[:16]
        cache = MODELS / f"siglip_words_{key}.npy"
        if cache.exists():
            text = np.load(cache)
        else:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            tok = Tokenizer.from_file(str(MODELS / "siglip_tokenizer.json"))
            tok.enable_padding(length=64, pad_id=tok.token_to_id("</s>") or 1)
            tok.enable_truncation(64)
            sess = ort.InferenceSession(str(MODELS / "siglip_text_q.onnx"), self._opts, providers=["CPUExecutionProvider"])
            parts = []
            for i in range(0, len(allwords), 32):
                ids = np.array([e.ids for e in tok.encode_batch([f"a photo of a {w}." for w in allwords[i:i + 32]])], dtype=np.int64)
                parts.append(sess.run(None, {"input_ids": ids})[1])
            text = np.concatenate(parts)
            text /= np.linalg.norm(text, axis=1, keepdims=True)
            for old in MODELS.glob("siglip_words_*.npy"):
                old.unlink()
            np.save(cache, text)
        self._vocab, self._text = allwords, text.astype(np.float32)

    def _name(self, img, boxes: list[tuple], cv2) -> list[tuple[str, float, float]]:
        """SigLIP's best word for each box (x, y, w, h): (word, similarity, lead over the runner-up)."""
        h, w = img.shape[:2]
        batch = []
        for x, y, bw, bh in boxes:
            pad = 0.15
            x0, y0 = max(0, int(x - pad * bw)), max(0, int(y - pad * bh))
            x1, y1 = min(w, int(x + bw * (1 + pad))), min(h, int(y + bh * (1 + pad)))
            crop = img[y0:max(y1, y0 + 2), x0:max(x1, x0 + 2)]
            c = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), (224, 224)).astype(np.float32) / 255.0
            batch.append(((c - 0.5) / 0.5).transpose(2, 0, 1))
        if not batch:
            return []
        v = self._sig.run(None, {"pixel_values": np.stack(batch).astype(np.float32)})[1]
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        sims = v @ self._text.T
        out = []
        for row in sims:
            top = np.argsort(-row)[:2]
            out.append((self._vocab[top[0]], float(row[top[0]]), float(row[top[0]] - row[top[1]])))
        return out

    def _cached_name(self, box, now: float) -> tuple[str, float] | None:
        for b, name, score, t in self._named:
            if now - t < 3 and _iou(b, box) > 0.4:
                return name, score
        return None

    def _run(self) -> None:
        try:
            ensure_models()
            self._load()
            self.ready = True
            print("perception: on (objects, hands, faces)")
        except Exception as e:  # missing package, no network on first run, bad file: carry on without it
            self.error = str(e)
            print(f"perception: off ({e})")
            return
        import cv2
        seq, next_at, warned = -1, 0.0, False
        while True:
            seq = self.eyes.wait_for_new(seq, timeout=1.0)
            now = time.time()
            if not self.enabled or now < next_at or not self.eyes.jpeg or self.paused():
                continue
            next_at = now + 1.0 / max(1.0, config.PERCEPTION_FPS if self.awake() else ASLEEP_FPS)
            img = cv2.imdecode(np.frombuffer(self.eyes.jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            try:
                self._look(img, self.eyes.frame_at, cv2)
            except Exception as e:
                if not warned:
                    print(f"perception: a frame failed ({e})")
                    warned = True

    def _objects_in(self, img, cv2) -> list[tuple[str, float, tuple]]:
        h, w = img.shape[:2]
        x = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (384, 384)).astype(np.float32) / 255.0
        x = ((x - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)).transpose(2, 0, 1)[None].astype(np.float32)
        boxes, logits = self._det.run(None, {"pixel_values": x})
        p = 1.0 / (1.0 + np.exp(-logits[0]))
        best, cls = p.max(-1), p.argmax(-1)
        out = []
        for i in np.where(best > OBJECT_SCORE)[0]:
            label = LABELS.get(int(cls[i]))
            if label is None:
                continue
            cx, cy, bw, bh = boxes[0][i]               # normalized centre / size
            out.append((label, float(best[i]), ((cx - bw / 2) * w, (cy - bh / 2) * h, bw * w, bh * h)))
        return out

    def _look(self, img, at: float, cv2) -> None:
        import mediapipe as mp
        h, w = img.shape[:2]
        now = time.time()
        awake = self.awake()
        self._looks += 1
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # Hands, every look: gestures change fast and a wave needs the samples.
        hands = []
        g = self._gest.recognize(frame)
        for lms, cats in zip(g.hand_landmarks, g.gestures):
            xs, ys = [p.x for p in lms], [p.y for p in lms]
            box = (min(xs) * w, min(ys) * h, (max(xs) - min(xs)) * w, (max(ys) - min(ys)) * h)
            top = cats[0] if cats else None
            name = GESTURES.get(top.category_name, "") if top is not None and top.score >= 0.6 else ""
            hands.append((name, box, lms[0].x))

        # Faces and objects every other look (they change slower and cost more); not at all while he's asleep.
        faces = objects = None
        if awake and self._looks % 2 == 0:
            faces = self._faces.detect(frame)
            objects = self._objects_in(img, cv2)

        # Names, every NAME_EVERY seconds: what's in a hand, then the biggest unnamed boxes.
        if objects is not None and now - self._named_at >= NAME_EVERY:
            if self._words_dirty or self._text is None:
                self._update_words()
            self._named_at = now
            self._named = [n for n in self._named if now - n[3] < 3]
            want: list[tuple] = []
            grips = [(hb[0] - 0.6 * hb[2], hb[1] - 0.6 * hb[3], hb[2] * 2.2, hb[3] * 2.2) for _, hb, _ in hands]
            want += grips[:1]
            todo = sorted((o for o in objects if o[0] != "person" and self._cached_name(o[2], now) is None),
                          key=lambda o: -o[2][2] * o[2][3])
            want += [o[2] for o in todo[:2]]
            names = self._name(img, want, cv2) if want else []
            if grips and names:
                word, score, lead = names[0]
                held = word if score >= NAME_MIN and word not in NOTHING else ""
                self._held_name = (held, now) if held else self._held_name
                names = names[1:]
            for box, (word, score, lead) in zip([o[2] for o in todo[:2]], names):
                self._named.append((box, word, score, now))
        if objects is not None:   # the detector's names, replaced by SigLIP's where it's sure
            renamed = []
            for label, conf, box in objects:
                got = None if label == "person" else self._cached_name(box, now)
                if got and got[1] >= NAME_MIN and got[0] not in NOTHING:
                    label = got[0]
                renamed.append((label, conf, box))
            objects = renamed

        events = []
        with self._lock:
            self._frame_at = at
            gesture = next((n for n, _, _ in hands if n and n not in ("open hand", "fist")), "")
            gesture = gesture or next((n for n, _, _ in hands if n), "")
            if gesture:
                self._gesture = (gesture, now)
            # a gesture held across two looks is an event (once every few seconds)
            streak = self._streak[1] + 1 if gesture and gesture == self._streak[0] else (1 if gesture else 0)
            self._streak = (gesture, streak)
            if gesture in ("thumbs up", "thumbs down") and streak == 2:
                events.append(gesture)
            # a wave: an open hand that moves side to side
            palm = next((wx for n, _, wx in hands if n == "open hand"), None)
            if palm is not None:
                self._palm.append((now, palm))
            recent = [x for t, x in self._palm if now - t < 1.5]
            if len(recent) >= 4 and max(recent) - min(recent) > 0.06 and now - self._waved_at > 4:
                self._waved_at = now
                self._palm.clear()
                events.append("wave")
            if faces is not None:
                self._face = self._read_face(faces, w, h, now)
                self._people.append((now, max(len(faces.face_landmarks), sum(1 for o in objects if o[0] == "person"))))
                for label, _, _ in objects:
                    if label != "person":
                        self._objects.setdefault(label, deque(maxlen=30)).append(now)
                held = ""
                for _, hb, _ in hands:
                    grip = (hb[0] - 0.3 * hb[2], hb[1] - 0.3 * hb[3], hb[2] * 1.6, hb[3] * 1.6)
                    for label, _, ob in objects:
                        if label not in NOT_HELD and _iou_part(grip, ob) > 0.3:
                            held = label
                hn = self._held_name
                if hands and hn[0] and now - hn[1] < 1.5:
                    held = hn[0]                         # SigLIP's name for what's in the hand
                if held:
                    self._holding = (held, now)
                self.boxes = [(lab, int(b[0]), int(b[1]), int(b[2]), int(b[3])) for lab, _, b in objects] + \
                             [(n or "hand", int(b[0]), int(b[1]), int(b[2]), int(b[3])) for n, b, _ in hands]
            elif not awake:
                self.boxes = [(n or "hand", int(b[0]), int(b[1]), int(b[2]), int(b[3])) for n, b, _ in hands]
        for e in events:
            if self._event_at.get(e, 0) < now - 3 and self.on_gesture is not None:
                self._event_at[e] = now
                self.on_gesture(e)

    def _read_face(self, res, w: int, h: int, now: float) -> dict | None:
        if not res.face_landmarks:
            return None
        sizes = [max(p.x for p in lm) - min(p.x for p in lm) for lm in res.face_landmarks]
        i = int(np.argmax(sizes))
        shapes = {c.category_name: c.score for c in res.face_blendshapes[i]} if res.face_blendshapes else {}
        smile = (shapes.get("mouthSmileLeft", 0) + shapes.get("mouthSmileRight", 0)) / 2
        blink = min(shapes.get("eyeBlinkLeft", 0), shapes.get("eyeBlinkRight", 0))
        yaw = pitch = 0.0
        if res.facial_transformation_matrixes:
            r = np.array(res.facial_transformation_matrixes[i])[:3, :3]
            yaw = math.degrees(math.asin(max(-1.0, min(1.0, -r[2, 0]))))
            pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
        # How far: the face's width against the camera's field of view (rough; the lens is very wide).
        hfov = config.TRACK_VFOV if config.CAMERA_ROTATE % 180 else config.TRACK_HFOV
        half = math.radians(sizes[i] * hfov / 2)
        dist = FACE_HALF_WIDTH_M / math.tan(half) if half > 0.01 else None
        return {"at": now, "smiling": smile > 0.45, "mouth_open": shapes.get("jawOpen", 0) > 0.45,
                "eyes_closed": blink > 0.6, "looking": abs(yaw) < 25 and abs(pitch) < 25,
                "distance_m": dist, "yaw": round(yaw), "pitch": round(pitch)}

    # ── what the brain reads ──
    def summary(self) -> dict:
        """The current state, for the prompt note and the dashboard."""
        now = time.time()
        with self._lock:
            live = self.ready and now - self._frame_at < 3
            people = max((n for t, n in self._people if now - t < RECENT), default=0)
            face = self._face if self._face and now - self._face["at"] < RECENT else None
            if face and not people:
                people = 1
            objects = sorted(((len([t for t in ts if now - t < RECENT]), lab) for lab, ts in self._objects.items()),
                             reverse=True)
            held = self._holding[0] if now - self._holding[1] < RECENT else ""
            objects = [lab for n, lab in objects if n >= 2 and lab != held][:8]
            gesture = self._gesture[0] if now - self._gesture[1] < RECENT else ""
            waved = now - self._waved_at < 5
        return {"live": live, "people": people, "face": face, "holding": held, "objects": objects,
                "gesture": "wave" if waved else gesture, "ready": self.ready, "error": self.error}

    def describe(self) -> str:
        """One line for the model, or "" when there's nothing useful (perception off / no live picture)."""
        s = self.summary()
        if not s["ready"] or not s["live"]:
            return ""
        bits = []
        if s["people"]:
            who = "one person" if s["people"] == 1 else f"{s['people']} people"
            f = s["face"]
            if f:
                d = f["distance_m"]
                if d is not None:
                    who += " very close" if d < 0.4 else f" about {max(0.5, round(d * 2) / 2):g} m away"
                who += ", looking at you" if f["looking"] else ", looking away"
                for key, words in (("smiling", "smiling"), ("eyes_closed", "eyes closed"), ("mouth_open", "mouth open")):
                    if f[key]:
                        who += ", " + words
            if s["gesture"] == "wave":
                who += ", waving"
            elif s["gesture"] and s["gesture"] not in ("open hand", "fist"):
                who += f", showing a {s['gesture']}"
            if s["holding"]:
                who += f", holding a {s['holding']}"
            bits.append(who)
        else:
            bits.append("no one in view")
        note = "; ".join(bits)
        if s["objects"]:
            note += ". Also in view: " + ", ".join(s["objects"])
        return f"(What your camera's detectors notice right now, may be wrong: {note}.)"
