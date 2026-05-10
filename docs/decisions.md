# KiloGlide — Decisions Log

Running log of project decisions and reasoning. Update this when decisions change.

---

## Project Identity

**Name: KiloGlide** (renamed from Kikaha Coach)
- *Kilo* is Hawaiian for observer — the patient, expert watching that traditional navigators used to read the stars, the sea, and the wind
- KiloGlide observes your glide and reports what it sees
- The name describes the device's function: an expert observer of your glide
- Verify with Hawaiian paddlers before any public launch

**Spirit animal:** the frigate bird (ʻiwa) — retained from Kikaha Coach

**Vocabulary discipline:** dropped "power" language. Use "stroke impulse," "boat response," "effective drive," "corrected DPS." Don't borrow credibility from cycling/rowing power meters without ergometer validation.

**Product voice:** KiloGlide doesn't coach. It doesn't motivate. It observes and reports. The coaching happens between the paddler and the data, or between the paddler and a human coach reading the data together.

---

## Hardware — Locked Decisions

| Function | Part | Why |
|---|---|---|
| MCU | ESP32-S3-DevKitC-1 N8R8 | WiFi + BLE + 8MB PSRAM, extensive library support |
| IMU | Adafruit LSM6DSOX (PID 4438) | Available, SPI/I2C, library-swap to ICM-42688-P later if needed |
| GPS | SparkFun SAM-M8Q | Built-in patch antenna, I2C, same library as M10Q. Velocity accuracy 0.05 m/s (identical to M10Q) |
| Display (breadboard) | Adafruit SHARP Memory Display Breakout 2.7" 400x240 (PID 4694) | Sunlight readable, SPI, built-in boost converter. Adafruit's library written for this exact board |
| Display (production) | JDI LPM027M128C color MIP w/ frontlight | Adds color + dawn/dusk visibility, same SPI protocol family |
| Storage | Adafruit microSD breakout (PID 4682, NOT 254) | 3V-only matches ESP32 directly, supports SPI and SDIO |
| Power | Adafruit bq25185 USB/DC Charger + 3.3V Buck (PID 5703) | Single board for charging + load sharing + 3.3V regulation, USB-C |
| Battery | 2000 mAh LiPo with JST-PH | Updated from 1200 mAh. Target 4+ hour runtime |
| Buttons | 6mm tactile switches (PID 1489) | Inside case for v0 |
| Case | Custom waterproof case (in development by collaborator) | Replaces Pelican 1010. Keep Pelican as backup if custom case delays |
| Mounting | NK adjustable surface mount + 3D-printed dovetail backplate | Compatible with existing SpeedCoach brackets |

### Hardware changes from original BOM

- **GPS: SAM-M10Q → SAM-M8Q.** Velocity accuracy identical (0.05 m/s), which is the spec that matters for sub-stroke analysis. Slightly worse position accuracy (2.5m vs 1.5m) and ~30% higher power draw, both acceptable. Same I2C interface, same library.
- **Display breakout: Kuzyatech → Adafruit (PID 4694).** Same display panel, same SPI interface, built-in boost converter. Better library support — Adafruit's library is written for this exact board.
- **Battery: 1200 mAh → 2000 mAh.** More runtime headroom. Still needs bench verification for 4+ hour target.
- **Case: Pelican 1010 → Custom waterproof case.** Collaborator developing custom case. Allows PCB-first design (case fits board, not board fits case). Keep Pelican as fallback.

---

## Communication Buses

| Bus | Devices | Notes |
|---|---|---|
| SPI2 (shared) | IMU (CS=GPIO 10) + LCD (different CS) | Use beginTransaction() with correct settings before each device |
| SPI3 (dedicated) | microSD | Don't share — SD cards misbehave on shared buses |
| I2C | GPS (SDA=GPIO 8, SCL=GPIO 9) | Low data rate, Qwiic-compatible |

---

## Power Architecture

USB-C → bq25185 → 3.3V to ESP32 + peripherals. LCD gets raw LiPo voltage and uses Adafruit breakout's onboard boost to 5V. No external buck-boost needed.

---

## Firmware Decisions

- **Framework:** Arduino-ESP32 via PlatformIO (not Arduino IDE, not ESP-IDF)
- **Language:** C++ (Arduino-flavored). Python for offline analysis.
- **IMU sample rate:** 416 Hz (native ODR for LSM6DSOX)
- **IMU ranges:** ±16g accel, ±2000 dps gyro
- **IMU reading strategy:** FIFO with watermark interrupt, not polling
- **Dual-core usage:** sensor acquisition on Core 1, display/UI on Core 0
- **GPS protocol:** UBX binary via SparkFun u-blox library, not NMEA
- **GPS update rate:** 5 Hz
- **SD library:** SdFat (Bill Greiman), not stock SD library
- **Orientation filter:** complementary filter. Not Kalman (overkill), not Madgwick (unnecessary for v0). Upgrade to Madgwick later if needed.
- **Session lifecycle:** file = session. Start on button press (not motion-detect for v0). End on button press or idle timeout.
- **Log format:** binary with sync bytes and CRC8. Magic number 0x4B494C47 ('KILG'). See firmware_roadmap.md for full spec.

---

## Product & Algorithm Decisions

- **Breadboard-first approach:** Adafruit Perma-Proto half-size perfboard (soldered, not solderless), then PCB v1 once algorithms are validated. Same chips on both stages so firmware ports without changes.
- **Build philosophy:** "Build the data logger first, earn the metrics, then earn the price."
- **Algorithms are the hard part, not hardware.**
- **TSP (True Stroke Power) / corrected DPS:** demoted to offline-only for v1. Develop in Python against logged data. Too risky to claim on-device without validation.
- **On-water display:** maximum 1-2 real-time metrics. Cadence + corrected DPS. Momentum curve as a glanceable shape.
- **Post-session review is the actual product.** Device is the sensor; post-session view is the coach.
- **Stroke detection:** peak detection with threshold + hysteresis + refractory period. IMU accel-z as primary signal. Forward acceleration zero-crossing as exit marker (more robust than roll reversal due to hip-induced roll noise).
- **Side classification:** roll velocity sign, but acknowledge contamination from hip movement. Validate on real water data.
- **Force curve display:** boat-frame acceleration vs stroke phase (0-100%). Call it "effective drive force" not "paddle force." Add boat-distance-traveled view later using GPS velocity integration.
- **No ML/inference on device.** Hand-engineered features are the right tool. Narrative coaching belongs in a cloud API or phone app, not on the ESP32.
- **App architecture (future):** device logs to SD → transfer to phone/PC → analysis pipeline → visualization. No real-time device-to-phone connection during sessions. Device is self-contained on the water.

---

## Killer Features (competitive advantages over NK SpeedCoach)

1. **Surf mode** — catch success rate, catch latency, ride duration, top wave speed, linking rate. SpeedCoach is bad at this; downwind community is the niche-passionate market.
2. **Force/momentum curve** — like an erg's force curve, showing acceleration through the stroke cycle. Reveals catch sharpness, exit checking, peak position, fatigue patterns.
3. **Corrected DPS** — using glide phase as environmental baseline to isolate paddler force from wind/current/wave forces.
4. **Asymmetry detection** — roll amplitude, force-curve area, catch timing per side. NK's meters-per-stroke-side is a primitive proxy.
5. **Fatigue signature** — force curves narrow, asymmetry widens, cadence drifts. Single-number fatigue index.

NK can't respond quickly — they'd need a board redesign to add a gyroscope. The gyro is what enables features 1-5.

---

## Collaborators

- **Josh** — coach, numbers person. Will use post-session artifacts to coach remotely.
- **Ray** — paddler, technical. Validated momentum curve concept, suggested pitch as surf-detection axis, suggested ANT+/Garmin (deferred to phase 2-3).
- **Case collaborator** — developing custom waterproof enclosure.

---

## Deferred (explicitly out of scope for v0)

- WiFi upload / cloud sync — USB cable + SD card is fine
- BLE phone app
- ANT+ / Garmin Connect (phase 2-3)
- OTA firmware updates
- Real-time TSP on-device
- Multi-paddler / boat-share modes
- Kalman filtering (complementary filter is sufficient)
- Machine learning / on-device inference
- Phone app development (validate metrics in Jupyter first)

---

## Development Environment

- **OS:** Windows (two PCs in use)
- **Terminal:** Git Bash (not PowerShell, not WSL2)
- **Editor:** VSCode with PlatformIO IDE, C/C++, Python extensions
- **Version control:** Git + GitHub (private repo: Brzotto/KiloGlide)
- **Python:** 3.14 with numpy, matplotlib
- **AI tools:** Claude Code Desktop for code questions (not for vibe-coding)
- **Analysis:** Python scripts in tools/ and analysis/ directories. Spyder available as alternative to Jupyter.

---

## Order Waves

| Wave | Contents | Cost | Status |
|---|---|---|---|
| 1 | ESP32 DevKit, IMU breakout, perfboard, headers, hookup wire, USB-C | ~$60 | Hardware arrived |
| 2 | GPS, microSD breakout + cards | ~$45 | |
| 3 | Sharp LCD + Adafruit breakout, bq25185 charger, LiPo battery | ~$70 | |
| 4 | Buttons, LEDs, resistors, case, NK mount, VHB | ~$60 | |

Total: ~$235
