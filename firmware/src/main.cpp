// desk-robot firmware: an expressive face, a turning head, a speaker, a
// microphone, and a camera. Driven over USB serial (115200 baud,
// type `help`) and, when include/secrets.h exists, over WiFi by the brain.

#include <Arduino.h>
#include <U8g2lib.h>
#include <WiFi.h>
#include <Wire.h>

#include "camera.h"
#include "config.h"
#include "face.h"
#include "home_screen.h"
#include "link.h"
#include "mic.h"
#include "servo_neck.h"
#include "speaker.h"

#if __has_include("secrets.h")
#include "secrets.h"
#define HAVE_BRAIN 1
#else
#define HAVE_BRAIN 0
#endif

// 1.3" SH1106 128x64 OLED over hardware I2C (SDA=D4/GPIO5, SCL=D5/GPIO6).
// OLED_FLIP (config.h) picks R2 = rotated 180 degrees for an upside-down mount.
#if OLED_SSD1309_242
U8G2_SSD1309_128X64_NONAME0_F_HW_I2C u8g2(OLED_FLIP ? U8G2_R2 : U8G2_R0, U8X8_PIN_NONE);
#else
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(OLED_FLIP ? U8G2_R2 : U8G2_R0, U8X8_PIN_NONE);
#endif

Face face(u8g2);
HomeScreen home(u8g2);

// What the OLED shows. Asleep = the home screen (clock, date, weather); awake = the face. Going to sleep shows the
// sleep face for SLEEP_FACE_MS first. Power-up starts on the home screen; the brain wakes him ("hey Rocky").
enum class Screen : uint8_t { Home, Face, Sleeping };
Screen screen = Screen::Home;
uint32_t sleepFaceUntil = 0;
constexpr uint32_t SLEEP_FACE_MS = 5000;
ServoNeck panNeck;
ServoNeck tiltNeck;
Link brainLink;
Speaker speaker;
Mic mic;
Camera camera;
uint32_t nextTempMs = 0;
volatile bool speakDonePending = false;  // set by the speaker task, sent from loop()
// Talking mouth while the voice plays on the computer instead of our speaker: the brain sends `mouth <level>`
// (the voice's loudness) ~25 times a second, and -1 when it's done. Stale after MOUTH_TIMEOUT_MS.
float brainMouthLevel = -1.0f;
uint32_t brainMouthMs = 0;
constexpr uint32_t MOUTH_TIMEOUT_MS = 300;

uint32_t lastFrameMs = 0;
uint32_t nextStateMs = 0;
bool demoMode = false; // `demo on`: cycles emotions on its own (to show the faces off without the brain)
bool brainConnected = false;
bool glanceWanted = true;  // the brain's `glance on|off` (off while it holds a pose or tracks a face)
bool assemblyMode = false; // servos held at centre for fitting gears and horns (BOOT button / `assembly`)

// Idle glances only while Rocky is awake and his brain is connected. Asleep,
// or with no server running, the head stays still.
void applyGlances() {
  bool on = !assemblyMode && brainConnected && !face.asleep() && glanceWanted;
  panNeck.setIdleGlances(on);
  tiltNeck.setIdleGlances(on);
}
uint32_t nextDemoEmotionMs = 0;
uint8_t demoEmotionIdx = 0;

void setAssemblyMode(bool on) {
  assemblyMode = on;
  if (on) {
    panNeck.setTarget(0);
    tiltNeck.setTarget(0);
  }
  applyGlances();
  Serial.println(on ? F("assembly mode: both servos centred and held. Fit the pan gear and the tilt horn now.")
                    : F("assembly mode off"));
}

// What the OLED shows in assembly mode instead of the face.
void drawAssemblyScreen() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(34, 12, "ASSEMBLY");
  u8g2.drawStr(10, 26, "servos centred");
  u8g2.drawStr(10, 38, "+ held. Fit gears");
  u8g2.drawStr(10, 50, "BOOT again = exit");
  u8g2.drawFrame(0, 0, 128, 64);
  u8g2.sendBuffer();
}

void printHelp() {
  Serial.println(F("desk-robot commands:"));
  Serial.println(F("  emo <name>   neutral|happy|sad|angry|surprised|sleepy|thinking"));
  Serial.println(F("  pan <deg>    turn head, -110 (left)..110 (right), 0 = center"));
  Serial.println(F("  tilt <deg>   nod head, -85 (down)..85 (up), 0 = level"));
  Serial.println(F("  center       head to center on both axes"));
  Serial.println(F("  assembly on|off  hold both servos at centre for fitting gears/horns (or BOOT within 5 s of power-up)"));
  Serial.println(F("  motion pan|tilt <speed> <accel>  tune head motion live (deg/s, deg/s^2)"));
  Serial.println(F("  raw pan|tilt <deg>  calibration move that ignores the limits (watch it!)"));
  Serial.println(F("  blink        blink now"));
  Serial.println(F("  sleep on|off eyes shut, breathing, Z's"));
  Serial.println(F("  demo on|off  wake up and cycle through the faces on his own"));
  Serial.println(F("  home         clock / weather settings and status"));
  Serial.println(F("  screen       dump what the OLED shows (hex), for a screenshot"));
  Serial.println(F("  weather      fetch the weather now"));
  Serial.println(F("  settings <json>  apply a settings message, as the brain sends it"));
  Serial.println(F("  glance on|off  allow idle head glances (only happen while the brain is connected and he is awake)"));
  Serial.println(F("  volume <0-1> speaker volume"));
  Serial.println(F("  beep         play a test tone through the speaker"));
  Serial.println(F("  oled off|on | oled <cmd> [arg]  screen power, or a raw SSD1309 command in hex (whine hunting)"));
  Serial.println(F("  mic on|off   stream the microphone to the brain"));
  Serial.println(F("  miclevel     print mic level for 3 s (talk to it)"));
  Serial.println(F("  stream on|off [fps]  stream camera JPEGs to the brain"));
  Serial.println(F("  snap         grab one frame and report its size"));
  Serial.println(F("  temp         chip temperature"));
  Serial.println(F("  help         this text"));
}

void handleCommand(String line) {
  line.trim();
  if (line.isEmpty()) return;

  int space = line.indexOf(' ');
  String cmd = (space < 0) ? line : line.substring(0, space);
  String arg = (space < 0) ? String() : line.substring(space + 1);
  cmd.toLowerCase();
  arg.trim();

  if (cmd == "help") {
    printHelp();
  } else if (cmd == "emo") {
    Emotion e;
    if (emotionFromName(arg.c_str(), e)) {
      face.setEmotion(e);
      Serial.printf("emotion: %s\n", emotionName(e));
    } else {
      Serial.println(F("unknown emotion — try: neutral happy sad angry surprised sleepy thinking"));
    }
  } else if (assemblyMode && (cmd == "pan" || cmd == "tilt")) {
    Serial.println(F("assembly mode: head held at centre (`assembly off` to leave)"));
  } else if (cmd == "assembly") {
    setAssemblyMode(arg == "on");
  } else if (cmd == "pan") {
    panNeck.setTarget(arg.toFloat());
    Serial.printf("pan -> %.0f deg\n", panNeck.target());
  } else if (cmd == "tilt") {
    tiltNeck.setTarget(arg.toFloat());
    Serial.printf("tilt -> %.0f deg\n", tiltNeck.target());
  } else if (cmd == "raw") {
    // raw pan|tilt <deg>: calibration, ignores the limits. Watch the mechanism!
    int sp = arg.indexOf(' ');
    String axis = sp < 0 ? arg : arg.substring(0, sp);
    float deg = sp < 0 ? 0 : arg.substring(sp + 1).toFloat();
    if (axis == "tilt") tiltNeck.setRaw(deg);
    else if (axis == "pan") panNeck.setRaw(deg);
    else { Serial.println(F("usage: raw pan|tilt <deg>")); return; }
    Serial.printf("raw %s -> %.0f deg (limits ignored)\n", axis.c_str(), deg);
  } else if (cmd == "center") {
    panNeck.setTarget(0);
    tiltNeck.setTarget(0);
    Serial.println(F("head -> center"));
  } else if (cmd == "blink") {
    face.blink();
  } else if (cmd == "sleep") {
    bool on = arg == "on";
    face.setAsleep(on);
    if (on) {                   // head home (straight ahead, level) to sleep; the face shows it, then the clock
      panNeck.setTarget(0);
      tiltNeck.setTarget(0);
      if (screen == Screen::Face) {
        screen = Screen::Sleeping;
        sleepFaceUntil = millis() + SLEEP_FACE_MS;
      }
    } else {
      screen = Screen::Face;
      home.restoreDisplay();
    }
    applyGlances();
    Serial.printf("sleep %s\n", face.asleep() ? "on" : "off");
  } else if (cmd == "screen") {
    // what the OLED shows right now, as hex (8 pages x 128 columns, a byte = 8 pixels down), for a screenshot
    uint8_t* buf = u8g2.getBufferPtr();
    Serial.print(F("screen:"));
    for (int i = 0; i < 1024; ++i) Serial.printf("%02x", buf[i]);
    Serial.println();
  } else if (cmd == "home") {
    home.printStatus();
  } else if (cmd == "weather") {
    home.refreshWeather();
    Serial.println(F("weather: fetching (see `home` in a few seconds)"));
  } else if (cmd == "settings") {
    if (home.applyJson(arg.c_str())) {
      if (screen != Screen::Home) home.restoreDisplay();   // brightness for the face
      Serial.println(F("settings: applied and saved"));
    } else {
      Serial.println(F("settings: not valid JSON"));
    }
  } else if (cmd == "oled") {
    // oled off|on, or oled <cmd> [arg] in hex: a raw SSD1309 command for hunting the module's coil whine, e.g.
    // `oled d5 f0` (display clock: osc freq high nibble, divide low), `oled 81 40` (contrast), `oled d9 22`
    // (pre-charge). Lasts until the next reboot.
    if (arg == "off" || arg == "on") {
      u8g2.setPowerSave(arg == "off");
      Serial.printf("oled %s\n", arg.c_str());
    } else {
      int sp = arg.indexOf(' ');
      long c = strtol((sp < 0 ? arg : arg.substring(0, sp)).c_str(), nullptr, 16);
      u8x8_t* u = u8g2.getU8x8();
      u8x8_cad_StartTransfer(u);
      u8x8_cad_SendCmd(u, static_cast<uint8_t>(c));
      if (sp > 0) u8x8_cad_SendArg(u, static_cast<uint8_t>(strtol(arg.substring(sp + 1).c_str(), nullptr, 16)));
      u8x8_cad_EndTransfer(u);
      Serial.printf("oled cmd 0x%02lX%s\n", c, sp > 0 ? (" " + arg.substring(sp + 1)).c_str() : "");
    }
  } else if (cmd == "speak_begin") {
    speaker.beginSpeech(static_cast<size_t>(arg.toInt()));
  } else if (cmd == "speak_end") {
    speaker.endSpeech();
  } else if (cmd == "mouth") {
    brainMouthLevel = arg.toFloat();   // no print: it comes 25 times a second
    brainMouthMs = millis();
  } else if (cmd == "volume") {
    speaker.setVolume(arg.toFloat());
    Serial.printf("volume -> %.2f\n", arg.toFloat());
  } else if (cmd == "beep") {
    // 0.4 s of 440 Hz so the amp can be checked without the brain.
    static int16_t tone[16000 * 4 / 10];
    for (size_t i = 0; i < sizeof(tone) / sizeof(tone[0]); ++i) {
      tone[i] = static_cast<int16_t>(8000 * sinf(2 * PI * 440 * i / 16000.0f));
    }
    speaker.beginSpeech();
    speaker.feed(reinterpret_cast<uint8_t*>(tone), sizeof(tone));
    speaker.endSpeech();
    Serial.println(F("beep"));
  } else if (cmd == "mic") {
    mic.setStreaming(arg == "on");
    Serial.printf("mic %s\n", mic.streaming() ? "on" : "off");
  } else if (cmd == "miclevel") {
    for (int i = 0; i < 12; ++i) {
      delay(250);
      int bars = static_cast<int>(mic.level() * 200);
      Serial.printf("  level %.3f %.*s\n", mic.level(), min(bars, 40), "########################################");
    }
  } else if (cmd == "stream") {
    int sp = arg.indexOf(' ');
    String onoff = sp < 0 ? arg : arg.substring(0, sp);
    float fps = sp < 0 ? 10.0f : arg.substring(sp + 1).toFloat();
    camera.setStreaming(onoff == "on", fps);
    Serial.printf("stream %s @ %.1f fps\n", camera.streaming() ? "on" : "off", fps);
  } else if (cmd == "snap") {
    if (!camera.ok()) {
      Serial.println(F("camera not available"));
    } else {
      bool was = camera.streaming();
      camera.setStreaming(true, 10);
      static uint8_t* jpg = static_cast<uint8_t*>(ps_malloc(64 * 1024));
      size_t n = 0;
      for (int i = 0; i < 40 && n == 0 && jpg; ++i) { delay(25); n = camera.takeFrame(jpg, 64 * 1024); }
      camera.setStreaming(was, 10);
      Serial.printf("snap: %u bytes (%s)\n", n, n ? "ok" : "no frame");
    }
  } else if (cmd == "motion") {
    // motion pan|tilt <maxSpeed> <accel>: live tuning (until reboot); no args = show
    int sp1 = arg.indexOf(' ');
    String axis = sp1 < 0 ? arg : arg.substring(0, sp1);
    ServoNeck* n = axis == "pan" ? &panNeck : axis == "tilt" ? &tiltNeck : nullptr;
    if (n && sp1 > 0) {
      String rest = arg.substring(sp1 + 1);
      int sp2 = rest.indexOf(' ');
      float v = rest.toFloat();
      float a = sp2 > 0 ? rest.substring(sp2 + 1).toFloat() : n->accel();
      if (v > 0 && a > 0) n->setMotion(v, a);
    }
    Serial.printf("motion pan %.0f deg/s %.0f deg/s^2 | tilt %.0f deg/s %.0f deg/s^2\n",
                  panNeck.maxSpeed(), panNeck.accel(), tiltNeck.maxSpeed(), tiltNeck.accel());
  } else if (cmd == "temp") {
    Serial.printf("chip %.1f C\n", temperatureRead());
  } else if (cmd == "glance") {
    glanceWanted = (arg == "on");
    applyGlances();
    Serial.printf("glance %s\n", glanceWanted ? "on" : "off");
  } else if (cmd == "demo") {
    demoMode = (arg == "on");
    if (demoMode) handleCommand("sleep off");
    Serial.printf("demo %s\n", demoMode ? "on" : "off");
  } else {
    Serial.println(F("unknown command — type `help`"));
  }
}

void setup() {
  Serial.begin(115200);
  randomSeed(esp_random());

  // ESP32Servo wants its LEDC timers claimed up front.
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  face.begin();
  // Camera first: the servos jump to home when they start, and that current
  // surge on USB power can brown out the camera's probe.
  if (camera.begin()) Serial.println(F("camera: ready"));
  panNeck.begin(PIN_SERVO_PAN, PAN_MIN_DEG, PAN_MAX_DEG, PAN_MAX_SPEED, PAN_ACCEL,
                SERVO_RELAX_MS, PAN_TRIM_DEG, /*glanceRange=*/25.0f,
                PAN_INVERT, PAN_GEAR_RATIO);
  delay(300);  // one servo surge at a time
  tiltNeck.begin(PIN_SERVO_TILT, TILT_MIN_DEG, TILT_MAX_DEG, TILT_MAX_SPEED, TILT_ACCEL,
                 TILT_RELAX_MS, TILT_TRIM_DEG, /*glanceRange=*/10.0f,
                 TILT_INVERT);
  tiltNeck.setRelaxWithin(TILT_RELAX_WITHIN_DEG);

  speaker.begin(PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DIN, SPEAKER_VOLUME,
                []() { speakDonePending = true; });
  mic.begin(PIN_PDM_CLK, PIN_PDM_DATA, MIC_GAIN);

  pinMode(PIN_BOOT_BUTTON, INPUT_PULLUP);

  face.setIdle(true);       // blinks and glances of the eyes whenever the face is up
  face.setAsleep(true);     // starts on the home screen
  home.begin();
  applyGlances();  // off: no brain yet
  nextDemoEmotionMs = millis() + 8000;

  Serial.println(F("\ndesk-robot v0.3.0 — hello!"));
  printHelp();

#if HAVE_BRAIN
  brainLink.onAudio([](const uint8_t* pcm, size_t len) { speaker.feed(pcm, len); });
  brainLink.onSettings([](const char* json) { handleCommand(String("settings ") + json); });
#ifndef ROBOT_TOKEN
#define ROBOT_TOKEN ""
#endif
  brainLink.begin(WIFI_SSID, WIFI_PASS, BRAIN_HOST, BRAIN_PORT, ROBOT_TOKEN,
             [](const String& cmd) { handleCommand(cmd); },
             [](bool connected) {
               // The brain says whether he's awake when it connects. If it goes away while he's awake, he can't hear
               // any more: he goes to sleep (sleep face, then the clock). Idle glances only while connected and awake.
               brainConnected = connected;
               if (!connected && screen == Screen::Face && !demoMode) handleCommand("sleep on");
               applyGlances();
             });
  home.startClock();         // internet time, once WiFi is up
#else
  Serial.println(F("no include/secrets.h — USB-only mode (see secrets.h.example)"));
#endif
}

void loop() {
  // Serial console.
  static String lineBuf;
  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (!lineBuf.isEmpty()) handleCommand(lineBuf);
      lineBuf = "";
    } else if (lineBuf.length() < 512) {     // long enough for a `settings {...}` line
      lineBuf += c;
    }
  }

  uint32_t now = millis();

#if HAVE_BRAIN
  brainLink.update(now);
  if (speakDonePending) {
    speakDonePending = false;
    brainLink.sendJson("{\"type\":\"speak_done\"}");
    Serial.printf("speech: %u underruns, prebuffered %u bytes in %u ms, wifi %d dBm\n",
                  speaker.lastUnderruns(), speaker.lastPrebuffered(),
                  speaker.lastPrebufferMs(), WiFi.RSSI());
  }
  {
    static uint8_t frame[Mic::FRAME_BYTES];
    while (brainLink.connected() && mic.nextFrame(frame)) {
      brainLink.sendBinary(0x01, frame, sizeof(frame));
    }
  }
  if (brainLink.connected() && camera.streaming()) {
    static uint8_t* jpg = static_cast<uint8_t*>(ps_malloc(64 * 1024));
    size_t n = jpg ? camera.takeFrame(jpg, 64 * 1024) : 0;
    if (n > 0) brainLink.sendBinary(0x02, jpg, n);
  }
  if (brainLink.connected() && now >= nextTempMs) {
    nextTempMs = now + 10000;
    brainLink.sendJson(String("{\"type\":\"temp\",\"c\":") + String(temperatureRead(), 1) + "}");
  }
  if (brainLink.connected() && now >= nextStateMs) {
    nextStateMs = now + 5000;
    brainLink.sendState(panNeck.current(), emotionName(face.emotion()));
  }
#endif

  // Demo mode: wander through emotions so a fresh flash shows everything.
  if (demoMode && now >= nextDemoEmotionMs) {
    static const Emotion cycle[] = {
        Emotion::Neutral, Emotion::Happy,     Emotion::Thinking,
        Emotion::Neutral, Emotion::Surprised, Emotion::Sleepy,
    };
    demoEmotionIdx = (demoEmotionIdx + 1) % (sizeof(cycle) / sizeof(cycle[0]));
    face.setEmotion(cycle[demoEmotionIdx]);
    nextDemoEmotionMs = now + random(6000, 12000);
  }

  // BOOT button: enters assembly mode in the first few seconds after power-up, and leaves it any time.
  {
    static bool wasDown = false;
    bool down = digitalRead(PIN_BOOT_BUTTON) == LOW;
    if (down && !wasDown) {
      if (assemblyMode) setAssemblyMode(false);
      else if (now < ASSEMBLY_WINDOW_MS) setAssemblyMode(true);
    }
    wasDown = down;
  }

  if (screen == Screen::Sleeping && static_cast<int32_t>(now - sleepFaceUntil) >= 0) screen = Screen::Home;

  if (assemblyMode) {
    static uint32_t lastAsmDrawMs = 0;
    if (now - lastAsmDrawMs >= 500) { lastAsmDrawMs = now; drawAssemblyScreen(); }
  } else if (screen == Screen::Home) {
    static uint32_t lastHomeMs = 0;
    if (now - lastHomeMs >= 500) { lastHomeMs = now; home.draw(); }
  } else if (now - lastFrameMs >= FRAME_INTERVAL_MS) {
    lastFrameMs = now;
    bool brainTalking = brainMouthLevel >= 0 && millis() - brainMouthMs < MOUTH_TIMEOUT_MS;  // not `now`: may predate it
    if (speaker.speaking()) face.setTalking(true, speaker.level());
    else face.setTalking(brainTalking, brainTalking ? brainMouthLevel : 0.0f);
    face.update(now);
  }

  // Servos on their own steady 50 Hz tick (not the face's 30 fps), so every
  // servo pulse gets a fresh, evenly spaced position.
  static uint32_t lastServoMs = 0;
  if (now - lastServoMs >= SERVO_UPDATE_MS) {
    lastServoMs = now;
    // While one axis swings, keep the other powered so it can't sag. In assembly
    // mode both stay powered at centre so they can't be turned by hand.
    if (panNeck.moving() || assemblyMode) tiltNeck.hold();
    if (tiltNeck.moving() || assemblyMode) panNeck.hold();
    panNeck.update(now);
    tiltNeck.update(now);
  }
}
