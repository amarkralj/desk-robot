from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from brain import main as brain_main
from deskbot_local.dashboard_enrollment import FaceEnrollmentSession, POSE_STEPS
from deskbot_local.identity import FaceIdentityService, FaceRegion, TemplateStore
from deskbot_local.registry import PersonRegistry


class TestKey:
    def get_or_create_key(self) -> bytes:
        return b"0123456789abcdef0123456789abcdef"


class FakeSource:
    def __init__(self) -> None:
        self.released = False

    def read(self) -> tuple[bool, object]:
        return True, object()

    def release(self) -> None:
        self.released = True


class FakeProvider:
    model_id = "fake-local"

    def detect_faces(self, _frame: object) -> tuple[FaceRegion, ...]:
        return (FaceRegion((0, 0, 100, 100), 0.99),)

    def create_embedding(self, _frame: object, _face: FaceRegion) -> tuple[float, ...]:
        return (1.0, 0.0, 0.0)


class FakeTracker:
    def __init__(self, identity_service: FaceIdentityService) -> None:
        self.identity_service = identity_service
        self.enrollment_session = None

    def set_enrollment_session(self, session: FaceEnrollmentSession | None) -> None:
        self.enrollment_session = session


class DashboardEnrollmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.registry = PersonRegistry(root / "people.sqlite3")
        self.templates = TemplateStore(root / "templates.sqlite3", key_provider=TestKey())
        self.provider = FakeProvider()
        self.service = FaceIdentityService(
            self.registry,
            self.provider,
            self.templates,
            privacy_mode=False,
        )
        self.source = FakeSource()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def wait_until(self, predicate) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition did not become true")

    def test_guided_pose_sequence_has_required_short_german_prompts(self) -> None:
        instructions = [instruction for _step, instruction in POSE_STEPS]
        self.assertEqual(len(instructions), 8)
        self.assertEqual(instructions[0], "Schau direkt in die Kamera")
        self.assertEqual(instructions[1], "Dreh deinen Kopf langsam nach links")
        self.assertEqual(instructions[2], "Jetzt nach rechts")
        self.assertIn("links oben", instructions[5])
        self.assertIn("rechts oben", instructions[6])
        self.assertIn("zur Mitte", instructions[7])

    def test_consent_is_required_before_session_starts(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit opt-in"):
            FaceEnrollmentSession(
                source=self.source,
                provider=self.provider,
                identity_service=self.service,
                registry=self.registry,
                display_name="Chef",
                role="owner",
            )

    def test_owner_wizard_saves_only_encrypted_templates_after_all_poses(self) -> None:
        session = FaceEnrollmentSession(
            source=self.source,
            provider=self.provider,
            identity_service=self.service,
            registry=self.registry,
            display_name="Sam",
            role="owner",
            consent_confirmed=True,
            make_configured_owner=True,
            quality_checker=lambda _frame, faces: (len(faces) == 1, "good"),
            frame_encoder=lambda _frame: b"preview-jpeg",
        )
        session.start()
        try:
            for index in range(len(POSE_STEPS)):
                self.wait_until(lambda: session.status()["quality_ok"])
                session.capture_pose(index)
                self.wait_until(
                    lambda i=index: session.status()["steps"][i]["samples"] == 3
                )
            self.assertTrue(session.status()["ready_to_save"])
            result = session.save(True)
            person = self.registry.get_person(result["person_id"])
            self.assertEqual(person.role, "owner")
            self.assertTrue(person.opted_in)
            self.assertTrue(person.enrolled)
            self.assertEqual(self.registry.get_configured_owner().person_id, person.person_id)
            self.assertEqual(result["greeting_alias"], "Chef")
            expected_templates = 3 * len(POSE_STEPS)
            self.assertEqual(result["templates_saved"], expected_templates)
            self.assertEqual(
                len(self.templates.list_all(self.provider.model_id)),
                expected_templates,
            )
            self.assertEqual(session.preview(), b"preview-jpeg")
        finally:
            session.stop()
        self.assertTrue(self.source.released)

    def test_test_mode_is_non_destructive_and_reports_unknown_or_match(self) -> None:
        person = self.registry.create_person("Chef", role="owner")
        self.registry.record_opt_in(person.person_id, True)
        self.templates.add(person.person_id, self.provider.model_id, (1.0, 0.0, 0.0))
        self.registry.enroll(person.person_id)
        session = FaceEnrollmentSession(
            source=self.source,
            provider=self.provider,
            identity_service=self.service,
            registry=self.registry,
            mode="test",
            quality_checker=lambda _frame, _faces: (True, "good"),
            frame_encoder=lambda _frame: b"preview-jpeg",
        )
        before = len(self.templates.list_all(self.provider.model_id))
        session.start()
        try:
            self.wait_until(lambda: session.status()["identity"]["status"] == "recognized")
            self.assertEqual(session.status()["identity"]["display_name"], "Chef")
            self.assertEqual(len(self.templates.list_all(self.provider.model_id)), before)
            with self.assertRaisesRegex(ValueError, "only available"):
                session.capture_pose(0)
            with self.assertRaisesRegex(ValueError, "do not enroll"):
                session.save(True)
        finally:
            session.stop()

    def test_local_camera_releases_after_dashboard_heartbeat_expires(self) -> None:
        now = [0.0]
        session = FaceEnrollmentSession(
            source=self.source,
            provider=self.provider,
            identity_service=self.service,
            registry=self.registry,
            mode="test",
            quality_checker=lambda _frame, _faces: (True, "good"),
            frame_encoder=lambda _frame: b"preview-jpeg",
            clock=lambda: now[0],
        )
        session.start()
        now[0] = 16.0
        try:
            self.wait_until(lambda: self.source.released)
            self.assertFalse(session.status()["active"])
        finally:
            session.stop()

    def test_quality_rejects_multiple_faces_and_small_faces(self) -> None:
        session = FaceEnrollmentSession(
            source=self.source,
            provider=self.provider,
            identity_service=self.service,
            registry=self.registry,
            display_name="Sam",
            consent_confirmed=True,
        )
        ok, message = session.quality_checker(object(), ())
        self.assertFalse(ok)
        self.assertIn("Kein Gesicht", message)
        faces = (
            FaceRegion((0, 0, 100, 100), 0.9),
            FaceRegion((120, 0, 100, 100), 0.9),
        )
        ok, message = session.quality_checker(object(), faces)
        self.assertFalse(ok)
        self.assertIn("nur ein Gesicht", message)
        too_small = FaceRegion((0, 0, 40, 40), 0.9)
        import numpy as np

        ok, message = session.quality_checker(np.zeros((100, 100, 3), dtype=np.uint8), (too_small,))
        self.assertFalse(ok)
        self.assertIn("näher", message)
        normal_size = FaceRegion((0, 0, 100, 100), 0.9)
        dark = np.zeros((100, 100, 3), dtype=np.uint8)
        ok, message = session.quality_checker(dark, (normal_size,))
        self.assertFalse(ok)
        self.assertIn("Licht", message)
        blurred = np.full((100, 100, 3), 128, dtype=np.uint8)
        ok, message = session.quality_checker(blurred, (normal_size,))
        self.assertFalse(ok)
        self.assertIn("unscharf", message)

    def test_unsuitable_frame_pauses_pose_capture_until_user_retries(self) -> None:
        quality_ok = [True]
        face = FaceRegion((0, 0, 100, 100), 0.99)
        session = FaceEnrollmentSession(
            source=None,
            provider=self.provider,
            identity_service=self.service,
            registry=self.registry,
            display_name="Sam",
            consent_confirmed=True,
            quality_checker=lambda _frame, _faces: (
                quality_ok[0],
                "good" if quality_ok[0] else "Bitte für gleichmäßiges Licht sorgen",
            ),
            frame_encoder=lambda _frame: b"preview-jpeg",
        )
        session.observe(object(), (face,))
        session.capture_pose(0)
        quality_ok[0] = False
        session.observe(object(), (face,))
        self.assertFalse(session.status()["collecting"])
        self.assertFalse(session.status()["quality_ok"])
        self.assertEqual(session.status()["steps"][0]["samples"], 0)

        quality_ok[0] = True
        session.observe(object(), (face,))
        session.capture_pose(0)
        for _ in range(3):
            session.observe(object(), (face,))
        self.assertEqual(session.status()["steps"][0]["samples"], 3)
        session.stop()

    def test_robot_dashboard_api_attaches_to_tracker_without_opening_another_camera(self) -> None:
        tracker = FakeTracker(self.service)
        with (
            patch.object(brain_main, "tracker", tracker),
            patch.object(brain_main, "face_enrollment_session", None),
            patch.object(brain_main.eyes, "latest", return_value=b"current robot frame"),
        ):
            response = asyncio.run(brain_main._console_command(
                "identity/enrollment/start", {"mode": "test"},
            ))
            self.assertEqual(response["session"]["source"], "robot")
            self.assertIs(tracker.enrollment_session, brain_main.face_enrollment_session)
            self.assertIsNone(tracker.enrollment_session.source)
            asyncio.run(brain_main._console_command("identity/enrollment/cancel", {}))
            self.assertIsNone(tracker.enrollment_session)
            self.assertIsNone(brain_main.face_enrollment_session)

    def test_robot_status_heartbeat_keeps_active_session_alive(self) -> None:
        class HeartbeatSession:
            touched = False

            def touch(self) -> None:
                self.touched = True

        session = HeartbeatSession()
        with patch.object(brain_main, "face_enrollment_session", session):
            result = asyncio.run(brain_main._console_command("identity/enrollment/touch", {}))
        self.assertTrue(result["touched"])
        self.assertTrue(session.touched)


if __name__ == "__main__":
    unittest.main()
