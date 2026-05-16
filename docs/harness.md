# KiloGlide Wiring Harness

Reference for soldering the v1 prototype harness. All pin assignments verified
against the firmware source (`button.h`, `led.h`, `imu.cpp`, `gps.cpp`,
`logger.cpp`).

Wire color suggestions are conventions, not requirements. Pick any colors you
like — just write down what you used.

---

## Power rail

Battery → charger → 3.3 V to all peripherals. The ESP32-S3 DevKitC has an
onboard 3.3 V LDO accessible via the `5V` pin (accepts 3.7–5.5 V battery
directly) **or** you can feed regulated 3.3 V straight to the `3V3` pin and
bypass the onboard LDO.

| From                     | To                       | Wire | Notes |
|--------------------------|--------------------------|------|-------|
| LiPo +                   | bq25185 `BAT`            | Red  | Battery input to charger |
| LiPo −                   | bq25185 `GND`            | Black | |
| USB-C (charge port)      | bq25185 `IN` / `VBUS`    | Red  | Per bq25185 module silkscreen |
| bq25185 `OUT` / `SYS`    | ESP32-S3 `5V` pin        | Red  | System load — uses ESP32 onboard LDO |
| bq25185 `GND`            | ESP32-S3 `GND`           | Black | |
| ESP32-S3 `3V3` pin       | IMU breakout `Vin`       | Red  | 3.3 V rail |
| ESP32-S3 `3V3` pin       | GPS breakout `3V3`       | Red  | 3.3 V rail |
| ESP32-S3 `3V3` pin       | SD breakout `3V` pin     | Red  | Use the 3V pin (not 5V) since the Adafruit breakout regulates 5V→3.3V; feeding 3.3V to the 5V pin works but wastes drop. |
| ESP32-S3 `GND`           | IMU `GND`                | Black | |
| ESP32-S3 `GND`           | GPS `GND`                | Black | |
| ESP32-S3 `GND`           | SD `GND`                 | Black | |

Star-ground all the modules at the ESP32 ground pin if you can — avoids
ground loops with the GPS antenna.

---

## SPI2 bus — IMU (LCD shares this bus, not yet wired)

Shared clock/MOSI/MISO across all SPI2 devices, separate CS per device.

| From (ESP32-S3 GPIO) | To (IMU pin) | Wire   | Function |
|----------------------|--------------|--------|----------|
| GPIO 12              | `SCL` / SCK  | Yellow | SPI clock |
| GPIO 11              | `SDI` / MOSI | Blue   | Master out |
| GPIO 13              | `SDO` / MISO | Green  | Master in |
| GPIO 10              | `CS`         | White  | IMU chip select |
| GPIO 4               | `INT1`       | Orange | FIFO watermark interrupt |

The LSM6DSOX breakout's silkscreen uses I²C labels (`SCL`/`SDA`) but the
pins work for SPI when CS is held low. Confirmed against the Adafruit
LSM6DSOX schematic.

When the LCD is added later: GPIO 12, 11, 13 will be shared; LCD gets its
own CS on a free GPIO (TBD).

---

## SPI3 bus — microSD

Dedicated bus. SD cards misbehave when sharing SPI with other devices, so
this gets its own peripheral.

| From (ESP32-S3 GPIO) | To (SD breakout pin) | Wire   | Function |
|----------------------|----------------------|--------|----------|
| GPIO 6               | `CLK`                | Yellow | SPI clock |
| GPIO 7               | `DI` / MOSI          | Blue   | Master out |
| GPIO 14              | `DO` / MISO          | Green  | Master in |
| GPIO 5               | `CS`                 | White  | SD chip select |

Card detect pin (`CD`) on the Adafruit breakout is unused — leave it open.

---

## I²C bus — GPS

Single-device bus. SparkFun Qwiic boards have built-in 4.7 kΩ pull-ups so
no external resistors needed.

| From (ESP32-S3 GPIO) | To (GPS pin) | Wire   | Function |
|----------------------|--------------|--------|----------|
| GPIO 8               | `SDA`        | Purple | I²C data |
| GPIO 9               | `SCL`        | Brown  | I²C clock |

If you use a Qwiic cable instead of discrete wires, the cable carries all
four (V+, GND, SDA, SCL) and you can skip the GPS power rows above —
just confirm the cable's V+ is on the 3.3 V rail.

---

## User input

| From (ESP32-S3 GPIO) | To           | Wire  | Function |
|----------------------|--------------|-------|----------|
| GPIO 1               | Button leg 1 | Any   | Active-low input with internal pull-up |
| GND                  | Button leg 2 | Black | |

No external pull-up — firmware enables the ESP32's internal 45 kΩ pull-up.
Short tap = user mark; 2 s hold = toggle session.

---

## Onboard (no wiring needed)

| Function | GPIO | Notes |
|----------|------|-------|
| RGB status LED | GPIO 38 | NeoPixel on the DevKitC — solder nothing |

Status colors: **red** = error, **blue** = standby, **green** = logging,
**white flash** = mark recorded.

---

## Cautions and gotchas

- **Strapping pins to avoid.** GPIO 0, 3, 45, 46 are ESP32-S3 strapping pins.
  They affect boot mode. Don't use them for peripherals. Current pin map
  avoids them.
- **GPIO 1 = UART0 RX on some pinouts.** It's fine for our use (input
  button) but means the serial console can't simultaneously use it. If you
  ever lose serial debug output, this is the suspect.
- **GPIO 19, 20 are USB.** Don't repurpose; you'll lose USB programming.
- **Boot button (GPIO 0) on the DevKitC.** Not our session button. Don't
  confuse them while debugging.
- **GPS antenna placement.** The SAM-M10Q needs sky view. If you bury it
  under the IMU or under metal, fix rate will drop. Mount it on top of the
  stack, antenna up.
- **SD card insertion direction.** Some breakouts are upside-down compared
  to where you'd expect. Check the silkscreen.

---

## Bench-check sequence before water

Power up over USB only (no battery) first. Verify in this order:

1. Serial monitor: ESP32 boots, prints firmware version.
2. LED goes **blue** (standby) within a few seconds → IMU + SD initialized.
3. Tap button → **white flash** confirms button wiring.
4. Long press → LED goes **green** (logging started). Confirm a new file
   appeared on the SD card.
5. Long press again → LED returns to **blue**.
6. Power off, plug in battery, unplug USB. Repeat steps 2–5 on battery only.
7. Take it outside. GPS should achieve 3D fix within ~60 seconds with sky view.

If any step fails, debug at the bench — not at the dock.

---

## Pre-flight checklist (water-test day)

- [ ] Battery charged (check LED on charger)
- [ ] SD card formatted FAT32 and inserted
- [ ] Device sealed and bungeed in final mounting position
- [ ] Mounting orientation photo taken (settles axis-convention questions later)
- [ ] Dock calibration: long-press to start session, sit still 20 s, leave running
- [ ] Axis-verification motions logged: 5× forward push, 5× right roll, 5× left roll, 5× nose-up pitch — short-tap between sets
- [ ] One-side-only block planned (20 R-only, 20 L-only) for side-classifier ground truth
- [ ] Paper log: session start time, weather, water conditions, anything notable
- [ ] Phone video of at least one paddle segment for cross-referencing later
- [ ] Long-press at end of session before extracting SD card
