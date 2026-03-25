from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import pandas as pd

from cpp_dlc_live.analysis.metrics import compute_speed_series, compute_summary, normalize_chamber_series
from cpp_dlc_live.analysis.plots import (
    plot_chamber_time_bars,
    plot_occupancy,
    plot_position_heatmap,
    plot_speed,
    plot_trajectory_speed_heatmap,
)
from cpp_dlc_live.realtime.roi import ChamberROI
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
    time_start_s: Optional[float] = None,
    time_end_s: Optional[float] = None,
    render_overlay_video: bool = False,
    overlay_video_source_override: Optional[Path] = None,
    overlay_video_filename_override: Optional[str] = None,
    output_dir_override: Optional[Path] = None,
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
    metadata = _load_metadata(session_dir=session_dir, logger=logger)

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
    logger.info("Analyze options: output_plots=%s fixed_fps_hz=%s cm_per_px=%s", output_plots, fixed_fps_hz, cm_per_px)

    df = pd.read_csv(log_path)
    if len(df) > 0:
        df = df.copy()
        df["chamber"] = normalize_chamber_series(df.get("chamber"), length=len(df))

    df, resolved_start_s, resolved_end_s = _filter_time_range(
        df=df,
        fixed_fps_hz=fixed_fps_hz,
        time_start_s=time_start_s,
        time_end_s=time_end_s,
        logger=logger,
    )

    output_dir = _resolve_analysis_output_dir(
        session_dir=session_dir,
        output_dir_override=output_dir_override,
        time_start_s=resolved_start_s,
        time_end_s=resolved_end_s,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = compute_summary(df, cm_per_px=cm_per_px, fixed_fps_hz=fixed_fps_hz)

    file_prefix = detect_session_file_prefix(session_dir)
    summary_name = ensure_prefixed_filename("summary.csv", file_prefix) if file_prefix else "summary.csv"
    summary_path = output_dir / summary_name
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    logger.info("Summary written: %s", summary_path)
    if fixed_fps_hz is not None:
        logger.info("Using fixed FPS for analysis: %.3f Hz", float(fixed_fps_hz))

    if output_plots:
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

        plot_targets = [
            ("figure1", output_dir / fig1_name),
            ("figure2", output_dir / fig2_name),
            ("figure3", output_dir / fig3_name),
            ("speed_over_time", output_dir / speed_name),
            ("occupancy_over_time", output_dir / occupancy_name),
        ]
        plot_failures: list[str] = []
        plots_written = 0

        for label, out_path in plot_targets:
            try:
                if label == "figure1":
                    plot_trajectory_speed_heatmap(
                        df=df,
                        speed_df=speed_df,
                        roi_cfg=roi_cfg,
                        out_path=out_path,
                        frame_shape=frame_shape,
                    )
                elif label == "figure2":
                    plot_position_heatmap(df=df, roi_cfg=roi_cfg, out_path=out_path, frame_shape=frame_shape)
                elif label == "figure3":
                    plot_chamber_time_bars(df=df, out_path=out_path, fixed_fps_hz=fixed_fps_hz)
                elif label == "speed_over_time":
                    plot_speed(speed_df, out_path=out_path)
                elif label == "occupancy_over_time":
                    plot_occupancy(df, out_path=out_path)
                if out_path.exists():
                    plots_written += 1
                logger.info("Plot written: %s", out_path)
            except Exception as exc:
                plot_failures.append(f"{label}: {type(exc).__name__}: {exc}")
                logger.exception("Failed to generate plot %s", label)

        logger.info("Plot generation finished: written=%d failed=%d", plots_written, len(plot_failures))
        if plot_failures:
            logger.error("Plot failures: %s", " | ".join(plot_failures))

    if render_overlay_video:
        try:
            overlay_path = render_session_overlay_video(
                session_dir=session_dir,
                df=df,
                config=config,
                metadata=metadata,
                source_video_override=overlay_video_source_override,
                output_filename_override=overlay_video_filename_override,
                output_dir_override=output_dir,
                logger=logger,
            )
            logger.info("Overlay video written: %s", overlay_path)
        except Exception:
            logger.exception("Failed to generate analysis overlay video")

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
    metadata = _load_metadata(session_dir=session_dir, logger=logger)
    if isinstance(metadata, dict):
        camera_meta = metadata.get("camera", {})
        if isinstance(camera_meta, dict):
            width = _coerce_optional_positive_int(camera_meta.get("width"))
            height = _coerce_optional_positive_int(camera_meta.get("height"))
            if width is not None and height is not None:
                return (width, height)

    camera_cfg = config.get("camera", {}) if isinstance(config, dict) else {}
    if isinstance(camera_cfg, dict):
        width = _coerce_optional_positive_int(camera_cfg.get("width"))
        height = _coerce_optional_positive_int(camera_cfg.get("height"))
        if width is not None and height is not None:
            return (width, height)
    return None


def render_session_overlay_video(
    session_dir: Path,
    df: Optional[pd.DataFrame] = None,
    config: Optional[dict] = None,
    metadata: Optional[dict] = None,
    source_video_override: Optional[Path] = None,
    output_filename_override: Optional[str] = None,
    output_dir_override: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> Path:
    logger = logger or logging.getLogger("cpp_dlc_live")
    session_dir = Path(session_dir)

    if df is None:
        log_path = resolve_session_file(session_dir, "cpp_realtime_log.csv")
        df = pd.read_csv(log_path)
    if config is None:
        config = {}
        cfg_path = resolve_session_file(session_dir, "config_used.yaml")
        if cfg_path.exists():
            config = load_yaml(cfg_path)
    if metadata is None:
        metadata = _load_metadata(session_dir=session_dir, logger=logger)
    if not isinstance(config, dict):
        config = {}
    if not isinstance(metadata, dict):
        metadata = {}

    source_path = _resolve_overlay_source_video(
        session_dir=session_dir,
        config=config,
        metadata=metadata,
        source_video_override=source_video_override,
    )
    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open source video for overlay: {source_path}")

    try:
        first_ok, first_frame = cap.read()
        if not first_ok or first_frame is None:
            raise RuntimeError(f"Source video has no readable frames: {source_path}")

        h, w = first_frame.shape[:2]
        fps = _resolve_overlay_output_fps(cap=cap, config=config, metadata=metadata)
        if fps <= 0:
            fps = 30.0

        file_prefix = detect_session_file_prefix(session_dir)
        out_name_raw = output_filename_override or "analysis_overlay.mp4"
        out_name = ensure_prefixed_filename(out_name_raw, file_prefix) if file_prefix else out_name_raw
        output_dir = Path(output_dir_override) if output_dir_override is not None else session_dir
        out_path = (output_dir / out_name) if not Path(out_name).is_absolute() else Path(out_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        writer = _open_overlay_writer(out_path=out_path, width=w, height=h, fps=fps)
        if writer is None:
            raise RuntimeError(f"Failed to open video writer for overlay output: {out_path}")

        try:
            roi = None
            try:
                roi_cfg = config.get("roi", {}) if isinstance(config, dict) else {}
                roi = ChamberROI.from_config(roi_cfg) if roi_cfg else None
            except Exception:
                logger.exception("Failed to build ROI for overlay video; proceeding without ROI draw")
                roi = None
            laser_mode_text = _resolve_laser_mode_overlay_text(config=config, metadata=metadata)

            t0 = _first_time_value(df)

            frame_i = 0
            last_target_frame: Optional[int] = None
            for _, row in df.iterrows():
                target_frame = _safe_int(row.get("frame_idx"))
                frame = None
                if target_frame is None:
                    frame = first_frame if frame_i == 0 else None
                    if frame_i > 0:
                        ok, frame = cap.read()
                        if not ok or frame is None:
                            break
                else:
                    if last_target_frame is None or target_frame != (last_target_frame + 1):
                        cap.set(cv2.CAP_PROP_POS_FRAMES, float(target_frame))
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        break
                    last_target_frame = target_frame
                frame_i += 1

                vis = frame.copy()
                if roi is not None:
                    vis = roi.draw(vis)

                x = _safe_float(row.get("x"))
                y = _safe_float(row.get("y"))
                p = _safe_float(row.get("p"))
                chamber = str(row.get("chamber", "unknown"))
                laser = int(round(_safe_float(row.get("laser_state"), default=0.0)))
                elapsed_s = _elapsed_from_row(row=row, t0=t0, frame_idx=int(_safe_float(row.get("frame_idx"), 0.0)), fps=fps)

                if np.isfinite(x) and np.isfinite(y):
                    cv2.circle(vis, (int(x), int(y)), 5, (255, 255, 255), -1)
                cv2.putText(vis, f"chamber: {chamber}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(vis, f"laser: {laser}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(vis, f"laser_mode: {laser_mode_text}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(vis, f"p: {p:.3f}", (10, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(
                    vis,
                    f"time: {_format_elapsed_hhmmss(elapsed_s)}",
                    (10, 136),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )
                writer.write(vis)
        finally:
            writer.release()
    finally:
        cap.release()

    return out_path


def _load_metadata(session_dir: Path, logger: logging.Logger) -> dict:
    metadata_path = resolve_session_file(session_dir, "metadata.json")
    if not metadata_path.exists():
        return {}
    try:
        with metadata_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
        if isinstance(metadata, dict):
            return metadata
    except Exception:
        logger.exception("Failed to read metadata: %s", metadata_path)
    return {}


def _resolve_overlay_source_video(
    session_dir: Path,
    config: dict,
    metadata: dict,
    source_video_override: Optional[Path],
) -> Path:
    if source_video_override is not None:
        p = Path(source_video_override)
        if not p.is_absolute():
            p = session_dir / p
        if p.exists():
            return p
        raise FileNotFoundError(f"Overlay source video override not found: {p}")

    raw_result = metadata.get("raw_recording_result", {})
    if isinstance(raw_result, dict):
        resolved = raw_result.get("resolved_path")
        if isinstance(resolved, str) and resolved.strip():
            p = Path(resolved)
            if p.exists():
                return p

    raw_cfg = config.get("raw_recording", {})
    if isinstance(raw_cfg, dict):
        filename = raw_cfg.get("filename")
        if isinstance(filename, str) and filename.strip():
            candidate = Path(filename)
            if not candidate.is_absolute():
                candidate = session_dir / candidate
            if candidate.exists():
                return candidate

    preview_result = metadata.get("preview_recording_result", {})
    if isinstance(preview_result, dict):
        resolved = preview_result.get("resolved_path")
        if isinstance(resolved, str) and resolved.strip():
            p = Path(resolved)
            if p.exists():
                return p

    preview_cfg = config.get("preview_recording", {})
    if isinstance(preview_cfg, dict):
        filename = preview_cfg.get("filename")
        if isinstance(filename, str) and filename.strip():
            candidate = Path(filename)
            if not candidate.is_absolute():
                candidate = session_dir / candidate
            if candidate.exists():
                return candidate

    cam_cfg = config.get("camera", {})
    if isinstance(cam_cfg, dict):
        source = cam_cfg.get("source")
        if isinstance(source, str) and source.strip():
            p = Path(source)
            if p.exists():
                return p
            candidate = session_dir / source
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        "No suitable source video found "
        "(raw_recording_result/raw_recording.filename/preview_recording_result/preview_recording.filename/camera.source)"
    )


def _resolve_overlay_output_fps(cap: cv2.VideoCapture, config: dict, metadata: dict) -> float:
    fixed_fps = config.get("fixed_fps")
    if fixed_fps is not None:
        fps = float(fixed_fps)
        if fps > 0:
            return fps

    raw_result = metadata.get("raw_recording_result", {})
    if isinstance(raw_result, dict):
        fps_actual = raw_result.get("fps_actual")
        if fps_actual is not None:
            fps = float(fps_actual)
            if fps > 0:
                return fps

    cam_cfg = config.get("camera", {})
    if isinstance(cam_cfg, dict):
        fps_target = cam_cfg.get("fps_target")
        if fps_target is not None:
            fps = float(fps_target)
            if fps > 0:
                return fps

    cap_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if cap_fps > 0:
        return cap_fps
    return 30.0


def _open_overlay_writer(out_path: Path, width: int, height: int, fps: float) -> Optional[cv2.VideoWriter]:
    ext = out_path.suffix.lower()
    codecs = ["MJPG", "XVID", "mp4v"] if ext == ".avi" else ["mp4v", "avc1", "MJPG"]
    for codec in codecs:
        writer = cv2.VideoWriter(
            str(out_path),
            cv2.VideoWriter_fourcc(*codec),
            float(fps),
            (int(width), int(height)),
        )
        if writer.isOpened():
            return writer
        writer.release()
    return None


def _safe_float(value: object, default: float = float("nan")) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: object) -> Optional[int]:
    try:
        if value is None:
            return None
        v = float(value)
        if not np.isfinite(v):
            return None
        if v < 0:
            return None
        return int(round(v))
    except Exception:
        return None


def _filter_time_range(
    df: pd.DataFrame,
    fixed_fps_hz: Optional[float],
    time_start_s: Optional[float],
    time_end_s: Optional[float],
    logger: logging.Logger,
) -> Tuple[pd.DataFrame, Optional[float], Optional[float]]:
    if time_start_s is None and time_end_s is None:
        return df, None, None

    start_s = float(time_start_s) if time_start_s is not None else 0.0
    end_s = float(time_end_s) if time_end_s is not None else None
    if start_s < 0:
        raise ValueError("time_start_s must be >= 0")
    if end_s is not None and end_s <= start_s:
        raise ValueError("time_end_s must be > time_start_s")

    elapsed = _elapsed_series(df=df, fixed_fps_hz=fixed_fps_hz)
    mask = elapsed >= start_s
    if end_s is not None:
        mask &= elapsed <= end_s
    filtered = df.loc[mask].copy()
    if filtered.empty:
        raise ValueError(
            f"No samples in requested time range: start={start_s:.3f}s end={('end' if end_s is None else f'{end_s:.3f}s')}"
        )
    logger.info(
        "Applied analysis time range: start=%.3fs end=%s kept=%d/%d",
        start_s,
        ("end" if end_s is None else f"{end_s:.3f}s"),
        len(filtered),
        len(df),
    )
    return filtered, start_s, end_s


def _elapsed_series(df: pd.DataFrame, fixed_fps_hz: Optional[float]) -> pd.Series:
    if len(df) == 0:
        return pd.Series([], dtype="float64")

    t = pd.to_numeric(df.get("t_wall"), errors="coerce")
    if t.notna().any():
        t0 = float(t.dropna().iloc[0])
        return (t - t0).astype(float)

    if fixed_fps_hz is not None and fixed_fps_hz > 0:
        frame_idx = pd.to_numeric(df.get("frame_idx"), errors="coerce")
        if frame_idx.notna().any():
            f0 = float(frame_idx.dropna().iloc[0])
            return ((frame_idx - f0) / float(fixed_fps_hz)).astype(float)

    return pd.Series(np.arange(len(df), dtype=float), index=df.index)


def _resolve_analysis_output_dir(
    session_dir: Path,
    output_dir_override: Optional[Path],
    time_start_s: Optional[float],
    time_end_s: Optional[float],
) -> Path:
    if output_dir_override is not None:
        return Path(output_dir_override)
    if time_start_s is None and time_end_s is None:
        return session_dir
    suffix = _format_time_range_suffix(time_start_s, time_end_s)
    return session_dir / f"analysis_range_{suffix}"


def _format_time_range_suffix(start_s: Optional[float], end_s: Optional[float]) -> str:
    def _fmt(v: Optional[float]) -> str:
        if v is None:
            return "end"
        fv = float(v)
        if fv.is_integer():
            return f"{int(fv)}s"
        return f"{fv:.3f}".rstrip("0").rstrip(".").replace(".", "p") + "s"

    return f"{_fmt(start_s)}_to_{_fmt(end_s)}"


def _resolve_laser_mode_overlay_text(config: dict, metadata: dict) -> str:
    laser_cfg = config.get("laser_control", {}) if isinstance(config, dict) else {}
    if not isinstance(laser_cfg, dict):
        laser_cfg = {}
    if not laser_cfg and isinstance(metadata, dict):
        daq = metadata.get("daq", {})
        if isinstance(daq, dict):
            laser_cfg = daq

    mode_raw = str(laser_cfg.get("mode", "dryrun")).strip().lower()
    if mode_raw in {"continuous", "continues", "level"}:
        return "continuous"
    if mode_raw in {"pulse", "gated", "startstop"}:
        freq = _coerce_optional_positive_float(laser_cfg.get("freq_hz"), field_name="laser_control.freq_hz")
        if freq is None:
            return "pulse"
        return f"pulse {float(freq):.1f}Hz"
    return mode_raw or "unknown"


def _first_time_value(df: pd.DataFrame) -> Optional[float]:
    if "t_wall" not in df.columns or df.empty:
        return None
    values = pd.to_numeric(df["t_wall"], errors="coerce").to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(finite[0])


def _elapsed_from_row(row: pd.Series, t0: Optional[float], frame_idx: int, fps: float) -> float:
    t = _safe_float(row.get("t_wall"))
    if t0 is not None and np.isfinite(t):
        return max(0.0, float(t - t0))
    if fps > 0:
        return max(0.0, float(frame_idx) / float(fps))
    return 0.0


def _format_elapsed_hhmmss(seconds: float) -> str:
    safe = max(0.0, float(seconds))
    total_ms = int(safe * 1000.0)
    hours = total_ms // (3600 * 1000)
    minutes = (total_ms % (3600 * 1000)) // (60 * 1000)
    secs = (total_ms % (60 * 1000)) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
