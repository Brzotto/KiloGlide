"""
Session 37 — does chop explain the low Connected % in strong miles?

Hypothesis A (chop): waves shake the IMU, splitting strokes into apparent
double peaks. Connected % should be LOW in choppy laps, HIGH in glass laps.

Hypothesis B (effort): pulling hard creates a stronger arm-led catch shoulder.
Connected % should be LOW in high-force laps, HIGH in easy laps.

Hypothesis C (cadence): rushing the catch in fast cadence creates the
disconnect. Connected % should drop as cadence climbs.

We measure per-lap chop level as the RMS of lateral acceleration in the wave
band (0.2–0.5 Hz), AFTER de-trending the gravity-tilt bias (lap-demeaned).
Then we scatter Connected % against chop, peak force, and cadence to see
which one is the actual driver.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, analyze_lap,
    KG_PATH, TCX_PATH, PLOTS_DIR, SYSTEM_MASS_KG,
)


def chop_rms_per_lap(kg, R, lap, align):
    """Per-lap RMS of lateral accel in the wave band (0.2-0.5 Hz)."""
    A_body = rotate_accel(R, kg["accel_raw"])
    t = kg["imu_t"]
    t0, t1 = lap_local_window(lap, align)
    m = (t >= t0) & (t <= t1)
    if np.sum(m) < 500:
        return float("nan")
    lat = A_body[m, 1]
    fs = (np.sum(m) - 1) / (t[m][-1] - t[m][0])
    if fs <= 1.0:
        return float("nan")
    lat = lat - np.mean(lat)  # remove gravity-tilt DC bias
    sos = butter(2, [0.2, 0.5], btype="band", fs=fs, output="sos")
    lat_wave = sosfiltfilt(sos, lat)
    return float(np.sqrt(np.mean(lat_wave ** 2)))


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])

    rows = []
    for lap in tcx["laps"]:
        per = analyze_lap(kg, A_body, G_body, lap, align, SYSTEM_MASS_KG)
        if per is None or per["n_strokes"] < 20:
            continue
        chop = chop_rms_per_lap(kg, R, lap, align)
        rows.append({
            "idx": lap["idx"],
            "n": per["n_strokes"],
            "connected": per.get("connected_fraction", 0.0) * 100,
            "peak_N": per["mean_peak_force_N"],
            "cadence": per["cadence_spm"],
            "speed": per.get("mean_speed_m_s", float("nan")),
            "chop_rms": chop,
        })

    print("\nPer-lap chop & connection summary (laps with >=20 strokes):")
    print(f"  {'Lap':>4}  {'n':>5}  {'Conn%':>6}  {'Peak N':>7}  {'Cad spm':>7}  {'Speed':>6}  {'Chop RMS m/s2':>13}")
    for r in rows:
        print(f"  {r['idx']:>4}  {r['n']:>5}  {r['connected']:>5.0f}%  {r['peak_N']:>7.0f}  "
              f"{r['cadence']:>7.1f}  {r['speed']:>6.2f}  {r['chop_rms']:>13.3f}")

    # Plot: 3-panel scatter — Connected % vs (chop, peak, cadence)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    idx = np.array([r["idx"] for r in rows])
    conn = np.array([r["connected"] for r in rows])
    chop = np.array([r["chop_rms"] for r in rows])
    peak = np.array([r["peak_N"] for r in rows])
    cad = np.array([r["cadence"] for r in rows])

    def scatter_with_fit(ax, x, y, xlabel, color):
        ax.scatter(x, y, s=80, c=idx, cmap="viridis",
                    edgecolor="black", linewidth=0.5, zorder=3)
        # Line of best fit
        valid = np.isfinite(x) & np.isfinite(y)
        if np.sum(valid) >= 3:
            slope, intercept = np.polyfit(x[valid], y[valid], 1)
            xx = np.linspace(x[valid].min(), x[valid].max(), 50)
            ax.plot(xx, slope * xx + intercept, color="gray",
                     linewidth=1.5, linestyle="--", alpha=0.7)
            # Pearson r
            r = float(np.corrcoef(x[valid], y[valid])[0, 1])
            ax.text(0.05, 0.95, f"Pearson r = {r:+.2f}\nn = {int(np.sum(valid))}",
                     transform=ax.transAxes, va="top", fontsize=10,
                     bbox=dict(facecolor="white", edgecolor="gray", alpha=0.85))
        for i, li in enumerate(idx):
            ax.annotate(f"L{li}", (x[i], y[i]), xytext=(5, 5),
                         textcoords="offset points", fontsize=8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Connected strokes (%)")
        ax.grid(True, alpha=0.3)

    scatter_with_fit(axes[0], chop, conn,
                     "Chop level — lateral RMS in 0.2-0.5 Hz band (m/s²)", "steelblue")
    axes[0].set_title("Hypothesis A: Chop")

    scatter_with_fit(axes[1], peak, conn,
                     "Mean peak drive force (N)", "purple")
    axes[1].set_title("Hypothesis B: Effort")

    scatter_with_fit(axes[2], cad, conn,
                     "Cadence (spm)", "firebrick")
    axes[2].set_title("Hypothesis C: Cadence")

    fig.suptitle("What drives the connected-stroke fraction?\n"
                 "Steeper negative slope + stronger negative r = stronger driver.",
                 fontsize=11)
    fig.tight_layout()
    savepath = os.path.join(PLOTS_DIR, "23_chop_vs_connection.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved {savepath}")


if __name__ == "__main__":
    main()
