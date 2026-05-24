"""
Session 37 — visually inspect the raw yaw signal during a cruise mile,
and the per-stroke yaw response at multiple time windows.

We expected 8-15 stroke blocks of same-sign yaw. Run-length analysis says
median = 2. Either the signal is too weak in cruise, or our integration
window is capturing the post-stroke correction along with the stroke impulse.

This script:
  1. Plots the raw yaw signal over a 60 s mid-mile window of lap 2 with
     stroke catches marked. If side blocks exist, we should see slow
     low-frequency drift in the yaw envelope across ~10 strokes.
  2. For each stroke, samples yaw at multiple post-catch delays (50, 100,
     200, 400 ms) and plots how the sign distribution changes with delay.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, detect_strokes,
    _bandpass, KG_PATH, TCX_PATH, PLOTS_DIR,
)


def plot_raw_yaw_segment(kg, R, tcx, align, savepath,
                         lap_idx=2, win_start_s=60.0, win_dur_s=60.0):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, _ = lap_local_window(lap, align)
    w0 = lt0 + win_start_s
    w1 = w0 + win_dur_s
    m = (t >= w0) & (t <= w1)
    tt = t[m] - w0
    fwd = A_body[m, 0]
    yaw_raw = G_body[m, 2]
    fs = (len(tt) - 1) / (tt[-1] - tt[0])
    yaw_bp = _bandpass(yaw_raw, fs, lo=0.5, hi=3.0)
    # Slow envelope: low-pass yaw to see if there's a DC drift on the stroke-block scale
    yaw_slow_sos_lo = 0.05  # Hz — slower than any stroke; tracks side-switching cadence
    from scipy.signal import butter, sosfiltfilt
    if fs > 0.2:
        sos_slow = butter(2, [yaw_slow_sos_lo, 0.3], btype="band", fs=fs, output="sos")
        yaw_slow = sosfiltfilt(sos_slow, yaw_raw)
    else:
        yaw_slow = yaw_raw * 0

    strokes = detect_strokes(tt + w0, fwd, prominence=1.5, height=1.0, refractory_s=0.4)
    catch_t = [s[0] - w0 for s in strokes]

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    axes[0].plot(tt, fwd, color="steelblue", linewidth=0.7)
    axes[0].set_ylabel("a_fwd (m/s²)")
    axes[0].set_title(f"Lap {lap_idx} cruise — 60 s starting at lap-relative t={win_start_s:.0f} s")
    axes[0].axhline(0, color="black", linewidth=0.3)
    for c in catch_t:
        axes[0].axvline(c, color="gray", alpha=0.3, linewidth=0.5)

    axes[1].plot(tt, yaw_raw, color="purple", linewidth=0.5, label="raw yaw rate")
    axes[1].plot(tt, yaw_bp, color="darkorange", linewidth=0.8, alpha=0.8,
                 label="band-passed (0.5-3 Hz, stroke band)")
    axes[1].axhline(0, color="black", linewidth=0.3)
    for c in catch_t:
        axes[1].axvline(c, color="gray", alpha=0.3, linewidth=0.5)
    axes[1].set_ylabel("ω_yaw (rad/s)")
    axes[1].set_title("Yaw rate — raw and band-passed")
    axes[1].legend(loc="upper right")

    axes[2].plot(tt, yaw_slow, color="darkgreen", linewidth=1.2,
                 label="slow envelope (0.05-0.3 Hz)")
    axes[2].axhline(0, color="black", linewidth=0.3)
    for c in catch_t:
        axes[2].axvline(c, color="gray", alpha=0.3, linewidth=0.5)
    axes[2].set_ylabel("slow ω_yaw (rad/s)")
    axes[2].set_xlabel("Time within 60 s window (s)")
    axes[2].set_title("Slow-envelope yaw (0.05-0.3 Hz). If side-blocks exist, "
                      "this should swing on the 10-20 s scale.")
    axes[2].legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_window_sweep(kg, R, tcx, align, savepath, lap_idx=2):
    """For lap_idx, compute per-stroke yaw at multiple post-catch windows and
    plot signed values over stroke index."""
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)
    m = (t >= lt0) & (t <= lt1)
    tt = t[m]
    fwd = A_body[m, 0]
    yaw = G_body[m, 2]
    fs = (len(tt) - 1) / (tt[-1] - tt[0])
    strokes = detect_strokes(tt, fwd, prominence=1.5, height=1.0, refractory_s=0.4)
    if not strokes:
        return

    delays = [(0.05, 0.10), (0.05, 0.15), (0.10, 0.25), (0.10, 0.40)]
    fig, axes = plt.subplots(len(delays), 1, figsize=(14, 9), sharex=True)
    for ax, (pre_skip, win) in zip(axes, delays):
        skip = int(pre_skip * fs)
        n = int(win * fs)
        scores = []
        for st_t, idx in strokes:
            lo = idx + skip
            hi = min(len(yaw), lo + n)
            if hi <= lo:
                scores.append(0.0)
                continue
            scores.append(float(np.mean(yaw[lo:hi])))
        scores = np.array(scores)
        colors = ["crimson" if s < 0 else "navy" for s in scores]
        ax.bar(np.arange(1, len(scores) + 1), scores, color=colors, alpha=0.85, width=0.9)
        ax.axhline(0, color="black", linewidth=0.5)
        sign = np.sign(scores)
        runs = 1 + int(np.sum(np.diff(sign) != 0))
        ax.set_title(f"Window: catch + {pre_skip*1000:.0f} ms to catch + {(pre_skip+win)*1000:.0f} ms  | "
                     f"runs = {runs} (lower is better — expect ~30-50 for 8-15 stroke blocks)")
        ax.set_ylabel("mean yaw (rad/s)")
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("Stroke # within lap")
    fig.suptitle(f"Lap {lap_idx} — varying the yaw sampling window around the catch",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    plot_raw_yaw_segment(kg, R, tcx, align,
                          os.path.join(PLOTS_DIR, "08_raw_yaw_window.png"),
                          lap_idx=2, win_start_s=120.0, win_dur_s=60.0)
    plot_window_sweep(kg, R, tcx, align,
                       os.path.join(PLOTS_DIR, "08_window_sweep.png"),
                       lap_idx=2)
    print("Done.")


if __name__ == "__main__":
    main()
