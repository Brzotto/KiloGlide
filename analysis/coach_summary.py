"""Coach-facing single-page summary of a KiloGlide session.

Four panels + a notes block:
  1. Annotated stroke explainer (what we're measuring) — drawn from the
     longest cruise lap in this session.
  2. Per-lap headline metrics (cadence, peak force, Connected %).
  3. Conditions cost: fastest vs slowest cruise lap, with current estimate
     (the comparison laps are auto-picked from data).
  4. Drag holding you back during glide, per lap.
  5. Notes block with metric ranges (computed from data) and a hand-curated
     narrative pulled from sessions.json.

Uses sport-familiar units: mph for speed, lbs for force, spm for cadence,
seconds for stroke timing. Native units (m/s, N) shown in parentheses
where useful for engineering reference.
"""
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

from correlate_kg_garmin import (
    load_kg, load_garmin, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, detect_strokes, lap_local_window,
    analyze_lap,
)
from session_config import get_session_from_args, get_compare_laps
from glide_speed_test import lap_median_decay_rate

MS_TO_MPH = 2.23694
N_TO_LBF = 0.224809


def main():
    cfg = get_session_from_args()
    print(f"Loading session {cfg.session_id} ({cfg.date}, {cfg.location})...")
    kg = load_kg(cfg.kg_path)
    tcx = load_garmin(cfg.garmin_path)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t_imu = kg["imu_t"]
    fwd = A_body[:, 0]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    # Per-lap headline metrics using analyze_lap (which has Connected %, etc.)
    exclude_laps = set(cfg.exclude_laps)
    per_lap = {}
    for li in sorted(laps_by_idx.keys()):
        if li in exclude_laps:
            continue
        r = analyze_lap(kg, A_body, G_body, laps_by_idx[li], align,
                        cfg.system_mass_kg, adaptive=cfg.adaptive_strokes,
                        gap_fill=cfg.gap_fill_strokes)
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

    # Color the highlighted comparison laps with their manifest colors;
    # everything else gray. Avoids the older mistake of coloring by hardcoded
    # session-37 lap numbers (which implied direction-of-current incorrectly
    # for any other session).
    per_lap_stats = {li: {"n_strokes": per_lap[li]["n_strokes"],
                          "mean_speed_m_s": per_lap[li]["mean_speed_m_s"]}
                     for li in per_lap}
    compare = get_compare_laps(cfg, per_lap_stats)
    compare_color_by_idx = {c["idx"]: c["color"] for c in compare}

    def lap_color(li):
        return compare_color_by_idx.get(li, "gray")

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
    # Subtitle says what the colored bars mean for THIS session — labels
    # come from the manifest's compare_laps, so they describe the actual
    # conditions of those laps (not a hardcoded current-direction story).
    if compare:
        legend_bits = [f"{c['color']}: {c['label']}" for c in compare]
        subtitle = "Highlighted laps — " + "  •  ".join(legend_bits)
    else:
        subtitle = "Gray bars: no comparison laps in manifest"
    ax2.set_title("Per-lap headline metrics\n" + subtitle,
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

    # Glide drag in lbs per lap, computed via the shared helper in
    # glide_speed_test so the algorithm doesn't drift between scripts.
    decay_lbs_per_s = []
    speed_mph = []
    lap_labels = []
    lap_colors_glide = []
    for li in laps_sorted:
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        m = (t_imu >= lt0) & (t_imu <= lt1)
        tt = t_imu[m]
        a_fwd = fwd[m]
        strokes = detect_strokes(tt, a_fwd, prominence=1.5, height=1.0,
                                 refractory_s=0.4)
        if len(strokes) < 10:
            continue
        med_decay_ms2 = lap_median_decay_rate(tt, a_fwd, strokes)
        if not np.isfinite(med_decay_ms2):
            continue
        # F = m*a, convert to lbs of equivalent drag force
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

    # Print a quick text summary too. Use the same fastest/slowest cruise
    # laps that drove panel 3 so the printout matches the plot.
    print(f"\n=== Session {cfg.session_id} headline numbers ===")
    if len(cruise_laps) >= 2:
        for li, role in [(fastest, "fastest"), (slowest, "slowest")]:
            r = per_lap[li]
            print(f"L{li} ({role:>7} cruise):  "
                  f"{r['mean_speed_m_s']*MS_TO_MPH:.1f} mph, "
                  f"{r['cadence_spm']:.0f} spm, "
                  f"{r['mean_peak_force_N']*N_TO_LBF:.0f} lbs peak, "
                  f"{r['connected_fraction']*100:.0f}% connected")
    else:
        print("(not enough cruise laps for fastest/slowest comparison)")


if __name__ == "__main__":
    main()
