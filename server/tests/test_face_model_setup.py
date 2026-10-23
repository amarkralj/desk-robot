"""Pinned model setup integrity tests; no downloads are performed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deskbot_local.setup_face_models import MODELS, REVISION, provision


class FaceModelSetupTests(unittest.TestCase):
    def test_open_cv_zoo_revision_and_expected_assets_are_pinned(self) -> None:
        self.assertEqual(len(REVISION), 40)
        self.assertIn("face_detection_yunet_2023mar.onnx", MODELS)
        self.assertIn("face_recognition_sface_2021dec.onnx", MODELS)
        self.assertTrue(all(len(digest) == 64 for _, digest in MODELS.values()))

    def test_existing_model_checksum_mismatch_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            model = model_dir / "face_detection_yunet_2023mar.onnx"
            model.write_bytes(b"user data")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                provision(model_dir)
            self.assertEqual(model.read_bytes(), b"user data")


if __name__ == "__main__":
    unittest.main()
