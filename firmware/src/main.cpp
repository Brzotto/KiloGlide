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
static unsigned long lastImuPrint = 0;
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
  Serial.println("LSM6DSOX OK");

  gpsAvailable = gps::init();
  Serial.println(gpsAvailable ? "SAM-M8Q OK" : "SAM-M8Q absent — running without GPS");

  neopixelWrite(RGB_LED_PIN, 0, 0, 20);  // blue = running
  Serial.println("Columns:");
  Serial.println("  IMU:\tax ay az (m/s^2)  gx gy gz (rad/s)");
  Serial.println("  GPS:\tfix sats lat lon alt(m) speed(m/s)");
}

void loop() {
  // --- IMU: drain whenever the FIFO watermark IRQ has fired ---
  if (imu::update()) {
    // Throttle prints to ~20 Hz so the serial output stays readable. The
    // FIFO itself batches at 104 Hz; the underlying data isn't lost, we
    // just don't print every burst.
    if (millis() - lastImuPrint >= 50) {
      lastImuPrint = millis();
      Serial.print("IMU:\t");
      Serial.print(imu::ax(), 3); Serial.print('\t');
      Serial.print(imu::ay(), 3); Serial.print('\t');
      Serial.print(imu::az(), 3); Serial.print('\t');
      Serial.print(imu::gx(), 4); Serial.print('\t');
      Serial.print(imu::gy(), 4); Serial.print('\t');
      Serial.println(imu::gz(), 4);
    }
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
