from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from cpp_dlc_live.analysis.metrics import compute_speed_series, compute_summary
from cpp_dlc_live.analysis.plots import (
    plot_chamber_time_bars,
    plot_occupancy,
    plot_position_heatmap,
    plot_speed,
    plot_trajectory_speed_heatmap,
)
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
            frame_shape = _resolve_frame_shape(session_dir=session_dir, config=config, logger=logger)
            fig1_name = (
                ensure_prefixed_filename("figure1_trajectory_speed_heatmap.png", file_prefix)
                if file_prefix
                else "figure1_trajectory_speed_heatmap.png"
            )
            fig2_name = (
                ensure_prefixed_filename("figure2_position_heatmap.png", file_prefix)
                if file_prefix
                else "figure2_position_heatmap.png"
            )
            fig3_name = (
                ensure_prefixed_filename("figure3_chamber_dwell.png", file_prefix)
                if file_prefix
                else "figure3_chamber_dwell.png"
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
            plot_trajectory_speed_heatmap(
                df=df,
                speed_df=speed_df,
                roi_cfg=roi_cfg,
                out_path=session_dir / fig1_name,
                frame_shape=frame_shape,
            )
            plot_position_heatmap(df=df, roi_cfg=roi_cfg, out_path=session_dir / fig2_name, frame_shape=frame_shape)
            plot_chamber_time_bars(df=df, out_path=session_dir / fig3_name, fixed_fps_hz=fixed_fps_hz)
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


def _coerce_optional_positive_int(value: object) -> Optional[int]:
    if value is None:
        return None
    parsed = int(value)
    if parsed <= 0:
        return None
    return parsed


def _resolve_frame_shape(
    session_dir: Path,
    config: dict,
    logger: logging.Logger,
) -> Optional[Tuple[int, int]]:
    metadata_path = resolve_session_file(session_dir, "metadata.json")
    if metadata_path.exists():
        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                metadata = json.load(f)
            if isinstance(metadata, dict):
                camera_meta = metadata.get("camera", {})
                if isinstance(camera_meta, dict):
                    width = _coerce_optional_positive_int(camera_meta.get("width"))
                    height = _coerce_optional_positive_int(camera_meta.get("height"))
                    if width is not None and height is not None:
                        return (width, height)
        except Exception:
            logger.exception("Failed to read metadata for plot frame size: %s", metadata_path)

    camera_cfg = config.get("camera", {}) if isinstance(config, dict) else {}
    if isinstance(camera_cfg, dict):
        width = _coerce_optional_positive_int(camera_cfg.get("width"))
        height = _coerce_optional_positive_int(camera_cfg.get("height"))
        if width is not None and height is not None:
            return (width, height)
    return None
