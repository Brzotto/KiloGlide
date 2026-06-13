"""
PERG-style per-stroke force curve display.

Concept2 PM5 / RowPro style: each individual stroke as its own force trace,
either in a small-multiples grid or overlaid on a common phase axis. Lets
you see stroke-by-stroke shape variation in a way that's lost in the
mean-curve view. Positive force = pull (blade in water); negative force =
recovery / glide (blade out, only drag decelerating the boat).

Session-aware: takes --session N (manifest default otherwise) and --lap N
(auto-picks the lap with the most strokes if omitted). Output filenames carry
the lap number so you can render several laps and compare them side by side.

Produces three plots per lap, under analysis/plots/session_N/:
  20_perg_grid_lapL.png        — individual strokes in a small-multiples grid
  20_perg_overlay_lapL.png     — same strokes overlaid with mean line on top
  20_perg_pm5_strict_lapL.png  — positive-only "pull arch" (PM5 convention)
"""

import os
import sys
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from correlate_kg_garmin import (
    load_kg, load_garmin, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, detect_strokes,
    stroke_features_for_window,
)
from session_config import get_session, add_session_arg


def _strokes_in_lap(kg, R, lap, align, skip_start_s, mass_kg, max_strokes=None):
    """Detect strokes in a mid-lap window and return their feature dicts."""
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    lt0, lt1 = lap_local_window(lap, align)
    w0 = lt0 + skip_start_s
    w1 = lt1
    m = (t >= w0) & (t <= w1)
    tt = t[m]
    fwd = A_body[m, 0]
    roll = G_body[m, 0]
    strokes = detect_strokes(tt, fwd, prominence=1.5, height=1.0, refractory_s=0.4)
    feats = stroke_features_for_window(tt, fwd, roll, strokes, mass_kg)
    return feats if max_strokes is None else feats[:max_strokes]


def pick_best_lap(kg, R, tcx, align, mass_kg, exclude=()):
    """Auto-pick the lap with the most detected strokes (a good PERG sample).
    Short pieces use a smaller skip so we don't discard the whole window."""
    best_idx, best_n = None, -1
    for lap in tcx["laps"]:
        if lap["idx"] in exclude:
            continue
        skip = 10.0 if lap["duration_s"] < 90 else 60.0
        n = len(_strokes_in_lap(kg, R, lap, align, skip, mass_kg))
        if n > best_n:
            best_idx, best_n = lap["idx"], n
    return best_idx


def collect_clean_strokes(kg, R, tcx, align, mass_kg, lap_idx,
                          skip_start_s=60.0, max_strokes=20):
    """Return N consecutive strokes from a mid-lap window of `lap_idx`.

    Drops the first detected stroke: its window starts at the clip boundary
    (no left neighbor to take a midpoint from), so its phase is distorted and
    it shows up "out of phase" in the overlay. Dropping it removes that
    edge artifact so every plotted stroke is bounded by real inter-stroke troughs.
    """
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    feats = _strokes_in_lap(kg, R, lap, align, skip_start_s, mass_kg)
    return feats[1:max_strokes + 1]


def plot_perg_grid(feats, savepath, mass_kg, title_suffix="", n_show=16):
    """Small-multiples grid of individual stroke force curves."""
    n = min(n_show, len(feats))
    if n == 0:
        return
    cols = 4
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(14, 2.4 * rows),
                              sharex=True, sharey=True)
    axes = np.atleast_1d(axes).flatten()

    # Common scale across all panels
    all_force = []
    for f in feats[:n]:
        seg = f.get("fwd_segment")
        if seg is None:
            continue
        all_force.append(seg * mass_kg)
    if not all_force:
        return
    f_max = max([np.max(np.maximum(c, 0)) for c in all_force]) * 1.1

    for i, f in enumerate(feats[:n]):
        ax = axes[i]
        seg = f.get("fwd_segment")
        if seg is None:
            ax.set_visible(False)
            continue
        force = seg * mass_kg
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

    fig.suptitle("Per-stroke force curves — Concept2 PM5 / PERG style"
                 f"{title_suffix}\n"
                 "Blue band = pull (force > 0, blade in water).  "
                 "Yellow band = glide/recovery (force < 0, only drag).",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_perg_overlay(feats, savepath, mass_kg, title_suffix="", n_show=20):
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
        force = seg * mass_kg
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
    axes[0].set_title(f"Overlay — {len(curves)} consecutive strokes{title_suffix}")
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


def plot_pm5_strict(feats, savepath, mass_kg, title_suffix="", n_show=20):
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
        force = np.maximum(seg * mass_kg, 0.0)
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
    axes[0].set_title(f"PM5-strict positive arch — {len(curves)} consecutive strokes{title_suffix}")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    # Small-multiples grid of the same positive-only strokes
    cols = 5
    rows = (n + cols - 1) // cols

    # Replace the right panel with a clean grid using gridspec.
    axes[1].remove()
    from matplotlib.gridspec import GridSpecFromSubplotSpec
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

    fig.suptitle("Your stroke on its own — recovery glide clipped out so only the pull arch shows."
                 f"{title_suffix}",
                 fontsize=11, y=0.995)
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _mean_full_curve(feats, mass_kg, n_points=101):
    """Phase-normalized MEAN force curve over a lap's strokes, keeping the
    negative (recovery/glide) portion. Returns (curve_lbf, p25, p75) or None."""
    N_TO_LBF = 0.224809
    curves = []
    for f in feats:
        seg = f.get("fwd_segment")
        if seg is None or len(seg) < 5:
            continue
        force_lbf = seg * mass_kg * N_TO_LBF
        curves.append(np.interp(np.linspace(0, 1, n_points),
                                np.linspace(0, 1, len(force_lbf)), force_lbf))
    if not curves:
        return None
    curves = np.array(curves)
    return (curves.mean(axis=0),
            np.percentile(curves, 25, axis=0),
            np.percentile(curves, 75, axis=0))


def _shape_metrics(mean_curve):
    """Technique descriptors from a lap's mean whole-stroke curve (lbf)."""
    from scipy.signal import find_peaks
    peak = float(np.max(mean_curve))
    peak_phase = float(np.argmax(mean_curve))  # 0..100 since 101 points
    pull_frac = float(np.mean(mean_curve > 0)) * 100.0
    glide_depth = float(-np.min(mean_curve))   # how hard the boat decelerates
    pos = np.maximum(mean_curve, 0.0)
    prom = max(0.5, 0.10 * peak)
    pk, _ = find_peaks(pos, height=0.10 * peak, prominence=prom, distance=5)
    n_pos_peaks = int(len(pk))
    # roughness: normalized curvature energy (jerky strokes score higher)
    d2 = np.diff(mean_curve, 2)
    roughness = float(np.sqrt(np.mean(d2 ** 2)) / peak) if peak > 0 else 0.0
    return dict(peak=peak, peak_phase=peak_phase, pull_frac=pull_frac,
                glide_depth=glide_depth, n_pos_peaks=n_pos_peaks,
                roughness=roughness)


def overlay_lap_means(kg, R, tcx, align, mass_kg, lap_list, savepath, title,
                      side_for=None):
    """Overlay the mean whole-stroke curve (pull + recovery) of several laps
    on one force axis, and return a per-lap shape-metric table for printing."""
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    fig, ax = plt.subplots(figsize=(11, 6.5))
    colors = plt.cm.turbo(np.linspace(0.05, 0.95, len(lap_list)))
    rows = []
    for c, li in zip(colors, lap_list):
        if li not in laps_by_idx:
            continue
        dur = laps_by_idx[li]["duration_s"]
        skip = 10.0 if dur < 90 else 60.0
        feats = _strokes_in_lap(kg, R, laps_by_idx[li], align, skip, mass_kg)
        res = _mean_full_curve(feats, mass_kg)
        if res is None:
            continue
        mean_c, p25, p75 = res
        phase = np.linspace(0, 100, len(mean_c))
        sm = _shape_metrics(mean_c)
        side = side_for.get(li, "?") if side_for else "?"
        lbl = (f"L{li} {side} {dur:.0f}s  pk{sm['peak']:.0f}lbf "
               f"pp{sm['peak_phase']:.0f}% np{sm['n_pos_peaks']}")
        ax.plot(phase, mean_c, color=c, linewidth=2.0, label=lbl)
        rows.append((li, side, dur, len(feats), sm))

    ax.axhline(0, color="gray", linewidth=0.7, linestyle="--")
    ax.fill_between([0, 100], 0, ax.get_ylim()[1], color="steelblue", alpha=0.04)
    ax.set_xlabel("Stroke phase (%)  —  catch → drive → exit → recovery")
    ax.set_ylabel("Effective drive force (lbf)   (+ pull in water,  − recovery/glide)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return rows


def overlay_force_vs_distance(kg, R, tcx, align, mass_kg, lap_list, savepath,
                              x_max=2.4, adaptive=True):
    """Per-stroke drive force vs BOAT DISTANCE from the catch, mean curve per lap.

    Unlike the time/phase force curves above, this puts force on a physical
    distance axis: within each stroke we reconstruct boat speed (integrate
    forward accel, anchor the stroke mean to GPS speed), integrate again to
    distance, and align every stroke at its catch. The AREA under the pull arch
    is work per stroke. This is the view that reveals leg drive — a leg-driven
    stroke is fuller/longer (force sustained over more travel) and/or does more
    work — where peak force, impulse, connection%, and the yaw side-bias do not.

    Compare MATCHED pairs (same side, adjacent in time, same conditions); a blind
    whole-session lap scan washes the contrast out by mixing sides and efforts.
    Returns a per-lap (idx, n_strokes, mean_work_J, mean_fullness) table.
    """
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]; fwd = A_body[:, 0]; roll = G_body[:, 0]
    gt, gv = kg["gps_t"], kg["gps_speed"]
    N_TO_LBF = 0.224809
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    grid = np.linspace(0, x_max, 100)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    colors = plt.cm.turbo(np.linspace(0.05, 0.95, max(1, len(lap_list))))
    rows = []
    for c, li in zip(colors, lap_list):
        if li not in laps_by_idx:
            continue
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        skip = 10.0 if lap["duration_s"] < 90 else 60.0
        m = (t >= lt0 + skip) & (t <= lt1)
        tt, aw, rr = t[m], fwd[m], roll[m]
        gm = (gt >= lt0) & (gt <= lt1)
        vmean = float(np.mean(gv[gm])) if np.any(gm) else 0.0
        strokes = detect_strokes(tt, aw, prominence=1.5, height=1.0,
                                 refractory_s=0.4,
                                 adaptive=bool(adaptive and vmean >= 1.1))
        feats = stroke_features_for_window(tt, aw, rr, strokes, mass_kg)
        curves, works, fulls = [], [], []
        for f in feats:
            seg = f.get("fwd_segment"); ts = f.get("time_segment")
            if seg is None or len(seg) < 12:
                continue
            dt = float(np.median(np.diff(ts)))
            a = seg.astype(float)
            v = np.clip(vmean + np.cumsum(a - a.mean()) * dt, 0.05, None)
            F = a * mass_kg
            d = np.cumsum(v) * dt
            pk = int(np.argmax(F)); cc = pk
            while cc > 0 and F[cc] > 0:
                cc -= 1
            pos = F > 0
            dpos = float(np.sum(v[pos]) * dt)
            work = float(np.sum(F[pos] * v[pos]) * dt)
            peak = float(F.max())
            if peak <= 0 or dpos <= 0:
                continue
            works.append(work); fulls.append(work / (peak * dpos))
            curves.append(np.interp(grid, d - d[cc], F * N_TO_LBF,
                                    left=np.nan, right=np.nan))
        if not curves:
            continue
        mean_c = np.nanmean(np.array(curves), axis=0)
        ax.plot(grid, mean_c, color=c, linewidth=2.2,
                label=f"L{li} {lap['duration_s']:.0f}s  "
                      f"work {np.mean(works):.0f} J  full {np.mean(fulls):.2f}")
        rows.append((li, len(works), float(np.mean(works)), float(np.mean(fulls))))

    ax.axhline(0, color="gray", linewidth=0.7, linestyle="--")
    ax.set_xlabel("boat distance from the catch (m)")
    ax.set_ylabel("drive force on boat (lbf)   (+ pull,  - glide)")
    ax.set_title("Per-stroke force vs distance - area under the arch = work per stroke\n"
                 "fuller/longer arch or more work = leg drive (compare MATCHED pairs)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    add_session_arg(p)
    p.add_argument("--lap", type=int, default=None,
                   help="Lap index to render (default: lap with the most strokes)")
    p.add_argument("--overlay", type=str, default=None,
                   help="Comma-separated lap indices: overlay their mean "
                        "whole-stroke curves (pull + recovery) on one axis "
                        "instead of the per-stroke plots.")
    p.add_argument("--distance", type=str, default=None,
                   help="Comma-separated lap indices: overlay per-stroke "
                        "force-vs-DISTANCE work curves (area = work/stroke). "
                        "The view that reveals leg drive; compare matched pairs "
                        "(same side, adjacent in time).")
    p.add_argument("--label", type=str, default="compare",
                   help="Filename label for --overlay output (default 'compare')")
    p.add_argument("--skip-start", type=float, default=None,
                   help="Seconds to skip at lap start before sampling strokes "
                        "(default: 10 s for short pieces, 60 s otherwise)")
    p.add_argument("--max-strokes", type=int, default=20,
                   help="Maximum number of strokes to display (default 20)")
    args = p.parse_args()

    cfg = get_session(args.session)
    mass_kg = cfg.system_mass_kg
    print(f"Loading session {cfg.session_id} ({cfg.date})...")
    kg = load_kg(cfg.kg_path)
    tcx = load_garmin(cfg.garmin_path)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    out = cfg.plots_dir

    # --- distance mode: per-stroke force-vs-distance work curves -------------
    if args.distance:
        lap_list = [int(x) for x in args.distance.split(",") if x.strip()]
        savepath = os.path.join(out, f"22_force_vs_distance_{args.label}.png")
        rows = overlay_force_vs_distance(kg, R, tcx, align, mass_kg, lap_list,
                                         savepath)
        print(f"Saved force-vs-distance overlay to {savepath}\n")
        print("lap  nstr  work(J)  fullness")
        for li, n, w, fu in rows:
            print(f"{li:3d}  {n:4d}  {w:7.0f}   {fu:.3f}")
        print("\nWork = area under the pull arch (energy into the boat per "
              "stroke). Fuller arch / more work on the leg piece of a matched "
              "pair = leg drive. Compare adjacent same-side pieces only.")
        return

    # --- overlay mode: compare mean whole-stroke curves across laps ----------
    if args.overlay:
        from correlate_kg_garmin import analyze_lap
        A_body = rotate_accel(R, kg["accel_raw"])
        G_body = rotate_gyro(R, kg["gyro_raw"])
        lap_list = [int(x) for x in args.overlay.split(",") if x.strip()]
        laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
        # Data-driven side label from the slow yaw envelope (reliable at lap level).
        side_for = {}
        for li in lap_list:
            if li in laps_by_idx:
                r = analyze_lap(kg, A_body, G_body, laps_by_idx[li], align, mass_kg)
                lf = r.get("left_time_fraction") if r else None
                side_for[li] = ("L" if lf > 0.5 else "R") if lf is not None else "?"
        savepath = os.path.join(out, f"21_stroke_overlay_{args.label}.png")
        title = (f"Session {cfg.session_id} — mean whole-stroke force "
                 f"(pull + recovery): {args.label}")
        rows = overlay_lap_means(kg, R, tcx, align, mass_kg, lap_list,
                                 savepath, title, side_for=side_for)
        print(f"Saved overlay to {savepath}\n")
        print("lap side  dur  nstr  peakLbf  peakPhase%  pull%  glideLbf  nPeaks  rough")
        for li, side, dur, nstr, sm in rows:
            print("%3d  %s  %4.0f  %4d   %6.1f     %5.0f     %5.0f   %6.1f    %3d    %.3f" % (
                li, side, dur, nstr, sm["peak"], sm["peak_phase"], sm["pull_frac"],
                sm["glide_depth"], sm["n_pos_peaks"], sm["roughness"]))
        return

    lap_idx = args.lap
    if lap_idx is None:
        lap_idx = pick_best_lap(kg, R, tcx, align, mass_kg,
                                exclude=set(cfg.exclude_laps))
        print(f"Auto-picked lap {lap_idx} (most strokes).")

    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    if lap_idx not in laps_by_idx:
        raise SystemExit(f"Lap {lap_idx} not found. Available: "
                         f"{sorted(laps_by_idx)}")
    dur = laps_by_idx[lap_idx]["duration_s"]
    skip = args.skip_start if args.skip_start is not None else (
        10.0 if dur < 90 else 60.0)

    feats = collect_clean_strokes(kg, R, tcx, align, mass_kg, lap_idx=lap_idx,
                                  skip_start_s=skip, max_strokes=args.max_strokes)
    print(f"Collected {len(feats)} consecutive strokes from mid-lap {lap_idx} "
          f"(skip {skip:.0f} s).")

    suffix = f" (lap {lap_idx})"
    out = cfg.plots_dir
    plot_perg_grid(feats, os.path.join(out, f"20_perg_grid_lap{lap_idx}.png"),
                   mass_kg, title_suffix=suffix, n_show=16)
    plot_perg_overlay(feats, os.path.join(out, f"20_perg_overlay_lap{lap_idx}.png"),
                      mass_kg, title_suffix=suffix, n_show=args.max_strokes)
    plot_pm5_strict(feats, os.path.join(out, f"20_perg_pm5_strict_lap{lap_idx}.png"),
                    mass_kg, title_suffix=suffix, n_show=args.max_strokes)
    print(f"Saved 3 PERG plots for lap {lap_idx} to {out}")


if __name__ == "__main__":
    main()
