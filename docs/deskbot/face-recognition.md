# Local face identity recognition

## What the existing system does

- **Detection** locates face-shaped regions in one supplied image frame.
- **Tracking** follows a detected face's position across camera frames and moves
  the head to keep that face in view. `server/brain/tracker.py` does not name or
  recognize a person.
- **Perception** extracts facial landmarks and visible expression/orientation
  features. `server/brain/perception.py` does not resolve a person's identity.
- **Identity recognition** compares a detected face with locally stored,
  voluntarily enrolled templates. It is a separate opt-in API in
  `server/deskbot_local/identity.py`; it is not connected to the camera stream,
  tracker, dashboard, voice responses, or brain.

## Interface and privacy behavior

`FaceIdentityService.detect_faces(frame)` and
`FaceIdentityService.recognize_frame(frame)` accept a frame from their caller;
they never open a camera. `resolve_identity(frame, face)` can resolve a single
face selected by the caller. Frames are processed in memory and are not written
to disk. Multiple faces in a frame are returned as unknown by the convenience
recognition call rather than selecting a person implicitly.

Privacy mode defaults to enabled. While enabled, detection returns no faces and
resolution reports `disabled`; enrollment raises an explicit error. Enabling
recognition is a caller decision and is not wired to application startup.
This module does not upload frames or templates. The existing brain's camera
path is separate and may send camera images to its configured model provider
when that existing feature is used; this work does not change that behavior.

Enrollment requires a separate explicit `enroll(person_id, frame)` call, an
enabled registry profile, and its recorded opt-in. Exactly one face must be
detected. Creating a profile, receiving a camera frame, or detecting a face
never enrolls a person. Registry opt-out deletes associated templates, clears
enrollment/personalized-greeting flags, and profile deletion invokes registered
local template cleanup hooks.

Approved feature vectors are stored locally in
`face_templates.sqlite3` under the per-user DeskBot data directory with
owner-only POSIX file permissions. No image is stored. The template database
is separate from dialogue content and does not store attendance history,
work hours, productivity, emotions, age, gender, or other inferred attributes.
Templates are not encrypted by this module; rely on per-user OS account
protection and full-disk encryption where appropriate. Do not share or back up
the template database as ordinary content.

The default match policy requires similarity of at least `0.5` and a `0.05`
margin over a different person's best match. These are configurable safety
defaults, not validated operating thresholds. Calibrate and validate thresholds
with consented, representative enrollment and evaluation data before enabling
real recognition. Low-score, close/ambiguous, missing, disabled, unenrolled,
or non-consenting matches resolve to unknown. The result is an identity
candidate only; it does not imply that personalized greetings are enabled.

## Provider choice and compatibility evidence

The optional `OpenCVSFaceProvider` uses OpenCV's CPU DNN APIs with local model
paths supplied by its caller:

- YuNet face detector (`face_detection_yunet_2023mar.onnx`), whose OpenCV Zoo
  directory documents an MIT license.
- SFace face recognizer (`face_recognition_sface_2021dec.onnx`), whose OpenCV
  Zoo directory documents Apache License 2.0 for all files in that directory.

The OpenCV Zoo READMEs describe this detector/recognizer pairing and the SFace
model's 5-landmark alignment path. These permissive licenses make the selected
pair suitable to evaluate, subject to preserving their notices and checking
the upstream terms again before redistribution. The project does not bundle or
download either model. The provider fails if paths do not already exist, and
does not activate merely by importing the module.

In the configured project environment, Python is 3.13.17 on macOS 27.0.1
Apple Silicon (`arm64`), with `opencv-contrib-python` 5.0.0.93 installed. A
local runtime probe confirmed `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF`
are present. No package was installed or dependency manifest changed. This
confirms API availability in this environment, not inference speed, accuracy,
or compatibility on every Python/macOS combination.

References:

- [OpenCV Zoo YuNet model and MIT license](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
- [OpenCV Zoo SFace model, API demo, and Apache-2.0 license](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
- [OpenCV SFace API tutorial](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html)

## Tests and remaining limitations

`server/tests/test_deskbot_identity.py` uses synthetic face regions and an
in-memory mock provider. The tests need no camera, real face, model weight,
network access, or API key.

The OpenCV adapter's real inference has not been exercised because no SFace
weights are provisioned. Similarity thresholds and demographic performance
have not been validated. The API accepts an explicit frame but is not
integrated with `Eyes`, `Tracker`, the UI, or voice. There is no enrollment UI,
consent receipt/audit record, encrypted template store, liveness detection, or
multi-face identity assignment. Unknown is the required outcome when any of
these constraints prevent confident matching.
