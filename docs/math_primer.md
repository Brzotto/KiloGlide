# KiloGlide — Math Primer

A practical guide to the mathematics you'll actually use, written for an EE who knows calculus and signals & systems but hasn't applied them to inertial sensing or sport biomechanics. The thesis: every technique here is shorter and less scary than it sounds, and you almost certainly already have the foundation.

This is reference material — skip to whichever section you need when you need it.

---

## What math you actually need (and what you don't)

### You need

- **Discrete-time calculus.** Integration becomes "sum and multiply by dt." Differentiation becomes "subtract consecutive samples and divide by dt." That's it.
- **Basic IIR filtering.** Mostly first-order low-pass, sometimes complementary filtering. Each one is 2–3 lines of code.
- **Peak detection.** Threshold + refractory period for v0. Smarter variants exist; you don't need them yet.
- **Descriptive statistics.** Mean, variance, percentiles, correlation. Standard library functions.
- **Linear regression.** One function call in numpy or scipy. Used for drag modeling.
- **Newton's second law.** `F = ma`. The whole foundation of the corrected-DPS idea.
- **3D vector basics.** Magnitude, dot product, axis projection. Algebra you already know.

### You don't need

- **Kalman filters.** Sometimes useful, often overkill. A complementary filter handles your orientation needs at 1% the complexity. Skip.
- **Quaternion mathematics in depth.** The Madgwick library uses them internally. You call `update()` and read `roll`, `pitch`, `yaw`. Treat it as a black box.
- **Fluid dynamics in any rigorous sense.** You'll fit an empirical drag curve to glide-phase data. That's not modeling fluid mechanics; it's regression.
- **Machine learning.** Wrong tool for this problem. Hand-engineered features informed by paddling biomechanics will outperform a neural net on a dataset of any size you can collect.
- **Advanced linear algebra.** No matrix decompositions, no eigenvalue work, nothing involving Lagrangians.

If you took DSP and signals & systems in school, you have ~95% of the prerequisites. The other 5% you'll pick up as you go.

---

## The techniques, one by one

Each section follows the same shape: what it does, why you need it, the math in code form, and what to watch out for.

### 1. Discrete integration and differentiation

**What it does:** turns acceleration into velocity, velocity into position, and back the other way.

**Why you need it:** acceleration is what the IMU measures; velocity and position are what you want for force curves and motion analysis. The boat's deceleration during glide phase, integrated over time, gives you energy lost to drag.

**The math:**

```python
# Integration: accumulate samples
velocity = 0
for accel_sample in accel_stream:
    velocity += accel_sample * dt   # dt = 1/sample_rate

# Differentiation: difference between samples
prev = accel_stream[0]
for sample in accel_stream[1:]:
    jerk = (sample - prev) / dt
    prev = sample
```

That's calculus on sampled data. Forward Euler integration. Engineers used it for decades before fancier methods existed; for our purposes it's plenty.

**Watch out for:**

- **Drift.** Integrating acceleration to get velocity accumulates sensor noise and bias. Over 30 seconds, integrated velocity will wander into nonsense. Mitigation: high-pass filter the acceleration before integrating, or reset velocity to zero at known stationary moments (between strokes is one).
- **Sample-rate consistency.** `dt` must actually equal the time between samples. If your IMU sometimes drops samples, you're integrating with wrong `dt` values. Use the IMU's onboard timestamps when available.

### 2. The complementary filter (orientation from IMU)

**What it does:** combines gyro (good short-term, drifts long-term) with accelerometer (noisy short-term, accurate long-term thanks to gravity) to give you a clean orientation estimate.

**Why you need it:** to know which way the boat is pitched and rolled. Roll dynamics drive stroke-side discrimination; pitch drives wave detection in surf mode.

**The math:**

```python
# alpha is the gyro weighting; typically 0.95–0.98
# higher alpha = more gyro, more responsive but more drift
# lower alpha = more accel, more stable but more noise

roll = 0.0
for sample in imu_stream:
    roll_from_gyro = roll + sample.gyro_x * dt
    roll_from_accel = atan2(sample.accel_y, sample.accel_z)
    roll = alpha * roll_from_gyro + (1 - alpha) * roll_from_accel
```

Three lines of actual logic. That's the whole filter. It works because the gyro and accelerometer have complementary failure modes — high-frequency drift in the accel, low-frequency drift in the gyro — and you trust each in the band where it's good.

For pitch, do the same thing with `gyro_y` and `atan2(accel_x, accel_z)`. Yaw needs a magnetometer (which you don't have); without one, yaw is uncalibrated. That's fine — boat heading comes from GPS.

**Madgwick's algorithm** is the same idea with quaternions instead of Euler angles. Better numerical behavior, no gimbal lock, but the conceptual content is identical: trust the gyro fast, correct with the accel slow. The Adafruit AHRS library does Madgwick in three lines of usage code.

**Watch out for:**

- **Gravity contamination during high acceleration.** The accel measures gravity *plus* dynamic acceleration. During a hard stroke, the dynamic component is comparable to gravity, and the accel-based tilt estimate becomes unreliable. Mitigation: lower alpha (lean more on gyro) during high-acceleration moments. There's a fancy version called "adaptive alpha" that does this automatically.
- **Initial convergence.** The filter needs a few seconds to settle. Either run it for a moment before logging, or seed `roll` with the accel-only estimate at startup.

### 3. Peak detection (stroke counting v0)

**What it does:** identifies discrete events in a continuous signal — in this case, strokes from accelerometer or gyro traces.

**Why you need it:** every stroke-rate, asymmetry, and force-curve metric depends on knowing when each stroke happened.

**The math:**

```python
THRESHOLD = 5.0     # tune empirically
REFRACTORY_MS = 250 # minimum time between strokes (= max ~240 spm)

last_stroke_time = 0
in_peak = False

for sample in imu_stream:
    signal = abs(sample.accel_z)  # or some combination of axes

    if signal > THRESHOLD and not in_peak:
        if (sample.timestamp - last_stroke_time) > REFRACTORY_MS:
            stroke_detected(sample.timestamp)
            last_stroke_time = sample.timestamp
            in_peak = True

    elif signal < THRESHOLD * 0.7:  # hysteresis: must drop below to re-arm
        in_peak = False
```

This is pre-school computer science with one wrinkle (hysteresis to avoid double-counting noisy peaks). The thresholds are empirical. Pick numbers that look right when you plot real data.

**Smarter versions exist** — bandpass-filter the signal first to isolate stroke-frequency content, use slope-based detection instead of magnitude, fit a template. None of them are necessary for v0. Get the simple version working, identify where it fails, *then* upgrade.

**Watch out for:**

- **The signal axis matters.** Z-axis acceleration is a reasonable starting point, but the boat's motion is complex; you may end up with a derived signal like `sqrt(accel_x² + accel_z²)` or filtered roll velocity from the gyro.
- **Threshold drift across paddlers.** A strong paddler's threshold is different from a casual one's. Eventually you want auto-tuning (e.g., threshold = N × running standard deviation), but for v0, hardcode and iterate.

### 4. Force/momentum curve characterization

**What it does:** extracts shape features from each stroke's acceleration trace — peak height, peak position, slope to peak, area under the curve.

**Why you need it:** these are the metrics that demonstrate the gyro+IMU advantage. NK can give you "you took 1,234 strokes;" you can give the *shape* of each one.

**The math:**

```python
# given a single stroke: array of accelerations, sampled at IMU rate
def characterize_stroke(accel_samples, dt):
    peak_idx = argmax(accel_samples)
    peak_value = accel_samples[peak_idx]

    # When in the stroke does the peak occur (0 = start, 1 = end)?
    peak_position = peak_idx / len(accel_samples)

    # How sharply did the catch ramp up?
    slope_to_peak = peak_value / (peak_idx * dt)  # accel per second

    # How much "work" — area under the acceleration curve
    impulse = sum(accel_samples) * dt   # discrete integral

    # Symmetry: what fraction is before vs after the peak
    pre_peak_area = sum(accel_samples[:peak_idx]) * dt
    post_peak_area = sum(accel_samples[peak_idx:]) * dt
    skew = (post_peak_area - pre_peak_area) / impulse

    return peak_value, peak_position, slope_to_peak, impulse, skew
```

Each of these is a feature. You compute them per stroke, log them, and now you have a per-stroke fingerprint. Compare fingerprints across strokes for asymmetry. Compare fingerprints across time for fatigue. Compare fingerprints across paddlers for technique differences.

The math is: find the maximum, divide some sums. That's it.

**Watch out for:**

- **Defining "the stroke."** You need start and end indices for the trace. Stroke detection (above) gives you the peaks; the boundary between strokes is the local minimum between them. Easy to find.
- **Gravity.** The acceleration you analyze should be *boat-frame* acceleration with gravity removed. Once your complementary filter gives you orientation, you rotate the gravity vector into the IMU frame and subtract.

### 5. Statistics for asymmetry and fatigue

**What it does:** compares groups of strokes to detect bias (asymmetry) or trends over time (fatigue).

**Why you need it:** asymmetry is the single highest-value insight per `data_insights.md`. Fatigue is the second highest.

**The math (asymmetry):**

```python
left_features = [stroke.peak_value for stroke in strokes if stroke.side == 'L']
right_features = [stroke.peak_value for stroke in strokes if stroke.side == 'R']

mean_diff = mean(right_features) - mean(left_features)
relative_asymmetry = mean_diff / mean(left_features + right_features)

# is the difference statistically real or just noise?
from scipy.stats import ttest_ind
t_stat, p_value = ttest_ind(left_features, right_features)
```

For asymmetry detection on a session, you have hundreds of strokes per side, so even a 5% mean difference will be statistically significant. The statistical test isn't to gatekeep — it's to avoid flagging a 2% asymmetry on 5 strokes as meaningful.

**The math (fatigue):**

```python
# fit a line through some metric vs. stroke number
from numpy.polynomial import polynomial as P

stroke_indices = arange(len(strokes))
peak_values = [s.peak_value for s in strokes]

slope, intercept = polyfit(stroke_indices, peak_values, 1)
# negative slope = peak force declining = fatigue signature
```

Linear regression on a metric over the course of a session. The slope is your fatigue index. Done.

**Watch out for:**

- **Side classification.** You need to know which strokes are left and which are right. The gyro tells you: roll velocity sign at the catch is the cleanest signal. This is a derived feature, not a sensor input.
- **Fatigue vs. pacing.** A planned warm-up-then-build session will show "fatigue signature" that isn't fatigue. Either segment by intent or look for *unexpected* drift in steady-state pieces.

### 6. The corrected-DPS / TSP idea

This is the most novel piece in the project, so it gets more space. The math is still moderate.

**What it does:** isolates paddle-driven boat acceleration from environmental contributions (drag, wind, wave-pumping), so DPS reflects the *paddler's* effort rather than tailwind luck.

**The physical model:**

During the **glide phase** (between strokes), the boat is decelerating purely from environmental forces. Mostly hydrodynamic drag, plus any wind effect. By Newton's second law:

```
m * a_glide(v) = -F_drag(v) + F_wind
```

Drag is empirically dominated by `v²` for a hull at typical paddling speeds:

```
F_drag(v) ≈ k₁*v + k₂*v²
```

So during glide:

```
a_glide(v) ≈ -(k₁*v + k₂*v²) / m + a_wind_constant
```

You **observe** `a_glide` at many different speeds across a session (boat speeds up and slows down naturally). Fit `k₁`, `k₂`, and the constant via linear regression on `[v, v², 1]` columns:

```python
from numpy.linalg import lstsq

# rows of glide-phase observations
A = [[v, v**2, 1] for v in glide_velocities]
b = glide_decelerations
coefficients, *_ = lstsq(A, b, rcond=None)
k1, k2, c = coefficients
```

Now you have a model of "what acceleration would the boat experience right now from environment alone, given its current speed."

During the **stroke phase**, total acceleration has two components:

```
a_total = a_paddle + a_environment
```

Subtract the modeled environment contribution to recover paddle-only acceleration:

```python
def paddle_acceleration(v, a_observed):
    a_env = -(k1*v + k2*v**2) / m + c
    return a_observed - a_env
```

Multiply by mass for force, integrate over the stroke for impulse, divide impulse by stroke count for "corrected" effort per stroke. That's the metric.

**The math involved:**

- `F = ma`. Newton's second law.
- A drag model that's two terms of a polynomial.
- One linear regression call.
- Subtraction.

**This is the entire conceptual machinery.** It's not novel mathematics; it's a thoughtful application of well-known physics to a new context.

**Watch out for:**

- **The model needs glide data.** Sessions consisting entirely of hard intervals with no glide phase won't fit the regression well. Recover from this by using a previously-fit model from a calibration session, or fall back to uncorrected DPS with a warning.
- **Wind changes within a session.** A 20-minute downwind run can have wind shifting noticeably. The "constant" term in the model is really a slow-varying function. Fit it on rolling windows (e.g., last 2 minutes of glide observations).
- **Boat mass and displacement matter.** A heavier paddler in a different boat has different `m`. Per-paddler calibration is needed for absolute numbers; for per-paddler trend tracking it doesn't matter because you compare against your own baseline.
- **Validation is the hard part.** You can't directly measure paddle force without instrumented oars. The way you validate is *consistency*: same paddler doing the same effort in different conditions should produce similar corrected DPS. That's the test that matters, and it's empirical.

### 7. Coordinate frames and 3D vectors

**What it does:** lets you work in a meaningful coordinate system (boat frame: forward/sideways/up) regardless of how the IMU is mounted.

**Why you need it:** the IMU axes are arbitrary; the boat's axes are physical. You'll want to express signals in the boat frame.

**The math:**

The IMU has a body frame: x, y, z relative to the chip. When you mount it in the boat, there's a fixed rotation between IMU frame and boat frame (because you don't mount it perfectly aligned). Calibrate this rotation once: with the boat sitting flat, average accel readings give you the gravity vector in IMU frame. Build a rotation matrix that aligns IMU-up with boat-up.

```python
# during calibration, boat sitting still
gravity_imu = mean(accel_samples)  # vector in IMU frame
gravity_boat = [0, 0, -9.81]       # by convention, z up, gravity down

# build rotation R that maps gravity_imu → gravity_boat
# (any 3D rotation library can do this from two vectors)
R = rotation_aligning(gravity_imu, gravity_boat)

# from now on, every IMU reading gets rotated:
def to_boat_frame(imu_vector):
    return R @ imu_vector
```

For yaw alignment (forward direction in the boat), you'd do an additional calibration with a known forward motion (e.g., paddle straight for 10 seconds, average GPS heading vs. gyro yaw integration). Most implementations skip this and assume you mount the device with one axis pointing forward; document the mounting orientation and call it good.

**Watch out for:**

- **Right-hand rule and sign conventions.** Decide once which direction is positive for each axis and stick with it. Document it in `decisions.md`.
- **Gimbal lock and Euler angles.** If you ever find yourself doing math with Euler angles directly, switch to quaternions. The libraries handle this.

---

## The actually-hard parts (which aren't math)

The math above is moderate. The skills below are what make or break the project, and they don't come from books.

### Signal noise: the developed intuition

Real IMU data is messy. Vibration, EMI from the GPS, small mounting flex, water hitting the hull — all show up as noise. You'll spend time:

- Recognizing which "feature" in a signal is real and which is artifact
- Choosing filters that suppress noise without destroying the signal you care about
- Understanding the trade-off between filter delay and smoothness (more smoothing = more lag = stale data on a real-time display)

The way to develop this intuition is: capture data, plot it in Jupyter, stare at it. Annotate stroke events by hand on a few minutes of recording. Compare against your detection algorithm. Iterate. There's no shortcut.

### Threshold tuning

No formula gives you the right peak detection threshold. It depends on paddler strength, mounting, the specific stroke style of the population. You tune it on real data. You'll find that what works for Ray fails for a different paddler because their stroke style is rounder, or sharper, or asymmetric.

This is *parameter engineering*, and it's where most of the empirical effort in the project will go. Don't underestimate it.

### Validation: knowing when you're fooling yourself

Every metric needs to pass the test: "does this number agree with what an expert sees?" The classic failure mode in sport-tech is metrics that look numerically beautiful but don't track lived experience. Avoid this by validating constantly:

- Collect data while a coach watches. Mark interesting moments live. Compare your metrics' flags against the coach's notes.
- Use yourself as a paddler: do something deliberately bad (heavy on one side, soft catch) and confirm your metrics show what you did.
- Compare across paddlers. A clean technical paddler should look different from a strong-but-rough one in interpretable ways.

Math without validation produces confident-sounding nonsense. This is the highest-value skill in the whole project, and it's not something you read about — it's something you do. Worth noting: this is exactly the practice of *kilo* — patient, careful observation that earns the right to claim what it sees. The product's name is also its method.

---

## Resources

One book, a few papers, and some online references. Don't try to read all of these; pick what you need when you need it.

### Primary

- **Steven W. Smith, *The Scientist and Engineer's Guide to Digital Signal Processing*.** Free at [dspguide.com](http://dspguide.com). Chapters 1–3, 14–15, 19. The most engineer-friendly DSP book ever written. If you read one thing, this is it.

### For sensor fusion specifically

- **Sebastian Madgwick's original paper** ("An efficient orientation filter for inertial and inertial/magnetic sensor arrays", 2010). 30 pages, freely available. Skim it for context on what your library is doing. Don't try to reimplement.
- **Pieter-Jan's blog series on IMU sensor fusion** at [pieter-jan.com](http://pieter-jan.com/node/11). Practical, code-first, exactly the right level for this project.

### For sport biomechanics context

- **Rowing biomechanics literature.** The closest analog to outrigger paddling, with decades of research on stroke shape, force curves, and asymmetry. Search Google Scholar for "rowing biomechanics force curve" — Kleshnev's work is canonical. Almost everything translates with minor reinterpretation.
- **Kleshnev's RowBiomechanics newsletter** is freely archived online and is the most accessible biomechanics writing for a non-academic audience.

### For when you're ready to go deeper

- **Madgwick's PhD thesis** (2014). The full derivation. Read only if you find yourself wanting to modify the algorithm.
- **Farrell, *Aided Navigation: GPS with High Rate Sensors* (2008).** The canonical reference for fusing IMU and GPS. Overkill for v0; relevant if you ever want a Kalman-filtered position estimate.

---

## A reality check

If you can confidently write the following in a Python notebook, you have everything you need to ship v0:

1. A function that reads a binary log and returns arrays of timestamped IMU samples.
2. A complementary filter that gives roll and pitch over time.
3. A peak detector that finds strokes and gives a stroke count.
4. A function that, given one stroke's acceleration trace, returns peak value, peak position, and impulse.
5. A scatter plot of glide-phase deceleration vs. boat speed, with a quadratic fit.

That's the whole math layer. Five functions, none longer than 30 lines. None of them require knowledge beyond what you already have or can pick up from Smith's first three chapters.

The project's risk is not the math. It's the empirical grind of validating that what you compute agrees with what paddlers feel — and that's a problem you solve by getting on the water with the device, not by reading another book.
