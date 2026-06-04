"""Session configuration loader.

Reads analysis/data/sessions.json and returns paths + metadata for a session.

Usage in a script:
    from session_config import get_session
    cfg = get_session()              # default session from manifest
    cfg = get_session(38)            # specific session
    # Then use cfg.kg_path, cfg.tcx_path, cfg.plots_dir, cfg.system_mass_kg, etc.

Override the default via env var KG_SESSION (e.g. KG_SESSION=38 python script.py)
or by passing --session 38 if a script accepts CLI args.
"""
import argparse
import json
import os
from dataclasses import dataclass
from typing import Optional


ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ANALYSIS_DIR, "data")
PLOTS_ROOT = os.path.join(ANALYSIS_DIR, "plots")
MANIFEST_PATH = os.path.join(DATA_DIR, "sessions.json")


@dataclass
class SessionConfig:
    session_id: int
    date: str
    kg_path: str
    garmin_path: Optional[str]  # Garmin activity file (.fit or .tcx), whichever the manifest gives
    tcx_path: Optional[str]     # backward-compatible alias for garmin_path
    nk_path: Optional[str]
    plots_dir: str
    location: str
    boat: str
    system_mass_kg: float
    mount: str
    conditions: str
    notes: str
    summary_narrative: list
    compare_laps: list  # [{idx, label, color}, ...] for cross-lap comparison plots
    exclude_laps: list  # lap indices to drop from summaries (rests, anomalies)
    adaptive_strokes: bool  # gate-adaptive weak-stroke detection (off = legacy fixed threshold)


def _load_manifest():
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def get_session(session_id=None) -> SessionConfig:
    """Look up a session in the manifest. If session_id is None, use the
    default from the manifest (or KG_SESSION env var if set)."""
    manifest = _load_manifest()

    if session_id is None:
        env_val = os.environ.get("KG_SESSION")
        if env_val is not None:
            session_id = int(env_val)
        else:
            session_id = int(manifest["default_session"])

    key = str(session_id)
    if key not in manifest["sessions"]:
        available = sorted(manifest["sessions"].keys())
        raise KeyError(f"Session {session_id} not in manifest. Available: {available}")

    s = manifest["sessions"][key]
    kg_path = os.path.join(DATA_DIR, s["kg_file"])
    # Garmin activity: accept either a .fit ("garmin_fit") or .tcx ("garmin_tcx").
    garmin_file = s.get("garmin_fit") or s.get("garmin_tcx")
    garmin_path = os.path.join(DATA_DIR, garmin_file) if garmin_file else None
    nk_path = os.path.join(DATA_DIR, s["nk_speedcoach"]) if s.get("nk_speedcoach") else None
    plots_dir = os.path.join(PLOTS_ROOT, f"session_{session_id}")
    os.makedirs(plots_dir, exist_ok=True)

    return SessionConfig(
        session_id=session_id,
        date=s["date"],
        kg_path=kg_path,
        garmin_path=garmin_path,
        tcx_path=garmin_path,  # alias kept so existing callers using cfg.tcx_path still work
        nk_path=nk_path,
        plots_dir=plots_dir,
        location=s["location"],
        boat=s["boat"],
        system_mass_kg=float(s["system_mass_kg"]),
        mount=s["mount"],
        conditions=s["conditions"],
        notes=s["notes"],
        summary_narrative=s.get("summary_narrative", []),
        compare_laps=s.get("compare_laps", []),
        exclude_laps=s.get("exclude_laps", []),
        adaptive_strokes=bool(s.get("adaptive_strokes", False)),
    )


# Default fallback palette for auto-picked comparison laps.
_AUTO_COLORS = ["firebrick", "steelblue", "seagreen"]


def get_compare_laps(cfg, per_lap_stats=None):
    """Return list of comparison-lap dicts [{idx, label, color}, ...].

    Resolution order:
      1. cfg.compare_laps from sessions.json (if set)
      2. Auto-pick fastest cruise + slowest cruise + longest cruise from
         per_lap_stats (a dict mapping lap_idx -> {"n_strokes", "mean_speed_m_s"}).
         Cruise lap defined as n_strokes > 100.
      3. Empty list — caller renders no comparison panel.

    Caller is expected to handle empty list gracefully (skip the panel).
    """
    if cfg.compare_laps:
        return list(cfg.compare_laps)

    if not per_lap_stats:
        return []

    cruise = {li: s for li, s in per_lap_stats.items()
              if s.get("n_strokes", 0) > 100}
    if len(cruise) < 2:
        return []

    fastest = max(cruise, key=lambda li: cruise[li].get("mean_speed_m_s", 0))
    slowest = min(cruise, key=lambda li: cruise[li].get("mean_speed_m_s", 0))
    longest = max(cruise, key=lambda li: cruise[li].get("n_strokes", 0))

    picks, seen = [], set()
    role_color = [
        (fastest, "fastest cruise", _AUTO_COLORS[0]),
        (slowest, "slowest cruise", _AUTO_COLORS[1]),
        (longest, "longest cruise", _AUTO_COLORS[2]),
    ]
    for li, role, color in role_color:
        if li in seen:
            continue
        picks.append({"idx": li, "label": f"L{li} ({role})", "color": color})
        seen.add(li)
    return picks


def add_session_arg(parser: argparse.ArgumentParser):
    """Add a --session int argument to an existing ArgumentParser."""
    parser.add_argument("--session", type=int, default=None,
                        help="Session ID from sessions.json (default: manifest default)")


def get_session_from_args(argv=None) -> SessionConfig:
    """Convenience for scripts that only need --session and nothing else."""
    p = argparse.ArgumentParser()
    add_session_arg(p)
    args, _ = p.parse_known_args(argv)
    return get_session(args.session)
