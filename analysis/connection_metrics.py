"""
Session 37 — stroke connection analysis on glass-water lap 13.

User flagged a "bump-lull-drive" shape in the mid-lap-2 PERG plot and asked
whether the same shape persists on the last paddling lap, which was the
calmest water of the session ("flat like glass, but slow because of current").

If the lull is real biomechanics (a catch-to-drive disconnect), it should
PERSIST in calm water. If the lull is chop-induced noise, it should
DISAPPEAR or significantly shrink.

Computes per-stroke:
  catch_peak_N        — height of the first positive local maximum
  drive_peak_N        — height of the global max (typically later than catch)
  lull_depth_N        — drop from min(catch_peak, drive_peak) to lull
                         valley between them
  catch_to_drive_pct  — phase distance between catch and drive in % stroke
  drive_over_catch    — ratio drive_peak / catch_peak (higher = more
                         body-dominant)

Produces:
  21_lap13_perg.png         — PM5-strict view of 20 lap-13 strokes
  21_lap2_vs_lap13.png      — side-by-side mean force curves
  21_connection_metrics.png — distributions of the four connection metrics
                              for lap 2 and lap 13, side by side
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import find_peaks

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, detect_strokes,
    stroke_features_for_window,
    KG_PATH, TCX_PATH, PLOTS_DIR, SYSTEM_MASS_KG,
)


def smooth(y, w=5):
    """Simple moving average for peak-finding stability."""
    if w <= 1 or len(y) < w:
        return y
    kernel = np.ones(w) / w
    return np.convolve(y, kernel, mode="same")


def collect_lap_strokes(kg, R, tcx, align, lap_idx, skip_start_s=120.0,
                        max_strokes=200):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)
    w0 = lt0 + skip_start_s
    m = (t >= w0) & (t <= lt1)
    tt = t[m]
    fwd = A_body[m, 0]
    roll = G_body[m, 0]
    strokes = detect_strokes(tt, fwd, prominence=1.5, height=1.0, refractory_s=0.4)
    feats = stroke_features_for_window(tt, fwd, roll, strokes, SYSTEM_MASS_KG)
    return feats[:max_strokes], lap


def connection_metrics(feats, mass_kg=SYSTEM_MASS_KG,
                        peak_min_N=10.0, prominence_frac=0.05,
                        min_separation_pct=5):
    """Compute per-stroke catch / drive / lull metrics.

    More sensitive than the previous version:
    - Detects peaks as small as 10 N tall (was 30 N).
    - Requires a peak's prominence to be at least 5% of the curve's max
      (so very small bumps register).
    - Peaks need to be only 5% of phase apart (was 8%).
    """
    out = []
    for f in feats:
        seg = f.get("fwd_segment")
        if seg is None or len(seg) < 20:
            continue
        # Resample to 101 points on stroke phase, clip to positive force
        n_points = 101
        force = np.maximum(seg * mass_kg, 0.0)
        c = np.interp(np.linspace(0, 1, n_points),
                      np.linspace(0, 1, len(force)), force)
        cs = smooth(c, w=3)

        curve_max = float(np.max(cs))
        # Prominence threshold scales with each stroke's amplitude so we
        # detect SMALL bumps relative to the drive, not just absolute-tall ones.
        prom_thresh = max(5.0, prominence_frac * curve_max)
        peaks, props = find_peaks(cs,
                                  height=peak_min_N,
                                  prominence=prom_thresh,
                                  distance=min_separation_pct)
        if len(peaks) == 0:
            # Edge case — should be rare; fall back to argmax
            drive_idx = int(np.argmax(cs))
            drive_peak = float(cs[drive_idx])
            out.append({
                "catch_peak_N": drive_peak, "drive_peak_N": drive_peak,
                "lull_value_N": drive_peak, "lull_depth_N": 0.0,
                "catch_phase_pct": drive_idx, "drive_phase_pct": drive_idx,
                "gap_pct": 0,
                "drive_over_catch": 1.0, "lull_depth_frac": 0.0,
                "connected": True, "n_peaks": 0,
                "curve_pos_clipped": c,
            })
            continue

        drive_idx = int(peaks[np.argmax(cs[peaks])])
        drive_peak = float(cs[drive_idx])

        # Catch = first peak (in time) before the drive peak. We dropped the
        # absolute height requirement so small bumps count.
        earlier = [p for p in peaks if p < drive_idx]
        if earlier:
            catch_idx = int(earlier[0])
            catch_peak = float(cs[catch_idx])
            lull_value = float(np.min(cs[catch_idx:drive_idx + 1]))
            lull_depth = float(min(catch_peak, drive_peak) - lull_value)
            connected = False
        else:
            catch_idx = drive_idx
            catch_peak = drive_peak
            lull_value = drive_peak
            lull_depth = 0.0
            connected = True

        out.append({
            "catch_peak_N": catch_peak,
            "drive_peak_N": drive_peak,
            "lull_value_N": lull_value,
            "lull_depth_N": lull_depth,
            "catch_phase_pct": catch_idx,
            "drive_phase_pct": drive_idx,
            "gap_pct": drive_idx - catch_idx,
            "drive_over_catch": drive_peak / catch_peak if catch_peak > 1 else float("nan"),
            "lull_depth_frac": lull_depth / drive_peak if drive_peak > 1 else 0.0,
            "connected": connected,
            "n_peaks": int(len(peaks)),
            "curve_pos_clipped": c,
        })
    return out


def plot_lap_perg(feats, lap, savepath, n_show=20):
    """PM5-strict view of one lap's strokes."""
    metrics = connection_metrics(feats)
    n = min(n_show, len(metrics))
    if n == 0:
        return None

    fig = plt.figure(figsize=(15, 6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1], wspace=0.25)

    # Left panel: overlay
    ax = fig.add_subplot(gs[0, 0])
    phase = np.linspace(0, 100, 101)
    colors = plt.cm.viridis(np.linspace(0, 1, n))
    curves = []
    for i, m in enumerate(metrics[:n]):
        c = m["curve_pos_clipped"]
        curves.append(c)
        ax.plot(phase, c, color=colors[i], alpha=0.5, linewidth=0.9)
    mean_curve = np.mean(curves, axis=0)
    median_curve = np.median(curves, axis=0)
    ax.plot(phase, mean_curve, color="black", linewidth=3.0, label="mean")
    ax.plot(phase, median_curve, color="red", linewidth=2.0, linestyle="--",
            label="median")
    ax.fill_between(phase,
                    np.percentile(curves, 25, axis=0),
                    np.percentile(curves, 75, axis=0),
                    color="black", alpha=0.10, label="25-75 pctl")
    ax.set_xlabel("Stroke phase (%)")
    ax.set_ylabel("Effective drive force (N) — clipped ≥ 0")
    ax.set_title(f"Lap {lap['idx']} ({lap['distance_m']:.0f} m glass-water mile)\n"
                 f"{n} consecutive strokes, mid-lap")
    ax.grid(True, alpha=0.3)
    ax.legend()

    # Right panel: small-multiples with metric overlay
    from matplotlib.gridspec import GridSpecFromSubplotSpec
    cols = 5
    rows = (n + cols - 1) // cols
    right_gs = GridSpecFromSubplotSpec(rows, cols, subplot_spec=gs[0, 1],
                                        wspace=0.15, hspace=0.35)
    f_max = max([np.max(c) for c in curves]) * 1.1
    for i, m in enumerate(metrics[:n]):
        ax2 = fig.add_subplot(right_gs[i // cols, i % cols])
        c = m["curve_pos_clipped"]
        ax2.fill_between(phase, 0, c, color="steelblue", alpha=0.45)
        ax2.plot(phase, c, color="black", linewidth=0.8)
        # Mark catch and drive
        ax2.plot(m["catch_phase_pct"], m["catch_peak_N"], "o",
                 color="orange", markersize=4)
        ax2.plot(m["drive_phase_pct"], m["drive_peak_N"], "o",
                 color="red", markersize=4)
        ax2.set_ylim(0, f_max)
        ax2.set_xticks([]); ax2.set_yticks([])
        if m["connected"]:
            tag = "★ connected"
            color = "green"
        else:
            tag = f"gap {m['gap_pct']}%"
            color = "darkred"
        ax2.set_title(f"#{i+1}  d/c={m['drive_over_catch']:.1f}  {tag}",
                       fontsize=7, color=color)
        ax2.grid(True, alpha=0.2)

    fig.suptitle("Orange dot = catch bump.  Red dot = drive peak.  ★ = single-peak (connected) stroke.",
                 fontsize=10, y=0.995)
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return metrics


def plot_lap_compare(feats_lap2, lap2, feats_lap13, lap13, savepath, n_show=20):
    """Mean force curves for lap 2 vs lap 13 side by side."""
    m2 = connection_metrics(feats_lap2)
    m13 = connection_metrics(feats_lap13)

    if not m2 or not m13:
        return

    phase = np.linspace(0, 100, 101)
    curves_2 = [x["curve_pos_clipped"] for x in m2[:n_show]]
    curves_13 = [x["curve_pos_clipped"] for x in m13[:n_show]]

    mean_2 = np.mean(curves_2, axis=0)
    mean_13 = np.mean(curves_13, axis=0)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: overlay on same axes
    ax = axes[0]
    for c in curves_2:
        ax.plot(phase, c, color="steelblue", alpha=0.15, linewidth=0.7)
    for c in curves_13:
        ax.plot(phase, c, color="seagreen", alpha=0.15, linewidth=0.7)
    ax.plot(phase, mean_2, color="steelblue", linewidth=3.0,
            label=f"Lap {lap2['idx']} (chop mile, mean over {len(curves_2)})")
    ax.plot(phase, mean_13, color="seagreen", linewidth=3.0,
            label=f"Lap {lap13['idx']} (glass mile, mean over {len(curves_13)})")
    ax.set_xlabel("Stroke phase (%)")
    ax.set_ylabel("Effective drive force (N) — clipped ≥ 0")
    ax.set_title("Mean force curves overlaid")
    ax.grid(True, alpha=0.3)
    ax.legend()

    # Right: median + IQR comparison
    ax = axes[1]
    med_2 = np.median(curves_2, axis=0)
    q1_2 = np.percentile(curves_2, 25, axis=0)
    q3_2 = np.percentile(curves_2, 75, axis=0)
    med_13 = np.median(curves_13, axis=0)
    q1_13 = np.percentile(curves_13, 25, axis=0)
    q3_13 = np.percentile(curves_13, 75, axis=0)
    ax.fill_between(phase, q1_2, q3_2, color="steelblue", alpha=0.25,
                    label=f"Lap {lap2['idx']} IQR")
    ax.fill_between(phase, q1_13, q3_13, color="seagreen", alpha=0.25,
                    label=f"Lap {lap13['idx']} IQR")
    ax.plot(phase, med_2, color="steelblue", linewidth=2.5,
            label=f"Lap {lap2['idx']} median")
    ax.plot(phase, med_13, color="seagreen", linewidth=2.5,
            label=f"Lap {lap13['idx']} median")
    ax.set_xlabel("Stroke phase (%)")
    ax.set_ylabel("Effective drive force (N)")
    ax.set_title("Median + IQR — does the lull shrink in glass water?")
    ax.grid(True, alpha=0.3)
    ax.legend()

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return m2, m13


def plot_metric_distributions(m2, m13, lap2_id, lap13_id, savepath):
    """Distributions of the four connection metrics across both laps."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))

    def by_lap(ms, key):
        vals = [m[key] for m in ms if np.isfinite(m.get(key, float("nan")))]
        return np.array(vals)

    # 1. Drive/catch ratio — higher = more body-dominant
    d2 = by_lap(m2, "drive_over_catch")
    d13 = by_lap(m13, "drive_over_catch")
    ax = axes[0, 0]
    bins = np.linspace(1, 6, 30)
    ax.hist(d2, bins=bins, alpha=0.55, color="steelblue",
            label=f"Lap {lap2_id} chop  (median {np.median(d2):.2f})", edgecolor="white")
    ax.hist(d13, bins=bins, alpha=0.55, color="seagreen",
            label=f"Lap {lap13_id} glass (median {np.median(d13):.2f})", edgecolor="white")
    ax.set_xlabel("Drive peak / Catch bump")
    ax.set_ylabel("Count")
    ax.set_title("Drive-over-catch ratio (higher = more connected drive dominates)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 2. Lull depth as fraction of drive peak — lower = better
    l2 = by_lap(m2, "lull_depth_frac")
    l13 = by_lap(m13, "lull_depth_frac")
    ax = axes[0, 1]
    bins = np.linspace(0, 0.8, 30)
    ax.hist(l2, bins=bins, alpha=0.55, color="steelblue",
            label=f"Lap {lap2_id} chop  (median {np.median(l2):.2f})", edgecolor="white")
    ax.hist(l13, bins=bins, alpha=0.55, color="seagreen",
            label=f"Lap {lap13_id} glass (median {np.median(l13):.2f})", edgecolor="white")
    ax.set_xlabel("Lull depth / drive peak")
    ax.set_ylabel("Count")
    ax.set_title("Lull depth fraction (lower = better, 0 = no lull)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 3. Catch-to-drive phase gap — lower = more connected
    g2 = by_lap(m2, "gap_pct")
    g13 = by_lap(m13, "gap_pct")
    ax = axes[1, 0]
    bins = np.arange(0, 60, 2)
    ax.hist(g2, bins=bins, alpha=0.55, color="steelblue",
            label=f"Lap {lap2_id} chop  (median {np.median(g2):.0f})", edgecolor="white")
    ax.hist(g13, bins=bins, alpha=0.55, color="seagreen",
            label=f"Lap {lap13_id} glass (median {np.median(g13):.0f})", edgecolor="white")
    ax.set_xlabel("Catch-to-drive gap (% stroke phase)")
    ax.set_ylabel("Count")
    ax.set_title("Phase gap from catch to drive (lower = more connected)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 4. Fraction of strokes with no distinct catch bump (single peak)
    f2 = float(np.mean([m["connected"] for m in m2]))
    f13 = float(np.mean([m["connected"] for m in m13]))
    ax = axes[1, 1]
    ax.bar([f"Lap {lap2_id}\nchop", f"Lap {lap13_id}\nglass"],
            [f2 * 100, f13 * 100],
            color=["steelblue", "seagreen"], alpha=0.85)
    ax.set_ylabel("Fraction of strokes with single peak (%)")
    ax.set_title("Single-peak (connected) strokes — higher = better technique")
    ax.set_ylim(0, max(100, max(f2, f13) * 110))
    for i, v in enumerate([f2 * 100, f13 * 100]):
        ax.text(i, v + 1, f"{v:.0f}%", ha="center", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)

    fig.suptitle("Connection metrics — chop mile (lap 2) vs glass mile (lap 13)\n"
                 "If the lull is chop-induced, glass-water metrics should be better. "
                 "If technique-induced, both should be similar.",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return f2, f13


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Collecting lap 13 (glass-water mile, slow current)...")
    feats_13, lap13 = collect_lap_strokes(kg, R, tcx, align, lap_idx=13,
                                           skip_start_s=120.0, max_strokes=100)
    print(f"  {len(feats_13)} strokes after warm-up window.")

    print("Collecting lap 2 (chop mile, strong push) for comparison...")
    feats_2, lap2 = collect_lap_strokes(kg, R, tcx, align, lap_idx=2,
                                          skip_start_s=120.0, max_strokes=100)
    print(f"  {len(feats_2)} strokes after warm-up window.")

    print("Lap 13 PERG plot...")
    m13_show = plot_lap_perg(feats_13, lap13,
                              os.path.join(PLOTS_DIR, "21_lap13_perg.png"),
                              n_show=20)

    print("Lap 2 vs Lap 13 comparison plot...")
    m2_all, m13_all = plot_lap_compare(feats_2, lap2, feats_13, lap13,
                                        os.path.join(PLOTS_DIR, "21_lap2_vs_lap13.png"),
                                        n_show=20)

    print("Connection-metric distribution plot...")
    f2, f13 = plot_metric_distributions(m2_all, m13_all, lap2["idx"], lap13["idx"],
                                          os.path.join(PLOTS_DIR, "21_connection_metrics.png"))

    # Summary text to stdout
    print("\n=== Connection metric summary ===")
    print(f"  Lap {lap2['idx']} (chop, n={len(m2_all)}):")
    print(f"    drive/catch median:     {np.median([m['drive_over_catch'] for m in m2_all]):.2f}")
    print(f"    lull depth frac median: {np.median([m['lull_depth_frac'] for m in m2_all]):.2f}")
    print(f"    phase gap median:       {np.median([m['gap_pct'] for m in m2_all]):.0f} %")
    print(f"    connected (single peak): {f2*100:.0f} %")
    print(f"  Lap {lap13['idx']} (glass, n={len(m13_all)}):")
    print(f"    drive/catch median:     {np.median([m['drive_over_catch'] for m in m13_all]):.2f}")
    print(f"    lull depth frac median: {np.median([m['lull_depth_frac'] for m in m13_all]):.2f}")
    print(f"    phase gap median:       {np.median([m['gap_pct'] for m in m13_all]):.0f} %")
    print(f"    connected (single peak): {f13*100:.0f} %")
    print("Done.")


if __name__ == "__main__":
    main()
