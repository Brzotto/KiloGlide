"""Coach-facing single-page summary of session 37.

Four panels:
  1. Annotated stroke explainer (what we're measuring)
  2. Per-lap headline metrics (cadence, peak force, Connected %, glide quality)
  3. Current cost: L2 vs L13 — same effort, different speed
  4. Notes on what's reliable and what's tentative

Uses sport-familiar units: mph for speed, lbs for force, spm for cadence,
seconds for stroke timing. Native units (m/s, N) shown in parentheses where
useful for engineering reference.
"""
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, detect_strokes, lap_local_window,
    analyze_lap,
)
from session_config import get_session_from_args

MS_TO_MPH = 2.23694
N_TO_LBF = 0.224809
EXCLUDE_LAPS = {14}


def main():
    cfg = get_session_from_args()
    print(f"Loading session {cfg.session_id} ({cfg.date}, {cfg.location})...")
    kg = load_kg(cfg.kg_path)
    tcx = load_tcx(cfg.tcx_path)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t_imu = kg["imu_t"]
    fwd = A_body[:, 0]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    # Per-lap headline metrics using analyze_lap (which has Connected %, etc.)
    per_lap = {}
    for li in sorted(laps_by_idx.keys()):
        if li in EXCLUDE_LAPS:
            continue
        r = analyze_lap(kg, A_body, G_body, laps_by_idx[li], align, cfg.system_mass_kg)
        if r is None or r["n_strokes"] < 10:
            continue
        per_lap[li] = r

    # ====================================================
    # Set up figure
    # ====================================================
    fig = plt.figure(figsize=(17, 13))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.0, 1.0, 0.6],
                          hspace=0.45, wspace=0.25)

    # ====================================================
    # PANEL 1: Annotated stroke — top-left
    # ====================================================
    ax1 = fig.add_subplot(gs[0, 0])

    # Pick the longest lap as our cruise-pace sample window
    annotated_lap = max(per_lap.keys(),
                        key=lambda li: per_lap[li]["n_strokes"])
    lap_obj = laps_by_idx[annotated_lap]
    lt0, lt1 = lap_local_window(lap_obj, align)
    win_start = lt0 + 20.0
    win_end = win_start + 4.0
    m = (t_imu >= win_start) & (t_imu <= win_end)
    tw = t_imu[m] - win_start
    aw = fwd[m]

    # Convert to force in lbs (mass * accel)
    force_lbs = aw * cfg.system_mass_kg * N_TO_LBF

    ax1.plot(tw, force_lbs, color="black", linewidth=1.2)
    ax1.axhline(0, color="gray", linewidth=0.6, linestyle="--")
    ax1.fill_between(tw, 0, force_lbs, where=(force_lbs > 0),
                     color="steelblue", alpha=0.25, label="Pull (blade in water)")
    ax1.fill_between(tw, 0, force_lbs, where=(force_lbs < 0),
                     color="khaki", alpha=0.35, label="Glide (blade out, drag)")

    ax1.set_xlim(tw[0], tw[-1])

    ax1.set_xlabel("Time (seconds)")
    ax1.set_ylabel("Force on boat (lbs)")
    ax1.set_title("What we measure: forward force on the boat through a stroke\n"
                  "Sample window from a cruise lap",
                  fontsize=11, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="lower right", fontsize=9)

    # ====================================================
    # PANEL 2: Per-lap headline metrics — top-right
    # ====================================================
    ax2 = fig.add_subplot(gs[0, 1])

    laps_sorted = sorted(per_lap.keys())
    cadences = [per_lap[li]["cadence_spm"] for li in laps_sorted]
    connected = [per_lap[li]["connected_fraction"] * 100 for li in laps_sorted]
    peak_force_lbs = [per_lap[li]["mean_peak_force_N"] * N_TO_LBF for li in laps_sorted]

    # Color by direction: with-current laps reddish, against-current bluish
    # From session 37: laps 2-4 strong miles (with current), 9-13 against
    def lap_color(li):
        if li in (2, 3, 4):
            return "firebrick"
        if li == 13:
            return "steelblue"
        if li in (9, 10, 11, 12):
            return "lightsteelblue"
        return "gray"

    colors = [lap_color(li) for li in laps_sorted]

    x = np.arange(len(laps_sorted))
    w = 0.27

    # Three side-by-side metrics, normalized to fit on one axis with twin y-axes
    ax2b = ax2.twinx()

    bars1 = ax2.bar(x - w, cadences, w, color=colors, edgecolor="white",
                    alpha=0.9, label="Cadence (spm)")
    bars2 = ax2.bar(x, peak_force_lbs, w, color=colors, edgecolor="white",
                    alpha=0.6, hatch="//", label="Peak force (lbs)")
    bars3 = ax2b.bar(x + w, connected, w, color="seagreen", edgecolor="white",
                     alpha=0.7, label="Connected stroke %")

    ax2.set_xticks(x)
    ax2.set_xticklabels([f"L{li}" for li in laps_sorted], fontsize=9)
    ax2.set_ylabel("Cadence (spm)  &  Peak force (lbs)")
    ax2b.set_ylabel("Connected stroke %  (higher = better)", color="seagreen")
    ax2b.tick_params(axis="y", labelcolor="seagreen")
    ax2.set_title("Per-lap headline metrics\n"
                  "Red = current pushing you  •  Blue = current against you",
                  fontsize=11, fontweight="bold")
    ax2.grid(True, alpha=0.3, axis="y")

    # Combined legend
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2b.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8)

    # ====================================================
    # PANEL 3: Current cost story — middle-left
    # ====================================================
    ax3 = fig.add_subplot(gs[1, 0])

    # Pick fastest and slowest cruise laps for the current-cost comparison.
    # Cruise = laps with > 100 strokes (filters out short burst/test laps).
    cruise_laps = [li for li in per_lap if per_lap[li]["n_strokes"] > 100]
    if len(cruise_laps) >= 2:
        fastest = max(cruise_laps, key=lambda li: per_lap[li]["mean_speed_m_s"])
        slowest = min(cruise_laps, key=lambda li: per_lap[li]["mean_speed_m_s"])
        lf = per_lap[fastest]
        ls = per_lap[slowest]
        labels = ["Cadence\n(spm)", "Peak force\n(lbs)", "Distance per stroke\n(meters)",
                  "Boat speed\n(mph)"]
        lf_vals = [lf["cadence_spm"], lf["mean_peak_force_N"] * N_TO_LBF,
                   lf["distance_per_stroke_m"], lf["mean_speed_m_s"] * MS_TO_MPH]
        ls_vals = [ls["cadence_spm"], ls["mean_peak_force_N"] * N_TO_LBF,
                   ls["distance_per_stroke_m"], ls["mean_speed_m_s"] * MS_TO_MPH]

        x = np.arange(len(labels))
        w = 0.38
        b1 = ax3.bar(x - w/2, lf_vals, w, color="firebrick",
                     edgecolor="white",
                     label=f"L{fastest} (fastest cruise lap)")
        b2 = ax3.bar(x + w/2, ls_vals, w, color="steelblue",
                     edgecolor="white",
                     label=f"L{slowest} (slowest cruise lap)")

        for bars, vals in [(b1, lf_vals), (b2, ls_vals)]:
            for b, v in zip(bars, vals):
                ax3.text(b.get_x() + b.get_width()/2, v + 0.5,
                         f"{v:.1f}", ha="center", fontsize=9, fontweight="bold")

        ax3.set_xticks(x)
        ax3.set_xticklabels(labels, fontsize=10)
        speed_gap_mph = abs(lf_vals[3] - ls_vals[3])
        current_mph = speed_gap_mph / 2.0
        ax3.set_title(f"Conditions cost: similar effort, different result\n"
                      f"Speed gap: {speed_gap_mph:.1f} mph between L{fastest} and L{slowest}  →  "
                      f"current estimate ≈ {current_mph:.1f} mph (assumes equal effort)",
                      fontsize=11, fontweight="bold")
        ax3.grid(True, alpha=0.3, axis="y")
        ax3.legend(loc="upper right", fontsize=10)

    # ====================================================
    # PANEL 4: Glide quality across laps — middle-right
    # ====================================================
    ax4 = fig.add_subplot(gs[1, 1])

    # Recompute glide decay rate from IMU integration for each lap
    # (we have it from glide_speed_test but it's not in per_lap; quick recompute)
    decay_lbs_per_s = []  # convert m/s² to lbs of "drag force equivalent"
    speed_mph = []
    lap_labels = []
    lap_colors_glide = []

    gt = kg["gps_t"]
    gv = kg["gps_speed"]
    for li in laps_sorted:
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        m = (t_imu >= lt0) & (t_imu <= lt1)
        tt = t_imu[m]
        a_fwd = fwd[m]
        strokes = detect_strokes(tt, a_fwd, prominence=1.5, height=1.0, refractory_s=0.4)
        if len(strokes) < 10:
            continue

        decays = []
        for i in range(len(strokes) - 1):
            i0, i1 = strokes[i][1], strokes[i + 1][1]
            if i1 - i0 < 20:
                continue
            seg_t = tt[i0:i1]
            seg_a = a_fwd[i0:i1]
            dur = seg_t[-1] - seg_t[0]
            if dur < 0.6 or dur > 2.0:
                continue
            dt_arr = np.diff(seg_t)
            dv = np.cumsum(seg_a[:-1] * dt_arr)
            dv = np.insert(dv, 0, 0.0)
            peak_idx = int(np.argmax(dv))
            if peak_idx < len(dv) - 10:
                glide_t = seg_t[peak_idx:] - seg_t[peak_idx]
                glide_dv = dv[peak_idx:]
                if len(glide_t) > 5:
                    slope = np.polyfit(glide_t, glide_dv, 1)[0]
                    decays.append(slope)
        if not decays:
            continue
        med_decay_ms2 = float(np.median(decays))
        # Convert to drag force in lbs: F = m*a
        drag_lbs = abs(med_decay_ms2) * cfg.system_mass_kg * N_TO_LBF
        decay_lbs_per_s.append(drag_lbs)
        speed_mph.append(per_lap[li]["mean_speed_m_s"] * MS_TO_MPH)
        lap_labels.append(li)
        lap_colors_glide.append(lap_color(li))

    ax4.bar(range(len(lap_labels)), decay_lbs_per_s, color=lap_colors_glide,
            edgecolor="white")
    ax4.set_xticks(range(len(lap_labels)))
    ax4.set_xticklabels([f"L{li}" for li in lap_labels], fontsize=9)
    ax4.set_ylabel("Drag force during glide (lbs)")
    ax4.set_title("Drag holding you back during glide\n"
                  "Higher bar = more force opposing forward motion when blade is out",
                  fontsize=11, fontweight="bold")
    ax4.grid(True, alpha=0.3, axis="y")

    ax4.text(0.02, 0.98,
             "Drag is equivalent force in lbs (mass × deceleration).\n"
             "Counter-intuitively, slower-GPS laps can show higher drag —\n"
             "that means hull was moving fast THROUGH WATER but slow over\n"
             "ground (paddling against current).",
             transform=ax4.transAxes, fontsize=8, va="top",
             bbox=dict(facecolor="lightyellow", edgecolor="gray", alpha=0.9))

    # ====================================================
    # PANEL 5: Notes / takeaways — bottom (full width)
    # ====================================================
    ax5 = fig.add_subplot(gs[2, :])
    ax5.axis("off")

    # Compute dynamic metric ranges from this session's per-lap data
    cads = [per_lap[li]["cadence_spm"] for li in cruise_laps]
    forces = [per_lap[li]["mean_peak_force_N"] * N_TO_LBF for li in cruise_laps]
    dpses = [per_lap[li]["distance_per_stroke_m"] for li in cruise_laps]
    conns = [per_lap[li]["connected_fraction"] * 100 for li in cruise_laps]
    drags = decay_lbs_per_s  # already computed above
    duration_min = (t_imu[-1] - t_imu[0]) / 60.0

    def rng(vals, fmt):
        if not vals:
            return "n/a"
        return f"{fmt.format(min(vals))} - {fmt.format(max(vals))}"

    header = (f"WHAT WE CAN MEASURE TODAY  (Session {cfg.session_id} — "
              f"{duration_min:.0f} min, {len(kg['imu_t']):,} IMU samples, {cfg.conditions})\n")

    measures = (
        f"    Cadence:                 {rng(cads, '{:.0f}')} spm                                            (reliable)\n"
        f"    Peak force per stroke:   {rng(forces, '{:.0f}')} lbs                                            (reliable)\n"
        f"    Distance per stroke:     {rng(dpses, '{:.1f}')} m                                            (reliable)\n"
        f"    Connected stroke %:      {rng(conns, '{:.0f}')}% — how often catch-to-drive is one clean motion (reliable)\n"
        f"    Glide drag:              {rng(drags, '{:.1f}')} lbs of equivalent drag force during recovery  (reliable)\n"
    )

    narrative_lines = ""
    if cfg.summary_narrative:
        narrative_lines = "WHAT WE LEARNED THIS SESSION\n\n"
        for i, item in enumerate(cfg.summary_narrative, 1):
            # Word-wrap each item to about 100 chars
            wrapped = []
            line = f"    {i}. "
            for word in item.split():
                if len(line) + len(word) + 1 > 100 and line.strip():
                    wrapped.append(line.rstrip())
                    line = "       " + word + " "
                else:
                    line += word + " "
            wrapped.append(line.rstrip())
            narrative_lines += "\n".join(wrapped) + "\n\n"

    next_steps = (
        "WHAT WOULD MAKE THIS BETTER (next sessions)\n\n"
        "    • Comparison data from a stronger paddler with same KG setup would calibrate 'good' shapes.\n"
        "    • A few deliberate L/R bursts with the side called out would label data for per-stroke L/R.\n"
        "    • Heart rate sync from the Garmin would tie effort (HR) to mechanical output (force).\n"
    )

    notes = header + "\n" + measures + "\n" + narrative_lines + next_steps

    ax5.text(0.01, 0.98, notes, transform=ax5.transAxes,
             fontsize=9, va="top", family="monospace",
             bbox=dict(facecolor="white", edgecolor="gray", boxstyle="round,pad=0.6"))

    fig.suptitle(f"KiloGlide — Session {cfg.session_id} Summary "
                 f"({cfg.date}, {cfg.location}, {cfg.boat})",
                 fontsize=14, fontweight="bold", y=0.995)
    savepath = os.path.join(cfg.plots_dir, "00_coach_summary.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {savepath}")

    # Print a quick text summary too
    print("\n=== Session 37 headline numbers ===")
    print(f"L2  (with current):   {per_lap[2]['mean_speed_m_s']*MS_TO_MPH:.1f} mph, "
          f"{per_lap[2]['cadence_spm']:.0f} spm, "
          f"{per_lap[2]['mean_peak_force_N']*N_TO_LBF:.0f} lbs peak, "
          f"{per_lap[2]['connected_fraction']*100:.0f}% connected")
    print(f"L13 (against current): {per_lap[13]['mean_speed_m_s']*MS_TO_MPH:.1f} mph, "
          f"{per_lap[13]['cadence_spm']:.0f} spm, "
          f"{per_lap[13]['mean_peak_force_N']*N_TO_LBF:.0f} lbs peak, "
          f"{per_lap[13]['connected_fraction']*100:.0f}% connected")


if __name__ == "__main__":
    main()
