"""Hardware-free tests for the opt-in webcam diagnostic."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from deskbot_local.webcam_test import run_webcam_test


class FakeCapture:
    def __init__(self, frames=(), opened=True) -> None:
        self.frames = list(frames)
        self.opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        return (True, self.frames.pop(0)) if self.frames else (False, None)

    def release(self) -> None:
        self.released = True


class FakeCV2:
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 1

    def __init__(self, key=ord("q")) -> None:
        self.key = key
        self.rectangles = []
        self.windows_destroyed = False

    def rectangle(self, frame, start, end, color, thickness) -> None:
        self.rectangles.append((start, end))

    def putText(self, *args) -> None:
        pass

    def imshow(self, *args) -> None:
        pass

    def waitKey(self, _delay: int) -> int:
        return self.key

    def destroyAllWindows(self) -> None:
        self.windows_destroyed = True


class FakeDetector:
    def __init__(self, _model: Path) -> None:
        self.frames = []

    def detect(self, frame):
        self.frames.append(frame)
        return ((2, 3, 10, 12),)


class WebcamTestTests(unittest.TestCase):
    def test_detection_preview_uses_injected_camera_and_detector_without_saving(self) -> None:
        frame = object()
        capture = FakeCapture([frame])
        cv2 = FakeCV2()
        detector_instances = []

        def detector_factory(model):
            detector = FakeDetector(model)
            detector_instances.append(detector)
            return detector

        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "yunet.onnx"
            model.touch()
            output = io.StringIO()
            result = run_webcam_test(
                model_path=model,
                capture_factory=lambda _index: capture,
                detector_factory=detector_factory,
                cv2_module=cv2,
                output=output,
                error_output=io.StringIO(),
            )

            self.assertEqual(result, 0)
            self.assertTrue(capture.released)
            self.assertTrue(cv2.windows_destroyed)
            self.assertEqual(detector_instances[0].frames, [frame])
            self.assertEqual(cv2.rectangles, [((2, 3), (12, 15))])
            self.assertIn("Captured 1 frame(s); face detections across frames: 1.", output.getvalue())
            self.assertEqual(list(Path(temporary).iterdir()), [model])

    def test_camera_unavailable_fails_clearly_and_releases_capture(self) -> None:
        capture = FakeCapture(opened=False)
        error_output = io.StringIO()
        result = run_webcam_test(
            capture_factory=lambda _index: capture,
            cv2_module=FakeCV2(),
            output=io.StringIO(),
            error_output=error_output,
        )

        self.assertEqual(result, 1)
        self.assertTrue(capture.released)
        self.assertIn("macOS Camera permission", error_output.getvalue())

    def test_missing_model_falls_back_to_preview_without_downloading(self) -> None:
        capture = FakeCapture([object()])
        error_output = io.StringIO()
        detector_calls = []
        with tempfile.TemporaryDirectory() as temporary:
            missing_model = Path(temporary) / "missing.onnx"
            result = run_webcam_test(
                model_path=missing_model,
                display=False,
                max_frames=1,
                capture_factory=lambda _index: capture,
                detector_factory=lambda model: detector_calls.append(model),
                cv2_module=FakeCV2(),
                output=io.StringIO(),
                error_output=error_output,
            )

        self.assertEqual(result, 0)
        self.assertTrue(capture.released)
        self.assertEqual(detector_calls, [])
        self.assertFalse(missing_model.exists())
        self.assertIn("No model will be downloaded", error_output.getvalue())

    def test_invalid_frame_limit_is_rejected_before_camera_open(self) -> None:
        camera_calls = []
        error_output = io.StringIO()
        result = run_webcam_test(
            max_frames=0,
            capture_factory=lambda index: camera_calls.append(index),
            cv2_module=FakeCV2(),
            error_output=error_output,
        )

        self.assertEqual(result, 2)
        self.assertEqual(camera_calls, [])
        self.assertIn("greater than zero", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
