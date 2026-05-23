"""
Session 37 — stroke-phase annotation and stroke-quality ranking.

Builds on correlate_kg_garmin.py. Produces three plots in
analysis/plots/session_37/:

  05_stroke_phases.png         — labeled catch / pull / glide on 3-4 strokes
  05_quality_strip.png         — 30 s of strokes color-coded by impulse quartile
  05_best_vs_worst.png         — top-10 vs bottom-10 force curves overlaid

The "quality" metric here is per-stroke impulse (positive-area integral of
forward accel × dt), interpreted within a single hard effort (laps 2-3).
Within a constant-effort window, variation in impulse is mostly TECHNIQUE
not EFFORT — so the spread tells you which strokes were biomechanically
effective.

Caveat: with only IMU + GPS we can rank strokes RELATIVE to each other.
We don't know the paddler's metabolic cost per stroke, so "good" here means
"high boat-response impulse," not "best technique by all dimensions."
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
    stroke_features_for_window, KG_PATH, TCX_PATH, PLOTS_DIR,
    SYSTEM_MASS_KG,
)


# ------------------------------------------------------------------
# Phase annotation: catch / pull / glide on a few clean strokes
# ------------------------------------------------------------------
def plot_stroke_phases(kg, R, tcx, align, savepath, lap_idx=2, n_strokes=4):
    """Render a short cruise window with phases shaded and annotated."""
    A_body = rotate_accel(R, kg["accel_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)

    # Take a window roughly 30 s into the lap so we skip the start transient
    win_t0 = lt0 + 30.0
    win_t1 = lt1
    m = (t >= win_t0) & (t <= win_t1)
    tt = t[m]
    a_fwd = A_body[m, 0]

    strokes = detect_strokes(tt, a_fwd, prominence=1.5, height=1.0, refractory_s=0.4)
    if len(strokes) < n_strokes + 1:
        return None

    # Choose the first n_strokes strokes inside the window
    sel = strokes[:n_strokes + 1]  # +1 so we have a closing catch
    t_start = sel[0][0] - 0.3
    t_end = sel[-1][0] + 0.3
    mm = (tt >= t_start) & (tt <= t_end)
    tw = tt[mm] - t_start
    aw = a_fwd[mm]

    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(tw, aw, color="black", linewidth=1.1)
    ax.axhline(0, color="gray", linewidth=0.6, linestyle="--")

    # Shade pull (a > 0) light blue, glide (a < 0) light yellow within each stroke cycle.
    # We identify cycle boundaries by the detected catch times.
    catches = [(st_t - t_start) for st_t, _ in sel]
    for i in range(len(catches) - 1):
        cs = catches[i]
        ce = catches[i + 1]
        # Inside this cycle find the transition where a_fwd crosses zero downward
        cyc_mask = (tw >= cs) & (tw <= ce)
        cyc_t = tw[cyc_mask]
        cyc_a = aw[cyc_mask]
        if len(cyc_t) < 5:
            continue
        # Find first zero-crossing after peak
        peak_idx = int(np.argmax(cyc_a))
        zc_idx = None
        for j in range(peak_idx, len(cyc_a)):
            if cyc_a[j] <= 0:
                zc_idx = j
                break
        if zc_idx is None:
            zc_idx = len(cyc_a) - 1
        pull_end = cyc_t[zc_idx]
        ax.axvspan(cs, pull_end, color="lightblue", alpha=0.45,
                   label="PULL (catch → exit)" if i == 0 else None)
        ax.axvspan(pull_end, ce, color="khaki", alpha=0.45,
                   label="GLIDE / RECOVERY" if i == 0 else None)

    # Mark catches with arrows
    ymin, ymax = ax.get_ylim()
    for c in catches:
        ax.annotate("catch", xy=(c, ymax * 0.95), xytext=(c, ymax * 1.15),
                    ha="center", fontsize=9, color="darkblue",
                    arrowprops=dict(arrowstyle="->", color="darkblue", lw=0.8))

    ax.set_xlabel("Time (s, within the highlighted window)")
    ax.set_ylabel("Forward acceleration (m/s²)")
    ax.set_title(f"Stroke phases on Lap {lap_idx} (cruise mile) — catch, pull, glide")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.9)
    ax.text(0.01, 0.02,
            "Blue band: blade IN water, paddler pulls back → boat accelerates (+)\n"
            "Yellow band: blade OUT of water, only drag acts → boat decelerates (−)\n"
            "At cruise speed, positive area ≈ negative area each cycle.",
            transform=ax.transAxes, fontsize=8, va="bottom",
            bbox=dict(facecolor="white", edgecolor="lightgray", alpha=0.9))

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return True


# ------------------------------------------------------------------
# Quality scoring + strip plot
# ------------------------------------------------------------------
def collect_lap_features(kg, R, tcx, align, lap_idxs, prominence=1.5, height=1.0,
                         refractory_s=0.4, mass_kg=SYSTEM_MASS_KG):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    all_feats = []
    spans = {}
    for li in lap_idxs:
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        m = (t >= lt0) & (t <= lt1)
        tt = t[m]
        fwd = A_body[m, 0]
        roll = G_body[m, 0]
        strokes = detect_strokes(tt, fwd, prominence=prominence,
                                 height=height, refractory_s=refractory_s)
        feats = stroke_features_for_window(tt, fwd, roll, strokes, mass_kg)
        for f in feats:
            f["lap_idx"] = li
        all_feats.extend(feats)
        spans[li] = (lt0, lt1)
    return all_feats, spans


def plot_quality_strip(kg, R, tcx, align, savepath, lap_idxs=(2, 3)):
    """30 s strip of strokes color-coded by impulse quartile within the window."""
    feats, spans = collect_lap_features(kg, R, tcx, align, lap_idxs)
    if not feats:
        return None
    imp = np.array([f["impulse_m_s"] for f in feats])
    q1, q3 = np.percentile(imp, [25, 75])

    def cls(v):
        if v >= q3:
            return ("green", "good")
        if v <= q1:
            return ("crimson", "weak")
        return ("dimgray", "avg")

    A_body = rotate_accel(R, kg["accel_raw"])
    t = kg["imu_t"]

    # Pick a 30-s window mid-lap so the strokes look representative
    lap0, lap1 = list(spans.values())[0]
    w0 = lap0 + 60.0
    w1 = w0 + 30.0
    m = (t >= w0) & (t <= w1)
    tt = t[m] - w0
    fwd = A_body[m, 0]

    in_win = [f for f in feats if w0 <= f["t"] <= w1]

    fig, ax = plt.subplots(1, 1, figsize=(14, 5))
    ax.plot(tt, fwd, color="black", linewidth=0.7)
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")

    for f in in_win:
        color, label = cls(f["impulse_m_s"])
        ax.axvline(f["t"] - w0, color=color, alpha=0.65, linewidth=1.2)

    # Legend handles (one per category)
    handles = [
        plt.Line2D([], [], color="green", linewidth=2,
                   label=f"top 25% impulse (≥ {q3:.2f} m/s)"),
        plt.Line2D([], [], color="dimgray", linewidth=2,
                   label=f"middle 50% impulse"),
        plt.Line2D([], [], color="crimson", linewidth=2,
                   label=f"bottom 25% impulse (≤ {q1:.2f} m/s)"),
    ]
    ax.legend(handles=handles, loc="upper right", framealpha=0.9)
    ax.set_xlabel("Time within 30 s strip (s)")
    ax.set_ylabel("Forward acceleration (m/s²)")
    ax.set_title("Stroke quality ranking across Lap 2-3 — 30 s mid-mile strip\n"
                 "Within a constant-effort segment, impulse spread is mostly technique, not effort.")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return q1, q3, len(feats), len(in_win)


def plot_best_vs_worst(kg, R, tcx, align, savepath, lap_idxs=(2, 3), n=10):
    """Overlay best-10 and worst-10 force curves on a common stroke-phase axis."""
    feats, _ = collect_lap_features(kg, R, tcx, align, lap_idxs)
    if len(feats) < 2 * n:
        return None
    feats_sorted = sorted(feats, key=lambda f: f["impulse_m_s"])
    worst = feats_sorted[:n]
    best = feats_sorted[-n:]

    def resample(seg, n_pts=101):
        if seg is None or len(seg) < 2:
            return None
        return np.interp(np.linspace(0, 1, n_pts),
                         np.linspace(0, 1, len(seg)), seg)

    phase = np.linspace(0, 100, 101)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for group, color, label in [(best, "green", f"Top {n} (best)"),
                                 (worst, "crimson", f"Bottom {n} (weakest)")]:
        curves = []
        for f in group:
            r = resample(f.get("fwd_segment"))
            if r is None:
                continue
            curves.append(r * SYSTEM_MASS_KG)
        if not curves:
            continue
        for c in curves:
            axes[0].plot(phase, c, color=color, alpha=0.3, linewidth=0.8)
        axes[0].plot(phase, np.mean(curves, axis=0), color=color, linewidth=3,
                     label=f"{label} mean (n={len(curves)})")

    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].set_xlabel("Stroke phase (%)")
    axes[0].set_ylabel("Effective drive force (N)")
    axes[0].set_title("Best vs worst strokes — laps 2-3")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    # Distribution of impulse across all laps 2-3 strokes
    imp = np.array([f["impulse_m_s"] for f in feats])
    axes[1].hist(imp, bins=40, color="steelblue", edgecolor="white")
    q1, q3 = np.percentile(imp, [25, 75])
    axes[1].axvline(q1, color="crimson", linewidth=2, label=f"25th pctl = {q1:.2f}")
    axes[1].axvline(q3, color="green", linewidth=2, label=f"75th pctl = {q3:.2f}")
    axes[1].set_xlabel("Per-stroke impulse (m/s)")
    axes[1].set_ylabel("Count")
    axes[1].set_title("Impulse distribution — laps 2-3 (all strokes)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return len(best), len(worst)


def main():
    print("Loading session data...")
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Phase annotation plot...")
    plot_stroke_phases(kg, R, tcx, align,
                       os.path.join(PLOTS_DIR, "05_stroke_phases.png"),
                       lap_idx=2, n_strokes=4)

    print("Quality strip plot...")
    out = plot_quality_strip(kg, R, tcx, align,
                              os.path.join(PLOTS_DIR, "05_quality_strip.png"))
    if out:
        q1, q3, n_all, n_strip = out
        print(f"  Lap 2-3 strokes: {n_all} total, {n_strip} in 30 s strip")
        print(f"  Impulse quartiles: Q1={q1:.2f}, Q3={q3:.2f} m/s")

    print("Best vs worst plot...")
    plot_best_vs_worst(kg, R, tcx, align,
                       os.path.join(PLOTS_DIR, "05_best_vs_worst.png"))

    print("Done. Plots saved to", PLOTS_DIR)


if __name__ == "__main__":
    main()
