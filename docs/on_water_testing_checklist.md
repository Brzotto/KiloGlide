# On-water testing checklist

A reusable pre-/in-/post-session checklist for getting the cleanest, most
analyzable data out of a KiloGlide water test. Not session-specific — follow it
every time, and record the session-specific notes in
`analysis/data/sessions.json` (the manifest), not here.

The ordering is deliberate: each section is "what to do and *why it matters for
the data*," because a habit only sticks if you know what breaks without it.

---

## This test's headline goal: validate sAcc logging

The firmware now logs the GPS **speed-accuracy estimate (sAcc)** in each GPS
record (see `docs/todo_gps_quality_logging.md`, merged in PR #30). The first job
of the next on-water session is to confirm it works and to learn what "good" vs
"degraded" sAcc looks like on the water.

- **Flash the latest firmware first** (the build that contains sAcc). If you're
  not sure it's on the device, reflash. Old firmware writes 0 in that field and
  the whole point of this session is lost.
- **Create a deliberate sAcc contrast.** Paddle a few minutes in the open with a
  clear sky view, then a few minutes close to an obstruction (under/near a
  bridge, beside moored boats, hugging a seawall). Press the mark button at each
  transition and jot the times. This gives a *known* good-vs-bad stretch to line
  the sAcc trace up against — the direct test of the antenna-contamination
  hypothesis.
- **Acceptance:** after offload, `python tools/kg_parse.py <log>.bin` should show
  a nonzero "Speed accuracy" line (min/max/mean in m/s), not "not logged".

---

## Before you leave (bench / firmware)

- [ ] **Reflash with the current `main` firmware** and confirm it boots and finds
      the SD card (watch the serial log for the `SD: <size> MB` and
      `Next session:` lines).
- [ ] **SD card has free space** and is seated. At ~9 KB/s a 1-hour session is
      ~32 MB — trivial, but confirm the card mounts.
- [ ] **Battery charged.** A brown-out mid-session truncates the log (the parser
      recovers, but you lose the tail and the clean SESSION_END).
- [ ] **Button works** — confirm a short press emits `USER_MARK` and a long press
      starts/ends the session (serial prints `MARK` / session open/close).

## At the dock (calibration — 1 minute, huge payoff)

- [ ] **30 s of stillness, device mounted, before the first stroke.** Sit still
      on the water. This gives a clean gravity vector for axis auto-discovery —
      the cleaner the gravity, the cleaner forward/up/lateral separation and
      everything downstream. Don't skip this; it's the single highest-value
      habit.
- [ ] **Photo of the mount** on the canoe. Captures which way the USB port faces
      and which way is "up," so the auto-detected axes can be checked against
      physical truth. One phone snap.
- [ ] **Let the GPS settle to a 3D fix before starting** (serial / fix count).
      A cold start mid-paddle pollutes the first minutes of speed.

## During the session (data quality)

- [ ] **Keep the GPS antenna's sky view unobstructed** where you can — no
      backpack/body over it. (This session you'll *deliberately* break that for
      the sAcc-contrast piece — but for the rest of the session, clean sky view
      is the goal.)
- [ ] **Deliberate L/R calibration burst.** 10 strokes LEFT only, pause,
      10 strokes RIGHT only, pause, 10 alternating. Mark the start with the
      button and write down what you did. This is labeled training data for the
      per-stroke L/R classifier (still the main open analysis problem).
- [ ] **Structured effort blocks.** e.g. 5 min easy / 5 min steady / 5 min hard /
      5 min easy. Gives clean cadence-vs-effort and fatigue signal instead of one
      undifferentiated cruise.
- [ ] **Mark distinct moments** with the button — start of a test piece, a surf
      attempt, a technique trial. Each mark becomes a known anchor in analysis.
- [ ] **Note conditions** on your phone: wind, tide/current, chop. "Light SW
      wind, 0.5–1 m/s flood, glassy." Explains edge cases later.

## Device cross-reference (ground truth)

- [ ] **Run the Garmin and the NK SpeedCoach simultaneously** with KG. The
      SpeedCoach is boat-mounted ground truth for speed (KG agrees to ~0.04 mph
      per piece); the Garmin gives independent stroke cadence + HR.
- [ ] **Note the wall-clock start time** of each device, or press all start
      buttons together. Makes time-alignment trivial. (KG now writes TIME anchor
      records, so absolute-UTC alignment works without cross-correlation — but a
      noted start time is a cheap backup.)
- [ ] **Press lap/marker buttons on the Garmin at the same moments** you press
      KG's mark button, so laps line up across devices.

## After the session (offload + verify — do it the same day)

- [ ] **Copy the `kg_NNNNNN.bin` off the SD card** into `analysis/data/`. Don't
      edit or rename the raw file; preserve it as captured.
- [ ] **Export the Garmin activity** (`.fit` preferred, `.tcx` works) and the
      **NK SpeedCoach CSV**, drop them in `analysis/data/`.
- [ ] **Add a manifest entry** in `analysis/data/sessions.json` (date, paths via
      `garmin_fit`/`garmin_tcx` + the SpeedCoach CSV, any `exclude_laps`,
      `compare_laps`, and notes like the sAcc-contrast mark times).
- [ ] **Sanity-check the parse:**
      `python tools/kg_parse.py analysis/data/kg_NNNNNN.bin`
      Confirm: **0 CRC errors**, a clean SESSION_END, expected duration, IMU ~416
      Hz / GPS ~5 Hz, your marks present, and a **nonzero Speed-accuracy line**.
- [ ] **Run the pipeline** on the new session:
      `python analysis/coach_summary.py --session N` and
      `python analysis/speedcoach_report.py --session N`.

---

## Why these specifically

| Habit | What it protects |
|---|---|
| 30 s stillness | Clean gravity → reliable forward/up/lateral axis split |
| Mount photo | Lets auto-detected axes be checked against physical truth |
| L/R calibration burst | Labeled data for the unsolved per-stroke side classifier |
| Effort blocks | Separates cadence-vs-effort from undifferentiated cruise |
| sAcc-contrast piece | Direct test of the patch-antenna contamination hypothesis |
| Simultaneous SpeedCoach/Garmin | Independent ground truth for speed and cadence |
| Same-day offload + parse check | Catches a bad log while you can still re-test |

## Related docs

- `docs/todo_gps_quality_logging.md` — the sAcc logging change and its acceptance.
- `docs/connection_test_protocol.md` — the on-water A/B protocol for the
  connection-usefulness test (run that protocol when that's the session's focus).
- `analysis/session_37_status_and_next_session.md` — the original "what to
  capture next time" notes this checklist generalizes from.
- `docs/README_analysis.md` — how to run the pipeline on a new session.
