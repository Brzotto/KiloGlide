# KiloGlide

Open-water paddling coach for canoe/SUP downwind and distance training.

*Kilo* is Hawaiian for observer — the patient, expert watching that
traditional navigators used to read the stars, the sea, and the wind.
KiloGlide observes your glide and tells you, with discipline, what it sees.

ESP32-S3 + LSM6DSOX IMU + u-blox GPS + Sharp memory LCD,
in a Pelican 1010 case.

## Status

Early hardware bring-up. See `docs/firmware_roadmap.md` for the staged plan.

## Documents

- [`docs/decisions.md`](docs/decisions.md) — running log of project decisions
- [`docs/data_insights.md`](docs/data_insights.md) — data ideas and design principles
- [`docs/firmware_roadmap.md`](docs/firmware_roadmap.md) — staged firmware development plan
- [`docs/developer_setup.md`](docs/developer_setup.md) — dev environment setup
- [`docs/math_primer.md`](docs/math_primer.md) — math primer for the algorithms
- [`docs/log_format.md`](docs/log_format.md) — binary session log spec (TBD)

## Building

Requires PlatformIO. From the repo root:

```bash
pio run                      # build
pio run -t upload            # build + flash
pio device monitor           # serial console
```

## Repo layout

- `firmware/` — ESP32 firmware (PlatformIO project)
- `tools/` — Python utilities (log parser, fake data generator)
- `analysis/` — Jupyter notebooks for algorithm development
- `docs/` — design and decision documents
- `sessions/` — raw water-test logs (gitignored)

## License

TBD.
