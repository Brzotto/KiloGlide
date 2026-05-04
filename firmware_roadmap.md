# KiloGlide — Firmware Roadmap

Staged plan that matches the hardware order waves. Each phase is gated by what's physically on the bench. Firmware is developed, tested, and committed before moving to the next phase.

---

## Framework decision: PlatformIO + Arduino-ESP32

**Recommendation:** PlatformIO with the Arduino-ESP32 framework, not Arduino IDE.

- Arduino IDE: fast to start, painful for serious work (no per-project deps, weak git integration, awkward CLI)
- PlatformIO: same library ecosystem (you can use any Arduino library), proper dependency pinning in `platformio.ini`, clean CLI for CI later, works well in VSCode
- ESP-IDF (native): more powerful, steeper curve. Drop into it later if you outgrow Arduino — code is portable enough that the move isn't painful

The Adafruit + SparkFun + u-blox libraries you'll need all live in the Arduino ecosystem and are well-maintained.

### Library shortlist

| Component | Library | Notes |
|---|---|---|
| LSM6DSOX | `Adafruit_LSM6DSOX` | Solid, well-documented. SPI mode. |
| Sharp LCD | `Adafruit_SHARP_Memory_Display` | Or roll your own — the protocol is trivial |
| GPS (M10Q) | `SparkFun_u-blox_GNSS_v3` | Use UBX binary mode, skip NMEA parsing |
| microSD | `SdFat` (Bill Greiman) | Faster + more reliable than stock SD lib for sustained logging |
| Filesystem | `LittleFS` for config, `SdFat` for session logs | Different roles |

---

## Repo structure

```
kiloglide/
├── firmware/
│   ├── platformio.ini
│   ├── src/
│   │   ├── main.cpp
│   │   ├── imu.{h,cpp}
│   │   ├── gps.{h,cpp}
│   │   ├── logger.{h,cpp}
│   │   ├── display.{h,cpp}
│   │   ├── ui.{h,cpp}
│   │   └── log_format.h        # shared with Python tools
│   └── lib/                    # any vendored libraries
├── tools/
│   ├── log_reader.py           # parses binary session files
│   ├── fake_imu.py             # generates synthetic data for offline dev
│   └── plot_session.py         # quick visualization
├── analysis/                   # Jupyter notebooks for algorithm dev
├── docs/
│   ├── decisions.md
│   ├── data_insights.md
│   ├── firmware_roadmap.md
│   └── log_format.md           # binary spec, source of truth
└── sessions/                   # gitignored — raw logs from water tests
```

`log_format.h` and `log_format.md` are paired — the C header is the canonical record layout, the markdown explains it for humans and the Python parser. When you change one, you change both, in the same commit.

---

## Pre-hardware work (do this week, before anything ships)

You can get a surprising amount done before the ESP32 arrives. None of this is wasted; all of it accelerates the day the parts hit the doormat.

1. **Set up the repo.** Initialize git, create the structure above, push to a private remote.
2. **Install PlatformIO** in VSCode. Create the project skeleton with the ESP32-S3-DevKitC-1 board target.
3. **Write `log_format.md` and `log_format.h`.** Decide the binary record layout now (proposal below). Lock it in. The Python parser and the firmware logger both consume this.
4. **Write `tools/log_reader.py`.** Reads a binary session file, yields records. ~50 lines. Test it against `tools/fake_imu.py`, which generates synthetic 200 Hz IMU data with realistic stroke shapes.
5. **Sketch the analysis pipeline in a Jupyter notebook.** Load fake data, run a basic stroke-detection algorithm, plot. This is where the actual product lives — the data layer that turns raw IMU samples into the metrics in `data_insights.md`. Develop it offline against synthetic data so it's ready when real data starts flowing.

By the time Wave 1 arrives, you have a parser, a fake-data simulator, and an analysis notebook. The first real session you record drops into a working pipeline.

### Proposed log format (v1)

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

Sync bytes mean a corrupted region doesn't kill the whole file — the parser can resync. CRC8 catches single-record corruption. Keep it tight; at 416 Hz IMU + 5 Hz GPS, you're writing ~7 KB/sec, ~25 MB/hour. Any modern SD card laughs at this.

---

## Wave 1: ESP32-S3 + IMU

**Hardware on bench:** dev kit, IMU breakout, perfboard, headers, USB-C.

### Day 1 goals

1. Blinky on the dev kit — verify toolchain end-to-end
2. Wire IMU to SPI2: SCK, MOSI, MISO, CS. Power off 3.3V from dev kit
3. Initialize LSM6DSOX, read WHO_AM_I, confirm communication
4. Stream raw accel + gyro over USB serial at 100 Hz, eyeball it in the serial plotter

### Week 1 goals

5. Configure IMU FIFO with watermark interrupt — **do not poll**. The FIFO holds samples in hardware; you read 32–64 samples per interrupt instead of one. This is the difference between reliable 400 Hz and dropped samples.
6. Run sensor task on Core 1, leave Core 0 for everything else (this is dual-core ESP32 — use both)
7. Implement complementary filter (or Madgwick if you want) for roll/pitch. Print at 10 Hz over serial.
8. Stroke detection v0: peak detection on accel-Z above a threshold, with a refractory period. Print stroke count.
9. Capture 5 minutes of you swinging the IMU around like a paddle, save the serial output to a CSV, plot it in the Jupyter notebook. Confirm the analysis pipeline works on real data from the real chip.

### Key technical decisions

- **Sample rate:** 416 Hz. Native ODR for the LSM6DSOX, gives ~50 samples per stroke at 50 spm (more than enough for clean force curves), leaves headroom on storage and bandwidth. Don't go higher until you have evidence you need it.
- **Full-scale ranges:** ±16g accel, ±2000 dps gyro. Paddling is well within these; don't truncate dynamics.
- **Don't poll the IMU.** FIFO + interrupt. Polling burns CPU and drops samples under load.
- **Timestamp source:** ESP32 `esp_timer_get_time()` returns microseconds. Anchor session start to GPS time once GPS arrives in Wave 2.

---

## Wave 2: + GPS + microSD

**Hardware added:** SAM-M10Q GPS, microSD breakout + cards.

This is where you have a working data logger. Get it on a boat.

### Goals

1. microSD on **dedicated SPI3** (do not share — SD cards misbehave on shared buses, especially with display). Use SdFat in `O_RDWR | O_CREAT | O_AT_END` mode with periodic `flush()` (every 1–5 seconds, not every record).
2. Implement the binary log writer per `log_format.h`. Write IMU records at 416 Hz, GPS records at 5 Hz.
3. GPS via I2C using SparkFun u-blox library, UBX binary mode (skip NMEA — it's slower and harder to parse). Configure for 5 Hz updates, request PVT messages.
4. Session lifecycle: file = session. Filename `kiloglide_<session_id>.bin`. Start on motion-detect (accel variance > threshold) or button. End on idle (no significant motion for N minutes) or button.
5. Time-sync: at GPS first fix, write a MARK record with the GPS time → session-time-offset. Python parser uses this to convert microseconds-since-start to absolute time.
6. **First water test.** Bag the breadboard in a ziploc, take it on a paddle, log everything. Don't try to display anything. Bring it home, parse the log, plot it. Celebrate.

### Watch out for

- SD card write latency spikes. SdFat handles this better than stock, but a write occasionally takes 50–100 ms. Buffer at least 1 second of IMU data in RAM so a slow write doesn't drop samples.
- GPS cold start can take 30+ seconds outdoors. Don't block session start on GPS fix — start logging IMU immediately, splice GPS in when it arrives.
- Power: SD writes spike to ~100 mA briefly. Make sure decoupling on the breadboard is generous (10 µF + 0.1 µF near the SD breakout).

---

## Wave 3: + Display + Power

**Hardware added:** Sharp LCD + Kuzyatech breakout, bq25185 charger, 2000 mAh LiPo.

Now it's wearable on the boat without a USB tether.

### Goals

1. Sharp LCD on SPI2 (shared with IMU, different CS). 400×240 monochrome, 12 KB frame buffer in RAM. ESP32-S3 has 8 MB PSRAM — frame buffer is trivial.
2. Render basic UI: cadence top-left, corrected DPS top-right, momentum curve trace bottom half. Refresh at 4–10 Hz (Sharp memory LCDs prefer slow refresh; they hold pixels indefinitely).
3. Battery voltage on ADC. bq25185 exposes battery voltage on a pin — wire it to an ADC input through a divider if needed. Log a BATTERY record every 30 seconds.
4. Power management: WiFi/BT off by default (only enable for upload mode later). Frontlight off by default — only on by button press, auto-off after 10 seconds.
5. **Bench-measure runtime.** Full duty cycle, IMU + GPS + SD logging, display on, frontlight off. Target 4+ hours from 2000 mAh. If you don't hit it, audit the IMU and GPS power configs first — they're the usual culprits.

### Display rendering note

The momentum curve trace is the headline visual. Render it as a circular buffer of the last N strokes (3–5 looks good), normalized so the most recent stroke is the brightest. Update on stroke detection, not on a timer — the visual aligns with what the paddler just felt.

---

## Wave 4: + UI + integration

**Hardware added:** buttons, LEDs, resistors, Pelican case, NK mount.

### Goals

1. Button debouncing (hardware RC + software, or just software with `Bounce2`). Two buttons is enough: short-press cycles screens, long-press starts/stops session.
2. Menu structure: live screen, last-session summary screen, battery/storage status, settings.
3. LED for storage activity + session-active indicator. Visible through the case.
4. Final assembly into Pelican 1010. Conformal coat first, mylar pouch + desiccant inside.
5. Mount integration with NK dovetail.

---

## Cross-cutting: testing approach

Hardware testing is slow and weather-dependent. Lean on simulation hard.

- **`tools/fake_imu.py`** generates synthetic IMU at 416 Hz with controllable stroke rate, asymmetry, fatigue drift. Pipes binary records in the log format. The analysis notebook should load fake and real sessions identically.
- **Replay mode in firmware:** a build flag that reads samples from flash instead of the IMU and runs them through the same pipeline. Lets you test display + algorithm changes at your desk.
- **Field test checklist** (commit this as `docs/field_test_checklist.md` once it stabilizes): battery topped, SD card inserted and formatted, GPS sky view confirmed before launch, session button pressed, etc. The first three sessions you'll forget one of these.

---

## Out of scope for v0 firmware

Explicitly defer these. They expand scope without de-risking the core.

- WiFi upload / cloud sync — USB cable + SD card eject is fine for v0
- BLE phone app — same reason
- ANT+ / Garmin Connect — Ray's suggestion, phase 2–3 per `decisions.md`
- OTA firmware updates — when there are users
- Real-time TSP / corrected DPS on-device — develop offline first, port to firmware once the algorithm is proven
- Multi-paddler / boat-share modes — feature creep
