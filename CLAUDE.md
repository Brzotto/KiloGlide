# KiloGlide

Open-water paddling coach. ESP32-S3 + LSM6DSOX IMU + u-blox SAM-M8Q GPS + Sharp memory LCD.

*Kilo* is Hawaiian for observer. The device observes your glide and reports what it sees.

## Project status

Wave 1 complete: IMU (LSM6DSOX) running with FIFO + watermark interrupt.
Wave 2 in progress: GPS bringup done, SD card next.

## Hardware

- MCU: ESP32-S3-DevKitC-1 (N8R8 — 8MB flash, 8MB PSRAM)
- IMU: Adafruit LSM6DSOX breakout (SPI on SPI2, CS = GPIO 10)
- GPS: SparkFun SAM-M8Q (I2C, SDA = GPIO 8, SCL = GPIO 9)
- Display: Adafruit SHARP Memory Display 2.7" 400x240 (SPI2, shared with IMU, different CS)
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
