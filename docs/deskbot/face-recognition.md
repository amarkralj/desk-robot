# Local face identity recognition

## Detection, tracking, and identity

- **Detection** finds face-shaped regions and five alignment landmarks in one
  caller-supplied frame. Shared YuNet detection is implemented by
  `server/brain/face_detector.py`.
- **Tracking** follows a face's position from the existing `Eyes` frame stream
  and steers the head. `server/brain/tracker.py` does not determine a name.
- **Identity recognition** locally compares an aligned face embedding against
  templates made during explicit enrollment. It is separate from detection and
  tracking and never treats a track as an identity.

The SFace adapter uses the same `YuNetFaceDetector` instance as the tracker:
the tracker makes one detection pass per frame, then supplies the region and
landmarks to SFace. No new camera capture, identity-specific tracking loop, or
raw-frame persistence was added.

## Default-off behavior and privacy

Recognition is disabled by default (`privacy_mode: true`,
`recognition_enabled: false`); automatic owner greetings are independently
disabled by default. Importing modules, opening the dashboard, and running
tests do not access a camera, load SFace weights, play audio, or start the
brain. When recognition is explicitly enabled in the local DeskBot settings,
it processes frames that the existing tracker already receives. Saving those
settings while the brain is running applies the preference to that existing
stream; it does not start the brain or acquire a new camera.

Enrollment is never automatic. A profile must be enabled and explicitly
opted-in, and the owner must be explicitly configured. The dashboard's
**Enroll owner from latest robot frame** control requires a confirmation and
uses the tracker's latest single-face detection (no second detection pass).
Alternatively, the explicit Mac webcam command below asks for a typed `YES`.
Exactly one detected face is required. The enrollment frame remains in memory
only; only its embedding is stored.

The template database is under the per-user DeskBot Application Support
directory on macOS:

`~/Library/Application Support/DeskBot/face_templates.sqlite3`

The per-user directory is mode `0700` and the SQLite database is mode `0600`.
Embedding vectors are encrypted with AES-256-GCM using the `cryptography`
library. Each row has a random 96-bit nonce and binds its person ID, model ID,
dimensions, and row ID as authenticated associated data. The random 256-bit
key is stored by the explicitly selected macOS Keychain backend from
`keyring`; it is not kept in SQLite, `.env`, or dashboard settings. Missing
crypto/keychain support, keychain failures, invalid ciphertext, or failed
authentication disable recognition; there is no plaintext fallback.

The existing registry remains the separate source of profile names, role,
consent, and explicit owner configuration. It contains no embeddings or
images. Removing a person through the registry/dashboard also deletes that
person's encrypted template rows. SQLite secure-delete is enabled, but
deletion cannot guarantee removal from filesystem snapshots or backups.

No frame, embedding, or biometric match is sent to an LLM, telemetry service,
or TTS provider. The owner greeting library contains ordinary fixed text; the
existing `mouth.py` receives only that German phrase text. No age, gender,
emotion, attendance, work-hour, or productivity inference is made. This is
not secure authentication and has no liveness or spoof protection.

## Install the optional encryption support

The base requirements remain unchanged. The optional file is pinned to
`cryptography==45.0.7` and `keyring==25.6.0`. Compatibility was verified in
the project's Python 3.13.17 macOS arm64 environment: PyPI publishes a
universal2 `cryptography` wheel usable by this interpreter, and keyring's
macOS documentation supports Keychain on macOS 11+ with Python 3.8.7+
universal2. Installation was tested with:

```sh
cd server
./.venv/bin/python -m pip install -r requirements-identity.txt
```

In this environment the Keyring macOS backend imports and instantiates. Actual
Keychain reads/writes were intentionally not exercised during implementation;
the first explicit enrollment/lookup may prompt macOS to authorize the app.

## Explicit model setup

No model is downloaded at import, app start, dashboard access, or test time.
After choosing to provision local recognition, run this command from
`server/`:

```sh
./.venv/bin/python -m deskbot_local.setup_face_models
```

The command downloads the YuNet and SFace ONNX assets from the official
OpenCV Zoo at pinned Git revision
`ba91a3b91d00d76e86540d4013f944bd6b514e39`, checks each SHA-256 before
installing, and never overwrites a file with a different checksum.

| Asset | OpenCV Zoo license | SHA-256 |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` | MIT | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `face_recognition_sface_2021dec.onnx` | Apache-2.0 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

Both model files are ignored by Git. The licenses are documented in the
respective upstream model directories; preserve their notices if redistributing
the weights. Sources:

- [Pinned OpenCV Zoo SFace model and Apache-2.0 notice](https://github.com/opencv/opencv_zoo/tree/ba91a3b91d00d76e86540d4013f944bd6b514e39/models/face_recognition_sface)
- [Pinned OpenCV Zoo YuNet model and MIT notice](https://github.com/opencv/opencv_zoo/tree/ba91a3b91d00d76e86540d4013f944bd6b514e39/models/face_detection_yunet)
- [OpenCV SFace API tutorial](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html)

If either model is missing, recognition reports unavailable/unknown and does
not download anything. OpenCV SFace inference is local CPU inference.

## Enrollment and Mac webcam smoke test

1. Install the optional dependencies and explicitly set up the models above.
2. Start the localhost dashboard manually from `server/`:

   ```sh
   ./.venv/bin/python launcher.py
   ```

   Open `http://localhost:8766/#people` and select **People**. Opening the
   dashboard or its People section does not start the brain or open a camera.
3. Turn privacy mode off and enable recognition in DeskBot settings. The
   configured threshold defaults to `0.5`, the stable match requirement to
   four consecutive frames, the unknown/presence reset to five frames, and
   the greeting cooldown to 900 seconds. Evaluate these defaults locally.
4. In **Person hinzufügen**, enter the display name, choose **Owner**, check
   the explicit-consent box, and check **Diese Owner-Person ausdrücklich als
   DeskBot-Eigentümer konfigurieren** if this should be the configured owner.
   The owner greeting phrase library addresses that configured owner as
   “Chef”; this does not replace the person's profile display name.
5. Choose **Mac-Webcam**, then explicitly start enrollment. Grant Camera
   permission to Terminal or VS Code if macOS asks. Follow the seven German
   pose prompts: center, slight left, slight right, slightly up, slightly
   down, slight upper-left, slight upper-right, and return to center. Each pose collects three
   good-quality embeddings. A frame is rejected if it has zero or multiple
   faces, a face smaller than 80×80 pixels, poor lighting, or practical blur
   checks fail. Review the profile and confirm saving. Raw images are used in
   memory for inference and the preview only; only the encrypted templates
   and minimum registry metadata are persisted.
6. Select **Erkennung testen** from the People section for a non-destructive
   webcam check. A stable positive result displays the enrolled display name;
   an unmatched or uncertain face remains **Unbekannt**. Testing does not add
   or change templates. Use the explicit cancel button or leave the People
   tab to stop and release the Mac camera. A 15-second dashboard inactivity
   timeout also releases the Mac capture if the page closes unexpectedly.
7. For a coworker, choose **Person**, and obtain that individual's explicit
   opt-in before starting; do not silently enroll coworkers. The UI's checkbox
   is a confirmation and does not substitute for any legal basis or other
   GDPR obligations. Biometric identification is specially protected under
   GDPR Article 9: [official EUR-Lex text](https://eur-lex.europa.eu/legal-content/EN-DE/TXT/?uri=CELEX%3A32016R0679).
8. Delete an identity from **Lokal gespeicherte Personen** with **Identität
   und Vorlagen löschen**. The registry invokes template cleanup and removes
   the configured-owner association if applicable. Filesystem snapshots and
   backups may retain old SQLite pages; SQLite secure-delete is not a promise
   about external backups.
9. To use the robot camera later, connect the robot and manually start the
   server with its existing **Start server** control. Then choose **Roboterkamera**
   in the same wizard. The dashboard reads the current `/frame` endpoint from
   the existing localhost live-camera service; the dashboard never starts the
   brain or robot hardware itself.

The standalone command remains available for explicit local diagnostics and
enrollment:

```sh
./.venv/bin/python -m deskbot_local.identity_webcam_test \
  --enroll-person <person-id> --confirm-consent
```

The command explicitly opens the selected webcam, asks the user to type
`YES`, waits for a single detected face, stores an encrypted embedding,
and displays stabilized identity status. It does not save the camera frame,
play audio, or send anything remotely. To test an already enrolled profile:

```sh
./.venv/bin/python -m deskbot_local.identity_webcam_test --frames 120
```

Press `q` or `Esc` in the preview to exit early. `--no-display` captures
without a preview window; `--camera N` selects another OpenCV camera index.
macOS may require Camera permission for Terminal or VS Code. The feature
settings must be enabled and privacy mode off before this explicit command
will open the webcam.

After enrollment, enable **Personalized greetings** for the owner profile and
separately enable **Automatic German owner greetings**. For a robot camera,
manually start the existing brain and connect the robot; the live status is
exposed as `identity_recognition` from the existing `/status` endpoint. This
integration does not start the brain or hardware itself.

The webcam smoke test prints the selected German greeting as a preview only.
In the live brain integration, a stable transition to the explicitly
configured, opted-in owner selects an entry from the editable German
`owner_greetings` phrase list, avoids its last three IDs, applies the selected
expression, and calls `mouth.py` with explicit `language="de"`. The existing
speech path generates PCM and sends it to the configured output: the robot
speaker when connected and selected, otherwise the Mac fallback. No identity
data is part of that speech request.

## Matching policy and limitations

The existing configurable default is cosine similarity `0.5` with a `0.05`
margin over another eligible person's best match. Scores are similarity
values, not probabilities. OpenCV documents `0.363` as a reference cosine
threshold for its SFace benchmark; it is not calibrated for DeskBot's camera,
lighting, angle, or enrollment process. Validate thresholds with consented,
representative local samples before enabling automatic behavior. Results below
threshold, with an insufficient margin, with multiple faces, or without an
eligible consented template remain unknown.

The matcher currently compares the single face in a frame against all eligible
templates and does not assign identities to multiple people in one frame.
Stable matching and presence reset are in-memory only and do not store
attendance. The model weights are not currently provisioned in this checkout,
so real SFace inference and physical camera fit/accuracy remain unverified.
No physical robot hardware was connected during implementation.

## Tests

From `server/`:

```sh
./.venv/bin/python -m unittest tests.test_dashboard_enrollment \
  tests.test_deskbot_dashboard_routes tests.test_tracker_identity_integration -v
./.venv/bin/python -m unittest tests.test_deskbot_identity tests.test_recognition_runtime \
  tests.test_identity_webcam_test \
  tests.test_face_model_setup tests.test_deskbot_dashboard_routes -v
./.venv/bin/python -m unittest discover -s tests -v
```

All identity, encryption, debounce, content, and dashboard tests use temporary
databases, deterministic providers, synthetic frames, and mocked callbacks.
They do not open a camera or microphone, play audio, download models, start the
brain, or contact an API.
