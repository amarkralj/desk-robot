#pragma once

// ─── Pin map (XIAO ESP32S3 Sense) ────────────────────────────────────────────
// Silkscreen label → GPIO number. The camera and PDM mic on the Sense
// expansion board use their own internal pins; its microSD slot shares D8-D10.
//
//   D0  = GPIO1   I2S BCLK  → MAX98357A BCLK      (speaker)
//   D1  = GPIO2   I2S LRC   → MAX98357A LRC       (speaker)
//   D2  = GPIO3   I2S DIN   → MAX98357A DIN       (speaker)
//   D3  = GPIO4   pan servo signal (orange wire)
//   D4  = GPIO5   I2C SDA   → OLED SDA
//   D5  = GPIO6   I2C SCL   → OLED SCL
//   D6  = GPIO43  spare: it's the ESP32's UART0 TX, which prints boot text, and a
//                  servo on it lunges to the end of its travel at every power-up
//   D7  = GPIO44  spare (UART0 RX: avoid for servos too)
//   D8  = GPIO7   tilt servo signal (orange wire). Shared with the Sense board's
//                  microSD slot (SCK): leave the slot empty

constexpr uint8_t PIN_SERVO_PAN = 4;   // D3
constexpr uint8_t PIN_SERVO_TILT = 7;  // D8 (was D6/GPIO43: boot text on it jerked the servo)

constexpr uint8_t PIN_I2S_BCLK = 1; // D0 → MAX98357A BCLK
constexpr uint8_t PIN_I2S_LRC = 2;  // D1 → MAX98357A LRC
constexpr uint8_t PIN_I2S_DIN = 3;  // D2 → MAX98357A DIN

// I2C uses the XIAO's default Wire pins (SDA=GPIO5/D4, SCL=GPIO6/D5).
// Most SH1106 modules answer at address 0x3C; U8g2 finds it automatically.

// ─── Display ─────────────────────────────────────────────────────────────────
// Rotate the face 180 degrees if the OLED is mounted upside down. The V2
// printed head holds it header-up (not flipped); the V1 bracket mount was
// upside down (true).
// Which OLED: 0 = the 1.3" SH1106 (V1 / rev A head), 1 = the 2.42" SSD1309 of head rev C (also set OLED_FLIP
// to true there: that screen is mounted upside down). Same 128x64 pixels, so the face code is unchanged.
#define OLED_SSD1309_242 1             // 2026-09-30: the 2.42" (HiLetgo) is in use
constexpr bool OLED_FLIP = true;        // 2026-09-30: the face showed upside down on the bench with false; re-check
                                        // once it's mounted in the head

// Assembly mode: press the XIAO's BOOT button within ASSEMBLY_WINDOW_MS of
// power-up (not while resetting: holding BOOT during a reset starts the
// bootloader). Both servos go to centre and hold there, so gears and horns
// can be fitted straight; press BOOT again (or type `assembly off`) to leave.
constexpr uint8_t PIN_BOOT_BUTTON = 0;   // GPIO0, the BOOT button
constexpr uint32_t ASSEMBLY_WINDOW_MS = 5000;

// ─── Motion limits ───────────────────────────────────────────────────────────
// V2 printed pan/tilt (docs/cad). Angles are "head degrees": 0/0 = straight
// ahead and level, the pose the neck was assembled in (both servos centred).
// It is also where the head goes when Rocky falls asleep.
//
// Pan is geared UP (2026-09-28 print): 38T gear on the servo drives the 30T gear
// built into the turntable, so the head turns 38/30 = 1.267x the servo. The
// ~180 deg servo gives the head about +-114 deg. The limits are where the servo
// runs out of travel with the trim below: head = (+-90 - PAN_TRIM_DEG) * 1.267,
// kept a few degrees short so the servo never grinds on its end stop.
// (Before: 18T/36T, a 1:2 reduction, only +-45.) Re-mesh one tooth to move home a
// long way: each tooth = 12 head degrees.
constexpr float PAN_MIN_DEG = -110.0f;  // head turn limit, robot's left
constexpr float PAN_MAX_DEG = 110.0f;   // robot's right
constexpr float PAN_GEAR_RATIO = 38.0f / 30.0f;  // head degrees per servo degree
constexpr bool PAN_INVERT = false;      // flip if `pan 30` turns LEFT (an external gear pair reverses
                                        // either way, so same as the 18/36 dome base: false)
constexpr float PAN_MAX_SPEED = 150.0f; // head deg/sec ceiling (servo ~120 deg/sec, as before)
constexpr float PAN_ACCEL = 450.0f;     // head deg/sec^2: how gently it speeds up and slows down
constexpr float PAN_TRIM_DEG = 0.0f;    // SERVO degrees; 1 here moves the head 1.27. Re-find by eye
                                        // for the 38/30 gears (reset 2026-09-29). Keep it small:
                                        // to move home a long way, re-mesh the gears with the
                                        // servo centred instead

// Tilt drives the head plate directly. The printed neck clears +-90, so these
// are chosen limits, not mechanical stops.
// 2026-09-30: the current head / dome clears 94 deg face-down and 99 deg face-up (Fusion sweep), so the servo's own
// +-90 is the limit; 5 deg short of that. (Was +-30 for the older neck.)
constexpr float TILT_MIN_DEG = -85.0f;  // look-down limit
constexpr float TILT_MAX_DEG = 85.0f;   // look-up limit
// The head's weight sits ~40 mm above the tilt axis, so a relaxed (unpowered) tilt servo lets a tipped head sag.
// The tilt servo only goes quiet at rest within this many degrees of level; further out it keeps holding.
constexpr float TILT_RELAX_WITHIN_DEG = 15.0f;
constexpr float TILT_MAX_SPEED = 160.0f; // was 120
constexpr float TILT_ACCEL = 600.0f;
constexpr float TILT_TRIM_DEG = 0.0f;   // tweak so the head sits level at 0
constexpr bool TILT_INVERT = true;      // flip if `tilt 15` looks DOWN instead of up. 2026-09-30: true for the
                                        // V2 neck as assembled (camera check: `tilt 15` looked down with false)
                                        // (was true on the V1 Adafruit bracket)

// First time on new hardware: try small moves (`pan 20`, `tilt 15`) before big
// ones, and check each axis turns the right way.

// Stop driving a servo after it has been at rest this long, so it doesn't buzz
// or burn power. 0 = never (holds, but the tilt servo buzzes holding the plate;
// quiet is preferred, 2026-09-28). An unpowered tilt lets an unbalanced head
// plate sag, so balance the plate (horn on the right spline tooth) instead.
constexpr uint32_t SERVO_RELAX_MS = 1500;
constexpr uint32_t TILT_RELAX_MS = 1500;

// ─── Microphone ──────────────────────────────────────────────────────────────
// The Sense board's PDM mic is hard-wired to these GPIOs (no header pins).
constexpr uint8_t PIN_PDM_CLK = 42;
constexpr uint8_t PIN_PDM_DATA = 41;
// Software gain on the mic samples. The PDM mic is quiet; raise if the brain
// says "too quiet", lower if loud speech clips.
constexpr float MIC_GAIN = 6.0f;

// ─── Camera ──────────────────────────────────────────────────────────────────
// The camera is mounted ribbon-up on the head, which puts the sensor upside
// down: flip + mirror = rotate 180 degrees.
constexpr bool CAMERA_VFLIP = true;
constexpr bool CAMERA_HMIRROR = true;

// ─── Speaker ─────────────────────────────────────────────────────────────────
// 0.0-1.0 software volume for the MAX98357A. For more than 1.0 can give,
// tie the amp's GAIN pin to GND (15 dB instead of the floating 9 dB).
constexpr float SPEAKER_VOLUME = 0.7f;

// ─── Behavior ────────────────────────────────────────────────────────────────
constexpr uint32_t FRAME_INTERVAL_MS = 33; // ~30 FPS face animation
constexpr uint32_t SERVO_UPDATE_MS = 20;   // 50 Hz, the servos' own pulse rate
