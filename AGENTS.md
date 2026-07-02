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
- `perg_plot.py` — Concept2-PM5-style per-stroke force curves; `--overlay` compares mean
  whole-stroke curves (pull + recovery) across laps
- `connected_quick.py` — quick Connected % printout for spot-checks
- `stroke_rate_timeline.py` — whole-session cadence (stroke-rate) timeline
- `nk_speedcoach.py` (`load_nk`) + `speedcoach_report.py` — NK SpeedCoach loader and the
  SpeedCoach-vs-KG data-quality + comparison report

This is the full, deliberately-lean script set. The directory was trimmed of redundant
single-session one-offs (the old `analyze_session`, `bonus_visualizations`, `lean_and_bursts`,
the `side_*` L/R-exploration scripts, the duplicate connection/speedcoach scripts) — recover
any from git history if needed. Before adding a NEW analysis script, check what already exists
and extend it instead of duplicating; keep new scripts session-aware (`--session N`) and general.

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

## Local tooling

GitHub CLI is installed and authenticated as `Brzotto`, but Codex may not see
`gh` on PATH. Use the full path if needed:

`C:\Program Files\GitHub CLI\gh.exe`

Useful commands:
- `& 'C:\Program Files\GitHub CLI\gh.exe' auth status`
- `& 'C:\Program Files\GitHub CLI\gh.exe' pr create`
- `& 'C:\Program Files\GitHub CLI\gh.exe' pr view`
- `& 'C:\Program Files\GitHub CLI\gh.exe' pr merge`

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

## Coding guidelines

Keep it simple — no premature optimization. Comment non-obvious lines. Build one
feature at a time, testable before moving on.

**Write general code, never session-specific one-offs.** Analysis scripts must
work for any session, not just the one in front of you. Never hard-code session
facts — file paths, dates, lap numbers, or thresholds tuned to a single session.
Session-specific data belongs in the manifest (`analysis/data/sessions.json`),
reached via `session_config` and a `--session N` argument; generated artifacts go
under `analysis/plots/session_N/`.

Physically-motivated constants (e.g. the 0.5-3 Hz stroke band) are fine as
defaults. Anything that could vary by session, boat, mount, or conditions must be
overridable — via the manifest or a CLI flag — not edited in the source. When you
touch an older exploratory script that still carries single-session assumptions,
generalize it rather than adding another hard-coded constant.

Firmware: use Arduino framework conventions.

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
- docs/on_water_testing_checklist.md — reusable pre/in/post-session checklist for clean data capture
- docs/connection_test_protocol.md — on-water A/B protocol for the connection-usefulness test
- docs/handoff_2026-06-03_connection.md — handoff for the connection-usefulness phase
- docs/handoff_2026-07-02.md — reference point through session 46 (state, open threads, cross-session learnings)
- analysis/session_37_report.md — first water-test report
- analysis/session_37_status_and_next_session.md — what's working and what's needed next
