"""Post-session calibration sanity check.

Reads a binary session log and analyzes the first N seconds - assumed to
be the dock-calibration segment when the device sat still - to extract:

  - Gyro bias per axis (mean, what to subtract from later analysis)
  - Accel bias per axis (mean, mostly gravity)
  - Accel magnitude (should be ~9.81 m/s^2 - anything else means scale error
    OR the still segment had real motion in it)
  - Noise floor per axis (standard deviation - confirms the device was
    actually still)
  - Which axis gravity is on (sanity-checks the mounting orientation)

Run this back at the truck after a water session. If the numbers look
right, you have a usable calibration baseline for the rest of the data.

Usage:
    python tools/check_calibration.py session.bin
    python tools/check_calibration.py session.bin --seconds 15
    python tools/check_calibration.py session.bin --skip-leading 2
"""

import argparse
import math
import os
import sys

# Add the tools/ dir to path so we can import the sibling parser.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kg_parse


# Acceptance thresholds. Tune as field experience accumulates.
GYRO_BIAS_WARN_DPS = 2.0          # >2 deg/s drift is unusual at rest
GYRO_NOISE_WARN_DPS = 1.0         # >1 deg/s stdev = something moved
ACCEL_MAG_TOLERANCE = 0.3         # |9.81 - measured| > 0.3 m/s^2 is suspect
ACCEL_NOISE_WARN_MPS2 = 0.5       # >0.5 m/s^2 stdev = device wasn't still


def mean(values):
    return sum(values) / len(values) if values else 0.0


def stdev(values):
    if len(values) < 2:
        return 0.0
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def status(ok, warn_msg=""):
    """Return a short pass/warn tag for printing."""
    return "OK  " if ok else f"WARN  ({warn_msg})"


def check_calibration(path, seconds=15.0, skip_leading=2.0):
    """Analyze the still segment at the start of a session.

    Args:
        path: path to a .bin session log
        seconds: how many seconds of "still" data to analyze
        skip_leading: seconds to skip at the very start (button bounce,
                      hands still moving, etc.)
    """
    result, err = kg_parse.parse_file(path)
    if err:
        print(f"ERROR: {err}")
        return False

    imu = result["records"]["imu"]
    if not imu:
        print("ERROR: no IMU records in log")
        return False

    # Filter timestamp underflows (pre-PR-15 bug; harmless here, just skip).
    imu = [s for s in imu if s["ts"] <= kg_parse.TS_MAX_PLAUSIBLE]
    if not imu:
        print("ERROR: all IMU records have underflowed timestamps")
        return False

    t0_ms = imu[0]["ts"]
    start_ms = t0_ms + int(skip_leading * 1000)
    end_ms = start_ms + int(seconds * 1000)

    segment = [s for s in imu if start_ms <= s["ts"] <= end_ms]
    if len(segment) < 100:
        print(f"ERROR: only {len(segment)} IMU samples in [{skip_leading:.1f}s, "
              f"{skip_leading + seconds:.1f}s] window - was the session long enough?")
        return False

    # Convert raw int16 to physical units.
    A = kg_parse.ACCEL_SCALE
    G_DEG = kg_parse.GYRO_SCALE * 180.0 / math.pi  # raw -> deg/s for human-readable output
    G_RAD = kg_parse.GYRO_SCALE                    # raw -> rad/s for analysis use

    ax = [s["ax"] * A for s in segment]
    ay = [s["ay"] * A for s in segment]
    az = [s["az"] * A for s in segment]
    gx_dps = [s["gx"] * G_DEG for s in segment]
    gy_dps = [s["gy"] * G_DEG for s in segment]
    gz_dps = [s["gz"] * G_DEG for s in segment]

    # Per-axis stats.
    ax_mean, ay_mean, az_mean = mean(ax), mean(ay), mean(az)
    ax_std,  ay_std,  az_std  = stdev(ax), stdev(ay), stdev(az)
    gx_mean, gy_mean, gz_mean = mean(gx_dps), mean(gy_dps), mean(gz_dps)
    gx_std,  gy_std,  gz_std  = stdev(gx_dps), stdev(gy_dps), stdev(gz_dps)

    # Accel magnitude - sample-wise, then averaged. This is the right way to
    # check sensor scale: a vector of length 9.81 will read 9.81 regardless of
    # how gravity is split across axes.
    mags = [math.sqrt(x*x + y*y + z*z) for x, y, z in zip(ax, ay, az)]
    mag_mean = mean(mags)
    mag_std = stdev(mags)

    # Which axis is gravity primarily on? Useful for sanity-checking mounting.
    gravity_axis = max(
        [("X", ax_mean), ("Y", ay_mean), ("Z", az_mean)],
        key=lambda kv: abs(kv[1])
    )

    # --- Print report ---
    fname = os.path.basename(path)
    print(f"\n{'='*60}")
    print(f"  Calibration check: {fname}")
    print(f"{'='*60}")
    print(f"  Session ID:      {result['header']['session_id']}")
    print(f"  Still segment:   {skip_leading:.1f}s to {skip_leading + seconds:.1f}s  "
          f"({len(segment)} samples)")
    print()

    # Gyro bias section
    gyro_bias_ok = (abs(gx_mean) < GYRO_BIAS_WARN_DPS and
                    abs(gy_mean) < GYRO_BIAS_WARN_DPS and
                    abs(gz_mean) < GYRO_BIAS_WARN_DPS)
    gyro_noise_ok = (gx_std < GYRO_NOISE_WARN_DPS and
                     gy_std < GYRO_NOISE_WARN_DPS and
                     gz_std < GYRO_NOISE_WARN_DPS)

    print(f"  Gyro bias (subtract these from later samples):")
    print(f"    X: {gx_mean:+7.3f} deg/s  ({gx_mean * math.pi / 180.0:+8.5f} rad/s)")
    print(f"    Y: {gy_mean:+7.3f} deg/s  ({gy_mean * math.pi / 180.0:+8.5f} rad/s)")
    print(f"    Z: {gz_mean:+7.3f} deg/s  ({gz_mean * math.pi / 180.0:+8.5f} rad/s)")
    print(f"    {status(gyro_bias_ok, f'>{GYRO_BIAS_WARN_DPS} deg/s - unusual at rest')}")
    print()
    print(f"  Gyro noise (per-axis stdev - confirms device was still):")
    print(f"    X: {gx_std:.3f} deg/s")
    print(f"    Y: {gy_std:.3f} deg/s")
    print(f"    Z: {gz_std:.3f} deg/s")
    print(f"    {status(gyro_noise_ok, f'>{GYRO_NOISE_WARN_DPS} deg/s - device was moving')}")
    print()

    # Accel section
    mag_ok = abs(mag_mean - 9.80665) < ACCEL_MAG_TOLERANCE
    accel_noise_ok = (ax_std < ACCEL_NOISE_WARN_MPS2 and
                      ay_std < ACCEL_NOISE_WARN_MPS2 and
                      az_std < ACCEL_NOISE_WARN_MPS2)

    print(f"  Accel mean (mostly gravity):")
    print(f"    X: {ax_mean:+7.3f} m/s^2")
    print(f"    Y: {ay_mean:+7.3f} m/s^2")
    print(f"    Z: {az_mean:+7.3f} m/s^2")
    print()
    print(f"  Accel magnitude (should be 9.81):")
    print(f"    |a| = {mag_mean:.3f} +/- {mag_std:.3f} m/s^2  "
          f"({(mag_mean - 9.80665) / 9.80665 * 100:+.1f}% vs. true g)")
    print(f"    {status(mag_ok, f'|9.81 - measured| > {ACCEL_MAG_TOLERANCE}')}")
    print()
    print(f"  Accel noise (per-axis stdev):")
    print(f"    X: {ax_std:.3f}  Y: {ay_std:.3f}  Z: {az_std:.3f}  m/s^2")
    print(f"    {status(accel_noise_ok, f'>{ACCEL_NOISE_WARN_MPS2} - device was not still')}")
    print()

    # Mounting / axis inference
    sign = "+" if gravity_axis[1] > 0 else "-"
    print(f"  Inferred mounting:")
    print(f"    Gravity points along {sign}{gravity_axis[0]} ({gravity_axis[1]:+.2f} m/s^2)")
    print(f"    -> The {sign}{gravity_axis[0]} axis is 'down' relative to the IMU chip")
    if gravity_axis[0] != "Y":
        print(f"    Note: expected gravity on Y if LSM6DSOX is mounted flat with chip face up.")
        print(f"          If you mounted the device differently, this is informational, not an error.")
    print()

    # Overall verdict
    all_ok = gyro_bias_ok and gyro_noise_ok and mag_ok and accel_noise_ok
    print(f"  Overall: {'CALIBRATION SEGMENT LOOKS GOOD' if all_ok else 'REVIEW WARNINGS ABOVE'}")
    print()

    return all_ok


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help="One or more .bin session logs")
    p.add_argument("--seconds", type=float, default=15.0,
                   help="Length of still segment to analyze (default 15s)")
    p.add_argument("--skip-leading", type=float, default=2.0,
                   help="Seconds to skip at session start (default 2s - covers "
                        "button-press settling and initial hand motion)")
    args = p.parse_args()

    any_failed = False
    for path in args.files:
        ok = check_calibration(path, seconds=args.seconds,
                               skip_leading=args.skip_leading)
        if not ok:
            any_failed = True

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
