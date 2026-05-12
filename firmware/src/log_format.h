// log_format.h — KiloGlide binary session log format v1.
//
// Canonical record layout. This header is the source of truth for the
// on-device writer; docs/log_format.md is the source of truth for the
// Python parser. Change one, change the other in the same commit.
//
// Design summary:
//   - Little-endian throughout (ESP32, x86, ARM Mac are all LE — no swaps)
//   - Packed structs (no compiler-inserted padding)
//   - u32 ms-since-session-start timestamps (49-day wrap, ample for paddling)
//   - Each record framed with sync bytes + length + CRC8 so corrupted
//     regions don't kill the file — parser can resync at the next 0xAA55
//   - Sensor data stored raw (int16, int32). Python multiplies by the
//     version-defined scale factor to get physical units.

#pragma once

#include <stdint.h>
#include <stddef.h>

// 'KILG' as four little-endian ASCII bytes. First 4 bytes of every log file.
constexpr uint32_t KG_LOG_MAGIC = 0x474C494B;

// Format version. Bump when any struct layout, scale factor, or record-type
// meaning changes. Old parsers reject unfamiliar versions rather than guess.
constexpr uint16_t KG_LOG_VERSION = 1;

// Sync bytes that precede every record. If a record's CRC fails, the parser
// advances byte-by-byte looking for the next 0xAA55 to resume. 0xAA55 has
// alternating bits — much less likely to occur inside payload data than
// e.g. 0xFFFF or 0x0000.
constexpr uint16_t KG_LOG_SYNC = 0xAA55;

// Hardware revision identifier. Lets future parsers distinguish a breadboard
// session from a PCB session if scale factors or pin assignments ever diverge.
constexpr uint16_t KG_HARDWARE_BREADBOARD_V0 = 1;

// Record type codes. New types may be added; old parsers should skip unknown
// types by reading `length` bytes and continuing.
enum KgRecordType : uint8_t {
  KG_REC_IMU     = 1,  // 12-byte IMU sample (accel + gyro raw int16)
  KG_REC_GPS     = 2,  // 24-byte GPS PVT solution
  KG_REC_EVENT   = 3,  // 1-byte event code (session boundaries, marks)
  KG_REC_BATTERY = 4,  // 4-byte battery status
  KG_REC_TIME    = 5,  // 12-byte time anchor: local_ms <-> unix_us
};

// Event codes for KG_REC_EVENT payloads.
enum KgEventCode : uint8_t {
  KG_EVT_SESSION_START = 1,
  KG_EVT_SESSION_END   = 2,
  KG_EVT_USER_MARK     = 3,  // user pressed the "mark this moment" button
  KG_EVT_GPS_FIX_LOST  = 4,
  KG_EVT_GPS_FIX_FOUND = 5,
};

// File header — written once at session start.
// Total size 32 bytes (verified by static_assert below).
struct __attribute__((packed)) KgFileHeader {
  uint32_t magic;            // KG_LOG_MAGIC
  uint16_t version;          // KG_LOG_VERSION
  uint16_t hardware_id;      // KG_HARDWARE_*
  uint32_t session_id;       // Monotonic; matches filename suffix
  uint64_t start_unix_us;    // Unix µs at session start, 0 if not yet known.
                             // A later TIME record provides the anchor if so.
  uint8_t  reserved[12];     // Pad to 32 bytes, reserved for future use
};
static_assert(sizeof(KgFileHeader) == 32, "KgFileHeader must be 32 bytes");

// Record header — precedes every payload.
// Total size 8 bytes.
struct __attribute__((packed)) KgRecordHeader {
  uint16_t sync;       // KG_LOG_SYNC (0xAA55)
  uint8_t  type;       // KgRecordType
  uint8_t  length;     // Payload bytes only (does NOT include this header
                       // or the trailing CRC8 byte)
  uint32_t timestamp;  // Milliseconds since session start
};
static_assert(sizeof(KgRecordHeader) == 8, "KgRecordHeader must be 8 bytes");

// Each record on disk is laid out as:
//   [KgRecordHeader] [payload, `length` bytes] [crc8, 1 byte]
//
// The CRC8 covers [type, length, timestamp, payload] — i.e., everything
// except the sync bytes themselves. Sync is just a marker; we don't want
// CRC failures triggered by legitimate sync values appearing inside payload
// data of a corrupted previous record.

// --- Payload structs ---

// IMU: raw FIFO sample. Scale factors for version 1:
//   accel: int16 * 0.000488f * 9.80665f  -> m/s^2  (±16g range)
//   gyro:  int16 * 0.070f   * pi/180.0f  -> rad/s  (±2000 dps range)
struct __attribute__((packed)) KgImuPayload {
  int16_t ax, ay, az;
  int16_t gx, gy, gz;
};
static_assert(sizeof(KgImuPayload) == 12, "KgImuPayload must be 12 bytes");

// GPS: PVT solution. All integer scales documented inline.
struct __attribute__((packed)) KgGpsPayload {
  int32_t  lat;         // degrees * 1e7
  int32_t  lon;         // degrees * 1e7
  int32_t  alt_mm;      // millimeters MSL
  uint32_t speed_mm_s;  // ground speed, mm/s
  uint16_t heading_cd;  // course over ground, degrees * 100
  uint8_t  fix_type;    // 0=none, 2=2D, 3=3D
  uint8_t  num_sats;
  uint16_t hdop_c;      // HDOP * 100
  uint16_t reserved;    // pad to 24 bytes; write zero
};
static_assert(sizeof(KgGpsPayload) == 24, "KgGpsPayload must be 24 bytes");

// Battery snapshot. Logged every ~30s once we have the bq25185 wired up.
struct __attribute__((packed)) KgBatteryPayload {
  uint16_t voltage_mv;
  uint8_t  percent;     // 0-100
  uint8_t  charging;    // 0 = not charging, 1 = charging
};
static_assert(sizeof(KgBatteryPayload) == 4, "KgBatteryPayload must be 4 bytes");

// Time anchor: maps a local timestamp to absolute Unix time. Written when
// GPS first reports valid time, and periodically thereafter. The Python
// parser uses these to convert local_ms in every other record to absolute
// time, and to detect MCU clock drift over a session.
struct __attribute__((packed)) KgTimePayload {
  uint32_t local_ms;    // Local timestamp this anchor corresponds to
  uint64_t unix_us;     // Unix µs at the same instant
};
static_assert(sizeof(KgTimePayload) == 12, "KgTimePayload must be 12 bytes");

// Event: single u8 code. v1 events carry no extra data, so the record's
// `length` is always 1 for these.
struct __attribute__((packed)) KgEventPayload {
  uint8_t code;         // KgEventCode
};

// CRC8 implementation — CCITT-8, polynomial 0x07, init 0x00, no reflection,
// no final xor. Inline so callers can use it without an extra .cpp file.
inline uint8_t kg_crc8(const uint8_t* data, size_t len) {
  uint8_t crc = 0x00;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int b = 0; b < 8; b++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}
