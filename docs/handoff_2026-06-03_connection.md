# Handoff — 2026-06-03 — Connection usefulness phase

## Where the project is
**The device works and the data is trusted.** Session 37 was validated three
ways: KG vs Garmin (speed r=0.94) and KG vs **NK SpeedCoach** (independent
stroke sensor) — average cadence identical (49.9 vs 49.9 spm), total stroke
count within **1.1%** over 66 min, cadence-vs-time r=0.93. Three devices agree
on speed, cadence, and stroke count to within ~1%.

That answered *"does it collect good data?"* — **yes.** The project has now
pivoted to the real question: ***is it useful?*** i.e. does KG surface something
a SpeedCoach structurally cannot, reliably enough to act on.

## First usefulness target: CONNECTION
Chosen because it's testable in flatwater immediately and has the strongest
"only-KG" claim — the SpeedCoach knows *when* you stroked and how fast you went,
but not the **force-vs-time shape within the stroke**, which is connection.

- Metric (see `analysis/connection_metrics.py`): per stroke, the drive-force
  curve (forward accel × mass) is either a single clean arch (**connected**) or
  catch-bump → lull → drive (**disconnected**). "Connected %" = fraction of
  single-arch strokes.
- **Session 37 hint (suggestive, NOT proof):** glass mile 26% connected vs chop
  mile 13%. But laps 2 and 13 differ in water *and* speed *and* effort, and chop
  can slap the hull and fake double-peaks. Triple-confounded.
- **The decisive test** is the flatwater A/B protocol →
  `docs/connection_test_protocol.md`. Matched cadence, same water, vary only
  catch technique (connected vs disconnected). If KG separates them, connection
  is real and coachable.

## Tomorrow's session — how to ingest
After the paddle you'll have three files. Drop them in `analysis/data/` and add
a manifest entry to `analysis/data/sessions.json` (use the next integer session
id; example assumes 38):

```json
"38": {
  "date": "2026-06-04",
  "kg_file": "kg_000038.bin",
  "garmin_tcx": "activity_XXXXXXXX.tcx",
  "nk_speedcoach": "speedcoach_2669512_20260604.csv",
  "location": "Alameda Bay, CA",
  "boat": "OC1",
  "system_mass_kg": 85,
  "mount": "breadboard forward of seat",
  "conditions": "flatwater connection A/B test",
  "notes": "Connection test: 3x A (connected) / 3x B (disconnected), ~50 spm, button-marked. First session on TIME-record firmware.",
  "compare_laps": []
}
```

Notes:
- This is the **first session on the new firmware**, so the log will have TIME
  records, GPS fix events, and real heading. `correlate_kg_garmin` aligns on
  TIME records when present (absolute clock) and falls back to GPS xcorr — no
  action needed; alignment will just be tighter than session 37.
- Set `default_session` to the new id if you want the bare commands to target it.

## Analysis recipe (after ingest)
```bash
# 1. The connection A/B test — the headline result
#    Pieces come from GARMIN LAP-BUTTON presses (no KG box-opening on the water).
python analysis/connection_test.py --session 38 --from-garmin --labels "skip,A,B,A,B,A,B,skip"
#    -> adjust labels to match the actual warm-up/cooldown lap count
#    -> check the 'cad' column: A and B must be within a couple spm (matched)
#    -> success = A pieces clearly higher connected % than B, across all 3 reps
#    If lap presses got muddled, segment by time instead:
#    python analysis/connection_test.py --session 38 --windows "m0:m1,m2:m3,..." --labels "A,B,..."

# 2. Sanity / cross-checks
python analysis/stroke_rate_timeline.py --session 38      # cadence over time
python analysis/compare_kg_speedcoach.py --session 38     # KG vs SpeedCoach again (new firmware)
python analysis/coach_summary.py --session 38             # one-page summary
```

## New/changed tooling this phase (all session-aware, `--session N`)
- `analysis/stroke_rate_timeline.py` — whole-session cadence + sustained max.
- `analysis/nk_speedcoach.py` — general NK SpeedCoach CSV loader.
- `analysis/compare_kg_speedcoach.py` — KG-vs-SpeedCoach validation + plot.
- `analysis/connection_test.py` — **the connection A/B workhorse**; segments by
  Garmin TCX laps (`--from-garmin`, the lap-button method), KG button marks
  (USER_MARK = event code 3), or explicit `--windows`. Reuses
  `connection_metrics.connection_metrics`. Pieces labeled `skip`/`-` are ignored.

## Open issues / tech debt (don't silently ignore)
- **"Single peak = good" is still a hypothesis.** Tomorrow's test validates it.
- **Many older scripts are session-37-hardcoded** (import `KG_PATH`/`TCX_PATH`):
  `connection_metrics, chop_vs_connection, connected_strokes, perg_plot,
  stroke_phases, lean_and_bursts, side_*, bonus_visualizations,
  inspect_yaw_signal, explore_side_discrimination`. Per the repo coding rule,
  generalize these to `--session` *when you next touch one* — don't bulk-refactor
  speculatively. `correlate_kg_garmin.py` is hardcoded in `main()` but its
  functions are reused fine as a library; leave it.
- **Axis detection** uses a cruise window; `connection_test` auto-picks a
  mid-session window for short sessions, but the 30 s stillness at session start
  (in the protocol) is what makes gravity/axis detection solid. Make sure it
  happened.
- **Wave-slap confound** is the reason for flatwater. If tomorrow isn't calm,
  the result is weaker — note conditions in the manifest.

## Reminder: coding rule (now in CLAUDE.md/AGENTS.md)
Write general, session-agnostic code. Session facts live in the manifest;
tunables are CLI flags with physical defaults. Don't hard-code one session's
paths, dates, lap numbers, or thresholds.
