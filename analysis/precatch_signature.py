"""Average forward accel shape per lap, phase-normalized, to reveal the
pre-catch wiggle (or absence) statistically across hundreds of strokes."""
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

from correlate_kg_garmin import (
    load_kg, load_garmin, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, detect_strokes, lap_local_window,
)
from session_config import get_session_from_args, get_compare_laps


def phase_accel_profiles(tt, a_fwd, strokes, n_phase=201):
    """Resample forward accel between each pair of catches to common phase axis."""
    phase = np.linspace(0, 1, n_phase)
    profiles = []
    for i in range(len(strokes) - 1):
        i0 = strokes[i][1]
        i1 = strokes[i + 1][1]
        if i1 - i0 < 50:
            continue
        seg_t = tt[i0:i1]
        seg_a = a_fwd[i0:i1]
        dur = float(seg_t[-1] - seg_t[0])
        if dur < 0.6 or dur > 2.0:
            continue
        t_rel = (seg_t - seg_t[0]) / dur
        profile = np.interp(phase, t_rel, seg_a)
        profiles.append(profile)
    return phase, np.array(profiles)


def main():
    cfg = get_session_from_args()
    print(f"Loading session {cfg.session_id}...")
    kg = load_kg(cfg.kg_path)
    tcx = load_garmin(cfg.garmin_path)
    PLOTS_DIR = cfg.plots_dir
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])

    t_imu = kg["imu_t"]
    fwd = A_body[:, 0]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    # Decide which laps to compare. Use manifest's compare_laps if set;
    # otherwise auto-pick from per-lap stroke counts (need to compute first).
    if cfg.compare_laps:
        compare = list(cfg.compare_laps)
    else:
        # Quick auto-pick using stroke count from the TCX (no IMU work yet).
        # This is a fall-back; manifest is preferred.
        gt = kg["gps_t"]
        gv = kg["gps_speed"]
        per_lap_stats = {}
        for lap in tcx["laps"]:
            li = lap["idx"]
            lt0, lt1 = lap_local_window(lap, align)
            m = (t_imu >= lt0) & (t_imu <= lt1)
            if np.sum(m) < 500:
                continue
            tt = t_imu[m]
            a_fwd = fwd[m]
            strokes = detect_strokes(tt, a_fwd, prominence=1.5, height=1.0,
                                     refractory_s=0.4)
            gm = (gt >= lt0) & (gt <= lt1)
            mean_spd = float(np.mean(gv[gm])) if np.any(gm) else 0.0
            per_lap_stats[li] = {"n_strokes": len(strokes),
                                 "mean_speed_m_s": mean_spd}
        compare = get_compare_laps(cfg, per_lap_stats)

    if not compare:
        print("No comparison laps available (manifest empty and not enough "
              "cruise laps to auto-pick). Skipping.")
        return

    target_laps = [c["idx"] for c in compare]
    lap_colors = {c["idx"]: c["color"] for c in compare}
    lap_names = {c["idx"]: c["label"] for c in compare}

    # Drop any compare_laps that don't actually exist in this session's TCX,
    # so a typo or sparse manifest doesn't KeyError below.
    missing = [li for li in target_laps if li not in laps_by_idx]
    if missing:
        print(f"  Skipping lap(s) {missing} — not in session's TCX laps.")
    target_laps = [li for li in target_laps if li in laps_by_idx]
    if not target_laps:
        print("No valid comparison laps. Skipping.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))

    # --- Top-left: mean accel profile per lap overlaid ---
    ax = axes[0, 0]
    lap_data = {}
    for li in target_laps:
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        m = (t_imu >= lt0) & (t_imu <= lt1)
        tt = t_imu[m]
        a_fwd = fwd[m]
        strokes = detect_strokes(tt, a_fwd, prominence=1.5, height=1.0, refractory_s=0.4)
        phase, profiles = phase_accel_profiles(tt, a_fwd, strokes)
        if len(profiles) < 10:
            continue
        mean_p = np.mean(profiles, axis=0)
        std_p = np.std(profiles, axis=0)
        lap_data[li] = (phase, profiles, mean_p, std_p)
        ax.plot(phase * 100, mean_p, color=lap_colors[li], linewidth=2,
                label=f"{lap_names[li]}  (n={len(profiles)})")
    ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Stroke phase % (0=accel peak, 100=next accel peak)")
    ax.set_ylabel("Forward accel (m/s²)")
    ax.set_title("Mean forward-accel signature per lap")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9, loc="lower right")

    # --- Top-right: zoom on the pre-catch region (last 30% of cycle) ---
    ax = axes[0, 1]
    for li in target_laps:
        if li not in lap_data:
            continue
        phase, profiles, mean_p, std_p = lap_data[li]
        ax.plot(phase * 100, mean_p, color=lap_colors[li], linewidth=2,
                label=lap_names[li])
        ax.fill_between(phase * 100, mean_p - std_p, mean_p + std_p,
                        color=lap_colors[li], alpha=0.15)
    ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
    ax.set_xlim(60, 100)
    ax.set_xlabel("Stroke phase % (zoomed on pre-catch region)")
    ax.set_ylabel("Forward accel (m/s²)")
    ax.set_title("Pre-catch region zoom (60-100% of cycle)\n±1 std band shows chop noise")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9, loc="upper left")

    # --- Bottom-left: zero-crossing rate within glide phase per lap ---
    # (proxy for noise/wiggle in glide)
    ax = axes[1, 0]
    zc_rates = []
    zc_lap_idxs = []  # laps that actually contributed data
    for li in target_laps:
        if li not in lap_data:
            continue
        phase, profiles, _, _ = lap_data[li]
        glide_slice = (phase >= 0.15) & (phase <= 0.85)
        per_stroke_zcs = []
        for prof in profiles:
            g = prof[glide_slice]
            zcs = np.sum(np.diff(np.sign(g)) != 0)
            per_stroke_zcs.append(zcs)
        if not per_stroke_zcs:
            continue
        zc_rates.append(per_stroke_zcs)
        zc_lap_idxs.append(li)

    if zc_rates:
        bp = ax.boxplot(zc_rates,
                        tick_labels=[f"L{li}" for li in zc_lap_idxs],
                        patch_artist=True)
        for patch, li in zip(bp["boxes"], zc_lap_idxs):
            patch.set_facecolor(lap_colors[li])
            patch.set_alpha(0.6)
    else:
        ax.text(0.5, 0.5, "(no laps with enough strokes)", ha="center",
                va="center", transform=ax.transAxes, fontsize=10, color="gray")
    ax.set_ylabel("Zero-crossings within glide (15-85% phase)")
    ax.set_title("Glide noise per stroke\n(more zero-crossings = more body/chop wiggle)")
    ax.grid(True, alpha=0.3, axis="y")

    # --- Bottom-right: summary metrics ---
    ax = axes[1, 1]
    ax.axis("off")
    rows = ["Lap        Pre-catch min %   Pre-catch min value   Mean ZCs in glide"]
    rows.append("-" * 70)
    # Build a clean lookup from lap_idx -> mean ZCs so the row builder doesn't
    # depend on positional alignment with zc_rates.
    mean_zcs_by_lap = {li: float(np.mean(z)) for li, z in zip(zc_lap_idxs, zc_rates)}
    for li in target_laps:
        if li not in lap_data:
            continue
        phase, profiles, mean_p, _ = lap_data[li]
        tail_slice = (phase >= 0.65) & (phase <= 0.95)
        idx_in_tail = np.argmin(mean_p[tail_slice])
        min_phase = phase[tail_slice][idx_in_tail] * 100
        min_val = mean_p[tail_slice][idx_in_tail]
        mean_zcs = mean_zcs_by_lap.get(li, float("nan"))
        rows.append(f"L{li:<3d}       {min_phase:6.1f}%          {min_val:+5.2f} m/s²"
                    f"            {mean_zcs:5.1f}")
    ax.text(0.05, 0.95, "\n".join(rows), transform=ax.transAxes, fontsize=10,
            va="top", family="monospace",
            bbox=dict(facecolor="lightyellow", edgecolor="gray"))

    fig.suptitle("Pre-catch signature — averaged over hundreds of strokes",
                 fontsize=13, fontweight="bold", y=1.00)
    fig.tight_layout()
    savepath = os.path.join(PLOTS_DIR, "34_precatch_signature.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {savepath}")


if __name__ == "__main__":
    main()
