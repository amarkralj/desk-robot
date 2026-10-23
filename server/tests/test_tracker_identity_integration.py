"""Identity reuses the tracker's single per-frame face detection."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from brain.tracker import Tracker
from deskbot_local.identity import IdentityResult


class StopTracker(Exception):
    pass


class OneFrameEyes:
    def __init__(self, jpeg: bytes) -> None:
        self.jpeg = jpeg
        self.frame_at = time.time()
        self.calls = 0
        self.published = 0

    def wait_for_new(self, _seq: int, timeout: float = 1.0) -> int:
        self.calls += 1
        if self.calls == 1:
            return 1
        raise StopTracker

    def publish(self, _jpeg: bytes) -> None:
        self.published += 1


class CountingDetector:
    def __init__(self) -> None:
        self.calls = 0
        self.row = tuple(float(value) for value in (10, 10, 20, 20, *range(10), 0.99))

    def detect_rows(self, _frame: object) -> tuple[tuple[float, ...], ...]:
        self.calls += 1
        return (self.row,)


class FakeService:
    def __init__(self) -> None:
        self.calls = 0
        self.face = None

    def resolve_identity(self, _frame: object, face: object) -> IdentityResult:
        self.calls += 1
        self.face = face
        return IdentityResult("unknown", reason="no_eligible_template")


class FakeRuntime:
    def status(self) -> dict[str, object]:
        return {"status": "unknown", "display_name": "Unknown"}

    def process(self, result: IdentityResult) -> dict[str, object]:
        return {"status": result.status, "display_name": "Unknown"}


class RecordingEnrollmentSession:
    mode = "enroll"
    expired = False

    def __init__(self) -> None:
        self.frames: list[tuple[object, tuple[object, ...]]] = []

    def observe(self, frame: object, faces: tuple[object, ...]) -> None:
        self.frames.append((frame, faces))


class TrackerIdentityIntegrationTests(unittest.TestCase):
    def test_one_shared_detection_feeds_tracking_and_identity_when_motion_is_disabled(self) -> None:
        ok, encoded = cv2.imencode(".jpg", np.zeros((80, 100, 3), dtype=np.uint8))
        self.assertTrue(ok)
        eyes = OneFrameEyes(encoded.tobytes())
        detector = CountingDetector()
        service = FakeService()
        tracker = Tracker(
            eyes,
            lambda *_: self.fail("identity-only detection must not move the head"),
            face_detector=detector,  # type: ignore[arg-type]
            identity_service=service,  # type: ignore[arg-type]
            recognition_runtime=FakeRuntime(),  # type: ignore[arg-type]
        )
        tracker.enabled = False
        enrollment = RecordingEnrollmentSession()
        tracker.set_enrollment_session(enrollment)  # type: ignore[arg-type]
        with patch.object(tracker, "_annotate", return_value=b"annotated"):
            with self.assertRaises(StopTracker):
                tracker._run()
        self.assertEqual(detector.calls, 1)
        self.assertEqual(service.calls, 1)
        self.assertEqual(service.face.provider_data, detector.row)
        self.assertEqual(len(enrollment.frames), 1)
        self.assertEqual(enrollment.frames[0][1][0].provider_data, detector.row)
        self.assertEqual(eyes.published, 1)


if __name__ == "__main__":
    unittest.main()
