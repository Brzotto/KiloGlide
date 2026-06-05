"""
Within-stroke speed from IMU integration — two-tier glide analysis.

Tier 1 (IMU-only, current-independent, always available):
  - Decay rate (m/s²): linear deceleration during glide phase
  - Pull delta-v (m/s): speed gained during pull
  - Speed lost in glide (m/s): speed lost from peak to next catch
  - Pull / glide timing (s and % of cycle)
  - Phase-normalized speed profile (zero-mean shape)

Tier 2 (GPS-enhanced, requires paired GPS or Garmin):
  - Absolute speed level (m/s over ground)
  - Speed retained ratio (v_end / v_peak)
  - DPS context from Garmin laps

Tier 1 metrics are computed from raw integration (no GPS anchoring).
Current doesn't produce acceleration, so delta-v from IMU integration
is speed change through water, not over ground. Slopes and differences
from integration are therefore current-independent.
"""
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

# Laps to exclude from cross-lap summaries (different stroke regime).
# L14 = cool-down paddle to dock, very short dabs not full strokes.
EXCLUDE_LAPS = {14}


def _find_zero_crossing(arr, start, direction):
    """Find first zero-crossing index from start going in direction (+1 or -1).

    direction=+1: find where arr goes from negative to positive (upward).
    direction=-1: find where arr goes from positive to negative (downward).
    Returns index of the first sample after the crossing, or None.
    """
    for j in range(start, len(arr) - 1):
        if direction == -1 and arr[j] >= 0 and arr[j + 1] < 0:
            return j + 1
        if direction == +1 and arr[j] <= 0 and arr[j + 1] > 0:
            return j + 1
    return None


def compute_glide_metrics(tt, a_fwd, strokes, gps_speed_at_imu=None):
    """Per-stroke glide metrics from IMU integration.

    Stroke windows run from accel-peak to accel-peak. Within each window
    we find zero-crossings to identify blade exit (downward crossing after
    peak) and blade entry (upward crossing before next peak). This gives
    true pull and glide durations.

    Tier 1 (IMU-only) metrics are always computed from raw delta-v.
    Tier 2 (GPS) metrics are added when gps_speed_at_imu is provided.
    """
    results = []
    n = len(strokes)
    for i in range(n - 1):
        i0 = strokes[i][1]
        i1 = strokes[i + 1][1]
        if i1 - i0 < 20:
            continue

        seg_t = tt[i0:i1]
        seg_a = a_fwd[i0:i1]
        dt_arr = np.diff(seg_t)
        dur = float(seg_t[-1] - seg_t[0])

        # ---- Tier 1: IMU-only integration ----
        dv = np.cumsum(seg_a[:-1] * dt_arr)
        dv = np.insert(dv, 0, 0.0)

        peak_idx = int(np.argmax(dv))
        pull_dv = float(dv[peak_idx])
        end_dv = float(dv[-1])
        glide_loss = pull_dv - end_dv

        # Decay rate: slope of delta-v from peak to end (current-independent)
        decay_rate = np.nan
        if peak_idx < len(dv) - 10:
            glide_t = seg_t[peak_idx:] - seg_t[peak_idx]
            glide_dv = dv[peak_idx:]
            if len(glide_t) > 5:
                decay_rate = float(np.polyfit(glide_t, glide_dv, 1)[0])

        # ---- Phase timing from zero-crossings ----
        # Window starts at accel peak (mid-pull). Within this window:
        #   blade_exit: first downward zero-crossing after start (a goes + to -)
        #   blade_entry: last upward zero-crossing before end (a goes - to +)
        #
        # Full pull = previous blade_entry to this blade_exit
        # Pure glide = this blade_exit to next blade_entry
        #
        # For the CURRENT stroke we can measure:
        #   exit_offset: time from accel peak to blade exit (2nd half of pull)
        #   entry_offset: time from next blade entry to next accel peak (1st half of next pull)
        #   glide_duration: blade exit to next blade entry (blade fully out of water)

        exit_idx = _find_zero_crossing(seg_a, 0, direction=-1)
        # Search backward from end for the last upward crossing
        entry_idx = None
        for j in range(len(seg_a) - 2, 0, -1):
            if seg_a[j] <= 0 and seg_a[j + 1] > 0:
                entry_idx = j + 1
                break

        if exit_idx is not None and entry_idx is not None and entry_idx > exit_idx:
            blade_exit_t = float(seg_t[exit_idx])
            blade_entry_t = float(seg_t[entry_idx])
            exit_offset_s = blade_exit_t - float(seg_t[0])
            entry_offset_s = float(seg_t[-1]) - blade_entry_t
            glide_duration_s = blade_entry_t - blade_exit_t
            # Full pull = entry_offset of THIS stroke + exit_offset of THIS stroke
            # approximates the blade-in-water time centered on the accel peak.
            # More precisely: previous entry_offset + this exit_offset, but since
            # the stroke is roughly symmetric, this_entry ≈ prev_entry.
            pull_duration_s = exit_offset_s + entry_offset_s
            pull_frac = pull_duration_s / dur if dur > 0 else 0.0
        else:
            exit_offset_s = np.nan
            entry_offset_s = np.nan
            glide_duration_s = np.nan
            pull_duration_s = np.nan
            pull_frac = np.nan

        # Zero-mean shape for phase normalization (current-independent)
        dv_shape = dv - np.mean(dv)

        entry = {
            # Tier 1: current-independent
            "t": seg_t,
            "dv": dv,
            "dv_shape": dv_shape,
            "dur_s": dur,
            "pull_dv": pull_dv,
            "glide_loss": glide_loss,
            "net_dv": end_dv,
            "decay_rate": decay_rate,
            "pull_duration_s": pull_duration_s,
            "glide_duration_s": glide_duration_s,
            "pull_frac": pull_frac,
            "exit_offset_s": exit_offset_s,
            "entry_offset_s": entry_offset_s,
            "stroke_idx": i,
        }

        # ---- Tier 2: GPS-enhanced (optional) ----
        if gps_speed_at_imu is not None:
            seg_gps = gps_speed_at_imu[i0:i1]
            gps_mean = float(np.mean(seg_gps))
            dv_anchored = dv - np.mean(dv) + gps_mean
            entry["gps_speed"] = seg_gps
            entry["gps_mean"] = gps_mean
            entry["imu_speed_anchored"] = dv_anchored
            entry["v_peak_abs"] = float(dv_anchored[peak_idx])
            entry["v_end_abs"] = float(dv_anchored[-1])
            entry["v_start_abs"] = float(dv_anchored[0])
            if entry["v_peak_abs"] > 0.1:
                entry["speed_retained"] = entry["v_end_abs"] / entry["v_peak_abs"]

        results.append(entry)
    return results


def lap_median_decay_rate(tt, a_fwd, strokes, min_dur=0.6, max_dur=2.0):
    """Median glide-phase deceleration (m/s²) across all valid strokes in a lap.

    Helper for callers that want the headline lap-level decay rate without
    pulling in the full per-stroke metrics list. Same math as the per-stroke
    `compute_glide_metrics` decay_rate, just aggregated.
    """
    decays = []
    for i in range(len(strokes) - 1):
        i0, i1 = strokes[i][1], strokes[i + 1][1]
        if i1 - i0 < 20:
            continue
        seg_t = tt[i0:i1]
        seg_a = a_fwd[i0:i1]
        dur = seg_t[-1] - seg_t[0]
        if dur < min_dur or dur > max_dur:
            continue
        dt_arr = np.diff(seg_t)
        dv = np.cumsum(seg_a[:-1] * dt_arr)
        dv = np.insert(dv, 0, 0.0)
        peak_idx = int(np.argmax(dv))
        if peak_idx >= len(dv) - 10:
            continue
        glide_t = seg_t[peak_idx:] - seg_t[peak_idx]
        glide_dv = dv[peak_idx:]
        if len(glide_t) <= 5:
            continue
        decays.append(float(np.polyfit(glide_t, glide_dv, 1)[0]))
    if not decays:
        return np.nan
    return float(np.median(decays))


def filter_strokes(strokes, min_dur=0.6, max_dur=2.0, min_pull_dv=0.05):
    """Remove outlier strokes using IMU-only criteria."""
    good = []
    for s in strokes:
        if s["dur_s"] < min_dur or s["dur_s"] > max_dur:
            continue
        if s["pull_dv"] < min_pull_dv:
            continue
        if not np.isfinite(s["decay_rate"]):
            continue
        if not np.isfinite(s.get("pull_duration_s", np.nan)):
            continue
        if s["glide_loss"] > s["pull_dv"] * 3:
            continue
        good.append(s)
    return good


def phase_normalize_shape(strokes, n_phase=101):
    """Resample zero-mean dv_shape to common phase axis (current-independent)."""
    phase = np.linspace(0, 1, n_phase)
    profiles = []
    for s in strokes:
        t_rel = s["t"] - s["t"][0]
        dur = t_rel[-1]
        if dur < 0.3:
            continue
        profile = np.interp(phase, t_rel / dur, s["dv_shape"])
        profiles.append(profile)
    return phase, np.array(profiles)


def phase_normalize_abs(strokes, n_phase=101):
    """Resample GPS-anchored speed to common phase axis (Tier 2)."""
    phase = np.linspace(0, 1, n_phase)
    profiles = []
    for s in strokes:
        if "imu_speed_anchored" not in s:
            continue
        t_rel = s["t"] - s["t"][0]
        dur = t_rel[-1]
        if dur < 0.3:
            continue
        profile = np.interp(phase, t_rel / dur, s["imu_speed_anchored"])
        profiles.append(profile)
    return phase, np.array(profiles)


def main():
    cfg = get_session_from_args()
    print(f"Loading session {cfg.session_id}...")
    kg = load_kg(cfg.kg_path)
    tcx = load_garmin(cfg.garmin_path)
    PLOTS_DIR = cfg.plots_dir
    align = align_kg_to_garmin(kg, tcx)
    R, axes_info = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])

    t_imu = kg["imu_t"]
    fwd = A_body[:, 0]
    gt = kg["gps_t"]
    gv = kg["gps_speed"]

    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    has_gps = len(gt) > 0

    # ---- Analyze every lap ----
    all_lap_data = {}
    for lap_idx in sorted(laps_by_idx.keys()):
        lap = laps_by_idx[lap_idx]
        lt0, lt1 = lap_local_window(lap, align)
        m = (t_imu >= lt0) & (t_imu <= lt1)
        if np.sum(m) < 500:
            continue
        tt = t_imu[m]
        a_fwd = fwd[m]

        strokes_det = detect_strokes(tt, a_fwd, prominence=1.5, height=1.0, refractory_s=0.4)
        if len(strokes_det) < 5:
            continue

        gps_at_imu = None
        gps_mean = np.nan
        if has_gps:
            gps_m = (gt >= lt0 - 5) & (gt <= lt1 + 5)
            if np.any(gps_m):
                gps_at_imu = np.interp(tt, gt[gps_m], gv[gps_m])
                gps_lap_m = (gt >= lt0) & (gt <= lt1)
                gps_mean = float(np.mean(gv[gps_lap_m])) if np.any(gps_lap_m) else np.nan

        raw = compute_glide_metrics(tt, a_fwd, strokes_det, gps_at_imu)
        filtered = filter_strokes(raw)

        all_lap_data[lap_idx] = {
            "raw": raw,
            "filtered": filtered,
            "gps_mean_speed": gps_mean,
        }
        n_dropped = len(raw) - len(filtered)
        gps_str = f", GPS mean {gps_mean:.2f} m/s" if np.isfinite(gps_mean) else ""
        print(f"  Lap {lap_idx:2d}: {len(raw):3d} strokes, {n_dropped:3d} filtered out, "
              f"{len(filtered):3d} clean{gps_str}")

    # Pick the comparison laps from manifest or auto-fall-back to data.
    # Used in the "key laps" overlay panels and the phase diagnostic.
    per_lap_stats = {li: {"n_strokes": len(d["raw"]),
                          "mean_speed_m_s": d["gps_mean_speed"]}
                     for li, d in all_lap_data.items() if li not in EXCLUDE_LAPS}
    compare = get_compare_laps(cfg, per_lap_stats)

    # ================================================================
    # PLOT 1: Tier 1 — IMU-only glide metrics across laps
    # ================================================================
    print("\n--- Plot 1: Tier 1 (IMU-only, current-independent) ---")
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Collect per-lap Tier 1 summaries
    t1 = {}  # lap_idx -> dict of medians
    for li in sorted(all_lap_data.keys()):
        if li in EXCLUDE_LAPS:
            continue
        d = all_lap_data[li]
        f = d["filtered"]
        if len(f) < 10:
            continue
        decays = [s["decay_rate"] for s in f]
        pull_dvs = [s["pull_dv"] for s in f]
        glide_losses = [s["glide_loss"] for s in f]
        pull_durs = [s["pull_duration_s"] for s in f]
        glide_durs = [s["glide_duration_s"] for s in f]
        total_durs = [s["dur_s"] for s in f]
        pull_fracs = [s["pull_frac"] for s in f if np.isfinite(s["pull_frac"])]
        t1[li] = {
            "decay_rate": np.median(decays),
            "pull_dv": np.median(pull_dvs),
            "glide_loss": np.median(glide_losses),
            "pull_dur": np.median(pull_durs),
            "glide_dur": np.median(glide_durs),
            "pull_frac": np.median(pull_fracs) if pull_fracs else np.nan,
            "cadence": 60.0 / np.median(total_durs),
            "n": len(f),
        }

    laps_t1 = sorted(t1.keys())
    # Color the comparison laps using the manifest palette; everything else gray.
    compare_color_by_idx = {c["idx"]: c["color"] for c in compare}
    colors_t1 = [compare_color_by_idx.get(li, "gray") for li in laps_t1]

    # Top-left: decay rate (the primary glide metric)
    ax = axes[0, 0]
    ax.bar(range(len(laps_t1)), [t1[li]["decay_rate"] for li in laps_t1],
           color=colors_t1, edgecolor="white")
    ax.set_xticks(range(len(laps_t1)))
    ax.set_xticklabels([f"L{l}" for l in laps_t1], fontsize=8)
    ax.set_ylabel("Decay rate (m/s²)")
    ax.set_title("Glide decay rate per lap (current-independent)")
    ax.grid(True, alpha=0.3, axis="y")
    ax.axhline(0, color="black", linewidth=0.5)

    # Top-right: pull delta-v vs glide loss
    ax = axes[0, 1]
    x = np.arange(len(laps_t1))
    w = 0.35
    ax.bar(x - w/2, [t1[li]["pull_dv"] for li in laps_t1], w,
           color="lightblue", edgecolor="white", label="pull delta-v")
    ax.bar(x + w/2, [t1[li]["glide_loss"] for li in laps_t1], w,
           color="salmon", edgecolor="white", label="glide loss")
    ax.set_xticks(x)
    ax.set_xticklabels([f"L{l}" for l in laps_t1], fontsize=8)
    ax.set_ylabel("Speed change (m/s)")
    ax.set_title("Pull gain vs glide loss per lap")
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend()

    # Bottom-left: phase timing stacked bars
    ax = axes[1, 0]
    pull_durs = [t1[li]["pull_dur"] for li in laps_t1]
    glide_durs = [t1[li]["glide_dur"] for li in laps_t1]
    ax.bar(range(len(laps_t1)), pull_durs, color="lightblue",
           edgecolor="white", label="pull (s)")
    ax.bar(range(len(laps_t1)), glide_durs, bottom=pull_durs,
           color="khaki", edgecolor="white", label="glide (s)")
    ax.set_xticks(range(len(laps_t1)))
    ax.set_xticklabels([f"L{l}" for l in laps_t1], fontsize=8)
    ax.set_ylabel("Duration (s)")
    ax.set_title("Pull (blade in water) vs glide (blade out) per lap")
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend()

    # Bottom-right: phase-normalized SHAPE (zero-mean, current-independent)
    ax = axes[1, 1]
    key_laps = [c for c in compare
                if c["idx"] in all_lap_data
                and len(all_lap_data[c["idx"]]["filtered"]) >= 10]
    for c in key_laps:
        li = c["idx"]
        phase, profiles = phase_normalize_shape(all_lap_data[li]["filtered"])
        if len(profiles) == 0:
            continue
        mean_p = np.mean(profiles, axis=0)
        ax.plot(phase * 100, mean_p, color=c["color"],
                linewidth=2, label=c["label"])
    ax.set_xlabel("Stroke phase (%)")
    ax.set_ylabel("Delta-v from mean (m/s)")
    ax.set_title("Speed profile SHAPE — zero-mean, current-independent")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.axhline(0, color="black", linewidth=0.5, linestyle=":")

    fig.suptitle("Tier 1: IMU-only glide metrics (current-independent)",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    path1 = os.path.join(PLOTS_DIR, "31_glide_tier1_imu.png")
    fig.savefig(path1, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {path1}")

    # ================================================================
    # PLOT 2: Tier 2 — GPS-enhanced (when available)
    # ================================================================
    if has_gps:
        print("\n--- Plot 2: Tier 2 (GPS-enhanced) ---")
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # Collect Tier 2 per-lap
        t2 = {}
        for li in laps_t1:
            d = all_lap_data[li]
            f = d["filtered"]
            retains = [s["speed_retained"] for s in f
                       if "speed_retained" in s]
            if len(retains) < 5:
                continue
            t2[li] = {
                "speed_retained": np.median(retains),
                "gps_mean": d["gps_mean_speed"],
            }

        laps_t2 = sorted(t2.keys())
        colors_t2 = [compare_color_by_idx.get(li, "gray") for li in laps_t2]

        # Top-left: speed retained per lap
        ax = axes[0, 0]
        ax.bar(range(len(laps_t2)),
               [t2[li]["speed_retained"] for li in laps_t2],
               color=colors_t2, edgecolor="white")
        ax.set_xticks(range(len(laps_t2)))
        ax.set_xticklabels([f"L{l}" for l in laps_t2], fontsize=8)
        ax.set_ylabel("Speed retained (v_end / v_peak)")
        ax.set_title("Speed retained per lap (GPS-anchored, current-dependent)")
        ax.grid(True, alpha=0.3, axis="y")

        # Top-right: decay rate vs GPS speed
        ax = axes[0, 1]
        gps_speeds = [t2[li]["gps_mean"] for li in laps_t2]
        decays = [t1[li]["decay_rate"] for li in laps_t2]
        ax.scatter(gps_speeds, decays, s=60, c=colors_t2, edgecolor="black", zorder=3)
        for j, li in enumerate(laps_t2):
            ax.annotate(f"L{li}", (gps_speeds[j], decays[j]),
                        textcoords="offset points", xytext=(5, 5), fontsize=8)
        ax.set_xlabel("Mean GPS speed over ground (m/s)")
        ax.set_ylabel("Glide decay rate (m/s²)")
        ax.set_title("Decay (Tier 1) vs GPS speed (Tier 2)\n"
                     "inverted trend = current bias in GPS")
        ax.grid(True, alpha=0.3)
        if len(gps_speeds) > 3:
            coeffs = np.polyfit(gps_speeds, decays, 1)
            xs = np.linspace(min(gps_speeds), max(gps_speeds), 50)
            ax.plot(xs, np.polyval(coeffs, xs), "r--", linewidth=1)
            r = np.corrcoef(gps_speeds, decays)[0, 1]
            ax.set_title(f"Decay (Tier 1) vs GPS speed (Tier 2)\n"
                         f"r = {r:.2f} — inverted trend = current bias in GPS")

        # Bottom-left: absolute speed profiles (GPS-anchored)
        ax = axes[1, 0]
        for c in key_laps:
            li = c["idx"]
            phase, profiles = phase_normalize_abs(all_lap_data[li]["filtered"])
            if len(profiles) == 0:
                continue
            mean_p = np.mean(profiles, axis=0)
            ax.plot(phase * 100, mean_p, color=c["color"],
                    linewidth=2, label=c["label"])
        ax.set_xlabel("Stroke phase (%)")
        ax.set_ylabel("Speed over ground (m/s)")
        ax.set_title("Absolute speed profile (GPS-anchored, current-dependent)")
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Bottom-right: decay rate vs pull delta-v (both Tier 1, but useful context)
        ax = axes[1, 1]
        pdvs = [t1[li]["pull_dv"] for li in laps_t1]
        drs = [t1[li]["decay_rate"] for li in laps_t1]
        ax.scatter(pdvs, drs, s=60, c=colors_t1, edgecolor="black", zorder=3)
        for j, li in enumerate(laps_t1):
            ax.annotate(f"L{li}", (pdvs[j], drs[j]),
                        textcoords="offset points", xytext=(5, 5), fontsize=8)
        ax.set_xlabel("Pull delta-v (m/s)")
        ax.set_ylabel("Glide decay rate (m/s²)")
        ax.set_title("Decay vs pull impulse (both Tier 1)")
        ax.grid(True, alpha=0.3)
        if len(pdvs) > 3:
            r2 = np.corrcoef(pdvs, drs)[0, 1]
            ax.text(0.05, 0.95, f"r = {r2:.2f}", transform=ax.transAxes,
                    fontsize=11, va="top",
                    bbox=dict(facecolor="white", edgecolor="gray", alpha=0.8))

        fig.suptitle("Tier 2: GPS-enhanced glide metrics (current-dependent)",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        path2 = os.path.join(PLOTS_DIR, "32_glide_tier2_gps.png")
        fig.savefig(path2, dpi=140, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {path2}")

    # ================================================================
    # Summary table — both tiers
    # ================================================================
    print("\n" + "=" * 105)
    header_gps = "  GPS(m/s)  Retained" if has_gps else ""
    print(f"{'Lap':>4} {'n':>5} {'Decay':>8} {'PullDv':>8} {'GlideLoss':>10} "
          f"{'Pull%':>6} {'Pull(s)':>8} {'Glide(s)':>9} {'SPM':>5}{header_gps}")
    print("-" * 105)
    for li in laps_t1:
        m = t1[li]
        pf = m['pull_frac'] * 100 if np.isfinite(m['pull_frac']) else 0.0
        row = (f"  {li:2d}  {m['n']:4d}  {m['decay_rate']:7.3f}  {m['pull_dv']:7.4f}  "
               f"{m['glide_loss']:9.4f}  {pf:5.1f}"
               f"  {m['pull_dur']:7.3f}  {m['glide_dur']:8.3f}  {m['cadence']:4.0f}")
        if has_gps and li in t2:
            row += f"  {t2[li]['gps_mean']:8.2f}  {t2[li]['speed_retained']:8.3f}"
        elif has_gps:
            row += f"  {all_lap_data[li]['gps_mean_speed']:8.2f}       ---"
        print(row)
    print("=" * 105)
    print("\nTier 1 columns (Decay through SPM) are current-independent.")
    if has_gps:
        print("Tier 2 columns (GPS, Retained) depend on speed over ground.")

    # ================================================================
    # PLOT 3: Phase detection diagnostic — individual strokes from
    #         the comparison laps (or first two cruise laps if none specified)
    # ================================================================
    print("\n--- Plot 3: Phase detection diagnostic ---")
    diagnostic_laps = [c for c in compare
                       if c["idx"] in all_lap_data
                       and len(all_lap_data[c["idx"]]["filtered"]) >= 10][:2]
    if diagnostic_laps:
        plot_phase_diagnostic(all_lap_data, t_imu, fwd,
                              diagnostic_laps,
                              savepath=os.path.join(PLOTS_DIR, "33_phase_detection.png"))
    else:
        print("  Skipped — no comparison laps with enough strokes.")


def plot_phase_diagnostic(all_lap_data, t_imu, fwd, compare_laps, savepath,
                          n_strokes_per_lap=4):
    """Show individual strokes with phase markers so you can verify how
    catch (accel peak), blade exit (downward zero-cross), and blade entry
    (upward zero-cross) are being identified.

    compare_laps is a list of dicts {idx, label, color} (from get_compare_laps).
    """
    n_rows = len(compare_laps)
    fig, axes = plt.subplots(n_rows, 1, figsize=(15, 5 * n_rows))
    if n_rows == 1:
        axes = [axes]

    for row, c in enumerate(compare_laps):
        lap_idx = c["idx"]
        d = all_lap_data.get(lap_idx)
        if d is None or len(d["filtered"]) < n_strokes_per_lap + 5:
            continue

        # Pick strokes from mid-lap (skip the start transient)
        mid = len(d["filtered"]) // 2
        selected = d["filtered"][mid : mid + n_strokes_per_lap]

        # Find the time span covering these strokes
        t_start = selected[0]["t"][0] - 0.1
        t_end = selected[-1]["t"][-1] + 0.1

        # Get the raw forward accel and time over this window
        m = (t_imu >= t_start) & (t_imu <= t_end)
        tw = t_imu[m] - t_start
        aw = fwd[m]

        ax = axes[row]
        ax.plot(tw, aw, color="black", linewidth=1.0, zorder=2)
        ax.axhline(0, color="gray", linewidth=0.6, linestyle="--", zorder=1)

        # For each stroke, mark the phases
        legend_added = {"catch": False, "exit": False, "entry": False,
                        "pull": False, "glide": False}
        for s in selected:
            t_rel = s["t"] - t_start
            seg_start = t_rel[0]
            seg_end = t_rel[-1]

            # Accel peak (catch) is at the start of this window — index 0
            catch_t = seg_start
            lbl = "accel peak (mid-pull)" if not legend_added["catch"] else None
            ax.axvline(catch_t, color="darkblue", linewidth=1.2, linestyle="-",
                       alpha=0.7, zorder=3, label=lbl)
            legend_added["catch"] = True

            # Blade exit at exit_offset from window start
            if np.isfinite(s["exit_offset_s"]):
                exit_t = seg_start + s["exit_offset_s"]
                lbl = "blade exit (a → -)" if not legend_added["exit"] else None
                ax.axvline(exit_t, color="orange", linewidth=1.2, linestyle="-",
                           alpha=0.8, zorder=3, label=lbl)
                legend_added["exit"] = True

                # Pull phase shading: from accel peak to blade exit (2nd half of pull)
                lbl = "pull half (a > 0)" if not legend_added["pull"] else None
                ax.axvspan(catch_t, exit_t, color="lightblue", alpha=0.35,
                           zorder=0, label=lbl)
                legend_added["pull"] = True

            # Blade entry at entry_offset before window end
            if np.isfinite(s["entry_offset_s"]):
                entry_t = seg_end - s["entry_offset_s"]
                lbl = "blade entry (a → +)" if not legend_added["entry"] else None
                ax.axvline(entry_t, color="green", linewidth=1.2, linestyle="-",
                           alpha=0.8, zorder=3, label=lbl)
                legend_added["entry"] = True

                if np.isfinite(s["exit_offset_s"]):
                    exit_t = seg_start + s["exit_offset_s"]
                    # Glide phase shading
                    lbl = "glide (a < 0, blade out)" if not legend_added["glide"] else None
                    ax.axvspan(exit_t, entry_t, color="khaki", alpha=0.35,
                               zorder=0, label=lbl)
                    legend_added["glide"] = True

        # Annotate one stroke with its measured durations
        s = selected[1] if len(selected) > 1 else selected[0]
        ymax = ax.get_ylim()[1]
        ax.text(0.01, 0.98,
                f"This lap medians:\n"
                f"  pull (blade in)  = {np.median([x['pull_duration_s'] for x in d['filtered']]):.3f} s\n"
                f"  glide (blade out) = {np.median([x['glide_duration_s'] for x in d['filtered']]):.3f} s\n"
                f"  cadence          = {60.0 / np.median([x['dur_s'] for x in d['filtered']]):.1f} spm",
                transform=ax.transAxes, fontsize=9, va="top", family="monospace",
                bbox=dict(facecolor="white", edgecolor="gray", alpha=0.9))

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Forward accel (m/s²)")
        ax.set_title(f"Lap {lap_idx} — {c['label']}")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="lower right", fontsize=8, ncol=2, framealpha=0.9)

    fig.suptitle("Phase detection diagnostic — how zero-crossings define "
                 "blade-in (pull) vs blade-out (glide)",
                 fontsize=13, fontweight="bold", y=1.00)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {savepath}")


if __name__ == "__main__":
    main()
