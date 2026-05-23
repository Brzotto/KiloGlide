"""
Session 37 — test whether side-switching is rhythmic.

If the user truly switches every ~5-15 strokes, run lengths should CLUSTER at
that value, not spread uniformly from 1 to 19. Spread = many real long blocks
broken by isolated sign flips.

Diagnostics:
  1. Run-length histogram for raw envelope-sign labels.
  2. Autocorrelation of the side-sign signal: rhythmic switching shows a clear
     negative peak at half-period and positive peak at full period.
  3. Apply HYSTERESIS: require N consecutive strokes on the new side before
     declaring a switch. Re-compute run statistics. If hysteresis dramatically
     tightens the run-length distribution, the underlying rhythm is real and
     the broken blocks were noise.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from side_envelope import collect_lap, runs
from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    KG_PATH, TCX_PATH, PLOTS_DIR,
)


def apply_hysteresis(signs, k=3):
    """Smooth a sign sequence by requiring k consecutive same-side strokes
    to flip. The 'current side' is held until k strokes in a row argue for
    the new side. Returns the smoothed sign sequence."""
    if len(signs) == 0:
        return signs
    out = np.array(signs, dtype=int).copy()
    cur = int(signs[0])
    pending_sign = cur
    pending_count = 1
    for i in range(1, len(signs)):
        s = int(signs[i])
        if s == cur:
            pending_count = 0
            pending_sign = cur
        else:
            if s == pending_sign:
                pending_count += 1
            else:
                pending_sign = s
                pending_count = 1
            if pending_count >= k:
                cur = pending_sign
                pending_count = 0
        out[i] = cur
    return out


def autocorrelation(signs):
    s = np.array(signs, dtype=float)
    s = s - s.mean()
    if np.std(s) == 0:
        return np.array([1.0])
    n = len(s)
    ac = np.correlate(s, s, mode="full")[n - 1:]
    return ac / ac[0]


def plot_rhythm_diagnostics(kg, R, tcx, align, savepath, lap_ids=(2, 3, 9, 13)):
    fig, axes = plt.subplots(len(lap_ids), 3, figsize=(16, 3 * len(lap_ids)))
    for row, li in enumerate(lap_ids):
        d = collect_lap(kg, R, tcx, align, li)
        env = d["catch_env"]
        if len(env) < 20:
            continue
        raw_signs = np.sign(env)
        raw_signs[raw_signs == 0] = 1
        hyst2 = apply_hysteresis(raw_signs, k=2)
        hyst3 = apply_hysteresis(raw_signs, k=3)

        rs_raw = runs(raw_signs.tolist())
        rs_h2 = runs(hyst2.tolist())
        rs_h3 = runs(hyst3.tolist())
        rl_raw = [r[0] for r in rs_raw]
        rl_h2 = [r[0] for r in rs_h2]
        rl_h3 = [r[0] for r in rs_h3]

        bins = np.arange(0.5, max(max(rl_raw, default=1),
                                  max(rl_h2, default=1),
                                  max(rl_h3, default=1)) + 1.5)

        # Panel 1: run-length histograms
        ax = axes[row, 0]
        ax.hist(rl_raw, bins=bins, alpha=0.4, color="gray", label=f"raw ({len(rs_raw)} runs, med {int(np.median(rl_raw))})")
        ax.hist(rl_h2, bins=bins, alpha=0.5, color="steelblue", label=f"hyst k=2 ({len(rs_h2)} runs, med {int(np.median(rl_h2))})")
        ax.hist(rl_h3, bins=bins, alpha=0.7, color="darkorange", label=f"hyst k=3 ({len(rs_h3)} runs, med {int(np.median(rl_h3))})")
        ax.axvspan(8, 15, color="green", alpha=0.10)
        ax.set_xlabel("Run length")
        ax.set_ylabel("Count")
        ax.set_title(f"Lap {li} — run-length distribution")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # Panel 2: hysteresis k=3 labels over stroke index
        ax = axes[row, 1]
        x = np.arange(1, len(env) + 1)
        colors = ["crimson" if s < 0 else "navy" for s in hyst3]
        ax.bar(x, hyst3 * np.abs(env), color=colors, alpha=0.85, width=1.0)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"Lap {li} — hysteresis k=3 cleaned labels  "
                     f"(L={int(np.sum(hyst3 < 0))} / R={int(np.sum(hyst3 > 0))})")
        ax.set_xlabel("Stroke # within lap")
        ax.set_ylabel("Signed envelope")
        ax.grid(True, alpha=0.3)

        # Panel 3: autocorrelation of raw signs
        ax = axes[row, 2]
        ac = autocorrelation(raw_signs.tolist())
        ax.bar(np.arange(min(80, len(ac))), ac[:80], color="purple", alpha=0.85, width=1.0)
        ax.axhline(0, color="black", linewidth=0.5)
        # Mark the first negative trough and first positive peak after lag 0
        first_neg = None
        first_pos = None
        for i in range(2, min(60, len(ac))):
            if first_neg is None and ac[i] < -0.15:
                first_neg = i
            if first_neg is not None and first_pos is None and ac[i] > 0.15:
                first_pos = i
                break
        if first_neg is not None:
            ax.axvline(first_neg, color="crimson", linewidth=1.5,
                       label=f"first dip @ lag {first_neg}")
        if first_pos is not None:
            ax.axvline(first_pos, color="green", linewidth=1.5,
                       label=f"first peak @ lag {first_pos}")
        ax.set_xlabel("Lag (strokes)")
        ax.set_ylabel("Autocorr of side sign")
        ax.set_title(f"Lap {li} — side-sign autocorrelation")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    kg = load_kg(KG_PATH)
    tcx = load_tcx(TCX_PATH)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)

    print("Computing rhythm diagnostics across cruise laps...")
    plot_rhythm_diagnostics(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "11_side_rhythm_diagnostics.png"),
        lap_ids=(2, 3, 9, 13),
    )

    print("\nPer-lap summary with and without hysteresis:")
    for li in (2, 3, 9, 13):
        d = collect_lap(kg, R, tcx, align, li)
        env = d["catch_env"]
        if len(env) < 20:
            continue
        raw_signs = np.sign(env)
        raw_signs[raw_signs == 0] = 1
        for k in (1, 2, 3):
            cleaned = apply_hysteresis(raw_signs, k=k) if k > 1 else raw_signs
            rs = runs(cleaned.tolist())
            rl = np.array([r[0] for r in rs])
            in_range = float(np.mean((rl >= 8) & (rl <= 15)))
            print(f"  Lap {li}  hyst k={k}:  {len(rs):>4} runs, median {int(np.median(rl))}, "
                  f"max {int(np.max(rl))}, fraction in 8-15: {in_range:.2f}")
    print("Done.")


if __name__ == "__main__":
    main()
