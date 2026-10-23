"""Explicit local webcam smoke test for consented identity recognition."""

from __future__ import annotations

import argparse
import sys
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from brain.face_detector import MODEL as YUNET_MODEL
from .dashboard_settings import DeskBotSettingsStore
from .identity import (
    FaceIdentityService,
    FaceRecognitionError,
    FaceRegion,
    IdentityResult,
    OpenCVSFaceProvider,
    TemplateStore,
)
from .recognition_runtime import OwnerGreeting, RecognitionRuntime
from .registry import ConsentRequiredError, PersonRegistry, RegistryError
from .setup_face_models import MODEL_DIR
from .webcam_test import run_webcam_test

SFACE_MODEL = MODEL_DIR / "face_recognition_sface_2021dec.onnx"


class ProviderDetector:
    """Adapter used by webcam_test so detection runs once per supplied frame."""

    def __init__(self, provider: OpenCVSFaceProvider) -> None:
        self.provider = provider
        self.last_regions: tuple[FaceRegion, ...] = ()

    def detect(self, frame: object) -> tuple[tuple[int, int, int, int], ...]:
        self.last_regions = self.provider.detect_faces(frame)
        return tuple(region.box for region in self.last_regions)


def run_identity_webcam_test(
    *,
    camera_index: int = 0,
    person_id: str | None = None,
    display: bool = True,
    max_frames: int | None = None,
    confirm: bool = False,
    input_fn=input,
    output: TextIO | None = None,
    error_output: TextIO | None = None,
    provider: OpenCVSFaceProvider | None = None,
    registry: PersonRegistry | None = None,
    service: FaceIdentityService | None = None,
    cv2_module: object | None = None,
) -> int:
    """Open a camera only on this explicit call; never store frames or play speech."""
    out = sys.stdout if output is None else output
    err = sys.stderr if error_output is None else error_output
    settings = DeskBotSettingsStore().load()
    if not settings["recognition_enabled"] or settings["privacy_mode"]:
        print(
            "Enable local recognition and turn privacy mode off in the DeskBot dashboard before this test.",
            file=err,
        )
        return 2
    if not YUNET_MODEL.is_file() or not SFACE_MODEL.is_file():
        print(
            "Local identity recognition unavailable. Run `python -m deskbot_local.setup_face_models` first.",
            file=err,
        )
        return 2

    active_registry = registry or PersonRegistry()
    try:
        active_provider = provider or OpenCVSFaceProvider(YUNET_MODEL, SFACE_MODEL)
        active_service = service or FaceIdentityService(
            active_registry,
            active_provider,
            TemplateStore(),
            minimum_similarity=settings["recognition_threshold"],
            privacy_mode=False,
        )
    except (FaceRecognitionError, FileNotFoundError, RuntimeError, RegistryError) as exc:
        print(f"Local identity test unavailable: {exc}", file=err)
        return 2
    if person_id is not None:
        try:
            person = active_registry.get_person(person_id)
        except RegistryError as exc:
            print(f"Enrollment profile unavailable: {exc}", file=err)
            return 2
        if not person.enabled or not person.opted_in:
            print("Enrollment requires an enabled profile with recorded explicit opt-in.", file=err)
            return 2
        if not confirm:
            print("Enrollment requires the interactive --confirm-consent prompt.", file=err)
            return 2
        answer = input_fn(
            f"Confirm that {person.display_name} explicitly agrees to local face enrollment? Type YES: "
        )
        if answer != "YES":
            print("Enrollment cancelled.", file=out)
            return 0

    detector = ProviderDetector(active_provider)
    greeting_runtime = RecognitionRuntime(
        active_registry,
        lambda greeting: print(
            f"Owner greeting preview [{greeting.response_id}]: {greeting.text}",
            file=out,
        ),
        model_available=True,
        enabled=True,
        privacy_mode=False,
        automatic_greetings=settings["automatic_greetings_enabled"],
        stable_frames=settings["recognition_stable_frames"],
        presence_reset_frames=settings["presence_reset_frames"],
        cooldown_seconds=settings["owner_greeting_cooldown_seconds"],
    )
    enrollment_done = False
    last_label = ""

    def observe(frame: object, _boxes: tuple[tuple[int, int, int, int], ...]) -> str:
        nonlocal enrollment_done, last_label
        regions = detector.last_regions
        if person_id is not None and not enrollment_done and len(regions) == 1:
            active_service.enroll_detected_face(person_id, frame, regions[0])
            enrollment_done = True
            print("Consent-gated enrollment saved as an encrypted local template.", file=out)
        if len(regions) == 1:
            result = active_service.resolve_identity(frame, regions[0])
        else:
            result = IdentityResult(
                "unknown",
                reason="multiple_faces" if regions else "no_face",
            )
        status = greeting_runtime.process(result)
        label = (
            f"Local identity: {status['display_name']} · {status['status']} "
            f"· model {'available' if status['model_available'] else 'unavailable'}"
        )
        if label != last_label:
            print(label, file=out)
            last_label = label
        return label

    try:
        return run_webcam_test(
            camera_index,
            model_path=YUNET_MODEL,
            display=display,
            max_frames=max_frames,
            detector_factory=lambda _path: detector,
            cv2_module=cv2_module,
            output=out,
            error_output=err,
            frame_observer=observe,
        )
    except (ConsentRequiredError, FaceRecognitionError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"Local identity test failed: {exc}", file=err)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly test local face identity on a webcam; no image or audio is saved or sent."
    )
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--enroll-person", help="Explicitly enroll one opted-in registry person")
    parser.add_argument(
        "--confirm-consent",
        action="store_true",
        help="Require interactive typed confirmation before one-frame enrollment",
    )
    parser.add_argument("--frames", type=int, help="Stop after this many frames")
    parser.add_argument("--no-display", action="store_true", help="Capture without opening the preview window")
    args = parser.parse_args(argv)
    try:
        return run_identity_webcam_test(
            camera_index=args.camera,
            person_id=args.enroll_person,
            confirm=args.confirm_consent,
            max_frames=args.frames,
            display=not args.no_display,
        )
    except KeyboardInterrupt:
        print("Local identity webcam test stopped.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
