# Carrier Board Rev A — Schematic Netlist

Canonical net-by-net connection reference for the Rev A carrier schematic.
Pairs with `docs/carrier_board_rev_a.md` (design rationale) and `docs/harness.md`
(the breadboard harness this board replaces).

Status: all sheets drawn and reviewed — power rails, ESP32, IMU, microSD,
display, GPS, UI buttons, power latch, fuel gauge, BQS25185 boost/charger, and
test points/fiducials. Remaining work is verifying the open review items below,
then annotate and transfer to PCB.

## Net naming conventions

| Net | Meaning | Source |
|---|---|---|
| `VBATT` | Raw LiPo / charger BAT node (always live) | bq25185 BAT |
| `BOOST_5V` | 5 V boost output (switched by power latch) | bq25185 boost OUT |
| `3V3` | Switched 3.3 V (ESP32 onboard LDO output) | ESP32 `3V3` pins |
| `GND` | System ground (star point at ESP32 GND) | — |

Naming notes (lock these spellings — Altium treats any variant as a separate net):
- Battery rail is `VBATT` (not `VBAT`) — use on latch, fuel gauge, bq25185 sheets.
- Raw button node is `BTN_RAW` (not `BUTTON_RAW`).
- Latch memory node is `OFF_LATCH` (not `PWR_OFF_LATCH`) — one name end to end.
- SPI clocks are `SPI2_CLK` / `SPI3_CLK` (not `_SCK`).
- 5 V rail is `BOOST_5V` (not `SYS_5V`).
- Power-latch hold is `ESP32_PWR_HOLD`.
- Power/select button sense is `BTN_SEL` (diode-isolated — see latch section).

Power property worth remembering: `3V3` only exists while the boost is on, so
every 3.3 V peripheral is *switched* and dies when the latch cuts power. The
**only** load on `VBATT` is the fuel gauge.

## SPI source termination

Series-termination resistor footprints sit at the **driver** end of each line
(populate `0 Ω` now; swap to `22–33 Ω` only if a scope shows overshoot/ringing).

| Net | Driver | Series R location |
|---|---|---|
| `SPI2_CLK` | ESP32 (GPIO12) | at ESP32 |
| `SPI2_MOSI` | ESP32 (GPIO11) | at ESP32 |
| `SPI2_MISO` | IMU | at IMU |
| `SPI3_CLK` | ESP32 (GPIO6) | at ESP32 |
| `SPI3_MOSI` | ESP32 (GPIO7) | at ESP32 |
| `SPI3_MISO` | microSD | at microSD |
| all CS lines | ESP32 | none (slow/static) |

Critical-length rule of thumb: termination matters once one-way trace delay
(~150–180 ps/in on FR4) exceeds ~half the driver rise time (~2 ns) → ~3 in.
Carrier traces are shorter than that, so 0 Ω is expected to be fine. Keep the
SPI2 device stubs (branch to each CS device) short — that matters more than the
resistor on a shared bus.

## ESP32-S3 DevKitC-1 — J1 (pins 1–22)

| Pin | Symbol | Net | Notes |
|---:|---|---|---|
| 1 | 3V3_1 | `3V3` | LDO output, feeds peripherals |
| 2 | 3V3_2 | `3V3` | |
| 3 | RST | NC | optional reset test point |
| 4 | IO_4 | `IMU_INT1` | |
| 5 | IO_5 | `SD_CS` | |
| 6 | IO_6 | `SPI3_CLK` | series R at ESP32 |
| 7 | IO_7 | `SPI3_MOSI` | series R at ESP32 |
| 8 | IO_15 | `FG_ALRT` | optional fuel-gauge alert |
| 9 | IO_16 | `DISP_CS` | |
| 10 | IO_17 | `DISP_EIN` | no-op in software-VCOM mode; provision only |
| 11 | IO_18 | `ESP32_PWR_HOLD` | power latch hold |
| 12 | IO_8 | `I2C_SDA` | |
| 13 | IO_3 | NC | strapping pin |
| 14 | IO_46 | NC | strapping pin |
| 15 | IO_9 | `I2C_SCL` | |
| 16 | IO_10 | `IMU_CS` | |
| 17 | IO_11 | `SPI2_MOSI` | series R at ESP32 |
| 18 | IO_12 | `SPI2_CLK` | series R at ESP32 |
| 19 | IO_13 | `SPI2_MISO` | |
| 20 | IO_14 | `SPI3_MISO` | |
| 21 | 5V | `BOOST_5V` | boost feeds ESP32 here |
| 22 | GND_1 | `GND` | |

## ESP32-S3 DevKitC-1 — J3 (pins 23–44)

| Pin | Symbol | Net | Notes |
|---:|---|---|---|
| 23 | GND_2 | `GND` | |
| 24 | TX | `UART_TX` → TP | UART0 TX (GPIO43), debug |
| 25 | RX | `UART_RX` → TP | UART0 RX (GPIO44), debug |
| 26 | IO_1 | `BTN_SEL` | **diode-isolated sense via latch — not a plain button** |
| 27 | IO_2 | `BTN_UP` | |
| 28 | IO_42 | `SPARE_1` → TP | |
| 29 | IO_41 | `SPARE_2` → TP | |
| 30 | IO_40 | `BTN_DOWN` | |
| 31 | IO_39 | `BTN_BACK` | |
| 32 | IO_38 | NC | onboard RGB LED — add No-ERC marker |
| 33 | IO_37 | `SPARE_3` → TP | |
| 34 | IO_36 | `SPARE_4` → TP | |
| 35 | IO_35 | `SPARE_5` → TP | |
| 36 | IO_0 | NC | strapping/boot |
| 37 | IO_45 | NC | strapping |
| 38 | IO_48 | `SPARE_6` → TP | |
| 39 | IO_47 | `SPARE_7` → TP | |
| 40 | IO_21 | `SPARE_8` → TP | alt `ESP32_PWR_HOLD` if GPIO18 freed |
| 41 | IO_20 | NC | USB D+ |
| 42 | IO_19 | NC | USB D− |
| 43 | GND_3 | `GND` | |
| 44 | GND_4 | `GND` | |

Programming note: USB feeds the ESP32 directly through its own Schottky, so the
board can always be reflashed over USB even when the power latch is off.

## IMU — LSM6DSOX (Adafruit 4438)

Electrical header J?A (1×9):

| Pin | Name | Net | Notes |
|---:|---|---|---|
| 1 | VIN | `3V3` | |
| 2 | 3Vo | NC | regulator output, leave open |
| 3 | GND_1 | `GND` | |
| 4 | SCK | `SPI2_CLK` | |
| 5 | MOSI | `SPI2_MOSI` | |
| 6 | MISO | `SPI2_MISO` | series R at IMU |
| 7 | CS | `IMU_CS` | |
| 8 | INT1 | `IMU_INT1` | |
| 9 | INT2 | `IMU_INT2` → TP | unused by firmware |

Side header J?B (daisy-chain) + mechanical:

| Pin | Name | Net |
|---:|---|---|
| 10 | SCX | NC |
| 11 | SDX | NC |
| 12 | CS | NC |
| 13 | DO | NC |
| 14 | GND_2 | `GND` |
| M1/M2 | mounting | NC (footprint-only holes) |

Local decoupling: 10 µF + 100 nF on `3V3` at the IMU.

## microSD (Adafruit 4682) — dedicated SPI3, 1×9

| Pin | Name | Net | Notes |
|---:|---|---|---|
| 1 | 3V3 | `3V3` | use 3V pin, not 5V |
| 2 | GND | `GND` | |
| 3 | CLK | `SPI3_CLK` | |
| 4 | MISO | `SPI3_MISO` | series R at SD |
| 5 | MOSI | `SPI3_MOSI` | |
| 6 | CS | `SD_CS` | |
| 7 | D1 | NC | SDIO only |
| 8 | D2 | NC | SDIO only |
| 9 | DET | `SD_DET` → TP | card detect, optional |
| M1/M2 | mounting | NC |

Local decoupling: 10 µF + 100 nF on `3V3` at the SD breakout (write spikes
~100 mA).

## Sharp display (Adafruit 4694) — shares SPI2, 1×9

| Pin | Name | Net | Notes |
|---:|---|---|---|
| 1 | 5V0 | `BOOST_5V` | display supply — 5 V, not 3.3 V |
| 2 | 3V3 | NC | regulator output, do not use |
| 3 | GND | `GND` | |
| 4 | CLK | `SPI2_CLK` | |
| 5 | MOSI | `SPI2_MOSI` | no MISO — display is write-only |
| 6 | CS | `DISP_CS` | |
| 7 | EMD | `GND` | EXTMODE low = software VCOM mode |
| 8 | DISP | `3V3` via 0 Ω | enable; jumper lets you reroute to a GPIO |
| 9 | EIN | `DISP_EIN` → TP | external VCOM (unused in software mode) |

Decoupling: 10 µF + 100 nF must be on **`BOOST_5V`** (pin 1, the display's
supply), not on 3V3. Add a shared ~22 µF bulk on `BOOST_5V` near the
display/SD to absorb SD write spikes.

## GPS / Qwiic (SAM-M10Q via PRT-16766 connector)

| Pin | Name | Net |
|---:|---|---|
| 1 | GND | `GND` |
| 2 | VCC | `3V3` |
| 3 | SDA | `I2C_SDA` |
| 4 | SCL | `I2C_SCL` |
| MP1/MP2 | mounting | NC |

I²C pull-ups: 4.7 k on SDA/SCL to `3V3` populated **on the carrier**. The
SAM-M10Q module also carries its own pull-ups, so the effective value is ~2.3 k
when GPS is plugged in (in spec, on the stronger side). Carrier pull-ups are
kept populated so the on-board MAX17048 fuel gauge bus works even with no GPS
attached.

## Net classes (for PCB rules)

| Class | Members |
|---|---|
| `SPI2` | SPI2_CLK, SPI2_MOSI, SPI2_MISO |
| `SPI3` | SPI3_CLK, SPI3_MOSI, SPI3_MISO, SD_CS |
| `I2C` | I2C_SDA, I2C_SCL |
| `PWR` | BOOST_5V, 3V3, VBATT |

Net classes are a **PCB-side** concept — there is no "Design → Classes" in the
schematic editor. Two ways to create them:

1. **PCB editor (reliable):** after the PCB document exists and the netlist is
   imported, open **Design » Classes…** → Object Class Explorer → right-click
   **Net Classes → Add Class** → move member nets in. Then scope width/clearance
   rules in **Design » Rules** to each class.
2. **From schematic (optional):** place a **Net Class directive** on the bus
   wire via **Place » Directives** so the class travels with the design on
   import. Verify the exact entry name in your Altium version.

No length-matching needed at these speeds — the value is per-bus width/clearance
rules and clean selection during routing.

## UI buttons

Plain GPIO-to-ground, firmware `INPUT_PULLUP` (pressed reads LOW). No external
pull-ups or debounce.

| Button | Net | GPIO |
|---|---|---|
| Up | `BTN_UP` | 2 |
| Down | `BTN_DOWN` | 40 |
| Back / mark | `BTN_BACK` | 39 |
| Power / select | `BTN_SEL` | 1 — **via power latch, not a plain switch** |

`BTN_SEL` (GPIO1) is the diode-isolated sense node in the latch below, not a
fourth button-to-ground.

## Pushbutton power latch

Parts: BSS138DW dual NMOS (Q?A = M1, Q?B = M2), BAT54C dual Schottky (D?),
two 1 M, one 100 k, one 100 nF.

Function each FET must satisfy (wire by **function**, not pin position — see
review item below):

| FET | Gate | Source | Drain |
|---|---|---|---|
| M1 (Q?A) | `OFF_LATCH` | `GND` | `BOOST_EN` |
| M2 (Q?B) | `ESP32_PWR_HOLD` | `GND` | `OFF_LATCH` |

Reference BSS138DW-7-F (Diodes Inc) SOT-363 pinout — **verify against datasheet**:
pin 1=G1, 2=S1, 6=D1 (→ M1: G=1, S=2, D=6); pin 3=G2, 4=D2, 5=S2
(→ M2: G=3, S=5, D=4).

Diodes (BAT54C, common cathode = pin 3):
- D-a: anode `OFF_LATCH`, cathode `BTN_RAW`
- D-b: anode `BTN_SEL`, cathode `BTN_RAW`
- Common cathode (pin 3) = `BTN_RAW`; arrows point toward `BTN_RAW`.

Passives:
- 1 M `BTN_RAW` → `VBATT` (default-high button node)
- 1 M `OFF_LATCH` → `VBATT` (default-high → M1 on → boost off at rest)
- 100 k `ESP32_PWR_HOLD` → `GND` (M2 off while ESP32 boots / GPIO hi-Z)
- 100 nF `BTN_SEL` → `GND` (filters waterproof button lead)
- `BTN_RAW` → SPST power button → `GND`
- No external `BOOST_EN` pull-up — bq25185 board pulls EN internally
  (**verify**; add 100 k EN→`VBATT` if it floats)

Sequence: rest → `OFF_LATCH` high → M1 on → `BOOST_EN` low → 5 V off. Press →
`BTN_RAW` low → diode pulls `OFF_LATCH` low → M1 off → boost on → ESP32 boots →
drives `ESP32_PWR_HOLD` high → M2 holds `OFF_LATCH` low. Long-press → firmware
closes SD, drives `ESP32_PWR_HOLD` low → on release latch returns to off.

## Test points / fiducials

- Test points on: `I2C_SDA`, `I2C_SCL`, `SPI2_CLK/MOSI/MISO`, `SPI3_CLK/MOSI/MISO`,
  `IMU_CS`, `DISP_CS`, `SD_CS`, `VBATT`, `BOOST_5V`, `3V3`, `GND` (×2). Plus
  per-sheet TPs: `OFF_LATCH`, `ESP32_PWR_HOLD`, `DISP_EIN`, `IMU_INT2`, `SD_DET`,
  `UART_TX/RX`, `SPARE_1..8`.
- 3× 1 mm round fiducials (FD1–FD3) for pick-and-place — confirm 1 mm copper dot
  with ~2 mm mask clearance.
- Mounting holes: M3, isolated (NC). Consider 4 holes (currently 2) for rigidity
  given the plugged-in breakouts and IMU lever arm.

## MAX17048 fuel gauge

On `VBATT` (always powered, continuously coulomb-counting). Pin numbers per the
symbol — verify against datasheet.

| Pin | Name | Net |
|---:|---|---|
| 2 | CELL | `VBATT` |
| 3 | VDD | `VBATT` |
| 8 | SDA | `I2C_SDA` |
| 7 | SCL | `I2C_SCL` |
| 5 | ALRT | `FG_ALRT` (R3 100 k pull-up to `3V3`) |
| 6 | QSTRT | `GND` |
| 1 | CTG | `GND` |
| 4 | GND | `GND` |
| 9 | EP | `GND` |

- C3 100 nF on VDD→GND at the part.
- I²C pull-ups live on switched `3V3` (GPS sheet), so the gauge is not
  addressable while the system is off — by design, avoids back-powering the bus
  from `VBATT`.

## BQS25185 boost/charger (J1)

| Pin | Name | Net |
|---:|---|---|
| 1 | VIN | NC (DC input, OR'd with VUSB internally — unused on carrier) |
| 2 | VUSB | NC (charge via onboard USB-C) |
| 3 | D− | NC |
| 4 | D+ | NC |
| 5 | GND | `GND` |
| 6 | BAT | `VBATT` (battery terminal — LiPo / battery tap) |
| 7 | 5V | `BOOST_5V` (boost output, system rail) |
| 8 | EN | `BOOST_EN` (internal pull-up enables; latch M1 pulls low) |
| M1–M4 | mounting | NC |

- C1 10 µF + C2 100 nF bulk+bypass on `VBATT` at the BAT pin.
- `VBATT` is the BAT pin (pin 6), **not** VIN. VIN/VUSB/D± are inputs and stay
  NC — charging is via the board's onboard USB-C.

How the part works: integrated linear charger + 5 V boost with power path.
External power (VIN/VUSB) charges the cell on BAT via CC/CV; the boost steps the
cell up to 5 V on the output. It **charges and powers the load simultaneously**,
and charging is **independent of `EN`** — so the battery charges over USB even
with the system latched off (EN low / boost off).

Charge-status display decision (Rev A):
- The Sharp LCD is not bistable and needs the ESP32 driving it, so charge % can
  only be shown while the system is powered on. The ESP32 is **not** kept always
  on — that would defeat the latch's true-off and drain the battery.
- While off/charging, charge status comes from the charger board's **onboard
  CHG/STAT LED** (charging vs full). No ESP32 involved.
- Accurate charge % appears **instantly on power-up**: the MAX17048 is a
  voltage-model gauge powered from `VBATT`, so it tracks SOC through the entire
  off period — no warm-up, no lost state.
- Auto-wake-on-charge is **not available**: the charger board does not break out
  a STAT/PG pin, so there's no signal to detect USB-present and assert
  `BOOST_EN`. Charge status while off is the onboard CHG/STAT LED only. (Could
  revisit in Rev B with a different charger board if a charge screen is wanted.)

## Open review items

1. **Buttons:** UP and DOWN nets are mislabeled `BTN_BACK?` — rename to `BTN_UP`
   and `BTN_DOWN`.
2. **Latch (critical):** verify BSS138DW terminals are wired by function
   (gate=control, source=GND, drain=load) — looks assigned by pin position.
3. **Latch (critical):** unify `PWR_OFF_LATCH` / `OFF_LATCH` to one net name.
4. **Latch:** confirm BAT54C common cathode (pin 3) = `BTN_RAW`; confirm 100 nF
   is on `BTN_SEL`; confirm bq25185 EN has an internal pull-up.
5. **Naming:** standardize `VBATT` and `BTN_RAW` across all sheets.
6. Add No-ERC marker on IO_38 (pin 32, onboard RGB LED).
7. Confirm display 10 µF/100 nF are on `BOOST_5V`, not `3V3`; add ~22 µF bulk.
8. GPS pull-ups parallel the module's to ~2.3 k — intentional, keep populated.
9. SD CS test-point net must be `SD_CS` (not a new `SPI3_CS`).
10. **Fuel gauge:** confirm R3 100 k pull-up is on ALRT (pin 5), and QSTRT
    (pin 6) ties to GND — not swapped. A swap floats ALRT and can trigger
    spurious quick-start resets.
11. **Boost/charger:** `VBATT` corrected to BAT (pin 6); VIN/VUSB/D± are NC
    (charge via onboard USB-C). Confirm the LiPo lands on BAT (or the board's
    onboard JST, with BAT as the tapped battery node).
12. Run **Tools → Annotate Schematics** to replace all `R?`/`C?`/`J?`
    designators before transferring to PCB.
