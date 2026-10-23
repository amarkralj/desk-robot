"""Tests for dry-run robot actions and existing firmware command mappings."""

from __future__ import annotations

import io
import unittest

from deskbot_local import (
    ActionCapability,
    BehaviorActionExecutor,
    BehaviorResponse,
    DryRunRobotAdapter,
    greet_unknown,
    on_head_tap,
)


class RobotActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = io.StringIO()
        self.adapter = DryRunRobotAdapter(output=self.output)

    def test_expression_and_head_commands_map_to_documented_websocket_messages(self) -> None:
        expression = self.adapter.set_expression("happy")
        pan = self.adapter.pan(-95)
        tilt = self.adapter.tilt(85)
        self.assertEqual(expression.message_dict(), {"type": "emotion", "name": "happy"})
        self.assertEqual(pan.message_dict(), {"type": "pan", "deg": -95.0})
        self.assertEqual(tilt.message_dict(), {"type": "tilt", "deg": 85.0})
        self.assertEqual(expression.capability, ActionCapability.WEBSOCKET)
        self.assertEqual(pan.capability, ActionCapability.WEBSOCKET)
        self.assertEqual(tilt.capability, ActionCapability.WEBSOCKET)
        self.assertTrue(all(record.enabled for record in self.adapter.records))

    def test_pan_tilt_reject_out_of_range_nonfinite_and_non_numeric_angles(self) -> None:
        for call in (
            lambda: self.adapter.pan(-95.1),
            lambda: self.adapter.pan(95.1),
            lambda: self.adapter.tilt(-85.1),
            lambda: self.adapter.tilt(85.1),
            lambda: self.adapter.pan(float("nan")),
            lambda: self.adapter.tilt(float("inf")),
            lambda: self.adapter.pan(True),
        ):
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()
        self.assertEqual(self.adapter.records, [])

    def test_blink_and_animations_are_reported_without_inventing_websocket_messages(self) -> None:
        blink = self.adapter.blink()
        sneeze = self.adapter.animate_sneeze()
        laugh = self.adapter.animate_laugh()
        self.assertEqual(blink.capability, ActionCapability.FIRMWARE_CONSOLE)
        self.assertIsNone(blink.protocol_message)
        self.assertEqual(sneeze.capability, ActionCapability.SIMULATED)
        self.assertEqual(laugh.capability, ActionCapability.SIMULATED)
        self.assertIsNone(sneeze.protocol_message)
        self.assertIsNone(laugh.protocol_message)

    def test_speech_prints_phrase_and_does_not_send_or_play_audio(self) -> None:
        record = self.adapter.speak_phrase("Hallo DeskBot!", "de")
        self.assertEqual(record.capability, ActionCapability.AUDIO_STREAM)
        self.assertIsNone(record.protocol_message)
        self.assertIn("Would speak [de]: Hallo DeskBot!", self.output.getvalue())
        self.assertIn("[dry-run]", self.output.getvalue())

    def test_quiet_state_suppresses_speech_and_idle_maps_to_asleep_protocol(self) -> None:
        quiet = self.adapter.set_quiet(True)
        speech = self.adapter.speak_phrase("Hello", "en")
        idle = self.adapter.set_idle(True)
        awake = self.adapter.set_idle(False)
        self.assertEqual(quiet.capability, ActionCapability.LOCAL_ONLY)
        self.assertFalse(speech.enabled)
        self.assertIn("suppressed by quiet mode", speech.description)
        self.assertEqual(idle.message_dict(), {"type": "asleep", "on": True})
        self.assertEqual(awake.message_dict(), {"type": "asleep", "on": False})
        self.assertEqual(idle.capability, ActionCapability.WEBSOCKET)

    def test_disabled_actions_are_recorded_but_not_performed(self) -> None:
        adapter = DryRunRobotAdapter(output=self.output, disabled_actions={"pan", "speak_phrase"})
        pan = adapter.pan(20)
        speech = adapter.speak_phrase("No output", "en")
        self.assertFalse(pan.enabled)
        self.assertFalse(speech.enabled)
        self.assertIn("Disabled:", pan.description)
        self.assertIn("Disabled:", speech.description)
        self.assertIn(pan, adapter.records)
        self.assertIn(speech, adapter.records)

    def test_behavior_executor_uses_injected_adapter(self) -> None:
        response = greet_unknown("en")
        executor = BehaviorActionExecutor(self.adapter)
        records = executor.execute(response)
        self.assertGreaterEqual(len(records), 2)
        self.assertEqual(records[0].action, "set_expression")
        self.assertEqual(records[-1].action, "speak_phrase")
        self.assertEqual(tuple(self.adapter.records), records)

    def test_default_executor_uses_dry_run_adapter(self) -> None:
        executor = BehaviorActionExecutor()
        self.assertIsInstance(executor.adapter, DryRunRobotAdapter)

    def test_head_tap_response_does_not_claim_to_detect_touch(self) -> None:
        response = on_head_tap("en")
        records = self.adapter.react_to_head_tap(response)
        self.assertTrue(records)
        self.assertEqual(records[0].action, "head_tap")
        self.assertEqual(records[0].capability, ActionCapability.SIMULATED)
        with self.assertRaises(ValueError):
            self.adapter.react_to_head_tap(greet_unknown("en"))

        disabled = DryRunRobotAdapter(output=self.output, disabled_actions={"head_tap"})
        self.assertEqual(disabled.react_to_head_tap(response)[0].enabled, False)
        self.assertEqual(len(disabled.records), 1)

    def test_response_action_mapping_only_uses_supported_or_simulated_actions(self) -> None:
        sneeze = BehaviorResponse(
            text="Achoo!",
            language="en",
            expression="surprised",
            action="sneeze_animation",
            event_type="sneeze",
            response_id="test-sneeze",
        )
        records = BehaviorActionExecutor(self.adapter).execute(sneeze)
        self.assertEqual([record.action for record in records], [
            "set_expression",
            "sneeze_animation",
            "speak_phrase",
        ])
        self.assertEqual(records[1].capability, ActionCapability.SIMULATED)

    def test_invalid_expressions_languages_phrases_and_disabled_action_names_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter.set_expression("not-a-face")
        with self.assertRaises(ValueError):
            self.adapter.speak_phrase("Hello", "fr")
        with self.assertRaises(ValueError):
            self.adapter.speak_phrase("  ", "en")
        with self.assertRaises(ValueError):
            DryRunRobotAdapter(disabled_actions={"teleport"})

    def test_every_operation_is_dry_run_and_printed(self) -> None:
        self.adapter.set_expression("happy")
        self.adapter.blink()
        self.adapter.pan(0)
        self.adapter.tilt(0)
        self.adapter.speak_phrase("Hello", "en")
        self.adapter.animate_sneeze()
        self.adapter.animate_laugh()
        self.adapter.set_idle(True)
        self.adapter.set_quiet(True)
        output = self.output.getvalue()
        self.assertEqual(output.count("[dry-run]"), len(self.adapter.records))
        self.assertTrue(all(record.protocol_message is None or record.enabled for record in self.adapter.records))


if __name__ == "__main__":
    unittest.main()
