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
    tcx_path: Optional[str]
    nk_path: Optional[str]
    plots_dir: str
    location: str
    boat: str
    system_mass_kg: float
    mount: str
    conditions: str
    notes: str
    summary_narrative: list


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
    tcx_path = os.path.join(DATA_DIR, s["garmin_tcx"]) if s.get("garmin_tcx") else None
    nk_path = os.path.join(DATA_DIR, s["nk_speedcoach"]) if s.get("nk_speedcoach") else None
    plots_dir = os.path.join(PLOTS_ROOT, f"session_{session_id}")
    os.makedirs(plots_dir, exist_ok=True)

    return SessionConfig(
        session_id=session_id,
        date=s["date"],
        kg_path=kg_path,
        tcx_path=tcx_path,
        nk_path=nk_path,
        plots_dir=plots_dir,
        location=s["location"],
        boat=s["boat"],
        system_mass_kg=float(s["system_mass_kg"]),
        mount=s["mount"],
        conditions=s["conditions"],
        notes=s["notes"],
        summary_narrative=s.get("summary_narrative", []),
    )


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
