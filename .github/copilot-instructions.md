# DeskBot project instructions

## Architecture

- Preserve the existing split: ESP32-S3 firmware in `firmware/src/`, the Python brain and local dashboard in `server/brain/` and `server/launcher.py`, and the robot/server WebSocket contract in `docs/protocol.md`.
- Read `docs/deskbot/implementation-plan.md` before working on the planned offline features. Extend existing settings, interfaces, tests, and protocol rather than creating parallel systems.
- Keep the independently developed offline behavior and scheduler modules in the separately testable `server/deskbot_local/` package; do not restructure or replace `server/brain/`. They must remain disconnected from the live application until explicitly integrated, disabled by default, and must not run as a side effect of importing modules or starting the existing application.

## Safety, privacy, and external services

- Do not start the brain, activate an LLM, or make calls to OpenAI, OpenRouter, Fish Audio, or other AI services unless the user explicitly asks for that work.
- Do not access camera or microphone hardware automatically. Sensor use must follow the explicit-consent design in the implementation plan; tests must use injected frames/audio or fakes.
- Face tracking and face detection are not identity recognition. Identify only people explicitly enrolled by the user, keep recognition local, fail closed for uncertain matches, and provide a way to delete enrollment data.
- Offline behavior must work without API keys and must not fall through to the LLM or hosted TTS path. Do not add automatic model downloads to startup.
- Never read, print, edit, or overwrite `.env`, `firmware/include/secrets.h`, `server/settings.json`, or other personal/secret configuration. Do not print credentials or commit generated model/person data.
- Do not upload firmware or claim hardware behavior is verified without physical integration tests. Use compile-only PlatformIO commands.

## Dependencies and changes

- Keep the pinned versions in `server/requirements.txt` unchanged unless a dependency is necessary. Explain the need and prove compatibility with Python 3.13 on macOS before changing or installing one.
- Preserve existing user changes; do not reset, discard, overwrite, commit, or push Git changes.
- Make focused changes, update related documentation and tests, and keep the firmware protocol documentation synchronized with both endpoints when changing messages.

## Validation

- Python tests: `(cd server && .venv/bin/python -m unittest tests/test_*.py)`
- Firmware compile only: `(cd firmware && pio run -e xiao_esp32s3)`
- Do not run `pio run -t upload` unless the user explicitly requests an upload and confirms hardware is connected.
