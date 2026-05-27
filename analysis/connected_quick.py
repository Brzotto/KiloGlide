"""Quick lookup: Connected % per lap.

Prints Connected % (and supporting cadence / speed / force) for each lap.
If the session manifest has `compare_laps`, only those laps are printed.
Otherwise prints every cruise-length lap.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, analyze_lap,
)
from session_config import get_session_from_args


def main():
    cfg = get_session_from_args()
    print(f"Loading session {cfg.session_id}...")
    kg = load_kg(cfg.kg_path)
    tcx = load_tcx(cfg.tcx_path)
    align = align_kg_to_garmin(kg, tcx)
    R, _ = detect_imu_axes(kg)
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    # Use manifest comparison laps if set; otherwise every lap in the session.
    if cfg.compare_laps:
        lap_idxs = [c["idx"] for c in cfg.compare_laps]
    else:
        lap_idxs = sorted(laps_by_idx.keys())

    print(f"{'Lap':>4} {'SPM':>5} {'Speed':>6} {'PeakF(N)':>9} {'Connected%':>11}")
    print("-" * 45)
    for li in lap_idxs:
        if li not in laps_by_idx:
            continue
        r = analyze_lap(kg, A_body, G_body, laps_by_idx[li], align, cfg.system_mass_kg)
        if r is None or r["n_strokes"] < 5:
            continue
        print(f"  {li:2d}  {r['cadence_spm']:4.1f}  {r['mean_speed_m_s']:5.2f}  "
              f"{r['mean_peak_force_N']:8.1f}  {r['connected_fraction']*100:9.1f}%")


if __name__ == "__main__":
    main()
