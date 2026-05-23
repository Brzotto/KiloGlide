"""
Session 37 — L/R switching periodicity validation.

User reports: paddles 8-15 strokes on one side, then switches. If the yaw-based
side discriminator is right, we should see clear alternating BLOCKS of negative
and positive per-stroke yaw integrals across any cruise lap.

Outputs:
  07_lap_side_timeline.png  — per-stroke yaw score across laps 2, 3, 9, 13 with
                              switches marked and runs annotated.
  07_run_length_histogram.png — distribution of consecutive-same-side runs.
  07_side_autocorrelation.png — autocorrelation of the sign signal; first
                                non-trivial peak should sit at the switch period.
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


def per_stroke_yaw(kg, R, tcx, align, lap_idx, post_s=0.3,
                   prominence=1.5, height=1.0, refractory_s=0.4):
    """Return list of (lap_relative_time_s, yaw_integral) for every detected stroke."""
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
    if len(tt) < 50:
        return [], lap
    fs = (len(tt) - 1) / (tt[-1] - tt[0])
    strokes = detect_strokes(tt, fwd, prominence=prominence, height=height,
                             refractory_s=refractory_s)
    post = max(1, int(post_s * fs))
    dt = 1.0 / fs
    out = []
    for st_t, idx in strokes:
        hi = min(len(yaw), idx + post)
        if hi <= idx:
            continue
        score = float(np.sum(yaw[idx:hi]) * dt)
        out.append((st_t - lt0, score))
    return out, lap


def runs(scores):
    """Given a sequence of scores, return list of (run_length, sign)."""
    if not scores:
        return []
    out = []
    cur_sign = 1 if scores[0] > 0 else -1
    cur_len = 1
    for s in scores[1:]:
        sg = 1 if s > 0 else -1
        if sg == cur_sign:
            cur_len += 1
        else:
            out.append((cur_len, cur_sign))
            cur_sign = sg
            cur_len = 1
    out.append((cur_len, cur_sign))
    return out


def plot_lap_timeline(kg, R, tcx, align, savepath, lap_ids=(2, 3, 9, 13)):
    fig, axes = plt.subplots(len(lap_ids), 1, figsize=(14, 3 * len(lap_ids)))
    if len(lap_ids) == 1:
        axes = [axes]
    summaries = []
    for ax, li in zip(axes, lap_ids):
        data, lap = per_stroke_yaw(kg, R, tcx, align, li)
        if not data:
            ax.set_title(f"Lap {li} — no strokes")
            continue
        idx = np.arange(1, len(data) + 1)
        scores = np.array([d[1] for d in data])
        colors = ["crimson" if s < 0 else "navy" for s in scores]

        ax.bar(idx, scores, color=colors, alpha=0.85, width=0.9)
        ax.axhline(0, color="black", linewidth=0.7)

        # Mark switch points (where sign changes between adjacent strokes)
        sign = np.sign(scores)
        switches = np.where(np.diff(sign) != 0)[0]
        for sw in switches:
            ax.axvline(sw + 1.5, color="orange", linewidth=0.8, alpha=0.7)

        rs = runs(scores.tolist())
        run_lens = [r[0] for r in rs]
        median_run = int(np.median(run_lens)) if run_lens else 0

        nL = int(np.sum(scores < 0))
        nR = int(np.sum(scores >= 0))
        ax.set_title(
            f"Lap {li}  ({lap['distance_m']:.0f} m, {lap['duration_s']:.0f} s)  | "
            f"{len(scores)} strokes, {nL} L / {nR} R  | "
            f"{len(rs)} runs, median run length = {median_run}  | "
            "crimson = L (negative yaw), navy = R (positive yaw), orange ticks = switch"
        )
        ax.set_xlabel("Stroke # within lap")
        ax.set_ylabel("Yaw integral (rad)")
        ax.grid(True, alpha=0.3)

        summaries.append({"lap": li, "n": len(scores), "runs": len(rs),
                          "median_run": median_run,
                          "run_lengths": run_lens})

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return summaries


def plot_run_length_histogram(summaries, savepath):
    all_runs = []
    for s in summaries:
        all_runs.extend(s["run_lengths"])
    if not all_runs:
        return
    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    bins = np.arange(0.5, max(all_runs) + 1.5)
    for s in summaries:
        ax.hist(s["run_lengths"], bins=bins, alpha=0.55,
                label=f"Lap {s['lap']} (n={len(s['run_lengths'])} runs, median {s['median_run']})",
                edgecolor="white")
    ax.set_xlabel("Run length (consecutive same-side strokes)")
    ax.set_ylabel("Count")
    ax.set_title("How many strokes between switches? Should cluster around 8-15.")
    ax.axvspan(8, 15, color="green", alpha=0.10, label="Expected range (8-15)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_autocorrelation(kg, R, tcx, align, savepath, lap_idx=2):
    data, _lap = per_stroke_yaw(kg, R, tcx, align, lap_idx)
    if len(data) < 50:
        return
    sign = np.array([1 if d[1] > 0 else -1 for d in data], dtype=float)
    sign = sign - sign.mean()
    # Autocorrelation
    n = len(sign)
    acorr = np.correlate(sign, sign, mode="full")[n - 1:]
    acorr = acorr / acorr[0]
    lags = np.arange(len(acorr))

    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.bar(lags[:60], acorr[:60], color="steelblue", alpha=0.85, width=0.9)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xlabel("Lag (number of strokes)")
    ax.set_ylabel("Autocorrelation of side sign")
    ax.set_title(f"Lap {lap_idx} — side-sign autocorrelation.  "
                 "First strong negative dip = half the switch period.  "
                 "First strong positive peak after lag 0 = full switch period.")
    ax.grid(True, alpha=0.3)
    ax.axvspan(8, 15, color="green", alpha=0.08, label="Expected half-period (8-15)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Computing per-stroke yaw scores and run statistics...")
    summaries = plot_lap_timeline(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "07_lap_side_timeline.png"),
        lap_ids=(2, 3, 9, 13),
    )

    print("\nPer-lap run summary:")
    for s in summaries:
        rl = np.array(s["run_lengths"])
        print(f"  Lap {s['lap']}: {s['n']} strokes, {s['runs']} runs, "
              f"median run length {s['median_run']}, "
              f"min/max = {rl.min()}/{rl.max()}, "
              f"fraction of runs in 8-15: {float(np.mean((rl >= 8) & (rl <= 15))):.2f}")

    plot_run_length_histogram(
        summaries, os.path.join(PLOTS_DIR, "07_run_length_histogram.png"))
    plot_autocorrelation(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "07_side_autocorrelation.png"),
        lap_idx=2)

    print("Done.")


if __name__ == "__main__":
    main()
