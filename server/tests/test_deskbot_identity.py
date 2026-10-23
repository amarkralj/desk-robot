"""Synthetic and mock-provider tests for local identity recognition."""

from __future__ import annotations

import os
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from deskbot_local import (
    ConsentRequiredError,
    FaceIdentityService,
    FaceRecognitionError,
    FaceRegion,
    MockFaceProvider,
    OpenCVSFaceProvider,
    PersonRegistry,
    TemplateStore,
)


class CountingMockProvider(MockFaceProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.detection_calls = 0
        self.embedding_calls = 0

    def detect_faces(self, frame: object) -> tuple[FaceRegion, ...]:
        self.detection_calls += 1
        return super().detect_faces(frame)

    def create_embedding(self, frame: object, face: FaceRegion) -> tuple[float, ...]:
        self.embedding_calls += 1
        return super().create_embedding(frame, face)


class TestKeyProvider:
    def get_or_create_key(self) -> bytes:
        return b"0123456789abcdef0123456789abcdef"


class FaceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.registry = PersonRegistry(root / "people.sqlite3")
        self.store = TemplateStore(root / "templates.sqlite3", key_provider=TestKeyProvider())
        self.face = FaceRegion((10, 20, 30, 40), 0.99)
        self.provider = CountingMockProvider(
            faces=(self.face,),
            embeddings={self.face.box: (1.0, 0.0, 0.0)},
        )
        self.service = FaceIdentityService(
            self.registry,
            self.provider,
            self.store,
            minimum_similarity=0.8,
            minimum_margin=0.1,
            privacy_mode=False,
        )
        self.frame = object()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def create_opted_in_person(self, person_id: str) -> None:
        self.registry.create_person("Enrolled person", person_id=person_id)
        self.registry.record_opt_in(person_id, True)

    def test_enroll_requires_consent_and_never_happens_automatically(self) -> None:
        person = self.registry.create_person("No consent", person_id="no-consent")
        self.assertFalse(person.enrolled)
        with self.assertRaises(ConsentRequiredError):
            self.service.enroll(person.person_id, self.frame)
        self.assertEqual(self.store.list_all(self.provider.model_id), [])

    def test_explicit_opt_in_enrollment_and_recognition(self) -> None:
        self.create_opted_in_person("person-1")
        self.service.enroll("person-1", self.frame)
        self.assertTrue(self.registry.get_person("person-1").enrolled)
        result = self.service.recognize_frame(self.frame)
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.person_id, "person-1")
        self.assertAlmostEqual(result.confidence, 1.0)

    def test_privacy_mode_blocks_detection_enrollment_and_resolution(self) -> None:
        self.service.set_privacy_mode(True)
        detection_calls = self.provider.detection_calls
        embedding_calls = self.provider.embedding_calls
        self.assertEqual(self.service.detect_faces(self.frame), ())
        self.assertEqual(self.service.recognize_frame(self.frame).status, "disabled")
        with self.assertRaises(ConsentRequiredError):
            self.service.enroll("missing", self.frame)
        self.assertEqual(
            self.service.resolve_identity(self.frame, self.face).reason,
            "privacy_mode",
        )
        self.assertEqual(self.provider.detection_calls, detection_calls)
        self.assertEqual(self.provider.embedding_calls, embedding_calls)

    def test_disabled_or_opted_out_people_resolve_as_unknown(self) -> None:
        self.create_opted_in_person("person-1")
        self.service.enroll("person-1", self.frame)
        self.registry.set_enabled("person-1", False)
        result = self.service.recognize_frame(self.frame)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reason, "no_eligible_template")
        self.assertEqual(self.store.list_all(self.provider.model_id)[0][0], "person-1")

    def test_low_similarity_returns_unknown(self) -> None:
        self.create_opted_in_person("person-1")
        self.service.enroll("person-1", self.frame)
        self.provider.embeddings[self.face.box] = (0.0, 1.0, 0.0)
        result = self.service.recognize_frame(self.frame)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reason, "below_threshold")

    def test_ambiguous_top_matches_return_unknown(self) -> None:
        self.create_opted_in_person("person-1")
        self.create_opted_in_person("person-2")
        self.service.enroll("person-1", self.frame)
        self.service.enroll("person-2", self.frame)
        self.provider.embeddings[self.face.box] = (1.0, 0.0, 0.0)
        result = self.service.recognize_frame(self.frame)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reason, "ambiguous_match")

    def test_no_face_and_multiple_faces_are_unknown(self) -> None:
        self.provider.faces = ()
        self.assertEqual(self.service.recognize_frame(self.frame).reason, "no_face")
        self.provider.faces = (self.face, FaceRegion((50, 60, 20, 20), 0.95))
        self.assertEqual(self.service.recognize_frame(self.frame).reason, "multiple_faces")

    def test_deleting_registry_person_removes_all_local_templates(self) -> None:
        self.create_opted_in_person("person-1")
        self.service.enroll("person-1", self.frame)
        self.store.add("person-1", self.provider.model_id, (0.9, 0.1, 0.0))
        self.assertEqual(len(self.store.list_all(self.provider.model_id)), 2)
        self.assertTrue(self.registry.delete_person("person-1"))
        self.assertEqual(self.store.list_all(self.provider.model_id), [])

    def test_withdrawing_opt_in_deletes_templates_and_disables_profile(self) -> None:
        self.create_opted_in_person("person-1")
        self.service.enroll("person-1", self.frame)
        self.registry.record_opt_in("person-1", False)
        self.assertEqual(self.store.list_all(self.provider.model_id), [])
        self.assertFalse(self.registry.get_person("person-1").enrolled)

    def test_cleanup_failure_still_revokes_recognition_eligibility(self) -> None:
        self.create_opted_in_person("person-1")
        self.service.enroll("person-1", self.frame)

        def fail_cleanup(_person_id: str) -> None:
            raise OSError("template cleanup failed")

        self.registry.add_recognition_data_deleter(fail_cleanup)
        with self.assertRaisesRegex(OSError, "template cleanup failed"):
            self.registry.record_opt_in("person-1", False)
        profile = self.registry.get_person("person-1")
        self.assertFalse(profile.opted_in)
        self.assertFalse(profile.enrolled)
        self.assertIsNone(self.registry.get_recognition_candidate("person-1"))

    def test_enrollment_requires_exactly_one_face(self) -> None:
        self.create_opted_in_person("person-1")
        self.provider.faces = (self.face, FaceRegion((50, 60, 20, 20), 0.95))
        with self.assertRaisesRegex(FaceRecognitionError, "exactly one"):
            self.service.enroll("person-1", self.frame)
        self.assertFalse(self.registry.get_person("person-1").enrolled)

    def test_invalid_thresholds_and_vectors_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FaceIdentityService(self.registry, self.provider, self.store, minimum_similarity=1.1)
        with self.assertRaises(ValueError):
            self.store.add("id", "mock", (float("nan"), 0.0))
        with self.assertRaises(ValueError):
            self.store.add("id", "mock", (0.0, 0.0))

    def test_opencv_provider_requires_existing_model_files_and_does_not_download(self) -> None:
        missing = Path(self.temporary_directory.name) / "not-downloaded.onnx"
        with self.assertRaises(FileNotFoundError):
            OpenCVSFaceProvider(missing, missing)
        self.assertFalse(missing.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX file permission check")
    def test_template_database_file_is_private_on_posix(self) -> None:
        self.assertEqual(self.store.database_path.stat().st_mode & 0o777, 0o600)

    def test_templates_are_authenticated_encrypted_in_sqlite(self) -> None:
        self.store.add("person-1", "mock-v1", (1.0, 0.0, 0.0))
        with sqlite3.connect(self.store.database_path) as connection:
            payload, nonce = connection.execute(
                "SELECT vector, nonce FROM face_templates"
            ).fetchone()
        self.assertEqual(len(nonce), 12)
        self.assertEqual(len(payload), 28)
        self.assertNotEqual(payload[:12], b"\x00\x00\x80?\x00\x00\x00\x00\x00\x00\x00\x00")
        self.assertEqual(self.store.list_all("mock-v1"), [("person-1", (1.0, 0.0, 0.0))])

    def test_modified_ciphertext_fails_authentication(self) -> None:
        self.store.add("person-1", "mock-v1", (1.0, 0.0, 0.0))
        with sqlite3.connect(self.store.database_path) as connection:
            payload = bytearray(connection.execute("SELECT vector FROM face_templates").fetchone()[0])
            payload[0] ^= 0x01
            connection.execute("UPDATE face_templates SET vector = ?", (bytes(payload),))
        with self.assertRaisesRegex(FaceRecognitionError, "authentication failed"):
            self.store.list_all("mock-v1")

    def test_legacy_plaintext_templates_are_migrated_before_use(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE face_templates (
                    template_id INTEGER PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO face_templates (person_id, model_id, dimensions, vector) VALUES (?, ?, ?, ?)",
                ("person-1", "mock-v1", 3, struct.pack("<3f", 1.0, 0.0, 0.0)),
            )
        migrated = TemplateStore(legacy_path, key_provider=TestKeyProvider())
        self.assertEqual(migrated.list_all("mock-v1"), [("person-1", (1.0, 0.0, 0.0))])


if __name__ == "__main__":
    unittest.main()
