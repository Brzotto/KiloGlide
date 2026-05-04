"""
KiloGlide — Starter Analysis Script

Loads a session CSV (real or fake), runs basic stroke detection,
computes per-stroke features, and plots the results.

This is the analysis pipeline in its simplest form. Everything here
will eventually run against real IMU data from the device — the only
change will be the input file.

Usage:
    python analysis/analyze_session.py
    python analysis/analyze_session.py --file sessions/my_real_session.csv
"""

import argparse
import numpy as np
import matplotlib.pyplot as plt
import os
import sys

SAMPLE_RATE = 416  # Hz


def load_session(filepath):
    """Load a session CSV and return timestamps, accel, gyro arrays."""
    data = np.genfromtxt(filepath, delimiter=',', skip_header=1)
    timestamps = data[:, 0]
    accel = data[:, 1:4]  # x, y, z
    gyro = data[:, 4:7]   # x, y, z
    return timestamps, accel, gyro


def load_ground_truth(filepath):
    """Load ground-truth stroke events (from fake_imu.py)."""
    events = []
    with open(filepath, 'r') as f:
        next(f)  # skip header
        for line in f:
            parts = line.strip().split(',')
            events.append((float(parts[0]), parts[1]))
    return events


# =========================================================
# STROKE DETECTION — the v0 algorithm from math_primer.md
# =========================================================

def detect_strokes(timestamps, accel_z, threshold=3.0, refractory_sec=0.25):
    """
    Simple peak detection on forward acceleration.

    Args:
        timestamps: time array in seconds
        accel_z: forward-axis acceleration array
        threshold: minimum peak height to count as a stroke
        refractory_sec: minimum time between strokes

    Returns:
        list of (timestamp, sample_index) for each detected stroke
    """
    strokes = []
    in_peak = False
    last_stroke_time = -1.0

    for i in range(len(accel_z)):
        signal = abs(accel_z[i])

        if signal > threshold and not in_peak:
            if (timestamps[i] - last_stroke_time) > refractory_sec:
                strokes.append((timestamps[i], i))
                last_stroke_time = timestamps[i]
                in_peak = True

        elif signal < threshold * 0.7:  # hysteresis
            in_peak = False

    return strokes


def classify_stroke_side(gyro_x_segment):
    """
    Determine if a stroke is left or right based on roll velocity.

    Positive roll velocity at peak = right side stroke
    Negative = left side stroke
    """
    peak_idx = np.argmax(np.abs(gyro_x_segment))
    return 'R' if gyro_x_segment[peak_idx] > 0 else 'L'


# =========================================================
# STROKE CHARACTERIZATION — from math_primer.md section 4
# =========================================================

def characterize_stroke(accel_samples, dt):
    """
    Extract shape features from one stroke's acceleration trace.

    Returns a dict with:
        peak_value: maximum acceleration
        peak_position: where in the stroke the peak occurs (0-1)
        slope_to_peak: how sharply the catch ramps up
        impulse: area under the curve (total "effort")
        skew: balance of effort before vs after peak
    """
    if len(accel_samples) < 5:
        return None

    peak_idx = np.argmax(accel_samples)
    peak_value = accel_samples[peak_idx]

    peak_position = peak_idx / len(accel_samples)

    if peak_idx > 0:
        slope_to_peak = peak_value / (peak_idx * dt)
    else:
        slope_to_peak = 0

    impulse = np.sum(accel_samples) * dt

    if peak_idx > 0 and peak_idx < len(accel_samples) - 1:
        pre_peak_area = np.sum(accel_samples[:peak_idx]) * dt
        post_peak_area = np.sum(accel_samples[peak_idx:]) * dt
        if impulse != 0:
            skew = (post_peak_area - pre_peak_area) / impulse
        else:
            skew = 0
    else:
        skew = 0

    return {
        'peak_value': peak_value,
        'peak_position': peak_position,
        'slope_to_peak': slope_to_peak,
        'impulse': impulse,
        'skew': skew,
    }


def extract_stroke_segments(timestamps, accel_z, gyro_x, detected_strokes):
    """
    Given detected stroke timestamps, extract the acceleration segment
    for each stroke (from midpoint between strokes to midpoint).

    Returns list of dicts with features + side classification.
    """
    dt = 1.0 / SAMPLE_RATE
    stroke_features = []

    for i, (stroke_time, stroke_idx) in enumerate(detected_strokes):
        # Define segment boundaries: halfway to previous and next stroke
        if i == 0:
            start = 0
        else:
            start = (detected_strokes[i-1][1] + stroke_idx) // 2

        if i == len(detected_strokes) - 1:
            end = len(accel_z)
        else:
            end = (stroke_idx + detected_strokes[i+1][1]) // 2

        segment = accel_z[start:end]
        gyro_segment = gyro_x[start:end]

        features = characterize_stroke(np.abs(segment), dt)
        if features is None:
            continue

        features['time'] = stroke_time
        features['side'] = classify_stroke_side(gyro_segment)
        features['stroke_num'] = i
        stroke_features.append(features)

    return stroke_features


# =========================================================
# ANALYSIS — asymmetry and fatigue from math_primer.md
# =========================================================

def analyze_asymmetry(stroke_features):
    """Compare left vs right stroke features."""
    left = [s for s in stroke_features if s['side'] == 'L']
    right = [s for s in stroke_features if s['side'] == 'R']

    if not left or not right:
        print("  Not enough strokes on both sides for asymmetry analysis")
        return

    left_impulse = np.mean([s['impulse'] for s in left])
    right_impulse = np.mean([s['impulse'] for s in right])
    mean_impulse = (left_impulse + right_impulse) / 2

    asymmetry = (right_impulse - left_impulse) / mean_impulse

    left_peak = np.mean([s['peak_value'] for s in left])
    right_peak = np.mean([s['peak_value'] for s in right])
    peak_asymmetry = (right_peak - left_peak) / ((right_peak + left_peak) / 2)

    print(f"  Left strokes:  {len(left)}")
    print(f"  Right strokes: {len(right)}")
    print(f"  Impulse asymmetry: {asymmetry:+.1%} (positive = right stronger)")
    print(f"  Peak force asymmetry: {peak_asymmetry:+.1%}")
    print(f"  Left avg impulse:  {left_impulse:.3f}")
    print(f"  Right avg impulse: {right_impulse:.3f}")


def analyze_fatigue(stroke_features):
    """Fit a trend line through peak force over time."""
    if len(stroke_features) < 10:
        print("  Not enough strokes for fatigue analysis")
        return

    stroke_nums = np.array([s['stroke_num'] for s in stroke_features])
    peak_values = np.array([s['peak_value'] for s in stroke_features])

    # Linear regression
    coeffs = np.polyfit(stroke_nums, peak_values, 1)
    slope = coeffs[0]

    # Express as percentage decline over the session
    start_val = np.polyval(coeffs, stroke_nums[0])
    end_val = np.polyval(coeffs, stroke_nums[-1])
    if start_val != 0:
        pct_change = (end_val - start_val) / start_val
    else:
        pct_change = 0

    print(f"  Peak force trend: {pct_change:+.1%} over session")
    print(f"  Slope: {slope:.4f} per stroke")
    if pct_change < -0.10:
        print("  --> Significant fatigue detected")
    elif pct_change < -0.05:
        print("  --> Mild fatigue detected")
    else:
        print("  --> No significant fatigue")

    return coeffs


# =========================================================
# PLOTTING
# =========================================================

def plot_session_overview(timestamps, accel, gyro, detected_strokes):
    """Plot raw data with detected strokes marked."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)

    # Forward acceleration
    axes[0].plot(timestamps, accel[:, 2], linewidth=0.5, color='steelblue')
    for stroke_time, stroke_idx in detected_strokes:
        axes[0].axvline(stroke_time, color='red', alpha=0.3, linewidth=0.5)
    axes[0].set_ylabel('Accel Z (m/s²)')
    axes[0].set_title('Forward Acceleration + Detected Strokes')

    # Roll rate (key signal for side detection)
    axes[1].plot(timestamps, gyro[:, 0], linewidth=0.5, color='coral')
    axes[1].set_ylabel('Gyro X (°/s)')
    axes[1].set_title('Roll Rate (positive = right stroke)')
    axes[1].axhline(0, color='gray', linewidth=0.5, linestyle='--')

    # Lateral acceleration
    axes[2].plot(timestamps, accel[:, 0], linewidth=0.5, color='seagreen')
    axes[2].set_ylabel('Accel X (m/s²)')
    axes[2].set_xlabel('Time (seconds)')
    axes[2].set_title('Lateral Acceleration')

    plt.tight_layout()
    return fig


def plot_force_curves(stroke_features, n_strokes=10):
    """Plot overlaid force curves for the first N strokes."""
    # This is a simplified version — with real data you'd overlay
    # the actual acceleration segments. Here we show the feature summary.
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    times = [s['time'] for s in stroke_features]
    colors = ['steelblue' if s['side'] == 'R' else 'coral' for s in stroke_features]

    # Peak force over time
    peaks = [s['peak_value'] for s in stroke_features]
    axes[0, 0].scatter(times, peaks, c=colors, s=10, alpha=0.7)
    axes[0, 0].set_ylabel('Peak Force (m/s²)')
    axes[0, 0].set_title('Peak Force Over Time (blue=R, red=L)')

    # Impulse over time
    impulses = [s['impulse'] for s in stroke_features]
    axes[0, 1].scatter(times, impulses, c=colors, s=10, alpha=0.7)
    axes[0, 1].set_ylabel('Impulse')
    axes[0, 1].set_title('Stroke Impulse Over Time')

    # Peak position distribution
    positions = [s['peak_position'] for s in stroke_features]
    axes[1, 0].hist(positions, bins=20, color='steelblue', alpha=0.7)
    axes[1, 0].set_xlabel('Peak Position (0=start, 1=end)')
    axes[1, 0].set_ylabel('Count')
    axes[1, 0].set_title('Catch Timing Distribution')

    # Cadence over time (inter-stroke interval)
    if len(times) > 1:
        intervals = np.diff(times)
        cadence = 60.0 / intervals  # strokes per minute
        axes[1, 1].plot(times[1:], cadence, linewidth=0.8, color='steelblue')
        axes[1, 1].set_ylabel('Strokes/min')
        axes[1, 1].set_xlabel('Time (seconds)')
        axes[1, 1].set_title('Cadence Over Time')

    plt.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description='Analyze a KiloGlide session')
    parser.add_argument('--file', type=str, default='sessions/fake_session.csv',
                        help='Path to session CSV')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        print("Run 'python tools/fake_imu.py' first to generate synthetic data.")
        sys.exit(1)

    print(f"Loading session: {args.file}")
    timestamps, accel, gyro = load_session(args.file)
    print(f"  Duration: {timestamps[-1]:.1f} seconds")
    print(f"  Samples: {len(timestamps)}")

    # Detect strokes
    print("\nDetecting strokes...")
    detected_strokes = detect_strokes(timestamps, accel[:, 2], threshold=3.0)
    print(f"  Found {len(detected_strokes)} strokes")

    if len(detected_strokes) < 2:
        print("Not enough strokes detected. Try lowering the threshold.")
        sys.exit(1)

    # Compute cadence
    intervals = np.diff([s[0] for s in detected_strokes])
    avg_cadence = 60.0 / np.mean(intervals)
    print(f"  Average cadence: {avg_cadence:.1f} spm")

    # Extract features per stroke
    print("\nCharacterizing strokes...")
    stroke_features = extract_stroke_segments(
        timestamps, accel[:, 2], gyro[:, 0], detected_strokes
    )
    print(f"  Characterized {len(stroke_features)} strokes")

    # Asymmetry analysis
    print("\nAsymmetry analysis:")
    analyze_asymmetry(stroke_features)

    # Fatigue analysis
    print("\nFatigue analysis:")
    fatigue_coeffs = analyze_fatigue(stroke_features)

    # Check against ground truth if available
    gt_path = args.file.replace('.csv', '_strokes.csv')
    if os.path.exists(gt_path):
        ground_truth = load_ground_truth(gt_path)
        print(f"\nGround truth comparison:")
        print(f"  Ground truth strokes: {len(ground_truth)}")
        print(f"  Detected strokes: {len(detected_strokes)}")
        detection_rate = len(detected_strokes) / len(ground_truth) if ground_truth else 0
        print(f"  Detection rate: {detection_rate:.1%}")

    # Plot
    print("\nGenerating plots...")
    fig1 = plot_session_overview(timestamps, accel, gyro, detected_strokes)
    fig2 = plot_force_curves(stroke_features)

    plt.show()
    print("Done.")


if __name__ == '__main__':
    main()
