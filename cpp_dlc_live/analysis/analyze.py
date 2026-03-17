from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from cpp_dlc_live.analysis.metrics import compute_speed_series, compute_summary
from cpp_dlc_live.analysis.plots import plot_occupancy, plot_speed, plot_trajectory
from cpp_dlc_live.utils.io_utils import (
    detect_session_file_prefix,
    ensure_prefixed_filename,
    load_yaml,
    resolve_session_file,
)


def analyze_session(
    session_dir: Path,
    cm_per_px_override: Optional[float] = None,
    fixed_fps_hz_override: Optional[float] = None,
    output_plots_override: Optional[bool] = None,
    logger: Optional[logging.Logger] = None,
) -> Path:
    logger = logger or logging.getLogger("cpp_dlc_live")
    session_dir = Path(session_dir)

    log_path = resolve_session_file(session_dir, "cpp_realtime_log.csv")
    if not log_path.exists():
        raise FileNotFoundError(f"Missing realtime log: {log_path}")

    config = {}
    config_path = resolve_session_file(session_dir, "config_used.yaml")
    if config_path.exists():
        config = load_yaml(config_path)

    analysis_cfg = config.get("analysis", {}) if isinstance(config, dict) else {}
    global_fixed_fps = _coerce_optional_positive_float(
        (config.get("fixed_fps") if isinstance(config, dict) else None),
        field_name="fixed_fps",
    )
    cm_per_px = cm_per_px_override if cm_per_px_override is not None else analysis_cfg.get("cm_per_px")
    analysis_fixed_fps_hz = _coerce_optional_positive_float(
        analysis_cfg.get("fixed_fps_hz"),
        field_name="analysis.fixed_fps_hz",
    )
    fixed_fps_hz = (
        _coerce_optional_positive_float(fixed_fps_hz_override, field_name="fixed_fps override")
        if fixed_fps_hz_override is not None
        # Priority: CLI override > global fixed_fps > legacy analysis.fixed_fps_hz.
        else (global_fixed_fps if global_fixed_fps is not None else analysis_fixed_fps_hz)
    )
    output_plots = (
        output_plots_override
        if output_plots_override is not None
        else bool(analysis_cfg.get("output_plots", True))
    )

    df = pd.read_csv(log_path)
    summary = compute_summary(df, cm_per_px=cm_per_px, fixed_fps_hz=fixed_fps_hz)

    file_prefix = detect_session_file_prefix(session_dir)
    summary_name = ensure_prefixed_filename("summary.csv", file_prefix) if file_prefix else "summary.csv"
    summary_path = session_dir / summary_name
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    logger.info("Summary written: %s", summary_path)
    if fixed_fps_hz is not None:
        logger.info("Using fixed FPS for analysis: %.3f Hz", float(fixed_fps_hz))

    if output_plots:
        try:
            speed_df = compute_speed_series(df, fixed_fps_hz=fixed_fps_hz)
            roi_cfg = config.get("roi", {}) if isinstance(config, dict) else {}
            trajectory_name = (
                ensure_prefixed_filename("trajectory.png", file_prefix) if file_prefix else "trajectory.png"
            )
            speed_name = (
                ensure_prefixed_filename("speed_over_time.png", file_prefix)
                if file_prefix
                else "speed_over_time.png"
            )
            occupancy_name = (
                ensure_prefixed_filename("occupancy_over_time.png", file_prefix)
                if file_prefix
                else "occupancy_over_time.png"
            )
            plot_trajectory(df, roi_cfg=roi_cfg, out_path=session_dir / trajectory_name)
            plot_speed(speed_df, out_path=session_dir / speed_name)
            plot_occupancy(df, out_path=session_dir / occupancy_name)
            logger.info("Plots written under %s", session_dir)
        except Exception:
            logger.exception("Failed to generate plots")

    return summary_path


def _coerce_optional_positive_float(value: object, field_name: str) -> Optional[float]:
    if value is None:
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return parsed
