"""
Session 37 — what do the user's "connected" strokes look like?

Filter lap 13 strokes for the ones the algorithm classified as single-peak
(connected). Show those examples directly, and overlay the connected mean
against the disconnected mean to see how they differ.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from connection_metrics import (
    collect_lap_strokes, connection_metrics,
)
from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    KG_PATH, TCX_PATH, PLOTS_DIR,
)


def plot_connected_examples(metrics, lap, savepath, n_show=12):
    """Two-panel view: connected stroke examples + connected vs disconnected mean curves."""
    connected = [m for m in metrics if m["connected"]]
    disconnected = [m for m in metrics if not m["connected"]]
    print(f"  Lap {lap['idx']}: {len(connected)} connected / {len(disconnected)} disconnected strokes")
    if not connected:
        return

    fig = plt.figure(figsize=(15, 9))
    gs = fig.add_gridspec(2, 4, height_ratios=[1.4, 1.0], hspace=0.35, wspace=0.25)

    # === Top-left big panel: overlay of connected vs disconnected mean curves ===
    ax = fig.add_subplot(gs[0, :2])
    phase = np.linspace(0, 100, 101)
    c_curves = [m["curve_pos_clipped"] for m in connected]
    d_curves = [m["curve_pos_clipped"] for m in disconnected]

    for c in c_curves:
        ax.plot(phase, c, color="green", alpha=0.15, linewidth=0.6)
    for c in d_curves:
        ax.plot(phase, c, color="crimson", alpha=0.10, linewidth=0.6)

    if c_curves:
        ax.plot(phase, np.mean(c_curves, axis=0), color="green", linewidth=3.5,
                label=f"Connected mean (n={len(c_curves)})")
    if d_curves:
        ax.plot(phase, np.mean(d_curves, axis=0), color="crimson", linewidth=3.5,
                label=f"Disconnected mean (n={len(d_curves)})")
    ax.set_xlabel("Stroke phase (%)")
    ax.set_ylabel("Effective drive force (N) — clipped ≥ 0")
    ax.set_title(f"Lap {lap['idx']} — connected vs disconnected mean force curves\n"
                 "Green = single-peak strokes.  Red = strokes with a separate catch bump.")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    # === Top-right: peak force histogram by class ===
    ax = fig.add_subplot(gs[0, 2:])
    c_peaks = [m["drive_peak_N"] for m in connected]
    d_peaks = [m["drive_peak_N"] for m in disconnected]
    bins = np.linspace(0, max(c_peaks + d_peaks) * 1.05, 25)
    ax.hist(c_peaks, bins=bins, alpha=0.65, color="green",
            label=f"Connected (median {np.median(c_peaks):.0f} N)", edgecolor="white")
    ax.hist(d_peaks, bins=bins, alpha=0.65, color="crimson",
            label=f"Disconnected (median {np.median(d_peaks):.0f} N)", edgecolor="white")
    ax.set_xlabel("Drive peak (N)")
    ax.set_ylabel("Count")
    ax.set_title("Peak force comparison")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # === Bottom: 8-12 connected example strokes ===
    n = min(n_show, len(connected))
    sel = connected[:n]
    cols = 6
    rows = (n + cols - 1) // cols
    from matplotlib.gridspec import GridSpecFromSubplotSpec
    bot_gs = GridSpecFromSubplotSpec(rows, cols, subplot_spec=gs[1, :],
                                      wspace=0.15, hspace=0.30)
    f_max = max([np.max(m["curve_pos_clipped"]) for m in sel]) * 1.1
    for i, m in enumerate(sel):
        ax2 = fig.add_subplot(bot_gs[i // cols, i % cols])
        c = m["curve_pos_clipped"]
        ax2.fill_between(phase, 0, c, color="green", alpha=0.45)
        ax2.plot(phase, c, color="black", linewidth=0.8)
        ax2.plot(m["drive_phase_pct"], m["drive_peak_N"], "o",
                  color="darkgreen", markersize=4)
        ax2.set_ylim(0, f_max)
        ax2.set_xticks([]); ax2.set_yticks([])
        ax2.set_title(f"★  peak {m['drive_peak_N']:.0f} N", fontsize=8, color="darkgreen")
        ax2.grid(True, alpha=0.2)

    fig.suptitle("Your connected strokes — what 'one smooth arch' looks like on YOUR data",
                 fontsize=12, y=0.995)
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Pulling lap 13 strokes...")
    feats, lap = collect_lap_strokes(kg, R, tcx, align, lap_idx=13,
                                       skip_start_s=120.0, max_strokes=200)
    metrics = connection_metrics(feats)
    plot_connected_examples(metrics, lap,
                              os.path.join(PLOTS_DIR, "22_connected_strokes.png"),
                              n_show=12)
    print("Done.")


if __name__ == "__main__":
    main()
