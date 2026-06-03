"""
Whole-session stroke-rate (cadence) timeline — KG-derived.

Runs the same stroke detector the rest of the pipeline uses, but over the
ENTIRE session. Turns stroke spacing into an instantaneous cadence (spm),
restricts attention to the on-water paddling window, and reports:

  - average cadence while paddling
  - sustained max cadence (rolling median over a few strokes — not a one-off fluke)
  - raw max cadence (single fastest stroke pair, kept only as a sanity bound)

and saves a plot of cadence vs. session time to plots/session_N/.

Works on any session in the manifest:

    python analysis/stroke_rate_timeline.py --session N

All thresholds have general, physically-motivated defaults and can be overridden
on the command line (e.g. a different boat/mount may need different detector
gains). Nothing here is tuned to a specific session.

Honesty notes:
  * This is KG-self-derived. It has NOT been validated against an external
    stroke counter (the NK SpeedCoach is the intended ground truth). Treat the
    numbers as internal estimates until a session carries SpeedCoach data.
  * The detector is band-pass (0.5-3 Hz) + prominence + height + refractory.
  * A peak-picker fires on noise during non-paddling stretches (pre-launch,
    drifting, rests, and the takeout carry). We restrict to the on-water window
    and a plausible cadence band, and smooth before quoting a max, so spurious
    spacings can't inflate the numbers.
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from session_config import get_session, add_session_arg
from correlate_kg_garmin import (
    load_kg, detect_imu_axes, rotate_accel, detect_strokes,
)

# --- General defaults (overridable via CLI; not session-specific) ---

# Stroke detector. These match the rest of the pipeline. A different mount or
# boat that changes forward-accel amplitude may want different gains.
DEFAULT_PROMINENCE = 1.5   # m/s^2 peak prominence
DEFAULT_HEIGHT = 1.0       # m/s^2 absolute peak height
DEFAULT_REFRACTORY_S = 0.4 # min spacing between strokes (also caps cadence)

# Plausible paddling cadence band. The refractory above already caps the upper
# end; the lower bound separates continuous paddling from rest gaps (a spacing
# longer than 60/MIN_SPM seconds is treated as a gap, not a stroke pair).
DEFAULT_MIN_SPM = 20.0
DEFAULT_MAX_SPM = 150.0

# On-water window detection. We find the single longest contiguous stretch where
# the boat is moving, which is the launch-to-takeout paddle; the walk-to-ramp
# before and the dock/carry after fall outside it. The threshold is deliberately
# low (not paddling speed): mid-session events like a turnaround drop speed for a
# minute or two but the boat keeps drifting, so the leg stays connected — only a
# genuine takeout (speed decaying to ~0) breaks the run.
DEFAULT_MOVE_THRESH = 0.4    # m/s — boat still moving above this; ~0 = stopped
DEFAULT_MOVE_SMOOTH_S = 25.0 # seconds of GPS-speed smoothing for window detection

# Rolling-median window (in strokes) defining a SUSTAINED cadence. A real "max
# stroke rate" should hold for several strokes, not a single lucky pair.
DEFAULT_SUSTAIN_WIN = 9


def find_paddling_window(gps_t, gps_speed, thresh, smooth_s):
    """Return (t_start, t_end) of the longest contiguous on-water moving run.

    Heavily smooths GPS speed, thresholds it, then picks the single longest
    contiguous above-threshold run. Falls back to the full GPS span if there is
    too little GPS data to judge.
    """
    if len(gps_t) < 5:
        return (gps_t[0], gps_t[-1]) if len(gps_t) else (0.0, 0.0)
    fs = (len(gps_t) - 1) / (gps_t[-1] - gps_t[0])
    win = max(1, int(smooth_s * fs))
    sm = np.convolve(gps_speed, np.ones(win) / win, mode="same")
    moving = sm >= thresh

    # Scan contiguous True runs; keep the longest by elapsed time.
    best = (gps_t[0], gps_t[-1])
    best_dur = 0.0
    i, n = 0, len(moving)
    while i < n:
        if not moving[i]:
            i += 1
            continue
        j = i
        while j < n and moving[j]:
            j += 1
        dur = gps_t[j - 1] - gps_t[i]
        if dur > best_dur:
            best_dur = dur
            best = (gps_t[i], gps_t[j - 1])
        i = j
    return best


def rolling_median(x, win):
    """Centered rolling median, same length as x (truncated near the ends)."""
    n = len(x)
    if n == 0:
        return x
    half = win // 2
    out = np.empty(n)
    for i in range(n):
        out[i] = np.median(x[max(0, i - half):min(n, i + half + 1)])
    return out


def build_parser():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_session_arg(p)

    d = p.add_argument_group("stroke detector")
    d.add_argument("--prominence", type=float, default=DEFAULT_PROMINENCE,
                   help="peak prominence (m/s^2)")
    d.add_argument("--height", type=float, default=DEFAULT_HEIGHT,
                   help="absolute peak height (m/s^2)")
    d.add_argument("--refractory", type=float, default=DEFAULT_REFRACTORY_S,
                   help="min spacing between strokes (s)")

    g = p.add_argument_group("gating")
    g.add_argument("--min-spm", type=float, default=DEFAULT_MIN_SPM,
                   help="lower cadence band (spm)")
    g.add_argument("--max-spm", type=float, default=DEFAULT_MAX_SPM,
                   help="upper cadence band (spm)")
    g.add_argument("--move-thresh", type=float, default=DEFAULT_MOVE_THRESH,
                   help="GPS speed above which the boat is 'moving' (m/s)")
    g.add_argument("--move-smooth", type=float, default=DEFAULT_MOVE_SMOOTH_S,
                   help="GPS-speed smoothing for window detection (s)")
    g.add_argument("--sustain-win", type=int, default=DEFAULT_SUSTAIN_WIN,
                   help="rolling-median window for sustained cadence (strokes)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = get_session(args.session)

    print(f"Session {cfg.session_id} ({cfg.date}) — {cfg.location}")
    print("Loading KG log...")
    kg = load_kg(cfg.kg_path)

    # Rotate raw accel into the boat body frame; column 0 is forward (surge).
    R, _ = detect_imu_axes(kg)
    fwd = rotate_accel(R, kg["accel_raw"])[:, 0]
    t = kg["imu_t"]                  # seconds since KG t=0
    session_dur_s = float(t[-1] - t[0])
    print(f"IMU span: {session_dur_s/60.0:.1f} min, {len(t):,} samples")

    print("Detecting strokes over the whole session...")
    strokes = detect_strokes(t, fwd, prominence=args.prominence,
                             height=args.height, refractory_s=args.refractory)
    stroke_t = np.array([st for st, _ in strokes], dtype=np.float64)
    print(f"  {len(stroke_t):,} candidate strokes detected")
    if len(stroke_t) < 5:
        print("Too few strokes to compute a cadence timeline.")
        return

    # Instantaneous cadence from spacing between consecutive strokes.
    intervals = np.diff(stroke_t)                 # seconds between strokes
    inst_cad = 60.0 / intervals                   # strokes per minute
    mid_t = 0.5 * (stroke_t[:-1] + stroke_t[1:])  # value placed at the midpoint

    # On-water paddling window (launch -> takeout) from GPS.
    win_t0, win_t1 = find_paddling_window(
        kg["gps_t"], kg["gps_speed"], args.move_thresh, args.move_smooth)
    window_min = (win_t1 - win_t0) / 60.0
    print(f"  Paddling window: {win_t0/60.0:.1f}-{win_t1/60.0:.1f} min "
          f"({window_min:.1f} min on the water)")

    # Gate to the cadence band (drops rest gaps + noise) AND to the window
    # (drops walk-to-ramp + dock/carry at the ends).
    in_band = (inst_cad >= args.min_spm) & (inst_cad <= args.max_spm)
    in_window = (mid_t >= win_t0) & (mid_t <= win_t1)
    paddling = in_band & in_window
    n_dropped_offwindow = int((in_band & ~in_window).sum())
    cad_p = inst_cad[paddling]
    t_p = mid_t[paddling]
    if len(cad_p) < 5:
        print("Too few in-band stroke pairs to summarize.")
        return

    # Sustained cadence = rolling median, so a single fluke pair can't define it.
    cad_smooth = rolling_median(cad_p, args.sustain_win)

    # The rolling median is truncated near each end, so take the sustained MAX
    # only over the trustworthy interior; report its time so middle (real effort)
    # is distinguishable from an edge (launch/takeout artifact).
    half = args.sustain_win // 2
    if len(cad_smooth) > 2 * half:
        core = cad_smooth[half:-half]
        core_t = t_p[half:-half]
    else:
        core, core_t = cad_smooth, t_p
    i_max = int(np.argmax(core))

    avg_cad = float(np.mean(cad_p))
    median_cad = float(np.median(cad_p))
    sustained_max = float(core[i_max])
    sustained_max_t_min = float(core_t[i_max] / 60.0)
    raw_max = float(np.max(cad_p))
    n_paddle_strokes = int(paddling.sum())

    # ---- Print summary -------------------------------------------------------
    print("\n" + "=" * 62)
    print(f"  KG-DERIVED STROKE RATE — session {cfg.session_id} (self-derived)")
    print("=" * 62)
    print(f"  Strokes (in window, in band): {n_paddle_strokes:,}")
    print(f"  Dropped outside window:       {n_dropped_offwindow:,} "
          f"(walk-to-ramp + dock/carry)")
    print(f"  On-water paddling time:       {window_min:.1f} min "
          f"(of {session_dur_s/60.0:.1f} min total)")
    print(f"  Average cadence (mean):       {avg_cad:.1f} spm")
    print(f"  Average cadence (median):     {median_cad:.1f} spm")
    print(f"  Sustained max ({args.sustain_win}-stroke median): {sustained_max:.1f} spm "
          f"at {sustained_max_t_min:.1f} min")
    print(f"  Raw single-pair max:          {raw_max:.1f} spm   (sanity bound only)")
    print("=" * 62)
    print("  Reminder: KG-self-derived, not checked against the SpeedCoach.")

    # ---- Plot ----------------------------------------------------------------
    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    ax.axvspan(win_t0 / 60.0, win_t1 / 60.0, color="aliceblue",
               label=f"paddling window ({window_min:.0f} min)")
    ax.scatter(t_p / 60.0, cad_p, s=6, color="lightgray", alpha=0.6,
               label="instantaneous (per stroke pair)")
    ax.plot(t_p / 60.0, cad_smooth, color="steelblue", linewidth=1.6,
            label=f"sustained ({args.sustain_win}-stroke rolling median)")
    ax.axhline(avg_cad, color="seagreen", linestyle="--", linewidth=1.2,
               label=f"average = {avg_cad:.1f} spm")
    ax.plot(sustained_max_t_min, sustained_max, marker="v", color="firebrick",
            markersize=10,
            label=f"sustained max = {sustained_max:.1f} spm @ {sustained_max_t_min:.0f} min")

    ax.set_xlabel("Session time (min)")
    ax.set_ylabel("Stroke rate (spm)")
    ax.set_ylim(0, min(args.max_spm, raw_max * 1.1))
    ax.set_title(f"KG-derived stroke rate over time — session {cfg.session_id} "
                 f"({cfg.date}, {cfg.location})\n"
                 f"detector gated to {args.min_spm:.0f}-{args.max_spm:.0f} spm "
                 f"— self-derived, not SpeedCoach-validated")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", framealpha=0.9)

    fig.tight_layout()
    savepath = os.path.join(cfg.plots_dir, "30_stroke_rate_timeline.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved: {savepath}")


if __name__ == "__main__":
    main()
