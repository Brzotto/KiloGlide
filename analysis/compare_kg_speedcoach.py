"""
KG vs NK SpeedCoach — independent stroke-rate validation (general, --session N).

The SpeedCoach detects strokes with its own sensor, so it is an INDEPENDENT
ground truth for KG's accelerometer-based stroke detection. This script:

  1. Loads KG (IMU) and the NK SpeedCoach per-stroke CSV from the manifest.
  2. Time-aligns them by cross-correlating GPS speed (session logs without TIME
     records have no absolute clock; speed shape is the shared reference).
  3. Compares, over the common on-water window:
       - total stroke count   (KG detector vs NK)
       - average cadence      (spm)
       - cadence-vs-time agreement (correlation + mean abs error of the curves)
  4. Saves an overlay plot to plots/session_N/31_kg_vs_speedcoach.png.

Requires a session whose manifest entry has "nk_speedcoach" set.
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
from nk_speedcoach import load_nk
from correlate_kg_garmin import load_kg, detect_imu_axes, rotate_accel, detect_strokes
from stroke_rate_timeline import (
    find_paddling_window, rolling_median,
    DEFAULT_PROMINENCE, DEFAULT_HEIGHT, DEFAULT_REFRACTORY_S,
    DEFAULT_MIN_SPM, DEFAULT_MAX_SPM, DEFAULT_MOVE_THRESH,
    DEFAULT_MOVE_SMOOTH_S, DEFAULT_SUSTAIN_WIN,
)


def align_by_speed(kg_t, kg_v, nk_t, nk_v, search_lo, search_hi, dt=1.0):
    """Find offset O (s) so that kg_local_time ~= nk_elapsed + O, by maximizing
    Pearson correlation of GPS speed on their overlap. Returns (offset, r)."""
    nk_grid = np.arange(nk_t[0], nk_t[-1], dt)
    nk_u = np.interp(nk_grid, nk_t, nk_v)
    best_off, best_r = 0.0, -2.0
    for off in np.arange(search_lo, search_hi, dt):
        kg_at = np.interp(nk_grid + off, kg_t, kg_v, left=np.nan, right=np.nan)
        m = ~np.isnan(kg_at)
        if m.sum() < 120:           # need a couple minutes of overlap
            continue
        a, b = nk_u[m], kg_at[m]
        if a.std() < 1e-6 or b.std() < 1e-6:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        if r > best_r:
            best_r, best_off = r, float(off)
    return best_off, best_r


def build_parser():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_session_arg(p)
    p.add_argument("--prominence", type=float, default=DEFAULT_PROMINENCE)
    p.add_argument("--height", type=float, default=DEFAULT_HEIGHT)
    p.add_argument("--refractory", type=float, default=DEFAULT_REFRACTORY_S)
    p.add_argument("--min-spm", type=float, default=DEFAULT_MIN_SPM)
    p.add_argument("--max-spm", type=float, default=DEFAULT_MAX_SPM)
    p.add_argument("--move-thresh", type=float, default=DEFAULT_MOVE_THRESH)
    p.add_argument("--move-smooth", type=float, default=DEFAULT_MOVE_SMOOTH_S)
    p.add_argument("--sustain-win", type=int, default=DEFAULT_SUSTAIN_WIN)
    p.add_argument("--search-lo", type=float, default=-600.0,
                   help="min alignment offset to search (s)")
    p.add_argument("--search-hi", type=float, default=1800.0,
                   help="max alignment offset to search (s)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = get_session(args.session)
    if not cfg.nk_path:
        print(f"Session {cfg.session_id} has no nk_speedcoach in the manifest.")
        return

    print(f"Session {cfg.session_id} ({cfg.date}) — {cfg.location}")
    kg = load_kg(cfg.kg_path)
    nk = load_nk(cfg.nk_path)
    print(f"  KG IMU span: {(kg['imu_t'][-1]-kg['imu_t'][0])/60:.1f} min")
    print(f"  NK strokes: {len(nk['elapsed_s']):,} over "
          f"{nk['elapsed_s'][-1]/60:.1f} min")

    # --- Align by GPS speed ---
    offset, r = align_by_speed(kg["gps_t"], kg["gps_speed"],
                               nk["elapsed_s"], nk["speed_ms"],
                               args.search_lo, args.search_hi)
    print(f"  Alignment: NK start sits at KG-local {offset/60:.1f} min "
          f"(speed correlation r={r:.3f})")
    nk_t_kg = nk["elapsed_s"] + offset      # NK stroke times in KG-local seconds

    # --- KG strokes ---
    R, _ = detect_imu_axes(kg)
    fwd = rotate_accel(R, kg["accel_raw"])[:, 0]
    t = kg["imu_t"]
    kg_strokes = detect_strokes(t, fwd, prominence=args.prominence,
                                height=args.height, refractory_s=args.refractory)
    kg_stroke_t = np.array([st for st, _ in kg_strokes], dtype=np.float64)
    kg_mid = 0.5 * (kg_stroke_t[:-1] + kg_stroke_t[1:])
    kg_inst = 60.0 / np.diff(kg_stroke_t)

    # --- Common on-water window (intersection of KG paddle window and NK span) ---
    win_t0, win_t1 = find_paddling_window(kg["gps_t"], kg["gps_speed"],
                                          args.move_thresh, args.move_smooth)
    c0 = max(win_t0, nk_t_kg[0])
    c1 = min(win_t1, nk_t_kg[-1])
    print(f"  Common window: {c0/60:.1f}-{c1/60:.1f} min ({(c1-c0)/60:.1f} min)")

    # KG stroke count + cadence in the common window.
    kg_in = (kg_stroke_t >= c0) & (kg_stroke_t <= c1)
    kg_count = int(kg_in.sum())
    kg_pair = (kg_mid >= c0) & (kg_mid <= c1) & \
              (kg_inst >= args.min_spm) & (kg_inst <= args.max_spm)
    kg_cad = kg_inst[kg_pair]
    kg_cad_t = kg_mid[kg_pair]

    # NK stroke count + cadence in the common window.
    nk_in = (nk_t_kg >= c0) & (nk_t_kg <= c1)
    nk_count = int(nk_in.sum())
    nk_band = nk_in & (nk["stroke_rate_spm"] >= args.min_spm) & \
              (nk["stroke_rate_spm"] <= args.max_spm)
    nk_cad = nk["stroke_rate_spm"][nk_band]
    nk_cad_t = nk_t_kg[nk_band]

    kg_avg, nk_avg = float(np.mean(kg_cad)), float(np.mean(nk_cad))
    count_diff = kg_count - nk_count
    count_pct = 100.0 * count_diff / nk_count if nk_count else float("nan")

    # --- Cadence-curve agreement on a common 30 s grid ---
    grid = np.arange(c0, c1, 30.0)
    kg_g = np.interp(grid, kg_cad_t, rolling_median(kg_cad, args.sustain_win))
    nk_g = np.interp(grid, nk_cad_t, rolling_median(nk_cad, args.sustain_win))
    curve_r = float(np.corrcoef(kg_g, nk_g)[0, 1])
    mae = float(np.mean(np.abs(kg_g - nk_g)))

    # ---- Print comparison ----------------------------------------------------
    print("\n" + "=" * 64)
    print(f"  KG vs NK SpeedCoach — session {cfg.session_id}")
    print("=" * 64)
    print(f"  {'':24}{'KG':>10}{'SpeedCoach':>14}{'diff':>10}")
    print(f"  {'Strokes (common window)':24}{kg_count:>10,}{nk_count:>14,}"
          f"{count_diff:>+10,}")
    print(f"  {'Avg cadence (spm)':24}{kg_avg:>10.1f}{nk_avg:>14.1f}"
          f"{kg_avg-nk_avg:>+10.1f}")
    print(f"  Stroke-count error: {count_pct:+.1f}%")
    print(f"  Cadence-curve agreement: r={curve_r:.3f}, "
          f"mean abs error={mae:.1f} spm (30 s bins)")
    print("-" * 64)
    print(f"  Device-reported session totals (NK summary):")
    print(f"    Total strokes {nk['summary'].get('total_strokes'):.0f}, "
          f"avg {nk['summary'].get('avg_spm'):.1f} spm, "
          f"{nk['summary'].get('elapsed_s', float('nan'))/60:.1f} min")
    print("=" * 64)

    # ---- Plot ----------------------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    # (1) Alignment check — GPS speed overlay.
    axes[0].plot(kg["gps_t"] / 60.0, kg["gps_speed"], color="steelblue",
                 linewidth=0.8, label="KG GPS speed")
    axes[0].plot(nk_t_kg / 60.0, nk["speed_ms"], color="darkorange",
                 linewidth=0.8, alpha=0.7, label="SpeedCoach GPS speed (aligned)")
    axes[0].axvspan(c0 / 60.0, c1 / 60.0, color="honeydew", label="common window")
    axes[0].set_ylabel("GPS speed (m/s)")
    axes[0].set_title(f"KG vs NK SpeedCoach — session {cfg.session_id} "
                      f"({cfg.date})  |  alignment r={r:.3f}, offset {offset/60:.1f} min")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="upper right", framealpha=0.9)

    # (2) Cadence overlay (sustained rolling medians).
    axes[1].plot(kg_cad_t / 60.0, rolling_median(kg_cad, args.sustain_win),
                 color="steelblue", linewidth=1.4, label="KG cadence")
    axes[1].plot(nk_cad_t / 60.0, rolling_median(nk_cad, args.sustain_win),
                 color="darkorange", linewidth=1.4, alpha=0.8,
                 label="SpeedCoach cadence")
    axes[1].axhline(kg_avg, color="steelblue", linestyle="--", linewidth=0.9)
    axes[1].axhline(nk_avg, color="darkorange", linestyle="--", linewidth=0.9)
    axes[1].set_xlabel("Session time (min, KG-local)")
    axes[1].set_ylabel("Stroke rate (spm)")
    axes[1].set_ylim(0, args.max_spm)
    axes[1].set_title(f"Cadence agreement: r={curve_r:.3f}, "
                      f"mean abs error {mae:.1f} spm  |  "
                      f"avg KG {kg_avg:.1f} vs NK {nk_avg:.1f} spm  |  "
                      f"strokes KG {kg_count:,} vs NK {nk_count:,} ({count_pct:+.1f}%)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="upper right", framealpha=0.9)

    fig.tight_layout()
    savepath = os.path.join(cfg.plots_dir, "31_kg_vs_speedcoach.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved: {savepath}")


if __name__ == "__main__":
    main()
