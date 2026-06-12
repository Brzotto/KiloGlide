# KiloGlide — Next Steps

_Last updated: 2026-06-09. Forward plan coming out of the carrier-board Rev A
power + thermistor design. Canonical detail lives in `docs/decisions.md` and
`docs/carrier_board_rev_a.md`; this is the running to-do, not a spec — keep it
trimmed as items land._

## Now: finish & fab Carrier Board Rev A

Schematic reviewed, pinout locked (see `docs/carrier_board_rev_a.md`).

- [ ] Lay out the Rev A PCB from the reviewed schematic.
- [ ] Confirm `ESP32_HOLD` on GPIO 18 stays **Hi-Z at reset** (no pull-up) — the
      watchdog power-off depends on it.
- [ ] Keep **GPIO 33–37 clear** (octal PSRAM on N8R8) and strapping/USB pins NC.
- [ ] Order via JLCPCB; verify the "verify JLC stock" parts (6.8 nF latch cap,
      `S2B-PH-SM4` thermistor connector, 10 k bias resistor).

## Next: Wave 3 bench bring-up (display + power)

### Power
- [ ] Bring up the bq25185 5 V boost + soft-latch: button-on → firmware-hold →
      off-on-release. Measure the release→off delay with the 6.8 nF cap (~3 ms).
- [ ] Verify the 3.3 V rail (DevKitC onboard LDO from 5 V): current budget under
      full load (ESP32 + IMU + GPS + SD + display logic) and LDO temperature in
      the closed case.
- [ ] **Implement the Task Watchdog** (documented, not yet written): TWDT,
      reset-on-timeout, fed only from the real sensor/work loop. Confirm a forced
      hang reboots and powers the unit off.
- [ ] Assert `ESP32_HOLD` as the first action in `setup()`; measure the required
      button-hold-to-boot time.

### Fuel gauge (MAX17048)
- [ ] I²C bring-up; read `VCELL` and `SOC`; sanity-check `SOC` against a known
      charge level. Confirm hibernate behavior and standby draw.

### Display (Sharp 2.7")
- [ ] Bring up on SPI2 (shared with IMU, `beginTransaction`), CS = GPIO 16, 5 V
      from the boost rail. Periodic VCOM refresh in firmware.

## Deferred (reserved on the board, not v0)

- **Battery temperature compensation (fuel-gauge `RCOMP`).** `R14` is DNP, NTC is
  off-board. Enable later: populate `R14`, bond the Tewa `TT7-10KC8-3` to the
  cell via `J_TEMP`, then firmware ADC1 (GPIO 2) → resistance → °C (Tewa "C8"
  curve — pull coefficients from the datasheet) → write `RCOMP` periodically.
  Treat near-0 / near-full-scale reads as "no sensor → default RCOMP."
- **Battery → 3.3 V buck-boost (future revision).** Replaces the 5 V-boost → LDO
  path; ~90% vs ~60% on the 3.3 V rail (~20% runtime back, less case heat).
  See `docs/decisions.md` → Power Architecture.

## Open from earlier phases (not power-related)

- Per-stroke L/R classification refinement (yaw + lap-demeaned lateral) — see
  `analysis/session_37_status_and_next_session.md`.
- On-water connection-usefulness A/B test — see
  `docs/connection_test_protocol.md`.
