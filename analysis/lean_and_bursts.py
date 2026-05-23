"""
Session 37 — answer two specific questions:

  Q1. Did the user paddle all on the same side in laps 6, 7, 8?
      Apply the slow-yaw-envelope side classifier to each burst lap.

  Q2. Show the lean in the data.
      Lean = roll about the forward axis. Compute the boat's tilt angle from
      low-passed accel: lean_deg = atan2(LP(a_y), LP(a_z)) * 180/pi.
      Positive = boat leaning toward +y (LEFT, ama side).

  Q3. The water was choppy — check the wave-band content of the signals to
      see what we're fighting against in classification.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt, welch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, detect_strokes,
    KG_PATH, TCX_PATH, PLOTS_DIR,
)


def low_pass(y, fs, cutoff_hz=0.1, order=2):
    sos = butter(order, cutoff_hz, btype="low", fs=fs, output="sos")
    return sosfiltfilt(sos, y)


def band_pass(y, fs, lo, hi, order=2):
    sos = butter(order, [lo, hi], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, y)


# ------------------------------------------------------------------
# Q1: per-lap side analysis for laps 6, 7, 8
# ------------------------------------------------------------------
def plot_burst_side_analysis(kg, R, tcx, align, savepath, burst_ids=(6, 7, 8)):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    fig, axes = plt.subplots(len(burst_ids), 3, figsize=(16, 3.5 * len(burst_ids)),
                             squeeze=False)
    summaries = []

    for row, li in enumerate(burst_ids):
        lap = laps_by_idx[li]
        lt0, lt1 = lap_local_window(lap, align)
        pad = 1.0
        m = (t >= lt0 - pad) & (t <= lt1 + pad)
        tt = t[m] - lt0
        fwd = A_body[m, 0]
        yaw = G_body[m, 2]
        fs = (len(tt) - 1) / (tt[-1] - tt[0])

        strokes = detect_strokes(t[m], fwd, prominence=1.5, height=0.5,
                                  refractory_s=0.35)
        catch_t_rel = np.array([s[0] - lt0 for s in strokes])
        catch_i = np.array([int(s[1]) for s in strokes])

        # Side envelope (slow yaw): use wider band for short data
        env = band_pass(yaw, fs, 0.05, 0.5)
        catch_env = env[catch_i]

        # Also compute the per-stroke yaw integral over 300ms after catch
        post = int(0.30 * fs)
        catch_yaw_int = []
        for i in catch_i:
            hi = min(len(yaw), i + post)
            catch_yaw_int.append(float(np.sum(yaw[i:hi]) / fs))
        catch_yaw_int = np.array(catch_yaw_int)

        # Combine: stroke-by-stroke side score
        side_score = catch_yaw_int + 0.5 * catch_env
        labels = np.where(side_score < 0, "L", "R")
        nL = int(np.sum(labels == "L"))
        nR = int(np.sum(labels == "R"))

        # Panel 1: forward accel + colored stroke markers
        ax = axes[row, 0]
        ax.plot(tt, fwd, color="steelblue", linewidth=0.7)
        ax.axhline(0, color="black", linewidth=0.4)
        for ct, lab in zip(catch_t_rel, labels):
            ax.axvline(ct, color=("crimson" if lab == "L" else "navy"),
                       alpha=0.9, linewidth=1.4)
        ax.axvspan(0, lt1 - lt0, color="gray", alpha=0.06)
        ax.set_ylabel("a_fwd (m/s²)")
        ax.set_title(f"Lap {li}  |  {len(strokes)} strokes  |  "
                     f"{nL} L (red)  /  {nR} R (navy)")
        ax.set_xlabel("Time since lap start (s)")
        ax.grid(True, alpha=0.3)

        # Panel 2: yaw rate (raw + envelope) — see if envelope holds one sign
        ax = axes[row, 1]
        ax.plot(tt, yaw, color="lightgray", linewidth=0.5, label="raw yaw")
        ax.plot(tt, env, color="purple", linewidth=1.6, label="slow envelope")
        ax.axhline(0, color="black", linewidth=0.4)
        for ct in catch_t_rel:
            ax.axvline(ct, color="gray", alpha=0.25, linewidth=0.5)
        ax.axvspan(0, lt1 - lt0, color="gray", alpha=0.06)
        ax.set_ylabel("ω_yaw (rad/s)")
        ax.set_title("Yaw rate.  Envelope above zero ⇒ R-side block.  Below zero ⇒ L-side.")
        ax.set_xlabel("Time since lap start (s)")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)

        # Panel 3: side score per stroke, with the dominant side called out
        ax = axes[row, 2]
        x = np.arange(1, len(side_score) + 1)
        colors = ["crimson" if s < 0 else "navy" for s in side_score]
        ax.bar(x, side_score, color=colors, alpha=0.85, width=0.9)
        ax.axhline(0, color="black", linewidth=0.5)
        verdict = ("all LEFT" if nR == 0 else
                   "all RIGHT" if nL == 0 else
                   f"mixed: {nL}L / {nR}R")
        ax.set_title(f"Per-stroke side score — verdict: {verdict}")
        ax.set_xlabel("Stroke # within burst")
        ax.set_ylabel("Combined side score")
        ax.grid(True, alpha=0.3)

        summaries.append({"lap": li, "n": len(strokes), "L": nL, "R": nR,
                          "labels": labels.tolist()})

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return summaries


# ------------------------------------------------------------------
# Q2: lean angle over the session
# ------------------------------------------------------------------
def plot_lean_over_session(kg, R, savepath, lap_marks=None):
    """Compute lean = atan2(LP(a_y), LP(a_z)) over the whole session.
    Positive = leaning toward +y (LEFT, ama side).
    """
    A_body = rotate_accel(R, kg["accel_raw"])
    t = kg["imu_t"]
    fs = (len(t) - 1) / (t[-1] - t[0])

    ay = A_body[:, 1]
    az = A_body[:, 2]
    # Low-pass at 0.1 Hz to kill stroke + wave dynamics, keep slow tilt
    ay_lp = low_pass(ay, fs, cutoff_hz=0.1)
    az_lp = low_pass(az, fs, cutoff_hz=0.1)
    lean_rad = np.arctan2(ay_lp, az_lp)
    lean_deg = lean_rad * 180.0 / np.pi

    # Also compute dynamic roll (stroke-band rocking)
    roll_band = band_pass(A_body[:, 1], fs, 0.5, 3.0)  # lateral accel in stroke band
    # Integrate it to get a rough lateral velocity? Not meaningful — keep it
    # as an amplitude measure: rolling RMS of stroke-band lateral accel.
    win = max(1, int(2.0 * fs))  # 2-second window
    # Quick rolling RMS via cumulative
    ay_band_sq = roll_band ** 2
    cumsum = np.cumsum(ay_band_sq)
    rms = np.zeros_like(ay_band_sq)
    rms[win:] = np.sqrt((cumsum[win:] - cumsum[:-win]) / win)
    rms[:win] = np.sqrt(cumsum[:win + 1].max() / win)

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    axes[0].plot(t, lean_deg, color="purple", linewidth=1.0)
    axes[0].axhline(0, color="black", linewidth=0.5, linestyle="--")
    mean_lean = float(np.mean(lean_deg))
    axes[0].axhline(mean_lean, color="crimson", linewidth=1.0, alpha=0.8,
                    label=f"session mean = {mean_lean:.2f}°")
    axes[0].set_ylabel("Lean angle (degrees)")
    axes[0].set_title("Boat lean angle over the session "
                      "(positive = leaning LEFT toward the ama)")
    axes[0].legend(loc="upper right")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(t, rms, color="darkorange", linewidth=0.9,
                 label="stroke-band lateral RMS (2 s window)")
    axes[1].set_ylabel("Lateral RMS (m/s²)")
    axes[1].set_xlabel("KG-local time (s)")
    axes[1].set_title("Stroke-band lateral acceleration — proxy for boat 'rocking' amplitude")
    axes[1].legend(loc="upper right")
    axes[1].grid(True, alpha=0.3)

    if lap_marks:
        for li, (t0, t1) in lap_marks.items():
            for ax in axes:
                ax.axvspan(t0, t1, color="gray", alpha=0.04)
                ax.text((t0 + t1) / 2, ax.get_ylim()[1] * 0.92, f"L{li}",
                        ha="center", va="top", fontsize=8, color="gray")

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return mean_lean


# ------------------------------------------------------------------
# Q3: choppiness — power spectrum of motion in 3 frequency bands
# ------------------------------------------------------------------
def plot_choppiness_spectrum(kg, R, tcx, align, savepath, lap_idx=2):
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}
    lap = laps_by_idx[lap_idx]
    lt0, lt1 = lap_local_window(lap, align)
    m = (t >= lt0) & (t <= lt1)
    fs = (np.sum(m) - 1) / (t[m][-1] - t[m][0])

    # Welch periodogram
    nperseg = int(min(np.sum(m), 30 * fs))  # 30 s windows
    fig, ax = plt.subplots(1, 1, figsize=(13, 6))
    for label, sig, color in [
        ("Forward accel (a_x)", A_body[m, 0], "steelblue"),
        ("Lateral accel (a_y)", A_body[m, 1], "darkorange"),
        ("Yaw rate (ω_z)",      G_body[m, 2], "purple"),
        ("Roll rate (ω_x)",     G_body[m, 0], "seagreen"),
    ]:
        f, psd = welch(sig, fs=fs, nperseg=nperseg)
        ax.loglog(f, psd, color=color, linewidth=1.3, label=label)

    # Annotate frequency bands
    ax.axvspan(0.02, 0.15, color="crimson", alpha=0.10, label="side-switching band")
    ax.axvspan(0.2, 0.5, color="khaki", alpha=0.3, label="wave/chop band")
    ax.axvspan(0.5, 3.0, color="lightgreen", alpha=0.2, label="stroke band")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Power spectral density")
    ax.set_title(f"Lap {lap_idx} — power spectrum across motion axes.\n"
                 "If chop power (yellow band) is comparable to side-switching power (red band), "
                 "side detection is harder.")
    ax.set_xlim(0.01, 10)
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Q1: Were laps 6, 7, 8 all on the same side?")
    summaries = plot_burst_side_analysis(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "12_burst_sides.png"),
        burst_ids=(6, 7, 8),
    )
    for s in summaries:
        verdict = ("all LEFT" if s["R"] == 0 else
                   "all RIGHT" if s["L"] == 0 else
                   f"mixed: {s['L']}L / {s['R']}R")
        print(f"  Lap {s['lap']}: {s['n']} strokes -> {verdict}")
        print(f"    sequence: {' '.join(s['labels'])}")

    print("\nQ2: Lean angle over the session...")
    lap_marks = {}
    for li in (2, 3, 9, 13, 6, 7, 8):
        lap = next(l for l in tcx["laps"] if l["idx"] == li)
        lap_marks[li] = lap_local_window(lap, align)
    mean_lean = plot_lean_over_session(
        kg, R, os.path.join(PLOTS_DIR, "13_lean_over_session.png"),
        lap_marks=lap_marks,
    )
    print(f"  Mean session lean = {mean_lean:+.2f}° (positive = leaning LEFT toward ama)")

    print("\nQ3: Choppiness — frequency content during lap 2...")
    plot_choppiness_spectrum(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "14_choppiness_spectrum.png"),
        lap_idx=2,
    )
    print("Done.")


if __name__ == "__main__":
    main()
