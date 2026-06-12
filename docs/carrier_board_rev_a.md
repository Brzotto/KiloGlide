# Carrier Board Rev A Notes

Design notes for the first PCB carrier board. This board replaces the
breadboard/perfboard harness with headers for the existing breakouts plus a few
small assembled support parts.

## Schematic style

- Draw the installed breakout boards as header/module symbols, not as the bare
  ICs, unless the bare IC is actually assembled on this PCB.
- Use honest footprints for what is built on Rev A: headers, connectors, fuel
  gauge, latch parts, resistors, capacitors, and test pads.
- Keep future cost-down bare-chip versions on a separate sheet/project or mark
  them clearly as not populated.

## Breakout connectors

Use socket headers for the breakouts so Rev A can be assembled and serviced like
the current bench harness. Normal-height Sullins sockets are fine for most
modules. Use a low-profile Samtec socket for the IMU electrical header to reduce
mechanical leverage and board motion.

| Module | Carrier connector | Part | Source | Notes |
|---|---|---|---|---|
| ESP32-S3 DevKitC-1 | Two 1x22 female sockets | Sullins PPPC221LFBN-RC | Digi-Key | DevKit plugs into two separate 0.1 inch rows; set row spacing from the actual board/mechanical drawing |
| Sharp 2.7 inch display breakout | 1x9 female socket | Sullins PPPC091LFBN-RC | Digi-Key | Standard-height socket is fine |
| microSD breakout, Adafruit PID 4682 | 1x9 female socket | Sullins PPPC091LFBN-RC | Digi-Key | Actual board in hand uses 1x9 |
| LSM6DSOX IMU electrical side | 1x9 low-profile female socket | Samtec SLW-109-01-*-S | Digi-Key or JLCPCB if stocked | Low-profile socket reduces IMU wobble; plating suffix is flexible |
| LSM6DSOX IMU mechanical side | 1x5 socket or matching mechanical support | Samtec SLW-105-01-*-S or equivalent | Digi-Key or JLCPCB if stocked | Mechanical support only; pads NC; height must match electrical side |
| bq25185 5 V boost board | 1x8 female socket | Sullins PPPC081LFBN-RC | Digi-Key | Carry only needed nets such as 5V, GND, VBAT/BAT, EN, and optional status/test nets |
| GPS / Qwiic I2C | 4-pin JST-SH/Qwiic vertical connector | XYECONN XY-BM04B-SRSS-TB, JLC C51940129 | JLCPCB | JLC-assembled Qwiic-compatible connector; verify footprint and pin order |

For socketed breakouts, use matching standoff height if mounting screws are
used. The IMU should be mechanically rigid but not bent by mismatched header and
standoff heights. The IMU socket should be the Samtec `SLW` low-profile family,
not `SSW`; `SSW` is the normal-height 8.5 mm class and does not reduce the IMU
lever arm. Normal 0.1 inch square male header soldered to the IMU breakout is
expected to mate with the `SLW` socket; install the longer male pins down into
the carrier socket.

JLCPCB assembly equivalents/fallbacks:

| Module/use | Preferred hand-solder part | JLCPCB assembly candidate | Notes |
|---|---|---|---|
| ESP32-S3 DevKitC-1, 1x22 sockets | Sullins PPPC221LFBN-RC | XUNPU FH2.54-09-22PZD, C7500786 | 1x22, 2.54 mm, 8.5 mm height, wave soldering |
| Standard 1x9 sockets for Sharp/microSD | Sullins PPPC091LFBN-RC | HCTL PM254-1-09-Z-8.5, C2897372 | 1x9, 2.54 mm, 8.5 mm height, wave soldering |
| IMU low-profile 1x9 electrical socket | Samtec SLW-109-01-*-S | Samtec SLW-109-01-*-S if stocked by JLCPCB | Preferred Rev A choice; any plating suffix is acceptable if geometry matches |
| IMU low-profile 1x9 fallback | Samtec SLW-109-01-*-S | Samtec SLW-110-01-G-S, C3321070 | 1x10 low-profile fallback; use pins 1-9 and mark pin 10 NC |
| IMU normal-height 1x9 fallback | Sullins PPPC091LFBN-RC | HCTL PM254-1-09-Z-8.5, C2897372 | Electrically works but is not low-profile; use only with matching-height support |
| IMU 1x5 mechanical support | Samtec SLW-105-01-*-S or matching support | Matching low-profile 1x5 if stocked by JLCPCB | Use only if height matches the IMU electrical support strategy; pads NC |
| bq25185 1x8 socket | Sullins PPPC081LFBN-RC | CONNFLY DS1023-01-1x8SF11, C47355683 | 1x8, 2.54 mm, through-hole/wave soldering |
| Alternate bq25185 1x8 socket | Sullins PPPC081LFBN-RC | BOOMELE 2.54-1x8P female, C27438 | Very high stock; verify footprint before use |
| GPS/Qwiic connector | SparkFun PRT-16766 or JST BM04B-SRSS-TB | XYECONN XY-BM04B-SRSS-TB, C51940129 | SMT vertical JST-SH/Qwiic-compatible |
| Right-angle UI button candidate | TBD after enclosure mockup | XUNPU TS-1002N-04526, C455128 | PTH right-angle SPST tact, 2.6 N; verify actuator height/feel |

## Fuel gauge

Use a MAX17048 single-cell LiPo fuel gauge on the existing I2C bus.

| Function | Part | JLCPCB part | Package | Notes |
|---|---|---|---|---|
| Fuel gauge | MAX17048G+T10 | C2682616 | DFN-8-EP 2x2 mm | I2C SoC gauge, no sense resistor |

Connections:

| Pin/net | Connection |
|---|---|
| CELL, VDD | LiPo battery positive / charger BAT node |
| GND | System ground |
| SDA | I2C SDA, GPIO 8 |
| SCL | I2C SCL, GPIO 9 |
| ALRT | Optional ESP32 GPIO, suggested GPIO 47 (a digital pin — keep it off the ADC pins) |
| QSTRT | GND for Rev A unless firmware-controlled quick-start is needed later |
| CTG | GND |

Add a local 100 nF capacitor from VDD to GND. I2C pull-up footprints are useful,
but mark them DNI if the GPS/Qwiic breakout pull-ups are already installed.
For the planned Rev A harness, the I2C pull-ups can live on the GPS Qwiic
breakout a few inches away from the main PCB. That is fine for this bus length;
leave optional local footprints on the carrier board as cheap insurance, but do
not populate duplicate pull-ups unless the bus needs them.

External parts and layout notes:

| Item | Value / connection | Notes |
|---|---|---|
| VDD bypass capacitor | 100 nF from VDD to GND | Place close to the MAX17048 pins |
| I2C pull-ups | GPS/Qwiic board pull-ups to switched 3.3 V | Do not pull SDA/SCL up to VBAT |
| Optional local I2C pull-ups | 4.7k or 10k to switched 3.3 V, DNI by default | Populate only if the remote pull-ups are removed or bus edges are poor |
| ALRT pull-up | 100k to switched 3.3 V, optional/DNI | Needed only if using the alert interrupt |
| QSTRT | Tie to GND for Rev A | Can be driven later if hardware quick-start is needed |
| CTG | Tie to GND | Datasheet-required connection |
| Exposed pad | GND | Use vias/stitching if the footprint provides a pad |

## Optional battery temperature sense (DNP, for fuel-gauge temp-comp)

The MAX17048 has no temperature sensor; its `RCOMP` temperature compensation is a
firmware feature that needs a *battery* temperature reading. v0 ships without
temp-comp (see `docs/decisions.md`), but leave a populate-if-needed divider so
adding it later is a firmware-only change, not a respin.

**Sense the cell, not the board.** A board-mounted SMD bead reads PCB / in-case
temperature — skewed by nearby self-heating (boost, ESP32) and lagging the actual
cell under load or in sun. For meaningful `RCOMP` comp the element must be in
thermal contact with the LiPo, so the NTC is an off-board *leaded* part bonded to
the cell; only the bias resistor and filter cap live on the carrier board.

Circuit (board parts **DNP**; the NTC + connector are added with the battery):

```text
switched 3.3V ── R_bias 10k ──┬── TEMP_SENSE (to GPIO 2 / ADC1_CH1)
                              ├── C 100nF ── GND
                              └──[J_TEMP 2-pin]── NTC 10k (on battery) ── GND
```

- **NTC:** 10 kΩ-at-25 °C *leaded* thermistor bonded to the cell face. A part like
  Tewa `TT7-10KC8-3` is the right *type* — a 10 k epoxy bead on insulated leads.
  Before committing, confirm: the B-value / R–T curve (firmware needs it for the
  conversion — Tewa's "C8" curve coefficients must match the table in code), lead
  length reaches the board, and 10 k ± a few % (tolerance is not critical for
  coarse `RCOMP`).
- **Connector `J_TEMP`:** 2-pin JST-PH (same family as your battery connector) or
  solder pads at the board edge for the thermistor leads. Polarity-agnostic — it is
  a two-terminal resistor.
- **Mounting:** Kapton tape or a dab of thermal adhesive to the flat face of the
  pouch, away from the tab/weld area; give the leads a little strain relief.
- **R_bias (`R14`) / filter cap (`C12`):** 10 kΩ 1 % and the shared 100 nF,
  board-mounted. **`R14` is DNP on Rev A**, so the divider is dormant — no
  quiescent draw, and `BATT_TEMP` sits near 0 V. Enable temp-comp later by
  populating `R14` and attaching the NTC via `J_TEMP`; firmware should treat a
  near-0 *or* near-full-scale `BATT_TEMP` as "no valid sensor → default RCOMP."
  Matching R_bias to the NTC's R25 centers sensitivity near room temperature.
- **Power from the *switched* 3.3 V**, not the always-on battery node — the divider
  draws ~165 µA only while the unit is on (when temperature is read anyway) and
  nothing when off.
- **ADC pin: GPIO 2 (`ADC1_CH1`).** ADC1 is never blocked by the Wi-Fi radio, so
  this holds up if Wi-Fi is added later. To free GPIO 2 the *Up/next* button moves
  to GPIO 41 (a digital JTAG pin, like the other nav buttons) and `ALRT` sits on
  GPIO 47 — the lone analog signal gets the Wi-Fi-immune ADC1 pin; digital signals
  take plain GPIOs. (A small I²C temp sensor, TMP102-class, on the existing bus is
  an alternative that needs no ADC pin at all.)

BOM additions (board parts **DNP** on Rev A; the NTC + connector are added with
the battery):

| Function | Part | JLCPCB part | Package | Notes |
|---|---|---|---|---|
| Battery NTC | Tewa TT7-10KC8-3 or equiv. | n/a — off-board | leaded bead | 10 k; confirm β / R–T curve for firmware |
| Thermistor connector `J_TEMP` | JST `S2B-PH-SM4-TB(LF)(SN)` | verify JLC stock | 2-pin PH, SMT side-entry | Same PH family as the battery; polarity-agnostic |
| NTC bias resistor `R14` | 10 kΩ 1 % | 0603WAF1002T5E, verify | 0603 | **DNP** on Rev A; board-mounted; matches NTC R25 |
| NTC filter cap | reuse 100 nF (C1591) | C1591 | 0603 | Board-mounted; shared 0603 part |

## Pushbutton power latch

Use the Adafruit bq25185 5 V boost board `EN` pin rather than switching the
high-current system rail. The latch only controls the boost enable signal.

Desired behavior:

1. Off state: latch pulls boost `EN` low, disabling 5 V.
2. Press the waterproof SPST momentary button: latch releases `EN`, boost turns
   on, ESP32 boots.
3. ESP32 immediately drives `ESP32_HOLD` high, holding the latch on after the
   button is released.
4. Firmware detects a long press, stops logging, flushes/closes the SD file,
   then drives `ESP32_HOLD` low.
5. On button release, latch returns to off and pulls `EN` low.

Recommended nets:

| Net | Purpose |
|---|---|
| BUTTON_RAW | Battery-side button node, pulled up to VBAT and pulled low by the SPST button |
| OFF_LATCH | Latch memory node; high means force boost off, low means allow boost on |
| ESP32_HOLD | ESP32 output that keeps the unit powered after boot |
| ESP32_BUTTON | Safe 3.3 V button sense input to firmware |

Use two Schottky diodes so the ESP32 can read the button without exposing a GPIO
to VBAT:

| Diode | Anode | Cathode / stripe |
|---|---|---|
| D1 | OFF_LATCH | BUTTON_RAW |
| D2 | ESP32_BUTTON | BUTTON_RAW |

Use `BAT54C` as the default dual-diode part. It is a common-cathode dual
Schottky in SOT-23. `BAS40-05` and `BAS70-05` are acceptable SOT-23
common-cathode substitutes. Tiny SOT-723 parts such as `NSR30CM3T5G` are
electrically suitable but are less friendly for inspection/rework on Rev A.

Critical pin mapping for the common-cathode SOT-23 part:

| Package pin | Function | Net |
|---:|---|---|
| 1 | Anode 1 | OFF_LATCH or ESP32_BUTTON |
| 2 | Anode 2 | ESP32_BUTTON or OFF_LATCH |
| 3 | Common cathode | BUTTON_RAW |

Pins 1 and 2 may swap because both are diode anodes. Pin 3 must connect to
`BUTTON_RAW`. If reusing a schematic symbol from another package, verify the
symbol pin numbers against the selected SOT-23 footprint before ordering.

Add a 100 nF capacitor from `ESP32_BUTTON` to GND near the ESP32/button-sense
input. This filters a few-inch waterproof button lead while firmware still does
normal debounce and long-press timing.

Add a separate 6.8 nF capacitor from `OFF_LATCH` to GND — the latch timing
capacitor, not the same as the `ESP32_BUTTON` filter above. With the 1 MΩ
`OFF_LATCH` pull-up it sets the turn-off slope: τ ≈ 6.8 ms, so boost `EN` crosses
the FET threshold ~3 ms after the button is released (off-on-release, like an NK
SpeedCoach). Power-on is independent of this cap — the pressed button discharges
it in well under a microsecond. Keep it small; a large value would both slow the
deliberate turn-off and defeat the watchdog power-off below.

**Power-off when firmware hangs.** The button can only switch the unit off when
firmware is alive to drop `ESP32_HOLD`. For the hung case (sealed enclosure, no
accessible switch), rely on the ESP32 Task Watchdog rather than extra hardware: a
hang reboots the chip, `ESP32_HOLD` momentarily goes Hi-Z, its 100 kΩ pull-down
wins, the latch releases, and the small `OFF_LATCH` cap lets the boost collapse
during the ~200 ms reboot — so a hang ends in a clean power-off and the user
restarts. For this to work, `ESP32_HOLD` must be on a GPIO that is Hi-Z at reset
(no internal pull-up), and firmware must feed the watchdog only from the real
work loop, never a timer/ISR. Rationale and the rejected pushbutton-IC
alternatives are in `docs/decisions.md`.

## Buttons

Use four board-mounted right-angle buttons for the product UI. Prefer
through-hole/PTH right-angle tact switches for Rev A because they are stronger
and easier to rework than SMT switches. SMT buttons are acceptable later if the
case mechanically supports the actuator and limits side load on the solder
joints.

Button wiring should stay simple:

```text
GPIO ---- button ---- GND
```

Use `INPUT_PULLUP` in firmware, so pressed reads `LOW`. Firmware debounce and
long-press detection are sufficient; no external debounce circuit is required.

Suggested assignment:

| Button | GPIO | Notes |
|---|---:|---|
| Power / select | 1 | Existing firmware button input; use diode-isolated sense path if sharing with the power latch |
| Up / next | 2 | Plain GPIO-to-ground button |
| Down / previous | 40 | Plain GPIO-to-ground button |
| Back / mark | 39 | Plain GPIO-to-ground button |

Keep `ESP32_HOLD` separate from the button inputs; suggested `ESP32_HOLD` pins
are GPIO 18 or GPIO 21. Both are Hi-Z at reset (not strapping, no default
pull-up), which the watchdog power-off relies on — keep that property if you
reassign the pin.

## Sharp memory display

Rev A uses the Adafruit 2.7 inch Sharp Memory Display breakout (PID 4694).
Power the breakout from the system 5 V boost rail through its `VIN` pin, and
drive the SPI/control pins from ESP32 3.3 V GPIO. Do not power the rest of the
system from the display breakout's `3v3` pin.

Recommended connector signals:

| Signal | Connection |
|---|---|
| GND | System ground |
| VIN | System 5 V boost output |
| CLK | SPI2 SCK, GPIO 12 |
| DI | SPI2 MOSI, GPIO 11 |
| CS | Suggested GPIO 16 |
| DISP | Optional display enable/control or spare |
| EXTCOMIN / EMD | Optional spare/test pad for external VCOM refresh |

The screen can be rotated in software with the Adafruit GFX `setRotation()`
API. Mounting the breakout 180 degrees is electrically fine, but the physical
board is visually directional: the display flex, larger lower bezel/chin, and
Adafruit label are on one edge. Keep the natural orientation if the full
breakout face is visible; rotating the board is fine if the enclosure/window
hides the PCB and only the active display area is visible.

The Sharp panel needs periodic VCOM inversion. For Rev A, handle this in
firmware by calling the display refresh path periodically, even if the image is
static. Leave an optional EXTCOMIN/EMD pad or connector pin as an escape hatch,
but do not spend a dedicated GPIO on external refresh unless testing shows it
is needed.

## Suggested JLCPCB parts

Verify stock and assembly class before ordering; these were selected as
JLC-friendly parts during Rev A planning.

| Function | Part | JLCPCB part | Package | Notes |
|---|---|---|---|---|
| Fuel gauge | MAX17048G+T10 | C2682616 | DFN-8-EP 2x2 mm | Single-cell LiPo SoC gauge, I2C, no sense resistor |
| Dual NMOS for latch | BSS138DW | C5362112 | SOT-363 | M1 pulls boost EN low; M2 pulls OFF_LATCH low |
| Alternate dual NMOS | 2N7002DW-7-F | C83571 | SOT-363 | Name-brand alternate |
| Dual Schottky, common cathode | BAT54C | C916424 | SOT-23 | Common cathode goes to BUTTON_RAW |
| Alternate dual Schottky | BAT54C | C408388 | SOT-23 | Also suitable |
| Alternate dual Schottky | BAS40-05 | C5189796 | SOT-23 | Common-cathode substitute for BAT54C |
| 100k resistor | 0603WAF1003T5E | C25803 | 0603 | Good for FET gate pulldown and EN pullup/pulldown as needed |
| 1M resistor | 0603WAF1004T5E | C22935 | 0603 | Good for low-current BUTTON_RAW/OFF_LATCH pullup |
| 100 nF capacitor | CL10B104KB8NNNC | C1591 | 0603 | X7R, 50 V, button filter and decoupling |
| 6.8 nF capacitor | CL10B682KB8NNNC | verify JLC stock | 0603 | `OFF_LATCH` latch timing cap; ~3 ms off-on-release with the 1 MΩ pull-up. X7R fine, C0G for tighter tolerance |
| Qwiic connector | XY-BM04B-SRSS-TB | C51940129 | SMD, 1 mm pitch | 4-pin vertical JST-SH/Qwiic-compatible connector |

## ESP32 pin reservations

Current firmware uses:

| GPIO | Use |
|---:|---|
| 1 | User button |
| 4 | IMU INT1 |
| 5 | microSD CS |
| 6 | microSD SCK |
| 7 | microSD MOSI |
| 8 | I2C SDA |
| 9 | I2C SCL |
| 10 | IMU CS |
| 11 | SPI2 MOSI |
| 12 | SPI2 SCK |
| 13 | SPI2 MISO |
| 14 | microSD MISO |
| 38 | Onboard RGB LED on current DevKitC revision |

Suggested new Rev A uses:

| GPIO | Suggested use |
|---:|---|
| 15 | Spare (ADC2_CH4) |
| 47 | Fuel gauge ALRT, optional (digital — moved off the ADC pin) |
| 16 | Display CS |
| 17 | Display EXTCOMIN / display refresh, if needed |
| 18 or 21 | ESP32_HOLD output for power latch |
| 2 | Battery temp-sense (`TEMP_SENSE`), ADC1_CH1, optional/DNP |
| 41 | Button: Up / next (moved off ADC1 to free GPIO 2 for `TEMP_SENSE`) |
| 39 | Button: Back / mark |
| 40 | Button: Down / previous |

Avoid GPIO 0, 3, 45, and 46 for normal peripherals because they are ESP32-S3
strapping pins. Avoid GPIO 19 and 20 because they are native USB. Avoid GPIO 33–37
— they are consumed by the in-package octal PSRAM on the N8R8 (broken out on the
DevKitC header but not usable). Leave GPIO 43 and 44 available for UART0 debug
unless there is a strong reason to use them.
