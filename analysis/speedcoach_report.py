"""
SpeedCoach <-> KiloGlide comparison report.

Defined workflow for an NK SpeedCoach session:
  1. Drop the SpeedCoach CSV export into analysis/data/.
  2. Set "nk_speedcoach": "<filename>.csv" in that session's manifest entry.
  3. Run:  python analysis/speedcoach_report.py --session N

Outputs (to analysis/plots/session_N/):
  40_speed_vs_time.png        SpeedCoach vs KG GPS speed over the session
  41_strokerate_vs_time.png   SpeedCoach stroke rate vs KG per-lap cadence
  42_per_lap_bars.png         per-lap mean speed and distance-per-stroke (SC vs KG)
And prints a validation + per-lap metrics table to the console.

SpeedCoach is the trusted boat-based reference: it and KG both measure hull
motion, so this report is the natural way to confirm KG's speed and stroke data.
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
    load_kg, load_garmin, align_kg_to_garmin,
    detect_imu_axes, rotate_accel, rotate_gyro, analyze_lap,
)
from nk_speedcoach import load_nk
from session_config import get_session, add_session_arg

MPH = 2.23694


def _resample(t, y, grid):
    return np.interp(grid, t, y, left=np.nan, right=np.nan)


def _refine_offset(sc_local, sc_speed, kg_t, kg_speed, search=15.0, step=1.0):
    """Slide SpeedCoach a few seconds to maximise speed correlation with KG.
    Returns (best_shift_s, best_r). Alignment is already ~right from the clocks;
    this just reports the residual and the agreement quality."""
    lo = max(sc_local.min(), kg_t.min()); hi = min(sc_local.max(), kg_t.max())
    if hi - lo < 30:
        return 0.0, np.nan
    grid = np.arange(lo, hi, 1.0)
    kg_u = _resample(kg_t, kg_speed, grid)
    best = (0.0, -2.0)
    for sh in np.arange(-search, search + step, step):
        sc_u = _resample(sc_local + sh, sc_speed, grid)
        m = np.isfinite(sc_u) & np.isfinite(kg_u)
        if m.sum() < 30:
            continue
        r = np.corrcoef(sc_u[m], kg_u[m])[0, 1]
        if r > best[1]:
            best = (float(sh), float(r))
    return best


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_session_arg(p)
    args = p.parse_args()
    cfg = get_session(args.session)
    if not cfg.nk_path:
        raise SystemExit(f"Session {cfg.session_id} has no nk_speedcoach in the manifest.")

    print(f"Session {cfg.session_id} ({cfg.date}) - SpeedCoach vs KiloGlide\n")
    kg = load_kg(cfg.kg_path)
    g = load_garmin(cfg.garmin_path) if cfg.garmin_path else None
    # Canonical SpeedCoach loader (nk_speedcoach.load_nk); adapt its key names
    # to the short ones this report uses.
    _nk = load_nk(cfg.nk_path)
    sc = {"t": _nk["elapsed_s"], "speed": _nk["speed_ms"],
          "stroke_rate": _nk["stroke_rate_spm"], "total_strokes": _nk["total_strokes"],
          "dps": _nk["dps_m"], "summary": _nk["summary"]}

    # --- time alignment -------------------------------------------------------
    # KG<->Garmin from TIME records; SpeedCoach started ~same UTC second as
    # Garmin (both GPS), so SC elapsed maps to KG-local via the Garmin offset,
    # then we refine the residual by speed cross-correlation.
    if g is not None:
        align = align_kg_to_garmin(kg, g)
        offset = align["offset_s"]
        gt0 = g["activity_start_utc"]
    else:
        raise SystemExit("This report needs the Garmin activity for KG time alignment.")

    sc_local = sc["t"] + offset
    shift, r_speed = _refine_offset(sc_local, sc["speed"],
                                    kg["gps_t"], kg["gps_speed"])
    sc_local = sc_local + shift

    # --- KG per-lap metrics ---------------------------------------------------
    R, _ = detect_imu_axes(kg)
    A = rotate_accel(R, kg["accel_raw"]); G = rotate_gyro(R, kg["gyro_raw"])
    laps = g["laps"]
    exclude = set(cfg.exclude_laps)

    # --- validation -----------------------------------------------------------
    # SpeedCoach was started ~`shift` s from Garmin/KG (you press start on the two
    # devices a few seconds apart), so map SC's elapsed clock onto the lap clock
    # before slicing. And compare per-lap MEAN speed over a ramp-trimmed window:
    # the first/last seconds of a short sprint are acceleration, not the effort,
    # and would otherwise drag a 40 s piece's average down.
    sc_clk = sc["t"] + shift
    gt, gv = kg["gps_t"], kg["gps_speed"]
    kg_t0 = align["kg_t0_utc"]
    sc_total = int(sc["summary"].get("total_strokes")
                   or np.nanmax(sc["total_strokes"]))
    kg_total = 0
    per_lap = []
    for lap in laps:
        a = lap["start_utc"] - gt0; b = a + lap["duration_s"]   # lap clock
        t0 = lap["start_utc"] - kg_t0; t1 = t0 + lap["duration_s"]  # KG-local
        pad = min(6.0, 0.15 * lap["duration_s"])                # trim accel ramp
        # stroke counts: full window (robust to a few seconds of misalignment)
        sc_n = int(np.sum((sc_clk >= a) & (sc_clk < b)))
        r = analyze_lap(kg, A, G, lap, align, cfg.system_mass_kg,
                        adaptive=cfg.adaptive_strokes,
                        gap_fill=cfg.gap_fill_strokes)
        kg_n = r["n_strokes"] if r else 0
        kg_total += kg_n
        # mean speed / rate / DPS: trimmed + aligned, so KG and SC are comparable
        scm = (sc_clk >= a + pad) & (sc_clk < b - pad)
        kgm = (gt >= t0 + pad) & (gt <= t1 - pad)
        sc_spd = np.nanmean(sc["speed"][scm]) * MPH if scm.any() else np.nan
        sc_sr = np.nanmean(sc["stroke_rate"][scm]) if scm.any() else np.nan
        sc_dps = np.nanmean(sc["dps"][scm]) if scm.any() else np.nan
        kg_spd = np.nanmean(gv[kgm]) * MPH if kgm.any() else np.nan
        kg_sr = r.get("cadence_spm", np.nan) if r else np.nan
        kg_dps = r.get("distance_per_stroke_m", np.nan) if r else np.nan
        per_lap.append(dict(idx=lap["idx"], dur=lap["duration_s"],
                            sc_n=sc_n, kg_n=kg_n, sc_spd=sc_spd, kg_spd=kg_spd,
                            sc_sr=sc_sr, kg_sr=kg_sr, sc_dps=sc_dps, kg_dps=kg_dps))

    # per-lap mean-speed agreement on real pieces (the number that matters)
    sd = [abs(L["kg_spd"] - L["sc_spd"]) for L in per_lap
          if L["kg_n"] >= 20 and L["idx"] not in exclude
          and np.isfinite(L["kg_spd"]) and np.isfinite(L["sc_spd"])]
    med_speed_err = float(np.median(sd)) if sd else float("nan")

    # per-lap cadence (stroke-rate) agreement on the same real pieces — the
    # second half of "did KG match the SpeedCoach". KG cadence is per-lap (median
    # inter-stroke interval); SC is its trimmed mean stroke rate over the piece.
    rd = [abs(L["kg_sr"] - L["sc_sr"]) for L in per_lap
          if L["kg_n"] >= 20 and L["idx"] not in exclude
          and np.isfinite(L["kg_sr"]) and np.isfinite(L["sc_sr"])]
    med_sr_err = float(np.median(rd)) if rd else float("nan")

    print("=== DATA QUALITY ===")
    print(f"  Device start offset (SpeedCoach vs Garmin/KG): {shift:+.1f} s")
    print(f"  Instantaneous speed correlation KG vs SpeedCoach:  r = {r_speed:.3f}")
    print(f"  Per-lap MEAN speed agreement (trimmed): median |KG-SC| = "
          f"{med_speed_err:.2f} mph")
    print(f"  Per-lap cadence agreement (trimmed):    median |KG-SC| = "
          f"{med_sr_err:.1f} spm")
    # Real-piece stroke agreement: sum over non-excluded laps only, so rests /
    # drills (which SpeedCoach counts but KG deliberately doesn't) don't drag the
    # headline number. This is the count metric that reflects real paddling.
    sc_real = sum(L["sc_n"] for L in per_lap if L["idx"] not in exclude)
    kg_real = sum(L["kg_n"] for L in per_lap if L["idx"] not in exclude)
    real_ratio = kg_real / max(sc_real, 1)
    print(f"  Total strokes (whole session):  SpeedCoach {sc_total}   KG {kg_total}"
          f"   ({100*kg_total/sc_total:.0f}%)")
    print(f"  Real-piece strokes (excl rests/drills):  SpeedCoach {sc_real}"
          f"   KG {kg_real}   ({100*real_ratio:.0f}%)")
    verdict = ("GOOD" if (med_speed_err < 0.3
                          and (np.isnan(med_sr_err) or med_sr_err < 2.0)
                          and 0.9 < real_ratio < 1.1)
               else "CHECK")
    print(f"  Verdict: {verdict}\n")

    print("=== PER-LAP (SpeedCoach | KG) ===")
    print("lap  dur  strokes(SC/KG)  mph(SC/KG)   spm(SC/KG)   DPS m(SC/KG)")
    for L in per_lap:
        if L["sc_n"] < 5 and L["kg_n"] < 5:
            continue
        tag = "  (excl)" if L["idx"] in exclude else ""
        print("%3d %4.0f   %4d /%4d    %4.1f /%4.1f   %4.0f /%4.0f   %4.2f /%4.2f%s" % (
            L["idx"], L["dur"], L["sc_n"], L["kg_n"], L["sc_spd"], L["kg_spd"],
            L["sc_sr"], L["kg_sr"], L["sc_dps"], L["kg_dps"], tag))

    # --- plots ---------------------------------------------------------------
    out = cfg.plots_dir
    _plot_speed(sc_local, sc, kg, laps, gt0, offset, r_speed,
                os.path.join(out, "40_speed_vs_time.png"), cfg.session_id)
    _plot_strokerate(sc_local, sc, per_lap, laps, gt0, offset,
                     os.path.join(out, "41_strokerate_vs_time.png"), cfg.session_id)
    _plot_bars(per_lap, exclude, os.path.join(out, "42_per_lap_bars.png"),
               cfg.session_id)
    print(f"\nSaved 3 plots to {out}")


def _lap_spans(laps, gt0, offset):
    return [(lap["idx"], lap["start_utc"] - gt0 + offset,
             lap["start_utc"] - gt0 + offset + lap["duration_s"]) for lap in laps]


def _plot_speed(sc_local, sc, kg, laps, gt0, offset, r_speed, path, sid):
    fig, ax = plt.subplots(figsize=(15, 5))
    ax.plot(kg["gps_t"], kg["gps_speed"] * MPH, color="steelblue", lw=0.6,
            alpha=0.7, label="KG GPS speed")
    ax.plot(sc_local, sc["speed"] * MPH, color="firebrick", lw=1.0,
            label="SpeedCoach speed")
    for idx, a, b in _lap_spans(laps, gt0, offset):
        ax.axvspan(a, b, color="gray", alpha=0.04)
    ax.set_xlabel("KG-local time (s)"); ax.set_ylabel("Speed (mph)")
    ax.set_title(f"Session {sid} — speed: SpeedCoach vs KG GPS  (r = {r_speed:.3f})")
    ax.grid(alpha=0.3); ax.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(path, dpi=140, bbox_inches="tight"); plt.close(fig)


def _plot_strokerate(sc_local, sc, per_lap, laps, gt0, offset, path, sid):
    fig, ax = plt.subplots(figsize=(15, 5))
    ax.plot(sc_local, sc["stroke_rate"], color="firebrick", lw=0.9,
            label="SpeedCoach stroke rate")
    spans = {idx: (a, b) for idx, a, b in _lap_spans(laps, gt0, offset)}
    first = True
    for L in per_lap:
        if L["kg_n"] < 5:
            continue
        a, b = spans[L["idx"]]
        ax.plot([a, b], [L["kg_sr"], L["kg_sr"]], color="steelblue", lw=2.5,
                label="KG per-lap cadence" if first else None)
        first = False
    ax.set_xlabel("KG-local time (s)"); ax.set_ylabel("Stroke rate (spm)")
    ax.set_title(f"Session {sid} — stroke rate: SpeedCoach (per stroke) vs KG (per lap)")
    ax.grid(alpha=0.3); ax.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(path, dpi=140, bbox_inches="tight"); plt.close(fig)


def _plot_bars(per_lap, exclude, path, sid):
    rows = [L for L in per_lap if L["kg_n"] >= 10 and L["idx"] not in exclude]
    if not rows:
        return
    idx = [L["idx"] for L in rows]; x = np.arange(len(idx)); w = 0.38
    fig, ax = plt.subplots(2, 1, figsize=(15, 8))
    ax[0].bar(x - w/2, [L["sc_spd"] for L in rows], w, color="firebrick", label="SpeedCoach")
    ax[0].bar(x + w/2, [L["kg_spd"] for L in rows], w, color="steelblue", label="KG")
    ax[0].set_ylabel("Mean speed (mph)"); ax[0].set_title(f"Session {sid} — per-lap mean speed")
    ax[0].set_xticks(x); ax[0].set_xticklabels(idx); ax[0].legend(); ax[0].grid(alpha=0.3, axis="y")
    ax[1].bar(x - w/2, [L["sc_dps"] for L in rows], w, color="firebrick", label="SpeedCoach")
    ax[1].bar(x + w/2, [L["kg_dps"] for L in rows], w, color="steelblue", label="KG")
    ax[1].set_ylabel("Distance / stroke (m)"); ax[1].set_title("Per-lap distance per stroke")
    ax[1].set_xlabel("Garmin lap"); ax[1].set_xticks(x); ax[1].set_xticklabels(idx)
    ax[1].legend(); ax[1].grid(alpha=0.3, axis="y")
    fig.tight_layout(); fig.savefig(path, dpi=140, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    main()
