"""
Session 37 — extract L/R side using the SLOW-FILTERED yaw envelope.

Instead of trying to classify each stroke individually (yaw at the catch is
noisy on a per-stroke basis), filter the yaw rate signal in the side-switching
band (8-15 strokes at 50 spm => 10-18 s blocks => fundamental ~0.03-0.06 Hz).
Sample that envelope at each stroke catch to get the side label.

Produces:
  10_side_envelope_lap2.png — raw yaw, side-band envelope, and stroke labels.
  10_side_envelope_summary.png — labeled-stroke timeline for laps 2, 3, 9, 13.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, detect_strokes,
    KG_PATH, TCX_PATH, PLOTS_DIR,
)


def side_envelope(yaw, fs, lo=0.02, hi=0.15):
    """Band-pass yaw rate in the side-switching band.

    Periods 6.7-50 s -> covers everything from 3-stroke micro-bursts to
    very slow side-pattern changes.
    """
    sos = butter(2, [lo, hi], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, yaw)


def collect_lap(kg, R, tcx, align, lap_idx,
                prominence=1.5, height=1.0, refractory_s=0.4):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)
    m = (t >= lt0) & (t <= lt1)
    tt = t[m] - lt0
    fwd = A_body[m, 0]
    yaw = G_body[m, 2]
    fs = (len(tt) - 1) / (tt[-1] - tt[0])
    envelope = side_envelope(yaw, fs)
    strokes = detect_strokes(t[m], fwd, prominence=prominence, height=height,
                             refractory_s=refractory_s)
    catch_idx = [s[1] for s in strokes]
    catch_t = [tt[i] for i in catch_idx]
    catch_env = [float(envelope[i]) for i in catch_idx]
    return {
        "lap": lap,
        "tt": tt,
        "fwd": fwd,
        "yaw": yaw,
        "envelope": envelope,
        "catch_t": np.array(catch_t),
        "catch_env": np.array(catch_env),
    }


def runs(signs):
    if len(signs) == 0:
        return []
    out = []
    cur = int(signs[0])
    n = 1
    for s in signs[1:]:
        if int(s) == cur:
            n += 1
        else:
            out.append((n, cur))
            cur = int(s)
            n = 1
    out.append((n, cur))
    return out


def plot_lap_envelope(d, savepath, hard_zoom_s=120.0):
    """Three panels: forward accel, yaw + envelope, per-stroke side score."""
    lap = d["lap"]
    tt = d["tt"]
    fwd = d["fwd"]
    yaw = d["yaw"]
    env = d["envelope"]
    catch_t = d["catch_t"]
    catch_env = d["catch_env"]

    # Optionally restrict to a mid-lap zoom for visibility
    if tt[-1] > hard_zoom_s:
        t_lo = hard_zoom_s / 2
        t_hi = t_lo + hard_zoom_s
    else:
        t_lo, t_hi = tt[0], tt[-1]
    sel = (tt >= t_lo) & (tt <= t_hi)
    csel = (catch_t >= t_lo) & (catch_t <= t_hi)

    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    axes[0].plot(tt[sel], fwd[sel], color="steelblue", linewidth=0.6)
    axes[0].set_ylabel("a_fwd (m/s²)")
    axes[0].set_title(f"Lap {lap['idx']} ({lap['distance_m']:.0f} m) — forward accel")
    for c in catch_t[csel]:
        axes[0].axvline(c, color="gray", alpha=0.25, linewidth=0.5)
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(tt[sel], yaw[sel], color="lightgray", linewidth=0.5, label="raw yaw rate")
    axes[1].plot(tt[sel], env[sel], color="purple", linewidth=2.0,
                 label="side envelope (0.02-0.15 Hz band-pass)")
    axes[1].axhline(0, color="black", linewidth=0.5)
    axes[1].set_ylabel("ω_yaw (rad/s)")
    axes[1].set_title("Yaw rate + side-switching envelope")
    axes[1].legend(loc="upper right")
    axes[1].grid(True, alpha=0.3)

    colors_at_catch = ["crimson" if e < 0 else "navy" for e in catch_env[csel]]
    axes[2].scatter(catch_t[csel], catch_env[csel], c=colors_at_catch, s=22,
                    edgecolor="white", linewidth=0.5)
    axes[2].plot(tt[sel], env[sel], color="purple", linewidth=0.8, alpha=0.7)
    axes[2].axhline(0, color="black", linewidth=0.5)
    axes[2].set_ylabel("envelope at catch (rad/s)")
    axes[2].set_xlabel("Time within lap (s)")
    axes[2].set_title("Per-stroke side label from envelope at catch (red = LEFT, navy = RIGHT)")
    axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_summary(kg, R, tcx, align, savepath, lap_ids=(2, 3, 9, 13)):
    fig, axes = plt.subplots(len(lap_ids), 1, figsize=(15, 3 * len(lap_ids)))
    if len(lap_ids) == 1:
        axes = [axes]
    rows = []
    for ax, li in zip(axes, lap_ids):
        d = collect_lap(kg, R, tcx, align, li)
        env = d["catch_env"]
        if len(env) == 0:
            ax.set_title(f"Lap {li} — no strokes")
            continue
        x = np.arange(1, len(env) + 1)
        colors = ["crimson" if e < 0 else "navy" for e in env]
        ax.bar(x, env, color=colors, alpha=0.85, width=1.0)
        ax.axhline(0, color="black", linewidth=0.5)
        signs = np.sign(env)
        switches = np.where(np.diff(signs) != 0)[0]
        for sw in switches:
            ax.axvline(sw + 1.5, color="orange", linewidth=0.6, alpha=0.5)
        rs = runs(signs.tolist())
        run_lens = [r[0] for r in rs]
        median_run = int(np.median(run_lens)) if run_lens else 0
        max_run = int(max(run_lens)) if run_lens else 0
        in_range = (float(np.mean([(r >= 8) and (r <= 15) for r in run_lens]))
                    if run_lens else 0)
        nL = int(np.sum(env < 0)); nR = int(np.sum(env >= 0))
        ax.set_title(
            f"Lap {li}  ({d['lap']['distance_m']:.0f} m, {d['lap']['duration_s']:.0f} s)  | "
            f"{len(env)} strokes, {nL} L / {nR} R  | "
            f"{len(rs)} runs, median {median_run}, max {max_run}, "
            f"frac in 8-15: {in_range:.2f}"
        )
        ax.set_xlabel("Stroke # within lap")
        ax.set_ylabel("Envelope at catch (rad/s)")
        ax.grid(True, alpha=0.3)
        rows.append({"lap": li, "runs": rs})
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return rows


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Lap 2 detailed plot...")
    d2 = collect_lap(kg, R, tcx, align, 2)
    plot_lap_envelope(d2, os.path.join(PLOTS_DIR, "10_side_envelope_lap2.png"))

    print("Summary across laps 2, 3, 9, 13...")
    plot_summary(kg, R, tcx, align,
                  os.path.join(PLOTS_DIR, "10_side_envelope_summary.png"),
                  lap_ids=(2, 3, 9, 13))
    print("Done.")


if __name__ == "__main__":
    main()
