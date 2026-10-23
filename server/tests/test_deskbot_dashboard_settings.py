"""Tests for isolated DeskBot settings and editable phrase overrides."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deskbot_local.content import PHRASE_DIR, PhraseCatalog, PhraseDataError
from deskbot_local.dashboard_content import EditablePhraseLibrary
from deskbot_local.dashboard_settings import DEFAULTS, DeskBotSettingsStore


class DeskBotSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "deskbot-settings.json"
        self.store = DeskBotSettingsStore(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_defaults_and_validated_updates_persist(self) -> None:
        self.assertEqual(self.store.load(), DEFAULTS)
        saved = self.store.update({
            "language": "de",
            "spontaneous_events_enabled": True,
            "min_event_interval_minutes": 30,
            "max_event_interval_minutes": 90,
            "active_start": "07:45",
            "quiet_mode": True,
            "touch_sensitivity": 61,
            "privacy_mode": False,
            "recognition_enabled": True,
        })
        self.assertEqual(self.store.load(), saved)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_invalid_values_and_cross_field_constraints_are_rejected(self) -> None:
        invalid_updates = (
            {"language": "fr"},
            {"quiet_mode": 1},
            {"active_start": "25:00"},
            {"touch_sensitivity": 101},
            {"min_event_interval_minutes": True},
            {"unexpected": "value"},
            {"min_event_interval_minutes": 120, "max_event_interval_minutes": 45},
            {"recognition_enabled": True},
        )
        for changes in invalid_updates:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.update(changes)

    def test_malformed_settings_file_is_reported(self) -> None:
        self.path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "could not read DeskBot settings"):
            self.store.load()


class EditablePhraseLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name) / "content"
        self.library = EditablePhraseLibrary(self.directory)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_reads_examples_and_validated_user_override(self) -> None:
        example, customized = self.library.read("en")
        self.assertFalse(customized)
        original = json.loads(example)
        original["greet_unknown"][0]["text"] = "Hello from my local copy."
        self.library.save("en", json.dumps(original))
        edited, customized = self.library.read("en")
        self.assertTrue(customized)
        self.assertIn("Hello from my local copy.", edited)
        with patch("deskbot_local.content.USER_PHRASE_DIR", self.directory):
            self.assertEqual(PhraseCatalog().load("en")["greet_unknown"][0]["text"], "Hello from my local copy.")

    def test_rejects_malformed_json_and_missing_required_entries(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            self.library.save("de", "{")
        incomplete = json.loads((PHRASE_DIR / "de.json").read_text(encoding="utf-8"))
        incomplete.pop("sneeze")
        with self.assertRaises(PhraseDataError):
            self.library.save("de", json.dumps(incomplete))
        with self.assertRaises(ValueError):
            self.library.save("fr", "{}")

    def test_reset_restores_example_library(self) -> None:
        example, _ = self.library.read("de")
        self.library.save("de", example)
        self.library.reset("de")
        restored, customized = self.library.read("de")
        self.assertFalse(customized)
        self.assertEqual(restored, example)
