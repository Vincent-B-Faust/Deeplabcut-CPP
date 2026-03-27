from __future__ import annotations

import logging
import math
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set, Tuple, Union

import cv2
import numpy as np

from cpp_dlc_live.realtime.camera import CameraConfig, CameraStream
from cpp_dlc_live.realtime.controller_base import LaserControllerBase
from cpp_dlc_live.realtime.controller_ni import DryRunLaserController, LaserControllerError, create_laser_controller
from cpp_dlc_live.realtime.debounce import Debouncer
from cpp_dlc_live.realtime.dlc_runtime import RuntimeBase, build_runtime
from cpp_dlc_live.realtime.issue_logger import SessionIssueLogger
from cpp_dlc_live.realtime.recorder import CSVRecorder
from cpp_dlc_live.realtime.roi import ChamberROI
from cpp_dlc_live.utils.io_utils import ensure_prefixed_filename, file_sha256, save_json
from cpp_dlc_live.utils.time_utils import utc_now_iso

_VALID_LASER_ON_CHAMBERS = {"chamber1", "chamber2", "neutral"}
_LASER_ON_CHAMBER_ALIASES = {
    "ch1": "chamber1",
    "1": "chamber1",
    "ch2": "chamber2",
    "2": "chamber2",
    "center": "neutral",
    "centre": "neutral",
    "none": "none",
    "off": "none",
    "disabled": "none",
    "disable": "none",
    "no": "none",
    "0": "none",
}


class RealtimeApp:
    def __init__(
        self,
        config: Dict[str, Any],
        session_dir: Path,
        duration_s: Optional[float] = None,
        camera_source_override: Optional[Union[int, str]] = None,
        preview: bool = True,
        offline_fast: bool = False,
        file_prefix: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = config
        self.session_dir = Path(session_dir)
        self.duration_s = duration_s
        self.camera_source_override = camera_source_override
        self.preview = preview
        self.offline_fast = bool(offline_fast)
        project_cfg = config.get("project", {}) if isinstance(config.get("project", {}), dict) else {}
        self.file_prefix = str(file_prefix or project_cfg.get("resolved_file_prefix") or "session")
        self.logger = logger or logging.getLogger("cpp_dlc_live")
        self._eof_is_normal_stop = False

    def run(self) -> int:
        camera: Optional[CameraStream] = None
        runtime: Optional[RuntimeBase] = None
        roi: Optional[ChamberROI] = None
        controller: Optional[LaserControllerBase] = None
        recorder: Optional[CSVRecorder] = None
        issue_logger: Optional[SessionIssueLogger] = None
        preview_writer: Optional[cv2.VideoWriter] = None
        raw_writer: Optional[cv2.VideoWriter] = None

        frame_idx = 0
        processed_frames = 0
        low_confidence_frames = 0
        chamber_transition_count = 0
        laser_transition_count = 0
        warning_count = 0
        preview_frames_written = 0
        preview_writer_opened = False
        preview_video_path: Optional[Path] = None
        raw_frames_written = 0
        raw_writer_opened = False
        raw_video_path: Optional[Path] = None
        last_context: Dict[str, Any] = {}
        previous_chamber = "unknown"
        previous_laser_state = 0

        status_code = 0
        setup_start_wall = time.time()
        setup_start_monotonic = time.monotonic()
        # Will be reset right before entering the realtime loop so init time is excluded.
        experiment_start_wall = setup_start_wall
        experiment_start_monotonic = setup_start_monotonic

        metadata: Dict[str, Any] = {
            "start_time_utc": utc_now_iso(),
            "start_wall": experiment_start_wall,
            "setup_start_wall": setup_start_wall,
            "session_dir": str(self.session_dir),
            "config": self.config,
            "file_prefix": self.file_prefix,
        }
        acclimation_enabled, acclimation_duration_s = _resolve_acclimation_config(self.config)
        metadata["acclimation"] = {
            "enabled": acclimation_enabled,
            "duration_s": acclimation_duration_s,
            "actual_duration_s": 0.0,
        }
        cfg_used = self.session_dir / self._prefixed_filename("config_used.yaml")
        if not cfg_used.exists():
            cfg_used = self.session_dir / "config_used.yaml"
        if cfg_used.exists():
            metadata["config_copy"] = str(cfg_used)
            metadata["config_sha256"] = file_sha256(cfg_used)

        raw_runtime_log_cfg = self.config.get("runtime_logging", {})
        runtime_log_cfg = dict(raw_runtime_log_cfg) if isinstance(raw_runtime_log_cfg, dict) else {}
        issue_enabled = bool(runtime_log_cfg.get("enabled", True))
        issue_events_file = ensure_prefixed_filename(
            str(runtime_log_cfg.get("issue_events_file", "issue_events.jsonl")),
            self.file_prefix,
        )
        heartbeat_interval_s = max(0.0, float(runtime_log_cfg.get("heartbeat_interval_s", 5.0)))
        low_conf_warn_every_n = max(1, int(runtime_log_cfg.get("low_conf_warn_every_n", 30)))
        inference_warn_ms = float(runtime_log_cfg.get("inference_warn_ms", 80.0))
        fps_warn_below = float(runtime_log_cfg.get("fps_warn_below", 10.0))
        metadata["runtime_logging"] = {
            "enabled": issue_enabled,
            "issue_events_file": issue_events_file,
            "heartbeat_interval_s": heartbeat_interval_s,
            "low_conf_warn_every_n": low_conf_warn_every_n,
            "inference_warn_ms": inference_warn_ms,
            "fps_warn_below": fps_warn_below,
        }
        # Global fixed FPS: one knob to enforce a single cadence across runtime and recording.
        fixed_fps = _optional_float(self.config.get("fixed_fps"))
        if fixed_fps is not None and fixed_fps <= 0:
            raise ValueError("fixed_fps must be > 0")
        metadata["fixed_fps"] = fixed_fps

        raw_preview_record_cfg = self.config.get("preview_recording", {})
        preview_record_cfg = (
            dict(raw_preview_record_cfg)
            if isinstance(raw_preview_record_cfg, dict)
            else {}
        )
        preview_record_requested = bool(preview_record_cfg.get("enabled", False))
        preview_record_enabled = preview_record_requested
        preview_filename = ensure_prefixed_filename(
            str(preview_record_cfg.get("filename", "preview_overlay.mp4")),
            self.file_prefix,
        )
        preview_codec_raw = str(preview_record_cfg.get("codec", "mp4v")).strip()
        preview_codec = preview_codec_raw if len(preview_codec_raw) == 4 else "mp4v"
        preview_fps_override = _optional_float(preview_record_cfg.get("fps"))
        preview_overlay = bool(preview_record_cfg.get("overlay", True))
        metadata["preview_recording"] = {
            "enabled_requested": preview_record_requested,
            "filename": preview_filename,
            "codec": preview_codec,
            "fps_override": preview_fps_override,
            "overlay": preview_overlay,
        }
        if preview_codec != preview_codec_raw:
            self.logger.warning(
                "Invalid preview_recording.codec=%r, fallback to 'mp4v'",
                preview_codec_raw,
            )

        raw_record_cfg_raw = self.config.get("raw_recording", {})
        raw_record_cfg = dict(raw_record_cfg_raw) if isinstance(raw_record_cfg_raw, dict) else {}
        raw_record_requested = bool(raw_record_cfg.get("enabled", False))
        raw_record_enabled = raw_record_requested
        raw_filename = ensure_prefixed_filename(
            str(raw_record_cfg.get("filename", "raw_video.mp4")),
            self.file_prefix,
        )
        raw_codec_raw = str(raw_record_cfg.get("codec", "mp4v")).strip()
        raw_codec = raw_codec_raw if len(raw_codec_raw) == 4 else "mp4v"
        raw_fps_override = _optional_float(raw_record_cfg.get("fps"))
        metadata["raw_recording"] = {
            "enabled_requested": raw_record_requested,
            "filename": raw_filename,
            "codec": raw_codec,
            "fps_override": raw_fps_override,
        }
        if raw_codec != raw_codec_raw:
            self.logger.warning(
                "Invalid raw_recording.codec=%r, fallback to 'mp4v'",
                raw_codec_raw,
            )

        try:
            issue_logger = SessionIssueLogger(self.session_dir / issue_events_file, enabled=issue_enabled)
        except Exception:
            self.logger.exception("Failed to initialize structured issue logger, continuing without it")
            issue_logger = SessionIssueLogger(self.session_dir / issue_events_file, enabled=False)
        issue_logger.log(
            "session_start",
            level="INFO",
            duration_s=self.duration_s,
            acclimation_enabled=acclimation_enabled,
            acclimation_duration_s=acclimation_duration_s,
            preview=self.preview,
            offline_fast=self.offline_fast,
            fixed_fps=fixed_fps,
            preview_recording_requested=preview_record_requested,
            raw_recording_requested=raw_record_requested,
            camera_source_override=self.camera_source_override,
        )

        try:
            camera = self._create_camera(fixed_fps=fixed_fps)
            camera_info = camera.camera_info()
            if acclimation_enabled and acclimation_duration_s > 0:
                self.logger.info(
                    "Acclimation started: %.2f s (preview=%s, no recording/no logging)",
                    acclimation_duration_s,
                    self.preview,
                )
                issue_logger.log(
                    "acclimation_start",
                    level="INFO",
                    duration_s=acclimation_duration_s,
                    preview=self.preview,
                )
                acclimation_actual_s = self._run_acclimation_phase(camera, acclimation_duration_s)
                metadata["acclimation"]["actual_duration_s"] = acclimation_actual_s
                self.logger.info("Acclimation finished: %.2f s", acclimation_actual_s)
                issue_logger.log(
                    "acclimation_end",
                    level="INFO",
                    duration_s=acclimation_actual_s,
                )

            runtime = build_runtime(self.config.get("dlc", {}), logger=self.logger)
            roi = ChamberROI.from_config(self.config.get("roi", {}))
            debouncer = Debouncer(
                required_count=int(self.config.get("roi", {}).get("debounce_frames", 8)),
                initial_state="unknown",
            )

            recorder = CSVRecorder(
                self.session_dir / self._prefixed_filename("cpp_realtime_log.csv"),
                fieldnames=[
                    "t_wall",
                    "frame_idx",
                    "x",
                    "y",
                    "p",
                    "chamber_raw",
                    "chamber",
                    "laser_state",
                    "inference_ms",
                    "fps_est",
                ],
                flush_every=200,
            )

            laser_cfg_raw = self.config.get("laser_control", {})
            laser_cfg = dict(laser_cfg_raw) if isinstance(laser_cfg_raw, dict) else {}
            laser_on_chambers = self._resolve_laser_on_chambers(laser_cfg)
            controller = self._create_and_start_controller(laser_cfg)
            previous_laser_state = 1 if controller.current_state else 0
            laser_mode_overlay = _format_laser_mode_overlay(laser_cfg if isinstance(laser_cfg, dict) else {})

            issue_logger.log(
                "runtime_ready",
                level="INFO",
                camera=camera_info,
                dlc_model=runtime.model_info(),
                laser_mode=laser_cfg.get("mode", "dryrun"),
                fallback_to_dryrun=laser_cfg.get("fallback_to_dryrun", True),
                laser_on_chambers=sorted(laser_on_chambers),
                debounce_frames=self.config.get("roi", {}).get("debounce_frames", 8),
                preview_recording_requested=preview_record_requested,
                raw_recording_requested=raw_record_requested,
            )

            metadata.update(
                {
                    "camera": camera_info,
                    "dlc_model": runtime.model_info(),
                    "daq": dict(laser_cfg),
                    "laser_on_chambers_resolved": sorted(laser_on_chambers),
                    "roi": roi.to_dict(),
                    "analysis": self.config.get("analysis", {}),
                }
            )
            self.logger.info(
                "Effective camera: source=%s size=%sx%s fps_capture=%.3f fps_target=%s enforce_fps=%s source_is_file=%s file_throttle=%s throttle_reason=%s fixed_fps=%s offline_fast=%s",
                camera_info.get("source"),
                camera_info.get("width"),
                camera_info.get("height"),
                float(camera_info.get("fps", 0.0) or 0.0),
                camera_info.get("fps_target"),
                camera_info.get("enforce_fps"),
                camera_info.get("source_is_file"),
                camera_info.get("file_realtime_throttle"),
                camera_info.get("fps_throttle_reason"),
                fixed_fps,
                self.offline_fast,
            )

            # Start experiment timer after all initialization (camera/runtime/controller/ROI/recorder)
            # so requested duration_s matches actual experiment acquisition duration.
            experiment_start_wall = time.time()
            experiment_start_monotonic = time.monotonic()
            metadata["start_time_utc"] = utc_now_iso()
            metadata["start_wall"] = experiment_start_wall
            metadata["setup_duration_s"] = max(0.0, experiment_start_wall - setup_start_wall)
            self.logger.info(
                "Experiment timer started (setup_duration_s=%.3f, duration_target_s=%s)",
                metadata["setup_duration_s"],
                self.duration_s,
            )
            issue_logger.log(
                "experiment_timer_started",
                level="INFO",
                setup_duration_s=metadata["setup_duration_s"],
                duration_target_s=self.duration_s,
            )

            timestamps: Deque[float] = deque(maxlen=60)
            inference_ms_window: Deque[float] = deque(maxlen=120)
            last_heartbeat_monotonic = time.monotonic()
            smooth_window = max(1, int(self.config.get("dlc", {}).get("smoothing", {}).get("window", 5)))
            smooth_enabled = bool(self.config.get("dlc", {}).get("smoothing", {}).get("enabled", False))
            smooth_points: Deque[Tuple[float, float]] = deque(maxlen=smooth_window)
            last_valid_xy: Optional[Tuple[float, float]] = None
            last_non_neutral = "unknown"
            p_thresh = float(self.config.get("dlc", {}).get("p_thresh", 0.6))
            display_bodyparts = _parse_display_bodyparts(self.config.get("dlc", {}).get("display_bodyparts"))
            metadata["dlc_display_bodyparts"] = display_bodyparts

            self.logger.info("Realtime session started")

            while True:
                if self.duration_s is not None:
                    if (time.monotonic() - experiment_start_monotonic) >= self.duration_s:
                        self.logger.info("Duration reached: %.2f s", self.duration_s)
                        break

                ok, frame = camera.read()
                if not ok or frame is None:
                    if self._eof_is_normal_stop:
                        self.logger.info("Input video reached end-of-stream")
                        break
                    raise RuntimeError("Camera stream ended or frame read failed")

                t_wall = time.time()
                elapsed_s = max(0.0, t_wall - experiment_start_wall)

                infer_t0 = time.perf_counter()
                pose = runtime.infer(frame)
                inference_ms = (time.perf_counter() - infer_t0) * 1000.0
                inference_ms_window.append(inference_ms)

                if pose.p >= p_thresh:
                    x, y = pose.x, pose.y
                    last_valid_xy = (x, y)
                else:
                    low_confidence_frames += 1
                    if last_valid_xy is not None:
                        x, y = last_valid_xy
                    else:
                        x, y = float("nan"), float("nan")
                    if low_confidence_frames == 1 or (low_confidence_frames % low_conf_warn_every_n) == 0:
                        warning_count += 1
                        action = "hold_last_valid" if last_valid_xy is not None else "no_valid_position"
                        self.logger.warning(
                            "Low confidence frame: p=%.3f < %.3f (frame=%d, action=%s)",
                            pose.p,
                            p_thresh,
                            frame_idx,
                            action,
                        )
                        issue_logger.log(
                            "low_confidence",
                            level="WARNING",
                            frame_idx=frame_idx,
                            p=float(pose.p),
                            p_thresh=p_thresh,
                            action=action,
                        )

                if math.isfinite(x) and math.isfinite(y):
                    smooth_points.append((x, y))
                    if smooth_enabled and len(smooth_points) > 0:
                        x = float(np.mean([p[0] for p in smooth_points]))
                        y = float(np.mean([p[1] for p in smooth_points]))

                if math.isfinite(x) and math.isfinite(y):
                    chamber_raw = roi.classify(x, y)
                else:
                    chamber_raw = "unknown"

                chamber_candidate = self._map_neutral_candidate(chamber_raw, last_non_neutral)
                chamber = debouncer.update(chamber_candidate)
                if chamber != previous_chamber:
                    chamber_transition_count += 1
                    self.logger.info(
                        "Stable chamber transition: %s -> %s (frame=%d, raw=%s)",
                        previous_chamber,
                        chamber,
                        frame_idx,
                        chamber_raw,
                    )
                    issue_logger.log(
                        "chamber_transition",
                        level="INFO",
                        frame_idx=frame_idx,
                        from_chamber=previous_chamber,
                        to_chamber=chamber,
                        chamber_raw=chamber_raw,
                        x=x,
                        y=y,
                        p=float(pose.p),
                    )
                    previous_chamber = chamber
                if chamber in {"chamber1", "chamber2"}:
                    last_non_neutral = chamber

                desired_laser_on = self._resolve_laser_target(
                    chamber,
                    last_non_neutral,
                    on_chambers=laser_on_chambers,
                )
                controller.set_state(desired_laser_on)
                laser_state = 1 if controller.current_state else 0
                if laser_state != previous_laser_state:
                    laser_transition_count += 1
                    self.logger.info(
                        "Laser transition: %d -> %d (frame=%d, chamber=%s, desired=%d)",
                        previous_laser_state,
                        laser_state,
                        frame_idx,
                        chamber,
                        int(bool(desired_laser_on)),
                    )
                    issue_logger.log(
                        "laser_transition",
                        level="INFO",
                        frame_idx=frame_idx,
                        from_state=previous_laser_state,
                        to_state=laser_state,
                        desired_state=int(bool(desired_laser_on)),
                        chamber=chamber,
                    )
                    previous_laser_state = laser_state

                timestamps.append(time.perf_counter())
                fps_est = self._estimate_fps(timestamps)

                if inference_warn_ms > 0 and inference_ms >= inference_warn_ms:
                    warning_count += 1
                    self.logger.warning(
                        "High inference latency: %.2f ms >= %.2f ms (frame=%d)",
                        inference_ms,
                        inference_warn_ms,
                        frame_idx,
                    )
                    issue_logger.log(
                        "inference_latency_warning",
                        level="WARNING",
                        frame_idx=frame_idx,
                        inference_ms=inference_ms,
                        threshold_ms=inference_warn_ms,
                        fps_est=fps_est,
                    )

                recorder.write_row(
                    {
                        "t_wall": t_wall,
                        "frame_idx": frame_idx,
                        "x": x,
                        "y": y,
                        "p": pose.p,
                        "chamber_raw": chamber_raw,
                        "chamber": chamber,
                        "laser_state": laser_state,
                        "inference_ms": inference_ms,
                        "fps_est": fps_est,
                    }
                )
                processed_frames += 1
                last_context = {
                    "frame_idx": frame_idx,
                    "t_wall": t_wall,
                    "elapsed_s": elapsed_s,
                    "x": x,
                    "y": y,
                    "p": float(pose.p),
                    "chamber_raw": chamber_raw,
                    "chamber": chamber,
                    "laser_state": laser_state,
                    "desired_laser_state": int(bool(desired_laser_on)),
                    "inference_ms": inference_ms,
                    "fps_est": fps_est,
                }

                now_monotonic = time.monotonic()
                if heartbeat_interval_s > 0 and (now_monotonic - last_heartbeat_monotonic) >= heartbeat_interval_s:
                    avg_inference_ms = float(np.mean(inference_ms_window)) if inference_ms_window else 0.0
                    self.logger.info(
                        "Heartbeat: frame=%d chamber=%s laser=%d fps=%.2f infer_avg=%.2fms low_conf=%d warnings=%d",
                        frame_idx,
                        chamber,
                        laser_state,
                        fps_est,
                        avg_inference_ms,
                        low_confidence_frames,
                        warning_count,
                    )
                    issue_logger.log(
                        "heartbeat",
                        level="INFO",
                        frame_idx=frame_idx,
                        chamber=chamber,
                        laser_state=laser_state,
                        fps_est=fps_est,
                        inference_avg_ms=avg_inference_ms,
                        low_confidence_frames=low_confidence_frames,
                        warning_count=warning_count,
                    )
                    if fps_warn_below > 0 and fps_est > 0 and fps_est < fps_warn_below:
                        warning_count += 1
                        self.logger.warning(
                            "FPS below threshold: %.2f < %.2f (frame=%d)",
                            fps_est,
                            fps_warn_below,
                            frame_idx,
                        )
                        issue_logger.log(
                            "fps_warning",
                            level="WARNING",
                            frame_idx=frame_idx,
                            fps_est=fps_est,
                            threshold_fps=fps_warn_below,
                    )
                    last_heartbeat_monotonic = now_monotonic

                overlay_frame: Optional[np.ndarray] = None
                if self.preview or (preview_record_enabled and preview_overlay):
                    overlay_frame = self._render_preview_frame(
                        frame=frame,
                        roi=roi,
                        x=x,
                        y=y,
                        control_p=float(pose.p),
                        control_bodypart=str(pose.bodypart),
                        keypoints=pose.keypoints,
                        display_bodyparts=display_bodyparts,
                        chamber=chamber,
                        laser_state=laser_state,
                        laser_mode_text=laser_mode_overlay,
                        fps_est=fps_est,
                        inference_ms=inference_ms,
                        elapsed_s=elapsed_s,
                    )

                if preview_record_enabled:
                    frame_to_write = overlay_frame if preview_overlay and overlay_frame is not None else frame
                    if preview_writer is None:
                        h, w = frame_to_write.shape[:2]
                        fps_cfg = _optional_float(self.config.get("camera", {}).get("fps_target"))
                        # Global fixed_fps has higher priority than preview_recording.fps.
                        preview_fps_effective = fixed_fps if fixed_fps is not None else preview_fps_override
                        preview_fps_source_label = "fixed_fps(global)" if fixed_fps is not None else "preview_recording.fps"
                        fps_for_writer, fps_source = self._resolve_preview_writer_fps(
                            preview_fps_override=preview_fps_effective,
                            camera_fps=float(camera_info.get("fps", 0.0) or 0.0),
                            camera_fps_target=fps_cfg,
                            override_source_label=preview_fps_source_label,
                        )

                        preview_video_path = self._resolve_preview_video_path(preview_filename)
                        preview_video_path.parent.mkdir(parents=True, exist_ok=True)
                        fourcc = cv2.VideoWriter_fourcc(*preview_codec)
                        candidate = cv2.VideoWriter(
                            str(preview_video_path),
                            fourcc,
                            float(fps_for_writer),
                            (int(w), int(h)),
                        )
                        if not candidate.isOpened():
                            warning_count += 1
                            preview_record_enabled = False
                            candidate.release()
                            self.logger.warning(
                                "Failed to open preview writer: %s (codec=%s fps=%.2f)",
                                preview_video_path,
                                preview_codec,
                                fps_for_writer,
                            )
                            issue_logger.log(
                                "preview_video_writer_failed",
                                level="WARNING",
                                path=str(preview_video_path),
                                codec=preview_codec,
                                fps=fps_for_writer,
                                width=w,
                                height=h,
                            )
                        else:
                            preview_writer = candidate
                            preview_writer_opened = True
                            metadata["preview_recording"]["resolved_path"] = str(preview_video_path)
                            metadata["preview_recording"]["fps_actual"] = float(fps_for_writer)
                            metadata["preview_recording"]["fps_source"] = fps_source
                            self.logger.info(
                                "Preview recording started: %s (codec=%s fps=%.2f source=%s overlay=%s)",
                                preview_video_path,
                                preview_codec,
                                fps_for_writer,
                                fps_source,
                                preview_overlay,
                            )
                            issue_logger.log(
                                "preview_video_writer_started",
                                level="INFO",
                                path=str(preview_video_path),
                                codec=preview_codec,
                                fps=fps_for_writer,
                                fps_source=fps_source,
                                width=w,
                                height=h,
                                overlay=preview_overlay,
                            )
                    if preview_writer is not None:
                        preview_writer.write(frame_to_write)
                        preview_frames_written += 1

                if raw_record_enabled:
                    if raw_writer is None:
                        h_raw, w_raw = frame.shape[:2]
                        fps_cfg = _optional_float(self.config.get("camera", {}).get("fps_target"))
                        # Global fixed_fps has higher priority than raw_recording.fps.
                        raw_fps_effective = fixed_fps if fixed_fps is not None else raw_fps_override
                        raw_fps_source_label = "fixed_fps(global)" if fixed_fps is not None else "raw_recording.fps"
                        fps_for_raw_writer, raw_fps_source = self._resolve_preview_writer_fps(
                            preview_fps_override=raw_fps_effective,
                            camera_fps=float(camera_info.get("fps", 0.0) or 0.0),
                            camera_fps_target=fps_cfg,
                            override_source_label=raw_fps_source_label,
                        )

                        raw_video_path = self._resolve_preview_video_path(raw_filename)
                        raw_video_path.parent.mkdir(parents=True, exist_ok=True)
                        raw_fourcc = cv2.VideoWriter_fourcc(*raw_codec)
                        raw_candidate = cv2.VideoWriter(
                            str(raw_video_path),
                            raw_fourcc,
                            float(fps_for_raw_writer),
                            (int(w_raw), int(h_raw)),
                        )
                        if not raw_candidate.isOpened():
                            warning_count += 1
                            raw_record_enabled = False
                            raw_candidate.release()
                            self.logger.warning(
                                "Failed to open raw writer: %s (codec=%s fps=%.2f)",
                                raw_video_path,
                                raw_codec,
                                fps_for_raw_writer,
                            )
                            issue_logger.log(
                                "raw_video_writer_failed",
                                level="WARNING",
                                path=str(raw_video_path),
                                codec=raw_codec,
                                fps=fps_for_raw_writer,
                                width=w_raw,
                                height=h_raw,
                            )
                        else:
                            raw_writer = raw_candidate
                            raw_writer_opened = True
                            metadata["raw_recording"]["resolved_path"] = str(raw_video_path)
                            metadata["raw_recording"]["fps_actual"] = float(fps_for_raw_writer)
                            metadata["raw_recording"]["fps_source"] = raw_fps_source
                            self.logger.info(
                                "Raw recording started: %s (codec=%s fps=%.2f source=%s)",
                                raw_video_path,
                                raw_codec,
                                fps_for_raw_writer,
                                raw_fps_source,
                            )
                            issue_logger.log(
                                "raw_video_writer_started",
                                level="INFO",
                                path=str(raw_video_path),
                                codec=raw_codec,
                                fps=fps_for_raw_writer,
                                fps_source=raw_fps_source,
                                width=w_raw,
                                height=h_raw,
                            )
                    if raw_writer is not None:
                        raw_writer.write(frame)
                        raw_frames_written += 1

                if self.preview:
                    cv2.imshow("cpp_dlc_live", overlay_frame if overlay_frame is not None else frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        self.logger.info("Preview exit key pressed")
                        break

                frame_idx += 1

            self.logger.info("Realtime loop ended normally")

        except KeyboardInterrupt:
            status_code = 0
            self.logger.info("Realtime session interrupted by user (Ctrl-C)")
            issue_logger.log("session_interrupted", level="INFO", last_context=last_context)
            if controller is not None:
                try:
                    controller.set_state(False)
                except Exception:
                    self.logger.exception("Failed to force laser OFF on KeyboardInterrupt")

        except Exception as exc:
            status_code = 1
            self.logger.exception("Realtime session failed")
            issue_logger.log(
                "runtime_exception",
                level="ERROR",
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                last_context=last_context,
            )
            self._write_incident_report(exc, traceback.format_exc(), last_context)
            if controller is not None:
                try:
                    controller.set_state(False)
                except Exception:
                    self.logger.exception("Failed to force laser OFF during exception handling")

        finally:
            if recorder is not None:
                recorder.close()

            if preview_writer is not None:
                try:
                    preview_writer.release()
                except Exception:
                    self.logger.exception("Failed to close preview video writer")
                if preview_video_path is not None:
                    self.logger.info(
                        "Preview recording saved: %s (frames=%d)",
                        preview_video_path,
                        preview_frames_written,
                    )

            if raw_writer is not None:
                try:
                    raw_writer.release()
                except Exception:
                    self.logger.exception("Failed to close raw video writer")
                if raw_video_path is not None:
                    self.logger.info(
                        "Raw recording saved: %s (frames=%d)",
                        raw_video_path,
                        raw_frames_written,
                    )

            if controller is not None:
                try:
                    controller.set_state(False)
                except Exception:
                    self.logger.debug("Ignoring laser OFF error during shutdown", exc_info=True)
                try:
                    controller.stop()
                except Exception:
                    self.logger.exception("Failed to stop laser controller cleanly")

            if camera is not None:
                camera.release()

            if self.preview:
                try:
                    cv2.destroyAllWindows()
                except Exception:
                    pass

            end_wall = time.time()
            metadata.update(
                {
                    "dlc_model": (runtime.model_info() if runtime is not None else metadata.get("dlc_model")),
                    "end_time_utc": utc_now_iso(),
                    "end_wall": end_wall,
                    "duration_s": max(0.0, end_wall - experiment_start_wall),
                    "session_total_s": max(0.0, end_wall - setup_start_wall),
                    "status_code": status_code,
                    "offline_fast": self.offline_fast,
                    "runtime_stats": {
                        "frames_total": processed_frames,
                        "low_confidence_frames": low_confidence_frames,
                        "chamber_transitions": chamber_transition_count,
                        "laser_transitions": laser_transition_count,
                        "warnings": warning_count,
                        "issue_events_file": issue_events_file if issue_enabled else None,
                        "preview_frames_written": preview_frames_written,
                        "raw_frames_written": raw_frames_written,
                    },
                    "preview_recording_result": {
                        "enabled_requested": preview_record_requested,
                        "enabled_effective": preview_record_enabled or preview_writer_opened,
                        "writer_opened": preview_writer_opened,
                        "resolved_path": str(preview_video_path) if preview_video_path is not None else None,
                        "frames_written": preview_frames_written,
                    },
                    "raw_recording_result": {
                        "enabled_requested": raw_record_requested,
                        "enabled_effective": raw_record_enabled or raw_writer_opened,
                        "writer_opened": raw_writer_opened,
                        "resolved_path": str(raw_video_path) if raw_video_path is not None else None,
                        "frames_written": raw_frames_written,
                    },
                    "last_context": last_context,
                }
            )
            metadata_path = self.session_dir / self._prefixed_filename("metadata.json")
            save_json(metadata, metadata_path)
            self.logger.info("Session metadata written: %s", metadata_path)
            if issue_logger is not None:
                issue_logger.log(
                    "session_end",
                    level=("INFO" if status_code == 0 else "ERROR"),
                    status_code=status_code,
                    duration_s=max(0.0, end_wall - experiment_start_wall),
                    frames_total=processed_frames,
                    low_confidence_frames=low_confidence_frames,
                    warning_count=warning_count,
                )
                issue_logger.close()

        return status_code

    def _run_acclimation_phase(self, camera: CameraStream, duration_s: float) -> float:
        if duration_s <= 0:
            return 0.0

        start = time.monotonic()
        deadline = start + float(duration_s)
        while True:
            now = time.monotonic()
            remaining_s = deadline - now
            if remaining_s <= 0:
                break

            if self.preview:
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError("Camera stream ended or frame read failed during acclimation")
                overlay = self._render_acclimation_frame(frame, remaining_s=remaining_s)
                cv2.imshow("cpp_dlc_live", overlay)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    self.logger.info("Preview exit key pressed during acclimation")
                    raise KeyboardInterrupt
            else:
                # Headless mode: still honor the acclimation wait without consuming/recording frames.
                time.sleep(min(0.05, max(0.0, remaining_s)))

        return max(0.0, time.monotonic() - start)

    def _create_camera(self, fixed_fps: Optional[float] = None) -> CameraStream:
        cam_cfg = dict(self.config.get("camera", {}))
        if self.camera_source_override is not None:
            cam_cfg["source"] = self.camera_source_override
        if fixed_fps is not None:
            # Global fixed_fps enforces a single frame/timebase. In offline_fast mode we keep
            # fps_target for metadata/writer timebase, but disable realtime pacing throttle.
            cam_cfg["fps_target"] = fixed_fps
            if not self.offline_fast:
                cam_cfg["enforce_fps"] = True
        if self.offline_fast:
            cam_cfg["enforce_fps"] = False
            cam_cfg["file_realtime_throttle"] = False

        source = cam_cfg.get("source", 0)
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        self._eof_is_normal_stop = isinstance(source, str) and Path(source).exists()

        cfg = CameraConfig(
            source=source,
            width=_optional_int(cam_cfg.get("width")),
            height=_optional_int(cam_cfg.get("height")),
            fps_target=_optional_float(cam_cfg.get("fps_target")),
            enforce_fps=bool(cam_cfg.get("enforce_fps", False)),
            file_realtime_throttle=bool(cam_cfg.get("file_realtime_throttle", True)),
            auto_exposure=_optional_bool(cam_cfg.get("auto_exposure")),
            exposure=_optional_float(cam_cfg.get("exposure")),
            gain=_optional_float(cam_cfg.get("gain")),
            flip=bool(cam_cfg.get("flip", False)),
            rotate_deg=int(cam_cfg.get("rotate_deg", 0)),
        )
        return CameraStream(cfg)

    def _create_and_start_controller(self, laser_cfg: Dict[str, Any]) -> LaserControllerBase:
        fallback = bool(laser_cfg.get("fallback_to_dryrun", True))
        try:
            controller = create_laser_controller(laser_cfg, logger=self.logger)
            controller.start()
            return controller
        except LaserControllerError:
            if fallback:
                self.logger.exception("NI controller setup failed, falling back to dryrun")
                dry = DryRunLaserController(logger=self.logger)
                dry.start()
                return dry
            raise

    def _resolve_laser_on_chambers(self, laser_cfg: Dict[str, Any]) -> Set[str]:
        raw = laser_cfg.get("on_chambers", None)
        if raw is None:
            return {"chamber1"}

        tokens: list[str]
        if isinstance(raw, str):
            cleaned = raw.replace("|", ",").replace(";", ",")
            tokens = [token.strip() for token in cleaned.split(",") if token.strip()]
        elif isinstance(raw, (list, tuple, set)):
            tokens = [str(token).strip() for token in raw if str(token).strip()]
            if not tokens:
                # Explicit empty list means "none": no chamber can turn laser ON.
                return set()
        else:
            self.logger.warning(
                "laser_control.on_chambers should be a string or list, got %s; fallback to ['chamber1']",
                type(raw).__name__,
            )
            return {"chamber1"}

        resolved: Set[str] = set()
        invalid_tokens: list[str] = []
        saw_none = False
        for token in tokens:
            token_norm = token.lower().strip()
            if token_norm in {"all", "*"}:
                return set(_VALID_LASER_ON_CHAMBERS)
            chamber_name = _LASER_ON_CHAMBER_ALIASES.get(token_norm, token_norm)
            if chamber_name == "none":
                saw_none = True
                continue
            if chamber_name in _VALID_LASER_ON_CHAMBERS:
                resolved.add(chamber_name)
            else:
                invalid_tokens.append(token)

        if invalid_tokens:
            self.logger.warning(
                "Ignoring unknown laser on_chambers entries: %s (valid: %s)",
                invalid_tokens,
                sorted(_VALID_LASER_ON_CHAMBERS),
            )

        if saw_none and not resolved:
            return set()
        if saw_none and resolved:
            self.logger.warning("laser_control.on_chambers contains both none and chamber names, ignoring none")

        if not resolved:
            self.logger.warning("laser_control.on_chambers resolved empty; fallback to ['chamber1']")
            return {"chamber1"}
        return resolved

    def _resolve_laser_target(self, chamber: str, last_non_neutral: str, on_chambers: Optional[Set[str]] = None) -> bool:
        laser_cfg = self.config.get("laser_control", {})
        if not isinstance(laser_cfg, dict):
            laser_cfg = {}
        if not bool(laser_cfg.get("enabled", True)):
            return False

        resolved_on_chambers = on_chambers if on_chambers is not None else self._resolve_laser_on_chambers(laser_cfg)
        if chamber in {"chamber1", "chamber2"}:
            return chamber in resolved_on_chambers

        if chamber == "neutral":
            strategy = str(self.config.get("roi", {}).get("strategy_on_neutral", "off")).lower().strip()
            if strategy == "hold_last":
                if last_non_neutral in {"chamber1", "chamber2"}:
                    return last_non_neutral in resolved_on_chambers
                return self._resolve_unknown_policy(last_non_neutral, resolved_on_chambers)
            if strategy == "unknown":
                return self._resolve_unknown_policy(last_non_neutral, resolved_on_chambers)
            return "neutral" in resolved_on_chambers

        return self._resolve_unknown_policy(last_non_neutral, resolved_on_chambers)

    def _resolve_unknown_policy(self, last_non_neutral: str, on_chambers: Set[str]) -> bool:
        unknown_policy = str(self.config.get("laser_control", {}).get("unknown_policy", "off")).lower().strip()
        if unknown_policy == "hold_last":
            return last_non_neutral in on_chambers
        return False

    def _map_neutral_candidate(self, chamber_raw: str, last_non_neutral: str) -> str:
        if chamber_raw != "neutral":
            return chamber_raw

        strategy = str(self.config.get("roi", {}).get("strategy_on_neutral", "off")).lower().strip()
        if strategy == "hold_last":
            if last_non_neutral in {"chamber1", "chamber2"}:
                return last_non_neutral
            return "unknown"
        if strategy == "unknown":
            return "unknown"
        return "neutral"

    @staticmethod
    def _estimate_fps(timestamps: Deque[float]) -> float:
        if len(timestamps) < 2:
            return 0.0
        dt = timestamps[-1] - timestamps[0]
        if dt <= 0:
            return 0.0
        return float((len(timestamps) - 1) / dt)

    @staticmethod
    def _render_preview_frame(
        frame: np.ndarray,
        roi: ChamberROI,
        x: float,
        y: float,
        control_p: float,
        control_bodypart: str,
        keypoints: Dict[str, Tuple[float, float, float]],
        display_bodyparts: Optional[list[str]],
        chamber: str,
        laser_state: int,
        laser_mode_text: str,
        fps_est: float,
        inference_ms: float,
        elapsed_s: float,
    ) -> np.ndarray:
        vis = roi.draw(frame)
        for name, (px, py, pp), is_control in _resolve_preview_points(
            keypoints=keypoints,
            display_bodyparts=display_bodyparts,
            control_bodypart=control_bodypart,
            control_point=(x, y, control_p),
        ):
            if not (math.isfinite(px) and math.isfinite(py)):
                continue
            color = (255, 255, 255) if is_control else _bodypart_color(name)
            radius = 5 if is_control else 4
            cv2.circle(vis, (int(px), int(py)), radius, color, -1)
            cv2.putText(
                vis,
                name,
                (int(px) + 6, int(py) - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
            )

        cv2.putText(vis, f"chamber: {chamber}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"laser: {laser_state}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(
            vis,
            f"laser_mode: {laser_mode_text}",
            (10, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        cv2.putText(vis, f"fps: {fps_est:.1f}", (10, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"infer_ms: {inference_ms:.1f}", (10, 136), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(
            vis,
            f"time: {RealtimeApp._format_elapsed_hhmmss(elapsed_s)}",
            (10, 164),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        return vis

    @staticmethod
    def _render_acclimation_frame(frame: np.ndarray, remaining_s: float) -> np.ndarray:
        vis = frame.copy()
        cv2.putText(
            vis,
            "acclimation: ON (not recording)",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            vis,
            f"remaining: {RealtimeApp._format_elapsed_hhmmss(remaining_s)}",
            (10, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        return vis

    def _resolve_preview_video_path(self, filename: str) -> Path:
        path = Path(str(filename))
        if path.is_absolute():
            return path
        return self.session_dir / path

    @staticmethod
    def _resolve_preview_writer_fps(
        preview_fps_override: Optional[float],
        camera_fps: float,
        camera_fps_target: Optional[float],
        override_source_label: str = "preview_recording.fps",
    ) -> Tuple[float, str]:
        if preview_fps_override is not None and preview_fps_override > 0:
            return float(preview_fps_override), override_source_label
        if camera_fps_target is not None and camera_fps_target > 0:
            return float(camera_fps_target), "camera.fps_target"
        if camera_fps > 0:
            return float(camera_fps), "camera_reported_fps"
        return 30.0, "default_30"

    @staticmethod
    def _format_elapsed_hhmmss(seconds: float) -> str:
        safe = max(0.0, float(seconds))
        total_ms = int(safe * 1000.0)
        hours = total_ms // (3600 * 1000)
        minutes = (total_ms % (3600 * 1000)) // (60 * 1000)
        secs = (total_ms % (60 * 1000)) // 1000
        millis = total_ms % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

    def _write_incident_report(
        self,
        exc: BaseException,
        traceback_text: str,
        last_context: Dict[str, Any],
    ) -> None:
        report = {
            "time_utc": utc_now_iso(),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback_text,
            "last_context": last_context,
            "camera_source_override": self.camera_source_override,
            "session_dir": str(self.session_dir),
        }
        base = f"incident_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
        path = self.session_dir / self._prefixed_filename(base)
        try:
            save_json(report, path)
            self.logger.error("Incident report written: %s", path)
        except Exception:
            self.logger.exception("Failed to write incident report")

    def _prefixed_filename(self, base_name: str) -> str:
        return ensure_prefixed_filename(base_name, self.file_prefix)


def _optional_int(v: Any) -> Optional[int]:
    return int(v) if v is not None else None


def _optional_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None


def _optional_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    text = str(v).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {v}")


def _parse_display_bodyparts(value: Any) -> Optional[list[str]]:
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.lower() in {"all", "*"}:
            return ["*"]
        return [text]

    if isinstance(value, (list, tuple)):
        names = [str(v).strip() for v in value if str(v).strip()]
        if not names:
            return None
        lowered = {n.lower() for n in names}
        if "all" in lowered or "*" in lowered:
            return ["*"]
        return names

    # Unsupported value type: ignore and fallback to default single control point.
    return None


def _resolve_preview_points(
    keypoints: Dict[str, Tuple[float, float, float]],
    display_bodyparts: Optional[list[str]],
    control_bodypart: str,
    control_point: Tuple[float, float, float],
) -> list[Tuple[str, Tuple[float, float, float], bool]]:
    if not keypoints:
        return [(control_bodypart, control_point, True)]

    if display_bodyparts is None:
        return [(control_bodypart, control_point, True)]

    if display_bodyparts == ["*"]:
        return [(name, pt, name == control_bodypart) for name, pt in keypoints.items()]

    by_lower = {name.lower(): name for name in keypoints.keys()}
    selected: list[Tuple[str, Tuple[float, float, float], bool]] = []
    seen: set[str] = set()
    for requested in display_bodyparts:
        actual = by_lower.get(requested.lower())
        if actual is None or actual in seen:
            continue
        selected.append((actual, keypoints[actual], actual == control_bodypart))
        seen.add(actual)

    # If configured names don't match runtime keypoints, still show control point.
    if not selected:
        return [(control_bodypart, control_point, True)]
    return selected


def _bodypart_color(name: str) -> Tuple[int, int, int]:
    palette = [
        (0, 255, 0),
        (0, 200, 255),
        (255, 120, 0),
        (255, 0, 180),
        (180, 255, 0),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 0),
    ]
    # Stable color assignment across frames/sessions for the same label.
    idx = abs(hash(name)) % len(palette)
    return palette[idx]


def _format_laser_mode_overlay(laser_cfg: Dict[str, Any]) -> str:
    mode_raw = str(laser_cfg.get("mode", "dryrun")).strip().lower()
    if mode_raw in {"continuous", "continues", "level"}:
        return "continuous"

    if mode_raw in {"pulse", "gated", "startstop"}:
        freq = _optional_float(laser_cfg.get("freq_hz"))
        if freq is not None and freq > 0:
            return f"pulse {freq:.1f}Hz"
        return "pulse"

    return mode_raw or "unknown"


def _resolve_acclimation_config(config: Dict[str, Any]) -> Tuple[bool, float]:
    acclimation_cfg = config.get("acclimation", {})
    if not isinstance(acclimation_cfg, dict):
        acclimation_cfg = {}

    enabled = _optional_bool(acclimation_cfg.get("enabled"))
    if enabled is None:
        # Backward-compatible fallback: allow session_info to drive acclimation.
        session_info = config.get("session_info", {})
        if isinstance(session_info, dict):
            enabled = _optional_bool(session_info.get("acclimation_enabled"))
    enabled = bool(enabled) if enabled is not None else False

    duration_s = _optional_float(acclimation_cfg.get("duration_s"))
    if duration_s is None:
        session_info = config.get("session_info", {})
        if isinstance(session_info, dict):
            duration_s = _optional_float(session_info.get("acclimation_duration_s"))

    if not enabled or duration_s is None or duration_s <= 0:
        return False, 0.0
    return True, float(duration_s)
