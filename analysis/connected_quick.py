"""Quick lookup: Connected % for L2, L3, L13."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

from correlate_kg_garmin import (
    load_kg, load_tcx, align_kg_to_garmin, detect_imu_axes,
    rotate_accel, rotate_gyro, analyze_lap,
)
from session_config import get_session_from_args

cfg = get_session_from_args()
kg = load_kg(cfg.kg_path)
tcx = load_tcx(cfg.tcx_path)
align = align_kg_to_garmin(kg, tcx)
R, _ = detect_imu_axes(kg)
A_body = rotate_accel(R, kg["accel_raw"])
G_body = rotate_gyro(R, kg["gyro_raw"])
laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

print(f"{'Lap':>4} {'SPM':>5} {'Speed':>6} {'PeakF(N)':>9} {'Connected%':>11}")
print("-" * 45)
for li in [2, 3, 13]:
    r = analyze_lap(kg, A_body, G_body, laps_by_idx[li], align, cfg.system_mass_kg)
    print(f"  {li:2d}  {r['cadence_spm']:4.1f}  {r['mean_speed_m_s']:5.2f}  "
          f"{r['mean_peak_force_N']:8.1f}  {r['connected_fraction']*100:9.1f}%")
