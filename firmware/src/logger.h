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

}  // namespace logger
