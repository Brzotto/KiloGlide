// gps.cpp — SAM-M8Q driver implementation.
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

// Navigation rate. 1 Hz is fine for bringup; bump to 5 Hz when we start
// logging real sessions in Wave 2.
constexpr uint8_t NAV_RATE_HZ = 1;

SFE_UBLOX_GNSS dev;

// Most-recent values, exposed through getters in gps.h.
uint8_t g_fix     = 0;
uint8_t g_sats    = 0;
double  g_lat     = 0;
double  g_lon     = 0;
double  g_alt     = 0;
double  g_speed   = 0;

}  // namespace

namespace gps {

bool init() {
  Wire.begin(GPS_SDA, GPS_SCL);
  if (!dev.begin(Wire)) {
    return false;
  }

  // UBX binary protocol — faster and more reliable than NMEA parsing.
  // Disable NMEA so we don't waste I2C bandwidth on sentences we ignore.
  dev.setI2COutput(COM_TYPE_UBX);
  dev.setNavigationFrequency(NAV_RATE_HZ);

  // Save the I/O port config to battery-backed RAM so it survives a power
  // cycle. (Coin cell on the breakout keeps this alive.)
  dev.saveConfigSelective(VAL_CFG_SUBSEC_IOPORT);
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
  return true;
}

uint8_t fixType()     { return g_fix; }
uint8_t numSats()     { return g_sats; }
double  latitude()    { return g_lat; }
double  longitude()   { return g_lon; }
double  altitudeMSL() { return g_alt; }
double  groundSpeed() { return g_speed; }

}  // namespace gps
