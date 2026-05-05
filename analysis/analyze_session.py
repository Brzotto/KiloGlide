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
    python analysis/analyze_session.py --mass-kg 112 --save-plots --no-show
"""

import argparse
import numpy as np
import matplotlib.pyplot as plt
import os
import sys

SAMPLE_RATE = 416  # Hz

# Effective force = system mass * boat acceleration.
# This is not direct paddle-blade force. It is the boat-response/effective-drive
# force the paddler is delivering to the hull after connection losses.
DEFAULT_SYSTEM_MASS_KG = 110.0  # paddler + boat + gear; tune per user/session
FORCE_CURVE_POINTS = 101        # 0..100% stroke phase


def load_session(filepath):
    """
    Load a session CSV and return timestamps, accel, gyro, optional speed.

    Expected columns:
        timestamp,accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z

    Optional future column:
        speed_mps

    Returns:
        timestamps: (N,) seconds
        accel: (N, 3) x, y, z acceleration
        gyro: (N, 3) x, y, z gyro
        speed_mps: (N,) speed in m/s, or None if unavailable
    """
    with open(filepath, 'r') as f:
        header = f.readline().strip().split(',')

    data = np.genfromtxt(filepath, delimiter=',', skip_header=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)

    timestamps = data[:, 0]
    accel = data[:, 1:4]  # x, y, z
    gyro = data[:, 4:7]   # x, y, z

    speed_mps = None
    if 'speed_mps' in header:
        speed_idx = header.index('speed_mps')
        if speed_idx < data.shape[1]:
            speed_mps = data[:, speed_idx]

    return timestamps, accel, gyro, speed_mps


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
        impulse: area under the acceleration curve
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


def extract_stroke_segments(timestamps, accel_z, gyro_x, detected_strokes, speed_mps=None):
    """
    Given detected stroke timestamps, extract the acceleration segment
    for each stroke from midpoint between strokes to midpoint.

    Returns list of dicts with features, side classification, and raw curve data.
    """
    if len(timestamps) > 1:
        dt = float(np.median(np.diff(timestamps)))
    else:
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

        # For summary features, keep the historical behavior: use magnitude.
        # That makes the feature extraction robust to a reversed sensor axis.
        drive_magnitude = np.abs(segment)
        features = characterize_stroke(drive_magnitude, dt)
        if features is None:
            continue

        features['time'] = stroke_time
        features['side'] = classify_stroke_side(gyro_segment)
        features['stroke_num'] = i
        features['start_idx'] = start
        features['end_idx'] = end
        features['dt'] = dt

        # Raw data needed for force-curve overlays.
        features['accel_segment'] = segment.copy()
        features['drive_accel_segment'] = drive_magnitude.copy()
        features['gyro_x_segment'] = gyro_segment.copy()
        features['time_segment'] = (timestamps[start:end] - timestamps[start]).copy()

        if speed_mps is not None:
            features['speed_segment'] = speed_mps[start:end].copy()

        stroke_features.append(features)

    return stroke_features


# =========================================================
# FORCE / DISTANCE HELPERS
# =========================================================

def resample_curve(y, n_points=FORCE_CURVE_POINTS):
    """
    Resample a 1D curve to a fixed number of points for stroke-phase overlays.
    """
    if y is None or len(y) < 2:
        return None

    old_x = np.linspace(0.0, 1.0, len(y))
    new_x = np.linspace(0.0, 1.0, n_points)
    return np.interp(new_x, old_x, y)


def smooth_moving_average(y, window_samples=7):
    """
    Light smoothing for display. Uses an odd-length moving average.
    """
    if window_samples is None or window_samples <= 1 or len(y) < window_samples:
        return y

    if window_samples % 2 == 0:
        window_samples += 1

    kernel = np.ones(window_samples) / window_samples
    return np.convolve(y, kernel, mode='same')


def acceleration_to_effective_force(accel_segment, system_mass_kg=DEFAULT_SYSTEM_MASS_KG,
                                    mode='positive', smooth_window=7):
    """
    Convert boat acceleration to effective drive force.

    This is boat-response force, not direct paddle-blade force.

    mode:
        positive  = use positive forward acceleration only; best when accel_z is calibrated forward
        magnitude = use abs(accel); useful for unknown/reversed sensor orientation
        signed    = preserve acceleration sign; useful for debugging/checking at exit
    """
    if mode == 'positive':
        drive_accel = np.maximum(accel_segment, 0.0)
    elif mode == 'magnitude':
        drive_accel = np.abs(accel_segment)
    elif mode == 'signed':
        drive_accel = accel_segment
    else:
        raise ValueError("mode must be 'positive', 'magnitude', or 'signed'")

    drive_accel = smooth_moving_average(drive_accel, smooth_window)
    return system_mass_kg * drive_accel


def estimate_relative_distance_from_accel(accel_segment, dt):
    """
    Estimate relative boat distance during one stroke by integrating acceleration.

    This is a short-window proxy. It is useful for fake data and visualization,
    but real boat-distance-per-stroke should come from GPS speed or fused velocity.
    """
    if len(accel_segment) < 2:
        return None

    # Remove local bias to reduce integration drift.
    accel = accel_segment - np.mean(accel_segment)

    # Integrate acceleration -> relative velocity.
    velocity = np.cumsum(accel) * dt

    # Shift velocity so cumulative distance is display-friendly.
    velocity = velocity - np.min(velocity)

    # Integrate velocity -> relative distance.
    distance = np.cumsum(velocity) * dt
    distance = distance - distance[0]

    return distance


def distance_during_stroke(stroke):
    """
    Return distance during the stroke and a label describing the source.

    If speed_mps is present, use it. Otherwise fall back to accel integration.
    """
    dt = stroke['dt']

    if 'speed_segment' in stroke and stroke['speed_segment'] is not None:
        speed = np.maximum(stroke['speed_segment'], 0.0)
        distance = np.cumsum(speed) * dt
        distance = distance - distance[0]
        return distance, 'GPS/fused speed'

    distance = estimate_relative_distance_from_accel(stroke['accel_segment'], dt)
    return distance, 'accel-integrated proxy'


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
    print(f"  Peak boat-response asymmetry: {peak_asymmetry:+.1%}")
    print(f"  Left avg accel impulse:  {left_impulse:.3f} m/s")
    print(f"  Right avg accel impulse: {right_impulse:.3f} m/s")


def analyze_fatigue(stroke_features):
    """Fit a trend line through peak boat response over time."""
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

    print(f"  Peak boat-response trend: {pct_change:+.1%} over session")
    print(f"  Slope: {slope:.4f} m/s^2 per stroke")
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
    axes[0].set_ylabel('Accel Z (m/s^2)')
    axes[0].set_title('Forward Acceleration + Detected Strokes')

    # Roll rate (key signal for side detection)
    axes[1].plot(timestamps, gyro[:, 0], linewidth=0.5, color='coral')
    axes[1].set_ylabel('Gyro X (deg/s)')
    axes[1].set_title('Roll Rate (positive = right stroke)')
    axes[1].axhline(0, color='gray', linewidth=0.5, linestyle='--')

    # Lateral acceleration
    axes[2].plot(timestamps, accel[:, 0], linewidth=0.5, color='seagreen')
    axes[2].set_ylabel('Accel X (m/s^2)')
    axes[2].set_xlabel('Time (seconds)')
    axes[2].set_title('Lateral Acceleration')

    plt.tight_layout()
    return fig


def plot_force_curves(stroke_features, system_mass_kg=DEFAULT_SYSTEM_MASS_KG):
    """
    Plot summary metrics over the session.

    This remains a summary view. The actual per-stroke curve overlays are in
    plot_force_curve_overlay() and plot_force_vs_stroke_distance().
    """
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    times = [s['time'] for s in stroke_features]
    colors = ['steelblue' if s['side'] == 'R' else 'coral' for s in stroke_features]

    # Peak effective force over time
    peaks = [s['peak_value'] * system_mass_kg for s in stroke_features]
    axes[0, 0].scatter(times, peaks, c=colors, s=10, alpha=0.7)
    axes[0, 0].set_ylabel('Peak Effective Drive Force (N)')
    axes[0, 0].set_title('Peak Effective Drive Force Over Time (blue=R, red=L)')

    # Effective impulse over time
    impulses = [s['impulse'] * system_mass_kg for s in stroke_features]
    axes[0, 1].scatter(times, impulses, c=colors, s=10, alpha=0.7)
    axes[0, 1].set_ylabel('Effective Impulse (N*s)')
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




def select_strokes_for_overlay(stroke_features, n_strokes=20, skip_edge_strokes=1):
    """
    Pick strokes for overlay plots while avoiding edge-window artifacts.

    The first and last detected strokes use the start/end of the file as one
    boundary, instead of a clean midpoint-to-midpoint stroke window. Those edge
    strokes often appear shifted left/right in force-curve overlays, so we skip
    one stroke at each end by default.
    """
    if not stroke_features:
        return []

    skip_edge_strokes = max(0, int(skip_edge_strokes))

    if len(stroke_features) > 2 * skip_edge_strokes:
        usable = stroke_features[skip_edge_strokes:-skip_edge_strokes]
    else:
        # Small files may not have enough strokes to skip both edges. In that
        # case, show what we have rather than returning an empty plot.
        usable = stroke_features

    return usable[:n_strokes]

def plot_force_curve_overlay(stroke_features, n_strokes=20,
                             system_mass_kg=DEFAULT_SYSTEM_MASS_KG,
                             force_mode='positive',
                             smooth_window=7,
                             skip_edge_strokes=1):
    """
    Plot overlaid effective-drive-force curves against normalized stroke phase.

    X axis: 0-100% stroke phase
    Y axis: effective drive force in Newtons
    """
    fig, ax = plt.subplots(figsize=(12, 6))

    selected = select_strokes_for_overlay(stroke_features, n_strokes, skip_edge_strokes)
    resampled_forces = []
    phase = np.linspace(0.0, 100.0, FORCE_CURVE_POINTS)

    for s in selected:
        force = acceleration_to_effective_force(
            s['accel_segment'],
            system_mass_kg=system_mass_kg,
            mode=force_mode,
            smooth_window=smooth_window
        )

        force_resampled = resample_curve(force, FORCE_CURVE_POINTS)
        if force_resampled is None:
            continue

        resampled_forces.append(force_resampled)

        color = 'steelblue' if s['side'] == 'R' else 'coral'
        ax.plot(
            phase,
            force_resampled,
            color=color,
            alpha=0.25,
            linewidth=1.0
        )

    if resampled_forces:
        mean_force = np.mean(resampled_forces, axis=0)
        ax.plot(
            phase,
            mean_force,
            color='black',
            linewidth=2.5,
            label='Average stroke'
        )
        ax.legend()

    ax.set_title('Effective Drive Force vs Stroke Phase')
    ax.set_xlabel('Stroke Phase (%)')
    ax.set_ylabel('Effective Drive Force (N)')
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    return fig


def plot_force_vs_stroke_distance(stroke_features, n_strokes=20,
                                  system_mass_kg=DEFAULT_SYSTEM_MASS_KG,
                                  force_mode='positive',
                                  smooth_window=7,
                                  skip_edge_strokes=1):
    """
    Plot effective drive force against boat distance during each stroke.

    If speed_mps exists in the CSV, distance is based on speed.
    Otherwise, distance is an accel-integrated short-window proxy.
    """
    fig, ax = plt.subplots(figsize=(12, 6))

    selected = select_strokes_for_overlay(stroke_features, n_strokes, skip_edge_strokes)
    distance_sources = set()

    for s in selected:
        force = acceleration_to_effective_force(
            s['accel_segment'],
            system_mass_kg=system_mass_kg,
            mode=force_mode,
            smooth_window=smooth_window
        )

        distance, source = distance_during_stroke(s)
        distance_sources.add(source)

        if distance is None:
            continue

        color = 'steelblue' if s['side'] == 'R' else 'coral'

        ax.plot(
            distance,
            force,
            color=color,
            alpha=0.35,
            linewidth=1.0
        )

    source_label = ', '.join(sorted(distance_sources)) if distance_sources else 'unknown'
    ax.set_title(f'Effective Drive Force vs Stroke Distance ({source_label})')
    ax.set_xlabel('Boat Distance During Stroke (m)')
    ax.set_ylabel('Effective Drive Force (N)')
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    return fig


def save_figures(figures, output_dir):
    """Save figures to PNG files."""
    os.makedirs(output_dir, exist_ok=True)

    saved_paths = []
    for name, fig in figures:
        path = os.path.join(output_dir, f'{name}.png')
        fig.savefig(path, dpi=160, bbox_inches='tight')
        saved_paths.append(path)

    return saved_paths


def main():
    parser = argparse.ArgumentParser(description='Analyze a KiloGlide session')
    parser.add_argument('--file', type=str, default='sessions/fake_session.csv',
                        help='Path to session CSV')
    parser.add_argument('--mass-kg', type=float, default=DEFAULT_SYSTEM_MASS_KG,
                        help='System mass: paddler + boat + gear in kg')
    parser.add_argument('--force-mode', type=str, default='positive',
                        choices=['positive', 'magnitude', 'signed'],
                        help='How to convert forward acceleration to drive force')
    parser.add_argument('--overlay-strokes', type=int, default=20,
                        help='Number of strokes to overlay in curve plots')
    parser.add_argument('--skip-edge-strokes', type=int, default=1,
                        help='Skip this many strokes at the beginning and end of overlay plots')
    parser.add_argument('--smooth-window', type=int, default=7,
                        help='Moving-average smoothing window in samples')
    parser.add_argument('--save-plots', action='store_true',
                        help='Save plots as PNG files')
    parser.add_argument('--plot-dir', type=str, default='analysis/plots',
                        help='Directory for saved plots')
    parser.add_argument('--no-show', action='store_true',
                        help='Do not open interactive plot windows')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        print("Run 'python tools/fake_imu.py' first to generate synthetic data.")
        sys.exit(1)

    print(f"Loading session: {args.file}")
    timestamps, accel, gyro, speed_mps = load_session(args.file)
    print(f"  Duration: {timestamps[-1]:.1f} seconds")
    print(f"  Samples: {len(timestamps)}")
    print(f"  System mass: {args.mass_kg:.1f} kg")
    if speed_mps is not None:
        print("  Speed source: speed_mps column")
    else:
        print("  Speed source: unavailable; distance plot will use accel-integrated proxy")

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
        timestamps, accel[:, 2], gyro[:, 0], detected_strokes, speed_mps=speed_mps
    )
    print(f"  Characterized {len(stroke_features)} strokes")
    if args.skip_edge_strokes > 0:
        print(f"  Overlay plots will skip {args.skip_edge_strokes} edge stroke(s) at each end")

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
    figures = [
        ('session_overview', plot_session_overview(timestamps, accel, gyro, detected_strokes)),
        ('session_summary', plot_force_curves(stroke_features, system_mass_kg=args.mass_kg)),
        ('force_vs_stroke_phase', plot_force_curve_overlay(
            stroke_features,
            n_strokes=args.overlay_strokes,
            system_mass_kg=args.mass_kg,
            force_mode=args.force_mode,
            smooth_window=args.smooth_window,
            skip_edge_strokes=args.skip_edge_strokes
        )),
        ('force_vs_stroke_distance', plot_force_vs_stroke_distance(
            stroke_features,
            n_strokes=args.overlay_strokes,
            system_mass_kg=args.mass_kg,
            force_mode=args.force_mode,
            smooth_window=args.smooth_window,
            skip_edge_strokes=args.skip_edge_strokes
        )),
    ]

    if args.save_plots:
        saved_paths = save_figures(figures, args.plot_dir)
        print("\nSaved plots:")
        for path in saved_paths:
            print(f"  {path}")

    if not args.no_show:
        plt.show()
    else:
        plt.close('all')

    print("Done.")


if __name__ == '__main__':
    main()
