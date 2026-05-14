// logger.cpp — Binary session logger implementation.
//
// SD card on SPI3 (dedicated bus). Uses SdFat for reliable high-throughput
// writes. The binary format is defined in log_format.h; this file just
// frames records and pushes them to the card.
//
// Write strategy: each record (21 bytes for IMU, 33 for GPS, 10 for events)
// is built in a small stack buffer and written via file.write(). SdFat
// manages its own 512-byte sector buffer internally, so writes are efficient
// without us adding another layer of buffering. flush() is called every
// ~2 seconds from main.cpp to update the FAT — a crash between flushes
// loses at most 2 seconds of data.

#include "logger.h"

#include <Arduino.h>
#include <SPI.h>
#include <SdFat.h>

#include "log_format.h"
#include "gps.h"

namespace {

// --- SD card hardware (SPI3, dedicated bus) ---

constexpr uint8_t SD_CS   = 5;
constexpr uint8_t SD_SCK  = 6;
constexpr uint8_t SD_MOSI = 7;
constexpr uint8_t SD_MISO = 14;

// HSPI = SPI3 on ESP32-S3. Separate from FSPI (SPI2) used by the IMU.
SPIClass sdSPI(HSPI);

// 20 MHz is safe on breadboard wiring. Bump to 40 on PCB.
SdFat sd;
SdSpiConfig sdConfig(SD_CS, DEDICATED_SPI, SD_SCK_MHZ(20), &sdSPI);

// --- Session state ---

FsFile file;
bool sdReady = false;
bool active  = false;

uint32_t currentSessionId  = 0;
uint32_t sessionStartMs    = 0;   // millis() at session start

// --- Helpers ---

// Timestamp: milliseconds since session start.
uint32_t sessionMs() {
  return millis() - sessionStartMs;
}

// Scan root directory for kg_NNNNNN.bin files, return the highest N + 1.
// If no files exist, returns 1.
uint32_t findNextSessionId() {
  uint32_t maxId = 0;
  FsFile root;
  if (!root.open("/")) return 1;

  FsFile entry;
  while (entry.openNext(&root)) {
    char name[32];
    entry.getName(name, sizeof(name));
    // Match pattern: kg_NNNNNN.bin
    if (strncmp(name, "kg_", 3) == 0 && strstr(name, ".bin") != nullptr) {
      uint32_t id = strtoul(name + 3, nullptr, 10);
      if (id > maxId) maxId = id;
    }
    entry.close();
  }
  root.close();
  return maxId + 1;
}

// Write one complete record to the open file. Builds the framing (sync,
// header, CRC) around the caller-provided payload.
//
// On-disk layout:
//   [sync 2B] [type 1B] [length 1B] [timestamp 4B] [payload] [crc8 1B]
//
void writeRecord(uint8_t type, uint32_t timestamp,
                 const void* payload, uint8_t payloadLen) {
  // Build header.
  KgRecordHeader hdr;
  hdr.sync      = KG_LOG_SYNC;
  hdr.type      = type;
  hdr.length    = payloadLen;
  hdr.timestamp = timestamp;

  // Assemble record into a contiguous buffer. Max record = 8 + 24 + 1 = 33.
  uint8_t buf[40];
  memcpy(buf, &hdr, sizeof(hdr));
  memcpy(buf + sizeof(hdr), payload, payloadLen);

  // CRC covers everything after the sync bytes: type, length, timestamp,
  // and payload. That's (sizeof(hdr) - 2) + payloadLen bytes starting at
  // offset 2.
  uint8_t crc = kg_crc8(buf + 2, sizeof(hdr) - 2 + payloadLen);
  buf[sizeof(hdr) + payloadLen] = crc;

  // One write call for the complete record.
  file.write(buf, sizeof(hdr) + payloadLen + 1);
}

}  // namespace

namespace logger {

bool init() {
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);

  if (!sd.begin(sdConfig)) {
    Serial.println("WARN: SD card not found — logging disabled");
    sdReady = false;
    return false;
  }

  // Print card info for debug.
  uint32_t sizeMB = sd.card()->sectorCount() / 2048;
  Serial.print("SD: ");
  Serial.print(sizeMB);
  Serial.println(" MB");

  currentSessionId = findNextSessionId();
  Serial.print("Next session: ");
  Serial.println(currentSessionId);

  sdReady = true;
  return true;
}

bool start() {
  if (!sdReady || active) return false;

  // Build filename: kg_000001.bin, kg_000002.bin, etc.
  char filename[20];
  snprintf(filename, sizeof(filename), "kg_%06lu.bin",
           (unsigned long)currentSessionId);

  if (!file.open(filename, O_WRONLY | O_CREAT | O_TRUNC)) {
    Serial.print("ERROR: can't open ");
    Serial.println(filename);
    return false;
  }

  // Record the start time before writing anything.
  sessionStartMs = millis();

  // Write the 32-byte file header.
  KgFileHeader hdr = {};
  hdr.magic       = KG_LOG_MAGIC;
  hdr.version     = KG_LOG_VERSION;
  hdr.hardware_id = KG_HARDWARE_BREADBOARD_V0;
  hdr.session_id  = currentSessionId;
  // start_unix_us left as 0 — a TIME record will anchor it once GPS has time.
  file.write((const uint8_t*)&hdr, sizeof(hdr));

  // Write SESSION_START event as the first record.
  KgEventPayload evt = { KG_EVT_SESSION_START };
  writeRecord(KG_REC_EVENT, 0, &evt, sizeof(evt));

  active = true;

  Serial.print("Session ");
  Serial.print(currentSessionId);
  Serial.print(" -> ");
  Serial.println(filename);

  return true;
}

void writeImu(const imu::Sample* samples, uint16_t count) {
  if (!active || count == 0) return;

  // Interpolate timestamps backward from "now". The last sample in the
  // batch was the most recently taken; earlier samples are spaced at
  // imu::DT intervals going back in time.
  //
  // dtMs ~= 2.404 ms at 416 Hz. We compute it once as an integer-friendly
  // value to avoid float accumulation drift.
  uint32_t nowMs = sessionMs();
  float dtMs = 1000.0f / imu::ODR_HZ;

  for (uint16_t i = 0; i < count; i++) {
    // Clamp to 0 if the backward offset exceeds nowMs (happens on the
    // very first batch when the session has just started and nowMs is
    // smaller than count * dtMs).
    uint32_t offset = (uint32_t)((count - 1 - i) * dtMs);
    uint32_t ts = (offset <= nowMs) ? (nowMs - offset) : 0;
    // imu::Sample and KgImuPayload have identical memory layout (both are
    // six packed int16s), so we can pass the Sample directly as payload.
    writeRecord(KG_REC_IMU, ts, &samples[i], sizeof(KgImuPayload));
  }
}

void writeGps() {
  if (!active) return;

  // Convert from gps:: floating-point values to the integer-scaled format
  // defined in log_format.h.
  KgGpsPayload gp = {};
  gp.lat        = (int32_t)(gps::latitude()    * 1e7);
  gp.lon        = (int32_t)(gps::longitude()   * 1e7);
  gp.alt_mm     = (int32_t)(gps::altitudeMSL() * 1000.0);
  gp.speed_mm_s = (uint32_t)(gps::groundSpeed() * 1000.0);
  gp.heading_cd = 0;       // TODO: add heading getter to gps.h
  gp.fix_type   = gps::fixType();
  gp.num_sats   = gps::numSats();
  gp.hdop_c     = 0;       // TODO: add HDOP getter to gps.h
  gp.reserved   = 0;

  writeRecord(KG_REC_GPS, sessionMs(), &gp, sizeof(gp));
}

void writeMark() {
  if (!active) return;

  KgEventPayload evt = { KG_EVT_USER_MARK };
  writeRecord(KG_REC_EVENT, sessionMs(), &evt, sizeof(evt));
  Serial.println("MARK");
}

void flush() {
  if (!active) return;
  file.flush();
}

void stop() {
  if (!active) return;

  // Write SESSION_END as the last record.
  KgEventPayload evt = { KG_EVT_SESSION_END };
  writeRecord(KG_REC_EVENT, sessionMs(), &evt, sizeof(evt));

  file.flush();
  file.close();
  active = false;

  Serial.print("Session ");
  Serial.print(currentSessionId);
  Serial.println(" closed");

  // Advance for the next session.
  currentSessionId++;
}

bool isActive()       { return active; }
uint32_t sessionId()  { return currentSessionId; }

}  // namespace logger
