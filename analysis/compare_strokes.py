"""
compare_strokes.py — overlay per-stroke force-vs-distance curves and compare
technique metrics across sessions / paddlers / pieces on one axis.

Each --entry is  SESSION:WINDOW:LABEL :
  SESSION  manifest session id (int)
  WINDOW   either  A-B   (KG-local MINUTES, e.g. 32.4-37.0) for a manual or
           GPS-detected piece, OR  lapN  (a Garmin lap index, e.g. lap23)
  LABEL    free text for the legend/table (no ':' in it)

Examples
  # Austin's time-trial (left, good strokes) vs my strong dragon-boat piece
  python analysis/compare_strokes.py \
      --entry "46:32.4-37.0:Austin TT (L)" \
      --entry "42:lap23:Me dragon-boat (R)"

Works with or without a Garmin export: a `lapN` window needs the session's
Garmin file; an `A-B` window does not (KG-local time IS the axis, anchored by
the log's TIME records). Reuses the exact same stroke math as perg_plot
(`force_vs_distance_curve`) and connected_quick (`analyze_lap`), so the numbers
match the per-session tools.

Saves one overlay to analysis/plots/compare/ and prints a comparison table.

NOTE ON UNITS: work (J) and peak force (lbf) are boat-response quantities and
scale with each session's `system_mass_kg`, so compare them only when the
masses are known/trustworthy. `fullness` (arch shape), connection %, cadence
and speed do not depend on mass, so they compare cleanly between paddlers.
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

from session_config import get_session
from correlate_kg_garmin import (
    load_kg, load_garmin, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, lap_local_window, analyze_lap,
    force_vs_distance_curve, detect_strokes,
)

N_TO_LBF = 0.224809
MS_TO_MPH = 2.23694


def load_session_bundle(sess, cache):
    """Load + rotate a session once; cache so a session reused across entries
    isn't re-parsed (the KG logs are large)."""
    if sess in cache:
        return cache[sess]
    cfg = get_session(sess)
    print(f"  loading session {sess} ({cfg.date}, mass {cfg.system_mass_kg:.0f} kg)...")
    kg = load_kg(cfg.kg_path)
    garmin = load_garmin(cfg.garmin_path) if cfg.garmin_path else None
    align = align_kg_to_garmin(kg, garmin)
    R, _ = detect_imu_axes(kg)
    A = rotate_accel(R, kg["accel_raw"])
    G = rotate_gyro(R, kg["gyro_raw"])
    laps_by_idx = {lap["idx"]: lap for lap in garmin["laps"]} if garmin else {}
    bundle = dict(cfg=cfg, kg=kg, align=align, A=A, G=G, laps_by_idx=laps_by_idx)
    cache[sess] = bundle
    return bundle


def resolve_window(bundle, window, label):
    """Resolve a WINDOW spec to (lap_dict, t0_local, t1_local) in KG seconds.

    'lapN'  -> the real Garmin lap (needs the export).
    'A-B'   -> a synthetic lap covering KG-local minutes A..B, built so that
               lap_local_window() returns exactly that window.
    """
    align = bundle["align"]
    sid = bundle["cfg"].session_id
    if window.lower().startswith("lap"):
        li = int(window[3:])
        if li not in bundle["laps_by_idx"]:
            raise SystemExit(f"Session {sid} has no lap {li} (need its Garmin "
                             f"export). Available laps: {sorted(bundle['laps_by_idx'])}")
        lap = bundle["laps_by_idx"][li]
        t0, t1 = lap_local_window(lap, align)
        return lap, t0, t1
    if "-" not in window:
        raise SystemExit(f"Bad WINDOW '{window}': use 'A-B' minutes or 'lapN'.")
    a, b = window.split("-")
    t0, t1 = float(a) * 60.0, float(b) * 60.0
    if align["kg_t0_utc"] is None:
        raise SystemExit(f"Session {sid}: can't anchor a time window (no TIME "
                         f"records and no Garmin). Use a 'lapN' window instead.")
    lap = {"idx": label, "start_utc": align["kg_t0_utc"] + t0,
           "duration_s": t1 - t0, "distance_m": 0.0}
    return lap, t0, t1


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entry", action="append", required=True,
                   help="SESSION:WINDOW:LABEL (repeatable). WINDOW = 'A-B' "
                        "minutes or 'lapN'.")
    p.add_argument("--tag", default="compare",
                   help="filename tag for the output plot (default 'compare')")
    p.add_argument("--x-max", type=float, default=2.4,
                   help="distance axis max in metres (default 2.4)")
    p.add_argument("--spread", action="store_true",
                   help="per-stroke spread view: draw EVERY stroke (faint) + "
                        "median + 25-75%% band, one panel per entry, instead of "
                        "overlaying mean curves. Shows consistency + glide.")
    p.add_argument("--max-lines", type=int, default=200,
                   help="max individual stroke curves to draw per panel (spread "
                        "mode; evenly subsampled if the window has more)")
    p.add_argument("--cycle", action="store_true",
                   help="recovery-phase view: catch-to-catch stroke-cycle average "
                        "of forward accel (drive + brake), pitch-rate magnitude "
                        "(fore-aft rock) and heave magnitude (vertical bounce), "
                        "overlaid across entries with the glide region shaded.")
    return p


def run_spread(args, cache):
    """Per-stroke spread view: one panel per entry, every stroke drawn faint
    with the median + 25-75% band on top. Band width = consistency; the
    negative tail = glide/check. Prints a consistency stats table."""
    specs = args.entry
    n = len(specs)
    fig, axes = plt.subplots(1, n, figsize=(6.2 * n, 6.0), sharex=True, sharey=True)
    if n == 1:
        axes = [axes]
    colors = plt.cm.turbo(np.linspace(0.12, 0.88, n))
    stats = []

    for ax, c, spec in zip(axes, colors, specs):
        parts = spec.split(":", 2)
        if len(parts) != 3:
            raise SystemExit(f"Bad --entry '{spec}'. Use SESSION:WINDOW:LABEL.")
        sess_s, window, label = parts
        b = load_session_bundle(int(sess_s), cache)
        cfg = b["cfg"]
        lap, t0, t1 = resolve_window(b, window, label)
        fvd = force_vs_distance_curve(
            b["kg"]["imu_t"], b["A"][:, 0], b["G"][:, 0],
            b["kg"]["gps_t"], b["kg"]["gps_speed"], cfg.system_mass_kg, t0, t1,
            x_max=args.x_max, adaptive=cfg.adaptive_strokes, return_strokes=True)
        if fvd is None:
            print(f"  [skip] {label}: no usable strokes")
            continue

        sc = fvd["stroke_curves_lbf"]
        grid = fvd["grid"]
        N = sc.shape[0]
        sel = np.unique(np.linspace(0, N - 1, min(args.max_lines, N)).astype(int))
        for r in sc[sel]:
            ax.plot(grid, r, color=c, alpha=0.05, linewidth=0.6)
        med = np.nanmedian(sc, axis=0)
        p25 = np.nanpercentile(sc, 25, axis=0)
        p75 = np.nanpercentile(sc, 75, axis=0)
        ax.fill_between(grid, p25, p75, color=c, alpha=0.30, zorder=5)
        ax.plot(grid, med, color="black", linewidth=2.4, zorder=6)
        ax.axhline(0, color="gray", linewidth=0.6, linestyle="--")

        peaks = np.nanmax(sc, axis=1)
        glides = np.nanmin(sc, axis=1)
        works = fvd["work_per_stroke_J"]
        cv_peak = float(np.nanstd(peaks) / np.nanmean(peaks) * 100)
        cv_work = float(np.nanstd(works) / np.nanmean(works) * 100)
        gl_med = float(np.nanmedian(glides))
        gl_iqr = float(np.nanpercentile(glides, 75) - np.nanpercentile(glides, 25))
        ax.set_title(f"{label}\nN={N}   peak CV {cv_peak:.0f}%   work CV {cv_work:.0f}%\n"
                     f"glide {gl_med:.0f} lbf (IQR {gl_iqr:.0f})", fontsize=10)
        ax.set_xlabel("boat distance from catch (m)")
        ax.grid(True, alpha=0.3)
        stats.append((label, N, cv_peak, cv_work, gl_med, gl_iqr))

    axes[0].set_ylabel("drive force on boat (lbf)   (+ pull,  - glide)")
    fig.suptitle("Every stroke (faint) + median (black) + 25-75% band (color)  —  "
                 "narrow band = consistent;  shallow negative tail = better glide/run",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    outdir = os.path.join(HERE, "plots", "compare")
    os.makedirs(outdir, exist_ok=True)
    savepath = os.path.join(outdir, f"spread_{args.tag}.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)

    print(f"\nSaved spread view: {savepath}\n")
    hdr = f"{'label':<26}{'nstr':>6}{'peak_CV%':>9}{'work_CV%':>9}{'glide_lbf':>10}{'glide_IQR':>10}"
    print(hdr)
    print("-" * len(hdr))
    for label, N, cvp, cvw, gm, gi in stats:
        print(f"{label:<26}{N:>6}{cvp:>9.0f}{cvw:>9.0f}{gm:>10.0f}{gi:>10.0f}")
    print("\nLower CV = more consistent stroke-to-stroke. glide_lbf = median "
          "deepest braking force during recovery (closer to 0 = boat holds its "
          "run); glide_IQR = how variable that check is.")


def run_cycle(args, cache):
    """Catch-to-catch stroke-cycle view across entries: forward accel (drive +
    glide brake), pitch-rate magnitude (fore-aft rock) and heave magnitude
    (vertical bounce), each averaged over the normalized stroke cycle. The
    recovery/glide region (mean forward accel < 0) is shaded. Flatter and
    shallower through the shade = a quieter recovery that holds the run."""
    N = 100
    phase = np.linspace(0, 100, N)
    xi = np.linspace(0, 1, N)
    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    colors = plt.cm.turbo(np.linspace(0.12, 0.88, len(args.entry)))
    fmeans = []

    for c, spec in zip(colors, args.entry):
        parts = spec.split(":", 2)
        if len(parts) != 3:
            raise SystemExit(f"Bad --entry '{spec}'. Use SESSION:WINDOW:LABEL.")
        sess_s, window, label = parts
        b = load_session_bundle(int(sess_s), cache)
        lap, t0, t1 = resolve_window(b, window, label)
        skip = 60.0 if (t1 - t0) >= 90 else 10.0
        t = b["kg"]["imu_t"]
        m = (t >= t0 + skip) & (t <= t1)
        fwd = b["A"][m, 0]
        pitch = b["G"][m, 1]
        heave = b["A"][m, 2] - float(np.mean(b["A"][m, 2]))
        peaks = [i for _, i in detect_strokes(t[m], fwd, prominence=1.5,
                                              height=1.0, refractory_s=0.4)]
        catches = []
        for p in peaks:
            cc = p
            while cc > 0 and fwd[cc] > 0:
                cc -= 1
            catches.append(cc)
        F, P, H = [], [], []
        for a, bx in zip(catches[:-1], catches[1:]):
            if bx - a < 20:
                continue
            xs = np.linspace(0, 1, bx - a)
            F.append(np.interp(xi, xs, fwd[a:bx]))
            P.append(np.interp(xi, xs, pitch[a:bx]))
            H.append(np.interp(xi, xs, heave[a:bx]))
        if not F:
            print(f"  [skip] {label}: no cycles")
            continue
        F, P, H = np.array(F), np.array(P), np.array(H)
        fmean = F.mean(axis=0)
        fmeans.append(fmean)
        axes[0].plot(phase, fmean, color=c, linewidth=2.2, label=f"{label} ({len(F)} cyc)")
        axes[0].fill_between(phase, np.percentile(F, 25, axis=0),
                             np.percentile(F, 75, axis=0), color=c, alpha=0.12)
        axes[1].plot(phase, np.sqrt(np.mean(P ** 2, axis=0)), color=c, linewidth=2.2)
        axes[2].plot(phase, np.sqrt(np.mean(H ** 2, axis=0)), color=c, linewidth=2.2)

    if fmeans:
        comb = np.mean(np.array(fmeans), axis=0)
        i0 = int(np.argmax(comb))
        rec = np.where((comb < 0) & (np.arange(N) > i0))[0]
        if len(rec):
            for ax in axes:
                ax.axvspan(phase[rec[0]], phase[rec[-1]], color="gray", alpha=0.10)

    axes[0].axhline(0, color="gray", linewidth=0.6, linestyle="--")
    axes[0].set_ylabel("forward accel (m/s^2)\n+ drive  /  - brake")
    axes[1].set_ylabel("pitch-rate RMS (rad/s)\nfore-aft rock")
    axes[2].set_ylabel("heave RMS (m/s^2)\nvertical bounce")
    axes[2].set_xlabel("stroke-cycle phase (%)   catch -> drive -> exit -> recovery -> next catch")
    axes[0].set_title("Stroke-cycle motion (shaded = recovery/glide):  shallower brake (top) + "
                      "flatter rock (mid) + flatter bounce (bottom) = cleaner run")
    for ax in axes:
        ax.grid(True, alpha=0.3)
    axes[0].legend(fontsize=9, loc="upper right")
    fig.tight_layout()

    outdir = os.path.join(HERE, "plots", "compare")
    os.makedirs(outdir, exist_ok=True)
    savepath = os.path.join(outdir, f"recovery_{args.tag}.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved recovery-phase view: {savepath}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    cache = {}
    if args.spread:
        return run_spread(args, cache)
    if args.cycle:
        return run_cycle(args, cache)
    results = []

    fig, ax = plt.subplots(figsize=(11, 6.5))
    colors = plt.cm.turbo(np.linspace(0.05, 0.95, max(1, len(args.entry))))

    for c, spec in zip(colors, args.entry):
        parts = spec.split(":", 2)
        if len(parts) != 3:
            raise SystemExit(f"Bad --entry '{spec}'. Use SESSION:WINDOW:LABEL.")
        sess_s, window, label = parts
        b = load_session_bundle(int(sess_s), cache)
        cfg = b["cfg"]
        mass = cfg.system_mass_kg
        lap, t0, t1 = resolve_window(b, window, label)

        fvd = force_vs_distance_curve(
            b["kg"]["imu_t"], b["A"][:, 0], b["G"][:, 0],
            b["kg"]["gps_t"], b["kg"]["gps_speed"], mass, t0, t1,
            x_max=args.x_max, adaptive=cfg.adaptive_strokes)
        al = analyze_lap(b["kg"], b["A"], b["G"], lap, b["align"], mass,
                         adaptive=cfg.adaptive_strokes,
                         gap_fill=cfg.gap_fill_strokes)
        if fvd is None or al is None:
            print(f"  [skip] {label}: no usable strokes in window {window}")
            continue

        ax.plot(fvd["grid"], fvd["mean_curve_lbf"], color=c, linewidth=2.3,
                label=f"{label}  ({fvd['n_strokes']} str)  "
                      f"work {fvd['work_J']:.0f} J  full {fvd['fullness']:.2f}")
        results.append(dict(
            label=label, sess=int(sess_s), n=fvd["n_strokes"],
            work=fvd["work_J"], full=fvd["fullness"],
            peak_lbf=al["mean_peak_force_N"] * N_TO_LBF,
            conn=al["connected_fraction"] * 100.0,
            spm=al["cadence_spm"], mph=al["mean_speed_m_s"] * MS_TO_MPH,
            mass=mass))

    ax.axhline(0, color="gray", linewidth=0.7, linestyle="--")
    ax.set_xlabel("boat distance from the catch (m)")
    ax.set_ylabel("drive force on boat (lbf)   (+ pull,  - glide)")
    ax.set_title("Per-stroke force vs distance — area under the arch = work/stroke\n"
                 "compare matched efforts (absolute force/work scale with system mass)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9, loc="best")
    fig.tight_layout()

    outdir = os.path.join(HERE, "plots", "compare")
    os.makedirs(outdir, exist_ok=True)
    savepath = os.path.join(outdir, f"compare_{args.tag}.png")
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)

    print(f"\nSaved overlay: {savepath}\n")
    hdr = (f"{'label':<26}{'sess':>5}{'nstr':>6}{'work_J':>8}{'full':>6}"
           f"{'peakLbf':>9}{'conn%':>7}{'spm':>6}{'mph':>6}{'mass_kg':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(f"{r['label']:<26}{r['sess']:>5}{r['n']:>6}{r['work']:>8.0f}"
              f"{r['full']:>6.2f}{r['peak_lbf']:>9.1f}{r['conn']:>7.0f}"
              f"{r['spm']:>6.1f}{r['mph']:>6.2f}{r['mass']:>8.0f}")
    print("\nfull = work / (peak force x forward travel): arch fullness, 0..1, "
          "mass-independent. conn% = single-arch (connected) stroke fraction. "
          "work_J / peakLbf scale with system mass — read them with that in mind.")


if __name__ == "__main__":
    main()
