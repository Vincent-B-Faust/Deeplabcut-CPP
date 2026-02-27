from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from cpp_dlc_live.analysis.metrics import compute_speed_series, compute_summary
from cpp_dlc_live.analysis.plots import plot_occupancy, plot_speed, plot_trajectory
from cpp_dlc_live.utils.io_utils import load_yaml


def analyze_session(
    session_dir: Path,
    cm_per_px_override: Optional[float] = None,
    output_plots_override: Optional[bool] = None,
    logger: Optional[logging.Logger] = None,
) -> Path:
    logger = logger or logging.getLogger("cpp_dlc_live")
    session_dir = Path(session_dir)

    log_path = session_dir / "cpp_realtime_log.csv"
    if not log_path.exists():
        raise FileNotFoundError(f"Missing realtime log: {log_path}")

    config = {}
    config_path = session_dir / "config_used.yaml"
    if config_path.exists():
        config = load_yaml(config_path)

    analysis_cfg = config.get("analysis", {}) if isinstance(config, dict) else {}
    cm_per_px = cm_per_px_override if cm_per_px_override is not None else analysis_cfg.get("cm_per_px")
    output_plots = (
        output_plots_override
        if output_plots_override is not None
        else bool(analysis_cfg.get("output_plots", True))
    )

    df = pd.read_csv(log_path)
    summary = compute_summary(df, cm_per_px=cm_per_px)

    summary_path = session_dir / "summary.csv"
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    logger.info("Summary written: %s", summary_path)

    if output_plots:
        try:
            speed_df = compute_speed_series(df)
            roi_cfg = config.get("roi", {}) if isinstance(config, dict) else {}
            plot_trajectory(df, roi_cfg=roi_cfg, out_path=session_dir / "trajectory.png")
            plot_speed(speed_df, out_path=session_dir / "speed_over_time.png")
            plot_occupancy(df, out_path=session_dir / "occupancy_over_time.png")
            logger.info("Plots written under %s", session_dir)
        except Exception:
            logger.exception("Failed to generate plots")

    return summary_path
