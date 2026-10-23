"""Explicit local webcam preview and face-detection diagnostic."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TextIO

from brain.face_detector import MODEL, YuNetFaceDetector


class Capture(Protocol):
    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, object]: ...

    def release(self) -> None: ...


class FaceDetector(Protocol):
    def detect(self, frame: object) -> tuple[tuple[int, int, int, int], ...]: ...


def run_webcam_test(
    camera_index: int = 0,
    *,
    model_path: Path | str = MODEL,
    preview_only: bool = False,
    display: bool = True,
    max_frames: int | None = None,
    capture_factory: Callable[[int], Capture] | None = None,
    detector_factory: Callable[[Path], FaceDetector] | None = None,
    cv2_module: object | None = None,
    output: TextIO | None = None,
    error_output: TextIO | None = None,
    frame_observer: Callable[[object, tuple[tuple[int, int, int, int], ...]], str | None] | None = None,
) -> int:
    """Open a webcam only when explicitly called; frames are never saved."""
    out = sys.stdout if output is None else output
    err = sys.stderr if error_output is None else error_output
    if camera_index < 0:
        print("Camera index must be zero or greater.", file=err)
        return 2
    if max_frames is not None and max_frames < 1:
        print("Frame limit must be greater than zero.", file=err)
        return 2

    if cv2_module is None:
        try:
            import cv2 as cv2_module
        except ImportError as exc:
            print(f"Webcam test requires OpenCV: {exc}", file=err)
            return 2

    open_camera = capture_factory or cv2_module.VideoCapture
    try:
        capture = open_camera(camera_index)
    except Exception as exc:
        print(f"Could not open camera {camera_index}: {exc}", file=err)
        return 1

    if not capture.isOpened():
        print(
            f"Could not open camera {camera_index}. Check that it is connected and "
            "that macOS Camera permission is granted to this terminal or VS Code.",
            file=err,
        )
        capture.release()
        return 1

    model = Path(model_path)
    detector: FaceDetector | None = None
    if not preview_only and model.is_file():
        try:
            detector = (detector_factory or YuNetFaceDetector)(model)
        except Exception as exc:
            print(f"Could not initialize local YuNet face detection: {exc}", file=err)
            capture.release()
            return 2
    elif not preview_only:
        print(
            f"YuNet model not found at {model}; showing camera preview without face detection. "
            "No model will be downloaded.",
            file=err,
        )

    face_count = 0
    frame_count = 0
    if display:
        print("Webcam is active; press q or Esc in the preview window to stop.", file=out)
    try:
        while max_frames is None or frame_count < max_frames:
            ok, frame = capture.read()
            if not ok:
                print("Camera stopped returning frames.", file=err)
                return 1
            frame_count += 1
            faces = ()
            if detector is not None:
                try:
                    faces = detector.detect(frame)
                except Exception as exc:
                    print(f"Local face detection failed: {exc}", file=err)
                    return 2
            face_count += len(faces)
            observed_status = frame_observer(frame, faces) if frame_observer is not None else None

            if display:
                for x, y, width, height in faces:
                    cv2_module.rectangle(frame, (x, y), (x + width, y + height), (80, 220, 120), 2)
                status = observed_status or (
                    f"YuNet face detection: {len(faces)} face(s)"
                    if detector is not None
                    else "Camera preview only; YuNet model unavailable"
                )
                cv2_module.putText(
                    frame,
                    status,
                    (8, 24),
                    cv2_module.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (80, 220, 120),
                    1,
                    cv2_module.LINE_AA,
                )
                cv2_module.imshow("DeskBot webcam test", frame)
                if cv2_module.waitKey(1) & 0xFF in (ord("q"), 27):
                    break

        detected = "not run" if detector is None else str(face_count)
        print(f"Captured {frame_count} frame(s); face detections across frames: {detected}.", file=out)
        return 0
    finally:
        capture.release()
        if display:
            cv2_module.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly test a local webcam without saving images or moving robot hardware."
    )
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    parser.add_argument("--model", type=Path, default=MODEL, help="Existing local YuNet ONNX model")
    parser.add_argument("--preview-only", action="store_true", help="Do not run face detection")
    parser.add_argument("--no-display", action="store_true", help="Capture frames without opening a preview window")
    parser.add_argument("--frames", type=int, help="Stop after this many frames (useful with --no-display)")
    args = parser.parse_args(argv)
    try:
        return run_webcam_test(
            args.camera,
            model_path=args.model,
            preview_only=args.preview_only,
            display=not args.no_display,
            max_frames=args.frames,
        )
    except KeyboardInterrupt:
        print("Webcam test stopped.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
