"""
Session 37 — PERG-style per-stroke force curve display.

Concept2 PM5 / RowPro style: each individual stroke as its own force trace,
either in a small-multiples grid or overlaid on a common phase axis. Lets
you see stroke-by-stroke shape variation in a way that's lost in the
mean-curve view.

Produces two plots:
  20_perg_grid.png    — 12-20 individual strokes in a small-multiples grid
  20_perg_overlay.png — same strokes overlaid with mean line on top
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
    stroke_features_for_window,
    KG_PATH, TCX_PATH, PLOTS_DIR, SYSTEM_MASS_KG,
)


def collect_clean_strokes(kg, R, tcx, align, lap_idx=2,
                          skip_start_s=60.0, max_strokes=20):
    """Return the first N strokes from a mid-lap window of `lap_idx`."""
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)
    w0 = lt0 + skip_start_s
    w1 = lt1
    m = (t >= w0) & (t <= w1)
    tt = t[m]
    fwd = A_body[m, 0]
    roll = G_body[m, 0]
    strokes = detect_strokes(tt, fwd, prominence=1.5, height=1.0, refractory_s=0.4)
    feats = stroke_features_for_window(tt, fwd, roll, strokes, SYSTEM_MASS_KG)
    return feats[:max_strokes]


def plot_perg_grid(feats, savepath, n_show=16):
    """Small-multiples grid of individual stroke force curves."""
    n = min(n_show, len(feats))
    if n == 0:
        return
    cols = 4
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(14, 2.4 * rows),
                              sharex=True, sharey=True)
    axes = axes.flatten()

    # Common scale across all panels
    all_force = []
    for f in feats[:n]:
        seg = f.get("fwd_segment")
        if seg is None:
            continue
        all_force.append(seg * SYSTEM_MASS_KG)
    if not all_force:
        return
    f_max = max([np.max(np.maximum(c, 0)) for c in all_force]) * 1.1

    for i, f in enumerate(feats[:n]):
        ax = axes[i]
        seg = f.get("fwd_segment")
        if seg is None:
            ax.set_visible(False)
            continue
        force = seg * SYSTEM_MASS_KG
        t_seg = f.get("time_segment")
        if t_seg is None or len(t_seg) != len(force):
            t_seg = np.linspace(0, f.get("duration_s", 1.0), len(force))

        # Shade pull region (positive force) light blue, glide (negative) light yellow
        positive = force > 0
        ax.fill_between(t_seg, 0, force, where=positive, color="steelblue",
                        alpha=0.4, interpolate=True)
        ax.fill_between(t_seg, force, 0, where=~positive, color="khaki",
                        alpha=0.4, interpolate=True)
        ax.plot(t_seg, force, color="black", linewidth=1.0)
        ax.axhline(0, color="gray", linewidth=0.4, linestyle="--")

        peak = float(np.max(np.maximum(force, 0)))
        impulse_pos = float(np.sum(np.maximum(force, 0)) *
                            (t_seg[1] - t_seg[0])) if len(t_seg) > 1 else 0.0
        ax.set_title(f"#{i+1}  peak {peak:.0f} N  ∫F+ {impulse_pos:.0f} N·s",
                     fontsize=9)
        ax.set_ylim(min(0, -f_max * 0.3), f_max)
        ax.grid(True, alpha=0.25)

    for j in range(n, len(axes)):
        axes[j].set_visible(False)

    # Common labels
    for ax in axes[-cols:]:
        ax.set_xlabel("Time (s)")
    for r in range(rows):
        axes[r * cols].set_ylabel("Force (N)")

    fig.suptitle("Per-stroke force curves — Concept2 PM5 / PERG style\n"
                 "Blue band = pull (force > 0, blade in water).  "
                 "Yellow band = glide/recovery (force < 0, only drag).",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_perg_overlay(feats, savepath, n_show=20):
    """Overlay individual stroke force curves on a common phase axis."""
    n = min(n_show, len(feats))
    if n == 0:
        return
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    n_points = 101
    phase = np.linspace(0, 100, n_points)

    curves = []
    colors = plt.cm.viridis(np.linspace(0, 1, n))
    for i, f in enumerate(feats[:n]):
        seg = f.get("fwd_segment")
        if seg is None or len(seg) < 5:
            continue
        force = seg * SYSTEM_MASS_KG
        c = np.interp(np.linspace(0, 1, n_points),
                      np.linspace(0, 1, len(force)), force)
        curves.append(c)
        axes[0].plot(phase, c, color=colors[i], alpha=0.7, linewidth=1.0,
                     label=f"#{i+1}")

    if curves:
        mean_curve = np.mean(curves, axis=0)
        axes[0].plot(phase, mean_curve, color="black", linewidth=3.0,
                     label="MEAN", zorder=10)

    axes[0].axhline(0, color="gray", linewidth=0.5, linestyle="--")
    axes[0].set_xlabel("Stroke phase (%)")
    axes[0].set_ylabel("Effective drive force (N)")
    axes[0].set_title(f"Overlay — {len(curves)} consecutive strokes (mid-lap 2)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(ncol=4, fontsize=7, loc="lower right")

    # Right panel: stroke-by-stroke peak / impulse / cadence
    if curves:
        peaks = [float(np.max(np.maximum(c, 0))) for c in curves]
        impulses = [float(np.sum(np.maximum(c, 0)) / 100.0 *
                          (feats[i].get("duration_s", 1.0)))
                    for i, c in enumerate(curves)]
        idx = np.arange(1, len(curves) + 1)
        ax2 = axes[1]
        ax2.bar(idx - 0.2, peaks, width=0.4, color="purple", label="peak force (N)")
        ax2b = ax2.twinx()
        ax2b.bar(idx + 0.2, impulses, width=0.4, color="darkgreen", alpha=0.7,
                 label="impulse (N·s)")
        ax2.set_xlabel("Stroke # within window")
        ax2.set_ylabel("Peak force (N)", color="purple")
        ax2b.set_ylabel("Positive impulse (N·s)", color="darkgreen")
        ax2.set_title("Per-stroke metrics within this window")
        ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_pm5_strict(feats, savepath, n_show=20):
    """Concept2-PM5-strict view: clip force to positive only.

    Removes the negative tails from the window edges (which are previous- and
    next-stroke glide), leaving only the actual pull arch. This is what an
    ergometer's force display shows — the stroke shape on its own.
    """
    n = min(n_show, len(feats))
    if n == 0:
        return
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    n_points = 101
    phase = np.linspace(0, 100, n_points)
    curves = []
    colors = plt.cm.viridis(np.linspace(0, 1, n))

    for i, f in enumerate(feats[:n]):
        seg = f.get("fwd_segment")
        if seg is None or len(seg) < 5:
            continue
        # Positive-only clamp — the PM5 force-curve convention
        force = np.maximum(seg * SYSTEM_MASS_KG, 0.0)
        c = np.interp(np.linspace(0, 1, n_points),
                      np.linspace(0, 1, len(force)), force)
        curves.append(c)
        axes[0].plot(phase, c, color=colors[i], alpha=0.6, linewidth=1.0)

    if curves:
        mean_curve = np.mean(curves, axis=0)
        median_curve = np.median(curves, axis=0)
        axes[0].plot(phase, mean_curve, color="black", linewidth=3.0,
                     label="mean", zorder=10)
        axes[0].plot(phase, median_curve, color="red", linewidth=2.0,
                     linestyle="--", label="median", zorder=11)
        axes[0].fill_between(phase,
                             np.percentile(curves, 25, axis=0),
                             np.percentile(curves, 75, axis=0),
                             color="black", alpha=0.10,
                             label="25-75 pctl band")

    axes[0].set_xlabel("Stroke phase (%)")
    axes[0].set_ylabel("Effective drive force (N) — clipped to ≥ 0")
    axes[0].set_title(f"PM5-strict positive arch — {len(curves)} consecutive strokes (mid-lap 2)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    # Small-multiples grid of the same positive-only strokes
    cols = 5
    rows = (n + cols - 1) // cols
    sub_axes = axes[1].inset_axes([0, 0, 1, 1])
    sub_axes.set_visible(False)  # placeholder, replace with proper grid

    # Easier: replace the right panel with a clean grid using gridspec.
    axes[1].remove()
    from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1])
    right_gs = GridSpecFromSubplotSpec(rows, cols, subplot_spec=gs[0, 1],
                                       wspace=0.15, hspace=0.35)
    f_max = max([np.max(c) for c in curves]) * 1.1 if curves else 1.0
    for i, c in enumerate(curves[:n]):
        ax = fig.add_subplot(right_gs[i // cols, i % cols])
        ax.fill_between(phase, 0, c, color="steelblue", alpha=0.5)
        ax.plot(phase, c, color="black", linewidth=0.8)
        ax.set_ylim(0, f_max)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"#{i+1}  {float(np.max(c)):.0f}N", fontsize=8)
        ax.grid(True, alpha=0.2)

    fig.suptitle("Your stroke on its own — recovery glide clipped out so only the pull arch shows.",
                 fontsize=11, y=0.995)
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    feats = collect_clean_strokes(kg, R, tcx, align, lap_idx=2,
                                  skip_start_s=120.0, max_strokes=20)
    print(f"Collected {len(feats)} consecutive strokes from mid-lap 2.")

    plot_perg_grid(feats, os.path.join(PLOTS_DIR, "20_perg_grid.png"),
                    n_show=16)
    plot_perg_overlay(feats, os.path.join(PLOTS_DIR, "20_perg_overlay.png"),
                       n_show=20)
    plot_pm5_strict(feats, os.path.join(PLOTS_DIR, "20_perg_pm5_strict.png"),
                     n_show=20)
    print("Done.")


if __name__ == "__main__":
    main()
