// imu.h — LSM6DSOX 6-DoF IMU driver.
//
// Public interface for the IMU module. Everything else (FIFO config, register
// addresses, SPI setup) is hidden inside imu.cpp. Callers see only the four
// functions below.
//
// Typical use:
//   imu::init();                       // in setup()
//   if (imu::update()) {               // in loop()
//     float ax = imu::ax();            // most recent sample, in m/s²
//     ...
//   }

#pragma once

#include <stdint.h>

namespace imu {

// Initialize the LSM6DSOX over SPI2, configure ranges, ODR, and FIFO with
// watermark interrupt routed to INT1. Returns true on success.
// Call once from setup() before anything else touches the IMU.
bool init();

// Drain the FIFO if the watermark interrupt has fired. Returns true if at
// least one new sample was processed. Call from loop() as often as you can.
// Cheap when nothing is ready — just checks a volatile flag.
bool update();

// Most recent accel (m/s²) and gyro (rad/s) values, updated by update().
// Until the first update() call returns true, these read as zero.
float ax();
float ay();
float az();
float gx();
float gy();
float gz();

}  // namespace imu
