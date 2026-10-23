"""Interactive simulator and command parser tests."""

from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from deskbot_local.demo import DeskBotDemo
from deskbot_local.intent import parse_demo_command
from deskbot_local.registry import PersonRegistry


class DemoCommandParserTests(unittest.TestCase):
    def test_examples_and_optional_arguments_parse(self) -> None:
        self.assertEqual(parse_demo_command("known Alex de").arguments, ("Alex", "de"))
        self.assertEqual(parse_demo_command('known "Alex Morgan"').arguments, ("Alex Morgan", ""))
        self.assertEqual(parse_demo_command("unknown").arguments, ("en",))
        self.assertEqual(parse_demo_command("boss away").command, "boss_away")
        self.assertEqual(parse_demo_command("boss here").command, "boss_here")
        self.assertEqual(parse_demo_command("simulate start").command, "simulate_start")
        self.assertEqual(parse_demo_command("tick 10").arguments, ("10",))

    def test_invalid_commands_and_arguments_are_rejected(self) -> None:
        for line in (
            "known",
            "unknown fr",
            "boss maybe",
            "simulate later",
            "tick 0",
            "tick -2",
            "yes extra",
            "not-a-command",
        ):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_demo_command(line)


class DeskBotDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output = io.StringIO()
        registry = PersonRegistry(Path(self.temporary_directory.name) / "people.sqlite3")
        self.demo = DeskBotDemo(
            seed=37,
            output=self.output,
            registry=registry,
            now=datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        )

    def tearDown(self) -> None:
        self.demo.close()
        self.temporary_directory.cleanup()

    def command(self, text: str) -> str:
        before = self.output.tell()
        self.assertTrue(self.demo.run_command(text))
        return self.output.getvalue()[before:]

    def test_known_requires_a_registered_enrolled_and_greeting_enabled_profile(self) -> None:
        before_enrollment = self.command("known Alex")
        self.assertIn("Unknown in this demo", before_enrollment)
        self.assertIn("greet_unknown", before_enrollment)

        self.command("enroll Alex de")
        no_greeting = self.command("known Alex")
        self.assertIn("Unknown in this demo", no_greeting)
        self.command("greetings Alex on")
        known = self.command("known Alex")
        self.assertIn("greet_known", known)
        self.assertIn("Language: de", known)
        self.assertIn("Alex", known)
        self.assertIn("simulated (dry-run; not physically executed", known)

    def test_unknown_person_never_gets_personalized_greeting(self) -> None:
        self.command("enroll Alex de")
        self.command("greetings Alex on")
        unknown = self.command("unknown de")
        self.assertIn("greet_unknown", unknown)
        self.assertNotIn("greet_known", unknown)

    def test_joke_offer_can_be_accepted_or_rejected_in_sequence(self) -> None:
        offered = self.command("joke en")
        self.assertIn("joke_offer", offered)
        accepted = self.command("yes")
        self.assertIn("Event: joke_answer", accepted)
        self.assertIn("What is a robot's favorite coffee break?", accepted)
        self.assertNotIn("no joke offer", accepted)

        self.command("joke de")
        rejected = self.command("no")
        self.assertIn("Event: joke_answer", rejected)
        self.assertIn("Language: de", rejected)
        self.assertIsNone(self.demo.pending_joke_language)

    def test_yes_or_no_without_an_offer_reports_actionable_error(self) -> None:
        output = self.command("yes")
        self.assertIn("there is no pending joke offer", output)

    def test_mute_suppresses_spoken_action_without_changing_behavior_selection(self) -> None:
        self.command("mute")
        response = self.command("unknown en")
        self.assertIn("Execution: simulated", response)
        self.assertIn("Speech suppressed by quiet mode", response)
        self.command("unmute")
        unmuted = self.command("unknown en")
        self.assertIn("Would speak [en]", unmuted)

    def test_owner_absent_reaction_occurs_once_per_presence_transition(self) -> None:
        configured = self.command("owner Morgan")
        self.assertIn("Configured demo owner", configured)
        here = self.command("boss here")
        self.assertIn("boss_present", here)

        away = self.command("boss away")
        self.assertIn("boss_absent", away)
        repeated = self.command("boss away")
        self.assertIn("no transition reaction", repeated)
        self.assertNotIn("boss_absent", repeated)

        returned = self.command("boss here")
        self.assertIn("boss_present", returned)
        away_again = self.command("boss away")
        self.assertIn("boss_absent", away_again)

    def test_spontaneous_scheduler_requires_explicit_start_and_manual_tick(self) -> None:
        stopped = self.command("tick")
        self.assertIn("scheduler is stopped", stopped)
        started = self.command("simulate start")
        self.assertIn("only on explicit tick commands", started)
        event = self.command("tick 45")
        self.assertIn("Scheduled event:", event)
        self.assertIn("simulated (dry-run; not physically executed", event)
        self.command("simulate stop")
        stopped_again = self.command("tick")
        self.assertIn("scheduler is stopped", stopped_again)

    def test_seed_makes_behavior_selection_reproducible(self) -> None:
        other_output = io.StringIO()
        other_registry = PersonRegistry(Path(self.temporary_directory.name) / "other.sqlite3")
        other = DeskBotDemo(
            seed=37,
            output=other_output,
            registry=other_registry,
            now=datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        )
        try:
            for command in ("unknown de", "sneeze en", "joke de", "yes"):
                self.demo.run_command(command)
                other.run_command(command)
            self.assertEqual(self.output.getvalue(), other_output.getvalue())
        finally:
            other.close()

    def test_head_tap_command_is_explicitly_simulated(self) -> None:
        result = self.command("pet")
        self.assertIn("Simulate a head-tap reaction", result)
        self.assertIn("no touch sensor", result)
        self.assertIn("not physically executed", result)


if __name__ == "__main__":
    unittest.main()
