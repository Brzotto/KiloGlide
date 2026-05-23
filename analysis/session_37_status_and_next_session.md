# Session 37 — status assessment & what to capture next time

Written 2026-05-23 after a working pass through `kg_000037.bin` paired with the Garmin TCX.

---

## How we're doing with this one dataset

### What's solid

| Capability | Status | Notes |
|---|---|---|
| Binary log parsing | Production-grade | Zero CRC errors, zero resync bytes, clean SESSION_END across all 4751 s. The format and Python parser are working. |
| KG ↔ Garmin time alignment | Reliable | Normalized GPS-speed cross-correlation gives Pearson r = 0.94, offset = 503 s. Works without any absolute time anchor in the firmware. |
| Body-frame IMU axes | Auto-discovered | Up = raw +Z, Forward = raw +Y for the "forward of seat" mount. Gravity recovers to 10.02 m/s². Method generalizes to any mount. |
| Stroke detection | Bullet-proof | Band-pass + scipy `find_peaks`. Forward-accel peaks are far above the noise floor. Tuned thresholds work across cruise, sprint, and cool-down. |
| Per-stroke characterization | Working | Peak force, impulse, peak position, distance per stroke. Numbers match plausible OC1 ranges. |
| Per-lap summary | Working | Cadence, mean speed, peak force, DPS, side-time fraction, side switches. All in the report table. |
| Lap-level side bias | Working | Slow yaw envelope (0.02-0.15 Hz band-pass) reliably tells which side dominates a lap. Lap 6 reads as 100% L; Lap 7 as 37% L (mostly R); Lap 8 as 67% L. |
| Lean angle | Visible | Boat sits 5-15° leaned LEFT (toward ama) during paddling. Matches what you described. |
| Current quantification | Confirmed | Same effort (205 N strong miles vs 187 N current mile) drove ~37% speed difference. The 1 m/s loss is the water. |

### What's marginal

| Capability | Issue | Path forward |
|---|---|---|
| Per-stroke L/R labels | Noisy in cruise/choppy water. Individual stroke yaw integrals get noise-flipped. | Use lap-level envelope (already swapped in). For per-stroke labels we need a multi-feature classifier (yaw + demeaned lateral + maybe heading derivative). |
| Lap 14 cool-down stroke counting | Slightly over-counts because of waves and intermittent strokes. | Add a "is paddling?" gate before counting — e.g., require local accel variance above a floor. |
| Absolute force calibration | Numbers depend on system-mass estimate (85 kg used). 10% mass error → 10% force error. | Calibrate against a known-resistance pull (e.g., towing a small drogue with known drag). Or just accept it as relative. |
| Lateral-axis dynamics | Biased by gravity from the persistent left lean (~+2 m/s² DC offset). | Subtract lean projection: `a_y_clean = a_y - g·sin(estimated_lean)`. Or just always demean per-lap. |

### What's missing (in this dataset)

| Missing | Why it matters |
|---|---|
| Absolute UTC time anchor | KG header `start_unix_us = 0`. We rely on GPS-cross-correlation. Cheap to fix — write a TIME record when GPS first locks. |
| USER_MARK events | No way to mark "test starts here" or "this is the surf attempt" without GPS-context reasoning. |
| SpeedCoach data | You mentioned you have one but it's not exported yet. Cross-checking stroke rate independently would tighten everything. |
| Cleaner stationary calibration | The "stationary" window I used at session start may have had small motion. A deliberate 30 s still recording would give a perfect gravity vector. |
| Photo of the mount orientation | Would let us cross-check the auto-detected axes against the physical truth. |

---

## What to capture in your next on-water session

A handful of small additions would make the *next* dataset much more analyzable. Roughly in order of value:

### Highest value — do these

1. **30 s of stillness at session start.** Once the device is mounted on the canoe at the dock, sit still for 30 s before paddling. Gives a clean gravity vector for axis discovery. The cleaner the gravity, the cleaner everything that follows.
2. **Photo of the IMU mount on the canoe.** Even a phone snap. Captures exactly which direction the USB port faces, which way is "up" on the breadboard, and where it sits relative to the paddler. Lets us validate the auto-detected axes against ground truth.
3. **A deliberate L/R calibration burst.** Like you did in laps 6-8, but with a clear known structure. E.g., 10 strokes on the LEFT only, pause, 10 strokes on the RIGHT only, pause, 10 strokes alternating. Write down what you did. This becomes the labeled training data for tuning the L/R classifier.
4. **NK SpeedCoach export.** If you can pull a CSV of stroke rate + split times from the SpeedCoach, that's independent ground truth for stroke detection — directly comparable to our cadence-per-lap numbers.

### Medium value — nice to have

5. **Variety in conditions.** Try to capture both a calm-water session and a choppy session. Helps separate "what's the stroke" from "what's the wave noise."
6. **Variety in effort.** Within one session, deliberately do: 5 min easy / 5 min steady / 5 min hard / 5 min easy. Gives a clean way to look at cadence-vs-effort, fatigue, etc.
7. **Lap markers on the Garmin keyed to events.** Press the lap button at distinct moments — start of test piece, surf attempt, technique trial. Each Garmin lap then has a known meaning.
8. **Write the TIME record once GPS locks.** Firmware change — small. Once it's there we never need to cross-correlate alignments again, and we can talk in absolute UTC throughout the codebase.

### Low priority — when you feel like it

9. **A second IMU breakout location.** Mount one forward of seat (current) and one at the seat / between feet. Two simultaneous IMUs let us separate boat motion from local-to-mount motion (the bow sees more yaw-induced motion than the seat does).
10. **Wind/current/water-temp log.** Just a note on your phone for the day. "Light SW wind, 0.5-1 m/s flood tide, glass." Helps interpret edge cases.
11. **Heart-rate or HRV stream from another device.** Garmin TCX has HR but at coarse resolution. A chest strap + ANT+ would be cleaner.

### What to add to the firmware before next time

A short developer wishlist for the firmware side, all small:

- Write a TIME record at session start once GPS locks (and again every ~5 min for drift detection).
- Wire up a button → emit `USER_MARK` events.
- Maybe a second event type for "calibration window started/stopped" so we know where to find the still segment automatically.
- Verify the IMU isn't saturating during hard strokes — peak we saw was 9 m/s² forward, well below 156 m/s² saturation at ±16 g, so headroom is fine.

---

## The full visualization catalog (in `analysis/plots/session_37/`)

Plots produced from this session, in roughly the order they were built:

| File | What it shows |
|---|---|
| `01_alignment_diagnostic.png` | Cross-correlation Pearson r vs candidate offset. Single sharp peak at 503 s, r=0.94. |
| `01_gps_track.png` | KG and Garmin GPS tracks overlaid on a lat/lon grid. Launch right (L14), turnaround left (L5-9). |
| `01_speed_overlay.png` | Both speed signals on a common UTC axis with Garmin lap boundaries marked. |
| `02_axis_verification.png` | Rotated forward / lateral / up accel vs GPS speed in the cruise window. |
| `03_burst_strokes_wide.png` | Laps 5-9 context with all detected strokes marked. |
| `03_burst_strokes_zoom.png` | Per-lap zoom on bursts 6, 7, 8 with yaw rate (the side discriminator) on the right. |
| `04_per_lap_summary.png` | 2×3 grid of cadence / speed / peak force / DPS / L% / switches across all laps. |
| `04_lap_compare_force.png` | Mean force-vs-stroke-phase for strong miles vs slow current mile, with metric bars. |
| `05_stroke_phases.png` | Three stroke cycles annotated with PULL (blue) and GLIDE (yellow) phases. |
| `05_quality_strip.png` | 30 s of strokes color-coded by impulse quartile. |
| `05_best_vs_worst.png` | Top-10 vs bottom-10 stroke force curves overlaid + impulse distribution. |
| `06_side_signal_histograms.png` | Per-stroke peak/integral histograms across 5 candidate signals, colored by lap. |
| `06_side_signal_scatter.png` | 2D scatter pairs (yaw vs lateral, yaw vs roll, lateral vs roll). |
| `06_side_timeline.png` | Per-stroke yaw + lat bars within each burst lap. |
| `07_lap_side_timeline.png` | Per-stroke yaw across cruise laps 2/3/9/13 with switch markers. |
| `07_run_length_histogram.png` | Distribution of same-side run lengths. |
| `07_side_autocorrelation.png` | Side-sign autocorrelation showing periodicity. |
| `08_raw_yaw_window.png` | Raw + band-passed + slow-envelope yaw in a 60 s mid-mile window. |
| `08_window_sweep.png` | Per-stroke yaw at 4 different post-catch sampling windows. |
| `09_side_blocks.png` | Combined yaw+lateral smoothed signal showing block structure across 4 laps. |
| `10_side_envelope_lap2.png` | Lap 2 forward accel + yaw + envelope + per-stroke labels. |
| `10_side_envelope_summary.png` | Per-stroke envelope-at-catch labels across 4 laps. |
| `11_side_rhythm_diagnostics.png` | Run-length histograms + cleaned timelines + autocorrelations across 4 laps. |
| `12_burst_sides.png` | Per-burst slow-envelope side analysis for laps 6, 7, 8. |
| `13_lean_over_session.png` | Boat lean angle (atan2 of low-passed accel) + stroke-band lateral RMS. |
| `14_choppiness_spectrum.png` | Power spectra across all motion axes with frequency bands labeled. |
| `15_distance_per_stroke.png` | Per-stroke DPS scatter + per-lap mean/median DPS bars. |
| `16_heart_rate.png` | Heart rate from Garmin TCX with KG GPS speed for context. |
| `17_stroke_evolution.png` | Average force curve per quarter of the session (Q1=warmup → Q4=cool-down). |
| `18_cadence_speed_dps.png` | Cadence vs speed and cadence vs DPS scatter — the efficiency tradeoff. |
| `19_summary_dashboard.png` | One-page overview with headline numbers, force curves, and per-lap bars. |

---

## Bottom line

You collected enough good data on the first water test to validate the entire pipeline end-to-end: parse, time-align, axis-detect, stroke-detect, characterize, summarize, and visualize. The few rough edges (per-stroke L/R, cool-down detection, lateral bias from lean) are well-understood and have known fixes.

For the next session: 30 s of stillness at start, a photo of the mount, and a deliberate L/R calibration burst will resolve most of the remaining ambiguity. If you can also pull the SpeedCoach data afterward, we have an independent ground truth for stroke count and cadence.
