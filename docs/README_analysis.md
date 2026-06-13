# KiloGlide Analysis Pipeline — How to Run a New Session

Quick reference for processing the data after each on-water session.

## Fast path — which question, which command (read this first)

The pipeline is session-aware, so you rarely need to re-explore. Add the session
to the manifest (Step 2), then map the question straight to a tool. This table is
the point: don't re-derive which metric answers what — look here.

| Question | Command / metric | Notes |
|---|---|---|
| Is the log OK? (corruption, duration) | `python tools/kg_parse.py analysis/data/kg_000NNN.bin` | Clean = 0 CRC / 0 resync / 0 underflow. A missing `SESSION_END` is harmless — duration falls back to IMU timestamps. |
| What happened when? (structure, build-ups) | `python analysis/session_timeline.py --session N` (`--tmin/--tmax` to zoom) | Speed / cadence / force / side+heel on one time axis with Garmin lap markers; near-stationary laps shaded. Build-ups show as ramps. |
| Sprint build-up inside a piece | session_timeline zoom, or within-lap 1st-third vs last-third of force/cadence/speed | A real build-up ramps all three *within* the lap; a flat piece is a warmup/cruise. |
| Coach one-pager | `python analysis/coach_summary.py --session N` | mph / lbs units. |
| Leg drive (vs not) | `python analysis/perg_plot.py --session N --distance L6,L7,L8,L9` | WORK PER STROKE = area under force-vs-distance. NOT visible in peak force / impulse / connection / side-bias. Compare MATCHED pairs (same side, adjacent in time); blind whole-lap scans wash it out. |
| Flying the ama / balance | heel angle (atan2 of low-passed lateral vs up accel) + roll-rate RMS per lap | Ama-flying = sustained heel off the floating baseline + roll-rate RMS ~2-3x cruise, usually near-stationary. Track: higher heel held at *lower* roll-RMS = steadier. |
| Which side (L / R)? | lap yaw envelope (`left_time_fraction`) | KNOWN-LIMITED: reads ~50% in glassy cruise water; per-stroke L/R is noise-dominated. Don't trust it to auto-pair sides — get the side order from the paddler. |
| Speed + cadence match vs SpeedCoach | `python analysis/speedcoach_report.py --session N` | The DATA QUALITY block is the standard per-session report (see below): speed `r`, per-lap mean-speed agreement (mph), per-lap cadence agreement (spm), KG/SC stroke-count %. SpeedCoach (boat-mounted) is the right reference; the Garmin *watch* over-counts strokes. |

Efficiency notes:
- The KG log is large (~40 MB, ~2M IMU samples); every script reloads + re-aligns +
  re-detects axes (~15-20 s each). Don't loop scripts needlessly.
- Alignment is automatic: TIME records (firmware >= 2026-05-23) give exact
  alignment; cross-correlation is the fallback and also the validation `r`.
- Record confirmed lap roles in the manifest `notes` so the next session (or agent)
  doesn't re-derive the structure. Save the Garmin + SpeedCoach files into
  `analysis/data/` — they're gitignored as user data (only `sessions.json` is
  tracked), but the manifest + scripts that reference them are committed, so the
  analysis stays reproducible whenever you have the files.

## What you have after a session

After paddling, you'll have:
1. `kg_000XYZ.bin` — KG binary log from the microSD card
2. A Garmin activity export — either `activity_NNN.tcx` **or** the native
   `NNN_ACTIVITY.fit` from Garmin Connect (optional but recommended). The
   pipeline reads both; `.fit` is what Garmin downloads by default.
3. Optionally an NK SpeedCoach CSV export (see the SpeedCoach section below)

Python dependencies: `numpy`, `scipy`, `matplotlib`, and `fitparse`
(`pip install fitparse`, only needed when the Garmin export is a `.fit`).

## Step 1 — Copy the raw data

Drop both files into `analysis/data/`:

```
analysis/data/
  kg_000038.bin              ← from microSD
  activity_22999999999.tcx   ← from Garmin Connect (TCX export)
  23129109922_ACTIVITY.fit   ← or the native FIT download
```

## Step 2 — Add a session entry to the manifest

Edit `analysis/data/sessions.json`. Append a new session under `"sessions"`:

```json
"38": {
  "date": "2026-06-XX",
  "kg_file": "kg_000038.bin",
  "garmin_tcx": "activity_22999999999.tcx",
  "garmin_fit": null,
  "nk_speedcoach": null,
  "location": "Alameda Bay, CA",
  "boat": "OC1",
  "system_mass_kg": 85,
  "mount": "breadboard forward of seat",
  "conditions": "describe wind / chop / current here",
  "notes": "anything unusual about this session",
  "compare_laps": [],
  "exclude_laps": [],
  "adaptive_strokes": false,
  "gap_fill_strokes": false,
  "summary_narrative": []
}
```

Use `garmin_tcx` **or** `garmin_fit` depending on what you exported — set the
one you have and leave the other `null` (or omit it). `exclude_laps` is an
optional list of lap indices to drop from the summaries (rests, anomalies,
a lap where you stopped to adjust the mount).

`adaptive_strokes` (default `false`) controls weak-stroke detection. With the
fixed default threshold, very soft strokes (e.g. a deliberately weak or injured
side) accelerate the boat too little to register, so KG counts fewer strokes
than Garmin on those pieces — by design, KG measures boat *thrust*, not arm
cadence. Setting `adaptive_strokes: true` lowers the detection threshold
adaptively to the signal's own amplitude **while the boat is moving** (GPS-speed
gated, so drifting rests still read zero). It only ever lowers the bar on weak
pieces; normal/strong laps are unchanged. Leave it `false` to reproduce the
legacy fixed-threshold counts (e.g. the session-37 reference).

`gap_fill_strokes` (default `false`) fixes a different miss: on long steady
cruise pieces the detector drops the *softest* real strokes, so KG's count runs
a few % under the SpeedCoach even when the cadence matches exactly (cadence is
median-based, so scattered misses don't move it — only the count). With the flag
on, KG uses its rock-solid median stroke period as a prior and recovers a dropped
stroke wherever the rhythm predicts one **and** a real sub-threshold bump
actually sits there. So it adds genuine soft strokes but never invents them on
rests/drills — it's speed-gated and needs an established cadence to extrapolate
from (a balance drill with no rhythm gets nothing). On session 45 it lifted
real-piece stroke agreement with the SpeedCoach from 91% to 96%. The residual
~4% are soft strokes that leave little *forward-accel* bump but still disturb the
hull on other axes (pitch/heave); NK's boat accelerometer catches them, KG's
forward-accel peak detector doesn't *yet* — an algorithm limit, not a sensing one
(both are hull-motion sensors; only the wrist Garmin senses arm motion). Like
`adaptive_strokes`, it only
ever adds strokes on moving pieces; leave it `false` for the session-37 reference.

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

### SpeedCoach comparison (if you have an NK SpeedCoach export)

SpeedCoach is boat-mounted like KG, so it's the right reference for confirming
KG's speed and stroke data (the Garmin *watch* counts arm cadence, not hull
motion, so it over-counts on rests/weak strokes).

Workflow:
1. Drop the SpeedCoach CSV into `analysis/data/`.
2. Set `"nk_speedcoach": "<filename>.csv"` in the session's manifest entry.
3. Run:

```bash
python analysis/speedcoach_report.py --session 38
```

It prints a DATA QUALITY block — **the standard per-session match to report** —
plus a per-lap table (strokes / speed / stroke-rate / distance-per-stroke,
SpeedCoach vs KG), and saves three plots to `analysis/plots/session_N/`:
`40_speed_vs_time.png`, `41_strokerate_vs_time.png`, `42_per_lap_bars.png`.

Report these four numbers each session (the DATA QUALITY block prints them all):

| Metric | What it is | Good |
|---|---|---|
| Speed correlation `r` | instantaneous KG-vs-SpeedCoach speed | > 0.9 |
| Per-lap mean-speed agreement | median \|KG − SC\| over real pieces (mph) | < 0.3 mph |
| Per-lap cadence agreement | median \|KG − SC\| stroke rate over real pieces (spm) | < 2 spm |
| Stroke-count ratio | KG total strokes / SpeedCoach total | 90–110% |

(Session 45 hit r = 0.954, 0.04 mph, 0.3 spm, 91% — verdict GOOD.) The report aligns the
SpeedCoach to KG (the two devices are usually started a few seconds apart) and
trims the acceleration ramp before averaging, so per-lap mean speeds are
comparable — KG agrees with the SpeedCoach to within hundredths of an mph on
piece averages. KG's *instantaneous* speed is noisier (a jumpy single-sample
max), so for a true peak speed use a smoothed value or the SpeedCoach.

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
| **Work per stroke (J)** | Area under force-vs-distance (`perg_plot --distance`). Energy into the boat per stroke; reveals leg drive. | Larger; a fuller/longer arch = sustained drive (compare matched pairs) |
| **Ama heel + roll-RMS** | Sustained heel off the floating baseline + roll-rate RMS. Balance skill while flying the ama. | Higher heel held at *lower* roll-RMS = steadier |

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
