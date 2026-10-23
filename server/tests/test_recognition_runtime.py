"""Deterministic tests for stable local identity status and owner greetings."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deskbot_local.content import PhraseCatalog
from deskbot_local.identity import IdentityResult
from deskbot_local.recognition_runtime import OwnerGreeting, RecognitionRuntime
from deskbot_local.registry import PersonRegistry


class FirstChoice:
    def choice(self, values: list[dict]) -> dict:
        return values[0]


class RecognitionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.registry = PersonRegistry(Path(self.temporary_directory.name) / "people.sqlite3")
        owner = self.registry.create_person("Sam", person_id="owner-1", role="owner")
        self.registry.record_opt_in(owner.person_id, True)
        self.registry.enroll(owner.person_id)
        self.registry.set_personalized_greetings_enabled(owner.person_id, True)
        self.registry.set_configured_owner(owner.person_id)
        self.greetings: list[OwnerGreeting] = []
        self.now = 1000.0
        self.runtime = RecognitionRuntime(
            self.registry,
            self.greetings.append,
            chooser=FirstChoice(),
            clock=lambda: self.now,
            model_available=True,
            enabled=True,
            privacy_mode=False,
            automatic_greetings=True,
            stable_frames=3,
            presence_reset_frames=2,
            cooldown_seconds=60,
        )
        self.owner_match = IdentityResult("recognized", person_id="owner-1", confidence=0.88)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_greeting_waits_for_stable_owner_and_is_german(self) -> None:
        self.runtime.process(self.owner_match)
        self.assertEqual(self.runtime.status()["status"], "unknown")
        self.runtime.process(self.owner_match)
        self.assertEqual(self.greetings, [])
        result = self.runtime.process(self.owner_match)
        self.assertEqual(result["status"], "recognized")
        self.assertEqual(result["display_name"], "Sam")
        self.assertEqual(len(self.greetings), 1)
        self.assertIn("Chef", self.greetings[0].text)
        self.assertEqual(self.greetings[0].response_id, "owner_greet_morning")

    def test_unknown_faces_never_greet_and_presence_reset_allows_return_transition(self) -> None:
        for _ in range(3):
            self.runtime.process(self.owner_match)
        self.assertEqual(len(self.greetings), 1)
        unknown = IdentityResult("unknown", reason="below_threshold")
        self.runtime.process(unknown)
        self.assertEqual(self.runtime.status()["status"], "recognized")
        self.runtime.process(unknown)
        self.assertEqual(self.runtime.status()["display_name"], "Unknown")
        self.now += 61
        for _ in range(3):
            self.runtime.process(self.owner_match)
        self.assertEqual(len(self.greetings), 2)
        self.assertNotEqual(self.greetings[0].response_id, self.greetings[1].response_id)

    def test_cooldown_prevents_repeated_owner_greetings(self) -> None:
        for _ in range(3):
            self.runtime.process(self.owner_match)
        for _ in range(2):
            self.runtime.process(IdentityResult("unknown", reason="no_face"))
        self.runtime.process(self.owner_match)
        for _ in range(2):
            self.runtime.process(IdentityResult("unknown", reason="no_face"))
        for _ in range(3):
            self.runtime.process(self.owner_match)
        self.assertEqual(len(self.greetings), 1)

    def test_recent_three_greeting_ids_are_not_reused(self) -> None:
        self.runtime.cooldown_seconds = 0
        for _ in range(4):
            for _ in range(3):
                self.runtime.process(self.owner_match)
            if len(self.greetings) < 4:
                for _ in range(2):
                    self.runtime.process(IdentityResult("unknown", reason="no_face"))
        self.assertEqual(len(self.greetings), 4)
        self.assertEqual(len({g.response_id for g in self.greetings[-3:]}), 3)

    def test_recognized_non_owner_does_not_receive_owner_greeting(self) -> None:
        colleague = self.registry.create_person("Alex", person_id="colleague-1")
        self.registry.record_opt_in(colleague.person_id, True)
        self.registry.enroll(colleague.person_id)
        result = IdentityResult("recognized", person_id=colleague.person_id, confidence=0.91)
        for _ in range(3):
            output = self.runtime.process(result)
        self.assertEqual(output["display_name"], "Alex")
        self.assertEqual(self.greetings, [])

    def test_consent_withdrawal_clears_stable_identity_immediately(self) -> None:
        for _ in range(3):
            self.runtime.process(self.owner_match)
        self.registry.record_opt_in("owner-1", False)
        result = self.runtime.process(IdentityResult("unknown", reason="no_eligible_template"))
        self.assertEqual(result["display_name"], "Unknown")
        self.assertEqual(result["status"], "unknown")

    def test_automatic_greetings_can_be_disabled(self) -> None:
        self.runtime.update_settings(enabled=True, privacy_mode=False, automatic_greetings=False)
        for _ in range(3):
            self.runtime.process(self.owner_match)
        self.assertEqual(self.runtime.status()["status"], "recognized")
        self.assertEqual(self.greetings, [])

    def test_privacy_mode_and_missing_model_fail_closed(self) -> None:
        self.runtime.update_settings(enabled=True, privacy_mode=True, automatic_greetings=True)
        result = self.runtime.process(self.owner_match)
        self.assertEqual(result["status"], "disabled")
        self.runtime.update_settings(enabled=True, privacy_mode=False, automatic_greetings=True)
        self.runtime.set_unavailable("model_missing")
        result = self.runtime.process(self.owner_match)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["display_name"], "Unknown")
        self.assertEqual(self.greetings, [])

    def test_greeting_content_errors_do_not_fall_back_to_generated_text(self) -> None:
        missing = PhraseCatalog(Path(self.temporary_directory.name) / "missing")
        self.runtime.catalog = missing
        for _ in range(3):
            result = self.runtime.process(self.owner_match)
        self.assertEqual(self.greetings, [])
        self.assertTrue(str(result["reason"]).startswith("greeting_content_unavailable:"))


if __name__ == "__main__":
    unittest.main()
