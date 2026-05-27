# KiloGlide

Open-water paddling coach. ESP32-S3 + LSM6DSOX IMU + u-blox SAM-M8Q GPS + Sharp memory LCD.

*Kilo* is Hawaiian for observer. The device observes your glide and reports what it sees.

## Project status

Wave 1 complete: IMU (LSM6DSOX) running with FIFO + watermark interrupt.

Wave 2 complete: GPS + microSD + button all working. Firmware writes:
- IMU at 416 Hz (FIFO + watermark IRQ)
- GPS PVT at 5 Hz with FIX_FOUND/FIX_LOST event transitions
- TIME anchor (KG_REC_TIME) on first GPS UTC validity, then every 5 min for drift detection
- USER_MARK events on single short button press
- SESSION_START / SESSION_END events on long press

First on-water test (session 37, 2026-05-21, Alameda Bay): 79 min, 1.94M IMU samples,
zero CRC errors, clean log. Full analysis pipeline validated end-to-end against a paired
Garmin TCX activity (cross-correlation r=0.94).

Analysis pipeline (`analysis/` directory):
- `session_config.py` + `data/sessions.json` — multi-session manifest; scripts take `--session N`
- `correlate_kg_garmin.py` — primary pipeline (binary parse, time-align with Garmin, axis
  auto-detect, stroke detection, per-lap summary, force curves). TIME-record alignment when
  available, falls back to GPS cross-correlation.
- `coach_summary.py` — single-page coach summary with sport-familiar units (mph, lbs)
- `glide_speed_test.py` — within-stroke speed integration + two-tier glide metrics
  (IMU-only Tier 1 = current-independent; GPS-anchored Tier 2 = absolute speed context)
- `precatch_signature.py` — averaged forward-accel signature revealing pre-catch body motion
- `stroke_phases.py` — catch / pull / glide annotations + per-stroke quality ranking
- `perg_plot.py` — Concept2-PM5-style individual stroke force curves
- `bonus_visualizations.py` — DPS, heart rate, stroke evolution, summary dashboard
- `lean_and_bursts.py` — boat lean angle + per-burst side analysis + spectral content
- `side_envelope.py`, `side_rhythm.py`, `side_blocks.py` — L/R side discrimination
- `connected_quick.py` — quick Connected % printout for spot-checks

Open issues:
- Per-stroke L/R classification: noise-dominated in cruise water. Lap-level
  side fraction from the slow yaw envelope is reliable. Future work: combine
  yaw + lap-demeaned lateral for a per-stroke classifier.
- Display + power (Wave 3) not yet on the bench.

## Hardware

- MCU: ESP32-S3-DevKitC-1 (N8R8 — 8MB flash, 8MB PSRAM)
- IMU: Adafruit LSM6DSOX breakout (SPI on SPI2, CS = GPIO 10) (app note: https://www.allaboutcircuits.com/uploads/articles/lsm6dsox-machine-learning-core-stmicroelectronics_compressed.pdf)
- GPS: SparkFun SAM-M10Q (I2C, SDA = GPIO 8, SCL = GPIO 9) (app note: https://content.u-blox.com/sites/default/files/documents/SAM-M10Q_IntegrationManual_UBX-22020019.pdf)
- Display: Adafruit SHARP Memory Display 2.7" 400x240 (SPI2, shared with IMU, different CS)  (app note: https://www.adafruit.com/product/4694)
- Storage: Adafruit microSD breakout (SPI3, SCK=GPIO 6, MOSI=GPIO 7, MISO=GPIO 14, CS=GPIO 5)
- Power: Adafruit bq25185 charger + 2000 mAh LiPo
- Case: Custom waterproof case (in development)

## Build system

PlatformIO with Arduino-ESP32 framework. Config in `platformio.ini`.

## Architecture decisions

- SPI2 shared: IMU + LCD (different CS, different speeds — use beginTransaction)
- SPI3 dedicated: microSD (SD cards misbehave on shared buses)
- I2C: GPS
- IMU FIFO with watermark interrupt, not polling
- Sensor task on Core 1, display/UI on Core 0
- Binary log format defined in docs/firmware_roadmap.md
- Analysis pipeline in Python (tools/ and analysis/ directories)

## Developer context

The developer is an electrical engineer experienced with hardware but
new to firmware development, git, Python, and C++. Explain things clearly.
Don't write entire modules without being asked. Prefer teaching over
generating — explain what the code does and why, don't just produce it.

## Agent instruction mirrors

Keep `AGENTS.md` and `CLAUDE.md` files in the same directory byte-for-byte
identical. When changing one, make the same change to the other in the same
commit. Directory-level instruction files should stay short and point to the
canonical docs instead of repeating large project history; this keeps future
agent sessions small while preserving the right context.

When asked to write code:
- Keep it simple. No premature optimization.
- Use Arduino framework conventions.
- Comment non-obvious lines.
- One feature at a time, testable before moving on.

## Key documents

- docs/decisions.md — project decision log
- docs/firmware_roadmap.md — staged development plan
- docs/data_insights.md — data ideas and metrics
- docs/math_primer.md — algorithm explanations
- docs/developer_setup.md — environment setup guide
- docs/log_format.md — binary log format spec (paired with firmware/src/log_format.h)
- docs/harness.md — wiring reference
- docs/README_analysis.md — how to run the analysis pipeline on a new session
- docs/handoff_2026-05-23.md — handoff from the session 37 pipeline build
- docs/handoff_2026-05-23_glide.md — handoff from the glide-analysis session
- analysis/session_37_report.md — first water-test report
- analysis/session_37_status_and_next_session.md — what's working and what's needed next
