"""
Session 37 — find the L/R stroke-side blocks the user expects to see
(8-15 strokes per side, switching periodically).

Strategy:
  1. Per-stroke yaw integral has signal but is noisy at the individual-stroke
     level.
  2. Apply a 5-stroke moving median to the per-stroke yaw signal. The block
     structure should pop out.
  3. Also build a combined "side score" = yaw_integral - alpha * lat_demeaned
     and try it. (Lateral is biased by ama-side lean -> demean per-lap.)
  4. Plot signed side-block signal across laps 2, 3, 9, 13 and report
     run-length statistics.
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


def per_stroke_features(kg, R, tcx, align, lap_idx,
                        prominence=1.5, height=1.0, refractory_s=0.4,
                        post_s=0.3):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)
    m = (t >= lt0) & (t <= lt1)
    tt = t[m]
    fwd = A_body[m, 0]
    lat = A_body[m, 1]
    yaw = G_body[m, 2]
    if len(tt) < 50:
        return [], lap
    fs = (len(tt) - 1) / (tt[-1] - tt[0])
    strokes = detect_strokes(tt, fwd, prominence=prominence, height=height,
                             refractory_s=refractory_s)
    post = max(1, int(post_s * fs))
    dt = 1.0 / fs

    lat_mean = float(np.mean(lat))

    rows = []
    for st_t, idx in strokes:
        hi = min(len(yaw), idx + post)
        if hi <= idx:
            continue
        yaw_i = float(np.sum(yaw[idx:hi]) * dt)
        lat_i = float(np.sum(lat[idx:hi]) * dt) - lat_mean * post_s
        rows.append({
            "t_rel": st_t - lt0,
            "yaw": yaw_i,
            "lat_dm": lat_i,
        })
    return rows, lap


def moving_median(x, w=5):
    """Centered moving median, odd window. Returns same length."""
    x = np.asarray(x)
    if w <= 1:
        return x
    if w % 2 == 0:
        w += 1
    half = w // 2
    out = np.zeros_like(x, dtype=float)
    for i in range(len(x)):
        lo = max(0, i - half)
        hi = min(len(x), i + half + 1)
        out[i] = np.median(x[lo:hi])
    return out


def runs(signs):
    if not len(signs):
        return []
    out = []
    cur = int(signs[0])
    n = 1
    for s in signs[1:]:
        s = int(s)
        if s == cur:
            n += 1
        else:
            out.append((n, cur))
            cur = s
            n = 1
    out.append((n, cur))
    return out


def plot_side_blocks(kg, R, tcx, align, savepath, lap_ids=(2, 3, 9, 13),
                     smooth_w=5, alpha_lat=2.0):
    fig, axes = plt.subplots(len(lap_ids), 1, figsize=(15, 3.2 * len(lap_ids)))
    if len(lap_ids) == 1:
        axes = [axes]
    summaries = []
    for ax, li in zip(axes, lap_ids):
        rows, lap = per_stroke_features(kg, R, tcx, align, li)
        if not rows:
            ax.set_title(f"Lap {li} — no strokes")
            continue
        yaw = np.array([r["yaw"] for r in rows])
        lat = np.array([r["lat_dm"] for r in rows])
        # Combined per-stroke side score: negate lateral because LEFT stroke
        # pushes boat right (-y) so lateral_dm is negative for L; we want L to
        # be negative in the combined score (consistent with yaw sign).
        combined = yaw + alpha_lat * lat
        combined_smooth = moving_median(combined, w=smooth_w)
        raw_sign = np.sign(yaw)
        smooth_sign = np.sign(combined_smooth)
        x = np.arange(1, len(rows) + 1)

        # Background: per-stroke raw signs (small bars)
        for xi, s in zip(x, raw_sign):
            c = "crimson" if s < 0 else "navy"
            ax.bar(xi, 0.3 * s, color=c, alpha=0.25, width=1.0)
        # Foreground: smoothed combined sign as continuous line
        ax.plot(x, combined_smooth, color="black", linewidth=1.5,
                label=f"smoothed combined score (window={smooth_w})")
        # Mark sign transitions of the smoothed signal
        switches = np.where(np.diff(np.sign(combined_smooth)) != 0)[0]
        for sw in switches:
            ax.axvline(sw + 1.5, color="orange", linewidth=0.9, alpha=0.6)

        ax.axhline(0, color="black", linewidth=0.5)
        rs = runs(smooth_sign.tolist())
        run_lens = [r[0] for r in rs]
        median_run = int(np.median(run_lens)) if run_lens else 0
        max_run = int(max(run_lens)) if run_lens else 0
        in_range = float(np.mean([(r >= 8) and (r <= 15) for r in run_lens])) if run_lens else 0
        ax.set_title(
            f"Lap {li}  ({lap['distance_m']:.0f} m, {lap['duration_s']:.0f} s)  | "
            f"{len(rows)} strokes  | smoothed sign: {len(rs)} runs, "
            f"median {median_run}, max {max_run}, frac in 8-15: {in_range:.2f}"
        )
        ax.set_xlabel("Stroke # within lap")
        ax.set_ylabel("Combined side score")
        ax.grid(True, alpha=0.3)
        summaries.append({"lap": li, "n": len(rows), "runs": len(rs),
                          "median_run": median_run, "max_run": max_run,
                          "frac_in_range": in_range, "run_lens": run_lens})

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return summaries


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    summaries = plot_side_blocks(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "09_side_blocks.png"),
        lap_ids=(2, 3, 9, 13),
        smooth_w=5,
        alpha_lat=2.0,
    )
    print("\nSmoothed combined-score run statistics:")
    for s in summaries:
        rl = np.array(s["run_lens"])
        print(f"  Lap {s['lap']}: {s['n']} strokes -> {s['runs']} runs, "
              f"median {s['median_run']}, max {s['max_run']}, "
              f"fraction in 8-15: {s['frac_in_range']:.2f}")
    print("Done.")


if __name__ == "__main__":
    main()
