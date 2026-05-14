// imu.h — LSM6DSOX 6-DoF IMU driver.
//
// Public interface for the IMU module. Everything else (FIFO config, register
// addresses, SPI setup) is hidden inside imu.cpp. Callers see the types and
// functions below.
//
// API design rationale
// --------------------
// The downstream algorithms (see docs/math_primer.md) need array access to
// consecutive samples — not just the latest value:
//
//   Complementary filter:  iterates samples, uses accel + gyro in physical
//                          units each step.
//   Peak detection:        compares sample[i] to a threshold, needs refractory
//                          timing across consecutive samples.
//   Force curve analysis:  indexes a contiguous window of one stroke (~500
//                          samples at 416 Hz / 50 spm) for argmax, impulse
//                          (sum * dt), slope, skew.
//   Discrete integration:  velocity += accel[i] * DT — needs DT constant
//                          and sequential access.
//   Differentiation:       (sample[i] - sample[i-1]) / DT — needs indexed
//                          neighbors.
//
// So update() drains the FIFO into an internal array, and count()/samples()
// let the caller walk that array with plain indexing. The array is valid until
// the next update() call.
//
// The Sample struct stores raw int16 values, matching KgImuPayload in
// log_format.h byte-for-byte. The logger can memcpy samples straight to the
// SD write buffer with no conversion. Convenience methods convert to physical
// units for real-time algorithms that need m/s^2 and rad/s.
//
// Typical use:
//   imu::init();                               // in setup()
//   if (imu::update()) {                       // in loop()
//     for (uint16_t i = 0; i < imu::count(); i++) {
//       const imu::Sample& s = imu::samples()[i];
//       float az = s.accelZ();                 // physical units
//     }
//   }

#pragma once

#include <stdint.h>

namespace imu {

// --- Constants ---------------------------------------------------------------

// Sensitivity from LSM6DSOX datasheet Table 2.
// Exposed here so callers (and the logger) can reference them without
// reaching into imu.cpp.
constexpr float ACCEL_SCALE = 0.000488f * 9.80665f;   // raw LSB -> m/s^2
constexpr float GYRO_SCALE  = 0.070f * 3.14159265f / 180.0f;  // raw LSB -> rad/s

// Output data rate. Algorithms that integrate or differentiate need the time
// step between consecutive samples: DT = 1 / ODR_HZ.
constexpr uint16_t ODR_HZ = 416;
constexpr float DT = 1.0f / ODR_HZ;   // ~2.404 ms between samples

// --- Sample type -------------------------------------------------------------

// One paired accel + gyro measurement, raw int16.
// Memory layout is identical to KgImuPayload in log_format.h — the logger
// can write these directly without conversion or copying field by field.
struct Sample {
  int16_t ax, ay, az;   // accel, raw LSB (±16 g full-scale)
  int16_t gx, gy, gz;   // gyro,  raw LSB (±2000 dps full-scale)

  // Convenience: convert to physical units for real-time processing.
  // Inline so the compiler can optimize away the multiply when not needed.
  float accelX() const { return ax * ACCEL_SCALE; }
  float accelY() const { return ay * ACCEL_SCALE; }
  float accelZ() const { return az * ACCEL_SCALE; }
  float gyroX()  const { return gx * GYRO_SCALE; }
  float gyroY()  const { return gy * GYRO_SCALE; }
  float gyroZ()  const { return gz * GYRO_SCALE; }
};

// --- Functions ---------------------------------------------------------------

// Initialize the LSM6DSOX over SPI2, configure +-16g / +-2000dps / 416 Hz,
// and set up FIFO with watermark interrupt routed to INT1.
// Returns true on success. Call once from setup().
bool init();

// Drain the FIFO if the watermark interrupt has fired. Returns true if at
// least one new paired sample was collected. Call from loop() as often as
// you can — cheap when nothing is ready (just checks a volatile flag).
//
// After update() returns true, call count() and samples() to access the
// batch. The returned array is valid until the NEXT call to update().
bool update();

// Number of paired accel+gyro samples from the most recent update().
// Zero if update() hasn't returned true yet.
uint16_t count();

// Pointer to the first Sample from the most recent update(). Walk with
// plain array indexing:
//   for (uint16_t i = 0; i < imu::count(); i++) {
//     imu::samples()[i].accelZ();   // physical units
//     imu::samples()[i].az;         // raw int16 for logging
//   }
// Valid until the next update() call — don't stash the pointer.
const Sample* samples();

}  // namespace imu
