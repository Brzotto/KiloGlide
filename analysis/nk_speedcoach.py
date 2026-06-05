"""
NK SpeedCoach CSV loader (general — works for any SpeedCoach GPS2 export).

The SpeedCoach CSV has several stacked sections:

    Session Information:   (device + start time, key:value pairs)
    Session Summary:       (one row of whole-session totals)
    Interval Summaries:    (one row per interval)
    Per-Stroke Data:       (one row PER STROKE — the useful part)

This module finds those sections by their headers (not by fixed line numbers,
so it survives firmware/format variations) and returns numpy arrays plus a
summary dict. It is the independent stroke-rate ground truth for validating
KG's stroke detection.

Units: the export may be in Miles/Speed or Metric. We read the unit columns
from the header and convert speed to m/s and distance to metres regardless.

Usage:
    from nk_speedcoach import load_nk
    nk = load_nk(path)
    nk["elapsed_s"], nk["speed_ms"], nk["stroke_rate_spm"], nk["total_strokes"]
    nk["summary"]["total_strokes"], nk["summary"]["avg_spm"]
"""

import csv

import numpy as np

MPH_TO_MS = 0.44704
KMH_TO_MS = 1.0 / 3.6


def _parse_hms(s):
    """Parse 'HH:MM:SS.t' (or 'MM:SS.t') into seconds. Returns nan on failure."""
    s = s.strip()
    if not s:
        return np.nan
    parts = s.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return np.nan
    sec = 0.0
    for p in parts:
        sec = sec * 60.0 + p
    return sec


def _speed_to_ms(value, unit_label):
    """Convert a speed in the file's units to m/s using the column unit label."""
    u = unit_label.upper()
    if "MPH" in u:
        return value * MPH_TO_MS
    if "KM/H" in u or "KPH" in u:
        return value * KMH_TO_MS
    if "M/S" in u:
        return value
    # Default assumption for NK "Miles/Speed" exports.
    return value * MPH_TO_MS


def _dist_to_m(value, unit_label):
    """Convert a distance in the file's units to metres using the unit label."""
    u = unit_label.upper()
    if "MILE" in u:
        return value * 1609.344
    if "FEET" in u or "FT" in u:
        return value * 0.3048
    if "KM" in u:
        return value * 1000.0
    if u.strip() in ("M", "METER", "METERS", "METRE", "METRES"):
        return value
    # Default assumption for NK "Miles/Speed" exports: distance miles, DPS feet.
    return value * 1609.344


def _find_section(rows, header_text):
    """Return the index of the first row whose first cell starts with header_text."""
    for i, r in enumerate(rows):
        if r and r[0].strip().lower().startswith(header_text.lower()):
            return i
    return None


def _column_map(header_row):
    """Map normalized column names to indices, for robust lookup by name."""
    out = {}
    for i, name in enumerate(header_row):
        out[name.strip().lower()] = i
    return out


def _get(colmap, *candidates):
    """Return the index of the first matching column name, or None."""
    for c in candidates:
        if c in colmap:
            return colmap[c]
    return None


def load_nk(path):
    """Load an NK SpeedCoach CSV. Returns a dict of per-stroke arrays + summary."""
    with open(path, "r", newline="") as f:
        rows = list(csv.reader(f))

    # --- Per-stroke data section ---
    sec = _find_section(rows, "Per-Stroke Data")
    if sec is None:
        raise RuntimeError("No 'Per-Stroke Data' section found in NK CSV")

    # Header is the next non-empty row; units row follows; data rows follow that.
    hdr_i = sec + 1
    while hdr_i < len(rows) and not any(c.strip() for c in rows[hdr_i]):
        hdr_i += 1
    header = rows[hdr_i]
    units = rows[hdr_i + 1] if hdr_i + 1 < len(rows) else [""] * len(header)
    colmap = _column_map(header)

    i_elapsed = _get(colmap, "elapsed time")
    i_speed = _get(colmap, "speed (gps)", "speed")
    i_rate = _get(colmap, "stroke rate")
    i_total = _get(colmap, "total strokes")
    i_lat = _get(colmap, "gps lat.", "gps lat")
    i_lon = _get(colmap, "gps lon.", "gps lon")
    i_dist = _get(colmap, "distance (gps)", "distance")
    i_dps = _get(colmap, "distance/stroke (gps)", "distance/stroke")
    speed_unit = units[i_speed] if i_speed is not None and i_speed < len(units) else "MPH"
    dist_unit = units[i_dist] if i_dist is not None and i_dist < len(units) else "Miles"
    dps_unit = units[i_dps] if i_dps is not None and i_dps < len(units) else "Feet"

    elapsed, speed, rate, total, lat, lon, dist, dps = ([] for _ in range(8))
    for r in rows[hdr_i + 2:]:
        if not r or not r[0].strip():
            break  # blank line ends the section
        # Data rows begin with an interval number; skip anything else.
        try:
            float(r[0])
        except ValueError:
            break
        try:
            elapsed.append(_parse_hms(r[i_elapsed]))
            speed.append(_speed_to_ms(float(r[i_speed]), speed_unit))
            rate.append(float(r[i_rate]))
            total.append(float(r[i_total]))
            lat.append(float(r[i_lat]) if i_lat is not None else np.nan)
            lon.append(float(r[i_lon]) if i_lon is not None else np.nan)
            dist.append(_dist_to_m(float(r[i_dist]), dist_unit) if i_dist is not None else np.nan)
            dps.append(_dist_to_m(float(r[i_dps]), dps_unit) if i_dps is not None else np.nan)
        except (ValueError, IndexError):
            continue

    # --- Session summary section (whole-session device-reported totals) ---
    summary = {}
    ssec = _find_section(rows, "Session Summary")
    if ssec is not None:
        s_hdr = ssec + 1
        while s_hdr < len(rows) and not any(c.strip() for c in rows[s_hdr]):
            s_hdr += 1
        s_map = _column_map(rows[s_hdr])
        s_units = rows[s_hdr + 1] if s_hdr + 1 < len(rows) else []
        s_data = rows[s_hdr + 2] if s_hdr + 2 < len(rows) else []

        def sval(idx, default=np.nan):
            try:
                return float(s_data[idx])
            except (ValueError, IndexError, TypeError):
                return default

        j_total = _get(s_map, "total strokes")
        j_rate = _get(s_map, "avg stroke rate")
        j_elapsed = _get(s_map, "total elapsed time")
        j_dist = _get(s_map, "total distance (gps)", "total distance")
        j_spd = _get(s_map, "avg speed (gps)", "avg speed")
        j_su = _get(s_map, "avg speed (gps)", "avg speed")
        summary["total_strokes"] = sval(j_total)
        summary["avg_spm"] = sval(j_rate)
        summary["elapsed_s"] = (_parse_hms(s_data[j_elapsed])
                                if j_elapsed is not None and j_elapsed < len(s_data) else np.nan)
        summary["distance_mi"] = sval(j_dist)
        avg_unit = (s_units[j_su] if j_su is not None and j_su < len(s_units) else "MPH")
        summary["avg_speed_ms"] = _speed_to_ms(sval(j_spd), avg_unit)

    # Device + start-time metadata (Session Information section).
    info = _find_section(rows, "Session Information")
    if info is not None:
        for r in rows[info:info + 10]:
            if r and r[0].strip().lower().startswith("start time"):
                summary["start_time"] = r[1].strip() if len(r) > 1 else ""

    return {
        "elapsed_s": np.array(elapsed, dtype=np.float64),
        "speed_ms": np.array(speed, dtype=np.float64),
        "stroke_rate_spm": np.array(rate, dtype=np.float64),
        "total_strokes": np.array(total, dtype=np.float64),
        "dist_m": np.array(dist, dtype=np.float64),
        "dps_m": np.array(dps, dtype=np.float64),
        "lat": np.array(lat, dtype=np.float64),
        "lon": np.array(lon, dtype=np.float64),
        "summary": summary,
    }
