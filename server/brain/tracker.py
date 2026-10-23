"""Tracker: detect faces in camera frames and steer the head toward a face.

This follows a face by its position and size; it does not recognize names or
identity. Face identity is handled separately by the opt-in local registry.

Runs in its own thread (OpenCV is blocking). For every new frame from Eyes
it detects faces (YuNet, ~6 ms at 640x480), picks the biggest, works out how
far off-center it is, and nudges the pan/tilt estimate toward it. The
proposed head pose goes into an outbox; main.py sends it to the robot.

The camera rides on the head, so where the face sits in the picture says how
far it is off the way the head was pointing. But a frame shows the head as it
was a moment ago (TRACK_LATENCY_S), and the head takes a while to get where it
was sent. So we run a copy of the firmware's motion profile to know where the
head pointed when each frame was taken, add the face's offset to get where the
face really is, and send the head a fraction (TRACK_GAIN) of the way there.
Adding each frame's error to the latest command instead piles up moves the
camera hasn't seen yet: the head overshoots, swings back and loses the face.
Tiny errors are ignored (TRACK_DEADBAND).
"""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable

import cv2
import numpy as np

from . import config
from .eyes import Eyes
from deskbot_local.identity import FaceIdentityService, FaceRecognitionError, FaceRegion, IdentityResult
from deskbot_local.dashboard_enrollment import FaceEnrollmentSession
from deskbot_local.recognition_runtime import RecognitionRuntime
from .face_detector import YuNetFaceDetector
SEND_EVERY = 0.08   # s between head commands (frames come every 0.1 s)


class Motion:
    """One neck axis as the firmware moves it (ServoNeck::update: 50 Hz, speed and acceleration limited), so we can
    tell where the head was pointing at any moment of the last two seconds."""

    DT = 0.02

    def __init__(self, speed: float, accel: float) -> None:
        self.speed, self.accel = speed, accel
        self.pos = self.target = self.vel = 0.0
        self.t = time.time()
        self.hist: deque[tuple[float, float]] = deque([(self.t, 0.0)], maxlen=100)

    def set_target(self, deg: float, now: float) -> None:
        self.advance(now)
        self.target = deg

    def advance(self, now: float) -> None:
        if now - self.t > 3.0:                  # idle a long while: it has long arrived
            self.pos, self.vel, self.t = self.target, 0.0, now - self.DT
        while self.t + self.DT <= now:
            self.t += self.DT
            diff = self.target - self.pos
            if abs(diff) > 0.05 or abs(self.vel) > 0.5:
                h = self.accel * self.DT * 0.5
                want = min(self.speed, math.sqrt(h * h + 2 * self.accel * abs(diff)) - h) * (1 if diff > 0 else -1)
                self.vel += max(-self.accel * self.DT, min(self.accel * self.DT, want - self.vel))
                step = self.vel * self.DT
                if (diff > 0 and step >= diff) or (diff < 0 and step <= diff) or (abs(diff) < 0.05 and abs(self.vel) < 3):
                    self.pos, self.vel = self.target, 0.0
                else:
                    self.pos += step
            self.hist.append((self.t, self.pos))

    def arrival_in(self, now: float) -> float:
        """Seconds until the head stops at its target (0 if it's there already)."""
        self.advance(now)
        pos, vel, t, hist = self.pos, self.vel, self.t, self.hist
        self.hist = deque(maxlen=1)              # simulate on a copy of the state, then put it back
        steps = 0
        while (self.pos != self.target or self.vel) and steps < 250:
            steps += 1
            self.advance(self.t + self.DT)
        left = max(0.0, self.t - now)
        self.pos, self.vel, self.t, self.hist = pos, vel, t, hist
        return left

    def at(self, when: float) -> float:
        """Where the head was at time `when` (the oldest we remember if it's further back)."""
        self.advance(when)
        for t, pos in reversed(self.hist):
            if t <= when:
                return pos
        return self.hist[0][1]


class Tracker:
    def __init__(
        self,
        eyes: Eyes,
        on_pose: Callable[[float | None, float | None, bool], None],
        *,
        face_detector: YuNetFaceDetector | None = None,
        identity_service: FaceIdentityService | None = None,
        recognition_runtime: RecognitionRuntime | None = None,
    ) -> None:
        """on_pose(pan, tilt, tracking) is called from the tracker thread
        whenever the head should move (None = leave that axis alone)."""
        self.eyes = eyes
        self.on_pose = on_pose
        self.pan = 0.0     # our estimate of where the head is (deg)
        self.tilt = 0.0
        self.tracking = False
        self.face: tuple[int, int, int, int] | None = None  # x, y, w, h in the frame
        self.last_seen = 0.0
        self.enabled = config.TRACKING
        self._face_detector = face_detector or YuNetFaceDetector()
        self.identity_service = identity_service
        self.enrollment_session: FaceEnrollmentSession | None = None
        self.recognition_runtime = recognition_runtime
        self.identity_status = (
            recognition_runtime.status()
            if recognition_runtime is not None
            else {
                "enabled": False,
                "privacy_mode": True,
                "model_available": False,
                "status": "disabled",
                "display_name": "Unknown",
                "similarity_score": None,
                "reason": "disabled",
            }
        )
        self._identity_error_reported = False
        self._enrollment_lock = threading.Lock()
        self._latest_enrollment_frame: tuple[object, tuple[FaceRegion, ...], float] | None = None
        self._last_sent = 0.0
        self._lost_reported = True
        self.motion = {"pan": Motion(config.TRACK_PAN_SPEED, config.TRACK_PAN_ACCEL),
                       "tilt": Motion(config.TRACK_TILT_SPEED, config.TRACK_TILT_ACCEL)}

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def face_detector(self) -> YuNetFaceDetector:
        """The shared detection provider used for tracking and identity regions."""
        return self._face_detector

    def arrival_in(self) -> float:
        """Seconds until the head finishes its current move, on both axes."""
        now = time.time()
        return max(m.arrival_in(now) for m in self.motion.values())

    # Called from main.py when it moves the head itself, so we stay in sync.
    def note_pose(self, pan: float | None = None, tilt: float | None = None) -> None:
        now = time.time()
        if pan is not None:
            self.pan = pan
            self.motion["pan"].set_target(pan, now)
        if tilt is not None:
            self.tilt = tilt
            self.motion["tilt"].set_target(tilt, now)

    def enroll_person(self, person_id: str) -> None:
        """Use the most recent in-memory tracker detection for an explicit enrollment request."""
        identity_service = self.identity_service
        if identity_service is None:
            raise ValueError("local identity recognition is unavailable or disabled")
        with self._enrollment_lock:
            detection = self._latest_enrollment_frame
        if detection is None or time.monotonic() - detection[2] > 2.0:
            raise ValueError("no recent camera detection is available")
        frame, regions, _detected_at = detection
        if len(regions) != 1:
            raise ValueError("enrollment requires exactly one face in the latest frame")
        identity_service.enroll_detected_face(person_id, frame, regions[0])

    def set_identity_service(self, service: FaceIdentityService | None) -> None:
        self.identity_service = service
        if service is None:
            with self._enrollment_lock:
                self._latest_enrollment_frame = None

    def set_enrollment_session(self, session: FaceEnrollmentSession | None) -> None:
        """Attach an explicit dashboard workflow to this one-pass camera detector."""
        self.enrollment_session = session

    def _run(self) -> None:
        seq = -1
        while True:
            seq = self.eyes.wait_for_new(seq, timeout=1.0)
            jpeg, seen_at = self.eyes.jpeg, self.eyes.frame_at
            if not jpeg:
                continue
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, w = img.shape[:2]
            face = None
            regions: tuple[FaceRegion, ...] = ()
            identity_service = self.identity_service
            recognition_runtime = self.recognition_runtime
            enrollment_session = self.enrollment_session
            if self.enabled or identity_service is not None:
                rows = self._face_detector.detect_rows(img)
                regions = tuple(
                    FaceRegion(
                        box=tuple(int(round(value)) for value in row[:4]),
                        confidence=row[14],
                        landmarks=row[4:14],
                        provider_data=row,
                    )
                    for row in rows
                )
                if identity_service is not None:
                    with self._enrollment_lock:
                        self._latest_enrollment_frame = (
                            img.copy(),
                            regions,
                            time.monotonic(),
                        )
                else:
                    with self._enrollment_lock:
                        self._latest_enrollment_frame = None
                if enrollment_session is not None and enrollment_session.expired:
                    enrollment_session.stop()
                    self.set_enrollment_session(None)
                    enrollment_session = None
                if enrollment_session is not None and enrollment_session.mode == "enroll":
                    enrollment_session.observe(img, regions)
                if self.enabled and regions:
                    face = max(regions, key=lambda region: region.box[2] * region.box[3]).box
            if identity_service is not None and recognition_runtime is not None:
                if len(regions) == 1:
                    try:
                        identity = identity_service.resolve_identity(img, regions[0])
                    except (FaceRecognitionError, sqlite3.Error):
                        if not self._identity_error_reported:
                            print("local identity recognition unavailable: encrypted templates or key unavailable")
                            self._identity_error_reported = True
                        recognition_runtime.set_unavailable("encrypted_store_unavailable")
                        self.set_identity_service(None)
                        identity = IdentityResult("disabled", reason="encrypted_store_unavailable")
                else:
                    identity = IdentityResult(
                        "unknown",
                        reason="multiple_faces" if regions else "no_face",
                    )
                self.identity_status = recognition_runtime.process(identity)
                if enrollment_session is not None and enrollment_session.mode == "test":
                    enrollment_session.observe(img, regions, identity)
            elif recognition_runtime is not None:
                self.identity_status = recognition_runtime.status()
            self.face = face
            now = time.time()

            if face is not None:
                self.last_seen = now
                self._lost_reported = False
                self._steer(face, w, h, now, seen_at)
            elif self.tracking and now - self.last_seen > config.TRACK_LOST_SECONDS:
                # Lost them: stop following; the head stays where it is.
                self.tracking = False
                if not self._lost_reported:
                    self._lost_reported = True
                    self.on_pose(None, None, False)

            self.eyes.publish(self._annotate(img, face, w, h))

    def _steer(self, face: tuple[int, int, int, int], w: int, h: int, now: float, seen_at: float) -> None:
        x, y, fw, fh = face
        ex = ((x + fw / 2) - w / 2) / (w / 2)   # -1 (left edge) .. +1 (right edge)
        ey = ((y + fh / 2) - h / 2) / (h / 2)   # -1 (top) .. +1 (bottom)
        # A frame turned 90 degrees (CAMERA_ROTATE) swaps the sensor's wide and narrow fields of view.
        hfov, vfov = (config.TRACK_VFOV, config.TRACK_HFOV) if config.CAMERA_ROTATE % 180 else (config.TRACK_HFOV, config.TRACK_VFOV)
        lo_t, hi_t = config.TRACK_FOLLOW_TILT
        lo_t, hi_t = max(lo_t, config.TRACK_TILT_MIN), min(hi_t, config.TRACK_TILT_MAX)
        taken = (seen_at or now) - config.TRACK_LATENCY_S   # when the camera took this frame
        # Face right of center → pan right; face above center (ey < 0) → look up (tilt toward its max).
        new_pan = self._aim("pan", ex * config.TRACK_PAN_SIGN, hfov, self.pan, taken, -config.TRACK_PAN_LIMIT, config.TRACK_PAN_LIMIT)
        new_tilt = self._aim("tilt", -ey * config.TRACK_TILT_SIGN, vfov, self.tilt, taken, lo_t, hi_t)
        moved = abs(new_pan - self.pan) >= 0.5 or abs(new_tilt - self.tilt) >= 0.5
        became_tracking = not self.tracking
        self.tracking = True
        if (moved or became_tracking) and now - self._last_sent >= SEND_EVERY:
            self._last_sent = now
            self.note_pose(round(new_pan, 1), round(new_tilt, 1))
            self.on_pose(self.pan, self.tilt, True)

    def _aim(self, axis: str, err: float, fov: float, cur: float, taken: float, lo: float, hi: float) -> float:
        """The new command for one axis: where the head pointed when the frame was taken, plus the face's angle off
        the middle of that frame, is where the face is; go TRACK_GAIN of the way there from the last command."""
        off = math.degrees(math.atan(err * math.tan(math.radians(fov / 2))))
        face_at = self.motion[axis].at(taken) + off
        deadband = math.degrees(math.atan(config.TRACK_DEADBAND * math.tan(math.radians(fov / 2))))
        if abs(face_at - cur) <= deadband:
            return cur
        return max(lo, min(hi, cur + (face_at - cur) * config.TRACK_GAIN))

    def _annotate(self, img, face, w: int, h: int) -> bytes:
        cv2.drawMarker(img, (w // 2, h // 2), (90, 90, 90), cv2.MARKER_CROSS, 12, 1)
        p = getattr(self, "perception", None)
        if p is not None and p.enabled:
            for label, x, y, bw, bh in list(p.boxes):   # what perception notices: amber boxes, named
                cv2.rectangle(img, (x, y), (x + bw, y + bh), (92, 180, 242), 1)
                cv2.putText(img, label, (x + 2, max(9, y + 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (92, 180, 242), 1)
        if face is not None:
            x, y, fw, fh = face
            cv2.rectangle(img, (x, y), (x + fw, y + fh), (80, 220, 120), 2)
        elif self.enabled:
            cv2.putText(img, "no face", (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 120, 200), 1)
        ok, out = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return out.tobytes() if ok else b""
