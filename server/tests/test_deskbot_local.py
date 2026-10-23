"""Offline DeskBot response primitives: no brain, network, or hardware."""

from __future__ import annotations

import builtins
import json
import socket
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from deskbot_local import (
    PhraseCatalog,
    answer_joke,
    boss_absent,
    boss_present,
    greet_known,
    greet_unknown,
    idle_reaction,
    offer_joke,
    on_head_tap,
    sneeze,
)


class FirstChoice:
    def choice(self, values: list[dict]) -> dict:
        return values[0]


class LastChoice:
    def choice(self, values: list[dict]) -> dict:
        return values[-1]


class DeskBotLocalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.first = FirstChoice()

    def test_english_and_german_phrase_data(self) -> None:
        english = greet_unknown("en", chooser=self.first)
        german = greet_unknown("de", chooser=self.first)
        self.assertEqual(english.language, "en")
        self.assertIn("Hi!", english.text)
        self.assertEqual(german.language, "de")
        self.assertIn("Hallo!", german.text)
        self.assertEqual(english.event_type, "greet_unknown")
        self.assertEqual(german.response_id, "greet_unknown_question")

    def test_required_dialogue_and_fallbacks_exist_in_both_languages(self) -> None:
        catalog = PhraseCatalog()
        for language in ("en", "de"):
            with self.subTest(language=language):
                data = catalog.load(language)
                ids = []
                for category in (
                    "greet_known",
                    "greet_unknown",
                    "head_tap",
                    "sneeze",
                    "joke_offer",
                    "boss_absent",
                    "boss_present",
                    "idle_reaction",
                ):
                    entries = data[category]
                    ids.extend(entry["id"] for entry in entries)
                    self.assertTrue(any(entry["fallback"] for entry in entries), category)
                    self.assertEqual(sum(entry["fallback"] for entry in entries), 1, category)
                for answer in ("yes", "no"):
                    entries = data["joke_answer"][answer]
                    ids.extend(entry["id"] for entry in entries)
                    self.assertTrue(entries)
                    self.assertEqual(sum(entry["fallback"] for entry in entries), 1, answer)
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(len(ids), 22)
        german_fallback = next(entry for entry in catalog.load("de")["greet_unknown"] if entry["fallback"])
        self.assertEqual(german_fallback["text"], "Hallo! Ich bin DeskBot. Schön, dich kennenzulernen.")
        self.assertEqual(
            on_head_tap("de", catalog=catalog, chooser=FirstChoice()).event_type,
            "head_tap",
        )
        german_data = catalog.load("de")
        english_data = catalog.load("en")
        self.assertEqual(next(entry for entry in german_data["sneeze"] if entry["fallback"])["text"],
                         "Hatschi! Oh, bless me!")
        self.assertEqual(next(entry for entry in german_data["joke_offer"] if entry["fallback"])["text"],
                         "Hey, willst du einen Witz hören?")
        self.assertIn("Chef ist nicht da", next(
            entry for entry in german_data["boss_absent"] if entry["fallback"]
        )["text"])
        self.assertEqual(next(entry for entry in english_data["sneeze"] if entry["fallback"])["text"],
                         "Achoo! Oh, bless me!")
        self.assertEqual(next(entry for entry in english_data["joke_offer"] if entry["fallback"])["text"],
                         "Hey, want to hear a joke?")

    def test_known_greeting_uses_only_the_supplied_name(self) -> None:
        english = greet_known("Alex", "en", chooser=self.first)
        german = greet_known("Alex", "de", chooser=self.first)
        self.assertIn("Alex", english.text)
        self.assertIn("Alex", german.text)
        self.assertNotIn("{person_name}", english.text)
        self.assertEqual(english.response_id, "greet_known_question")

    def test_all_behavior_primitives_return_descriptions(self) -> None:
        cases = (
            (on_head_tap("en", chooser=self.first), "head_tap", "blink"),
            (sneeze("de", chooser=self.first), "sneeze", "sneeze_animation"),
            (offer_joke("en", chooser=self.first), "joke_offer", None),
            (boss_absent("de", chooser=self.first), "boss_absent", "head_tilt"),
            (boss_present("en", chooser=self.first), "boss_present", "blink"),
            (idle_reaction("de", chooser=self.first), "idle_reaction", "blink"),
        )
        for response, expected_event, expected_action in cases:
            with self.subTest(event=expected_event):
                self.assertTrue(response.text)
                self.assertEqual(response.event_type, expected_event)
                self.assertEqual(response.action, expected_action)
                self.assertTrue(response.response_id)
                self.assertTrue(response.expression)

    def test_joke_acceptance_and_rejection(self) -> None:
        accepted = answer_joke("yes", "en", chooser=self.first)
        declined = answer_joke("nein", "de", chooser=self.first)
        self.assertIn("raise the bar", accepted.text)
        self.assertIn("anspruchsvolles Publikum", declined.text)
        self.assertEqual(answer_joke(True, "de", chooser=self.first).response_id, "joke_yes_meeting")
        self.assertEqual(answer_joke(False, "en", chooser=self.first).response_id, "joke_no_audience")

    def test_injected_selector_controls_random_choice(self) -> None:
        first = greet_unknown("en", chooser=FirstChoice())
        last = greet_unknown("en", chooser=LastChoice())
        self.assertNotEqual(first.response_id, last.response_id)

    def test_missing_names_and_invalid_inputs_are_rejected(self) -> None:
        for name in ("", "  ", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                greet_known(name, "en")
        with self.assertRaises(ValueError):
            greet_unknown("fr")
        with self.assertRaises(ValueError):
            answer_joke("maybe", "en")

    def test_missing_phrase_file_returns_explicit_non_spoken_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            response = greet_unknown("en", catalog=PhraseCatalog(directory))
        self.assertIsNone(response.text)
        self.assertEqual(response.response_id, "content_unavailable")
        self.assertIn("could not read phrase data", response.error)

    def test_malformed_phrase_file_returns_explicit_non_spoken_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            phrase_file = Path(directory) / "en.json"
            phrase_file.write_text("{not valid json", encoding="utf-8")
            response = on_head_tap("en", catalog=PhraseCatalog(directory))
        self.assertIsNone(response.text)
        self.assertEqual(response.event_type, "head_tap")
        self.assertIn("could not read phrase data", response.error)

    def test_invalid_phrase_schema_is_reported_without_external_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            phrase_file = Path(directory) / "en.json"
            phrase_file.write_text(json.dumps({"schema_version": 1, "language": "en"}), encoding="utf-8")
            response = offer_joke("en", catalog=PhraseCatalog(directory))
        self.assertIsNone(response.text)
        self.assertIn("greet_known", response.error)

    def test_only_fallback_entries_are_used_when_regular_phrases_are_removed(self) -> None:
        source = PhraseCatalog().load("de")
        source["greet_unknown"] = [entry for entry in source["greet_unknown"] if entry["fallback"]]
        source["joke_answer"]["yes"] = [entry for entry in source["joke_answer"]["yes"] if entry["fallback"]]
        source["joke_answer"]["no"] = [entry for entry in source["joke_answer"]["no"] if entry["fallback"]]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "de.json").write_text(json.dumps(source), encoding="utf-8")
            catalog = PhraseCatalog(directory)
            self.assertEqual(
                greet_unknown("de", catalog=catalog, chooser=LastChoice()).response_id,
                "greet_unknown_welcome",
            )
            self.assertEqual(answer_joke(True, "de", catalog=catalog).response_id, "joke_yes_recharge")
            self.assertEqual(answer_joke(False, "de", catalog=catalog).response_id, "joke_no_save")

    def test_missing_fallback_is_rejected_as_unavailable_content(self) -> None:
        source = PhraseCatalog().load("en")
        source["joke_answer"]["yes"] = [
            entry for entry in source["joke_answer"]["yes"] if not entry["fallback"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "en.json").write_text(json.dumps(source), encoding="utf-8")
            response = answer_joke(True, "en", catalog=PhraseCatalog(directory))
        self.assertIsNone(response.text)
        self.assertIn("exactly one fallback", response.error)

    def test_no_network_subprocess_or_sensor_access(self) -> None:
        original_import = builtins.__import__
        forbidden_imports = {"brain", "cv2", "openai", "sounddevice", "websockets"}

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name.split(".", maxsplit=1)[0] in forbidden_imports:
                raise AssertionError(f"unexpected dependency access: {name}")
            return original_import(name, *args, **kwargs)

        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network access")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network access")),
            patch.object(subprocess, "run", side_effect=AssertionError("subprocess access")),
            patch("builtins.__import__", side_effect=guarded_import),
        ):
            responses = (
                greet_known("Sam", "en", chooser=self.first),
                greet_unknown("de", chooser=self.first),
                on_head_tap("en", chooser=self.first),
                sneeze("de", chooser=self.first),
                offer_joke("en", chooser=self.first),
                answer_joke(True, "de", chooser=self.first),
                boss_absent("en", chooser=self.first),
                boss_present("de", chooser=self.first),
                idle_reaction("en", chooser=self.first),
            )
        self.assertTrue(all(response.text for response in responses))


if __name__ == "__main__":
    unittest.main()
