"""Shared YuNet face detection for caller-supplied BGR frames."""

from __future__ import annotations

import threading
from pathlib import Path

MODEL = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"


class YuNetFaceDetector:
    """Lazily load the existing local YuNet model and return face boxes."""

    def __init__(self, model_path: Path | str = MODEL) -> None:
        self.model_path = Path(model_path)
        self._detector = None
        self._size = (0, 0)
        self._lock = threading.RLock()

    def detect(self, frame: object) -> tuple[tuple[int, int, int, int], ...]:
        return tuple(
            tuple(int(round(value)) for value in row[:4])
            for row in self.detect_rows(frame)
        )

    def detect_rows(self, frame: object) -> tuple[tuple[float, ...], ...]:
        """Return YuNet rows, including five landmarks, for reuse by SFace."""
        shape = getattr(frame, "shape", None)
        if (
            shape is None
            or len(shape) != 3
            or shape[0] <= 0
            or shape[1] <= 0
            or shape[2] < 3
        ):
            raise ValueError("frame must be a non-empty BGR image with at least three channels")
        if not self.model_path.is_file():
            raise FileNotFoundError(f"local YuNet model not found: {self.model_path}")

        height, width = int(shape[0]), int(shape[1])
        with self._lock:
            if self._detector is None or self._size != (width, height):
                try:
                    import cv2
                except ImportError as exc:
                    raise RuntimeError("OpenCV is required for YuNet face detection") from exc
                self._detector = cv2.FaceDetectorYN.create(
                    str(self.model_path), "", (width, height), score_threshold=0.6
                )
                self._size = (width, height)
            _status, faces = self._detector.detect(frame)
        if faces is None:
            return ()
        rows = tuple(tuple(float(value) for value in face) for face in faces)
        if any(len(row) != 15 for row in rows):
            raise RuntimeError("YuNet returned an unsupported face row shape")
        return rows
