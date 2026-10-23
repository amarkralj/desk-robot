# Safe local testing on macOS

These commands test DeskBot without starting `brain.main`, contacting an AI
service, connecting to an ESP32, or activating a servo. Camera and microphone
tests below open those devices only when their specific command is run.

## Existing features and boundaries

- `server/brain/tracker.py` detects and tracks faces from the existing robot
  camera stream and can request head motion through the brain. It does not
  recognize names.
- `server/deskbot_local/identity.py` provides a separate consent-gated identity
  API. Its synthetic tests run without a camera. Real SFace identity matching
  needs both local YuNet and SFace model files; the SFace model is not present
  in this checkout and is never downloaded automatically.
- The brain has microphone input through `sounddevice`/PortAudio and local
  speech-to-text through `faster-whisper`. Starting the normal brain is not a
  hardware-free test: it starts its application paths and can invoke the
  configured LLM or hosted voice.
- `server/brain/mouth.py` has a built-in macOS `say` voice fallback and
  Fish Audio support. Configure independent English/German voice IDs and
  fallback voices as described below.
- `server/deskbot_local.demo` and `DryRunRobotAdapter` simulate responses and
  intended actions as terminal text. There is no rendered OLED/display
  simulator and no physical robot adapter in the offline package.
- The full test suite uses mocks for sensor/device paths. It does not require
  camera or microphone permission, enrolled faces, or ESP32 hardware.

## Automated tests

From the repository root:

```bash
cd server
./.venv/bin/python --version
./.venv/bin/python -m unittest discover -s tests -v
```

Run just the new webcam workflow tests:

```bash
cd server
./.venv/bin/python -m unittest tests.test_webcam_test -v
```

Run the offline interaction demo:

```bash
cd server
./.venv/bin/python -m deskbot_local.demo --seed 37
```

Type `help` for commands and `quit` to exit. It uses a dry-run adapter and
does not access sensors or hardware.

## Webcam preview and face detection

From `server/`, explicitly start the camera preview with optional local YuNet
detection:

```bash
./.venv/bin/python -m deskbot_local.webcam_test
```

Press `q` or Escape in the preview window to stop. Select another OpenCV
camera index with `--camera 1`; use `--preview-only` to skip detection. The
existing `server/models/face_detection_yunet_2023mar.onnx` is used if present.
If it is absent, the command reports that it is running preview-only and does
not download a model. For a bounded capture without a GUI:

```bash
./.venv/bin/python -m deskbot_local.webcam_test --no-display --frames 30
```

The test holds frames only in memory. It does not save images, enroll anyone,
recognize identities, or move the head. Grant the terminal or VS Code access
under **System Settings → Privacy & Security → Camera** if macOS asks. If the
camera is busy, close other apps using it and retry.

## Microphone and local speech smoke tests

List available audio devices without recording:

```bash
cd server
./.venv/bin/python -m sounddevice
```

To explicitly test microphone input for three seconds, process the samples in
memory only, and print the peak level without writing audio to disk:

```bash
./.venv/bin/python -c 'import numpy as np, sounddevice as sd; x = sd.rec(48000, samplerate=16000, channels=1, dtype="float32"); sd.wait(); print(f"Peak input level: {np.max(np.abs(x)):.4f}")'
```

Grant microphone access to the terminal or VS Code under **System Settings →
Privacy & Security → Microphone**. A near-zero level can mean the wrong input
device is selected or the microphone is muted.

### DeskBot text-to-speech voice test

Configure voices in the existing `server/.env` (copy from `.env.example` if
needed). Keep the Fish key there; do not put keys in commands or settings:

```dotenv
FISH_AUDIO_API_KEY=your-existing-key
TTS_VOICE_ID_EN=your-english-fish-voice-id
TTS_VOICE_ID_DE=your-german-fish-voice-id
TTS_FALLBACK_VOICE_EN=Samantha
TTS_FALLBACK_VOICE_DE=Anna
```

The language-specific Fish IDs are optional. If one is blank, DeskBot uses
the existing `TTS_VOICE_ID` (or active personality voice) for that language.
The example selects `Samantha` for English and `Anna` for German as feminine
macOS voices; voice availability depends on the macOS installation. Confirm
both names with `say -v '?'` and replace either with an installed voice if
needed. If the variables are omitted in an existing `.env`, English preserves
the legacy `Fred` fallback and German defaults to `Anna`. These variables are
read when the Python process starts.

Choose which language voice normal generated speech uses in the dashboard:
**Settings → Rocky → Speech voice language**. It is an explicit voice
selection, not language detection. The current response generator has no
per-utterance language metadata, and the existing speech recognizer is
configured for English. No automatic guessing is performed. Callers that
already know a response language can pass it explicitly to
`mouth.stream(..., language="en"|"de")`.

Test either local macOS fallback without contacting Fish Audio:

```bash
cd server
./.venv/bin/python -m brain.mouth_test --language en
./.venv/bin/python -m brain.mouth_test --language de
```

For an explicitly requested Fish Audio test using the configured language ID
and key, the same standalone command supports:

```bash
./.venv/bin/python -m brain.mouth_test --language en --provider fish
./.venv/bin/python -m brain.mouth_test --language de --provider fish
```

The Fish option requires internet access and may incur service charges. It
does not start the brain or use an LLM. It fails rather than silently
substituting the Mac voice if the Fish request fails. The default `macos`
provider never checks or calls Fish Audio.

List installed macOS voices directly if needed:

```bash
say -v '?'
```

The voice test prints the selected language/provider and phrase, then plays
through the Mac's current output. It does not start the brain, activate a
robot, or store audio. A Fish-generated voice sample plays on the Mac during
this test; the robot is not involved.

When connected and configured to use its speaker, the existing
`SpokenReply` pipeline generates 16 kHz mono signed 16-bit PCM via `mouth`,
then sends `speak_begin`, binary audio frames (`0x01`), and `speak_end` over
the existing protocol. The firmware plays those frames through the robot's
speaker. No firmware change is needed for voice selection or PCM transport.

## Troubleshooting

- `No module named cv2` or `sounddevice`: confirm the command is run from
  `server/` with the existing `.venv/bin/python`. Dependencies are pinned in
  `server/requirements.txt`; this workflow does not install or upgrade them.
- Webcam cannot open: check camera permission, camera index, and whether
  another app owns the camera. `--preview-only` still tests camera access when
  the YuNet model is missing.
- Preview window does not appear: try `--no-display --frames 30` to test
  capture without GUI support.
- Face detection unavailable: verify the local YuNet ONNX file exists at
  `server/models/face_detection_yunet_2023mar.onnx`; the webcam test does not
  download it.
- Identity always reports unknown: this is expected without explicitly
  opted-in local templates and both approved recognition model files.
- Microphone permission denied or no input: grant permission and check the
  device list from `python -m sounddevice`. The automated suite does not need
  this permission.
- `say` voice unavailable: choose a voice listed by `say -v '?'`; this does
  not require Fish Audio or an API key.
- Fish voice test reports missing configuration: confirm the language-specific
  ID or legacy `TTS_VOICE_ID` and `FISH_AUDIO_API_KEY` are set in `server/.env`.
  Restart the command after editing; do not paste the key into a shell command.

No command in this document flashes firmware. Physical OLED, servo, ESP32
camera/microphone, and speaker behavior cannot be verified without the robot.
