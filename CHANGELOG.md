# Changelog

Each version of the robot is a git tag and a GitHub Release. `main` is the
latest work. A video matches the tagged version it was made with.

## v2.0

Hardware:

- New 3D-printed neck and head with MG90S servos: pan geared up 38:30
  (±95°), tilt ±85°, the 2.42" SSD1309 screen, the camera on its side in
  the head, the Dayton CE32A-8 speaker and the amp in the head, power in at
  the base. Replaces the off-the-shelf SG90 bracket.
- Custom head and base boards in place of the perfboards (the board files
  are in the hardware bundle; the connections are in the README).

Software:

- Clock and weather screen while Rocky is asleep, run by the robot itself.
- Dashboard (`server/launcher.py`, http://localhost:8766/): live view,
  settings saved in `server/settings.json`, face packs, server log, and a
  Start / Stop button for the brain.
- Face packs: twelve emotions, four built-in looks, your own made in the
  dashboard.
- Personalities: make new characters in the dashboard from a short
  description (name and wake word, Fish Audio voice, Fish's Drama 3 model
  for sighs, laughs and whispers). Rocky stays the default.
- Seeing: a picture with every question, sharp stills when he looks, and
  a local model that finds faces so he can follow you. A wave wakes him.
- Voice tuned for the CE32A-8 (bass cut at 300 Hz, peaks kept under the
  amp's clean limit).
- Language model: Claude Haiku 5.5 (was Haiku 4.5).
- Assembly mode (BOOT button) centres both servos for fitting the gears.
- Body language: small head moves with his emotion while he talks, and a
  thinking glance; still while asleep, tracking, or taking a picture.

## v1.0 - 2026-09-22

The robot in the videos: XIAO ESP32S3 Sense, OLED face, off-the-shelf
pan/tilt bracket with SG90 servos, camera, PDM mic, MAX98357A amp and
speaker; Python brain on your computer with wake word, speech-to-text,
a language model, and a cloned voice.

- Fixed: the voice was crackly on the robot's speaker since the release
  prep on 2026-09-17. Back to the original (2026-09-06) voice pipeline:
  the original loudness and gain cap, and a limiter that turns loud
  chunks down instead of clipping them. The bass-cut and presence
  sliders are still on the console, off by default.
