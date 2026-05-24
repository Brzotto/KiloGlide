"""
Session 37 — bonus visualizations: distance per stroke (DPS), heart rate
overlay, and an end-of-session summary dashboard.
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
    stroke_features_for_window, analyze_lap,
    KG_PATH, TCX_PATH, PLOTS_DIR, SYSTEM_MASS_KG,
)


# ------------------------------------------------------------------
# Distance per stroke (DPS) — over time, per-stroke and per-lap
# ------------------------------------------------------------------
def plot_dps(kg, R, tcx, align, savepath):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    gps_t = kg["gps_t"]
    gps_v = kg["gps_speed"]
    fs = (len(t) - 1) / (t[-1] - t[0])
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    # Walk the whole session of strokes
    strokes = detect_strokes(t, A_body[:, 0], prominence=1.5, height=1.0,
                              refractory_s=0.4)
    if len(strokes) < 2:
        return
    times = np.array([s[0] for s in strokes])
    periods = np.concatenate([[np.median(np.diff(times))], np.diff(times)])
    # Interpolate GPS speed at each stroke time
    speed_at_stroke = np.interp(times, gps_t, gps_v)
    dps = speed_at_stroke * periods

    # Lap assignment per stroke
    lap_at_stroke = np.zeros(len(times), dtype=int)
    for lap in tcx["laps"]:
        lt0, lt1 = lap_local_window(lap, align)
        m = (times >= lt0) & (times < lt1)
        lap_at_stroke[m] = lap["idx"]

    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
    # Top: per-stroke DPS scatter, colored by lap parity for visual separation
    colors_by_lap = plt.cm.tab20(np.linspace(0, 1, 14))
    for li in range(1, 15):
        m = lap_at_stroke == li
        if not np.any(m):
            continue
        axes[0].scatter(times[m], dps[m], s=4, color=colors_by_lap[li - 1],
                        alpha=0.7, label=f"L{li}" if m.sum() > 50 else None)
    axes[0].set_ylabel("Distance per stroke (m)")
    axes[0].set_title("Per-stroke DPS over the session (each point = one stroke)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(ncol=8, fontsize=8, loc="upper right")
    axes[0].set_ylim(0, np.percentile(dps[dps > 0], 99) * 1.2)

    # Mark Garmin lap boundaries
    for lap in tcx["laps"]:
        lt0, _ = lap_local_window(lap, align)
        axes[0].axvline(lt0, color="black", linewidth=0.4, alpha=0.4, linestyle="--")

    # Bottom: per-lap mean DPS bar chart
    lap_ids = []
    lap_dps_mean = []
    lap_dps_median = []
    for lap in tcx["laps"]:
        m = lap_at_stroke == lap["idx"]
        if np.sum(m) < 5:
            continue
        lap_ids.append(lap["idx"])
        lap_dps_mean.append(float(np.mean(dps[m])))
        lap_dps_median.append(float(np.median(dps[m])))
    x = np.arange(len(lap_ids))
    axes[1].bar(x - 0.18, lap_dps_mean, width=0.35, color="teal", label="mean")
    axes[1].bar(x + 0.18, lap_dps_median, width=0.35, color="darkblue", label="median")
    axes[1].set_xticks(x); axes[1].set_xticklabels([f"L{i}" for i in lap_ids])
    axes[1].set_ylabel("Distance per stroke (m)")
    axes[1].set_xlabel("Garmin lap")
    axes[1].set_title("Per-lap DPS — your boat run per stroke. Strong miles trade slight DPS for cadence.")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Heart rate overlay
# ------------------------------------------------------------------
def plot_heart_rate(kg, tcx, align, savepath):
    hr = tcx["hr"]
    if np.all(np.isnan(hr)) or np.nansum(hr) == 0:
        return False

    # Convert TCX UTC times to KG-local seconds
    hr_t_local = tcx["t"] - align["kg_t0_utc"]
    valid = ~np.isnan(hr)
    hr_t = hr_t_local[valid]
    hr_v = hr[valid]

    # GPS speed for overlay
    gps_t = kg["gps_t"]
    gps_v = kg["gps_speed"]

    fig, axes = plt.subplots(2, 1, figsize=(15, 7), sharex=True)
    axes[0].plot(hr_t, hr_v, color="crimson", linewidth=1.1, label="heart rate (bpm)")
    axes[0].set_ylabel("HR (bpm)")
    axes[0].set_title("Heart rate from Garmin TCX")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="upper right")

    axes[1].plot(gps_t, gps_v, color="steelblue", linewidth=0.6, alpha=0.7)
    axes[1].set_ylabel("Speed (m/s)")
    axes[1].set_xlabel("KG-local time (s)")
    axes[1].set_title("KG GPS speed for context")
    axes[1].grid(True, alpha=0.3)

    for lap in tcx["laps"]:
        lt0, _ = lap_local_window(lap, align)
        for ax in axes:
            ax.axvline(lt0, color="gray", alpha=0.3, linewidth=0.5)
            ax.text(lt0, ax.get_ylim()[1] * 0.96, f"L{lap['idx']}", fontsize=7,
                    color="gray", ha="left", va="top")

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return True


# ------------------------------------------------------------------
# Stroke shape evolution — average force curve per quarter of the session
# ------------------------------------------------------------------
def plot_stroke_evolution(kg, R, tcx, align, savepath, mass_kg=SYSTEM_MASS_KG):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    # Take only the paddling laps (skip 5 which is rest, 6-8 which are bursts)
    cruise_laps = [lap for lap in tcx["laps"]
                   if lap["idx"] in (1, 2, 3, 4, 9, 10, 11, 12, 13, 14)]
    t_starts = [lap_local_window(l, align)[0] for l in cruise_laps]
    t_ends = [lap_local_window(l, align)[1] for l in cruise_laps]
    t_min = min(t_starts); t_max = max(t_ends)
    quarters = np.linspace(t_min, t_max, 5)

    fig, ax = plt.subplots(1, 1, figsize=(13, 6))
    n_points = 101
    phase = np.linspace(0, 100, n_points)
    colors = plt.cm.viridis(np.linspace(0, 1, 4))

    for q in range(4):
        q_lo = quarters[q]
        q_hi = quarters[q + 1]
        m = (t >= q_lo) & (t < q_hi)
        if not np.any(m):
            continue
        tt = t[m]
        fwd = A_body[m, 0]
        roll = G_body[m, 0]
        strokes = detect_strokes(tt, fwd, prominence=1.5, height=1.0, refractory_s=0.4)
        feats = stroke_features_for_window(tt, fwd, roll, strokes, mass_kg)
        curves = []
        for f in feats:
            seg = f.get("fwd_segment")
            if seg is None or len(seg) < 5:
                continue
            drive = np.maximum(seg, 0.0) * mass_kg
            r = np.interp(np.linspace(0, 1, n_points),
                          np.linspace(0, 1, len(drive)), drive)
            curves.append(r)
        if not curves:
            continue
        mean_curve = np.mean(curves, axis=0)
        ax.plot(phase, mean_curve, color=colors[q], linewidth=2.5,
                label=f"Q{q+1}  ({q_lo:.0f}-{q_hi:.0f} s)  n={len(curves)}")

    ax.set_xlabel("Stroke phase (%)")
    ax.set_ylabel("Effective drive force (N)")
    ax.set_title("Stroke shape evolution across the session (Q1=start, Q4=end).\n"
                 "Drift = fatigue / technique change.")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Cadence vs speed scatter — paddling efficiency curve
# ------------------------------------------------------------------
def plot_cadence_vs_speed(per_lap, savepath):
    laps = [r for r in per_lap if r is not None and r["n_strokes"] >= 5]
    cad = [r["cadence_spm"] for r in laps]
    spd = [r["mean_speed_m_s"] for r in laps]
    dps = [r.get("distance_per_stroke_m", 0) for r in laps]
    ids = [r["lap"]["idx"] for r in laps]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    axes[0].scatter(cad, spd, s=80, c=ids, cmap="viridis",
                    edgecolor="white", linewidth=0.8)
    for c, s, i in zip(cad, spd, ids):
        axes[0].annotate(f"L{i}", (c, s), xytext=(4, 4),
                          textcoords="offset points", fontsize=8)
    axes[0].set_xlabel("Cadence (spm)")
    axes[0].set_ylabel("Mean speed (m/s)")
    axes[0].set_title("Speed vs cadence — labels are Garmin laps")
    axes[0].grid(True, alpha=0.3)

    axes[1].scatter(cad, dps, s=80, c=ids, cmap="viridis",
                    edgecolor="white", linewidth=0.8)
    for c, d, i in zip(cad, dps, ids):
        axes[1].annotate(f"L{i}", (c, d), xytext=(4, 4),
                          textcoords="offset points", fontsize=8)
    axes[1].set_xlabel("Cadence (spm)")
    axes[1].set_ylabel("Distance per stroke (m)")
    axes[1].set_title("DPS vs cadence — efficiency tradeoff")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Summary dashboard
# ------------------------------------------------------------------
def plot_dashboard(kg, R, tcx, align, per_lap, savepath):
    fig = plt.figure(figsize=(18, 11))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.0, 1.0, 1.2], hspace=0.45, wspace=0.30)

    # GPS speed overlay
    ax0 = fig.add_subplot(gs[0, :])
    kg_t_utc = kg["gps_t"] + align["kg_t0_utc"]
    ax0.plot(kg_t_utc, kg["gps_speed"], color="steelblue", linewidth=0.6, label="KG")
    ax0.plot(tcx["t"], tcx["speed"], color="firebrick", linewidth=0.6, alpha=0.85,
             label="Garmin")
    for lap in tcx["laps"]:
        ax0.axvline(lap["start_utc"], color="gray", linewidth=0.4, alpha=0.4)
        ax0.text(lap["start_utc"], ax0.get_ylim()[1] * 0.95, f"L{lap['idx']}",
                 fontsize=7, color="gray", ha="left", va="top")
    ax0.set_xlabel("UTC time")
    ax0.set_ylabel("Speed (m/s)")
    ax0.set_title("Session 37 — KG (blue) vs Garmin (red) GPS speed with lap boundaries")
    ax0.grid(True, alpha=0.3); ax0.legend(loc="upper right")
    import matplotlib.ticker as mtkr
    import datetime as dtm
    def utc_fmt(x, _):
        return dtm.datetime.fromtimestamp(x, tz=dtm.timezone.utc).strftime("%H:%M")
    ax0.xaxis.set_major_formatter(mtkr.FuncFormatter(utc_fmt))

    laps_ok = [r for r in per_lap if r is not None and r["n_strokes"] >= 5]
    idx = [r["lap"]["idx"] for r in laps_ok]

    # Force, DPS, side fraction
    ax1 = fig.add_subplot(gs[1, 0])
    ax1.bar(idx, [r["mean_peak_force_N"] for r in laps_ok], color="purple")
    ax1.set_title("Peak drive force (N)"); ax1.set_xlabel("Lap")
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs[1, 1])
    ax2.bar(idx, [r["distance_per_stroke_m"] for r in laps_ok], color="teal")
    ax2.set_title("Distance per stroke (m)"); ax2.set_xlabel("Lap")
    ax2.grid(True, alpha=0.3)

    ax3 = fig.add_subplot(gs[1, 2])
    ax3.bar(idx, [r.get("left_time_fraction", 0.5) * 100 for r in laps_ok],
            color="darkorange")
    ax3.axhline(50, color="black", linestyle="--", linewidth=0.6)
    ax3.set_title("Time on LEFT side (%)"); ax3.set_xlabel("Lap"); ax3.set_ylim(0, 100)
    ax3.grid(True, alpha=0.3)

    # Force curves
    ax4 = fig.add_subplot(gs[2, :2])
    n_points = 101
    phase = np.linspace(0, 100, n_points)
    for label, lap_idxs, color in [
        ("Strong miles (L2-3)", [2, 3], "steelblue"),
        ("Slow current mile (L13)", [13], "firebrick"),
    ]:
        curves = []
        for li in lap_idxs:
            for r in per_lap:
                if r and r["lap"]["idx"] == li:
                    for f in r["feats"]:
                        seg = f.get("fwd_segment")
                        if seg is None or len(seg) < 5:
                            continue
                        d = np.maximum(seg, 0.0) * SYSTEM_MASS_KG
                        c = np.interp(np.linspace(0, 1, n_points),
                                      np.linspace(0, 1, len(d)), d)
                        curves.append(c)
        if curves:
            mean = np.mean(curves, axis=0)
            q1 = np.percentile(curves, 25, axis=0)
            q3 = np.percentile(curves, 75, axis=0)
            ax4.plot(phase, mean, color=color, linewidth=2.5, label=f"{label} (n={len(curves)})")
            ax4.fill_between(phase, q1, q3, color=color, alpha=0.2)
    ax4.set_xlabel("Stroke phase (%)")
    ax4.set_ylabel("Effective drive force (N)")
    ax4.set_title("Force curves — strong miles vs slow-current mile")
    ax4.grid(True, alpha=0.3); ax4.legend()

    # Headline text
    ax5 = fig.add_subplot(gs[2, 2])
    ax5.axis("off")
    # Compute summary numbers
    speed_strong = float(np.mean([r["mean_speed_m_s"] for r in laps_ok
                                  if r["lap"]["idx"] in (2, 3)]))
    speed_slow = float(np.mean([r["mean_speed_m_s"] for r in laps_ok
                                 if r["lap"]["idx"] in (13,)]))
    peak_strong = float(np.mean([r["mean_peak_force_N"] for r in laps_ok
                                  if r["lap"]["idx"] in (2, 3)]))
    peak_slow = float(np.mean([r["mean_peak_force_N"] for r in laps_ok
                                if r["lap"]["idx"] in (13,)]))
    total_strokes = sum(r["n_strokes"] for r in laps_ok)
    txt = (
        f"SESSION 37 — Alameda Bay\n"
        f"2026-05-21\n"
        f"────────────────\n"
        f"Duration:     79.2 min\n"
        f"Total strokes: {total_strokes:,}\n"
        f"\n"
        f"STRONG MILES (L2-3)\n"
        f"  speed  {speed_strong:.2f} m/s\n"
        f"  force  {peak_strong:.0f} N\n"
        f"\n"
        f"SLOW MILE (L13)\n"
        f"  speed  {speed_slow:.2f} m/s\n"
        f"  force  {peak_slow:.0f} N\n"
        f"\n"
        f"CURRENT COST\n"
        f"  speed lost: {speed_strong-speed_slow:.2f} m/s\n"
        f"  effort lost: {(peak_strong-peak_slow)/peak_strong*100:.0f}%\n"
        f"\n"
        f"Same effort, different water."
    )
    ax5.text(0.02, 0.98, txt, transform=ax5.transAxes, va="top",
             fontsize=10, family="monospace",
             bbox=dict(facecolor="lightyellow", edgecolor="gold", boxstyle="round,pad=0.6"))

    fig.suptitle("KiloGlide — Session 37 Summary Dashboard", fontsize=14, y=0.995)
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    per_lap = [analyze_lap(kg, A_body, G_body, lap, align, SYSTEM_MASS_KG)
               for lap in tcx["laps"]]

    print("Building DPS plot...")
    plot_dps(kg, R, tcx, align, os.path.join(PLOTS_DIR, "15_distance_per_stroke.png"))

    print("Building heart-rate overlay...")
    ok = plot_heart_rate(kg, tcx, align,
                         os.path.join(PLOTS_DIR, "16_heart_rate.png"))
    if not ok:
        print("  (no HR data in TCX)")

    print("Building stroke evolution plot...")
    plot_stroke_evolution(kg, R, tcx, align,
                          os.path.join(PLOTS_DIR, "17_stroke_evolution.png"))

    print("Building cadence/speed/DPS scatter...")
    plot_cadence_vs_speed(per_lap,
                          os.path.join(PLOTS_DIR, "18_cadence_speed_dps.png"))

    print("Building summary dashboard...")
    plot_dashboard(kg, R, tcx, align, per_lap,
                   os.path.join(PLOTS_DIR, "19_summary_dashboard.png"))
    print("Done.")


if __name__ == "__main__":
    main()
