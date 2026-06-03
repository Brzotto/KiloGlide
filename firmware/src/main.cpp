// main.cpp — KiloGlide firmware entry point.
//
// Orchestration only. Each subsystem lives in its own module:
//   imu      — LSM6DSOX at 416 Hz via FIFO + watermark IRQ
//   gps      — SAM-M10Q at 1 Hz via I2C
//   logger   — binary session writer to SD card
//   button   — session start/stop (single press) and user mark (double press)
//   led      — RGB status: red = error, blue = standby, green = logging
//
// This file should stay short — if logic is creeping in here, it probably
// belongs in a module.

#include <Arduino.h>

#include "imu.h"
#include "gps.h"
#include "logger.h"
#include "button.h"
#include "led.h"
#include "version.h"

static bool gpsAvailable = false;
static bool sdAvailable  = false;

// --- Status reporting (serial) ---
static uint32_t imuSamplesThisSec = 0;
static uint32_t gpsUpdatesThisSec = 0;
static unsigned long lastStatusPrint = 0;

// --- LED mark flash (non-blocking) ---
static unsigned long markFlashStart = 0;
static bool markFlashing = false;
constexpr unsigned long MARK_FLASH_MS = 100;

// --- Logger flush timer ---
static unsigned long lastFlush = 0;
constexpr unsigned long FLUSH_INTERVAL_MS = 2000;

// --- GPS event tracking (per-session) ---
// Reset on every session start. We need to know:
//   - Have we written the initial TIME anchor yet?
//   - What was the previous fix state, so we can detect transitions?
//   - When did we last write a TIME anchor, so we can re-anchor periodically?
static bool          timeAnchored      = false;
static uint8_t       prevFixType       = 0;
static unsigned long lastTimeAnchorMs  = 0;
// Re-anchor every 5 minutes once we have valid time. Lets the parser detect
// MCU clock drift over the course of a long session.
constexpr unsigned long TIME_ANCHOR_INTERVAL_MS = 5UL * 60UL * 1000UL;

void setup() {
  Serial.begin(115200);
  delay(1000);
  // Identify the running build so a stale/failed flash is obvious at boot.
  // __DATE__/__TIME__ are the compile time of this file; do a clean build
  // (pio run -t clean) if you want them to always refresh.
  Serial.print("KiloGlide boot — firmware v");
  Serial.print(KG_FIRMWARE_VERSION);
  Serial.print(" (built " __DATE__ " " __TIME__ ")");
  Serial.println();

  // --- Initialize subsystems ---

  // IMU is critical — can't do anything useful without it.
  if (!imu::init()) {
    Serial.println("FATAL: LSM6DSOX not found. Check wiring and SPI jumper.");
    led::error();
    while (1) { delay(100); }
  }
  Serial.println("LSM6DSOX OK — 416 Hz");

  // GPS is optional — keep running without it.
  gpsAvailable = gps::init();
  Serial.println(gpsAvailable ? "SAM-M10Q OK" : "SAM-M10Q absent — running without GPS");

  // SD/logger is optional — device can run sensors without logging.
  sdAvailable = logger::init();

  // Button — always available.
  button::init();

  // Ready. Blue = standby, waiting for button press to start logging.
  led::standby();
  Serial.println("Standby — press button to start session");

  lastStatusPrint = millis();
}

void loop() {
  // --- Button: check for presses ---
  button::update();
  button::Action act = button::action();

  // Long press (hold 2 s) → toggle session start/stop.
  if (act == button::LONG) {
    if (logger::isActive()) {
      logger::stop();
      led::standby();
      Serial.println("Session stopped — standby");
    } else if (sdAvailable) {
      if (logger::start()) {
        led::logging();
        lastFlush = millis();
        // New session — reset GPS-tracking state so the first valid time
        // and the first 3D fix this session get their own log records.
        timeAnchored = false;
        prevFixType = 0;
        lastTimeAnchorMs = 0;
      } else {
        led::error();
        delay(500);
        led::standby();
      }
    } else {
      Serial.println("No SD card — can't start session");
    }
  }

  // Short press (quick tap) → mark this moment.
  if (act == button::SHORT) {
    if (logger::isActive()) {
      logger::writeMark();
      led::mark();
      markFlashStart = millis();
      markFlashing = true;
      Serial.println("MARK recorded");
    } else {
      Serial.println("MARK ignored — no active session");
    }
  }

  // --- LED: restore green after mark flash ---
  if (markFlashing && (millis() - markFlashStart >= MARK_FLASH_MS)) {
    led::logging();
    markFlashing = false;
  }

  // --- IMU: drain FIFO whenever the watermark IRQ has fired ---
  if (imu::update()) {
    imuSamplesThisSec += imu::count();

    // Write every sample to SD if a session is active.
    if (logger::isActive()) {
      logger::writeImu(imu::samples(), imu::count());
    }
  }

  // --- GPS: poll for new fix ---
  if (gpsAvailable && gps::update()) {
    gpsUpdatesThisSec++;
    if (logger::isActive()) {
      // 1. Always write the raw GPS PVT record.
      logger::writeGps();

      // 2. Emit FIX_FOUND / FIX_LOST events on transitions across the 3D
      //    threshold. Cheap one-byte events that let the parser mark
      //    fix-quality changes without scanning every GPS record.
      uint8_t curFix = gps::fixType();
      bool was3D = prevFixType >= 3;
      bool now3D = curFix >= 3;
      if (now3D && !was3D)  logger::writeFixEvent(true);
      if (!now3D && was3D)  logger::writeFixEvent(false);
      prevFixType = curFix;

      // 3. Write a TIME anchor the first moment we have valid UTC, and
      //    again every TIME_ANCHOR_INTERVAL_MS afterward so the Python
      //    parser can detect MCU clock drift over the session.
      if (gps::hasValidTime()) {
        uint64_t unix_us = gps::unixMicroseconds();
        unsigned long now = millis();
        if (!timeAnchored) {
          logger::writeTimeAnchor(unix_us);
          timeAnchored = true;
          lastTimeAnchorMs = now;
        } else if (now - lastTimeAnchorMs >= TIME_ANCHOR_INTERVAL_MS) {
          logger::writeTimeAnchor(unix_us);
          lastTimeAnchorMs = now;
        }
      }
    }
  }

  // --- Periodic flush: push buffered data to the SD card ---
  if (logger::isActive() && (millis() - lastFlush >= FLUSH_INTERVAL_MS)) {
    logger::flush();
    lastFlush = millis();
  }

  // --- Status print: once per second over serial ---
  if (millis() - lastStatusPrint >= 1000) {
    // IMU rate.
    Serial.print("IMU: ");
    Serial.print(imuSamplesThisSec);
    Serial.print(" samp/s");

    // Session status.
    if (logger::isActive()) {
      Serial.print("  LOG: session ");
      Serial.print(logger::sessionId());
      if (logger::writeErrors() > 0) {
        Serial.print(" wr_err=");
        Serial.print(logger::writeErrors());
      }
    } else {
      Serial.print("  STANDBY");
    }

    if (imu::droppedSamples() > 0 || imu::ignoredFifoEntries() > 0) {
      Serial.print("  IMU_DIAG: drop=");
      Serial.print(imu::droppedSamples());
      Serial.print(" ign=");
      Serial.print(imu::ignoredFifoEntries());
    }

    // GPS summary: show update rate so we can tell if data is actually flowing.
    if (gpsAvailable) {
      Serial.print("  GPS: ");
      Serial.print(gpsUpdatesThisSec);
      Serial.print(" upd/s fix=");
      Serial.print(gps::fixType());
      Serial.print(" sats=");
      Serial.print(gps::numSats());
    }

    Serial.println();

    imuSamplesThisSec = 0;
    gpsUpdatesThisSec = 0;
    lastStatusPrint = millis();
  }

  // Yield briefly so FreeRTOS can run its housekeeping tasks.
  delay(1);
}
