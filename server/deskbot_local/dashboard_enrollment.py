"""Explicit, in-memory face enrollment sessions for the local dashboard."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

from .identity import FaceIdentityService, FaceRegion, IdentityResult
from .recognition_runtime import RecognitionRuntime
from .registry import PersonRegistry

POSE_STEPS = (
    ("center", "Schau direkt in die Kamera"),
    ("left", "Dreh deinen Kopf langsam nach links"),
    ("right", "Jetzt nach rechts"),
    ("up", "Schau leicht nach oben"),
    ("down", "Jetzt leicht nach unten"),
    ("diagonal_left", "Dreh leicht nach links oben"),
    ("diagonal_right", "Dreh leicht nach rechts oben"),
    ("return", "Komm zurück zur Mitte"),
)
SAMPLES_PER_POSE = 3
CAMERA_SESSION_IDLE_SECONDS = 15.0


class FrameSource(Protocol):
    def read(self) -> tuple[bool, object]: ...

    def release(self) -> None: ...


class OpenCVCameraSource:
    """A webcam opened only by an explicit dashboard enrollment/test request."""

    def __init__(self, camera_index: int = 0, *, cv2_module: object | None = None) -> None:
        if camera_index < 0:
            raise ValueError("camera index must be zero or greater")
        if cv2_module is None:
            try:
                import cv2 as cv2_module
            except ImportError as exc:
                raise RuntimeError("OpenCV is required for local webcam enrollment") from exc
        self._cv2 = cv2_module
        self._capture = cv2_module.VideoCapture(camera_index)
        if not self._capture.isOpened():
            self._capture.release()
            raise RuntimeError(
                "Could not open the webcam. Check that it is connected and that macOS Camera "
                "permission is granted to Terminal or VS Code."
            )

    def read(self) -> tuple[bool, object]:
        return self._capture.read()

    def release(self) -> None:
        self._capture.release()


class RobotCameraSource:
    """Read frames from the already-running robot camera HTTP frame endpoint."""

    def __init__(
        self,
        load_jpeg: Callable[[], bytes],
        *,
        cv2_module: object | None = None,
    ) -> None:
        if cv2_module is None:
            try:
                import cv2 as cv2_module
            except ImportError as exc:
                raise RuntimeError("OpenCV is required for local face enrollment") from exc
        self._cv2 = cv2_module
        self._load_jpeg = load_jpeg

    def read(self) -> tuple[bool, object]:
        import numpy as np

        jpeg = self._load_jpeg()
        if not jpeg:
            raise RuntimeError("The robot camera has no current frame")
        frame = self._cv2.imdecode(np.frombuffer(jpeg, np.uint8), self._cv2.IMREAD_COLOR)
        return frame is not None, frame

    def release(self) -> None:
        return


class QualityChecker(Protocol):
    def __call__(
        self, frame: object, faces: tuple[FaceRegion, ...]
    ) -> tuple[bool, str]: ...


class FaceEnrollmentSession:
    """Consume frames supplied by one explicit camera source; persist embeddings only."""

    def __init__(
        self,
        *,
        source: FrameSource | None,
        provider: object,
        identity_service: FaceIdentityService,
        registry: PersonRegistry,
        mode: str = "enroll",
        camera_source: str = "unknown",
        display_name: str = "",
        role: str = "person",
        consent_confirmed: bool = False,
        make_configured_owner: bool = False,
        quality_checker: QualityChecker | None = None,
        frame_encoder: Callable[[object], bytes] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if mode not in ("enroll", "test"):
            raise ValueError("mode must be 'enroll' or 'test'")
        if mode == "enroll":
            if not isinstance(display_name, str) or not display_name.strip():
                raise ValueError("display name is required")
            if role not in ("owner", "person"):
                raise ValueError("role must be 'owner' or 'person'")
            if consent_confirmed is not True:
                raise ValueError("explicit opt-in is required before face enrollment")
            if make_configured_owner and role != "owner":
                raise ValueError("only an owner profile can be configured as the owner")
        self.source = source
        self.provider = provider
        self.identity_service = identity_service
        self.registry = registry
        self.mode = mode
        self.camera_source = camera_source
        self.display_name = display_name.strip()
        self.role = role
        self.consent_confirmed = consent_confirmed
        self.make_configured_owner = make_configured_owner
        self.quality_checker = quality_checker or check_frame_quality
        self.frame_encoder = frame_encoder or encode_jpeg
        self.clock = clock
        self._last_client_seen = clock()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error = ""
        self._closed = False
        self._frame_seq = 0
        self._preview_jpeg: bytes | None = None
        self._quality = "Warte auf Kamerabild"
        self._quality_ok = False
        self._collecting_step: int | None = None
        self._samples: list[list[tuple[float, ...]]] = [[] for _ in POSE_STEPS]
        self._identity_status: dict[str, object] = {
            "status": "unknown",
            "display_name": "Unknown",
            "similarity_score": None,
            "reason": "no_frame",
        }
        self._runtime = RecognitionRuntime(
            registry,
            lambda _greeting: None,
            model_available=True,
            enabled=True,
            privacy_mode=False,
            automatic_greetings=False,
            stable_frames=3,
            presence_reset_frames=3,
            cooldown_seconds=0,
        )

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("camera session has already been started")
        if self.source is not None:
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="deskbot-enrollment-camera",
                daemon=True,
            )
            self._thread.start()

    def touch(self) -> None:
        """Mark a dashboard status/preview poll as an active user session."""
        self._last_client_seen = self.clock()

    @property
    def expired(self) -> bool:
        return self.clock() - self._last_client_seen > CAMERA_SESSION_IDLE_SECONDS

    def _capture_loop(self) -> None:
        failed_reads = 0
        try:
            while not self._stop.is_set():
                if self.expired:
                    break
                ok, frame = self.source.read()
                if not ok:
                    failed_reads += 1
                    if failed_reads >= 30:
                        raise RuntimeError("Camera stopped returning usable frames")
                    if self._stop.wait(0.1):
                        break
                    continue
                failed_reads = 0
                self.observe(frame, tuple(self.provider.detect_faces(frame)))
                self._stop.wait(0.08)
        except Exception as exc:
            with self._condition:
                self._error = f"{type(exc).__name__}: {exc}"
                self._collecting_step = None
                self._stop.set()
                self._condition.notify_all()
        finally:
            if self.source is not None:
                self.source.release()
            with self._condition:
                self._closed = True
                self._condition.notify_all()

    def observe(
        self,
        frame: object,
        faces: tuple[FaceRegion, ...],
        identity_result: IdentityResult | None = None,
    ) -> None:
        """Accept a frame and detections from an existing pipeline, without redetecting."""
        if self._stop.is_set():
            return
        try:
            quality_ok, quality_message = self.quality_checker(frame, faces)
            jpeg = self.frame_encoder(frame)
            with self._condition:
                self._frame_seq += 1
                self._preview_jpeg = jpeg
                self._quality_ok = quality_ok
                self._quality = quality_message
                if self.mode == "enroll" and self._collecting_step is not None:
                    if not quality_ok:
                        self._collecting_step = None
                    else:
                        samples = self._samples[self._collecting_step]
                        if len(samples) < SAMPLES_PER_POSE and len(faces) == 1:
                            samples.append(self.provider.create_embedding(frame, faces[0]))
                            if len(samples) >= SAMPLES_PER_POSE:
                                self._collecting_step = None
                                self._quality = "Pose gespeichert"
                elif self.mode == "test":
                    result = identity_result or (
                        self.identity_service.resolve_identity(frame, faces[0])
                        if len(faces) == 1 and quality_ok
                        else IdentityResult(
                            "unknown",
                            reason="multiple_faces" if len(faces) > 1 else quality_message,
                        )
                    )
                    self._identity_status = self._runtime.process(result)
                self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                self._error = f"{type(exc).__name__}: {exc}"
                self._collecting_step = None
                self._stop.set()
                self._condition.notify_all()

    def capture_pose(self, step: int) -> dict[str, object]:
        if self.mode != "enroll":
            raise ValueError("pose capture is only available in enrollment mode")
        if isinstance(step, bool) or not isinstance(step, int) or not 0 <= step < len(POSE_STEPS):
            raise ValueError("pose step is out of range")
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            expected = self.next_step
            if step != expected:
                raise ValueError("complete the current pose before continuing")
            if self._collecting_step is not None:
                raise ValueError("this pose is already being captured")
            if not self._quality_ok:
                raise ValueError(self._quality)
            self._collecting_step = step
            self._condition.notify_all()
            return self.status()

    @property
    def next_step(self) -> int:
        for index, samples in enumerate(self._samples):
            if len(samples) < SAMPLES_PER_POSE:
                return index
        return len(POSE_STEPS)

    def status(self) -> dict[str, object]:
        with self._condition:
            return {
                "mode": self.mode,
                "source": self.camera_source,
                "active": not self._closed and not self._stop.is_set(),
                "error": self._error,
                "quality": self._quality,
                "quality_ok": self._quality_ok,
                "collecting": self._collecting_step is not None,
                "next_step": self.next_step,
                "steps": [
                    {"id": key, "instruction": instruction, "samples": len(self._samples[index])}
                    for index, (key, instruction) in enumerate(POSE_STEPS)
                ],
                "ready_to_save": self.mode == "enroll" and self.next_step == len(POSE_STEPS),
                "identity": dict(self._identity_status),
            }

    def preview(self) -> bytes | None:
        with self._condition:
            return self._preview_jpeg

    def save(self, confirmed: bool) -> dict[str, object]:
        if self.mode != "enroll":
            raise ValueError("recognition test sessions do not enroll people")
        if confirmed is not True:
            raise ValueError("final enrollment confirmation is required")
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            if self.next_step != len(POSE_STEPS):
                raise ValueError("complete all guided poses before saving")
            embeddings = [sample for pose in self._samples for sample in pose]
        role = "owner" if self.role == "owner" else "colleague"
        person = self.registry.create_person(
            self.display_name,
            preferred_language="de",
            role=role,
        )
        try:
            self.registry.record_opt_in(person.person_id, True)
            for embedding in embeddings:
                self.identity_service.enroll_embedding(person.person_id, embedding)
            if self.make_configured_owner:
                self.registry.set_configured_owner(person.person_id)
        except Exception:
            self.registry.add_recognition_data_deleter(
                self.identity_service.template_store.delete_person
            )
            self.registry.delete_person(person.person_id)
            raise
        return {
            "person_id": person.person_id,
            "display_name": person.display_name,
            "role": role,
            "greeting_alias": "Chef" if role == "owner" else None,
            "templates_saved": len(embeddings),
        }

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout=3)
        if not self._closed and self.source is not None:
            self.source.release()
        self._closed = True


def check_frame_quality(frame: object, faces: tuple[FaceRegion, ...]) -> tuple[bool, str]:
    if len(faces) != 1:
        return False, "Erlaube nur ein Gesicht im Bild" if len(faces) > 1 else "Kein Gesicht erkannt"
    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        return False, "Kamerabild ist nicht auswertbar"
    x, y, width, height = faces[0].box
    if width < 80 or height < 80:
        return False, "Bitte etwas näher zur Kamera gehen"
    try:
        import cv2
        import numpy as np

        crop = frame[max(0, y):y + height, max(0, x):x + width]
        if crop.size == 0:
            return False, "Gesicht liegt außerhalb des Bildes"
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except (ImportError, AttributeError, TypeError, ValueError):
        return True, "Ein Gesicht erkannt"
    if brightness < 35 or brightness > 225:
        return False, "Bitte für gleichmäßiges Licht sorgen"
    if sharpness < 25:
        return False, "Bild ist unscharf – bitte ruhig halten"
    return True, "Gute Aufnahme – halte die Pose kurz"


def encode_jpeg(frame: object) -> bytes:
    try:
        import cv2

        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("could not encode camera preview") from exc
    if not ok:
        raise RuntimeError("could not encode camera preview")
    return encoded.tobytes()
