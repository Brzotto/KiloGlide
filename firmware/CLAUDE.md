# KiloGlide Firmware

This directory contains the Arduino-ESP32 firmware for the KiloGlide device.
Keep agent context small: read the module, header, and firmware docs relevant
to the change, but avoid loading analysis reports unless the firmware change
affects logged data semantics.

## Agent instruction mirrors

Keep `firmware/AGENTS.md` and `firmware/CLAUDE.md` byte-for-byte identical.
When changing one, make the same change to the other in the same commit.

## Current architecture

- Build system: PlatformIO with Arduino-ESP32.
- MCU: ESP32-S3-DevKitC-1.
- IMU: LSM6DSOX on SPI2 using FIFO and watermark interrupt.
- GPS: SparkFun/u-blox GPS on I2C, logging UBX PVT at 5 Hz.
- Storage: microSD on dedicated SPI3.
- Button events: user mark plus session start/end.
- Binary records are defined in `firmware/src/log_format.h`, documented in
  `docs/log_format.md`, and parsed by `tools/kg_parse.py`.

## Firmware principles

- Keep changes simple and testable one feature at a time.
- Use Arduino framework conventions and the existing module boundaries.
- Do not casually change the binary log layout. If a log record changes, update
  `log_format.h`, `docs/log_format.md`, and `tools/kg_parse.py` together, and
  consider whether the format version needs to change.
- Adding meaning to an existing reserved field is acceptable only when the docs
  and parser clearly describe the field and older logs remain readable.
- Keep sensor acquisition, logging, GPS parsing, display/UI, and button logic
  separated by responsibility.
- Preserve the bus architecture: SPI2 shared by IMU/display with transactions;
  SPI3 dedicated to SD.
- Logging should continue if optional peripherals are absent unless the user
  explicitly asks for fail-fast behavior.

## Key files

- `src/main.cpp` - top-level setup and task orchestration.
- `src/log_format.h` - binary log record definitions.
- `src/gps.*` - GPS setup, parsing, and PVT fields.
- `src/storage.*` - SD logging.
- `src/imu.*` - LSM6DSOX setup and FIFO handling.
- `src/button.*` - user mark and session events.
- `platformio.ini` - build configuration.

## Build and verification

Use PlatformIO from the repository root:

```bash
pio run
```

If `pio` is not on PATH, use the local PlatformIO executable. For log-format
changes, also parse a known-good binary or run the relevant analysis script.
