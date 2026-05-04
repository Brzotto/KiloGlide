"""
KiloGlide — Fake IMU Data Generator

Generates synthetic 6-axis IMU data (accel + gyro) at 416 Hz
with realistic paddling stroke patterns. Outputs a CSV file
that the analysis pipeline can load.

Usage:
    python tools/fake_imu.py                    # defaults: 2 min, 55 spm
    python tools/fake_imu.py --duration 300     # 5 minutes
    python tools/fake_imu.py --spm 45           # 45 strokes per minute
    python tools/fake_imu.py --asymmetry 0.15   # 15% left-right imbalance
    python tools/fake_imu.py --fatigue 0.3      # 30% force decline over session
"""

import argparse
import numpy as np
import os

SAMPLE_RATE = 416  # Hz, matches LSM6DSOX native ODR


def generate_single_stroke(n_samples, peak_force, peak_position=0.35, side='R'):
    """
    Generate one stroke's acceleration profile.

    The shape is a skewed bell curve: fast rise to peak (the catch),
    slower decay (the drive and exit). This matches real paddling
    biomechanics where the catch is sharp and the exit is gradual.

    Args:
        n_samples: number of IMU samples for this stroke
        peak_force: maximum acceleration in m/s^2
        peak_position: where in the stroke the peak occurs (0-1)
        side: 'L' or 'R', affects roll direction
    """
    t = np.linspace(0, 1, n_samples)
    peak_idx = peak_position

    # Skewed gaussian-ish shape for the force curve
    # Sharper rise (catch), slower decay (exit)
    rise = np.exp(-((t - peak_idx) ** 2) / (2 * (0.08 ** 2)))
    decay = np.exp(-((t - peak_idx) ** 2) / (2 * (0.15 ** 2)))
    stroke_shape = np.where(t < peak_idx, rise, decay)

    # Scale to peak force
    stroke_shape = stroke_shape * peak_force

    # Add a small negative phase at the exit (the "checking" Ray talks about)
    exit_region = t > 0.75
    stroke_shape[exit_region] -= peak_force * 0.05

    # Forward acceleration (z-axis in boat frame)
    accel_z = stroke_shape

    # Lateral acceleration (x-axis) — small, from torso rotation
    accel_x = stroke_shape * 0.15 * (1 if side == 'R' else -1)

    # Vertical acceleration (y-axis) — minimal during stroke
    accel_y = stroke_shape * 0.05 + 9.81  # gravity baseline

    # Roll from the stroke (gyro_x) — the key signal for side detection
    roll_amplitude = 25.0  # degrees per second
    roll_sign = 1 if side == 'R' else -1
    gyro_x = roll_sign * roll_amplitude * np.sin(t * np.pi) * (stroke_shape / peak_force)

    # Pitch (gyro_y) — small forward lean during catch
    gyro_y = 5.0 * np.sin(t * np.pi * 2) * (stroke_shape / peak_force)

    # Yaw (gyro_z) — torso rotation
    gyro_z = 8.0 * np.sin(t * np.pi) * (1 if side == 'R' else -1)

    return accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z


def generate_glide(n_samples):
    """
    Generate the glide phase between strokes.

    During glide, the boat decelerates from drag. Accelerometer
    reads mostly gravity with small noise. Gyro reads near-zero
    with small oscillations from water movement.
    """
    noise_scale = 0.05

    accel_x = np.random.normal(0, noise_scale, n_samples)
    accel_y = np.full(n_samples, 9.81) + np.random.normal(0, noise_scale, n_samples)
    accel_z = np.random.normal(-0.3, noise_scale, n_samples)  # slight deceleration from drag
    gyro_x = np.random.normal(0, 0.5, n_samples)
    gyro_y = np.random.normal(0, 0.3, n_samples)
    gyro_z = np.random.normal(0, 0.3, n_samples)

    return accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z


def generate_session(duration_sec, strokes_per_minute, asymmetry=0.0, fatigue=0.0):
    """
    Generate a full paddling session.

    Args:
        duration_sec: session length in seconds
        strokes_per_minute: stroke rate (typical: 45-65 spm)
        asymmetry: left-right force imbalance (0.0 = symmetric, 0.15 = 15% weaker on left)
        fatigue: force decline over session (0.0 = none, 0.3 = 30% decline by end)

    Returns:
        timestamps: array of timestamps in seconds
        accel: (N, 3) array of accelerometer data [x, y, z]
        gyro: (N, 3) array of gyroscope data [x, y, z]
        stroke_events: list of (timestamp, side) tuples marking each stroke
    """
    total_samples = int(duration_sec * SAMPLE_RATE)
    stroke_period = 60.0 / strokes_per_minute  # seconds per stroke
    samples_per_stroke = int(stroke_period * SAMPLE_RATE * 0.55)  # stroke is ~55% of cycle
    samples_per_glide = int(stroke_period * SAMPLE_RATE * 0.45)   # glide is ~45%

    base_peak_force = 8.0  # m/s^2, typical for recreational paddler

    all_ax, all_ay, all_az = [], [], []
    all_gx, all_gy, all_gz = [], [], []
    stroke_events = []

    sample_count = 0
    stroke_num = 0
    side = 'R'  # start on right

    while sample_count < total_samples:
        # Apply fatigue: linear decline in peak force over session
        progress = sample_count / total_samples
        fatigue_factor = 1.0 - (fatigue * progress)

        # Apply asymmetry: one side is weaker
        if side == 'L':
            side_factor = 1.0 - asymmetry
        else:
            side_factor = 1.0

        # Add natural variation (±5%)
        variation = np.random.normal(1.0, 0.05)

        peak_force = base_peak_force * fatigue_factor * side_factor * variation

        # Slight variation in peak position (catch timing)
        peak_pos = np.random.normal(0.35, 0.03)
        peak_pos = np.clip(peak_pos, 0.2, 0.5)

        # Generate stroke
        n_stroke = min(samples_per_stroke, total_samples - sample_count)
        if n_stroke <= 0:
            break

        ax, ay, az, gx, gy, gz = generate_single_stroke(
            n_stroke, peak_force, peak_pos, side
        )

        # Record stroke event
        stroke_time = sample_count / SAMPLE_RATE
        stroke_events.append((stroke_time, side))

        all_ax.append(ax)
        all_ay.append(ay)
        all_az.append(az)
        all_gx.append(gx)
        all_gy.append(gy)
        all_gz.append(gz)
        sample_count += n_stroke

        # Generate glide
        n_glide = min(samples_per_glide, total_samples - sample_count)
        if n_glide <= 0:
            break

        ax, ay, az, gx, gy, gz = generate_glide(n_glide)
        all_ax.append(ax)
        all_ay.append(ay)
        all_az.append(az)
        all_gx.append(gx)
        all_gy.append(gy)
        all_gz.append(gz)
        sample_count += n_glide

        # Alternate sides
        side = 'L' if side == 'R' else 'R'
        stroke_num += 1

    # Concatenate and trim to exact length
    accel_x = np.concatenate(all_ax)[:total_samples]
    accel_y = np.concatenate(all_ay)[:total_samples]
    accel_z = np.concatenate(all_az)[:total_samples]
    gyro_x = np.concatenate(all_gx)[:total_samples]
    gyro_y = np.concatenate(all_gy)[:total_samples]
    gyro_z = np.concatenate(all_gz)[:total_samples]

    timestamps = np.arange(total_samples) / SAMPLE_RATE

    accel = np.column_stack([accel_x, accel_y, accel_z])
    gyro = np.column_stack([gyro_x, gyro_y, gyro_z])

    return timestamps, accel, gyro, stroke_events


def save_csv(filepath, timestamps, accel, gyro):
    """Save session data to CSV for easy loading in any tool."""
    header = "timestamp,accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z"
    data = np.column_stack([timestamps, accel, gyro])
    np.savetxt(filepath, data, delimiter=',', header=header, comments='', fmt='%.6f')


def save_stroke_events(filepath, stroke_events):
    """Save ground-truth stroke events for validation."""
    with open(filepath, 'w') as f:
        f.write("timestamp,side\n")
        for time, side in stroke_events:
            f.write(f"{time:.6f},{side}\n")


def main():
    parser = argparse.ArgumentParser(description='Generate fake IMU data for KiloGlide')
    parser.add_argument('--duration', type=float, default=120,
                        help='Session duration in seconds (default: 120)')
    parser.add_argument('--spm', type=float, default=55,
                        help='Strokes per minute (default: 55)')
    parser.add_argument('--asymmetry', type=float, default=0.10,
                        help='Left-right force imbalance, 0-1 (default: 0.10)')
    parser.add_argument('--fatigue', type=float, default=0.15,
                        help='Force decline over session, 0-1 (default: 0.15)')
    parser.add_argument('--output', type=str, default='sessions/fake_session.csv',
                        help='Output CSV path')
    args = parser.parse_args()

    print(f"Generating {args.duration:.0f}s session at {args.spm:.0f} spm...")
    print(f"  Asymmetry: {args.asymmetry:.0%}")
    print(f"  Fatigue: {args.fatigue:.0%}")

    timestamps, accel, gyro, stroke_events = generate_session(
        args.duration, args.spm, args.asymmetry, args.fatigue
    )

    # Make sure output directory exists
    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)

    save_csv(args.output, timestamps, accel, gyro)
    events_path = args.output.replace('.csv', '_strokes.csv')
    save_stroke_events(events_path, stroke_events)

    print(f"  Total samples: {len(timestamps)}")
    print(f"  Total strokes: {len(stroke_events)}")
    print(f"  Saved to: {args.output}")
    print(f"  Stroke events: {events_path}")


if __name__ == '__main__':
    main()
