"""Perception's note to the model, from hand-made detector state. No models, no camera."""

import time
import unittest
from collections import deque
from types import SimpleNamespace

import numpy as np

from brain import perception as P


class NoteTests(unittest.TestCase):
    def fresh(self):
        p = P.Perception(eyes=None)
        p.ready = True
        p._frame_at = time.time()
        return p

    def test_off_or_stale_says_nothing(self):
        p = P.Perception(eyes=None)
        self.assertEqual(p.describe(), "")              # models not loaded
        p.ready = True
        p._frame_at = time.time() - 10
        self.assertEqual(p.describe(), "")              # no live picture

    def test_person_gesture_and_things(self):
        p, now = self.fresh(), time.time()
        p._people.append((now, 1))
        p._face = {"at": now, "smiling": True, "mouth_open": False, "eyes_closed": False, "looking": True,
                   "distance_m": 1.1, "yaw": 3, "pitch": -2}
        p._gesture = ("thumbs up", now)
        p._holding = ("cup", now)
        p._objects = {"laptop": deque([now, now]), "cup": deque([now, now]), "chair": deque([now])}
        note = p.describe()
        self.assertIn("one person about 1 m away, looking at you, smiling, showing a thumbs up, holding a cup", note)
        self.assertIn("Also in view: laptop", note)
        self.assertNotIn("chair", note)                 # seen once: not trusted yet
        self.assertNotIn("Also in view: laptop, cup", note)   # the held cup isn't listed twice

    def test_nobody(self):
        p, now = self.fresh(), time.time()
        p._objects = {"keyboard": deque([now, now, now])}
        self.assertIn("no one in view. Also in view: keyboard", p.describe())

    def test_wave_beats_other_gestures(self):
        p, now = self.fresh(), time.time()
        p._people.append((now, 1))
        p._waved_at = now
        p._gesture = ("open hand", now)
        self.assertIn("waving", p.describe())

    def test_asleep_watches_only_hands(self):
        import cv2

        class Hands:
            def recognize(self, frame):
                return SimpleNamespace(hand_landmarks=[], gestures=[])

        class Unused:
            def __getattr__(self, name):
                raise AssertionError("an awake-only model ran while asleep")

        p = P.Perception(eyes=None)
        p._gest, p._faces, p._det, p._sig = Hands(), Unused(), Unused(), Unused()
        p.awake = lambda: False
        for _ in range(4):                              # faces / objects would run on every other look
            p._look(np.zeros((48, 64, 3), np.uint8), time.time(), cv2)
        self.assertEqual(p.boxes, [])

    def test_holding_overlap(self):
        hand = (100, 100, 40, 40)
        self.assertGreater(P._iou_part((88, 88, 64, 64), (110, 110, 20, 20)), 0.9)   # cup inside the grip
        self.assertEqual(P._iou_part(hand, (300, 300, 20, 20)), 0.0)


if __name__ == "__main__":
    unittest.main()
