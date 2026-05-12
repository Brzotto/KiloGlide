# KiloGlide — Firmware Roadmap

Staged plan that matches the hardware order waves. Each phase is gated by what's physically on the bench. Firmware is developed, tested, and committed before moving to the next phase.

---

## Framework decision: PlatformIO + Arduino-ESP32

PlatformIO with the Arduino-ESP32 framework. Not Arduino IDE, not ESP-IDF.

- PlatformIO: proper dependency pinning in `platformio.ini`, clean CLI, works well in VSCode
- ESP-IDF: more powerful, steeper curve. Drop into it later if needed — code is portable

### Library shortlist

| Component | Library | Notes |
|---|---|---|
| LSM6DSOX | `Adafruit_LSM6DSOX` | Solid, well-documented. SPI mode. |
| Sharp LCD | `Adafruit_SHARP_Memory_Display` | Written for our exact breakout (PID 4694) |
| GPS (M8Q) | `SparkFun_u-blox_GNSS_v3` | Use UBX binary mode, skip NMEA parsing |
| microSD | `SdFat` (Bill Greiman) | Faster + more reliable than stock SD lib for sustained logging |
| Filesystem | `LittleFS` for config, `SdFat` for session logs | Different roles |
| Buttons | `Bounce2` | Debouncing |

---

## Repo structure

```
KiloGlide/
├── CLAUDE.md                   # Claude Code context file
├── README.md
├── platformio.ini              # in root, not firmware/
├── .gitignore
├── firmware/
│   ├── src/
│   │   ├── main.cpp
│   │   ├── imu.{h,cpp}
│   │   ├── gps.{h,cpp}
│   │   ├── logger.{h,cpp}
│   │   ├── display.{h,cpp}
│   │   ├── ui.{h,cpp}
│   │   └── log_format.h        # shared with Python tools
│   └── include/
├── tools/
│   ├── fake_imu.py             # generates synthetic data for offline dev
│   └── plot_session.py         # quick visualization
├── analysis/
│   └── analyze_session.py      # stroke detection, asymmetry, fatigue
├── docs/
│   ├── decisions.md
│   ├── data_insights.md
│   ├── firmware_roadmap.md
│   ├── developer_setup.md
│   ├── math_primer.md
│   └── log_format.md           # binary spec, source of truth
└── sessions/                   # gitignored — raw logs from water tests
```

`log_format.h` and `log_format.md` are paired — the C header is the canonical record layout, the markdown explains it for humans and the Python parser. When you change one, you change both, in the same commit.

---

## Pre-hardware work — COMPLETED

- [x] Set up repo on GitHub (Brzotto/KiloGlide)
- [x] Install PlatformIO in VSCode
- [x] Create project skeleton with platformio.ini
- [x] Write fake_imu.py — synthetic 416 Hz IMU data with stroke patterns
- [x] Write analyze_session.py — stroke detection, asymmetry, fatigue analysis
- [x] Set up Python environment (numpy, matplotlib)
- [ ] Write log_format.h and log_format.md — binary record spec
- [ ] Write binary log_reader.py (currently using CSV; binary comes with Wave 2)

---

## Proposed log format (v1)

```
File header (32 bytes, written once):
  magic        u32   0x4B494C47 ('KILG')
  version      u16   0x0001
  hardware_id  u16   board revision
  session_id   u32   monotonic, set at session start
  start_time   u64   unix microseconds (from GPS, or 0 if no fix yet)
  reserved     u64

Records (variable length, packed):
  sync         u16   0xAA55
  type         u8    1=IMU, 2=GPS, 3=EVENT, 4=BATTERY, 5=MARK
  length       u8    payload bytes
  timestamp    u32   microseconds since session start
  payload      ...
  crc8         u8    over type+length+timestamp+payload

IMU payload (12 bytes):
  ax, ay, az   i16   raw, scale per FS setting in header
  gx, gy, gz   i16   raw, scale per FS setting in header

GPS payload (24 bytes):
  lat, lon     i32   degrees * 1e7
  alt          i32   mm
  speed        u32   mm/s
  heading      u16   degrees * 100
  fix_type     u8
  num_sats     u8
  hdop         u16   * 100
  reserved     u32
```

Sync bytes mean a corrupted region doesn't kill the whole file — the parser can resync. CRC8 catches single-record corruption. At 416 Hz IMU + 5 Hz GPS: ~7 KB/sec, ~25 MB/hour.

---

## Wave 1: ESP32-S3 + IMU — IN PROGRESS

**Hardware on bench:** dev kit, IMU breakout, perfboard, headers, USB-C.

### Day 1 goals — COMPLETED

1. ~~Blinky on the dev kit — verify toolchain end-to-end~~
2. Wire IMU to SPI2: SCK=GPIO 12, MOSI=GPIO 11, MISO=GPIO 13, CS=GPIO 10
3. Initialize LSM6DSOX, read WHO_AM_I, confirm communication
4. Stream raw accel + gyro over USB serial, eyeball in serial monitor

### Week 1 goals

5. Configure IMU FIFO with watermark interrupt — **do not poll**. The FIFO holds samples in hardware; you read 32–64 samples per interrupt instead of one. This is the difference between reliable 400 Hz and dropped samples.
6. Run sensor task on Core 1, leave Core 0 for everything else (dual-core ESP32)
7. Implement complementary filter for roll/pitch. Print at 10 Hz over serial.
8. Stroke detection v0: peak detection on accel-Z above a threshold, with hysteresis and refractory period. Print stroke count.
9. Capture 5 minutes of swinging the IMU around like a paddle, pipe serial output to CSV, load in analyze_session.py. Confirm analysis pipeline works on real data.

### Week 2+ goals

10. Force curve extraction: segment each stroke, compute peak value, peak position, impulse, skew.
11. Exit detection: forward acceleration zero-crossing (more robust than roll reversal — hip movement contaminates roll signal).
12. Side classification: roll velocity sign at catch. Acknowledge contamination from hips; validate on real water data.
13. Capture desk-test data at different "stroke styles" — hard/soft, left-biased/right-biased. Verify analysis pipeline detects the differences.

### Key technical decisions

- **Sample rate:** 416 Hz. Native ODR for the LSM6DSOX, gives ~50 samples per stroke at 50 spm.
- **Full-scale ranges:** ±16g accel, ±2000 dps gyro.
- **Don't poll the IMU.** FIFO + interrupt.
- **Timestamp source:** ESP32 `esp_timer_get_time()` returns microseconds. Anchor to GPS time in Wave 2.
- **Orientation filter:** complementary filter, not Kalman. Three lines of code, sufficient for paddling dynamics.
- **Exit detection signal:** forward acceleration zero-crossing, not roll reversal. Roll is contaminated by hip-induced movement independent of paddle entry/exit.

---

## Wave 2: + GPS + microSD

**Hardware added:** SAM-M8Q GPS, microSD breakout + cards.

This is where you have a working data logger. Get it on a boat.

### Goals

1. microSD on **dedicated SPI3** (do not share — SD cards misbehave on shared buses). Pins: SCK=GPIO 6, MOSI=GPIO 7, MISO=GPIO 14, CS=GPIO 5. Use SdFat in `O_RDWR | O_CREAT | O_AT_END` mode with periodic `flush()` (every 1–5 seconds, not every record).
2. Implement the binary log writer per `log_format.h`. Write IMU records at 416 Hz, GPS records at 5 Hz.
3. GPS via I2C (SDA=GPIO 8, SCL=GPIO 9) using SparkFun u-blox library, UBX binary mode. Configure for 5 Hz updates, request PVT messages.
4. Session lifecycle: file = session. Filename `kiloglide_<session_id>.bin`. **Start on button press for v0** (not motion-detect — false starts in gear bags). End on button press or idle timeout.
5. Time-sync: at GPS first fix, write a MARK record with the GPS time → session-time-offset. Python parser uses this to convert microseconds-since-start to absolute time.
6. **First water test.** Bag the breadboard in a ziploc, take it on a paddle, log everything. Don't try to display anything. Bring it home, parse the log, plot it. Celebrate.

### Watch out for

- SD card write latency spikes. SdFat handles this better than stock, but a write occasionally takes 50–100 ms. Buffer at least 1 second of IMU data in RAM so a slow write doesn't drop samples.
- GPS cold start can take 30+ seconds outdoors. Don't block session start on GPS fix — start logging IMU immediately, splice GPS in when it arrives.
- Power: SD writes spike to ~100 mA briefly. Generous decoupling on the breadboard (10 µF + 0.1 µF near the SD breakout).
- GPS needs sky view — test near a window or outside.

---

## Wave 3: + Display + Power

**Hardware added:** Adafruit SHARP Memory Display Breakout (PID 4694), bq25185 charger, 2000 mAh LiPo.

Now it's wearable on the boat without a USB tether.

### Goals

1. Sharp LCD on SPI2 (shared with IMU, different CS). 400×240 monochrome, 12 KB frame buffer in RAM. Use `beginTransaction()` with correct SPI settings before each device — IMU runs faster than LCD.
2. Render basic UI: cadence top-left, corrected DPS top-right, force curve trace bottom half. Refresh at 4–10 Hz.
3. **Force curve display:** effective drive force vs stroke phase (0–100%). Overlay last 3–5 strokes, most recent brightest. Update on stroke detection, not on a timer. This is the headline visual.
4. Battery voltage on ADC. bq25185 exposes battery voltage on a pin. Log a BATTERY record every 30 seconds.
5. Power management: WiFi/BT off by default (only enable for upload mode later).
6. **Bench-measure runtime.** Full duty cycle, IMU + GPS + SD logging, display on. Target 4+ hours from 2000 mAh. If you don't hit it, audit IMU and GPS power configs first.

### SPI2 sharing note

IMU runs at ~10 MHz, LCD at ~2 MHz. Wrap each device's I/O in helper functions that always `beginTransaction()` with the right settings and `endTransaction()` after. Don't trust yourself to remember at every call site.

---

## Wave 4: + UI + integration

**Hardware added:** buttons, LEDs, resistors, custom case, NK mount.

### Goals

1. Button debouncing with `Bounce2`. Two buttons: short-press cycles screens, long-press starts/stops session.
2. Menu structure: live screen, last-session summary screen, battery/storage status, settings.
3. LED for storage activity + session-active indicator. Visible through the case.
4. Final assembly into custom waterproof case. Conformal coat the PCB first, mylar pouch + desiccant inside.
5. Mount integration with NK dovetail.
6. If custom case isn't ready, fall back to Pelican 1010 (IP67, polycarbonate, ePTFE vent built in).

---

## Cross-cutting: testing approach

Hardware testing is slow and weather-dependent. Lean on simulation hard.

- **`tools/fake_imu.py`** generates synthetic IMU at 416 Hz with controllable stroke rate, asymmetry, fatigue drift. The analysis pipeline should load fake and real sessions identically.
- **`analysis/analyze_session.py`** loads sessions (fake or real), runs stroke detection, computes per-stroke features, plots force curves, asymmetry, and fatigue.
- **Replay mode in firmware (future):** a build flag that reads samples from flash instead of the IMU. Lets you test display + algorithm changes at your desk.
- **Field test checklist** (commit as `docs/field_test_checklist.md` once it stabilizes): battery topped, SD card inserted and formatted, GPS sky view confirmed before launch, session button pressed, etc.

---

## Out of scope for v0 firmware

Explicitly defer these. They expand scope without de-risking the core.

- WiFi upload / cloud sync — USB cable + SD card eject is fine for v0
- BLE phone app
- ANT+ / Garmin Connect — phase 2–3 per `decisions.md`
- OTA firmware updates — when there are users
- Real-time TSP / corrected DPS on-device — develop offline first, port once proven
- Multi-paddler / boat-share modes
- Kalman filtering — complementary filter is sufficient
- On-device ML inference — analysis belongs in Python / cloud
- Phone app — validate metrics in Jupyter first, build app from validated insights
