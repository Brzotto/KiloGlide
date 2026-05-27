# KiloGlide Analysis Pipeline — How to Run a New Session

Quick reference for processing the data after each on-water session.

## What you have after a session

After paddling, you'll have:
1. `kg_000XYZ.bin` — KG binary log from the microSD card
2. `activity_NNN.tcx` — Garmin TCX export (optional but recommended)
3. Possibly an NK SpeedCoach export (not yet wired in)

## Step 1 — Copy the raw data

Drop both files into `analysis/data/`:

```
analysis/data/
  kg_000038.bin              ← from microSD
  activity_22999999999.tcx   ← from Garmin Connect
```

## Step 2 — Add a session entry to the manifest

Edit `analysis/data/sessions.json`. Append a new session under `"sessions"`:

```json
"38": {
  "date": "2026-06-XX",
  "kg_file": "kg_000038.bin",
  "garmin_tcx": "activity_22999999999.tcx",
  "nk_speedcoach": null,
  "location": "Alameda Bay, CA",
  "boat": "OC1",
  "system_mass_kg": 85,
  "mount": "breadboard forward of seat",
  "conditions": "describe wind / chop / current here",
  "notes": "anything unusual about this session",
  "compare_laps": [],
  "summary_narrative": []
}
```

Optionally update `"default_session"` to the new number so scripts default to it.

The `summary_narrative` can be empty at first and filled in after you look at
the plots. It's a list of strings — each one becomes a numbered paragraph in
the coach summary.

The `compare_laps` field is optional and controls which laps the
diagnostic / overlay plots highlight. Format:

```json
"compare_laps": [
  {"idx": 2,  "label": "L2 (strong current)", "color": "firebrick"},
  {"idx": 13, "label": "L13 (glass water)",   "color": "steelblue"}
]
```

If you leave it as `[]`, scripts auto-pick the fastest cruise, slowest
cruise, and longest cruise lap with default colors. Set it explicitly to
call out specific laps (e.g. a drift test, an L/R burst, a hard interval).
Up to 3 laps is recommended for readability.

## Step 3 — Run the scripts

All scripts accept `--session N` and default to the manifest's default.

```bash
# Headline coach summary (the one you share)
python analysis/coach_summary.py --session 38

# Detailed glide metrics with two-tier breakdown
python analysis/glide_speed_test.py --session 38

# Pre-catch body motion signature
python analysis/precatch_signature.py --session 38

# Quick Connected % printout for spot-checking
python analysis/connected_quick.py --session 38
```

Plots land in `analysis/plots/session_38/` — directory is created automatically.

## Step 4 — Write the narrative

After looking at the generated plots, edit `sessions.json` and fill in the
`summary_narrative` list with 2-4 bullet-style observations. These render as
the "WHAT WE LEARNED THIS SESSION" section in the coach summary. Re-run
`coach_summary.py` and the narrative appears.

## What each script does

### `coach_summary.py` → `00_coach_summary.png`
Single page for sharing with a coach. Sport-familiar units (mph, lbs).
Auto-picks the longest cruise lap for the annotated-stroke panel and the
fastest/slowest cruise laps for the conditions-cost comparison.

### `glide_speed_test.py` → `31_glide_tier1_imu.png`, `32_glide_tier2_gps.png`, `33_phase_detection.png`
Two-tier glide analysis. Tier 1 metrics (decay rate, pull/glide duration,
pull delta-v) are computed from IMU integration alone and are
**current-independent** — they generalize across any course shape.
Tier 2 metrics (absolute speed, retained ratio) need GPS anchoring.

Phase detection diagnostic shows individual strokes with blade-entry and
blade-exit zero-crossings marked, so you can verify the timing measurements
visually.

### `precatch_signature.py` → `34_precatch_signature.png`
Averages forward accel across hundreds of strokes per lap to reveal the
universal pre-catch body motion signature. Useful for understanding why
your stroke looks different in chop vs glass water (spoiler: the signature
is the same, but chop adds noise that masks it on individual strokes).

### `connected_quick.py` (stdout only)
One-shot printout of Connected % for a few key laps. No plot, just numbers.

## Key metrics to track session-over-session

These metrics are reliable comparisons even across different courses /
conditions:

| Metric | What it tells you | Better = |
|---|---|---|
| **Decay rate (m/s²)** | Drag deceleration during glide. Pure hull+body drag. | Smaller magnitude (closer to zero) |
| **Pull delta-v (m/s)** | Speed gained per stroke. Stroke power. | Larger |
| **Connected %** | Fraction of strokes with clean catch-to-drive | Higher |
| **Pull duration (s)** | Time blade is in water per stroke | Stable across cadences (good) |
| **Glide duration (s)** | Time blade is out, between strokes | Shrinks at high cadence (normal) |

These are GPS-dependent (current-contaminated), useful but harder to compare:

| Metric | Caveat |
|---|---|
| Mean GPS speed | Includes current — compare only on similar courses |
| Distance per stroke | Includes current |
| Speed retained | Includes current |

## Things to do during a session that help the analysis

These are *nice-to-have*, not required:

- **Drift test**: Stop paddling for ~30 s mid-session to measure current
  directly. GPS speed during the drift = true current speed.
- **L/R bursts**: A short segment of "10 strokes left, pause, 10 strokes
  right" with the side called out as a button press would label the data
  for per-stroke L/R classification.
- **Photo of the mount**: helps validate the auto-detected IMU axes.

## Troubleshooting

**Script can't find data file**: Check `sessions.json` filenames match
exactly what's in `analysis/data/`. The script resolves paths relative to
the analysis directory.

**Alignment uses xcorr instead of TIME records**: Your KG firmware predates
2026-05-23. After that date, the firmware writes `KG_REC_TIME` and alignment
should automatically use `Method: time_record`.

**Plot folder doesn't exist**: Scripts auto-create `analysis/plots/session_N/`
when they save. If you see a permission error, check write access to the
analysis directory.

**Connected % is weirdly high or low**: Cadence is the biggest driver
(r = -0.56 in session 37). Then chop (r = -0.47). Force has essentially no
correlation. Compare Connected % within similar cadence + conditions, not
across very different ones.

**Pull duration looks too short**: If you see ~200 ms instead of ~400-500 ms,
you may be looking at an older version of the script. The fix landed in the
glide-analysis PR (session 2026-05-23). The corrected metric uses
zero-crossings around the accel peak to measure full blade-in-water time.

## See also

- `CLAUDE.md` — top-level project status
- `docs/handoff_2026-05-23.md` — handoff from the session 37 pipeline build
- `docs/handoff_2026-05-23_glide.md` — handoff from the glide-analysis session
- `docs/log_format.md` — binary log format spec
- `analysis/session_37_report.md` — auto-generated report for session 37
- `analysis/session_37_status_and_next_session.md` — human notes from session 37
