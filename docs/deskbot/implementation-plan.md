# DeskBot offline features: implementation plan

## Purpose and constraints

Plan the next incremental DeskBot work without replacing the existing robot. The product goal is a low-cost, maintainable, stationary office companion with a compact enclosure, animated face, pan/tilt head, USB-C power, local Wi-Fi, microphone and speaker, English/German reactions, local content, optional recognition of explicitly enrolled people, and touch interaction.

This document is a plan, not authorization to start the brain, capture sensor data, call an external service, install dependencies, alter user configuration, flash hardware, or implement application code. Keep the existing LLM path dormant unless separately and explicitly requested. New offline features must be modular, testable without hardware, and off by default.

## Repository baseline inspected

- `README.md`, `CHANGELOG.md`, `docs/protocol.md`, and `docs/wiring.md` describe the V2 build, local dashboard, Python brain, hardware, and WebSocket protocol.
- `server/requirements.txt` pins the current Python stack. The repository targets Python 3.13; the stated environment has already passed its full Python test suite.
- `server/launcher.py` is a standard-library local dashboard process. Its Start control launches `brain.main`; do not use it to validate this plan because that would start the brain.
- `server/brain/` contains the existing settings and configuration, ears/transcription, perception, face tracker, camera/live view, LLM (`thinking.py`), TTS/audio (`mouth.py`), robot orchestration (`main.py`), face packs, characters, and computer-control modules.
- `server/tests/` uses `unittest` and fakes for robot, audio, and perception behavior. The README documents a no-hardware/no-model-download full test command.
- `firmware/src/` contains the existing face, clock/idle screen, camera, microphone, speaker, servo neck, WebSocket link, and serial-command implementation. `firmware/include/config.h` and `firmware/platformio.ini` configure the XIAO ESP32S3 Sense target.
- `.gitignore` excludes build output, secrets, personal settings, and downloaded models. No existing `.github/copilot-instructions.md` was found.
- Initial Git state was clean on branch `deskbot-first-tests`. No branch changes were made.

## Existing architecture and important conflicts

### Existing components to reuse

- Keep the ESP32 as the real-time face, display, servo, audio, camera, and network endpoint. Keep high-level decisions and local content in the Python server.
- Extend `server/brain/settings.py` and the existing local dashboard instead of adding a second settings service. The dashboard is bound to loopback and uses guarded local control routes.
- Reuse the existing `Eyes` camera-frame boundary, face/landmark and YuNet detection where suitable, `Tracker` for head-following, `Face`/face packs for expressions, `Speaker` and the existing audio transport, and `settings.py` validation patterns.
- Keep `docs/protocol.md` authoritative for WebSocket changes and update it together with `server/brain/main.py` and `firmware/src/link.cpp`.

### Requirements the current V2 does not meet yet

- **Local identity backend now integrated, model still unprovisioned:** `tracker.py` continues to perform face tracking, while the separately gated SFace service can resolve one explicitly enrolled identity from the same YuNet detection pass. Recognition defaults off and remains unavailable until checksum-verified model assets are explicitly installed. The dashboard exposes consent/enrollment controls and structured status.
- **No touch sensor:** the firmware has a BOOT button but no touch input or touch protocol event. Select and electrically validate a touch sensor and safe connection before defining GPIO assignments.
- **No verified 100-120 mm enclosure dimensions:** the README describes the V2 printed head, neck, and base, but does not state overall height; CAD is not in the repository. Measure the current design and check screen, servo, camera, and speaker clearances before claiming this size is feasible.
- **No 360-degree pan:** V2 firmware limits pan to -95 to +95 degrees and tilt to -85 to +85 degrees. Do not claim continuous rotation or a full 360-degree turn.
- **English/German speech is not a current feature:** the default transcription model is `base.en`. Existing OS speech fallbacks are platform-dependent and do not guarantee an installed German voice. Confirm German local STT/TTS assets and quality on the target macOS/Python 3.13 setup before committing to them.
- **Existing sensor activation is not privacy opt-in:** the brain has `LISTEN_ON_START = True`; on robot connection, `main.py` requests microphone and camera streaming. Firmware startup initializes the camera and microphone. A future privacy phase must gate new feature use and explicitly resolve this existing startup behavior before describing the product as requiring affirmative, per-session consent.
- **Offline speech must avoid hosted fallthrough:** `mouth.stream()` can use Fish Audio when its key is configured. New offline responses must call a local-only speech path and must never fall through to `thinking.py`, Fish Audio, or another hosted provider.
- Existing requirements already include OpenCV, MediaPipe, faster-whisper, and ONNX Runtime. The OpenCV Zoo SFace model is selected but not provisioned in this checkout; real-camera identity accuracy and the configured threshold remain unvalidated. A separate optional dependency file supplies authenticated encryption and Keychain access. Touch hardware remains absent.

## Proposed architecture

1. **Offline domain package:** the first standalone behavior primitives live in `server/deskbot_local/`, outside the existing `brain/`. Keep them small and independently testable:
   - `__init__.py`: package boundary and public API only.
   - `service.py`: orchestration for explicit offline requests/events, using injected dependencies.
   - `content.py`: validated, versioned local greetings, jokes, and reaction selection.
   - `scheduler.py`: explicit, deterministic-when-seeded random-event evaluation; no camera, microphone, network, or LLM access.
   - `registry.py`: local SQLite person profiles, explicit owner selection, consent-gated eligibility, and deletion; do not store biometric data in this phase.
   - `identity.py`: supplied-frame face detection and consent-gated local enrolled-person matching. Reuse an existing detector where appropriate; do not confuse detection/tracking with identity.
2. **Opt-in integration:** extend `settings.py`, `main.py`, `launcher.py`, and the existing dashboard only after the standalone modules pass tests. A default-off feature flag and explicit session controls must gate the service. The feature must not start a sensor, thread, download, or model merely because the application or a module was imported.
3. **Existing sources, not duplicate device stacks:** pass camera frames/audio into the service through narrow injected interfaces only after explicit user activation. Do not open a second camera or microphone stream. Offline content selection must be callable without either sensor.
4. **Local response output:** keep phrase selection separate from speech synthesis. Offline behavior primitives remain local. The explicitly requested owner greeting uses the existing `mouth.py` pipeline with explicit German language metadata; it sends only the selected fixed phrase to the configured speech path, never an image, embedding, or match result.
5. **Identity model and assets:** choose an embedding model only after checking its license, provenance, size, accuracy/threshold behavior, and Python 3.13/macOS CPU performance. Use the already-pinned ONNX Runtime only if the selected model works with it. Provide an explicit, checksum-verified model setup/update step; never download identity models at application startup.
6. **Firmware and hardware:** retain the current `Link` protocol and commands where possible. Add touch input and any sensor activation controls only after confirming the actual board, sensor, GPIO, wiring, enclosure placement, and noise behavior. Keep firmware changes compile-testable without upload.

## Implemented localhost configuration area

The existing launcher dashboard now has a separate DeskBot tab and local routes for its preferences, explicitly configured owner, local people, editable bilingual phrase overrides, and backup export. DeskBot preferences are stored separately from legacy `server/settings.json`; profiles remain in the per-user SQLite registry and phrase edits remain in per-user application data rather than changing tracked examples. This interface only stores configuration: it does not start the offline scheduler, brain/LLM, camera, microphone, recognition, audio, or hardware. See [dashboard-configuration.md](./dashboard-configuration.md) for the settings schema, storage, routes, privacy boundaries, and test commands.

## Planned files by phase

| Area | Candidate files | Purpose |
|---|---|---|
| Project guidance | `.github/copilot-instructions.md` | Always-on project safety and engineering constraints |
| Plan | `docs/deskbot/implementation-plan.md` | Phases, architecture, privacy, and validation |
| Offline core | `server/deskbot_local/__init__.py`, `models.py`, `content.py`, `behaviors.py`, `scheduler.py` | Local response descriptions and explicitly evaluated spontaneous events outside the existing brain |
| Person registry | `server/deskbot_local/registry.py` | Per-user SQLite profiles, consent-gated enrollment eligibility, explicit owner state, and deletion; no biometric templates |
| Local content | `server/deskbot_local/content/README.md`, `en.json`, `de.json` | Documented schema and versioned English/German content |
| Settings/integration | `server/brain/settings.py`, `server/brain/main.py`, `server/launcher.py`, `server/brain/dashboard.html` | Default-off configuration and explicit controls using existing surfaces |
| Local speech | `server/deskbot_local/tts.py` (or an extracted local-only adapter) | Local OS speech only; language capability checked on the target machine |
| Identity | `server/deskbot_local/identity.py`; `docs/deskbot/face-recognition.md`; later explicit model provisioning | Supplied-frame detection, consent-gated local matching and template deletion; no automatic weight download |
| Hardware action boundary | `server/deskbot_local/actions.py`, `docs/deskbot/hardware-actions.md` | Injected action interface, default dry-run recording, documented command mapping, and pan/tilt range validation |
| Offline CLI simulator | `server/deskbot_local/intent.py`, `server/deskbot_local/demo.py`, `docs/deskbot/demo.md` | Explicit command-driven demo with ephemeral registry state, optional random seed, and manually ticked scheduler |
| Personal data protection | `.gitignore`; a narrowly scoped local data directory such as `server/data/people/` | Keep face templates and enrollment metadata out of Git; never place them in `server/settings.json` |
| Python tests | `server/tests/test_deskbot_local.py`, `test_deskbot_scheduler.py`; later `test_offline_privacy.py`, `test_offline_identity.py` | Unit and privacy regressions using fakes and generated fixtures |
| Hardware/protocol, only after validation | `firmware/include/config.h`, `firmware/src/main.cpp`, new `firmware/src/touch.h/.cpp`, `firmware/src/link.cpp`, `firmware/src/link.h`, `docs/protocol.md`, `docs/wiring.md` | Validated touch input and explicit sensor lifecycle/protocol changes |

The offline behavior primitives and content files are implemented in `server/deskbot_local/`; the remaining entries are candidates for later phases, not permission to change unrelated application, firmware, or user-configuration files. Preserve `server/.env`, `firmware/include/secrets.h`, `server/settings.json`, `firmware/.pio/`, generated binaries, and other user configuration.

## Dependency policy

- First implementation should use the current standard library and already-pinned dependencies wherever technically sound. Do not add a package just to organize code.
- Do not change pinned versions or install packages without explaining the need and demonstrating compatibility on Python 3.13/macOS. Verify import, CPU inference, and the focused test suite before recommending any model-runtime change.
- Keep runtime assets local and versioned by explicit metadata/checksum. Provision assets through a user-triggered setup/update action; startup and unit tests must not make network requests.
- No API key is required for content, events, recognition, local transcription, or local speech. Offline tests should pass with all AI service keys absent.

## Privacy and recognition safeguards

- Make offline functionality and every sensor-dependent capability disabled on a fresh install. No module import, launcher startup, or default brain startup may activate the camera or microphone on behalf of the new features.
- Before integration, document and test the existing automatic mic/camera behavior. The product privacy goal requires explicit per-session user activation; decide and test the migration of the current wake-word/camera behavior rather than implying the current defaults already satisfy it.
- Give separate, clear controls for microphone listening, camera use, and identity enrollment/recognition. Require an intentional enrollment action and an informed participant. Do not enroll from ordinary tracking or automatically infer identity.
- Perform detection and matching locally. Do not send identity templates, images, names, or recognition results to an AI/API provider. Do not save source frames or audio by default. Provide explicit delete-all and per-person deletion behavior.
- Return “unknown” when no enrolled match passes a validated threshold; do not guess. Keep thresholds and comparisons testable. Do not surface identity-sensitive information in ordinary logs.
- Use fake image/audio providers in tests. Assert that default construction/startup does not open devices, trigger model downloads, call `urllib`/hosted endpoints, or instantiate the LLM/TTS hosted clients.
- Explain current network behavior accurately: the existing robot protocol is plain WebSocket on the LAN, and the existing LLM application can send prompts/images to its provider. Offline features must not use either external AI path.

## Implementation phases and validation

Run from the stated directory. These commands are compile/test-only; none starts the brain, connects hardware, downloads models, or uploads firmware.

### Phase 0 - Baseline and design gates

- Record baseline Python and firmware results; inspect the actual V2 CAD/hardware bundle and measure overall size.
- Select touch hardware and determine safe GPIO/physical placement. Confirm English/German local voice options and choose identity model candidates by license and offline suitability.
- Resolve the user-visible migration for the existing mic/camera startup behavior before claiming consent is explicit.
- No application code changes in this phase.

Commands:

```bash
(cd server && .venv/bin/python -m unittest tests/test_*.py)
(cd firmware && pio run -e xiao_esp32s3)
```

The repository owner reports that both suites already passed/built in the current environment. Do not rerun the brain or upload firmware.

### Phase 1 - Offline domain core

- Add the isolated `server/deskbot_local/` response primitives and versioned content data outside the existing `brain/`.
- Use typed response descriptions and an injected selector; do not call hardware, the hosted AI path, or integrate with `main.py`.
- Validate the phrase schema, language selection, deterministic choice injection, and an explicit non-spoken result when content is unavailable.
- Keep the feature disconnected from `main.py`, sensors, OS audio, network, and the LLM.

Commands:

```bash
(cd server && ./.venv/bin/python -m unittest discover -s tests -v)
```

### Phase 2 - Default-off, consent-based application integration

- Add a default-off setting and existing-dashboard controls for enabling the offline service.
- Route explicitly requested offline interactions to the local service before any `RobotBrain`/LLM path. Leave hosted features unchanged when the offline mode is off.
- Gate mic and camera use behind explicit per-session activation. Ensure firmware does not initialize/acquire either sensor for this feature before permission; synchronize any change to `docs/protocol.md`.
- Add a strictly local TTS adapter or text-only fallback. Test English and German voice availability rather than assuming it.

Commands:

```bash
(cd server && .venv/bin/python -m unittest discover -s tests -p 'test_offline_*.py' -v)
(cd server && .venv/bin/python -m unittest tests/test_settings.py tests/test_mic_choice.py)
(cd server && .venv/bin/python -m unittest tests/test_*.py)
(cd firmware && pio run -e xiao_esp32s3)
```

Acceptance: a fresh/default configuration stays inactive; enabling local content does not instantiate a hosted client; no sensor is initialized until its explicit control is activated; disabling it stops new processing. Tests use fakes and do not launch the app.

### Phase 3 - Explicitly enrolled local identity (backend integrated; model validation pending)

- Keep person profiles in the per-user application data directory (macOS: `~/Library/Application Support/DeskBot`; Windows: `%LOCALAPPDATA%/DeskBot`; Linux: `$XDG_DATA_HOME/deskbot` or `~/.local/share/deskbot`). The independent registry implementation is `server/deskbot_local/registry.py` and uses SQLite; its database is not part of version-controlled content.
- The registry supports profile creation, explicit consent, enrollment state, preferred language/role, personalized greetings, explicit owner configuration, current owner presence, and deletion. Creation is not enrollment. Recognition candidates are returned only for enabled, enrolled, opted-in people. Attendance is not recorded.
- `server/deskbot_local/identity.py` uses authenticated AES-GCM-encrypted SQLite templates with a key stored in macOS Keychain. No raw camera image is persisted. Registry deletion and opt-out remove matching template rows.
- Detection, tracking, and identity are distinct: `server/brain/tracker.py` only follows detected face positions; `server/brain/perception.py` describes landmarks and visible expressions but does not identify a person.
- YuNet and SFace are from OpenCV Zoo at the pinned revision and have MIT and Apache-2.0 model-directory licenses respectively. Their SHA-256 values are verified by the explicit setup command. The current Python 3.13.17/macOS arm64 environment installed the optional encryption dependencies and imports the OpenCV APIs. Actual Keychain reads/writes and SFace inference were not exercised.
- The same existing tracker frame pass feeds identity matching; the dashboard exposes consent-gated enrollment/status. Stable-match debounce, owner-only German greetings, no-repeat history, cooldown, and presence reset are implemented. Recognition, privacy-mode override, and automatic greetings are off by default. See `docs/deskbot/face-recognition.md` for setup, operation, license references, and limitations.
- Remaining validation: provision weights explicitly, validate thresholds and accuracy with consented samples on the actual camera, exercise macOS Keychain authorization, and verify robot-camera and speaker behavior with hardware. This is not authentication and has no liveness protection.
- Keep this feature separately disabled even when the general offline content feature is enabled.

Commands:

```bash
(cd server && .venv/bin/python -m unittest tests.test_deskbot_identity tests.test_recognition_runtime tests.test_tracker_identity_integration tests.test_identity_webcam_test tests.test_face_model_setup tests.test_deskbot_dashboard_routes -v)
(cd server && .venv/bin/python -m unittest discover -s tests -v)
(cd server && .venv/bin/python -m deskbot_local.setup_face_models)  # explicit optional download; not run by tests/startup
```

Acceptance: tests prove known enrolled fixtures can match under a documented threshold, unknown and borderline fixtures remain unknown, deletion removes persisted templates, and no raw capture or external request is made.

### Phase 4 - Touch and enclosure integration

- After physical sensor and CAD validation, implement a touch driver and minimal protocol event, update wiring/protocol docs, and confirm it does not interfere with the display, servos, camera, microphone, serial boot pins, or power.
- Measure actual enclosure height and clearances. Change geometry only if the validated BOM fits; record any tradeoffs. Keep the V2 pan/tilt capability claims within measured and configured limits.
- Do not claim physical touch, pan, tilt, camera identity, or enclosure fit based on compilation alone.

Commands:

```bash
(cd firmware && pio run -e xiao_esp32s3)
(cd server && .venv/bin/python -m unittest tests/test_*.py)
```

After hardware is available, add explicit bench acceptance tests for sensor input, permission-on/off behavior, touch debounce/noise, head travel limits, and enclosure clearances. Do not upload unless separately authorized.

### Phase 5 - Content/update and release hardening

- Add validated import/export or versioned content updates through existing dashboard/project conventions. Apply content atomically and reject malformed or incompatible files.
- Document model/content update, enrollment backup/deletion, and factory reset procedures without exposing secrets or personal templates.
- Run all tests and compile the firmware; review the final protocol and privacy descriptions against actual behavior.

Commands:

```bash
(cd server && .venv/bin/python -m unittest tests/test_*.py)
(cd firmware && pio run -e xiao_esp32s3)
```

## Completion criteria

- Fresh install: offline service, identity, camera, and microphone processing remain inactive until their relevant explicit user action.
- Offline greetings, jokes, and random events are bilingual, locally available, deterministic under test, and do not need keys or hosted services.
- Recognition is limited to explicitly enrolled people, runs locally, safely reports unknown, and supports deletion.
- No unsupported physical capability is advertised. Pan/tilt, touch, enclosure size, and identity claims reflect measured hardware tests rather than face tracking or a successful build.
- Existing Python tests and the `xiao_esp32s3` compile pass. No firmware upload is part of automated validation.
