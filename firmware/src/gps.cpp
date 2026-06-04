// gps.cpp — SAM-M10Q driver implementation.
//
// I2C/Qwiic transport, UBX binary protocol. All hardware specifics live here;
// callers see only the interface in gps.h.

#include "gps.h"

#include <Arduino.h>
#include <Wire.h>
#include <SparkFun_u-blox_GNSS_v3.h>

namespace {

// I2C pins for the Qwiic breakout
constexpr uint8_t GPS_SDA = 8;
constexpr uint8_t GPS_SCL = 9;

// Navigation rate. 5 Hz gives ~6 speed readings per stroke at 50 spm,
// enough to see speed pulse shape and anchor IMU-integrated velocity.
constexpr uint8_t NAV_RATE_HZ = 5;

SFE_UBLOX_GNSS dev;

// Most-recent values, exposed through getters in gps.h.
uint8_t  g_fix       = 0;
uint8_t  g_sats      = 0;
double   g_lat       = 0;
double   g_lon       = 0;
double   g_alt       = 0;
double   g_speed     = 0;
double   g_heading   = 0;
bool     g_timeValid = false;
uint64_t g_unix_us   = 0;

}  // namespace

namespace gps {

bool init() {
  Wire.begin(GPS_SDA, GPS_SCL);
  if (!dev.begin(Wire)) {
    return false;
  }

  // UBX binary protocol — faster and more reliable than NMEA parsing.
  // Disable NMEA so we don't waste I2C bandwidth on sentences we ignore.
  bool configOk = true;
  configOk &= dev.setI2COutput(COM_TYPE_UBX);
  configOk &= dev.setNavigationFrequency(NAV_RATE_HZ);

  // Sea dynamic model: a paddle craft is low, slow, and has ~zero vertical
  // motion. This tells the receiver's internal velocity Kalman filter to expect
  // boat-like dynamics instead of the default Portable model (which allows
  // car/running accelerations), reducing ground-speed jitter. The library
  // default layer is RAM+BBR, so this persists via the breakout's coin cell and
  // is also reapplied here on every boot.
  configOk &= dev.setDynamicModel(DYN_MODEL_SEA);

  // Save the I/O port config to battery-backed RAM so it survives a power
  // cycle. (Coin cell on the breakout keeps this alive.)
  configOk &= dev.saveConfigSelective(VAL_CFG_SUBSEC_IOPORT);

  if (!configOk) {
    Serial.println("WARN: GPS responded, but one or more config writes failed");
  }
  return true;
}

bool update() {
  // getPVT() does its own rate-limiting against the module's nav frequency.
  // Returns true only when a fresh solution has been pushed up.
  if (!dev.getPVT()) return false;

  g_fix   = dev.getFixType();
  g_sats  = dev.getSIV();
  g_lat   = dev.getLatitude()    / 1e7;
  g_lon   = dev.getLongitude()    / 1e7;
  g_alt   = dev.getAltitudeMSL() / 1000.0;
  g_speed = dev.getGroundSpeed() / 1000.0;
  g_heading = dev.getHeading() / 100000.0;
  while (g_heading < 0.0) g_heading += 360.0;
  while (g_heading >= 360.0) g_heading -= 360.0;

  // UTC time validity. GPS modules typically get a position fix before they
  // can decode the full time-of-week + week-number needed for absolute time,
  // so we check both date and time validity flags explicitly.
  g_timeValid = dev.getDateValid() && dev.getTimeValid();
  if (g_timeValid) {
    uint32_t micros = 0;
    uint32_t unix_s = dev.getUnixEpoch(micros);
    // Combine seconds + microseconds into Unix µs. uint64_t arithmetic is
    // mandatory: unix_s * 1e6 overflows uint32_t.
    g_unix_us = (uint64_t)unix_s * 1000000ULL + (uint64_t)micros;
  } else {
    g_unix_us = 0;
  }
  return true;
}

uint8_t  fixType()           { return g_fix; }
uint8_t  numSats()           { return g_sats; }
double   latitude()          { return g_lat; }
double   longitude()         { return g_lon; }
double   altitudeMSL()       { return g_alt; }
double   groundSpeed()       { return g_speed; }
double   headingDeg()        { return g_heading; }
bool     hasValidTime()      { return g_timeValid; }
uint64_t unixMicroseconds()  { return g_unix_us; }

}  // namespace gps
