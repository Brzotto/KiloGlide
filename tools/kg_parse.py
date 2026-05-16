"""KiloGlide binary log parser — v1 format."""

import struct
import sys
import os
import math
from collections import defaultdict

MAGIC = 0x474C494B
SYNC = 0xAA55
HEADER_FMT = "<I H H I Q 12s"  # 32 bytes
RECORD_HDR_FMT = "<H B B I"     # 8 bytes: sync, type, length, timestamp

IMU_FMT = "<hhhhhh"    # 12 bytes
GPS_FMT = "<iiiI H BB H H"  # 24 bytes
EVENT_FMT = "<B"        # 1 byte
BATT_FMT = "<HBB"       # 4 bytes
TIME_FMT = "<IQ"         # 12 bytes

ACCEL_SCALE = 0.000488 * 9.80665   # LSB -> m/s^2
GYRO_SCALE = 0.070 * 3.14159265 / 180.0  # LSB -> rad/s

EVENT_NAMES = {1: "SESSION_START", 2: "SESSION_END", 3: "USER_MARK",
               4: "GPS_FIX_LOST", 5: "GPS_FIX_FOUND"}
REC_NAMES = {1: "IMU", 2: "GPS", 3: "EVENT", 4: "BATTERY", 5: "TIME"}

# Timestamps above this are likely underflow from the backward interpolation
# bug in writeImu (first batch: nowMs is small, count*dt is larger, u32 wraps)
TS_MAX_PLAUSIBLE = 86400000   # 24 hours in ms — no session is this long

def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def parse_file(path):
    with open(path, "rb") as f:
        raw = f.read()

    if len(raw) < 32:
        return None, f"File too small ({len(raw)} bytes)"

    # Parse header
    hdr = struct.unpack(HEADER_FMT, raw[:32])
    magic, version, hw_id, session_id, start_unix_us, reserved = hdr

    if magic != MAGIC:
        return None, f"Bad magic: {magic:#010x}"
    if version != 1:
        return None, f"Unsupported version: {version}"

    header_info = {
        "session_id": session_id,
        "version": version,
        "hardware_id": hw_id,
        "start_unix_us": start_unix_us,
        "file_size": len(raw),
    }

    records = {"imu": [], "gps": [], "events": [], "battery": [], "time": []}
    stats = {"total_records": 0, "crc_errors": 0, "resync_bytes": 0,
             "unknown_types": 0, "imu_ts_underflow": 0}

    pos = 32
    while pos + 8 <= len(raw):
        # Look for sync
        sync_val = struct.unpack_from("<H", raw, pos)[0]
        if sync_val != SYNC:
            stats["resync_bytes"] += 1
            pos += 1
            continue

        # Read record header
        sync, rtype, length, ts = struct.unpack_from(RECORD_HDR_FMT, raw, pos)

        # Check we have enough data for payload + crc
        if pos + 8 + length + 1 > len(raw):
            break

        payload = raw[pos + 8 : pos + 8 + length]
        crc_byte = raw[pos + 8 + length]

        # Verify CRC over [type, length, timestamp, payload]
        crc_data = raw[pos + 2 : pos + 8 + length]  # skip sync (2 bytes)
        expected_crc = crc8(crc_data)

        if crc_byte != expected_crc:
            stats["crc_errors"] += 1
            pos += 1
            continue

        stats["total_records"] += 1

        if rtype == 1 and length == 12:  # IMU
            ax, ay, az, gx, gy, gz = struct.unpack(IMU_FMT, payload)
            # Filter timestamp underflow from backward interpolation bug
            if ts > TS_MAX_PLAUSIBLE:
                stats["imu_ts_underflow"] += 1
                ts = 0  # clamp to session start
            records["imu"].append({
                "ts": ts,
                "ax": ax, "ay": ay, "az": az,
                "gx": gx, "gy": gy, "gz": gz,
            })
        elif rtype == 2 and length == 24:  # GPS
            lat, lon, alt_mm, speed_mm_s, heading_cd, fix_type, num_sats, hdop_c, _ = \
                struct.unpack(GPS_FMT, payload)
            records["gps"].append({
                "ts": ts,
                "lat": lat / 1e7, "lon": lon / 1e7,
                "alt_m": alt_mm / 1000.0,
                "speed_m_s": speed_mm_s / 1000.0,
                "heading_deg": heading_cd / 100.0,
                "fix_type": fix_type, "num_sats": num_sats,
                "hdop": hdop_c / 100.0,
            })
        elif rtype == 3 and length == 1:  # Event
            code = struct.unpack(EVENT_FMT, payload)[0]
            records["events"].append({
                "ts": ts,
                "code": code,
                "name": EVENT_NAMES.get(code, f"UNKNOWN({code})"),
            })
        elif rtype == 4 and length == 4:  # Battery
            voltage_mv, percent, charging = struct.unpack(BATT_FMT, payload)
            records["battery"].append({
                "ts": ts,
                "voltage_mv": voltage_mv,
                "percent": percent,
                "charging": charging,
            })
        elif rtype == 5 and length == 12:  # Time
            local_ms, unix_us = struct.unpack(TIME_FMT, payload)
            records["time"].append({
                "ts": ts,
                "local_ms": local_ms,
                "unix_us": unix_us,
            })
        else:
            stats["unknown_types"] += 1

        pos += 8 + length + 1

    return {"header": header_info, "records": records, "stats": stats}, None


def print_summary(path):
    fname = os.path.basename(path)
    result, err = parse_file(path)

    if err:
        print(f"\n{'='*60}")
        print(f"  {fname}: ERROR - {err}")
        return result

    h = result["header"]
    r = result["records"]
    s = result["stats"]

    imu_count = len(r["imu"])
    gps_count = len(r["gps"])
    events = r["events"]
    marks = [e for e in events if e["code"] == 3]

    # Session duration from events (most reliable)
    start_evt = [e for e in events if e["code"] == 1]
    end_evt = [e for e in events if e["code"] == 2]
    if start_evt and end_evt:
        duration_s = (end_evt[-1]["ts"] - start_evt[0]["ts"]) / 1000.0
    elif imu_count > 1:
        # Use valid IMU timestamps (skip underflowed ones)
        valid_ts = [s_rec["ts"] for s_rec in r["imu"] if s_rec["ts"] <= TS_MAX_PLAUSIBLE]
        if len(valid_ts) > 1:
            duration_s = (max(valid_ts) - min(valid_ts)) / 1000.0
        else:
            duration_s = 0
    else:
        duration_s = 0

    # IMU rate from valid timestamps
    valid_imu_ts = [s_rec["ts"] for s_rec in r["imu"] if s_rec["ts"] <= TS_MAX_PLAUSIBLE and s_rec["ts"] > 0]
    imu_rate = 0
    if len(valid_imu_ts) > 1:
        imu_span = (max(valid_imu_ts) - min(valid_imu_ts)) / 1000.0
        if imu_span > 0:
            imu_rate = len(valid_imu_ts) / imu_span

    # GPS rate
    gps_rate = 0
    if gps_count >= 2:
        gps_dur = (r["gps"][-1]["ts"] - r["gps"][0]["ts"]) / 1000.0
        gps_rate = gps_count / gps_dur if gps_dur > 0 else 0

    # Accel stats (magnitude)
    if imu_count > 0:
        accel_mags = []
        for s_rec in r["imu"]:
            ax = s_rec["ax"] * ACCEL_SCALE
            ay = s_rec["ay"] * ACCEL_SCALE
            az = s_rec["az"] * ACCEL_SCALE
            accel_mags.append(math.sqrt(ax*ax + ay*ay + az*az))
        accel_mean = sum(accel_mags) / len(accel_mags)
        accel_max = max(accel_mags)
        accel_min = min(accel_mags)
    else:
        accel_mean = accel_max = accel_min = 0

    # GPS speed stats
    if gps_count > 0:
        speeds = [g["speed_m_s"] for g in r["gps"]]
        speed_max = max(speeds)
        speed_mean = sum(speeds) / len(speeds)
        lats = [g["lat"] for g in r["gps"] if g["fix_type"] >= 2]
        lons = [g["lon"] for g in r["gps"] if g["fix_type"] >= 2]
        fix_types = [g["fix_type"] for g in r["gps"]]
        sats = [g["num_sats"] for g in r["gps"]]
    else:
        speeds = []
        speed_max = speed_mean = 0
        lats = lons = []
        fix_types = []
        sats = []

    has_clean_end = any(e["code"] == 2 for e in events)

    print(f"\n{'='*60}")
    print(f"  Session {h['session_id']}  ({fname})")
    print(f"{'='*60}")
    print(f"  File size:       {h['file_size']:,} bytes")
    print(f"  Duration:        {duration_s:.1f} s ({duration_s/60:.1f} min)")
    print(f"  Clean end:       {'YES' if has_clean_end else 'NO (missing SESSION_END)'}")
    print(f"  CRC errors:      {s['crc_errors']}")
    print(f"  Resync bytes:    {s['resync_bytes']}")
    print(f"  TS underflows:   {s['imu_ts_underflow']}")
    print()
    print(f"  IMU records:     {imu_count:,}  ({imu_rate:.0f} Hz effective)")
    print(f"  Accel |g|:       mean={accel_mean:.2f}  min={accel_min:.2f}  max={accel_max:.2f} m/s^2")
    print()
    print(f"  GPS records:     {gps_count:,}  ({gps_rate:.1f} Hz effective)")
    if gps_count > 0:
        fix_counts = defaultdict(int)
        for ft in fix_types:
            fix_counts[ft] += 1
        fix_str = ", ".join(f"{'3D' if k==3 else '2D' if k==2 else 'none'}={v}"
                           for k, v in sorted(fix_counts.items()))
        print(f"  Fix types:       {fix_str}")
        if sats:
            print(f"  Satellites:      min={min(sats)}  max={max(sats)}  mean={sum(sats)/len(sats):.0f}")
        print(f"  Speed:           mean={speed_mean:.2f}  max={speed_max:.2f} m/s ({speed_max*3.6:.1f} km/h)")
        if lats:
            print(f"  Position:        lat=[{min(lats):.6f}, {max(lats):.6f}]")
            print(f"                   lon=[{min(lons):.6f}, {max(lons):.6f}]")
    else:
        print(f"  (no GPS data)")
    print()
    print(f"  Events:")
    for e in events:
        t = e["ts"] / 1000.0
        print(f"    {t:8.1f}s  {e['name']}")
    if marks:
        print(f"\n  User marks: {len(marks)}")
        for i, m in enumerate(marks):
            print(f"    #{i+1}  @ {m['ts']/1000.0:.1f}s into session")

    return result


if __name__ == "__main__":
    files = sys.argv[1:]
    if not files:
        files = sorted([f for f in os.listdir(".") if f.startswith("kg_") and f.endswith(".bin")])

    for f in files:
        print_summary(f)
    print()
