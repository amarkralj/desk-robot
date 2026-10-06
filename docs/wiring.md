# Wiring guide

Read this with the parts in hand. Nothing here is hard, but do the
**power rules** section first — it's the difference between a happy robot
and a rebooting one.

## The XIAO's pins

The XIAO ESP32S3 has 7 pins per side. Labels below match the silkscreen
printed on the board:

```
             USB-C at top
        ┌───────────────────┐
   D0 ──┤ GPIO1      5V     ├── 5V out (from USB)   ← servo + amp power
   D1 ──┤ GPIO2      GND    ├── ground
   D2 ──┤ GPIO3      3V3    ├── 3.3V out            ← OLED power
   D3 ──┤ GPIO4      D10    ├── GPIO9
   D4 ──┤ GPIO5      D9     ├── GPIO8
   D5 ──┤ GPIO6      D8     ├── GPIO7
   D6 ──┤ GPIO43     D7     ├── GPIO44
        └───────────────────┘
```

## Power rules (do these, always)

1. **Everything shares ground.** XIAO GND, OLED GND, servo brown wire, amp
   GND — all to the breadboard's ground rail, and the ground rail to a GND
   pin on the XIAO.
2. **Servo and amp get 5V, never 3V3.** Run the XIAO's `5V` pin to the
   breadboard's red rail; servo red wire and amp Vin connect there. The
   3V3 regulator cannot handle a servo and will brown-out the board.
3. **The big capacitor (470–1000µF) goes across the 5V and GND rails**,
   as close to the servo's power wires as practical. Electrolytic caps are
   polarized: the **striped leg is negative** → GND rail. Backwards = it
   can pop. Check twice.
4. Use a **5V/2A (or better) USB-C supply** — a laptop port works for
   flashing and face-only testing, but use a wall supply once the servo
   and speaker are in play.

## OLED and servos

| From | To |
|---|---|
| OLED VCC | XIAO 3V3 |
| OLED GND | ground rail |
| OLED SCL | XIAO **D5** |
| OLED SDA | XIAO **D4** |
| Pan servo brown (GND) | ground rail |
| Pan servo red (5V) | 5V rail |
| Pan servo orange (signal) | XIAO **D3** |
| Tilt servo brown (GND) | ground rail |
| Tilt servo red (5V) | 5V rail |
| Tilt servo orange (signal) | XIAO **D8** (not D6: D6 is the ESP32's serial TX and the boot text on it jerks the servo at power-up) |
| Capacitor − (striped) | ground rail |
| Capacitor + | 5V rail |

On the Adafruit pan-tilt, the **bottom** servo (rotates the whole assembly)
is pan; the **top** servo (nods the platform) is tilt.

Power it up: the eyes should open with a blink and start looking around.
If the OLED stays black, the usual suspects are swapped SDA/SCL or a loose
jumper. Then check the head's manners:

- If tilt nods the wrong way (`tilt -20` should look **down**), flip
  `TILT_INVERT` in `firmware/include/config.h` and re-flash. Tilt only goes
  from eye level (0) down to -60 on this mount: the platform hits the pan
  servo if it tries to look up.
- If the head isn't level/straight at `center`, adjust `TILT_TRIM_DEG` /
  `PAN_TRIM_DEG` a few degrees at a time.
- If the tilt bracket strains or buzzes at the ends of its travel, pull
  `TILT_MIN_DEG` / `TILT_MAX_DEG` in until it stops.

## Amp and speaker

| From | To |
|---|---|
| Amp Vin | 5V rail |
| Amp GND | ground rail |
| Amp BCLK | XIAO **D0** |
| Amp LRC | XIAO **D1** |
| Amp DIN | XIAO **D2** |
| Amp + / − terminals | speaker (snip the white plug, strip, screw down) |

The amp's `GAIN` and `SD` pins can be left unconnected (defaults: 9dB gain,
enabled). Software volume is `SPEAKER_VOLUME` in `firmware/include/config.h`
(0.7 as tuned); for more, jumper `GAIN` to the ground rail (15dB).

## Head assembly (v1, no 3D printing)

- Only the OLED + XIAO ride on the pan-tilt. Amp, speaker, breadboard, and
  capacitor stay on the desk.
- Bolt or foam-tape the OLED to a small backing plate (stiff plastic card
  works) attached to the pan-tilt's top platform; the OLED has four corner
  holes sized for M2/M2.5 standoffs.
- Mount the XIAO behind the OLED with the camera's ribbon pointed up so the
  lens peeks over the top edge of the face.
- Leave a generous service loop of wire at the neck so the head can turn
  freely, and route wires so they can't snag the servo horn.

## Reserved for later

| Pin | Future job |
|---|---|
| D7 (GPIO44) | spare |
| D8–D10 | spare (used by the Sense's microSD slot if you ever add one) |

Camera and microphone need **no wiring** — they're built into the Sense
board.
