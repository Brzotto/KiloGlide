# TODO (next session): log GPS quality (speed accuracy) to detect signal contamination

**Status:** planned, not started. Hand this to a future session.

## Why
KG's *instantaneous* GPS ground speed is jittery (single-sample max inflated;
per-piece mean is accurate — validated to ~0.04 mph vs SpeedCoach on session 42).
We added the u-blox **Sea dynamic model** (PR #28) to tighten the velocity
solution, but we still can't *see* when the GPS itself is degraded — important
because the device uses the SAM-M10Q's integrated patch antenna (no external
antenna), so multipath / poor sky view could contaminate speed without warning.

Logging the receiver's own **speed-accuracy estimate (sAcc)** alongside the
already-logged satellite count + HDOP gives a per-fix quality signal: when sAcc
spikes, distrust that speed sample. It also lets us confirm/deny the
"antenna contamination" hypothesis directly.

## What to change (keep the binary layout change minimal)
The GPS record already carries `num_sats` and `hdop_c`, and has a spare
`uint16_t reserved` (currently written as zero). **Repurpose `reserved` →
`speed_acc_mm_s`** so the struct stays 24 bytes and old logs remain readable
(old logs have 0 there = "unknown", which is distinguishable from a real value).

Per the firmware rules, change these together in one commit:

1. **`firmware/src/log_format.h`** — rename `reserved` to
   `uint16_t speed_acc_mm_s;` (u-blox sAcc in mm/s, capped at 65535 ≈ 65 m/s).
   Keep `static_assert(sizeof(KgGpsPayload) == 24)`. Update the inline comment.
2. **`firmware/src/gps.cpp`** — capture sAcc from the PVT solution
   (`dev.getSpeedAccEst()` in the SparkFun u-blox v3 lib — verify return units =
   mm/s) into a `g_speedAcc`; add a `speedAccMmS()` getter in `gps.h`.
3. **`firmware/src/logger.cpp`** — write `gp.speed_acc_mm_s =
   (uint16_t)min(gps::speedAccMmS(), 65535u);`.
4. **`docs/log_format.md`** — document the field; note old logs read 0 here.
5. **`tools/kg_parse.py`** — parse the field; expose e.g. `gps_speed_acc` (m/s).
6. **Format version:** struct size is unchanged and old logs stay readable, so a
   bump is optional — but bumping (and having the parser treat 0/absent as
   "unknown") is the cleaner signal of the semantic change. Decide at implement
   time.

## Analysis follow-up (optional, after firmware ships)
- Add a GPS-quality panel to `speedcoach_report.py`: plot sAcc and satellite
  count vs time; flag/grey-out speed samples where sAcc exceeds a threshold.
- Consider a light low-pass on logged speed *only as a fallback* — the Sea model
  + sAcc gating is the preferred fix. (User declined blanket smoothing.)

## Acceptance
- A fresh on-water log shows nonzero `speed_acc_mm_s` per fix.
- Can plot sAcc + SIV over a session; high-sAcc stretches line up with the speed
  jitter → confirms when the antenna/signal is the limiter.

## Related
- PR #28 (GPS Sea dynamic model). This builds on it.
- Validation context: SpeedCoach is boat-mounted ground truth; KG and SpeedCoach
  speed agree to ~0.04 mph per piece (see `speedcoach_report.py`).
