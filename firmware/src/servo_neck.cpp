#include "servo_neck.h"

#include <driver/mcpwm.h>

void ServoNeck::begin(uint8_t pin, float minDeg, float maxDeg,
                      float maxSpeedDegPerSec, float accelDegPerSec2, uint32_t relaxAfterMs,
                      float trimDeg, float glanceRangeDeg, bool invert,
                      float gearRatio) {
  pin_ = pin;
  minDeg_ = minDeg;
  maxDeg_ = maxDeg;
  maxSpeed_ = maxSpeedDegPerSec;
  accel_ = accelDegPerSec2;
  velocity_ = 0;
  relaxAfterMs_ = relaxAfterMs;
  trimDeg_ = trimDeg;
  glanceRange_ = glanceRangeDeg;
  invert_ = invert;
  gearRatio_ = gearRatio > 0.0f ? gearRatio : 1.0f;
  currentDeg_ = 0;
  targetDeg_ = 0;
  lastUpdateMs_ = millis();
  nextGlanceMs_ = millis() + 5000;
  attachIfNeeded();
  writeAngle(0);
}

void ServoNeck::attachIfNeeded() {
  if (attached_) return;
  if (mcpwmCode_ < 0) {
    servo_.setPeriodHertz(50);
    // 500-2400us covers the full travel of SG90/MG90S-class servos. On the S3
    // the library returns 100 + unit*10 + timer*2 + operator for an MCPWM output.
    int ch = servo_.attach(pin_, 500, 2400);
    mcpwmCode_ = ch >= 100 ? ch - 100 : 999;
  } else if (mcpwmCode_ < 100) {
    // Route our MCPWM output back to the pin. Don't detach/re-attach through the
    // library: on the S3 it hands out operators by count, so a servo that
    // re-attaches while the other is still running can land on the other's
    // operator, and then both servos get the same pulses.
    int unit = mcpwmCode_ / 10, timer = (mcpwmCode_ % 10) / 2, op = mcpwmCode_ % 2;
    (void)timer;
    mcpwm_io_signals_t sig = unit == 0 ? (op == 0 ? MCPWM0A : MCPWM0B) : (op == 0 ? MCPWM1A : MCPWM1B);
    mcpwm_gpio_init(static_cast<mcpwm_unit_t>(unit), sig, pin_);
  } else {
    servo_.attach(pin_, 500, 2400);  // LEDC output (not expected on the S3)
  }
  attached_ = true;
}

void ServoNeck::writeAngle(float deg) {
  // Head degrees → servo degrees (through the gear ratio) → microseconds;
  // 0 head-deg = servo center. The trim is in servo degrees.
  float servoDeg = (invert_ ? -deg : deg) / gearRatio_ + trimDeg_;
  float t = (servoDeg + 90.0f) / 180.0f;
  int us = 500 + static_cast<int>(t * 1900.0f);
  servo_.writeMicroseconds(constrain(us, 500, 2400));
}

void ServoNeck::setRaw(float deg) {
  deg = constrain(deg, -60.0f, 60.0f);
  attachIfNeeded();
  currentDeg_ = targetDeg_ = deg;
  velocity_ = 0;
  settledSinceMs_ = 0;
  writeAngle(deg);
}

void ServoNeck::hold() {
  bool wasAttached = attached_;
  attachIfNeeded();
  if (!wasAttached) writeAngle(currentDeg_);  // put it back where it belongs
  settledSinceMs_ = 0;                        // and don't relax while held
}

void ServoNeck::setTarget(float deg) {
  targetDeg_ = constrain(deg, minDeg_, maxDeg_);
  settledSinceMs_ = 0;
  attachIfNeeded();
}

void ServoNeck::update(uint32_t nowMs) {
  float dt = (nowMs - lastUpdateMs_) / 1000.0f;
  lastUpdateMs_ = nowMs;
  if (dt <= 0 || dt > 0.5f) dt = 0.02f;

  if (idleGlances_ && nowMs >= nextGlanceMs_) {
    // Small wander, biased back toward center.
    int range = static_cast<int>(glanceRange_);
    float glance = static_cast<float>(random(-range, range + 1));
    if (random(100) < 50) glance = 0;
    setTarget(glance);
    nextGlanceMs_ = nowMs + random(6000, 16000);
  }

  float diff = targetDeg_ - currentDeg_;
  if (fabsf(diff) > 0.05f || fabsf(velocity_) > 0.5f) {
    // The fastest speed from which we can still stop exactly on the target at
    // accel_ is about sqrt(2*a*d) (the h terms correct it for stepping every dt
    // instead of continuously). Aim for that, capped at maxSpeed_, and change the
    // velocity toward it by at most accel_*dt per tick. Speeding up, cruising,
    // slowing down and bending toward a moved target all fall out of this.
    float dist = fabsf(diff);
    float h = accel_ * dt * 0.5f;
    float want = fminf(maxSpeed_, sqrtf(h * h + 2.0f * accel_ * dist) - h) * (diff > 0 ? 1.0f : -1.0f);
    float dv = constrain(want - velocity_, -accel_ * dt, accel_ * dt);
    velocity_ += dv;
    float step = velocity_ * dt;
    if ((diff > 0 && step >= diff) || (diff < 0 && step <= diff) || (dist < 0.05f && fabsf(velocity_) < 3.0f)) {
      currentDeg_ = targetDeg_;   // arrive exactly, no overshoot
      velocity_ = 0;
    } else {
      currentDeg_ += step;
    }
    attachIfNeeded();
    writeAngle(currentDeg_);
    settledSinceMs_ = 0;
  } else if (attached_ && relaxAfterMs_ > 0 && (relaxWithin_ < 0 || fabsf(currentDeg_) <= relaxWithin_)) {
    if (settledSinceMs_ == 0) {
      settledSinceMs_ = nowMs;
    } else if (nowMs - settledSinceMs_ >= relaxAfterMs_) {
      // At rest long enough: stop driving the servo so it doesn't buzz.
      // Take the pin off the PWM and hold it low: no pulses, so the servo goes
      // quiet (the library's detach() leaves MCPWM driving the pin on the S3).
      attached_ = false;
      if (mcpwmCode_ >= 100) servo_.detach();
      pinMode(pin_, OUTPUT);
      digitalWrite(pin_, LOW);
    }
  }
}
