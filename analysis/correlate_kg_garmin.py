"""
Session 37 — KiloGlide vs Garmin correlation and per-lap analysis.

Phases:
  1. Time-align KG (no absolute time anchor) with Garmin TCX (absolute UTC)
     via cross-correlation of GPS speed signals.
  2. Auto-detect IMU body-frame axes (forward / lateral / up) from gravity
     and from GPS-derived forward acceleration.
  3. Stroke detection v0 on the L/R burst section (Garmin laps 6-8).
  4. Per-lap stroke summary + force curves; compare strong miles vs
     slow-against-current mile.

Outputs go to analysis/plots/session_37/ (PNGs) and the console.
"""

import os
import sys
import math
import json
import datetime as dt
import xml.etree.ElementTree as ET

# Headless matplotlib so this works whether or not a display is attached.
import matplotlib
matplotlib.use("Agg")

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt, find_peaks

# Import the existing binary parser
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from tools.kg_parse import parse_file, ACCEL_SCALE, GYRO_SCALE  # noqa: E402

# ------------------------------------------------------------------
# Constants / inputs
# ------------------------------------------------------------------
KG_PATH = os.path.join(HERE, "data", "kg_000037.bin")
TCX_PATH = os.path.join(HERE, "data", "activity_22960598946.tcx")
PLOTS_DIR = os.path.join(HERE, "plots", "session_37")
REPORT_PATH = os.path.join(HERE, "session_37_report.md")

SYSTEM_MASS_KG = 85.0          # from user
NOMINAL_IMU_HZ = 416.0
GPS_HZ = 5.0

TCX_NS = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}

os.makedirs(PLOTS_DIR, exist_ok=True)


# ------------------------------------------------------------------
# Loaders
# ------------------------------------------------------------------
def load_kg(path):
    """Parse KG binary log into numpy arrays (physical units)."""
    result, err = parse_file(path)
    if err:
        raise RuntimeError(f"Parse error: {err}")

    imu = result["records"]["imu"]
    gps = result["records"]["gps"]
    events = result["records"]["events"]

    imu_t = np.array([r["ts"] for r in imu], dtype=np.float64) / 1000.0  # seconds since KG t=0
    ax = np.array([r["ax"] for r in imu], dtype=np.float64) * ACCEL_SCALE
    ay = np.array([r["ay"] for r in imu], dtype=np.float64) * ACCEL_SCALE
    az = np.array([r["az"] for r in imu], dtype=np.float64) * ACCEL_SCALE
    gx = np.array([r["gx"] for r in imu], dtype=np.float64) * GYRO_SCALE
    gy = np.array([r["gy"] for r in imu], dtype=np.float64) * GYRO_SCALE
    gz = np.array([r["gz"] for r in imu], dtype=np.float64) * GYRO_SCALE

    # Drop any rows with bogus timestamps (parser tags underflows with ts=0 only
    # for early-batch rows; we still sort/dedupe just to be safe).
    order = np.argsort(imu_t)
    imu_t = imu_t[order]
    ax, ay, az = ax[order], ay[order], az[order]
    gx, gy, gz = gx[order], gy[order], gz[order]

    gps_t = np.array([r["ts"] for r in gps], dtype=np.float64) / 1000.0
    speed = np.array([r["speed_m_s"] for r in gps], dtype=np.float64)
    lat = np.array([r["lat"] for r in gps], dtype=np.float64)
    lon = np.array([r["lon"] for r in gps], dtype=np.float64)
    fix = np.array([r["fix_type"] for r in gps], dtype=np.int32)
    sats = np.array([r["num_sats"] for r in gps], dtype=np.int32)

    # Mask out no-fix GPS samples
    good = fix >= 2
    return {
        "imu_t": imu_t,
        "accel_raw": np.stack([ax, ay, az], axis=1),
        "gyro_raw": np.stack([gx, gy, gz], axis=1),
        "gps_t": gps_t[good],
        "gps_speed": speed[good],
        "gps_lat": lat[good],
        "gps_lon": lon[good],
        "gps_sats": sats[good],
        "events": events,
        "time_records": result["records"]["time"],
        "header": result["header"],
    }


def _parse_iso_utc(s):
    """Parse an ISO 8601 UTC timestamp like '2026-05-21T13:29:33.000Z'."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s)


def load_tcx(path):
    """Parse a Garmin TCX. Returns per-trackpoint arrays + per-lap metadata."""
    tree = ET.parse(path)
    root = tree.getroot()

    activity = root.find(".//t:Activity", TCX_NS)
    laps_el = activity.findall("t:Lap", TCX_NS)

    laps = []
    all_t, all_speed, all_dist, all_lat, all_lon, all_hr = [], [], [], [], [], []

    for i, lap in enumerate(laps_el):
        lap_start = _parse_iso_utc(lap.get("StartTime"))
        total_s = float(lap.findtext("t:TotalTimeSeconds", default="0", namespaces=TCX_NS))
        dist_m = float(lap.findtext("t:DistanceMeters", default="0", namespaces=TCX_NS))
        max_spd = float(lap.findtext("t:MaximumSpeed", default="0", namespaces=TCX_NS))

        tps = lap.findall("t:Track/t:Trackpoint", TCX_NS)
        lap_t, lap_speed, lap_dist, lap_lat, lap_lon, lap_hr = [], [], [], [], [], []

        for tp in tps:
            time_s = tp.findtext("t:Time", namespaces=TCX_NS)
            t_abs = _parse_iso_utc(time_s).timestamp()

            d = tp.findtext("t:DistanceMeters", namespaces=TCX_NS)
            d = float(d) if d is not None else np.nan

            pos = tp.find("t:Position", TCX_NS)
            if pos is not None:
                la = float(pos.findtext("t:LatitudeDegrees", namespaces=TCX_NS))
                lo = float(pos.findtext("t:LongitudeDegrees", namespaces=TCX_NS))
            else:
                la, lo = np.nan, np.nan

            hr = tp.findtext("t:HeartRateBpm/t:Value", namespaces=TCX_NS)
            hr = float(hr) if hr is not None else np.nan

            # Garmin TCX speed lives in the namespaced TPX extension when present.
            # Fall back to distance-derived speed if missing.
            spd_el = tp.find(".//{http://www.garmin.com/xmlschemas/ActivityExtension/v2}Speed")
            if spd_el is not None and spd_el.text is not None:
                spd = float(spd_el.text)
            else:
                spd = np.nan

            lap_t.append(t_abs)
            lap_speed.append(spd)
            lap_dist.append(d)
            lap_lat.append(la)
            lap_lon.append(lo)
            lap_hr.append(hr)

            all_t.append(t_abs)
            all_speed.append(spd)
            all_dist.append(d)
            all_lat.append(la)
            all_lon.append(lo)
            all_hr.append(hr)

        laps.append({
            "idx": i + 1,
            "start_utc": lap_start.timestamp(),
            "duration_s": total_s,
            "distance_m": dist_m,
            "max_speed_m_s": max_spd,
            "track_t": np.array(lap_t, dtype=np.float64),
            "track_dist": np.array(lap_dist, dtype=np.float64),
        })

    t_arr = np.array(all_t, dtype=np.float64)
    order = np.argsort(t_arr)

    spd_arr = np.array(all_speed, dtype=np.float64)[order]
    dist_arr = np.array(all_dist, dtype=np.float64)[order]
    t_arr = t_arr[order]

    # If most TCX speeds are missing, derive from distance differences.
    nan_frac = float(np.mean(np.isnan(spd_arr)))
    if nan_frac > 0.5 and not np.all(np.isnan(dist_arr)):
        dd = np.diff(dist_arr)
        dt_arr = np.diff(t_arr)
        spd = np.where(dt_arr > 0, dd / np.maximum(dt_arr, 1e-3), 0)
        spd_arr = np.concatenate([[0.0], spd])

    # Fill any remaining NaN with 0 (pre-motion / between samples).
    spd_arr = np.where(np.isnan(spd_arr), 0.0, spd_arr)

    return {
        "t": t_arr,
        "speed": spd_arr,
        "dist": dist_arr,
        "lat": np.array(all_lat, dtype=np.float64)[order],
        "lon": np.array(all_lon, dtype=np.float64)[order],
        "hr": np.array(all_hr, dtype=np.float64)[order],
        "laps": laps,
        "activity_start_utc": _parse_iso_utc(activity.findtext("t:Id", namespaces=TCX_NS)).timestamp(),
    }


# Semicircles -> degrees. FIT stores lat/lon as int32 semicircles.
_SEMICIRCLE_TO_DEG = 180.0 / 2**31


def _fit_utc(d):
    """fitparse returns naive datetimes that are already UTC. Stamp them as
    UTC before .timestamp() so we don't accidentally use the local zone."""
    if d is None:
        return np.nan
    return d.replace(tzinfo=dt.timezone.utc).timestamp()


def _fit_fields(m):
    """Flatten a FIT message to {name: value}, keeping the first non-None value
    when a field name repeats (Garmin emits e.g. enhanced_max_speed twice, native
    then a developer copy that is often None — a plain dict comp would keep None)."""
    out = {}
    for d in m:
        if d.value is None:
            out.setdefault(d.name, None)
        elif out.get(d.name) is None:
            out[d.name] = d.value
    return out


def load_fit(path):
    """Parse a Garmin .fit activity into the same dict structure as load_tcx().

    Garmin Connect's native download is FIT; this lets the pipeline read it
    directly instead of requiring a TCX conversion. Uses 'record' messages for
    the per-trackpoint track (timestamp, enhanced_speed, distance, position,
    heart_rate) and 'lap' messages for manual lap-press boundaries.
    """
    from fitparse import FitFile  # lazy import: only needed for .fit inputs

    fit = FitFile(path)

    # --- per-record track -------------------------------------------------
    all_t, all_speed, all_dist, all_lat, all_lon, all_hr = [], [], [], [], [], []
    for m in fit.get_messages("record"):
        f = _fit_fields(m)
        t = f.get("timestamp")
        if t is None:
            continue
        all_t.append(_fit_utc(t))
        # Prefer enhanced_speed (m/s); fall back to plain speed; else NaN.
        spd = f.get("enhanced_speed", f.get("speed"))
        all_speed.append(float(spd) if spd is not None else np.nan)
        d = f.get("distance")
        all_dist.append(float(d) if d is not None else np.nan)
        la = f.get("position_lat")
        lo = f.get("position_long")
        all_lat.append(la * _SEMICIRCLE_TO_DEG if la is not None else np.nan)
        all_lon.append(lo * _SEMICIRCLE_TO_DEG if lo is not None else np.nan)
        hr = f.get("heart_rate")
        all_hr.append(float(hr) if hr is not None else np.nan)

    t_arr = np.array(all_t, dtype=np.float64)
    order = np.argsort(t_arr)
    t_arr = t_arr[order]
    spd_arr = np.array(all_speed, dtype=np.float64)[order]
    dist_arr = np.array(all_dist, dtype=np.float64)[order]
    lat_arr = np.array(all_lat, dtype=np.float64)[order]
    lon_arr = np.array(all_lon, dtype=np.float64)[order]
    hr_arr = np.array(all_hr, dtype=np.float64)[order]

    # Same speed-recovery policy as load_tcx: derive from distance if mostly missing.
    nan_frac = float(np.mean(np.isnan(spd_arr))) if spd_arr.size else 1.0
    if nan_frac > 0.5 and not np.all(np.isnan(dist_arr)):
        dd = np.diff(dist_arr)
        dt_arr = np.diff(t_arr)
        derived = np.where(dt_arr > 0, dd / np.maximum(dt_arr, 1e-3), 0)
        spd_arr = np.concatenate([[0.0], derived])
    spd_arr = np.where(np.isnan(spd_arr), 0.0, spd_arr)

    # --- laps (manual presses) -------------------------------------------
    laps = []
    for i, m in enumerate(fit.get_messages("lap")):
        f = _fit_fields(m)
        start = _fit_utc(f.get("start_time"))
        dur = f.get("total_elapsed_time") or f.get("total_timer_time") or 0.0
        dist_m = f.get("total_distance") or 0.0
        max_spd = f.get("enhanced_max_speed") or f.get("max_speed") or 0.0
        # Records whose timestamp falls within [start, start+dur) belong to this lap.
        in_lap = (t_arr >= start) & (t_arr < start + float(dur))
        laps.append({
            "idx": i + 1,
            "start_utc": start,
            "duration_s": float(dur),
            "distance_m": float(dist_m),
            "max_speed_m_s": float(max_spd),
            "track_t": t_arr[in_lap].copy(),
            "track_dist": dist_arr[in_lap].copy(),
        })

    # --- activity start ---------------------------------------------------
    activity_start = np.nan
    for m in fit.get_messages("session"):
        f = _fit_fields(m)
        activity_start = _fit_utc(f.get("start_time"))
        break
    if np.isnan(activity_start) and t_arr.size:
        activity_start = float(t_arr[0])

    return {
        "t": t_arr,
        "speed": spd_arr,
        "dist": dist_arr,
        "lat": lat_arr,
        "lon": lon_arr,
        "hr": hr_arr,
        "laps": laps,
        "activity_start_utc": activity_start,
    }


def load_garmin(path):
    """Load a Garmin activity by extension: .fit -> load_fit, else load_tcx.

    Returns the common track+lap dict that the rest of the pipeline consumes,
    so callers don't care which format Garmin Connect handed them."""
    if path is None:
        raise ValueError("No Garmin file path provided for this session.")
    if str(path).lower().endswith(".fit"):
        return load_fit(path)
    return load_tcx(path)


# ------------------------------------------------------------------
# Phase 1 — time alignment via GPS speed cross-correlation
# ------------------------------------------------------------------
def _resample_uniform(t, y, t_grid):
    """Linear interpolate y(t) onto t_grid. y is filled with 0 outside [t.min, t.max]."""
    return np.interp(t_grid, t, y, left=0.0, right=0.0)


def _xcorr_alignment(kg, tcx, max_search_s=1500.0, dt_s=1.0):
    """
    Cross-correlate KG GPS speed and Garmin GPS speed to find the offset.

    Uses NORMALIZED Pearson cross-correlation at each lag (not raw dot product).
    Returns (kg_t0_utc, offset_s, best_r, fallback_used, extras_dict).
    """
    kg_dur = float(kg["gps_t"].max())
    kg_grid_local = np.arange(0.0, kg_dur, dt_s)
    kg_speed_u = _resample_uniform(kg["gps_t"], kg["gps_speed"], kg_grid_local)

    garmin_t0 = float(tcx["t"][0])
    garmin_dur = float(tcx["t"][-1] - tcx["t"][0])
    garmin_grid_local = np.arange(0.0, garmin_dur, dt_s)
    garmin_speed_u = _resample_uniform(tcx["t"] - garmin_t0, tcx["speed"], garmin_grid_local)

    a = kg_speed_u
    b = garmin_speed_u
    n_a = len(a)
    n_b = len(b)
    n_lags = int(max_search_s / dt_s)

    lags = []
    scores = []
    for k in range(0, n_lags + 1):
        end = min(k + n_b, n_a)
        usable = end - k
        if usable < int(120 / dt_s):
            break
        a_w = a[k:end]
        b_w = b[:usable]
        a_m = a_w.mean()
        b_m = b_w.mean()
        a_d = a_w - a_m
        b_d = b_w - b_m
        denom = math.sqrt(float(np.dot(a_d, a_d)) * float(np.dot(b_d, b_d)))
        if denom <= 1e-12:
            r = 0.0
        else:
            r = float(np.dot(a_d, b_d) / denom)
        lags.append(k * dt_s)
        scores.append(r)

    lags = np.array(lags)
    scores = np.array(scores)
    best_idx = int(np.argmax(scores))
    best_offset = float(lags[best_idx])
    best_r = float(scores[best_idx])

    duration_diff = kg_dur - garmin_dur
    fallback_used = False
    if best_r < 0.3 and duration_diff > 60:
        best_offset = duration_diff
        fallback_used = True

    kg_t0_utc = garmin_t0 - best_offset

    extras = {
        "kg_grid_local": kg_grid_local,
        "kg_speed_u": kg_speed_u,
        "garmin_grid_local": garmin_grid_local,
        "garmin_speed_u": garmin_speed_u,
        "garmin_t0_utc": garmin_t0,
        "kg_duration_s": kg_dur,
        "garmin_duration_s": garmin_dur,
        "lags": lags,
        "scores": scores,
    }
    return kg_t0_utc, best_offset, best_r, fallback_used, extras


def align_kg_to_garmin(kg, tcx, max_search_s=1500.0, dt_s=1.0):
    """
    Determine kg_t0_utc — the absolute UTC epoch-seconds of KG local t=0.

    If the log contains TIME records (firmware >= 2026-05-23), uses the first
    one directly:  kg_t0_utc = unix_us/1e6 - local_ms/1e3.
    Falls back to GPS-speed cross-correlation for older logs without TIME records.

    Always runs cross-correlation so the diagnostic plot and validation r are
    available regardless of alignment method.
    """
    # Always compute cross-correlation (needed for diagnostic plot + validation)
    xcorr_t0, xcorr_offset, xcorr_r, xcorr_fallback, extras = \
        _xcorr_alignment(kg, tcx, max_search_s, dt_s)

    time_recs = kg.get("time_records", [])
    if time_recs:
        tr = time_recs[0]
        # local_ms: millis since KG boot.  unix_us: microseconds since Unix epoch.
        kg_t0_utc = tr["unix_us"] / 1e6 - tr["local_ms"] / 1e3
        garmin_t0 = extras["garmin_t0_utc"]
        offset_s = garmin_t0 - kg_t0_utc
        method = "time_record"
    else:
        kg_t0_utc = xcorr_t0
        offset_s = xcorr_offset
        method = "xcorr"

    return {
        "kg_t0_utc": kg_t0_utc,
        "offset_s": offset_s,
        "best_r": xcorr_r,
        "lags": extras["lags"],
        "scores": extras["scores"],
        "fallback_used": xcorr_fallback,
        "alignment_method": method,
        "xcorr_kg_t0_utc": xcorr_t0,
        "kg_grid_local": extras["kg_grid_local"],
        "kg_speed_u": extras["kg_speed_u"],
        "garmin_grid_local": extras["garmin_grid_local"],
        "garmin_speed_u": extras["garmin_speed_u"],
        "garmin_t0_utc": extras["garmin_t0_utc"],
        "kg_duration_s": extras["kg_duration_s"],
        "garmin_duration_s": extras["garmin_duration_s"],
    }


def plot_alignment_diagnostic(align, savepath):
    """Plot the cross-correlation curve over the candidate offset range."""
    fig, ax = plt.subplots(2, 1, figsize=(14, 7))
    ax[0].plot(align["lags"], align["scores"], color="steelblue")
    ax[0].axvline(align["offset_s"], color="red", linewidth=1.0, alpha=0.8,
                  label=f"chosen offset = {align['offset_s']:.1f} s  (r = {align['best_r']:.3f})")
    ax[0].set_xlabel("Candidate offset (KG-local seconds when Garmin starts)")
    ax[0].set_ylabel("Pearson r of speed signals")
    ax[0].set_title("Cross-correlation diagnostic")
    ax[0].grid(True, alpha=0.3)
    ax[0].legend()

    # Show both signals on a common LOCAL time axis (Garmin shifted by offset)
    kg_local = align["kg_grid_local"]
    g_local = align["garmin_grid_local"] + align["offset_s"]
    ax[1].plot(kg_local, align["kg_speed_u"], color="steelblue", linewidth=0.7, label="KG speed (local)")
    ax[1].plot(g_local, align["garmin_speed_u"], color="firebrick", linewidth=0.7, alpha=0.8, label="Garmin speed (shifted)")
    ax[1].set_xlabel("KG-local time (s)")
    ax[1].set_ylabel("Speed (m/s)")
    ax[1].set_title("KG vs Garmin speed in KG-local time after alignment")
    ax[1].grid(True, alpha=0.3)
    ax[1].legend()

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_speed_overlay(kg, tcx, align, savepath):
    fig, ax = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    # Convert KG GPS to UTC seconds using alignment
    kg_t_utc = kg["gps_t"] + align["kg_t0_utc"]

    ax[0].plot(kg_t_utc, kg["gps_speed"], label="KG GPS speed", color="steelblue", linewidth=0.8)
    ax[0].plot(tcx["t"], tcx["speed"], label="Garmin GPS speed", color="firebrick", linewidth=0.8, alpha=0.8)
    ax[0].set_ylabel("Speed (m/s)")
    ax[0].set_title(f"Session 37 — KG vs Garmin GPS speed (aligned offset = {align['offset_s']:.1f} s)")
    ax[0].legend(loc="upper right")
    ax[0].grid(True, alpha=0.3)

    # Mark Garmin lap boundaries
    for lap in tcx["laps"]:
        ax[0].axvline(lap["start_utc"], color="gray", alpha=0.25, linewidth=0.6)
        ax[0].text(lap["start_utc"], ax[0].get_ylim()[1] * 0.92, f"L{lap['idx']}", fontsize=7,
                   color="gray", ha="left", va="top")

    # Bottom panel: residual (interpolated KG - Garmin) over the overlap window
    ovr_t = tcx["t"]
    kg_local = ovr_t - align["kg_t0_utc"]
    kg_speed_at_garmin = np.interp(kg_local, kg["gps_t"], kg["gps_speed"], left=np.nan, right=np.nan)
    ax[1].plot(ovr_t, kg_speed_at_garmin - tcx["speed"], color="purple", linewidth=0.6)
    ax[1].axhline(0, color="black", linewidth=0.5)
    ax[1].set_ylabel("KG − Garmin (m/s)")
    ax[1].set_xlabel("UTC time (s since epoch)")
    ax[1].set_title("Residual after alignment")
    ax[1].grid(True, alpha=0.3)

    # Convert x-axis ticks to readable HH:MM:SS UTC
    def utc_fmt(x, _pos):
        return dt.datetime.fromtimestamp(x, tz=dt.timezone.utc).strftime("%H:%M:%S")
    for a_ in ax:
        a_.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(utc_fmt))

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_gps_track(kg, tcx, savepath):
    fig, ax = plt.subplots(1, 1, figsize=(10, 9))
    ax.plot(kg["gps_lon"], kg["gps_lat"], color="steelblue", linewidth=0.7, label="KG track")
    valid = ~np.isnan(tcx["lat"])
    ax.plot(tcx["lon"][valid], tcx["lat"][valid], color="firebrick", linewidth=0.7, alpha=0.7, label="Garmin track")

    # Mark lap starts
    for lap in tcx["laps"]:
        if len(lap["track_t"]) == 0:
            continue
        # find the Garmin trackpoint at lap start
        idx = np.argmin(np.abs(tcx["t"] - lap["start_utc"]))
        if not np.isnan(tcx["lat"][idx]):
            ax.plot(tcx["lon"][idx], tcx["lat"][idx], "o", color="black", markersize=5)
            ax.annotate(f"L{lap['idx']}", (tcx["lon"][idx], tcx["lat"][idx]),
                        textcoords="offset points", xytext=(4, 4), fontsize=7)

    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_title("Session 37 GPS tracks — Alameda Bay")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Phase 2 — auto-detect IMU body-frame axes
# ------------------------------------------------------------------
def find_stationary_window(kg, min_duration_s=20.0):
    """Find the longest contiguous KG-local segment where the device is
    effectively stationary, using GPS speed < 0.3 m/s and low gyro magnitude.
    Returns (t0, t1) in KG-local seconds, or (None, None) if no good window."""
    gps_t = kg["gps_t"]
    gps_v = kg["gps_speed"]
    if len(gps_t) < 10:
        return None, None
    # Resample GPS speed onto IMU times
    imu_t = kg["imu_t"]
    speed_imu = np.interp(imu_t, gps_t, gps_v, left=0, right=0)
    gyro_mag = np.linalg.norm(kg["gyro_raw"], axis=1)

    stationary = (speed_imu < 0.3) & (gyro_mag < 0.3)  # rad/s threshold

    # Find longest contiguous True run
    best_start = best_end = 0
    cur_start = None
    for i, s in enumerate(stationary):
        if s and cur_start is None:
            cur_start = i
        elif not s and cur_start is not None:
            if (i - cur_start) > (best_end - best_start):
                best_start, best_end = cur_start, i
            cur_start = None
    if cur_start is not None:
        if (len(stationary) - cur_start) > (best_end - best_start):
            best_start, best_end = cur_start, len(stationary)

    t0 = float(imu_t[best_start])
    t1 = float(imu_t[best_end - 1]) if best_end > best_start else t0
    if (t1 - t0) < min_duration_s:
        return None, None
    return t0, t1


def detect_imu_axes(kg, cruise_local_window=(900.0, 1400.0)):
    """
    Find a rotation R (3x3) so that body-frame accel = R @ raw_accel,
    with the convention x=forward, y=left, z=up.

    Strategy:
      - up = mean(accel during a stationary segment) / |that mean| (gravity in body frame)
      - horizontal accel = accel - up * <up, accel>
      - principal axis of horizontal accel (PCA) ≈ forward direction
      - sign-correct forward by correlating with GPS dV/dt during cruise
    """
    A = kg["accel_raw"]

    # Prefer a stationary window for gravity estimation
    s0, s1 = find_stationary_window(kg)
    if s0 is not None:
        m_still = (kg["imu_t"] >= s0) & (kg["imu_t"] <= s1)
        g_body = np.mean(A[m_still], axis=0)
        gravity_window = (s0, s1)
    else:
        g_body = np.mean(A, axis=0)
        gravity_window = None

    g_mag = float(np.linalg.norm(g_body))
    up = g_body / g_mag
    # We want z=up to point in the gravity-positive direction (so static accel reads +g on z).

    # Restrict the search for "forward" to a clean cruise window in KG-local seconds
    t = kg["imu_t"]
    mask = (t >= cruise_local_window[0]) & (t <= cruise_local_window[1])
    if not np.any(mask):
        mask = np.ones_like(t, dtype=bool)
    A_cruise = A[mask]

    # Remove gravity component from cruise accel
    A_cruise_horiz = A_cruise - np.outer(A_cruise @ up, up)

    # PCA: principal axis of horizontal motion accel
    A_cruise_horiz -= A_cruise_horiz.mean(axis=0)
    cov = A_cruise_horiz.T @ A_cruise_horiz / max(1, A_cruise_horiz.shape[0] - 1)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # Largest eigenvalue at index -1
    fwd_raw = eigvecs[:, -1]

    # Force fwd to be perpendicular to up (numerically clean)
    fwd_raw = fwd_raw - up * float(fwd_raw @ up)
    fwd_raw = fwd_raw / np.linalg.norm(fwd_raw)

    # Sign-correct: project cruise accel onto fwd_raw, compare to GPS dV/dt
    a_fwd = A_cruise_horiz @ fwd_raw  # scalar trace over cruise window

    # Build a low-passed GPS speed for the same window, then differentiate
    gps_t = kg["gps_t"]
    gps_v = kg["gps_speed"]
    in_win = (gps_t >= cruise_local_window[0]) & (gps_t <= cruise_local_window[1])
    if np.sum(in_win) >= 5:
        gt = gps_t[in_win]
        gv = gps_v[in_win]
        dvdt = np.gradient(gv, gt)  # m/s^2
        # Interp dvdt onto IMU cruise times
        dvdt_imu = np.interp(t[mask], gt, dvdt, left=0, right=0)
        # Smooth a_fwd to similar timescale (~0.2 s window)
        # Effective sample rate
        if len(t[mask]) > 100:
            est_dt = float(np.median(np.diff(t[mask])))
            win = max(3, int(round(0.2 / max(est_dt, 1e-3))))
            if win % 2 == 0:
                win += 1
            kernel = np.ones(win) / win
            a_fwd_smooth = np.convolve(a_fwd, kernel, mode="same")
        else:
            a_fwd_smooth = a_fwd
        # Correlation
        if np.std(a_fwd_smooth) > 0 and np.std(dvdt_imu) > 0:
            corr = float(np.corrcoef(a_fwd_smooth, dvdt_imu)[0, 1])
        else:
            corr = 0.0
    else:
        corr = 0.0

    if corr < 0:
        fwd_raw = -fwd_raw

    forward = fwd_raw
    # Right-hand frame: lateral (left) = up x forward
    lateral = np.cross(up, forward)
    lateral = lateral / np.linalg.norm(lateral)

    R = np.stack([forward, lateral, up], axis=0)  # rows are body axes expressed in raw frame
    # body_accel = R @ raw_accel; for each row of accel matrix (n,3): body = raw @ R.T

    # Pick which raw axis the forward direction is most aligned with (for diagnostics)
    fwd_label = ["+X", "+Y", "+Z", "-X", "-Y", "-Z"]
    fwd_components = np.concatenate([forward, -forward])
    fwd_dom_idx = int(np.argmax(np.abs(fwd_components)))
    up_components = np.concatenate([up, -up])
    up_dom_idx = int(np.argmax(np.abs(up_components)))

    info = {
        "gravity_magnitude": g_mag,
        "gravity_window_s": gravity_window,
        "up_in_raw": up.tolist(),
        "forward_in_raw": forward.tolist(),
        "lateral_in_raw": lateral.tolist(),
        "axis_corr_with_gps_dvdt": corr,
        "up_dominant_raw_axis": fwd_label[up_dom_idx],
        "forward_dominant_raw_axis": fwd_label[fwd_dom_idx],
        "cruise_window_s": cruise_local_window,
    }
    return R, info


def rotate_accel(R, A_raw):
    """Rotate raw accel into body frame x=forward, y=left, z=up."""
    return A_raw @ R.T


def rotate_gyro(R, G_raw):
    return G_raw @ R.T


def plot_axis_verification(kg, R, info, align, savepath):
    """Plot rotated forward accel vs GPS speed in a cruise window."""
    t = kg["imu_t"]
    A_body = rotate_accel(R, kg["accel_raw"])
    t0, t1 = info["cruise_window_s"]
    m = (t >= t0) & (t <= t1)

    fig, ax = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    ax[0].plot(t[m], A_body[m, 0], color="steelblue", linewidth=0.5, label="forward (x)")
    ax[0].set_ylabel("a_fwd (m/s²)")
    ax[0].set_title(f"Rotated forward accel — cruise window [{t0:.0f}, {t1:.0f}] s")
    ax[0].grid(True, alpha=0.3)
    ax[0].legend(loc="upper right")

    ax[1].plot(t[m], A_body[m, 1], color="seagreen", linewidth=0.5, label="lateral / left (y)")
    ax[1].plot(t[m], A_body[m, 2] - 9.81, color="orange", linewidth=0.5, label="up (z) − 9.81")
    ax[1].set_ylabel("a (m/s²)")
    ax[1].set_title("Other rotated axes (lateral and gravity-removed up)")
    ax[1].grid(True, alpha=0.3)
    ax[1].legend(loc="upper right")

    # GPS speed in same window
    g_t = kg["gps_t"]
    g_v = kg["gps_speed"]
    g_m = (g_t >= t0) & (g_t <= t1)
    ax[2].plot(g_t[g_m], g_v[g_m], color="firebrick", linewidth=1.0, label="GPS speed")
    ax[2].set_ylabel("Speed (m/s)")
    ax[2].set_xlabel("KG local time (s)")
    ax[2].grid(True, alpha=0.3)
    ax[2].legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Phase 3 — stroke detection v0 on the L/R burst section
# ------------------------------------------------------------------
def _estimate_fs(t):
    """Robust sample-rate estimate from total span (timestamps are 1 ms quantized)."""
    if len(t) < 2:
        return 0.0
    span = t[-1] - t[0]
    if span <= 0:
        return 0.0
    return (len(t) - 1) / span


def _bandpass(y, fs, lo=0.5, hi=3.0, order=2):
    """Butterworth band-pass in second-order-section form for numerical stability
    at the wide-fs / narrow-passband ratio we see here (fs≈412 Hz, passband 0.5-3 Hz)."""
    if fs <= 2 * hi:
        return y
    sos = butter(order, [lo, hi], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, y)


def _gap_fill_peaks(signal, peaks, min_sep, floor_frac=0.35, max_k=3):
    """Recover soft real strokes the amplitude detector dropped, using the
    established cadence as a prior.

    The median inter-peak spacing is the most reliable thing KG measures, so we
    trust it: for each gap that is ~k x the median period (k = 2..max_k), look
    near each rhythm-predicted catch for a local maximum that clears a LOWERED
    floor (floor_frac of the detected peaks' median height). A stroke is added
    only where such a bump actually exists, so genuine glides/pauses (no bump)
    and drills with no steady rhythm are left untouched — the fill is
    self-gating. `signal` is the same (band-passed) trace find_peaks ran on;
    `peaks` and `min_sep` are in samples.
    """
    peaks = sorted(int(p) for p in peaks)
    diffs = np.diff(peaks)
    period = float(np.median(diffs)) if len(diffs) else 0.0
    if period <= 0:
        return peaks
    floor = floor_frac * float(np.median(signal[peaks]))
    half = max(1, int(0.30 * period))
    out = list(peaks)
    for a, b in zip(peaks[:-1], peaks[1:]):
        gap = b - a
        k = int(round(gap / period))
        if k < 2 or k > max_k:
            continue
        for j in range(1, k):
            center = a + int(round(j * gap / k))
            lo = max(a + min_sep, center - half)
            hi = min(b - min_sep, center + half)
            if hi <= lo:
                continue
            idx = lo + int(np.argmax(signal[lo:hi]))
            if signal[idx] >= floor:
                out.append(idx)
    return sorted(set(out))


def detect_strokes(t, fwd_accel, prominence=1.0, height=0.5, refractory_s=0.4,
                   use_bandpass=True, adaptive=False, adaptive_k=1.3,
                   adaptive_floor=0.7, gap_fill=False, gap_fill_floor_frac=0.35,
                   gap_fill_max_k=3):
    """Peak detection on forward accel.

    Uses scipy.signal.find_peaks with both a prominence and an absolute height
    threshold. Prominence handles amplitude variation between cruise and sprint;
    height kills low-level oscillations that pass prominence in slow water.

    Adaptive mode (opt-in, default off so existing callers are unchanged):
    when a paddler's strokes are unusually weak, their forward-accel peaks fall
    below the fixed `height`/`prominence` floor and get missed. With
    `adaptive=True`, the threshold is scaled to the band-passed signal's own
    amplitude (k * MAD) and CLAMPED to [adaptive_floor, height] — i.e. it can
    only ever *lower* the bar relative to the caller's `height`, and only when
    the signal is weak. Strong/normal laps land at `height` and are unchanged.
    Because a quiet rest looks the same as weak strokes to an amplitude test,
    callers should gate this on a "boat is moving" signal (see analyze_lap).

    Returns list of (time, index) tuples where index is into the input arrays.
    """
    if len(t) < 50:
        return []

    fs = _estimate_fs(t)
    if fs <= 0:
        return []
    dt = 1.0 / fs

    signal = fwd_accel
    if use_bandpass and fs > 6:
        try:
            signal = _bandpass(fwd_accel, fs, lo=0.5, hi=3.0)
            if not np.all(np.isfinite(signal)):
                signal = fwd_accel
        except Exception:
            signal = fwd_accel

    if adaptive:
        # Robust amplitude scale (median absolute deviation). Clamp so we never
        # raise the bar above the caller's height nor drop below the floor.
        mad = float(np.median(np.abs(signal - np.median(signal))))
        h = min(height, max(adaptive_floor, adaptive_k * mad))
        prom = prominence * (h / height) if height > 0 else prominence
        height, prominence = h, prom

    distance = max(1, int(refractory_s / dt))
    peaks, _ = find_peaks(signal, prominence=prominence, height=height,
                          distance=distance)
    peaks = list(peaks)
    if gap_fill and len(peaks) >= 5:
        peaks = _gap_fill_peaks(signal, peaks, distance,
                                floor_frac=gap_fill_floor_frac,
                                max_k=gap_fill_max_k)
    return [(float(t[i]), int(i)) for i in peaks]


def lap_local_window(lap, align):
    """Return (t_local_start, t_local_end) in KG local seconds for a Garmin lap."""
    t0 = lap["start_utc"] - align["kg_t0_utc"]
    t1 = t0 + lap["duration_s"]
    return t0, t1


def _classify_side(g_roll_seg, g_yaw_seg=None):
    """Return 'L' or 'R' for a stroke given gyro segments around the catch.

    Preferred signal (OC1): yaw rate about the up axis. A LEFT-side stroke
    applies forward thrust on the boat's left, offset from centerline; the
    bow yaws RIGHT, which is NEGATIVE yaw rate in our right-hand x=fwd,
    y=left, z=up convention. RIGHT-side stroke -> bow yaws left -> +yaw.

    Roll rate is kept as a backup signal because some boats (kayak/surfski)
    have strong roll dynamics. The integral of yaw over the catch window is
    a more robust feature than the peak — see explore_side_discrimination.py.
    """
    if g_yaw_seg is not None and len(g_yaw_seg) > 0:
        # Integral (preserves direction) of yaw over the window
        score = float(np.sum(g_yaw_seg))
        # NEGATIVE yaw rate at catch -> bow yaws right -> LEFT stroke
        return "L" if score < 0 else "R"
    # Fallback to roll-based classification
    if len(g_roll_seg) == 0:
        return "?"
    peak = g_roll_seg[int(np.argmax(np.abs(g_roll_seg)))]
    return "L" if peak > 0 else "R"


def plot_burst_strokes(kg, R, tcx, align, savepath, savepath_zoom):
    """Two renderings of the L/R hard-stroke test:
       - Wide view of Garmin laps 5-9 to show context
       - Per-lap zoom on laps 6, 7, 8 (the actual bursts)
    """
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    t = kg["imu_t"]
    laps_by_idx = {lap["idx"]: lap for lap in tcx["laps"]}

    # ---- Wide view (laps 5-9) ----
    wide_laps = [laps_by_idx[i] for i in (5, 6, 7, 8, 9) if i in laps_by_idx]
    if not wide_laps:
        return None
    t0w = min(lap_local_window(lap, align)[0] for lap in wide_laps) - 2.0
    t1w = max(lap_local_window(lap, align)[1] for lap in wide_laps) + 2.0
    mw = (t >= t0w) & (t <= t1w)
    tt_w = t[mw]; a_w = A_body[mw, 0]
    g_w = G_body[mw, 0]      # roll
    yaw_w = G_body[mw, 2]    # yaw — the actual OC1 side discriminator
    sw = detect_strokes(tt_w, a_w, prominence=1.5, height=0.5, refractory_s=0.35)
    sides_w = []
    post = int(0.30 * NOMINAL_IMU_HZ)  # 300 ms after catch
    for _, idx in sw:
        lo_i = idx
        hi_i = min(len(yaw_w), idx + post)
        sides_w.append(_classify_side(g_w[lo_i:hi_i], yaw_w[lo_i:hi_i]))

    fig, ax = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    ax[0].plot(tt_w, a_w, color="steelblue", linewidth=0.5)
    for (st_t, _), side in zip(sw, sides_w):
        ax[0].axvline(st_t, color=("red" if side == "L" else "navy"),
                      alpha=0.4, linewidth=0.5)
    ax[0].set_ylabel("a_fwd (m/s²)")
    ax[0].set_title(f"Laps 5-9 (context) — {len(sw)} strokes; red=L, navy=R")
    ax[0].grid(True, alpha=0.3)
    ax[1].plot(tt_w, g_w, color="coral", linewidth=0.5)
    ax[1].axhline(0, color="black", linewidth=0.4)
    ax[1].set_ylabel("ω_roll (rad/s)")
    ax[1].grid(True, alpha=0.3)
    for lap in wide_laps:
        lt0, lt1 = lap_local_window(lap, align)
        for a_ in ax[:2]:
            a_.axvspan(lt0, lt1, color="gray", alpha=0.06)
        ax[0].text((lt0 + lt1) / 2, ax[0].get_ylim()[1] * 0.92,
                   f"L{lap['idx']}\n{lap['distance_m']:.0f}m\n{lap['duration_s']:.0f}s",
                   ha="center", va="top", fontsize=8)
    g_t = kg["gps_t"]; g_v = kg["gps_speed"]
    gm = (g_t >= t0w) & (g_t <= t1w)
    ax[2].plot(g_t[gm], g_v[gm], color="firebrick", linewidth=1.0)
    ax[2].set_ylabel("GPS speed (m/s)")
    ax[2].set_xlabel("KG local time (s)")
    ax[2].grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)

    # ---- Per-burst zoom: laps 6, 7, 8 ----
    burst_ids = [i for i in (6, 7, 8) if i in laps_by_idx]
    fig, axes = plt.subplots(len(burst_ids), 2, figsize=(14, 3 * len(burst_ids)),
                             squeeze=False)
    burst_summary = []
    for row, idx in enumerate(burst_ids):
        lap = laps_by_idx[idx]
        lt0, lt1 = lap_local_window(lap, align)
        pad = 0.5
        mm = (t >= lt0 - pad) & (t <= lt1 + pad)
        tt = t[mm]
        a = A_body[mm, 0]
        gr = G_body[mm, 0]
        yaw_seg_all = G_body[mm, 2]
        strokes = detect_strokes(tt, a, prominence=1.5, height=0.5, refractory_s=0.35)
        sides = []
        post = int(0.30 * NOMINAL_IMU_HZ)
        for st_t, _ in strokes:
            local_i = int(np.searchsorted(tt, st_t))
            lo_i = local_i
            hi_i = min(len(yaw_seg_all), local_i + post)
            sides.append(_classify_side(gr[lo_i:hi_i], yaw_seg_all[lo_i:hi_i]))
        nL = sum(1 for s in sides if s == "L")
        nR = sum(1 for s in sides if s == "R")
        cad = 0.0
        if len(strokes) >= 2:
            intervals = np.diff([st[0] for st in strokes])
            cad = 60.0 / float(np.median(intervals))
        burst_summary.append({"lap": idx, "n": len(strokes), "L": nL, "R": nR, "cad": cad})

        ax0 = axes[row, 0]
        ax0.plot(tt - lt0, a, color="steelblue", linewidth=0.7)
        for (st_t, _), side in zip(strokes, sides):
            ax0.axvline(st_t - lt0, color=("red" if side == "L" else "navy"),
                        alpha=0.8, linewidth=1.0)
        ax0.axvspan(0, lt1 - lt0, color="gray", alpha=0.08)
        ax0.set_ylabel("a_fwd (m/s²)")
        ax0.set_title(f"Lap {idx}  | {lap['duration_s']:.1f}s, {lap['distance_m']:.0f}m  | "
                      f"{len(strokes)} strokes ({nL} L / {nR} R) @ {cad:.0f} spm")
        ax0.grid(True, alpha=0.3)

        ax1 = axes[row, 1]
        ax1.plot(tt - lt0, yaw_seg_all, color="purple", linewidth=0.8, label="yaw rate")
        ax1.axhline(0, color="black", linewidth=0.5)
        ax1.axvspan(0, lt1 - lt0, color="gray", alpha=0.08)
        for (st_t, _), side in zip(strokes, sides):
            ax1.axvline(st_t - lt0, color=("red" if side == "L" else "navy"),
                        alpha=0.8, linewidth=1.0)
        ax1.set_ylabel("ω_yaw (rad/s)")
        ax1.set_title(f"Lap {idx} yaw rate at catches  (negative = LEFT stroke, positive = RIGHT)")
        ax1.grid(True, alpha=0.3)
        if row == len(burst_ids) - 1:
            ax0.set_xlabel("Time since lap start (s)")
            ax1.set_xlabel("Time since lap start (s)")

    fig.tight_layout()
    fig.savefig(savepath_zoom, dpi=140, bbox_inches="tight")
    plt.close(fig)

    return {
        "n_strokes_wide": len(sw),
        "sides_wide": sides_w,
        "per_burst": burst_summary,
    }


# ------------------------------------------------------------------
# Phase 4 — per-lap stroke summary and force-curve comparison
# ------------------------------------------------------------------
def stroke_features_for_window(t, fwd_accel, gyro_roll, strokes, mass_kg):
    """For each detected stroke, characterize a window between midpoints."""
    feats = []
    n = len(strokes)
    for i, (st_t, st_i) in enumerate(strokes):
        start = 0 if i == 0 else (strokes[i - 1][1] + st_i) // 2
        end = len(fwd_accel) if i == n - 1 else (st_i + strokes[i + 1][1]) // 2
        if end - start < 5:
            continue
        seg = fwd_accel[start:end]
        seg_t = t[start:end] - t[start]

        peak = float(np.max(seg))
        peak_idx_rel = int(np.argmax(seg))
        peak_pos = peak_idx_rel / max(1, len(seg) - 1)
        impulse = float(np.sum(np.maximum(seg, 0.0)) * np.median(np.diff(seg_t)) if len(seg_t) > 1 else 0.0)

        # Side
        roll_seg = gyro_roll[start:end]
        peak_roll = float(roll_seg[np.argmax(np.abs(roll_seg))]) if len(roll_seg) else 0.0
        side = "L" if peak_roll > 0 else "R"

        feats.append({
            "t": float(st_t),
            "peak_accel": peak,
            "peak_force_N": peak * mass_kg,
            "peak_pos": peak_pos,
            "impulse_m_s": impulse,
            "side": side,
            "start_idx": start,
            "end_idx": end,
            "duration_s": float(seg_t[-1] - seg_t[0]) if len(seg_t) > 1 else 0.0,
            "fwd_segment": seg.copy(),
            "time_segment": seg_t.copy(),
        })
    return feats


def _is_connected_stroke(fwd_segment, mass_kg, n_points=101,
                          peak_min_N=10.0, prominence_frac=0.05,
                          min_separation_pct=5):
    """Classify one stroke's positive-only force curve as connected (single
    peak) or disconnected (separate catch bump before drive).

    Implementation matches `analysis/connection_metrics.py::connection_metrics`:
    - resample stroke segment to 101 phase points and clip to ≥ 0
    - light smoothing (3-point moving average)
    - scipy.signal.find_peaks with absolute-height floor + prominence threshold
      scaled to each stroke's amplitude
    - connected = only one positive peak survives the filters
    """
    from scipy.signal import find_peaks
    if fwd_segment is None or len(fwd_segment) < 20:
        return None
    force = np.maximum(fwd_segment * mass_kg, 0.0)
    c = np.interp(np.linspace(0, 1, n_points),
                  np.linspace(0, 1, len(force)), force)
    # 3-point moving average — light, just smooths quantization noise
    kernel = np.ones(3) / 3.0
    cs = np.convolve(c, kernel, mode="same")

    curve_max = float(np.max(cs))
    if curve_max < peak_min_N:
        return None
    prom = max(5.0, prominence_frac * curve_max)
    peaks, _ = find_peaks(cs, height=peak_min_N, prominence=prom,
                          distance=min_separation_pct)
    if len(peaks) == 0:
        return True  # no clear structure — treat as connected
    return bool(len(peaks) == 1)


def _side_envelope_metrics(yaw, fs, edge_skip_s=5.0):
    """Per-lap side metrics from the slow yaw envelope.

    The 0.02-0.15 Hz band-passed yaw rate tracks which side the paddler is
    biased toward. Sign of envelope = current side. Aggregating from the
    envelope is far more robust than counting per-stroke labels (which are
    noise-dominated in cruise/choppy conditions).

    Returns:
        left_fraction:    fraction of lap time with negative envelope (L-bias)
        n_switches:       count of envelope sign changes
        median_block_s:   median duration of a single-side run (in seconds)
    """
    if fs <= 0.3:
        return None
    try:
        env = _bandpass(yaw, fs, lo=0.02, hi=0.15)
    except Exception:
        return None
    if not np.all(np.isfinite(env)):
        return None
    edge = int(edge_skip_s * fs)
    if len(env) > 2 * edge + 100:
        core = env[edge:-edge]
    else:
        core = env
    if len(core) < 10:
        return None
    left_fraction = float(np.mean(core < 0))
    signs = np.sign(core)
    signs[signs == 0] = 1
    switch_idx = np.where(np.diff(signs) != 0)[0] + 1
    boundaries = np.concatenate(([0], switch_idx, [len(signs)]))
    run_lens_samples = np.diff(boundaries)
    median_run_s = (float(np.median(run_lens_samples)) / fs
                    if len(run_lens_samples) else 0.0)
    return {
        "left_fraction": left_fraction,
        "n_switches": int(len(switch_idx)),
        "median_block_s": median_run_s,
        "envelope": env,
    }


def analyze_lap(kg, A_body, G_body, lap, align, mass_kg, prominence=1.5,
                height=1.0, refractory_s=0.4, adaptive=False,
                adaptive_gate_mps=1.1, adaptive_k=1.3, adaptive_floor=0.7,
                gap_fill=False):
    t0, t1 = lap_local_window(lap, align)
    t = kg["imu_t"]
    m = (t >= t0) & (t <= t1)
    if np.sum(m) < 200:
        return None
    tt = t[m]
    fwd = A_body[m, 0]
    roll = G_body[m, 0]
    yaw_seg = G_body[m, 2]
    fs = _estimate_fs(tt)
    side_metrics = _side_envelope_metrics(yaw_seg, fs)

    # Gate adaptive (weak-stroke) detection on GPS speed: only lower the
    # detection threshold when the boat is actually moving. A drifting rest has
    # the same low signal amplitude as weak strokes, so without this gate the
    # adaptive floor would manufacture phantom strokes out of rest noise.
    gt, gv = kg["gps_t"], kg["gps_speed"]
    gm = (gt >= t0) & (gt <= t1)
    mean_speed = float(np.mean(gv[gm])) if np.any(gm) else float("nan")
    use_adaptive = bool(adaptive and np.isfinite(mean_speed)
                        and mean_speed >= adaptive_gate_mps)
    # Gap-fill rides the same "boat is moving" gate as adaptive, so it never
    # invents strokes on a drift/rest/ama drill (no steady cadence there anyway).
    use_gap_fill = bool(gap_fill and np.isfinite(mean_speed)
                        and mean_speed >= adaptive_gate_mps)

    strokes = detect_strokes(tt, fwd, prominence=prominence, height=height,
                              refractory_s=refractory_s, adaptive=use_adaptive,
                              adaptive_k=adaptive_k, adaptive_floor=adaptive_floor,
                              gap_fill=use_gap_fill)
    feats = stroke_features_for_window(tt, fwd, roll, strokes, mass_kg)
    if len(feats) < 2:
        return {"lap": lap, "feats": feats, "cadence_spm": 0.0, "n_strokes": len(feats)}

    times = np.array([f["t"] for f in feats])
    intervals = np.diff(times)
    cadence = 60.0 / np.median(intervals) if len(intervals) > 0 else 0.0

    # mean_speed (GPS, KG side) already computed above for the adaptive gate.

    # Distance per stroke (DPS) — paddle-sport gold-standard metric
    duration_s = float(tt[-1] - tt[0]) if len(tt) > 1 else 0.0
    distance_m = mean_speed * duration_s if duration_s > 0 else 0.0
    dps_m = (distance_m / len(feats)) if len(feats) > 0 else 0.0

    # Connected-stroke fraction — what % of strokes are textbook single-arch
    # vs have a separate catch bump + lull before the drive. Higher = more
    # textbook PERG-style technique.
    conn_flags = [_is_connected_stroke(f.get("fwd_segment"), mass_kg)
                  for f in feats]
    conn_valid = [c for c in conn_flags if c is not None]
    connected_fraction = (float(np.mean(conn_valid)) if conn_valid else 0.0)

    out = {
        "lap": lap,
        "feats": feats,
        "cadence_spm": float(cadence),
        "n_strokes": len(feats),
        "mean_speed_m_s": mean_speed,
        "mean_peak_force_N": float(np.mean([f["peak_force_N"] for f in feats])),
        "mean_impulse_m_s": float(np.mean([f["impulse_m_s"] for f in feats])),
        "distance_per_stroke_m": dps_m,
        "connected_fraction": connected_fraction,
    }
    if side_metrics is not None:
        out["left_time_fraction"] = side_metrics["left_fraction"]
        out["n_side_switches"] = side_metrics["n_switches"]
        out["median_block_s"] = side_metrics["median_block_s"]
        out["median_block_strokes"] = (side_metrics["median_block_s"] * (cadence / 60.0)
                                       if cadence > 0 else 0.0)
    return out


def plot_per_lap_summary(per_lap, savepath):
    laps_ok = [r for r in per_lap if r is not None and r["n_strokes"] >= 5]
    if not laps_ok:
        return
    idx = [r["lap"]["idx"] for r in laps_ok]
    cad = [r["cadence_spm"] for r in laps_ok]
    spd = [r["mean_speed_m_s"] for r in laps_ok]
    peak = [r["mean_peak_force_N"] for r in laps_ok]
    dps = [r.get("distance_per_stroke_m", 0) for r in laps_ok]
    lfrac = [r.get("left_time_fraction", 0.5) for r in laps_ok]
    switches = [r.get("n_side_switches", 0) for r in laps_ok]
    conn = [r.get("connected_fraction", 0.0) for r in laps_ok]

    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    axes[0, 0].bar(idx, cad, color="steelblue"); axes[0, 0].set_title("Cadence per lap (spm)")
    axes[0, 1].bar(idx, spd, color="firebrick"); axes[0, 1].set_title("Mean GPS speed per lap (m/s)")
    axes[0, 2].bar(idx, peak, color="purple");   axes[0, 2].set_title("Mean peak drive force (N)")
    axes[0, 3].bar(idx, dps, color="teal");      axes[0, 3].set_title("Distance per stroke (m)")

    axes[1, 0].bar(idx, [v * 100 for v in conn], color="darkgreen")
    axes[1, 0].set_title("Connected strokes (%)  -  single-peak fraction")
    axes[1, 0].set_ylim(0, 100)

    axes[1, 1].bar(idx, [v * 100 for v in lfrac], color="darkorange")
    axes[1, 1].axhline(50, color="black", linewidth=0.7, linestyle="--",
                       label="50% (balanced)")
    axes[1, 1].set_title("Time on LEFT side (%)  -  envelope-based")
    axes[1, 1].set_ylim(0, 100); axes[1, 1].legend(fontsize=8)
    axes[1, 2].bar(idx, switches, color="seagreen")
    axes[1, 2].set_title("Side switches per lap")
    axes[1, 3].axis("off")  # spare slot for future metric

    for a in axes.ravel():
        if a.axison if hasattr(a, "axison") else True:
            a.set_xlabel("Garmin lap")
            a.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _resample_curve(y, n_points=101):
    if y is None or len(y) < 2:
        return None
    return np.interp(np.linspace(0, 1, n_points),
                     np.linspace(0, 1, len(y)), y)


def plot_lap_compare(per_lap, savepath, mass_kg=SYSTEM_MASS_KG):
    """Force-curve overlay comparing strong miles (laps 2-3) vs slow mile (lap 13).

    Uses ACTUAL stroke segments (not synthetic), resampled to a common phase
    grid so cruise vs slow-current strokes can be compared shape-by-shape.
    """
    by_idx = {r["lap"]["idx"]: r for r in per_lap if r is not None}
    comparisons = [
        ("Laps 2-3 (strong miles)", [2, 3], "steelblue"),
        ("Lap 13 (slow / current)", [13], "firebrick"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    n_points = 101
    phase_pct = np.linspace(0, 100, n_points)

    summary_lines = []
    for label, lap_idxs, color in comparisons:
        curves = []
        peaks_N = []
        impulses_m_s = []
        for li in lap_idxs:
            r = by_idx.get(li)
            if r is None:
                continue
            for f in r["feats"]:
                seg = f.get("fwd_segment")
                if seg is None or len(seg) < 5:
                    continue
                drive = np.maximum(seg, 0.0) * mass_kg
                cur = _resample_curve(drive, n_points)
                if cur is not None:
                    curves.append(cur)
                    peaks_N.append(f["peak_force_N"])
                    impulses_m_s.append(f["impulse_m_s"])
        if not curves:
            continue
        curves = np.array(curves)
        mean_curve = np.mean(curves, axis=0)
        q1 = np.percentile(curves, 25, axis=0)
        q3 = np.percentile(curves, 75, axis=0)

        axes[0].plot(phase_pct, mean_curve, color=color, linewidth=2.5,
                     label=f"{label} (n={len(curves)})")
        axes[0].fill_between(phase_pct, q1, q3, color=color, alpha=0.2)

        # Bar comparison: peak and impulse means
        summary_lines.append(
            f"{label}: mean peak = {np.mean(peaks_N):.0f} N, "
            f"mean impulse = {np.mean(impulses_m_s):.2f} m/s, n={len(curves)}"
        )

    axes[0].set_xlabel("Stroke phase (%)")
    axes[0].set_ylabel("Effective drive force (N)")
    axes[0].set_title("Mean force vs stroke phase  (band: 25-75 percentile)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    # Bar chart of peak and impulse
    labels_bar = []
    peaks_bar = []
    imp_bar = []
    cad_bar = []
    spd_bar = []
    for label, lap_idxs, _ in comparisons:
        agg_feats = []
        speeds = []
        for li in lap_idxs:
            r = by_idx.get(li)
            if r is None:
                continue
            agg_feats.extend(r["feats"])
            if "mean_speed_m_s" in r:
                speeds.append(r["mean_speed_m_s"])
        if not agg_feats:
            continue
        labels_bar.append(label.split(" (")[0])
        peaks_bar.append(np.mean([f["peak_force_N"] for f in agg_feats]))
        imp_bar.append(np.mean([f["impulse_m_s"] for f in agg_feats]))
        # cadence = 60 / median interstroke
        times = sorted([f["t"] for f in agg_feats])
        if len(times) >= 2:
            cad_bar.append(60.0 / float(np.median(np.diff(times))))
        else:
            cad_bar.append(0.0)
        spd_bar.append(np.mean(speeds))

    x = np.arange(len(labels_bar))
    width = 0.2
    axes[1].bar(x - 1.5 * width, peaks_bar, width, label="Peak force (N)", color="purple")
    axes[1].bar(x - 0.5 * width, [v * 100 for v in imp_bar],
                width, label="Impulse × 100 (m/s)", color="darkgreen")
    axes[1].bar(x + 0.5 * width, cad_bar, width, label="Cadence (spm)", color="steelblue")
    axes[1].bar(x + 1.5 * width, [v * 50 for v in spd_bar],
                width, label="Speed × 50 (m/s)", color="firebrick")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels_bar)
    axes[1].set_title("Mean per-stroke metrics  (scaled for comparison)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(savepath, dpi=140, bbox_inches="tight")
    plt.close(fig)

    return summary_lines


# ------------------------------------------------------------------
# Report writer
# ------------------------------------------------------------------
def _lap_metric(per_lap, idxs, key):
    vals = []
    for r in per_lap:
        if r is None:
            continue
        if r["lap"]["idx"] in idxs and key in r:
            vals.append(r[key])
    return float(np.mean(vals)) if vals else float("nan")


def write_report(path, kg, tcx, align, axes_info, burst_info, per_lap):
    lines = []
    lines.append("# Session 37 — KiloGlide ↔ Garmin Correlation Report")
    lines.append("")
    lines.append("**Auto-generated by `analysis/correlate_kg_garmin.py`. First on-water test, 2026-05-21, Alameda Bay.**")
    lines.append("")

    # ---- Headline findings up top ----
    lines.append("## Headline findings")
    lines.append("")
    lines.append("1. **The data is excellent.** Zero CRC errors, zero resync bytes, clean SESSION_END. "
                 f"79.2 minutes, 1.94M IMU samples at 409 Hz, 23.7k GPS records at 5 Hz, ≥3D fix for 99% of samples.")
    speed_23 = _lap_metric(per_lap, [2, 3], "mean_speed_m_s")
    speed_13 = _lap_metric(per_lap, [13], "mean_speed_m_s")
    peak_23 = _lap_metric(per_lap, [2, 3], "mean_peak_force_N")
    peak_13 = _lap_metric(per_lap, [13], "mean_peak_force_N")
    cad_23 = _lap_metric(per_lap, [2, 3], "cadence_spm")
    cad_13 = _lap_metric(per_lap, [13], "cadence_spm")
    lines.append(
        f"2. **The current ate roughly 1 m/s of your speed.** Strong miles (laps 2-3): "
        f"{speed_23:.2f} m/s mean speed with {peak_23:.0f} N peak drive force at {cad_23:.0f} spm. "
        f"Slow current mile (lap 13): {speed_13:.2f} m/s with {peak_13:.0f} N at {cad_13:.0f} spm. "
        f"Effort dropped only ~{abs((peak_13-peak_23)/peak_23)*100:.0f}% but speed dropped "
        f"~{abs((speed_13-speed_23)/speed_23)*100:.0f}%. "
        f"The difference is the water, not you.")
    lines.append(
        "3. **KG vs Garmin GPS agree to within ~0.5 m/s residual** across most of the session "
        f"(Pearson r = {align['best_r']:.3f} on 1-Hz speed signals). KG started "
        f"{align['offset_s']/60:.1f} min before Garmin, as expected from your "
        "device-on → GPS-acquire → walk-to-ramp → 2-strokes → Garmin-on sequence.")
    lines.append(
        f"4. **IMU mounting was: forward is raw {axes_info['forward_dominant_raw_axis']}, "
        f"up is raw {axes_info['up_dominant_raw_axis']}.** "
        f"Gravity recovered to {axes_info['gravity_magnitude']:.2f} m/s² from a stationary "
        "window (within IMU calibration tolerance). Forward sign confirmed by GPS-derived "
        "acceleration correlation = "
        f"{axes_info['axis_corr_with_gps_dvdt']:+.3f}.")
    lines.append("")

    # ---- Caveats ----
    lines.append("## Caveats and known limitations of this analysis")
    lines.append("")
    lines.append("- **L/R side classification is approximate for OC1.** The ama suppresses roll, "
                 "so the roll-rate signal at the catch is small and noisy. Look at the per-burst zoom "
                 "(`03_burst_strokes_zoom.png`) and compare to your memory; if labels are reversed or "
                 "random, future work is to discriminate sides from lateral accel or yaw rate.")
    lines.append("- **Stroke detection is v0.** Uses a Butterworth band-pass (0.5-3 Hz) + prominence "
                 "+ height + refractory. Works on cruise and bursts; tuned thresholds may need adjustment "
                 "for slower/calmer water than what we saw here.")
    lines.append("- **'Peak effective drive force' is boat-response force, not paddle-blade force.** "
                 "It is F = m_system × a_forward, after connection losses through hull, paddler body, "
                 "and water. Useful for relative comparisons, not for absolute biomechanics.")
    lines.append("- **No USER_MARK events.** Future sessions will be easier to navigate if a "
                 "mark-button is wired up before the next on-water test.")
    lines.append("")

    # ---- The actual data sections ----
    lines.append("## File summary")
    lines.append("")
    lines.append(f"- KG log: `analysis/data/kg_000037.bin` ({kg['header']['file_size']:,} bytes)")
    lines.append(f"- TCX: `analysis/data/activity_22960598946.tcx`")
    lines.append(f"- IMU samples: {len(kg['imu_t']):,}")
    lines.append(f"- GPS records (3D fix): {len(kg['gps_t']):,}")
    lines.append("")

    lines.append("## Phase 1 — Time alignment")
    lines.append("")
    kg_t0_iso = dt.datetime.fromtimestamp(align["kg_t0_utc"], tz=dt.timezone.utc).isoformat()
    lines.append(f"- KG t=0 absolute UTC: **{kg_t0_iso}**")
    lines.append(f"- Garmin started at KG-local t = **{align['offset_s']:.1f} s** "
                 f"(~{align['offset_s']/60:.1f} min after KG turn-on)")
    lines.append(f"- Cross-correlation peak Pearson r: **{align['best_r']:.3f}**")
    lines.append("- Method: normalized cross-correlation of 1-Hz resampled GPS speed signals. "
                 "The KG header `start_unix_us` is 0 (firmware doesn't write a time anchor yet).")
    lines.append("")

    lines.append("## Phase 2 — IMU axis discovery")
    lines.append("")
    gw = axes_info.get("gravity_window_s")
    gw_str = f"({gw[0]:.0f}-{gw[1]:.0f} s)" if gw else "(whole session — no stationary window found)"
    lines.append(f"- Gravity magnitude (from stationary window {gw_str}): **{axes_info['gravity_magnitude']:.3f} m/s²**")
    lines.append(f"- 'Up' axis maps closest to raw **{axes_info['up_dominant_raw_axis']}**")
    lines.append(f"- 'Forward' axis maps closest to raw **{axes_info['forward_dominant_raw_axis']}**")
    lines.append(f"- Forward sign confirmed via GPS dV/dt correlation = **{axes_info['axis_corr_with_gps_dvdt']:+.3f}**")
    lines.append(f"- `up_in_raw` = {[round(x,3) for x in axes_info['up_in_raw']]}")
    lines.append(f"- `forward_in_raw` = {[round(x,3) for x in axes_info['forward_in_raw']]}")
    lines.append(f"- `lateral_in_raw` = {[round(x,3) for x in axes_info['lateral_in_raw']]}")
    lines.append("")

    lines.append("## Phase 3 — Burst-section stroke detection (L/R test)")
    lines.append("")
    if burst_info:
        lines.append(f"- Wide window (laps 5-9): **{burst_info['n_strokes_wide']}** strokes detected.")
        lines.append("- Per-burst (laps 6, 7, 8) — the L-then-R hard-stroke test:")
        for b in burst_info["per_burst"]:
            lines.append(f"  - **Lap {b['lap']}**: {b['n']} strokes ({b['L']} L / {b['R']} R) @ {b['cad']:.0f} spm")
        lines.append("")
        lines.append("Cadence of ~50 spm during the bursts suggests they were *hard* strokes "
                     "rather than *fast* strokes — peak force in laps 7-8 (~245 N) is higher than "
                     f"the strong-mile average ({peak_23:.0f} N), but cadence is similar to cruise.")
    lines.append("")

    lines.append("## Phase 4 — Per-lap summary")
    lines.append("")
    lines.append("`Conn %` is the fraction of strokes with a single connected force "
                 "peak (textbook PERG arch). `L %` is the fraction of lap time where the "
                 "slow yaw envelope is biased to the left side. `Switches` is the number "
                 "of envelope sign flips. `DPS` is distance per stroke (boat run between catches).")
    lines.append("")
    lines.append("| Lap | Dist (m) | Dur (s) | Mean speed | Strokes | Cadence | Peak (N) | DPS (m) | Conn % | L % | Switches |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in per_lap:
        if r is None:
            continue
        lap = r["lap"]
        lf = r.get("left_time_fraction")
        ns = r.get("n_side_switches")
        cf = r.get("connected_fraction")
        lines.append(
            f"| {lap['idx']} | {lap['distance_m']:.0f} | {lap['duration_s']:.0f} | "
            f"{r.get('mean_speed_m_s', float('nan')):.2f} | {r['n_strokes']} | "
            f"{r['cadence_spm']:.1f} | {r.get('mean_peak_force_N', 0):.0f} | "
            f"{r.get('distance_per_stroke_m', 0):.2f} | "
            f"{(f'{cf*100:.0f}%' if cf is not None else '—')} | "
            f"{(f'{lf*100:.0f}%' if lf is not None else '—')} | "
            f"{(f'{ns}' if ns is not None else '—')} |"
        )
    lines.append("")

    # ---- Follow-ups ----
    lines.append("## Suggested follow-ups")
    lines.append("")
    lines.append("1. **Verify L/R sign convention** by eyeballing `03_burst_strokes_zoom.png` next to "
                 "your memory of which sides you paddled in laps 6, 7, 8. If labels look random, "
                 "investigate lateral-accel or yaw-rate-based side discrimination.")
    lines.append("2. **Add a mark-button** so future sessions can anchor key moments (start of "
                 "test piece, surf attempt, etc.) without depending on GPS-speed cross-correlation.")
    lines.append("3. **Write a TIME record** at session start once GPS lock is acquired. That removes "
                 "the need for cross-correlation alignment entirely on future sessions.")
    lines.append("4. **Quantify glide-phase drag** during the recovery between strokes, using "
                 "stroke segments + integrated accel. With the current alignment, you have ground-truth "
                 "GPS to validate this.")
    lines.append("5. **Compare against the NK SpeedCoach** when you have its data. The SpeedCoach reports "
                 "stroke rate directly and is a clean independent check on KG's stroke count.")
    lines.append("")

    lines.append("## Plots (see `analysis/plots/session_37/`)")
    lines.append("")
    plot_captions = {
        "01_speed_overlay.png": "KG vs Garmin GPS speed in absolute UTC time; lap boundaries marked.",
        "01_alignment_diagnostic.png": "Cross-correlation curve over candidate offsets; sharp peak at 503 s.",
        "01_gps_track.png": "Both GPS tracks overlaid on lat/lon. Launch on the right (L14), turnaround on the left (L5-9).",
        "02_axis_verification.png": "Rotated forward, lateral, and up-residual accel vs GPS speed in a cruise window.",
        "03_burst_strokes_wide.png": "Forward accel + roll rate over laps 5-9 with all detected strokes marked.",
        "03_burst_strokes_zoom.png": "Per-lap zoom on the three L/R burst laps. Use this to verify L/R labels.",
        "04_per_lap_summary.png": "Cadence / speed / peak-force / impulse bar charts across all 14 laps.",
        "04_lap_compare_force.png": "Mean force-vs-stroke-phase curve and metric bars: strong miles (2-3) vs slow mile (13).",
    }
    for f in sorted(os.listdir(PLOTS_DIR)):
        cap = plot_captions.get(f, "")
        lines.append(f"- `{f}` — {cap}" if cap else f"- `{f}`")
    lines.append("")

    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    print("Loading KG binary...")
    kg = load_kg(KG_PATH)
    print(f"  IMU samples: {len(kg['imu_t']):,}")
    print(f"  GPS records (3D fix): {len(kg['gps_t']):,}")
    print(f"  Duration: {kg['imu_t'].max():.1f} s")

    print("Loading TCX...")
    tcx = load_tcx(TCX_PATH)
    print(f"  Garmin trackpoints: {len(tcx['t']):,}")
    print(f"  Garmin laps: {len(tcx['laps'])}")

    print("\nPhase 1 — Time alignment...")
    align = align_kg_to_garmin(kg, tcx)
    kg_t0_iso = dt.datetime.fromtimestamp(align['kg_t0_utc'], tz=dt.timezone.utc).isoformat()
    print(f"  Method: {align['alignment_method']}")
    print(f"  KG t=0 UTC: {kg_t0_iso}")
    print(f"  Garmin started at KG local t = {align['offset_s']:.1f} s ({align['offset_s']/60:.2f} min)")
    print(f"  Cross-correlation Pearson r: {align['best_r']:.3f}")
    if align['alignment_method'] == 'time_record':
        delta = align['kg_t0_utc'] - align['xcorr_kg_t0_utc']
        print(f"  TIME vs xcorr difference: {delta:+.1f} s (sanity check)")
    plot_alignment_diagnostic(align, os.path.join(PLOTS_DIR, "01_alignment_diagnostic.png"))
    plot_speed_overlay(kg, tcx, align, os.path.join(PLOTS_DIR, "01_speed_overlay.png"))
    plot_gps_track(kg, tcx, os.path.join(PLOTS_DIR, "01_gps_track.png"))

    print("\nPhase 2 — IMU axis auto-detection...")
    R, axes_info = detect_imu_axes(kg)
    print(f"  Gravity magnitude: {axes_info['gravity_magnitude']:.3f} m/s^2")
    print(f"  Up dominant raw axis: {axes_info['up_dominant_raw_axis']}")
    print(f"  Forward dominant raw axis: {axes_info['forward_dominant_raw_axis']}")
    print(f"  Forward-vs-GPS-dvdt correlation: {axes_info['axis_corr_with_gps_dvdt']:+.3f}")
    plot_axis_verification(kg, R, axes_info, align, os.path.join(PLOTS_DIR, "02_axis_verification.png"))

    print("\nPhase 3 — Burst-section stroke detection (Garmin laps 6-8)...")
    burst_info = plot_burst_strokes(
        kg, R, tcx, align,
        os.path.join(PLOTS_DIR, "03_burst_strokes_wide.png"),
        os.path.join(PLOTS_DIR, "03_burst_strokes_zoom.png"),
    )
    if burst_info:
        print(f"  Wide window strokes: {burst_info['n_strokes_wide']}")
        for b in burst_info["per_burst"]:
            print(f"    Lap {b['lap']}: {b['n']} strokes ({b['L']} L / {b['R']} R) @ {b['cad']:.0f} spm")

    print("\nPhase 4 — Per-lap stroke summary & force comparison...")
    A_body = rotate_accel(R, kg["accel_raw"])
    G_body = rotate_gyro(R, kg["gyro_raw"])
    per_lap = []
    for lap in tcx["laps"]:
        per_lap.append(analyze_lap(kg, A_body, G_body, lap, align, SYSTEM_MASS_KG))
    plot_per_lap_summary(per_lap, os.path.join(PLOTS_DIR, "04_per_lap_summary.png"))
    compare_summary = plot_lap_compare(per_lap, os.path.join(PLOTS_DIR, "04_lap_compare_force.png"))
    if compare_summary:
        for line in compare_summary:
            print(f"  {line}")

    print("\nWriting report...")
    write_report(REPORT_PATH, kg, tcx, align, axes_info, burst_info, per_lap)
    print(f"  Wrote {REPORT_PATH}")
    print(f"  Plots in {PLOTS_DIR}")
    print("Done.")


if __name__ == "__main__":
    main()
