// main.cpp — KiloGlide firmware entry point.
//
// Orchestration only. Each sensor lives in its own module (imu, gps, ...).
// Setup initializes each module; loop pumps each module's update() and
// prints results. This file should stay short — if logic is creeping in
// here, it probably belongs in a module.

#include <Arduino.h>

#include "imu.h"
#include "gps.h"

#define RGB_LED_PIN 38

static bool gpsAvailable = false;

// IMU verification counters. At 416 Hz we expect ~416 samples/sec. Printing
// every sample would overwhelm serial (~40 KB/s of ASCII), so we count and
// report once per second.
static uint32_t imuSamplesThisSec = 0;
static unsigned long lastImuReport = 0;

static unsigned long lastGpsPrint = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("KiloGlide boot");

  neopixelWrite(RGB_LED_PIN, 0, 20, 0);  // green = booting

  if (!imu::init()) {
    Serial.println("FATAL: LSM6DSOX not found. Check wiring and SPI jumper.");
    neopixelWrite(RGB_LED_PIN, 80, 0, 0);
    while (1) { delay(100); }
  }
  Serial.println("LSM6DSOX OK — 416 Hz, FIFO watermark 208");

  gpsAvailable = gps::init();
  Serial.println(gpsAvailable ? "SAM-M10Q OK" : "SAM-M10Q absent — running without GPS");

  neopixelWrite(RGB_LED_PIN, 0, 0, 20);  // blue = running
  Serial.println("IMU: reporting samples/sec + last sample each second");
  Serial.println("GPS: fix sats lat lon alt(m) speed(m/s)");

  lastImuReport = millis();
}

void loop() {
  // --- IMU: drain whenever the FIFO watermark IRQ has fired ---
  if (imu::update()) {
    // Walk the sample array. For now we just count; the logger (next PR)
    // will write each sample to SD here.
    imuSamplesThisSec += imu::count();
  }

  // Once per second: report sample rate and print the last sample as a
  // sanity check. Expect ~416 samples/sec if the ODR and FIFO are correct.
  if (millis() - lastImuReport >= 1000) {
    Serial.print("IMU:\t");
    Serial.print(imuSamplesThisSec);
    Serial.print(" samp/s");

    // Print the last sample from the most recent batch (if any) so we can
    // eyeball that accel/gyro values look physically reasonable.
    if (imu::count() > 0) {
      const imu::Sample& s = imu::samples()[imu::count() - 1];
      Serial.print("\t last: ");
      Serial.print(s.accelX(), 2); Serial.print(' ');
      Serial.print(s.accelY(), 2); Serial.print(' ');
      Serial.print(s.accelZ(), 2); Serial.print("  g:");
      Serial.print(s.gyroX(), 3);  Serial.print(' ');
      Serial.print(s.gyroY(), 3);  Serial.print(' ');
      Serial.print(s.gyroZ(), 3);
    }
    Serial.println();

    imuSamplesThisSec = 0;
    lastImuReport = millis();
  }

  // --- GPS: poll at the module's nav rate, non-blocking ---
  if (gpsAvailable && gps::update()) {
    if (millis() - lastGpsPrint >= 1000) {
      lastGpsPrint = millis();
      Serial.print("GPS:\t");
      Serial.print(gps::fixType());          Serial.print('\t');
      Serial.print(gps::numSats());          Serial.print('\t');
      Serial.print(gps::latitude(),     7);  Serial.print('\t');
      Serial.print(gps::longitude(),    7);  Serial.print('\t');
      Serial.print(gps::altitudeMSL(),  1);  Serial.print('\t');
      Serial.println(gps::groundSpeed(), 2);
    }
  }

  // Yield briefly so FreeRTOS can run its housekeeping tasks.
  delay(1);
}
