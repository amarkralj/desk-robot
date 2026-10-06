# Robot ↔ brain WebSocket protocol (v0)

The robot connects to `ws://<mac-ip>:8765`. The first message must be a
`hello` carrying the shared `ROBOT_TOKEN` (server/.env, firmware secrets.h);
the server drops anything else without replying, and allows one robot at a
time. Plain `ws://` on the home LAN — no TLS in v1. Text frames are JSON. Binary
frames start with one type byte: `0x01` = mic audio, `0x02` = camera JPEG.
The rest of the frame is the payload.

## Robot → server

```json
{"type": "hello", "who": "desk-robot", "fw": "0.3.0", "token": "..."}  // must be the first message; token = ROBOT_TOKEN
{"type": "state", "pan": 12.5, "emotion": "neutral"}
{"type": "temp", "c": 52.0}       // chip temperature, sent every ~10 s
{"type": "speak_done"}            // finished playing the last reply
```

Binary `0x01` frames: microphone audio, 16 kHz mono signed 16-bit PCM,
little-endian, 30 ms (480 samples) per frame.

Binary `0x02` frames: one camera JPEG per frame, QVGA (320×240) by
default, sent continuously at `fps` while streaming is on. The server keeps
the latest frame for the live-view page, the face tracker, and the language model.

## Server → robot

```json
{"type": "emotion", "name": "happy"}
{"type": "pan", "deg": -20}
{"type": "tilt", "deg": 15}
{"type": "speak_begin", "bytes": 0}      // binary TTS audio frames follow; bytes = total if known, 0 = streaming (robot starts after 200 ms of audio)
{"type": "speak_end"}             // no more audio; robot replies speak_done when played out
{"type": "volume", "level": 0.4}  // speaker volume 0.0-1.0
{"type": "mouth", "level": 0.08}  // voice playing on the computer: its loudness (RMS, 0-1) ~25x/s moves the mouth; -1 = done
{"type": "asleep", "on": true}    // sleep face for ~5 s, then the clock screen; false = wake up (the face). Asleep = no idle glances.
{"type": "glance", "on": false}   // allow/forbid the firmware's idle head glances; the server sends off on connect and leaves them off
{"type": "mic", "on": true}       // stream the microphone to the server
{"type": "stream", "on": true, "fps": 10}   // start/stop the camera stream, set rate
{"type": "settings", "tz": "EST5EDT,M3.2.0,M11.1.0", "h24": false, "dmy": false, "wday": true,
 "wx": true, "lat": 40.71, "lon": -74.01, "unit": "f", "sun": false, "wxmin": 30,
 "bri": 80, "night": "dim", "n0": "23:00", "n1": "07:00", "nbri": 10}
                                  // the clock screen's settings (from server/settings.json); the robot keeps them in flash
```

`settings` keys: `tz` POSIX time zone rule; `h24` 24-hour clock; `dmy` day
before month; `wday` show the weekday; `wx` show the weather (needs
`lat`/`lon`); `unit` `f` or `c`; `sun` sunrise/sunset instead of high/low;
`wxmin` weather refresh in minutes; `bri` brightness %; `night` `off`,
`dim` or `dark` between `n0` and `n1` (local `HH:MM`); `nbri` night
brightness %. Any subset is accepted; missing keys keep their value. The
robot fetches the time (SNTP) and the weather (Open-Meteo) itself.

On connect the server sends `mic on`, `stream on` at `CAMERA_FPS`, `glance
off`, `settings`, `volume`, and `asleep` (whether Rocky is asleep). The live page
is served by `server/brain/eyes.py` at http://localhost:8767/, and with
settings by the launcher at http://localhost:8766/.

Binary frames: type byte `0x01` then TTS audio for the speaker, same
PCM format as above, ~100 ms per frame. The server streams each reply as
the voice generates it (`bytes: 0`); the robot starts playing after 200 ms
of audio is buffered and keeps a 32 s ring buffer in PSRAM. The server
waits for `speak_done` before it un-mutes the microphone.

Firmware side: `firmware/src/link.cpp` maps each server message onto the
same text commands the USB console uses (`emo`, `pan`, `tilt`), so both
paths behave identically. The robot sends `state` every 5 s.

Keep this file in sync with `firmware/src/link.cpp` and `server/brain/main.py`
whenever a message type is added.
