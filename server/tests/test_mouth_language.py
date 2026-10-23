"""Language-specific voice selection without network calls or audio playback."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from brain import config, main, mouth, settings


class PassThroughLeveler:
    def process(self, audio: bytes) -> bytes:
        return audio

    def flush(self) -> bytes:
        return b""


class LanguageVoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_config = (
            config.TTS_VOICE_ID,
            config.TTS_VOICE_ID_EN,
            config.TTS_VOICE_ID_DE,
            config.TTS_FALLBACK_VOICE_EN,
            config.TTS_FALLBACK_VOICE_DE,
            config.TTS_LANGUAGE,
            main.current_settings,
        )

    def tearDown(self) -> None:
        (
            config.TTS_VOICE_ID,
            config.TTS_VOICE_ID_EN,
            config.TTS_VOICE_ID_DE,
            config.TTS_FALLBACK_VOICE_EN,
            config.TTS_FALLBACK_VOICE_DE,
            config.TTS_LANGUAGE,
            main.current_settings,
        ) = self.saved_config

    def test_language_specific_fish_id_and_legacy_fallback(self) -> None:
        config.TTS_VOICE_ID = "legacy-voice"
        config.TTS_VOICE_ID_EN = "english-voice"
        config.TTS_VOICE_ID_DE = ""

        self.assertEqual(mouth.voice_id_for_language("en"), "english-voice")
        self.assertEqual(mouth.voice_id_for_language("de"), "legacy-voice")
        config.TTS_VOICE_ID_EN = ""
        self.assertEqual(mouth.voice_id_for_language("en"), "legacy-voice")
        with self.assertRaises(ValueError):
            mouth.voice_id_for_language("fr")  # type: ignore[arg-type]

    def test_language_specific_macos_voice_selection(self) -> None:
        config.TTS_FALLBACK_VOICE_EN = "English Voice"
        config.TTS_FALLBACK_VOICE_DE = "German Voice"

        self.assertEqual(mouth.builtin_voice_for_language("en"), "English Voice")
        self.assertEqual(mouth.builtin_voice_for_language("de"), "German Voice")
        with self.assertRaises(ValueError):
            mouth.builtin_voice_for_language("fr")  # type: ignore[arg-type]

    def test_local_only_stream_uses_language_fallback_and_never_checks_fish(self) -> None:
        with (
            patch.object(mouth, "Leveler", PassThroughLeveler),
            patch.object(mouth, "fish_available", side_effect=AssertionError("Fish must not be checked")),
            patch.object(mouth, "_synthesize_builtin", return_value=b"local-pcm") as synthesize,
        ):
            result = b"".join(mouth.stream("Guten Tag", language="de", local_only=True))

        self.assertEqual(result, b"local-pcm")
        synthesize.assert_called_once_with("Guten Tag.", "de")

    def test_fish_stream_receives_selected_language_voice(self) -> None:
        config.TTS_VOICE_ID = "legacy-voice"
        config.TTS_VOICE_ID_EN = "english-voice"
        config.TTS_VOICE_ID_DE = "german-voice"
        with (
            patch.object(mouth, "Leveler", PassThroughLeveler),
            patch.object(mouth, "fish_available", return_value=True),
            patch.object(mouth, "_fish_stream", return_value=iter((b"fish-pcm",))) as fish_stream,
        ):
            result = b"".join(mouth.stream("Guten Tag", language="de", require_fish=True))

        self.assertEqual(result, b"fish-pcm")
        fish_stream.assert_called_once_with("Guten Tag.", "german-voice")

    def test_required_fish_test_does_not_fall_back_to_mac_voice(self) -> None:
        with (
            patch.object(mouth, "Leveler", PassThroughLeveler),
            patch.object(mouth, "fish_available", return_value=True),
            patch.object(mouth, "_fish_stream", side_effect=OSError("offline")),
            patch.object(mouth, "_synthesize_builtin") as synthesize,
        ):
            with self.assertRaisesRegex(RuntimeError, "Fish Audio voice test failed"):
                b"".join(mouth.stream("Hello", language="en", require_fish=True))
        synthesize.assert_not_called()

    def test_speech_language_setting_applies_without_inference(self) -> None:
        selected = settings.defaults()
        selected["rocky"]["speech_language"] = "de"
        main.apply_settings(selected)
        self.assertEqual(config.TTS_LANGUAGE, "de")
        self.assertEqual(settings.clean_value("rocky", "speech_language", "en"), "en")
        with self.assertRaises(ValueError):
            settings.clean_value("rocky", "speech_language", "auto")

    def test_spoken_reply_passes_explicit_language_to_mouth(self) -> None:
        config.TTS_LANGUAGE = "de"
        loop = asyncio.new_event_loop()
        reply = main.SpokenReply(loop, main.Timeline(0.0))
        reply.sentences.put("Guten Tag.")
        reply.sentences.put(None)
        try:
            with patch("brain.main.mouth.stream", return_value=iter((b"pcm",))) as stream:
                reply._voice()
        finally:
            loop.close()
        stream.assert_called_once()
        self.assertEqual(stream.call_args.kwargs["language"], "de")


if __name__ == "__main__":
    unittest.main()
