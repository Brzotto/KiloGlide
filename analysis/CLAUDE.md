# KiloGlide Analysis

This directory contains the Python analysis pipeline for KiloGlide sessions.
Keep agent context small: load the script, manifest entry, and docs needed for
the current question instead of rereading generated reports or large plots.

## Agent instruction mirrors

Keep `analysis/AGENTS.md` and `analysis/CLAUDE.md` byte-for-byte identical.
When changing one, make the same change to the other in the same commit.

## Session workflow

- Raw session inputs live in `analysis/data/`.
- Session metadata lives in `analysis/data/sessions.json`.
- Newer scripts should accept `--session N` and load paths through
  `analysis/session_config.py`.
- Generated plots should go under `analysis/plots/session_N/`.
- For a new on-water session, add the KG binary and Garmin TCX to `data/`,
  add a manifest entry, then run the manifest-aware scripts.

Common commands:

```bash
python analysis/coach_summary.py --session N
python analysis/glide_speed_test.py --session N
python analysis/precatch_signature.py --session N
python analysis/connected_quick.py --session N
```

Older exploratory scripts may still have session-37 assumptions. When touching
one, migrate hard-coded paths, lap IDs, and labels to `session_config.py`
instead of adding more one-off constants.

## Analysis principles

- Preserve raw data files.
- Treat session 37 as the validated reference dataset, not as a permanent
  assumption for every script.
- Avoid hard-coded lap numbers except in session-specific notes or manifest
  metadata such as `compare_laps`.
- Prefer TIME-record alignment when available; use GPS speed cross-correlation
  as the fallback for older logs.
- Keep units explicit. Raw calculations are usually m/s, m/s^2, and N;
  coach-facing summaries should use familiar units such as mph and pounds.
- Distinguish IMU-only/current-independent metrics from GPS-over-ground speed
  metrics.

## Key files

- `session_config.py` - session manifest loader.
- `data/sessions.json` - per-session paths and comparison metadata.
- `correlate_kg_garmin.py` - primary parse, align, stroke, lap, and force
  pipeline.
- `coach_summary.py` - coach-facing one-page output.
- `glide_speed_test.py` - within-stroke speed and glide metrics.
- `precatch_signature.py` - averaged pre-catch forward-acceleration signature.
- `stroke_phases.py` - catch, pull, and glide annotations.

## Verification

For script edits, run at least a syntax check. For behavior changes, run the
smallest relevant session-37 command and inspect the printed output or plot.
