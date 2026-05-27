// logger.h — Binary session logger to microSD.
//
// Writes IMU and GPS data to SD card in the format defined by log_format.h.
// SD card lives on SPI3 (dedicated bus — SD cards misbehave on shared SPI).
//
// Lifecycle:
//   logger::init()      mount SD card, scan for next session ID
//   logger::start()     open file, write header + SESSION_START event
//   logger::writeImu()  write a batch of IMU samples (called after imu::update)
//   logger::writeGps()  write one GPS record (called after gps::update)
//   logger::flush()     force buffered data to card (call every ~2 sec)
//   logger::stop()      write SESSION_END event, flush, close file
//
// All write functions are no-ops if no session is active. Safe to call
// unconditionally from the main loop.
//
// Typical use:
//   logger::init();                      // in setup()
//   logger::start();                     // on button press
//   logger::writeImu(imu::samples(), imu::count());  // after imu::update()
//   logger::writeGps();                  // after gps::update()
//   logger::flush();                     // periodic
//   logger::stop();                      // on button press

#pragma once

#include "imu.h"

#include <stdint.h>

namespace logger {

// Mount the SD card on SPI3 and scan for the next available session ID.
// Returns true if the card is ready. Non-fatal if false — the device can
// still run sensors, just can't log.
bool init();

// Open a new session file (kg_NNNNNN.bin), write the file header and a
// SESSION_START event. Returns true on success.
bool start();

// Write a batch of IMU samples. Timestamps are interpolated backward from
// "now" using imu::DT so each sample gets its own timestamp.
// No-op if no session is active.
void writeImu(const imu::Sample* samples, uint16_t count);

// Write one GPS record from the current gps:: state.
// No-op if no session is active.
void writeGps();

// Write a user-mark event at the current timestamp.
// No-op if no session is active.
void writeMark();

// Write a TIME record anchoring the current local timestamp (ms since session
// start) to an absolute Unix microsecond time. The first anchor lets the
// Python parser convert every other record's local_ms to absolute UTC; later
// anchors let the parser detect MCU clock drift over a session.
// No-op if no session is active.
void writeTimeAnchor(uint64_t unix_us);

// Write a GPS fix-state event. Pass true when the fix transitions from <3D
// to 3D, false when it drops below 3D. Helps the analysis pipeline ignore
// no-fix portions of GPS records without scanning every record.
// No-op if no session is active.
void writeFixEvent(bool found);

// Force any buffered data to the SD card. Call every 1-2 seconds while
// logging. Skipping this risks losing the tail of a session on power loss.
// No-op if no session is active.
void flush();

// Write a SESSION_END event, flush, and close the file.
// No-op if no session is active.
void stop();

// True if a session file is currently open and recording.
bool isActive();

// Current or most recent session ID. Zero before the first start().
uint32_t sessionId();

// Cumulative SD write diagnostics since boot. Nonzero writeErrors() means at
// least one write or flush did not complete; bytesWritten() is useful for
// sanity-checking expected log growth during bench tests.
uint32_t writeErrors();
uint32_t bytesWritten();

}  // namespace logger
