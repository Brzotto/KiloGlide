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

static bool gpsAvailable = false;
static bool sdAvailable  = false;

// --- Status reporting (serial) ---
static uint32_t imuSamplesThisSec = 0;
static unsigned long lastStatusPrint = 0;

// --- Logger flush timer ---
static unsigned long lastFlush = 0;
constexpr unsigned long FLUSH_INTERVAL_MS = 2000;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("KiloGlide boot");

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

  if (act == button::SINGLE) {
    if (logger::isActive()) {
      // Stop the current session.
      logger::stop();
      led::standby();
      Serial.println("Session stopped — standby");
    } else if (sdAvailable) {
      // Start a new session.
      if (logger::start()) {
        led::logging();
        lastFlush = millis();
      } else {
        // File open failed — flash red briefly, return to standby.
        led::error();
        delay(500);
        led::standby();
      }
    } else {
      Serial.println("No SD card — can't start session");
    }
  }

  if (act == button::DOUBLE && logger::isActive()) {
    logger::writeMark();
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
    if (logger::isActive()) {
      logger::writeGps();
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
    } else {
      Serial.print("  STANDBY");
    }

    // GPS summary.
    if (gpsAvailable && gps::fixType() >= 3) {
      Serial.print("  GPS: ");
      Serial.print(gps::numSats());
      Serial.print(" sats");
    }

    Serial.println();

    imuSamplesThisSec = 0;
    lastStatusPrint = millis();
  }

  // Yield briefly so FreeRTOS can run its housekeeping tasks.
  delay(1);
}
