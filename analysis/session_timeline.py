"""
Whole-session timeline — one figure that lines up everything the boat felt,
on a common KG-local time axis with Garmin lap boundaries marked.

Four stacked panels (shared x = session minutes):
  1. Speed: KG GPS over ground (mph), with the NK SpeedCoach speed overlaid
     when the manifest has one (anchored to the Garmin lap-1 start, since the
     paddler starts both devices together).
  2. Cadence: instantaneous stroke rate (per stroke pair) + a rolling median.
  3. Drive force: per-stroke peak forward force on the boat (lbs) + rolling
     median. This is boat-response force (mass x forward accel), not blade force.
  4. Side + balance: the slow yaw envelope (which side the paddler is biased to;
     negative = LEFT in our x=fwd, y=left, z=up frame) on the left axis, and the
     low-frequency heel angle (deg, from the gravity direction in the body frame)
     on the right axis. Heel + roll activity is what reveals ama-flying.

This is the "what happened when" view: drift shows as flat speed, sprint
build-ups as ramps, rests as gaps, and ama-flying as a sustained heel with busy
roll. It is general and session-aware:

    python analysis/session_timeline.py --session N

Nothing here is tuned to one session; detector gains and smoothing windows are
physically-motivated defaults and can be overridden on the CLI.
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
from correlate_kg_garmin import (
    load_kg, load_garmin, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, detect_strokes, lap_local_window,
    _bandpass, _estimate_fs,
)

MS_TO_MPH = 2.23694
N_TO_LBF = 0.224809


def rolling_median(x, win):
    """Centered rolling median, same length as x."""
    n = len(x)
    if n == 0:
        return x
    half = win // 2
    out = np.empty(n)
    for i in range(n):
        out[i] = np.median(x[max(0, i - half):min(n, i + half + 1)])
    return out


def lowpass_gravity_dir(a_y, a_z, fs, smooth_s=4.0):
    """Low-pass lateral & up accel to recover the gravity direction, then the
    heel (roll) angle in degrees. A simple moving average is enough — we only
    want the slow tilt, not stroke-rate wiggle."""
    win = max(1, int(smooth_s * fs))
    k = np.ones(win) / win
    y = np.convolve(a_y, k, mode="same")
    z = np.convolve(a_z, k, mode="same")
    return np.degrees(np.arctan2(y, z))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_arg(p)
    p.add_argument("--prominence", type=float, default=1.5)
    p.add_argument("--height", type=float, default=1.0)
    p.add_argument("--refractory", type=float, default=0.4)
    p.add_argument("--cad-smooth", type=int, default=9,
                   help="rolling-median window (strokes) for cadence + force")
    p.add_argument("--tmin", type=float, default=None,
                   help="zoom: start of x window (session minutes)")
    p.add_argument("--tmax", type=float, default=None,
                   help="zoom: end of x window (session minutes)")
    p.add_argument("--tag", type=str, default="",
                   help="suffix for the output filename (e.g. _workout)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = get_session(args.session)
    print(f"Session {cfg.session_id} ({cfg.date}) — {cfg.location}")

    kg = load_kg(cfg.kg_path)
    garmin = load_garmin(cfg.garmin_path)
    align = align_kg_to_garmin(kg, garmin)
    R, _ = detect_imu_axes(kg)
    A = rotate_accel(R, kg["accel_raw"])
    G = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    fwd = A[:, 0]
    fs = _estimate_fs(t)

    # --- strokes over the whole session: cadence + per-stroke peak force ---
    strokes = detect_strokes(t, fwd, prominence=args.prominence,
                             height=args.height, refractory_s=args.refractory)
    st_t = np.array([s for s, _ in strokes], dtype=np.float64)
    st_i = np.array([i for _, i in strokes], dtype=np.int64)
    peak_lbs = fwd[st_i] * cfg.system_mass_kg * N_TO_LBF
    mid_t = 0.5 * (st_t[:-1] + st_t[1:])
    inst_cad = 60.0 / np.diff(st_t)
    band = (inst_cad >= 20) & (inst_cad <= 150)  # drop rest gaps for readability

    # --- side envelope + heel angle (decimate IMU to keep the plot light) ---
    yaw = G[:, 2]
    env = _bandpass(yaw, fs, lo=0.02, hi=0.15)
    heel = lowpass_gravity_dir(A[:, 1], A[:, 2], fs)
    dec = max(1, int(len(t) / 20000))  # ~20k points is plenty for a timeline
    td, envd, heeld = t[::dec], env[::dec], heel[::dec]

    # --- optional SpeedCoach speed overlay (anchored to Garmin lap-1 start) ---
    sc = None
    if cfg.nk_path and os.path.exists(cfg.nk_path):
        try:
            from nk_speedcoach import load_nk
            nk = load_nk(cfg.nk_path)
            sc_t_min = (align["offset_s"] + nk["elapsed_s"]) / 60.0
            sc = (sc_t_min, nk["speed_ms"] * MS_TO_MPH)
        except Exception as e:
            print(f"  (SpeedCoach overlay skipped: {e})")

    # ============================ plot ============================
    fig, ax = plt.subplots(4, 1, figsize=(16, 13), sharex=True)
    tmin = t / 60.0

    # near-stationary laps get a light shade so rests/drift/ama stand out.
    # Only draw markers/labels inside the visible window — otherwise off-axis
    # text inflates the saved canvas under bbox_inches="tight".
    xlo = args.tmin if args.tmin is not None else tmin.min()
    xhi = args.tmax if args.tmax is not None else tmin.max()
    laps = garmin["laps"]
    for lap in laps:
        lt0, lt1 = lap_local_window(lap, align)
        if lt1 / 60.0 < xlo or lt0 / 60.0 > xhi:
            continue
        near_static = lap["distance_m"] < 0.5 * lap["duration_s"]  # < 0.5 m/s avg
        for a_ in ax:
            a_.axvline(lt0 / 60.0, color="gray", alpha=0.35, linewidth=0.7)
            if near_static:
                a_.axvspan(lt0 / 60.0, lt1 / 60.0, color="orange", alpha=0.07)
        ax[0].text((lt0 + lt1) / 120.0, 0.96, f"L{lap['idx']}",
                   transform=ax[0].get_xaxis_transform(), ha="center", va="top",
                   fontsize=8, color="dimgray", clip_on=True)

    # 1) speed
    ax[0].plot(kg["gps_t"] / 60.0, kg["gps_speed"] * MS_TO_MPH,
               color="firebrick", linewidth=0.9, label="KG GPS speed")
    if sc is not None:
        ax[0].plot(sc[0], sc[1], color="darkorange", linewidth=0.8, alpha=0.6,
                   label="SpeedCoach speed")
    ax[0].set_ylabel("Speed (mph)")
    ax[0].set_title(f"KiloGlide session {cfg.session_id} timeline "
                    f"({cfg.date}, {cfg.boat}, {cfg.paddle if hasattr(cfg,'paddle') else ''})  "
                    f"— orange bands = near-stationary laps",
                    fontsize=12, fontweight="bold")
    ax[0].legend(loc="upper right", fontsize=8)
    ax[0].grid(True, alpha=0.3)

    # 2) cadence
    ax[1].scatter(mid_t[band] / 60.0, inst_cad[band], s=5, color="lightgray", alpha=0.5)
    if band.sum() > args.cad_smooth:
        ax[1].plot(mid_t[band] / 60.0, rolling_median(inst_cad[band], args.cad_smooth),
                   color="steelblue", linewidth=1.3, label=f"{args.cad_smooth}-stroke median")
    ax[1].set_ylabel("Cadence (spm)")
    ax[1].set_ylim(0, 80)
    ax[1].legend(loc="upper right", fontsize=8)
    ax[1].grid(True, alpha=0.3)

    # 3) per-stroke peak drive force
    fb = band  # same in-band mask length as mid_t
    pk_mid = peak_lbs[:-1]  # align with mid_t (one fewer than strokes)
    ax[2].scatter(mid_t[fb] / 60.0, pk_mid[fb], s=5, color="thistle", alpha=0.6)
    if fb.sum() > args.cad_smooth:
        ax[2].plot(mid_t[fb] / 60.0, rolling_median(pk_mid[fb], args.cad_smooth),
                   color="purple", linewidth=1.3, label=f"{args.cad_smooth}-stroke median")
    ax[2].set_ylabel("Peak drive force (lbs)")
    ax[2].legend(loc="upper right", fontsize=8)
    ax[2].grid(True, alpha=0.3)

    # 4) side envelope + heel
    ax[3].fill_between(td / 60.0, 0, envd, where=(envd < 0), color="steelblue",
                       alpha=0.5, label="LEFT bias (yaw env < 0)")
    ax[3].fill_between(td / 60.0, 0, envd, where=(envd >= 0), color="firebrick",
                       alpha=0.5, label="RIGHT bias (yaw env > 0)")
    ax[3].axhline(0, color="black", linewidth=0.5)
    ax[3].set_ylabel("Yaw envelope (rad/s)")
    ax[3].grid(True, alpha=0.3)
    ax3b = ax[3].twinx()
    ax3b.plot(td / 60.0, heeld, color="seagreen", linewidth=1.0, alpha=0.8,
              label="heel angle (deg)")
    ax3b.set_ylabel("Heel angle (deg)", color="seagreen")
    ax3b.tick_params(axis="y", labelcolor="seagreen")
    h1, l1 = ax[3].get_legend_handles_labels()
    h2, l2 = ax3b.get_legend_handles_labels()
    ax[3].legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8)
    ax[3].set_xlabel("Session time (min)")

    if args.tmin is not None or args.tmax is not None:
        ax[0].set_xlim(args.tmin, args.tmax)

    fig.tight_layout()
    savepath = os.path.join(cfg.plots_dir, f"31_session_timeline{args.tag}.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {savepath}")


if __name__ == "__main__":
    main()
