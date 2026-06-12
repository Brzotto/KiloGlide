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
| GPS | SparkFun SAM-M10Q | Built-in patch antenna, I2C. Velocity accuracy 0.05 m/s (identical to M10Q) |
| Display (breadboard) | Adafruit SHARP Memory Display Breakout 2.7" 400x240 (PID 4694) | Sunlight readable, SPI, built-in boost converter. Adafruit's library written for this exact board |
| Display (production) | JDI LPM027M128C color MIP w/ frontlight | Adds color + dawn/dusk visibility, same SPI protocol family |
| Storage | Adafruit microSD breakout (PID 4682, NOT 254) | 3V-only matches ESP32 directly, supports SPI and SDIO |
| Power | Adafruit bq25185 USB/DC Charger (PID 5703) | Charging + load sharing + the 5 V system rail, USB-C. 3.3 V is the DevKitC's onboard LDO output — see Power Architecture |
| Battery | 2000 mAh LiPo with JST-PH | Updated from 1200 mAh. Target 4+ hour runtime |
| Buttons | 6mm tactile switches (PID 1489) | Inside case for v0 |
| Case | Custom waterproof case (in development by collaborator) | Replaces Pelican 1010. Keep Pelican as backup if custom case delays |
| Mounting | NK adjustable surface mount + 3D-printed dovetail backplate | Compatible with existing SpeedCoach brackets |

### Hardware changes from original BOM

- **GPS: SAM-M10Q.** Velocity accuracy identical (0.05 m/s), which is the spec that matters for sub-stroke analysis. 1.5m accuracy. Sparkfun I2C interface.
- **Display breakout: Kuzyatech → Adafruit (PID 4694).** Same display panel, same SPI interface, built-in boost converter. Better library support — Adafruit's library is written for this exact board.
- **Battery: 1200 mAh → 2000 mAh.** More runtime headroom. Still needs bench verification for 4+ hour target.
- **Case: Pelican 1010 → Custom waterproof case.** Collaborator developing custom case. Allows PCB-first design (case fits board, not board fits case). Keep Pelican as fallback.

---

## Communication Buses

| Bus | Devices | Pins | Notes |
|---|---|---|---|
| SPI2 (shared) | IMU + LCD | SCK=12, MOSI=11, MISO=13, IMU_CS=10 | Use beginTransaction() with correct settings before each device |
| SPI3 (dedicated) | microSD | SCK=6, MOSI=7, MISO=14, CS=5 | Dedicated — SD cards misbehave on shared buses |
| I2C | GPS | SDA=8, SCL=9 | Qwiic-compatible, 400 kHz |

---

## Power Architecture

Battery ↔ bq25185 charger (USB-C). The bq25185 board's regulated output is a **5 V boost rail**, gated by the power-button soft-latch (`BOOST_EN`). 5 V powers the Sharp display directly and feeds the ESP32-S3 DevKitC's `5V` pin; the DevKitC's **onboard LDO** derives the 3.3 V rail for the ESP32 + peripherals — so 3.3 V has a single source (the LDO), not an external regulator. The MAX17048 fuel gauge sits on the always-on battery node.

**Efficiency / future revision:** the 3.3 V rail runs battery → 5 V boost → linear LDO → 3.3 V, ~60% efficient (the LDO burns the 5→3.3 V drop). The display forces a 5 V rail and the bq board outputs only 5 V, so an *efficient* direct 3.3 V would need a battery→3.3 V **buck-boost** (a 1S LiPo swings both above and below 3.3 V). Accepted as-is for v0 to keep the board simple; the buck-boost is the candidate fix for a future revision — it would reclaim ~20% of 3.3 V-rail runtime against the 4-hour target and move the LDO heat out of the sealed case.

Rev A PCB carrier-board notes, including the MAX17048 fuel gauge, bq25185 boost
`EN` soft-latch, and JLCPCB assembly parts, live in
`docs/carrier_board_rev_a.md`.

### Power on/off — discrete soft-latch, not a controller IC

**Decision:** keep the discrete pushbutton soft-latch (parts/nets in the
*Pushbutton power latch* section of `docs/carrier_board_rev_a.md`); do **not**
add a dedicated pushbutton-controller IC.

- **Why not the IC:** LTC2954 / MAX16150 are functionally ideal but **$5–7 each
  at our quantities** — not worth it. A Renesas GreenPAK SLG46826 (~$1) matches
  them and is the upgrade path if a production run later wants a
  firmware-independent hardware force-off + reset ride-through, but it adds
  tooling (~$35 dev kit + learning curve). **Deferred.**
- **Power-off is off-on-release**, like the NK SpeedCoach — hold to shut down,
  release, it's off. A single-button soft-latch inherently cannot power off
  *while the button is held* (the held button pulls the latch into the on-state).
  This is expected behavior, not a limitation.
- **`OFF_LATCH` timing cap = 6.8 nF.** With the 1 MΩ pull-up, τ ≈ 6.8 ms → rail
  off ~3 ms after release. Power-on is independent of this cap (the button shorts
  it down in <1 µs). *Note: this is a separate cap from the 100 nF `ESP32_BUTTON`
  lead filter; the latch timing cap is currently missing from the carrier-board
  BOM and should be added.*
- **Hung-firmware safety = ESP32 Task Watchdog, no extra hardware.** The one
  failure the button cannot cover is firmware hanging without ever dropping
  `ESP32_HOLD`. The watchdog reboots a hung chip; on reboot `ESP32_HOLD` drops
  (GPIO → Hi-Z, its 100 kΩ pull-down wins) and the small `OFF_LATCH` cap lets the
  boost collapse during the ~200 ms reboot → device powers off, user restarts.
  Permanent stuck-on in the sealed case is therefore impossible.
- **Constraints:** `ESP32_HOLD` must use a GPIO that is **Hi-Z at reset**
  (GPIO 18 or 21 are fine — not strapping, no reset pull-up). Feed the watchdog
  only from the **real work loop**, never a timer/ISR, or a hang could go
  undetected.

Schematic/sim: `Circuit Simulation/Power Button.asc` (the sim uses generic `D`
diodes + `BSZ019N03LS` FETs — substitute BAT54C + BSS138DW models before trusting
absolute thresholds).

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
- **Log format:** binary with sync bytes and CRC8. Magic number 0x474C494B ('KILG' as little-endian ASCII). See `docs/log_format.md` for the full spec and `firmware/src/log_format.h` for the C structs.
- **Absolute time anchoring:** firmware writes a `KG_REC_TIME` record the first GPS PVT update with `getDateValid() && getTimeValid()`, then every 5 minutes for clock-drift detection. The first water test (session 37) had no TIME anchors because this feature came later; future sessions don't need GPS-speed cross-correlation to align with absolute time.
- **Fix-state events:** firmware emits `KG_EVT_GPS_FIX_FOUND` / `KG_EVT_GPS_FIX_LOST` on transitions across the 3D fix threshold. Lets the parser quickly find the first and last 3D-fix moments without scanning every GPS record.
- **Power-off watchdog (Wave 3 — documented, not yet implemented):** enable the ESP32 Task Watchdog (TWDT) with reset-on-timeout, and feed it only from the real sensor/work loop — never a timer or ISR (a stray feeder hides a hang). This is the hung-firmware safety for the discrete power latch: a hang reboots the chip, `ESP32_HOLD` drops, and (with the small `OFF_LATCH` cap) the unit powers off, so it cannot get stuck on inside the sealed case. Hardware interaction is documented under *Power Architecture → Power on/off* here and in the latch section of `docs/carrier_board_rev_a.md`. Tabled until Wave-3 power bring-up.

---

## Product & Algorithm Decisions

- **Breadboard-first approach:** Adafruit Perma-Proto half-size perfboard (soldered, not solderless), then PCB v1 once algorithms are validated. Same chips on both stages so firmware ports without changes.
- **Build philosophy:** "Build the data logger first, earn the metrics, then earn the price."
- **Algorithms are the hard part, not hardware.**
- **TSP (True Stroke Power) / corrected DPS:** demoted to offline-only for v1. Develop in Python against logged data. Too risky to claim on-device without validation.
- **On-water display:** maximum 1-2 real-time metrics. Cadence + corrected DPS. Momentum curve as a glanceable shape.
- **Post-session review is the actual product.** Device is the sensor; post-session view is the coach.
- **Stroke detection:** scipy.signal.find_peaks on a Butterworth-band-passed (0.5-3 Hz) forward acceleration channel, with both prominence and absolute-height thresholds + a refractory period derived from a max-cadence cap (~150 spm). Forward acceleration zero-crossing remains the exit marker.
- **Side classification (per-burst / per-lap, robust):** sign of the slow yaw envelope — band-pass yaw rate at 0.02-0.15 Hz, then sample at the catch or aggregate fraction-of-time-on-each-side over the lap. Reliable on OC1 in choppy water.
- **Side classification (per-stroke, marginal):** yaw-rate integral over `[catch, catch+300ms]`, with a hysteresis filter (k=3) to suppress isolated noise flips. Acceptable in clean conditions; noisy in chop. Roll rate (the original v0 plan) does NOT work for OC1 — the ama suppresses roll. See `analysis/session_37_status_and_next_session.md` for the diagnostic plots.
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
| 1 | ESP32 DevKit, IMU breakout, perfboard, headers, hookup wire, USB-C | ~$60 | Complete — IMU at 416 Hz via FIFO/IRQ |
| 2 | GPS, microSD breakout + cards | ~$45 | Complete — first water test 2026-05-21, session 37 |
| 3 | Sharp LCD + Adafruit breakout, bq25185 charger, LiPo battery | ~$70 | Not yet on bench |
| 4 | Buttons, LEDs, resistors, case, NK mount, VHB | ~$60 | Button + LED already wired (using whatever was in box) |

Total: ~$235
