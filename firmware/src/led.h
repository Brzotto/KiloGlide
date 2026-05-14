// led.h — On-board RGB LED status indicator.
//
// Header-only — no .cpp file needed. The RGB NeoPixel on the ESP32-S3
// DevKitC lives on GPIO 38. These three states are the entire vocabulary:
//
//   RED    = error (IMU not found, SD mount failed, etc.)
//   BLUE   = standby (booted OK, waiting for button press)
//   GREEN  = logging (session active, writing to SD)

#pragma once

#include <Arduino.h>

namespace led {

constexpr uint8_t PIN = 38;

inline void error()   { neopixelWrite(PIN, 80, 0, 0); }
inline void standby() { neopixelWrite(PIN, 0, 0, 20); }
inline void logging() { neopixelWrite(PIN, 0, 20, 0); }
inline void mark()    { neopixelWrite(PIN, 40, 40, 40); }  // white flash
inline void off()     { neopixelWrite(PIN, 0, 0, 0); }

}  // namespace led
