"""Explicit local speech smoke test; never starts the brain or robot."""

from __future__ import annotations

import argparse
import subprocess
import sys

from . import config, mouth

SAMPLES = {
    "en": "Hello! This is a local DeskBot English voice test.",
    "de": "Hallo! Dies ist ein lokaler deutscher DeskBot-Stimmtest.",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test a configured DeskBot voice on this Mac.")
    parser.add_argument("--language", choices=("en", "de"), required=True)
    parser.add_argument(
        "--provider",
        choices=("macos", "fish"),
        default="macos",
        help="macos uses the local say voice (default); fish explicitly uses Fish Audio",
    )
    parser.add_argument("--text", help="Optional phrase to speak")
    args = parser.parse_args(argv)

    language = args.language
    if args.provider == "macos":
        voice = mouth.builtin_voice_for_language(language)
        local_only = True
        require_fish = False
    else:
        if not mouth.fish_available(language):
            print("Fish Audio needs a configured voice ID and FISH_AUDIO_API_KEY in server/.env.", file=sys.stderr)
            return 2
        voice = "configured Fish Audio voice"
        local_only = False
        require_fish = True

    print(f"Testing {language} with {voice} on this Mac ({args.provider}).")
    try:
        pcm = b"".join(
            mouth.stream(
                args.text or SAMPLES[language],
                language=language,
                local_only=local_only,
                require_fish=require_fish,
            )
        )
        if not pcm:
            raise RuntimeError("speech synthesis returned no audio")
        mouth.play(pcm)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Voice test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
