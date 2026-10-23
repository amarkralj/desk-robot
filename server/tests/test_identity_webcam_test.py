"""The explicit identity webcam command stays closed unless enabled by the user."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from deskbot_local import identity_webcam_test


class DisabledSettings:
    def load(self) -> dict[str, object]:
        return {"recognition_enabled": False, "privacy_mode": True}


class IdentityWebcamCommandTests(unittest.TestCase):
    def test_disabled_settings_return_before_opening_camera(self) -> None:
        error = io.StringIO()
        with (
            patch.object(identity_webcam_test, "DeskBotSettingsStore", return_value=DisabledSettings()),
            patch.object(
                identity_webcam_test,
                "run_webcam_test",
                side_effect=AssertionError("camera must remain closed"),
            ),
        ):
            result = identity_webcam_test.run_identity_webcam_test(error_output=error)
        self.assertEqual(result, 2)
        self.assertIn("Enable local recognition", error.getvalue())


if __name__ == "__main__":
    unittest.main()
