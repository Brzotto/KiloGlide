// gps.h — u-blox SAM-M10Q GNSS driver.
//
// Public interface for the GPS module. UBX-only, I2C/Qwiic transport. Polling
// is rate-limited internally (1 Hz for now, 5 Hz in Wave 2) so callers can
// invoke update() as fast as they like without flooding the bus.
//
// Typical use:
//   gps::init();                         // in setup() — non-fatal if absent
//   if (gps::update()) {                 // in loop()
//     if (gps::fixType() >= 3) {
//       double lat = gps::latitude();
//       ...
//     }
//   }

#pragma once

#include <stdint.h>

namespace gps {

// Initialize the SAM-M8Q over I2C. Returns true if the module responded.
// If false, the GPS is just absent — keep running, don't halt.
bool init();

// Poll the module for a fresh PVT solution. Internally rate-limited, so it
// only actually hits the bus at the configured navigation frequency.
// Returns true when a new fix has been received.
bool update();

// Most recent fix info, updated by update(). Until the first successful
// update(), these read as zero.
uint8_t fixType();        // 0=none, 2=2D, 3=3D
uint8_t numSats();
double  latitude();       // degrees
double  longitude();      // degrees
double  altitudeMSL();    // meters
double  groundSpeed();    // m/s

}  // namespace gps
