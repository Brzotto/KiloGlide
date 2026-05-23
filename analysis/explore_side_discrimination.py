"""
Session 37 — exploring L/R stroke-side discrimination signals.

The default analysis used gyro_x (roll rate) to label strokes L vs R. That
works on a kayak or surfski where roll dynamics drive the side. On an OC1
the ama suppresses roll, so we need to look elsewhere.

Candidates we sample at each stroke catch:
  - gyro_x (roll rate)     — about forward axis; should be SMALL on OC1
  - gyro_y (pitch rate)    — about lateral axis; bow nodding, not stroke-side
  - gyro_z (yaw rate)      — about up axis; bow swings RIGHT on LEFT strokes
  - a_y (lateral accel)    — boat pushed sideways at the catch
  - a_x (forward accel)    — same on both sides; should NOT discriminate

This script measures the peak of each signal in a ±150 ms window around each
detected stroke in the burst laps (6, 7, 8), then plots per-lap histograms
and a per-stroke scatter so we can SEE which signal separates the bursts.
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
    KG_PATH, TCX_PATH, PLOTS_DIR,
)


def signed_integral(seg, dt):
    """Integral of the signal over the segment. Preserves direction (sign)
    — better than 'signed peak' because it captures NET response, not whichever
    half-swing is bigger."""
    if len(seg) == 0:
        return np.nan
    return float(np.sum(seg) * dt)


def sample_at_catches(t, signal, catch_indices, pre_s, post_s, fs):
    """For each catch index, integrate `signal` over [catch - pre, catch + post]."""
    pre = max(1, int(pre_s * fs))
    post = max(1, int(post_s * fs))
    dt = 1.0 / fs
    out = []
    for i in catch_indices:
        lo = max(0, i - pre)
        hi = min(len(signal), i + post)
        out.append(signed_integral(signal[lo:hi], dt))
    return np.array(out)


def collect_burst_samples(kg, R, tcx, align, lap_ids=(5, 6, 7, 8, 9),
                          pre_s=0.0, post_s=0.3):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    rows = []
    for li in lap_ids:
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        m = (t >= lt0) & (t <= lt1)
        tt = t[m]
        fwd = A_body[m, 0]
        lat = A_body[m, 1]
        up = A_body[m, 2]
        roll = G_body[m, 0]
        pitch = G_body[m, 1]
        yaw = G_body[m, 2]

        if len(tt) < 50:
            continue
        fs = (len(tt) - 1) / (tt[-1] - tt[0])
        strokes = detect_strokes(tt, fwd, prominence=1.5, height=1.0, refractory_s=0.35)
        if not strokes:
            continue
        catch_idx = [s[1] for s in strokes]

        roll_peaks = sample_at_catches(tt, roll, catch_idx, pre_s, post_s, fs)
        pitch_peaks = sample_at_catches(tt, pitch, catch_idx, pre_s, post_s, fs)
        yaw_peaks = sample_at_catches(tt, yaw, catch_idx, pre_s, post_s, fs)
        lat_peaks = sample_at_catches(tt, lat, catch_idx, pre_s, post_s, fs)
        fwd_peaks = sample_at_catches(tt, fwd, catch_idx, pre_s, post_s, fs)

        for k, (st_t, _) in enumerate(strokes):
            rows.append({
                "lap": li,
                "t": st_t,
                "roll": roll_peaks[k],
                "pitch": pitch_peaks[k],
                "yaw": yaw_peaks[k],
                "lat": lat_peaks[k],
                "fwd": fwd_peaks[k],
            })
    return rows


def plot_signal_histograms(rows, savepath):
    """For each candidate signal, show a per-lap histogram in the burst window."""
    burst_ids = sorted({r["lap"] for r in rows if r["lap"] in (6, 7, 8)})
    if not burst_ids:
        return None
    fig, axes = plt.subplots(5, 1, figsize=(13, 14), sharex=False)
    signals = [
        ("roll", "Gyro X — Roll rate (rad/s)", "thistle"),
        ("pitch", "Gyro Y — Pitch rate (rad/s)", "lightblue"),
        ("yaw", "Gyro Z — Yaw rate (rad/s)", "lightgreen"),
        ("lat", "Accel Y — Lateral accel (m/s²)", "lightsalmon"),
        ("fwd", "Accel X — Forward accel (m/s²) (control: should NOT separate)", "lightgray"),
    ]
    colors = {6: "#1f77b4", 7: "#ff7f0e", 8: "#2ca02c"}
    for ax, (key, title, _bg) in zip(axes, signals):
        for li in burst_ids:
            vals = [r[key] for r in rows if r["lap"] == li and np.isfinite(r[key])]
            if not vals:
                continue
            ax.hist(vals, bins=12, alpha=0.6, color=colors.get(li, "gray"),
                    label=f"Lap {li} (n={len(vals)})", edgecolor="white")
        ax.axvline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.set_title(title)
        ax.set_ylabel("Count")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("Signed integral over [catch, catch + 300 ms]")
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_timeline(rows, savepath):
    """Per-stroke side signature on a timeline within each burst lap.
    If the user did 'L then R' within a single lap, we should see a sign flip."""
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=False)
    burst_ids = [6, 7, 8]
    for ax, li in zip(axes, burst_ids):
        sub = [r for r in rows if r["lap"] == li]
        if not sub:
            continue
        # demean lateral within this lap to remove the gravity-tilt bias
        lat = np.array([r["lat"] for r in sub])
        lat_dm = lat - np.mean(lat)
        yaw = np.array([r["yaw"] for r in sub])
        ts = np.array([r["t"] for r in sub])
        ts_rel = ts - ts.min()
        n = len(ts)
        idx = np.arange(1, n + 1)

        # Two y-axes: yaw on left, demeaned lateral on right
        color_yaw = "#2ca02c"
        color_lat = "#d62728"
        ax.bar(idx - 0.18, yaw, width=0.35, color=color_yaw, alpha=0.85,
               label="yaw rate integral (rad)")
        ax2 = ax.twinx()
        ax2.bar(idx + 0.18, lat_dm, width=0.35, color=color_lat, alpha=0.85,
                label="lateral integral, lap-demeaned (m/s)")

        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_title(f"Lap {li} — per-stroke side signatures (n={n})  |  "
                     f"strokes are indexed catch order, not time")
        ax.set_xlabel("Stroke # within lap")
        ax.set_ylabel("Yaw integral (rad)", color=color_yaw)
        ax2.set_ylabel("Lat integral (m/s, demeaned)", color=color_lat)
        ax.tick_params(axis="y", labelcolor=color_yaw)
        ax2.tick_params(axis="y", labelcolor=color_lat)
        ax.grid(True, alpha=0.3)

    fig.suptitle("If you did 'L then R' inside one lap, expect the BARS TO FLIP SIGN partway through.\n"
                 "If each lap is a single side, bars stay one sign per lap.",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_scatter_grid(rows, savepath):
    """Per-stroke scatter of (yaw, lateral) and (yaw, roll) colored by lap.

    If the user did 'all L' in one lap and 'all R' in another, we should see
    clean clusters separated by the side-discriminating axis.
    """
    burst = [r for r in rows if r["lap"] in (6, 7, 8)]
    if not burst:
        return None
    colors = {6: "#1f77b4", 7: "#ff7f0e", 8: "#2ca02c"}
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    for li in sorted({r["lap"] for r in burst}):
        sub = [r for r in burst if r["lap"] == li]
        x = [r["yaw"] for r in sub]
        y = [r["lat"] for r in sub]
        axes[0].scatter(x, y, color=colors[li], alpha=0.7, label=f"Lap {li}",
                        s=60, edgecolor="white", linewidth=0.5)

        axes[1].scatter([r["yaw"] for r in sub], [r["roll"] for r in sub],
                        color=colors[li], alpha=0.7, label=f"Lap {li}",
                        s=60, edgecolor="white", linewidth=0.5)

        axes[2].scatter([r["lat"] for r in sub], [r["roll"] for r in sub],
                        color=colors[li], alpha=0.7, label=f"Lap {li}",
                        s=60, edgecolor="white", linewidth=0.5)

    for ax, (xlab, ylab) in zip(axes, [
        ("yaw rate (rad/s)", "lateral accel (m/s²)"),
        ("yaw rate (rad/s)", "roll rate (rad/s)"),
        ("lateral accel (m/s²)", "roll rate (rad/s)"),
    ]):
        ax.axhline(0, color="black", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.axvline(0, color="black", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.set_xlabel(xlab)
        ax.set_ylabel(ylab)
        ax.legend()
        ax.grid(True, alpha=0.3)

    fig.suptitle("Per-stroke peaks at the catch — colored by lap. Clean clusters = good side discriminator.",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def compute_lap_means(rows):
    """For each lap and each signal, return mean and signed-mean (preserving direction)."""
    by_lap = {}
    for li in sorted({r["lap"] for r in rows}):
        sub = [r for r in rows if r["lap"] == li]
        d = {}
        for key in ("roll", "pitch", "yaw", "lat", "fwd"):
            vals = np.array([r[key] for r in sub if np.isfinite(r[key])])
            if len(vals) == 0:
                continue
            d[key] = {
                "mean": float(np.mean(vals)),
                "median": float(np.median(vals)),
                "frac_positive": float(np.mean(vals > 0)),
                "n": len(vals),
            }
        by_lap[li] = d
    return by_lap


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Sampling per-stroke peaks for each candidate axis...")
    rows = collect_burst_samples(kg, R, tcx, align,
                                  lap_ids=(5, 6, 7, 8, 9),
                                  pre_s=0.0, post_s=0.3)
    print(f"  Collected {len(rows)} stroke samples.")

    means = compute_lap_means(rows)
    print("\nMean signal per lap at the catch (preserved sign):")
    print(f"  {'Lap':>4}  {'n':>4}  {'roll':>10}  {'pitch':>10}  {'yaw':>10}  {'lat':>10}  {'fwd':>10}")
    for li in sorted(means.keys()):
        d = means[li]
        if not d:
            continue
        print(f"  {li:>4}  {d['roll']['n']:>4}  "
              f"{d['roll']['mean']:+10.4f}  {d['pitch']['mean']:+10.4f}  "
              f"{d['yaw']['mean']:+10.4f}  {d['lat']['mean']:+10.4f}  "
              f"{d['fwd']['mean']:+10.4f}")

    print("\nFraction of strokes with POSITIVE signed integral (~0.5 means random):")
    print(f"  {'Lap':>4}  {'roll':>8}  {'pitch':>8}  {'yaw':>8}  {'lat':>8}  {'fwd':>8}")
    for li in sorted(means.keys()):
        d = means[li]
        if not d:
            continue
        print(f"  {li:>4}  {d['roll']['frac_positive']:>8.2f}  "
              f"{d['pitch']['frac_positive']:>8.2f}  {d['yaw']['frac_positive']:>8.2f}  "
              f"{d['lat']['frac_positive']:>8.2f}  {d['fwd']['frac_positive']:>8.2f}")

    print("\nWriting plots...")
    plot_signal_histograms(rows, os.path.join(PLOTS_DIR, "06_side_signal_histograms.png"))
    plot_scatter_grid(rows, os.path.join(PLOTS_DIR, "06_side_signal_scatter.png"))
    plot_timeline(rows, os.path.join(PLOTS_DIR, "06_side_timeline.png"))
    print("Done.")


if __name__ == "__main__":
    main()
