# Carrier Board Rev A — Schematic Review (2026-06-17)

Independent review of the Rev A carrier schematic as drawn (buttons + power
latch, boost + charger + fuel gauge, ESP32-S3 DevKitC, and the IMU / SD / GPS /
display / thermistor breakout headers). Canonical design intent lives in
[`carrier_board_rev_a.md`](carrier_board_rev_a.md) and
[`decisions.md`](decisions.md); the running to-do is in
[`next_steps.md`](next_steps.md). This file is the **review record**: what was
checked, what was confirmed safe, and the decisions taken on the open items so
they are not re-litigated later.

**Method.** Each subsystem was reviewed against the part datasheets (BSS138DW,
BAT54C, MAX17048, TPS61023/bq25185, Sharp LS027 panel + Adafruit 4694 breakout,
SAM-M10Q, ESP32-S3), and the higher-impact findings were re-checked
adversarially against the primary datasheet before being kept. Several alarming
first-pass findings did **not** survive that check — those are recorded under
"Verified safe" so the cleared reasoning is preserved.

**Net-name note.** The schematic sheets label the latch nets `BTN_RAW`,
`BTN_SEL`, `OFF_LATCH`, `BOOST_EN`, and `ESP32_PWR_HOLD`. These map to the
canonical doc's `BUTTON_RAW`, `ESP32_BUTTON`, `OFF_LATCH`, boost `EN`, and
`ESP32_HOLD` respectively.

## Outcome

No critical defects. The soft power-latch topology is correct as drawn, the SPI
buses and I²C addressing are clean, and the ESP32-S3 pin map respects the
strapping / octal-PSRAM / USB constraints. The real work is **one firmware item**
plus a few **DNP hedges** and silkscreen cleanup. Most first-pass "issues" were
either already handled in the canonical doc or cleared on datasheet review.

## Action items

| # | Item | Where | Status |
|---|------|-------|--------|
| 1 | Assert `ESP32_PWR_HOLD` (GPIO 18) high as the **first action in `setup()`** — without it the latch cannot self-hold and the unit only stays on while the button is physically held | firmware | tracked in `next_steps.md`; not yet implemented |
| 2 | Tie MAX17048 `CTG` (datasheet-required) and `QSTRT` to GND | schematic | already specified in `carrier_board_rev_a.md`; confirm in layout |
| 3 | Add a **100 kΩ DNP pulldown on `DISP_CS` (GPIO 16)** and confirm series `R13` does **not** pull CS toward 3.3 V | schematic | added to `carrier_board_rev_a.md`; populate only if bring-up shows display corruption |
| 4 | Keep GPS I²C pull-ups (`R10`/`R11`) **DNP**; rely on the SAM-M10Q breakout's onboard 2.2 kΩ pair | schematic | done (DNP) |
| 5 | Rename `BQS25185` → `bq25185` on silk/BOM | schematic | silk cleanup |
| 6 | Verify the BSS138DW **symbol pin numbers** match the SOT-363 footprint (gate ↔ control net, source ↔ GND) | schematic/library | added note to `carrier_board_rev_a.md` |

Test points on the latch nets (`OFF_LATCH`, `BOOST_EN`, `ESP32_PWR_HOLD`,
`BTN_RAW`) already exist on the board — no action.

## Verified safe (investigated; no change needed)

These were raised as potential problems and then cleared. Recorded so they are
not re-opened.

- **BSS138DW gate/source "swap."** First pass flagged a possible gate↔source
  swap that would leave both latch FETs permanently off. The Diodes **DS30203**
  datasheet does not publish a numbered pin table — only a die map
  (`D2 G1 S1 / S2 G2 D1`) — and the authoritative numbered pinout
  (pin1=S1, pin2=G1, pin3=D2, pin4=S2, pin5=G2, pin6=D1) makes the **as-drawn
  wiring a correct common-source switch** (source→GND, gate→control net,
  drain→load). The latch works as drawn. The only residual is a library hygiene
  check (action item 6): confirm the symbol's pin numbers match the footprint,
  since SOT-363 dual-NMOS numbering varies between sources.

- **MAX17048 I²C level vs. cell-referenced VDD.** `VDD` sits on the cell
  (`VBATT`, 3.0–4.2 V) while SDA/SCL/ALRT pull up to switched 3.3 V. This is in
  spec: those pins are rated **−0.3 V to +6 V, independent of VDD**, so the bus
  may sit above VDD near end-of-charge without violating abs-max, and the input
  logic-high threshold (~0.7 × VDD ≈ 2.94 V at a 4.2 V cell) is still cleared by
  the 3.3 V bus. Powering `VDD` from the cell is the **intended** choice — it
  keeps the gauge alive through power-off so state-of-charge tracking is
  continuous (powering VDD from switched 3.3 V would reset the model every boot).

- **Brown-out / latch oscillation near empty.** The 5 V stage is a TPS61023
  whose *falling* UVLO is ~0.4–0.5 V — far below any Li-ion discharge voltage —
  so the boost does not brown out at end-of-charge. If the 3.3 V rail ever does
  collapse, the latch fails **OFF cleanly** (`ESP32_PWR_HOLD` → Hi-Z → R12 pulls
  Q1B off → R7 pulls `OFF_LATCH` high → Q1A on → `BOOST_EN` low) with no restart
  path until the next button press. No relaxation oscillation.

- **Battery charging.** The Adafruit bq25185 board charges the cell through its
  **own onboard USB-C** connector (5.1 kΩ CC resistors); leaving the carrier's
  `VUSB`/`D±` header pins unconnected is correct. The only consequence is
  mechanical: **the enclosure must expose that USB-C jack** for charging.

- **USB-VBUS vs. BOOST_5V at the DevKit 5 V pin.** The DevKitC feeds its 5 V rail
  from USB-VBUS through a series Schottky, so USB and the 5.0 V boost are
  effectively diode-OR'd: the boost wins and USB simply reverse-biases off. No
  source fight, no part stress. The only effect is that USB does **not** power
  the system during programming — see "Programming behavior" below.

- **Sharp display `DISP` pin.** Left at direct-connect/NC, which matches Adafruit's
  recommended 5-wire hookup — the 4694 breakout drives `DISP` high onboard. Do
  **not** add a pulldown on `DISP` (it would blank the panel). The pulldown in
  action item 3 is on **CS**, a different pin.

## Notes by subsystem

### Power latch
Topology confirmed: default `OFF_LATCH` high (R7) → Q1A on → `BOOST_EN` low →
boost off. Button press pulls `BTN_RAW` low → BAT54C steers `OFF_LATCH` low →
Q1A off → boost on → ESP32 boots → firmware drives `ESP32_PWR_HOLD` high → Q1B
holds `OFF_LATCH` low. The 6.8 nF cap on `OFF_LATCH` is the off-on-release timing
cap (τ ≈ 6.8 ms with the 1 MΩ pull-up), **not** a boot-hold reservoir — hence
action item 1: firmware must grab `ESP32_PWR_HOLD` before the user releases the
button. Pressing through a single BAT54C drop pulls `OFF_LATCH` to only
~0.15–0.25 V at the ~4 µA set by R7, comfortably below the BSS138 V_GS(th) — Q1A
turns off reliably.

### Fuel gauge (MAX17048)
`CTG` and `QSTRT` to GND (item 2). `VDD` on the cell, I²C to switched 3.3 V — in
spec and intended (see "Verified safe"). 100 nF VDD bypass and exposed-pad-to-GND
per the canonical doc.

### Display (Sharp 2.7", Adafruit 4694)
5 V from the boost rail; SPI2 shared with the IMU (separate CS, no MISO from the
panel). The panel's CS is **active-high**, so it must idle low while the IMU
transacts; `DISP_CS` (GPIO 16) floats during the reset/boot window before
firmware runs. Mitigation: 100 kΩ DNP pulldown on `DISP_CS` plus firmware
driving GPIO 16 low early (item 3). Confirm `R13` is a series element or a
pulldown, **never** a pull-up to 3.3 V (that would jam the panel selected).
`EXTMODE` = GND (software VCOM) is correct; keep periodic VCOM refresh in firmware.

### I²C bus (GPS + fuel gauge)
Shared `I2C_SDA`/`SCL` (GPIO 8/9). No address conflict (SAM-M10Q 0x42,
MAX17048 0x36). Pull-ups: carrier `R10`/`R11` are DNP; the SAM-M10Q breakout's
onboard 2.2 kΩ `I2CPUR` pair (closed by default) is the single pull-up set
(item 4). Note the bus therefore depends on the GPS module being populated — the
fuel gauge brings no pull-ups of its own.

### ESP32-S3 pin map
Strapping pins (IO0/IO3/IO45/IO46), native USB (IO19/IO20), and octal-PSRAM pins
(IO33–37 on N8R8) are all left clear/NC. `BATT_TEMP` is on GPIO 2 = ADC1_CH1
(Wi-Fi-immune). `ESP32_PWR_HOLD` on GPIO 18 is non-strapping and Hi-Z at reset,
so the R12 100 kΩ pulldown holds it low through boot — required for the watchdog
power-off.

### Programming behavior (battery + USB connected)
You can flash with the battery and USB both connected. The ESP32 is powered from
**USB** (VBUS → DevKit Schottky → 5 V rail → onboard 3.3 V LDO), independent of
the boost, so erase/flash always works regardless of latch state. The boost
follows the **latch**, not USB: when esptool resets the chip into download mode,
firmware stops running, `ESP32_PWR_HOLD` drops low, and the boost shuts off mid-
flash (unless the power button is physically held). This is harmless — only the
display (the sole `BOOST_5V` load) power-cycles; the MCU and the 3.3 V
peripherals stay alive on USB. After flashing, the chip resets, firmware
re-asserts `ESP32_PWR_HOLD`, and the boost returns.

### Protection (deferred to production)
No reverse-polarity / TVS / fuse on `VBATT`. Acceptable for Rev A: the LiPo pack's
integral PCM covers short/over-discharge and the JST-PH is keyed. Revisit
reverse-polarity (series P-FET / Schottky) and connector ESD for the production
respin.
