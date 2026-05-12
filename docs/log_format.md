# KiloGlide binary log format — v1

This document is the source of truth for the Python parser. The firmware writes logs per `firmware/src/log_format.h`. When you change one, change the other in the same commit.

---

## Design goals (and the tradeoffs they imply)

| Goal | Choice |
|---|---|
| Capture raw sensor data faithfully | Store integers in their native form; scale to physical units in post-processing |
| Survive partial corruption | Sync bytes (`0xAA55`) + per-record CRC8 + explicit length field |
| Easy to parse on ESP32 and Python | Packed little-endian structs; identical layout on both sides |
| Don't bottleneck on SD writes | Per-record overhead (9 bytes) is acceptable at our ~3 KB/s rate |
| Be extensible | Versioned header; new record types may be added without breaking parsers (skip unknown by reading `length` bytes) |

**Endianness.** Little-endian throughout. The ESP32, x86, and ARM-based Macs are all little-endian — no swaps needed anywhere in the pipeline.

**Time base.** `u32` milliseconds since session start. Wraps in ~49 days, which is far longer than any plausible session. Microsecond precision was tempting but `u32 µs` wraps in 71 minutes, and `u64 µs` doubles timestamp overhead per record. Millisecond resolution preserves the features that matter (stroke cadence at 50 spm has 1200 ms period — ms precision is 0.04% timing error; force-curve features are 50–100 ms wide).

**Scale factors are implicit by version.** Version 1 means ±16 g accel, ±2000 dps gyro. Storing scales in the header was considered but rejected — implicit-by-version is simpler and a hardware change that affects scaling is exactly the kind of thing that should bump the format version anyway.

---

## File layout

```
+----------------------+
| File header (32 B)   |
+----------------------+
| Record 1             |
+----------------------+
| Record 2             |
+----------------------+
| ...                  |
+----------------------+
```

A session file = one header followed by an arbitrary stream of records. Records are not guaranteed to be in monotonic time order across types (e.g., a GPS record may arrive a few ms "late" relative to an IMU record), but timestamps within each record are accurate.

Filename convention: `kg_NNNNNN.bin` where `NNNNNN` is the zero-padded `session_id` from the header.

---

## File header (32 bytes)

| Offset | Field | Type | Notes |
|---|---|---|---|
| 0 | `magic` | u32 | `0x474C494B` (`'KILG'` little-endian). Reject if mismatch. |
| 4 | `version` | u16 | Currently `1`. |
| 6 | `hardware_id` | u16 | `1` = breadboard v0. Reserved for future hardware revisions. |
| 8 | `session_id` | u32 | Monotonic across sessions; matches filename. |
| 12 | `start_unix_us` | u64 | Unix microseconds at session start. `0` if GPS time wasn't available yet — a later `TIME` record will provide the anchor. |
| 20 | `reserved[12]` | bytes | Zero. Reserved for future use. |
| 32 | — end — | | |

Python `struct` format string: `<I H H I Q 12s`

---

## Record framing

Every record on disk:

```
+--------+------+--------+-----------+------------------+------+
| sync   | type | length | timestamp | payload (length) | crc8 |
| 2 B    | 1 B  | 1 B    | 4 B       | length bytes     | 1 B  |
+--------+------+--------+-----------+------------------+------+
```

Total record size = `9 + length` bytes (8-byte header + payload + 1-byte CRC).

| Field | Type | Notes |
|---|---|---|
| `sync` | u16 | Always `0xAA55`. Resync marker — see Recovery below. |
| `type` | u8 | `KgRecordType` (see table). |
| `length` | u8 | Payload byte count (excludes header and CRC). |
| `timestamp` | u32 | Milliseconds since session start. |
| `payload` | variable | See per-type structures below. |
| `crc8` | u8 | Computed over `[type, length, timestamp, payload]`. Excludes sync. |

**CRC8 algorithm:** polynomial `0x07` (CCITT-8), init `0x00`, no reflection, no final XOR.

```python
def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc
```

---

## Record types

### Type 1 — IMU (12-byte payload)

| Offset | Field | Type | Scale (v1) |
|---|---|---|---|
| 0 | `ax` | i16 | × 0.000488 × 9.80665 → m/s² |
| 2 | `ay` | i16 | same |
| 4 | `az` | i16 | same |
| 6 | `gx` | i16 | × 0.070 × π/180 → rad/s |
| 8 | `gy` | i16 | same |
| 10 | `gz` | i16 | same |

Python `struct` format: `<hhhhhh`

### Type 2 — GPS (24-byte payload)

| Offset | Field | Type | Scale |
|---|---|---|---|
| 0 | `lat` | i32 | × 1e-7 → degrees |
| 4 | `lon` | i32 | × 1e-7 → degrees |
| 8 | `alt_mm` | i32 | × 1e-3 → meters MSL |
| 12 | `speed_mm_s` | u32 | × 1e-3 → m/s |
| 16 | `heading_cd` | u16 | × 1e-2 → degrees |
| 18 | `fix_type` | u8 | 0 = none, 2 = 2D, 3 = 3D |
| 19 | `num_sats` | u8 | |
| 20 | `hdop_c` | u16 | × 1e-2 → unitless |
| 22 | `reserved` | u16 | Zero. |

Python `struct` format: `<iiiI H BB H H`

### Type 3 — Event (1-byte payload)

| Offset | Field | Type | Notes |
|---|---|---|---|
| 0 | `code` | u8 | See event codes below. |

Event codes:

| Code | Name | Meaning |
|---|---|---|
| 1 | `SESSION_START` | First record after header, always. |
| 2 | `SESSION_END` | Last record before file close. |
| 3 | `USER_MARK` | User pressed the "mark this moment" button. |
| 4 | `GPS_FIX_LOST` | GPS dropped from 3D fix to less. |
| 5 | `GPS_FIX_FOUND` | GPS acquired 3D fix. |

### Type 4 — Battery (4-byte payload)

| Offset | Field | Type | Notes |
|---|---|---|---|
| 0 | `voltage_mv` | u16 | Millivolts |
| 2 | `percent` | u8 | 0-100 |
| 3 | `charging` | u8 | 0 or 1 |

Python `struct` format: `<H B B`

### Type 5 — Time anchor (12-byte payload)

| Offset | Field | Type | Notes |
|---|---|---|---|
| 0 | `local_ms` | u32 | Local timestamp this anchor corresponds to |
| 4 | `unix_us` | u64 | Unix microseconds at the same instant |

The parser uses these to convert every other record's `local_ms` timestamp to absolute time. The first TIME record after GPS fix establishes the anchor; subsequent ones let you detect MCU clock drift.

Python `struct` format: `<I Q`

---

## Versioning policy

- **Patch-compatible changes** (don't bump version): adding a new record type. Old parsers skip unknown types using the `length` field.
- **Breaking changes** (bump version): changing any existing struct layout, scale factor, or the meaning of an existing field.

The Python parser should reject files whose `version` it doesn't recognize, rather than guess at compatibility.

---

## Recovery from corruption

SD writes occasionally tear (power loss, card eject). The parser should handle this gracefully:

1. Validate the file header. Reject if magic or version are wrong.
2. For each record:
   - Verify the sync bytes are `0xAA55`. If not, advance one byte and try again.
   - Read the header. If `length` is implausible (e.g., a known record type with the wrong size), treat as corruption.
   - Read the payload and CRC. If CRC fails, advance to the next sync and report.
3. Skip unknown record types by reading `length` bytes and continuing.

A clean parser logs how many bytes were skipped to corruption and how many records were recovered. Loud failure is better than silent corruption.

---

## Worked example: parsing one IMU record

Given these 21 bytes on disk:

```
55 AA 01 0C 64 00 00 00  FF 7F 00 80 00 00 00 00 50 0A 00 00 00  XX
```

| Bytes | Interpretation |
|---|---|
| `55 AA` | sync = `0xAA55` (little-endian) ✓ |
| `01` | type = 1 (IMU) |
| `0C` | length = 12 |
| `64 00 00 00` | timestamp = 100 ms |
| `FF 7F` | ax = 32767 → 32767 × 0.000488 × 9.80665 ≈ 156.9 m/s² (saturated) |
| `00 80` | ay = -32768 → -156.9 m/s² (saturated, opposite direction) |
| `00 00` | az = 0 |
| `00 00 00 00 50 0A` | gx, gy, gz |
| `XX` | crc8 of the 16 bytes between sync and crc |

---

## Reference Python parser sketch

```python
import struct
from collections import namedtuple

HEADER_FMT  = "<I H H I Q 12s"
RECORD_HDR  = "<H B B I"  # sync, type, length, timestamp
IMU_FMT     = "<hhhhhh"
GPS_FMT     = "<iiiI H BB H H"
BATT_FMT    = "<H B B"
TIME_FMT    = "<I Q"

MAGIC = 0x474C494B
SYNC  = 0xAA55

def parse(path):
    with open(path, "rb") as f:
        header = struct.unpack(HEADER_FMT, f.read(32))
        magic, version, hw_id, session_id, start_unix_us, _ = header
        assert magic == MAGIC, f"bad magic {magic:#x}"
        assert version == 1, f"unsupported version {version}"

        records = []
        while True:
            buf = f.read(8)
            if len(buf) < 8:
                break
            sync, rtype, length, ts = struct.unpack(RECORD_HDR, buf)
            if sync != SYNC:
                # resync logic goes here
                continue
            payload = f.read(length)
            crc = f.read(1)[0]
            # verify crc, dispatch on rtype, etc.
            records.append((ts, rtype, payload))
        return header, records
```

---

## Data rates

Per-record overhead: 9 bytes (8 B header + 1 B CRC).

| Source | Rate | Record size | Throughput |
|---|---|---|---|
| IMU | 104 Hz | 21 B | 2.18 KB/s |
| GPS | 1 Hz (5 Hz later) | 33 B | 33 B/s → 165 B/s |
| Battery | 0.033 Hz | 13 B | 0.4 B/s |
| Events / time | very rare | varies | negligible |

Session total at 1 Hz GPS: ~2.2 KB/s, ~7.9 MB/hour. A 32 GB card holds ~4000 hours of data. SD writes are not the bottleneck.

---

## Open questions / known limitations for v1

- **One IMU sample per `imu::update()` cycle, not per FIFO entry.** The current `imu` module only exposes the most-recent sample after a drain. Real analysis wants every 104 Hz sample. Fix is a future change to `imu.{h,cpp}` to expose the full FIFO drain — the log format already supports this rate.
- **No checksum on the file header.** Header is short enough to eyeball; if it's corrupt, the file is unrecoverable anyway.
- **No file-level total CRC.** Per-record CRC8 is sufficient for the failure modes we expect (single-record SD write tears).
- **No record-type for display state or UI events.** Add when needed (UI is Wave 4).
