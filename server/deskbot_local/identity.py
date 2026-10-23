"""Local face detection and consent-gated identity resolution interfaces.

Frames are supplied by the caller and are processed only in memory. The core
does not open a camera, fetch models, call a service, or persist raw frames.
"""

from __future__ import annotations

import math
import os
import base64
import binascii
import sqlite3
import struct
import sys
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, Protocol

from .registry import ConsentRequiredError, PersonRegistry, default_data_directory

IdentityStatus = Literal["recognized", "unknown", "disabled"]


class FaceRecognitionError(Exception):
    """A provider or local recognition-template operation failed."""


class KeyStorageError(FaceRecognitionError):
    """The locally protected encryption key is unavailable."""


class KeyProvider(Protocol):
    """Store one local encryption key using an operating-system key store."""

    def get_or_create_key(self) -> bytes: ...


class MacKeychainKeyProvider:
    """Retrieve the template key from the current user's macOS Keychain."""

    def __init__(self, account: str) -> None:
        if sys.platform != "darwin":
            raise KeyStorageError("biometric template encryption requires macOS Keychain")
        self.account = account
        try:
            import keyring.backends.macOS
            from keyring.errors import KeyringError
        except ImportError as exc:
            raise KeyStorageError(
                "install server/requirements-identity.txt to use encrypted recognition"
            ) from exc
        try:
            self._backend = keyring.backends.macOS.Keyring()
        except (AttributeError, OSError, RuntimeError) as exc:
            raise KeyStorageError("could not initialize the macOS Keychain backend") from exc
        self._keyring_error = KeyringError

    def get_or_create_key(self) -> bytes:
        try:
            encoded = self._backend.get_password("DeskBot face templates", self.account)
            if encoded is None:
                key = os.urandom(32)
                self._backend.set_password(
                    "DeskBot face templates",
                    self.account,
                    base64.b64encode(key).decode("ascii"),
                )
                return key
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise KeyStorageError("the Keychain template key has an invalid length")
            return key
        except KeyStorageError:
            raise
        except (self._keyring_error, binascii.Error, OSError, TypeError, ValueError) as exc:
            raise KeyStorageError("could not access the macOS Keychain template key") from exc


@dataclass(frozen=True, slots=True)
class FaceRegion:
    """Detected face bounds and provider-only alignment data for this frame."""

    box: tuple[int, int, int, int]
    confidence: float
    landmarks: tuple[float, ...] = ()
    provider_data: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class IdentityResult:
    """Recognition result; uncertain, ineligible, or ambiguous matches are unknown."""

    status: IdentityStatus
    person_id: str | None = None
    confidence: float | None = None
    reason: str = ""


class FaceProvider(Protocol):
    """Backend boundary. A provider must infer only from supplied frames."""

    model_id: str

    def detect_faces(self, frame: object) -> tuple[FaceRegion, ...]: ...

    def create_embedding(self, frame: object, face: FaceRegion) -> tuple[float, ...]: ...


class TemplateStore:
    """Per-user SQLite store for AEAD-encrypted vectors, never images."""

    def __init__(
        self,
        database_path: Path | str | None = None,
        *,
        key_provider: KeyProvider | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else default_data_directory() / "face_templates.sqlite3"
        )
        self._key_provider = key_provider
        self._cached_key: bytes | None = None
        self._key_lock = threading.Lock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.database_path.parent.chmod(0o700)
            descriptor = os.open(self.database_path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            self.database_path.chmod(0o600)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS face_templates (
                    template_id INTEGER PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
                    vector BLOB NOT NULL,
                    nonce BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(face_templates)").fetchall()
            }
            if "nonce" not in columns:
                connection.execute("ALTER TABLE face_templates ADD COLUMN nonce BLOB")
                legacy = connection.execute(
                    """
                    SELECT template_id, person_id, model_id, dimensions, vector
                    FROM face_templates ORDER BY template_id
                    """
                ).fetchall()
                for template_id, person_id, model_id, dimensions, payload in legacy:
                    if dimensions <= 0 or len(payload) != dimensions * 4:
                        raise FaceRecognitionError(
                            "legacy face template is malformed; remove the template database and re-enroll"
                        )
                    self._encrypt_row(
                        connection,
                        template_id,
                        person_id,
                        model_id,
                        dimensions,
                        bytes(payload),
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS face_templates_person_idx ON face_templates(person_id)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA secure_delete = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add(self, person_id: str, model_id: str, embedding: Sequence[float]) -> None:
        vector = self._validate_embedding(embedding)
        try:
            payload = struct.pack(f"<{len(vector)}f", *vector)
        except (OverflowError, struct.error) as exc:
            raise ValueError("face embedding values must fit in a float32 vector") from exc
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO face_templates (person_id, model_id, dimensions, vector, nonce)
                VALUES (?, ?, ?, ?, ?)
                """,
                (person_id, model_id, len(vector), b"", b""),
            )
            self._encrypt_row(
                connection,
                cursor.lastrowid,
                person_id,
                model_id,
                len(vector),
                payload,
            )

    def list_all(self, model_id: str) -> list[tuple[str, tuple[float, ...]]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT template_id, person_id, dimensions, vector, nonce
                FROM face_templates WHERE model_id = ? ORDER BY template_id
                """,
                (model_id,),
            ).fetchall()
        if not rows:
            return []
        results: list[tuple[str, tuple[float, ...]]] = []
        key = self._get_key()
        aesgcm = self._aesgcm(key)
        for template_id, person_id, dimensions, payload, nonce in rows:
            if dimensions <= 0 or len(payload) != dimensions * 4 + 16 or nonce is None or len(nonce) != 12:
                raise FaceRecognitionError("stored encrypted face template has an invalid payload")
            try:
                payload = aesgcm.decrypt(
                    bytes(nonce),
                    bytes(payload),
                    self._associated_data(template_id, person_id, model_id, dimensions),
                )
            except self._invalid_tag_type() as exc:
                raise FaceRecognitionError(
                    "stored face template authentication failed; the data or Keychain key may be damaged"
                ) from exc
            if len(payload) != dimensions * 4:
                raise FaceRecognitionError("decrypted face template has an invalid vector payload")
            vector = struct.unpack(f"<{dimensions}f", payload)
            if any(not math.isfinite(value) for value in vector):
                raise FaceRecognitionError("stored face template contains non-finite values")
            results.append((person_id, vector))
        return results

    def delete_person(self, person_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM face_templates WHERE person_id = ?", (person_id,))

    def _encrypt_row(
        self,
        connection: sqlite3.Connection,
        template_id: int,
        person_id: str,
        model_id: str,
        dimensions: int,
        payload: bytes,
    ) -> None:
        nonce = os.urandom(12)
        ciphertext = self._aesgcm(self._get_key()).encrypt(
            nonce,
            payload,
            self._associated_data(template_id, person_id, model_id, dimensions),
        )
        connection.execute(
            "UPDATE face_templates SET vector = ?, nonce = ? WHERE template_id = ?",
            (ciphertext, nonce, template_id),
        )

    def _get_key(self) -> bytes:
        with self._key_lock:
            if self._cached_key is not None:
                return self._cached_key
            if self._key_provider is None:
                self._key_provider = MacKeychainKeyProvider(str(self.database_path.resolve()))
            key = self._key_provider.get_or_create_key()
            if not isinstance(key, bytes) or len(key) != 32:
                raise KeyStorageError("template key provider must return exactly 32 bytes")
            self._cached_key = key
            return self._cached_key

    @staticmethod
    def _aesgcm(key: bytes):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise FaceRecognitionError(
                "install server/requirements-identity.txt to use encrypted recognition"
            ) from exc
        return AESGCM(key)

    @staticmethod
    def _invalid_tag_type():
        try:
            from cryptography.exceptions import InvalidTag
        except ImportError as exc:
            raise FaceRecognitionError(
                "install server/requirements-identity.txt to use encrypted recognition"
            ) from exc
        return InvalidTag

    @staticmethod
    def _associated_data(template_id: int, person_id: str, model_id: str, dimensions: int) -> bytes:
        return f"{template_id}\0{person_id}\0{model_id}\0{dimensions}".encode("utf-8")

    @staticmethod
    def _validate_embedding(embedding: Sequence[float]) -> tuple[float, ...]:
        try:
            vector = tuple(float(value) for value in embedding)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("face embedding must be a finite numeric vector") from exc
        if len(vector) < 2 or any(not math.isfinite(value) for value in vector):
            raise ValueError("face embedding must contain at least two finite values")
        if not any(value != 0 for value in vector):
            raise ValueError("face embedding must not be the zero vector")
        return vector


class FaceIdentityService:
    """Privacy-gated identity service that delegates inference to a provider."""

    def __init__(
        self,
        registry: PersonRegistry,
        provider: FaceProvider,
        template_store: TemplateStore,
        *,
        minimum_similarity: float = 0.5,
        minimum_margin: float = 0.05,
        privacy_mode: bool = True,
    ) -> None:
        if not isinstance(privacy_mode, bool):
            raise ValueError("privacy_mode must be a boolean")
        thresholds = (minimum_similarity, minimum_margin)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in thresholds
        ):
            raise ValueError("recognition thresholds must be finite numeric values")
        if not 0 <= minimum_similarity <= 1:
            raise ValueError("minimum_similarity must be between 0 and 1")
        if not 0 <= minimum_margin <= 1:
            raise ValueError("minimum_margin must be between 0 and 1")
        self.registry = registry
        self.provider = provider
        self.template_store = template_store
        self.minimum_similarity = minimum_similarity
        self.minimum_margin = minimum_margin
        self.privacy_mode = privacy_mode
        self.registry.add_recognition_data_deleter(self.template_store.delete_person)

    def set_privacy_mode(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("privacy mode must be a boolean")
        self.privacy_mode = enabled

    def detect_faces(self, frame: object) -> tuple[FaceRegion, ...]:
        """Detect faces in a caller-supplied frame, unless privacy mode is active."""
        if self.privacy_mode:
            return ()
        return self.provider.detect_faces(frame)

    def enroll(self, person_id: str, frame: object) -> None:
        """Explicitly enroll one face for an opted-in profile; frame is not retained."""
        if self.privacy_mode:
            raise ConsentRequiredError("disable privacy mode before explicit enrollment")
        faces = self.provider.detect_faces(frame)
        if len(faces) != 1:
            raise FaceRecognitionError("enrollment requires exactly one detected face")
        self.enroll_detected_face(person_id, frame, faces[0])

    def enroll_detected_face(self, person_id: str, frame: object, face: FaceRegion) -> None:
        """Enroll an explicitly consented face already detected in this same frame."""
        if self.privacy_mode:
            raise ConsentRequiredError("disable privacy mode before explicit enrollment")
        embedding = self.provider.create_embedding(frame, face)
        self.enroll_embedding(person_id, embedding)

    def enroll_embedding(self, person_id: str, embedding: Sequence[float]) -> None:
        """Store one supplied in-memory embedding after checking consent and privacy state."""
        if self.privacy_mode:
            raise ConsentRequiredError("disable privacy mode before explicit enrollment")
        person = self.registry.get_person(person_id)
        if not person.enabled or not person.opted_in:
            raise ConsentRequiredError("an enabled profile with explicit opt-in is required")
        self.template_store.add(person_id, self.provider.model_id, embedding)
        self.registry.enroll(person_id)

    def resolve_identity(self, frame: object, face: FaceRegion) -> IdentityResult:
        """Resolve one already-detected face, returning unknown unless confidently eligible."""
        if self.privacy_mode:
            return IdentityResult("disabled", reason="privacy_mode")
        query = TemplateStore._validate_embedding(self.provider.create_embedding(frame, face))
        best_by_person: dict[str, float] = {}
        for person_id, stored in self.template_store.list_all(self.provider.model_id):
            if len(stored) != len(query):
                continue
            score = self._cosine_similarity(query, stored)
            previous = best_by_person.get(person_id)
            best_by_person[person_id] = score if previous is None else max(previous, score)

        eligible = [
            (person_id, score)
            for person_id, score in best_by_person.items()
            if self.registry.get_recognition_candidate(person_id) is not None
        ]
        eligible.sort(key=lambda item: item[1], reverse=True)
        if not eligible:
            return IdentityResult("unknown", reason="no_eligible_template")
        person_id, score = eligible[0]
        runner_up = eligible[1][1] if len(eligible) > 1 else -1.0
        if score < self.minimum_similarity:
            return IdentityResult("unknown", confidence=score, reason="below_threshold")
        if score - runner_up < self.minimum_margin:
            return IdentityResult("unknown", confidence=score, reason="ambiguous_match")
        return IdentityResult("recognized", person_id=person_id, confidence=score)

    def recognize_frame(self, frame: object) -> IdentityResult:
        """Detect and resolve only a single face; no-face and multi-face frames stay unknown."""
        if self.privacy_mode:
            return IdentityResult("disabled", reason="privacy_mode")
        faces = self.provider.detect_faces(frame)
        if not faces:
            return IdentityResult("unknown", reason="no_face")
        if len(faces) != 1:
            return IdentityResult("unknown", reason="multiple_faces")
        return self.resolve_identity(frame, faces[0])

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return -1.0
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


class OpenCVSFaceProvider:
    """Optional local CPU provider using OpenCV Zoo YuNet detection and SFace.

    Both model files must already exist locally and be supplied explicitly.
    This class performs no downloads and loads neither model until instantiated.
    """

    model_id = "opencv-zoo-sface-2021dec"

    def __init__(
        self,
        detector_model: Path | str,
        recognizer_model: Path | str,
        *,
        detector: object | None = None,
    ) -> None:
        detector_path = Path(detector_model)
        recognizer_path = Path(recognizer_model)
        for path in (detector_path, recognizer_path):
            if not path.is_file():
                raise FileNotFoundError(f"local face model not found: {path}")
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required to use OpenCVSFaceProvider") from exc
        self._cv2 = cv2
        if detector is None:
            from brain.face_detector import YuNetFaceDetector

            detector = YuNetFaceDetector(detector_path)
        self._detector = detector
        self._recognizer = cv2.FaceRecognizerSF.create(
            str(recognizer_path),
            "",
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        self._recognizer_lock = threading.Lock()

    def detect_faces(self, frame: object) -> tuple[FaceRegion, ...]:
        detect_rows = getattr(self._detector, "detect_rows", None)
        if not callable(detect_rows):
            raise FaceRecognitionError("the shared YuNet detector does not provide aligned face rows")
        faces = detect_rows(frame)
        regions = []
        for row in faces:
            values = tuple(float(value) for value in row)
            if len(values) != 15:
                raise FaceRecognitionError("YuNet returned a face row with unexpected dimensions")
            regions.append(
                FaceRegion(
                    box=tuple(int(round(value)) for value in values[:4]),
                    confidence=values[14],
                    landmarks=values[4:14],
                    provider_data=values,
                )
            )
        return tuple(regions)

    def create_embedding(self, frame: object, face: FaceRegion) -> tuple[float, ...]:
        self._frame_size(frame)
        if len(face.provider_data) != 15:
            raise ValueError("face region was not produced by this OpenCV YuNet provider")
        import numpy as np

        detector_row = np.asarray(face.provider_data, dtype=np.float32).reshape(1, 15)
        with self._recognizer_lock:
            aligned = self._recognizer.alignCrop(frame, detector_row)
            embedding = self._recognizer.feature(aligned).reshape(-1)
        return tuple(float(value) for value in embedding)

    @staticmethod
    def _frame_size(frame: object) -> tuple[int, int]:
        shape = getattr(frame, "shape", None)
        if (
            shape is None
            or len(shape) != 3
            or shape[0] <= 0
            or shape[1] <= 0
            or shape[2] < 3
        ):
            raise ValueError("frame must be a non-empty BGR image with at least three channels")
        return int(shape[0]), int(shape[1])


class MockFaceProvider:
    """Simple deterministic provider for tests; never contacts a camera or service."""

    def __init__(
        self,
        *,
        faces: tuple[FaceRegion, ...] = (),
        embeddings: dict[tuple[int, int, int, int], tuple[float, ...]] | None = None,
        model_id: str = "mock-v1",
    ) -> None:
        self.faces = faces
        self.embeddings = embeddings or {}
        self.model_id = model_id

    def detect_faces(self, frame: object) -> tuple[FaceRegion, ...]:
        return self.faces

    def create_embedding(self, frame: object, face: FaceRegion) -> tuple[float, ...]:
        try:
            return self.embeddings[face.box]
        except KeyError as exc:
            raise FaceRecognitionError(f"no mock embedding configured for face {face.box}") from exc


def default_template_database_path() -> Path:
    """Return the non-versioned per-user template database location."""
    return default_data_directory() / "face_templates.sqlite3"
