"""
Connection A/B test analysis (general, --session N).

Built to answer "is KG's connection metric a real TECHNIQUE signal, or is it
measuring water conditions?" by analyzing a deliberately-designed on-water test:
matched-cadence pieces in calm water, alternating connected vs disconnected
catch technique, separated by button marks (USER_MARK events).

The script:
  1. Loads any session from the manifest.
  2. Splits the paddle into PIECES, either:
       - between consecutive USER_MARK (button) events, or
       - from explicit --windows "m0:m1,m2:m3" (minutes), a fallback for
         sessions without marks or if the button misbehaved.
  3. Per piece, detects strokes and computes connection metrics
     (reusing connection_metrics.connection_metrics) plus cadence, so you can
     confirm the pieces were actually matched-cadence.
  4. Optionally groups pieces by --labels "A,B,A,B,..." into an A-vs-B summary.
  5. Saves plots/session_N/32_connection_test.png and prints a table.

Connection here = fraction of strokes whose drive-force curve is a single clean
arch ("connected"), vs a catch-bump-then-lull-then-drive shape ("disconnected").
See connection_metrics.py for the per-stroke definition. This is an IMU-only
metric the SpeedCoach structurally cannot produce.
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
    load_kg, load_tcx, align_kg_to_garmin, lap_local_window,
    detect_imu_axes, rotate_accel, rotate_gyro,
    detect_strokes, stroke_features_for_window,
)
from connection_metrics import connection_metrics

KG_EVT_USER_MARK = 3
DEFAULT_MIN_PIECE_S = 30.0
# Stroke detector defaults — same as the rest of the pipeline.
DEFAULT_PROMINENCE = 1.5
DEFAULT_HEIGHT = 1.0
DEFAULT_REFRACTORY_S = 0.4


def _parse_pairs(spec):
    """Parse 'a:b,c:d' into [(a,b),(c,d)] of floats."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        lo, hi = part.split(":")
        out.append((float(lo), float(hi)))
    return out


def piece_windows(kg, cfg, args):
    """Return (list of (t0,t1) KG-local seconds, source string).

    Piece sources, in priority order:
      --windows         explicit minute ranges
      --from-garmin     Garmin TCX laps (lap-button presses) -> aligned to KG
      KG button marks   USER_MARK events
      fallback          whole session as one piece
    """
    t = kg["imu_t"]
    if args.windows:
        mins = _parse_pairs(args.windows)
        return [(a * 60.0, b * 60.0) for a, b in mins], "explicit --windows"

    if args.from_garmin:
        if not cfg.tcx_path:
            raise SystemExit("--from-garmin needs a garmin_tcx in the manifest")
        tcx = load_tcx(cfg.tcx_path)
        align = align_kg_to_garmin(kg, tcx)
        pieces = [lap_local_window(lap, align) for lap in tcx["laps"]]
        r = align.get("speed_corr", align.get("r"))
        rtxt = f", align r={r:.3f}" if isinstance(r, float) else ""
        return pieces, f"{len(pieces)} Garmin laps{rtxt}"

    marks = sorted(float(e["ts"]) / 1000.0
                   for e in kg["events"] if e.get("code") == KG_EVT_USER_MARK)
    if len(marks) >= 2:
        pieces = [(marks[i], marks[i + 1]) for i in range(len(marks) - 1)]
        pieces = [(a, b) for a, b in pieces if (b - a) >= args.min_piece_s]
        if pieces:
            return pieces, f"{len(marks)} button marks"

    # Fallback: whole session as one piece.
    return [(float(t[0]), float(t[-1]))], "no marks/windows — whole session"


def analyze_piece(t, fwd, roll, t0, t1, mass_kg, args):
    """Detect strokes in [t0,t1] and return aggregate connection stats."""
    m = (t >= t0) & (t <= t1)
    tt, fwd_w, roll_w = t[m], fwd[m], roll[m]
    strokes = detect_strokes(tt, fwd_w, prominence=args.prominence,
                             height=args.height, refractory_s=args.refractory)
    if len(strokes) < 5:
        return None
    feats = stroke_features_for_window(tt, fwd_w, roll_w, strokes, mass_kg)
    metrics = connection_metrics(feats, mass_kg=mass_kg)
    if not metrics:
        return None

    stroke_t = np.array([s for s, _ in strokes])
    iv = np.diff(stroke_t)
    iv = iv[(iv > 0.4) & (iv < 3.0)]                  # plausible paddling spacing
    cadence = 60.0 / np.median(iv) if len(iv) else float("nan")

    connected = np.array([mm["connected"] for mm in metrics], dtype=float)
    lull = np.array([mm["lull_depth_frac"] for mm in metrics], dtype=float)
    doc = np.array([mm["drive_over_catch"] for mm in metrics], dtype=float)
    gap = np.array([mm["gap_pct"] for mm in metrics], dtype=float)
    curves = [mm["curve_pos_clipped"] for mm in metrics]

    return {
        "t0": t0, "t1": t1,
        "dur_min": (t1 - t0) / 60.0,
        "n_strokes": len(metrics),
        "cadence": float(cadence),
        "connected_pct": 100.0 * float(np.mean(connected)),
        "lull_frac_med": float(np.nanmedian(lull)),
        "drive_over_catch_med": float(np.nanmedian(doc)),
        "gap_pct_med": float(np.nanmedian(gap)),
        "connected_flags": connected,
        "mean_curve": np.mean(curves, axis=0),
    }


def build_parser():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_session_arg(p)
    p.add_argument("--from-garmin", action="store_true",
                   help="use Garmin TCX laps (lap-button presses) as pieces")
    p.add_argument("--windows", type=str, default=None,
                   help="fallback piece windows in minutes: 'm0:m1,m2:m3'")
    p.add_argument("--labels", type=str, default=None,
                   help="per-piece labels, e.g. 'skip,A,B,A,B,A,B,skip'. "
                        "Pieces labeled 'skip' or '-' are ignored.")
    p.add_argument("--min-piece-s", type=float, default=DEFAULT_MIN_PIECE_S,
                   help="ignore marked pieces shorter than this (s)")
    p.add_argument("--axis-window", type=str, default=None,
                   help="seconds 's0:s1' of steady cruise for axis detection")
    p.add_argument("--prominence", type=float, default=DEFAULT_PROMINENCE)
    p.add_argument("--height", type=float, default=DEFAULT_HEIGHT)
    p.add_argument("--refractory", type=float, default=DEFAULT_REFRACTORY_S)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = get_session(args.session)
    print(f"Session {cfg.session_id} ({cfg.date}) — {cfg.location}")
    kg = load_kg(cfg.kg_path)
    t = kg["imu_t"]
    dur = float(t[-1] - t[0])

    # Axis detection. For short test sessions the default cruise window may not
    # fit, so derive a mid-session steady window unless one is given.
    if args.axis_window:
        s0, s1 = _parse_pairs(args.axis_window)[0]
        axis_win = (s0, s1)
    elif dur < 1400.0:
        axis_win = (t[0] + 0.4 * dur, t[0] + 0.7 * dur)
    else:
        axis_win = (900.0, 1400.0)
    R, _ = detect_imu_axes(kg, cruise_local_window=axis_win)
    fwd = rotate_accel(R, kg["accel_raw"])[:, 0]
    roll = rotate_gyro(R, kg["gyro_raw"])[:, 0]

    pieces, source = piece_windows(kg, cfg, args)
    print(f"Pieces: {len(pieces)} ({source})")

    labels = None
    if args.labels:
        labels = [s.strip() for s in args.labels.split(",")]
        if len(labels) != len(pieces):
            print(f"  WARN: {len(labels)} labels for {len(pieces)} pieces — ignoring labels")
            labels = None

    skip = {"skip", "-", ""}
    results = []
    for i, (t0, t1) in enumerate(pieces):
        label = labels[i] if labels else f"P{i+1}"
        if label.lower() in skip:
            continue
        r = analyze_piece(t, fwd, roll, t0, t1, cfg.system_mass_kg, args)
        if r is None:
            print(f"  Piece {i+1} ({label}): too few strokes, skipped")
            continue
        r["idx"] = i + 1
        r["label"] = label
        results.append(r)
    if not results:
        print("No analyzable pieces.")
        return

    # ---- Per-piece table -----------------------------------------------------
    print("\n" + "=" * 78)
    print(f"  CONNECTION BY PIECE — session {cfg.session_id}")
    print("=" * 78)
    print(f"  {'piece':6}{'window(min)':14}{'strokes':>8}{'cad':>7}"
          f"{'conn%':>8}{'lull':>8}{'d/c':>7}{'gap%':>7}")
    for r in results:
        print(f"  {r['label']:6}{r['t0']/60:5.1f}-{r['t1']/60:<7.1f}"
              f"{r['n_strokes']:>8}{r['cadence']:>7.1f}{r['connected_pct']:>8.0f}"
              f"{r['lull_frac_med']:>8.2f}{r['drive_over_catch_med']:>7.1f}"
              f"{r['gap_pct_med']:>7.0f}")

    # ---- Grouped A-vs-B summary (if labels given) ----------------------------
    groups = {}
    if labels:
        for r in results:
            groups.setdefault(r["label"], []).append(r)
        print("-" * 78)
        print("  GROUPED:")
        for lab, rs in groups.items():
            flags = np.concatenate([r["connected_flags"] for r in rs])
            cad = np.mean([r["cadence"] for r in rs])
            print(f"    {lab}: {len(flags)} strokes, cadence {cad:.1f} spm, "
                  f"connected {100*np.mean(flags):.0f}%")
    print("=" * 78)
    print("  Reminder: connection is KG-only and still being validated as a")
    print("  technique metric. Matched cadence across pieces is required for a")
    print("  fair comparison — check the 'cad' column.")

    # ---- Plot ----------------------------------------------------------------
    phase = np.linspace(0, 100, 101)
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    cmap = plt.cm.tab10(np.linspace(0, 1, max(2, len(results))))
    for i, r in enumerate(results):
        axes[0].plot(phase, r["mean_curve"], color=cmap[i], linewidth=2,
                     label=f"{r['label']} ({r['cadence']:.0f} spm, conn {r['connected_pct']:.0f}%)")
    axes[0].set_xlabel("Stroke phase (%)")
    axes[0].set_ylabel("Effective drive force (N)")
    axes[0].set_title("Mean drive-force curve per piece")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8)

    bar_labels = [r["label"] for r in results]
    bar_vals = [r["connected_pct"] for r in results]
    axes[1].bar(bar_labels, bar_vals, color=cmap[:len(results)])
    axes[1].set_ylabel("Connected (single-peak) strokes (%)")
    axes[1].set_title("Connection % per piece  (higher = cleaner catch-to-drive)")
    axes[1].grid(True, alpha=0.3)
    for i, v in enumerate(bar_vals):
        axes[1].text(i, v + 0.5, f"{v:.0f}%", ha="center", fontsize=10, fontweight="bold")

    fig.suptitle(f"Connection test — session {cfg.session_id} ({cfg.date})  |  "
                 f"pieces from {source}", fontsize=11)
    fig.tight_layout()
    savepath = os.path.join(cfg.plots_dir, "32_connection_test.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved: {savepath}")


if __name__ == "__main__":
    main()
