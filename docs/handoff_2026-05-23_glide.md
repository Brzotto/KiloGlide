# KiloGlide — Conversation Handoff (Glide Analysis Session)

Written after the working session on 2026-05-23 that followed the original
session 37 pipeline build. The earlier handoff (`docs/handoff_2026-05-23.md`)
covers the project up through merging PR #18. This document covers what
happened next.

Read both handoffs in order, plus `CLAUDE.md`, before starting any new work.

---

## Branches / PRs created this session

- **PR (merged)**: `time-record-alignment` — pipeline now reads
  `KG_REC_TIME` records from the firmware and computes `kg_t0_utc` directly,
  falling back to GPS cross-correlation for older logs. Always runs xcorr as
  a sanity check.
- **PR (this session)**: `glide-analysis` (or similar) — within-stroke speed
  integration, two-tier glide metrics, phase detection diagnostic,
  coach-facing summary plot, and a session manifest for handling future data.

## What we built in this session

### 1. Within-stroke speed from IMU integration

The core insight: integrating forward accel across a stroke window gives a
416 Hz speed profile that the 5 Hz GPS can't deliver. Drift over seconds is
real but small within a ~1.2 s stroke. Anchor each window's mean to GPS for
absolute speed if needed; the *shape* and *slopes* are reliable regardless.

File: `analysis/glide_speed_test.py`.

### 2. Two-tier metric design

Glide metrics are split into two tiers:

| Tier 1 (IMU-only, current-independent, always available) | Tier 2 (GPS-enhanced) |
|---|---|
| Decay rate (m/s²) — slope of speed during glide | Absolute speed (m/s, mph) |
| Pull delta-v (m/s) — speed gained per pull | Speed retained ratio |
| Speed lost in glide (m/s) | DPS context |
| Pull / glide timing (s and % of cycle) | Course map, lap boundaries |
| Phase-normalized speed *shape* | |

The Tier 1 metrics use raw integration (no GPS anchoring). Since current
is a uniform flow that doesn't accelerate anything, IMU-integrated speed
changes are speed-through-water changes — **current-independent**. Slopes
and differences from integration are correct regardless of where you paddled.

Tier 2 metrics depend on speed over ground, so are current-contaminated.
We still report them as useful context, but the headline glide quality
number is the Tier 1 decay rate.

This matters for the user because they don't always paddle out-and-back —
sometimes loops or arbitrary shapes. Tier 1 metrics generalize across any
course geometry.

### 3. Phase detection using zero-crossings

Originally we used catch-to-catch (accel-peak to accel-peak) as the stroke
window, which made "pull duration" look like ~200 ms — that's only the time
from peak force to blade exit (second half of pull). The user correctly
flagged this as unrealistic.

Fixed by finding zero-crossings of forward accel within each window:
- First downward zero-crossing after window start = **blade exit**
- Last upward zero-crossing before window end = **blade entry**
- Full pull ≈ exit_offset + entry_offset (assumes symmetry around peak)

Result: pull durations ~0.4-0.5 s, glide ~0.7-0.85 s. Now physically sensible.

File: `analysis/glide_speed_test.py` (the `_find_zero_crossing` helper and
the updated `compute_glide_metrics`).

### 4. Pre-catch body motion analysis

The user noticed a small forward-accel "shoulder" right before each main
stroke peak in the phase diagnostic. After explaining that paddle is out
of water during this region, we concluded it's biomechanical: body weight
transferring through the seat as the paddler reaches forward, pauses at
full extension, then commits backward for the catch.

Averaged across hundreds of strokes per lap (`precatch_signature.py`), all
laps show the same underlying signature — the visible difference between
glass-water L13 and choppy L2/L3 wasn't a difference in body motion, just
a signal-to-noise difference. L2 actually has the deepest pre-catch trough
(-0.37 m/s²); L13 just has cleaner curves because chop isn't masking it.

This connects directly to Connected %: a "disconnected" stroke is body
weight transferring *before* the paddle catches water, creating the
characteristic bump-lull-drive force pattern.

### 5. Coach-facing summary plot

`analysis/coach_summary.py` produces a single PNG (`00_coach_summary.png`)
with:

1. Annotated stroke window showing pull/glide phases
2. Per-lap headline metrics (cadence, peak force, Connected %)
3. Fastest vs slowest cruise lap comparison with current estimate
4. Drag during glide across laps
5. Dynamic notes block with metric ranges + session narrative

Sport-familiar units: mph for speed, lbs for force, spm for cadence,
seconds for stroke timing. The narrative is pulled from `sessions.json`
per-session so it can be hand-curated; the numeric ranges are computed
from the lap data automatically.

### 6. Session manifest + config helper (Option A)

For multi-session support, added `analysis/data/sessions.json` (JSON for
stdlib compatibility — no PyYAML dependency) and `analysis/session_config.py`.
Scripts call `get_session_from_args()`, accept `--session N` CLI arg,
and resolve paths + metadata through the manifest.

To add a new session: append an entry to `sessions.json` with the KG binary
filename, paired Garmin TCX filename, date, conditions, etc.

Old session-37-specific scripts (correlate_kg_garmin.py and the family of
side/perg/lean scripts) still hardcode session 37 paths. This is fine —
they're historical analyses tied to that specific dataset. New scripts use
the manifest.

## Key things to know

### Current cost is estimated, not measured

The "current ≈ 1.2 mph" number in the session 37 narrative is derived from
`(speed_fast_lap - speed_slow_lap) / 2`, assuming equal effort both
directions. Effort isn't actually identical — L2 had ~10% more force than
L13. So 1.2 mph is an upper bound on current. For tighter estimates the
user can do a drift test (30 s of no paddling mid-lap, GPS speed = current)
or look up NOAA tidal current predictions.

The summary plot and narrative both flag this as an estimate now.

### Pull duration assumption: symmetric around the accel peak

`pull_duration_s = exit_offset_s + entry_offset_s` treats the first half of
the next pull as equal to the second half of this pull. Looking at the
averaged accel signature, this is a reasonable approximation, but it's not
exact. If a future analysis needs higher accuracy, track pull cycles by
matching consecutive blade_entry → blade_exit pairs (one full pull spans
two consecutive windows in the current scheme).

### Excluded laps

`EXCLUDE_LAPS = {14}` in `glide_speed_test.py`. L14 was the cool-down
paddle to the dock — very short dabs at ~64 spm, not full strokes. Don't
include it in cross-lap summaries.

### Body motion is universally present

Don't make the mistake of thinking the pre-catch wiggle is unique to any
particular lap. It's a fundamental property of the paddler's stroke
biomechanics. The interesting differences between laps live in *amplitude*,
*timing relative to catch*, and *how well it aligns with paddle force* —
not in whether it's present.

## Where the new files live

```
analysis/
  data/
    sessions.json                  ← session manifest (new)
    kg_000037.bin                  ← raw KG binary
    activity_22960598946.tcx       ← paired Garmin TCX
  session_config.py                ← manifest loader + --session CLI arg (new)
  glide_speed_test.py              ← within-stroke speed + two-tier glide metrics (new)
  precatch_signature.py            ← pre-catch body motion signature (new)
  coach_summary.py                 ← coach-facing single-page summary (new)
  connected_quick.py               ← quick Connected % lookup (new)
  correlate_kg_garmin.py           ← primary pipeline (unchanged structurally)
  stroke_phases.py / perg_plot.py / etc. — historical session-37 scripts
  plots/session_37/
    00_coach_summary.png           ← the headline plot for the coach
    30_glide_speed_integration.png ← initial exploration
    31_glide_tier1_imu.png         ← Tier 1 (current-independent) metrics
    32_glide_tier2_gps.png         ← Tier 2 (GPS-enhanced) metrics
    33_phase_detection.png         ← phase detection diagnostic
    34_precatch_signature.png      ← averaged accel signature

docs/
  README_analysis.md               ← how to use the pipeline (new)
  handoff_2026-05-23.md            ← previous handoff
  handoff_2026-05-23_glide.md      ← this document
```

## Open threads / what's next

1. **Validate TIME-record alignment with real data** — the firmware now
   emits KG_REC_TIME on first GPS valid-time and every 5 min. Session 37
   pre-dates this firmware. The next session will be the first test of the
   new alignment path (Method: `time_record`). Sanity check: the
   TIME-vs-xcorr delta should be near zero.

2. **Add new session to manifest** — when the next on-water test comes in:
   - Copy `kg_000XYZ.bin` and `activity_NNN.tcx` into `analysis/data/`
   - Add a new entry to `sessions.json` with metadata
   - Run `python analysis/coach_summary.py --session XYZ` and the other
     scripts the same way
   - Write the session narrative in the manifest based on what you saw

3. **Compare TIME-record alignment vs xcorr** quantitatively on a session
   that has both signals. Once we trust TIME records, can drop the
   GPS-speed cross-correlation as a fallback.

4. **Drift test for current estimate** — next session, deliberately stop
   paddling for 30 s in the middle of a lap. The GPS speed during that
   window is the true current speed. Compare against the 1.2 mph estimate.

5. **Per-stroke L/R classifier** — yaw + lap-demeaned lateral as features
   (still pending from before).

6. **Wave 3** — display + power not started.

7. **"Glide smoothness" as a metric** — quantify how much the actual glide
   deceleration deviates from a clean linear decay. Smoother = body holding
   still during recovery; bumpy = body shifting and adding drag. Mentioned
   but not implemented.

## Collaboration style reminder

User is hardware-strong, learning firmware/Python/C++. CLAUDE.md says:
"Don't write entire modules without being asked. Prefer teaching over
generating." When the user asks exploratory questions, propose 2-3 sentences
with a recommendation and the main tradeoff *before* writing code or
building infra. They'll redirect or approve.

When the user explicitly authorizes ("lets do it"), it's fine to work
through multiple phases — but keep checking in at meaningful decision points.
