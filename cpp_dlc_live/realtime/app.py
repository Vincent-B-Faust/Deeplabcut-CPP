from __future__ import annotations

import logging
import math
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple, Union

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
from cpp_dlc_live.utils.io_utils import file_sha256, save_json
from cpp_dlc_live.utils.time_utils import utc_now_iso


class RealtimeApp:
    def __init__(
        self,
        config: Dict[str, Any],
        session_dir: Path,
        duration_s: Optional[float] = None,
        camera_source_override: Optional[Union[int, str]] = None,
        preview: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = config
        self.session_dir = Path(session_dir)
        self.duration_s = duration_s
        self.camera_source_override = camera_source_override
        self.preview = preview
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

        frame_idx = 0
        processed_frames = 0
        low_confidence_frames = 0
        chamber_transition_count = 0
        laser_transition_count = 0
        warning_count = 0
        preview_frames_written = 0
        preview_writer_opened = False
        preview_video_path: Optional[Path] = None
        last_context: Dict[str, Any] = {}
        previous_chamber = "unknown"
        previous_laser_state = 0

        status_code = 0
        start_wall = time.time()
        start_monotonic = time.monotonic()

        metadata: Dict[str, Any] = {
            "start_time_utc": utc_now_iso(),
            "start_wall": start_wall,
            "session_dir": str(self.session_dir),
            "config": self.config,
        }
        cfg_used = self.session_dir / "config_used.yaml"
        if cfg_used.exists():
            metadata["config_copy"] = str(cfg_used)
            metadata["config_sha256"] = file_sha256(cfg_used)

        raw_runtime_log_cfg = self.config.get("runtime_logging", {})
        runtime_log_cfg = dict(raw_runtime_log_cfg) if isinstance(raw_runtime_log_cfg, dict) else {}
        issue_enabled = bool(runtime_log_cfg.get("enabled", True))
        issue_events_file = str(runtime_log_cfg.get("issue_events_file", "issue_events.jsonl"))
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

        raw_preview_record_cfg = self.config.get("preview_recording", {})
        preview_record_cfg = (
            dict(raw_preview_record_cfg)
            if isinstance(raw_preview_record_cfg, dict)
            else {}
        )
        preview_record_requested = bool(preview_record_cfg.get("enabled", False))
        preview_record_enabled = preview_record_requested
        preview_filename = str(preview_record_cfg.get("filename", "preview_overlay.mp4"))
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

        try:
            issue_logger = SessionIssueLogger(self.session_dir / issue_events_file, enabled=issue_enabled)
        except Exception:
            self.logger.exception("Failed to initialize structured issue logger, continuing without it")
            issue_logger = SessionIssueLogger(self.session_dir / issue_events_file, enabled=False)
        issue_logger.log(
            "session_start",
            level="INFO",
            duration_s=self.duration_s,
            preview=self.preview,
            preview_recording_requested=preview_record_requested,
            camera_source_override=self.camera_source_override,
        )

        try:
            camera = self._create_camera()
            camera_info = camera.camera_info()
            runtime = build_runtime(self.config.get("dlc", {}), logger=self.logger)
            roi = ChamberROI.from_config(self.config.get("roi", {}))
            debouncer = Debouncer(
                required_count=int(self.config.get("roi", {}).get("debounce_frames", 8)),
                initial_state="unknown",
            )

            recorder = CSVRecorder(
                self.session_dir / "cpp_realtime_log.csv",
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

            laser_cfg = self.config.get("laser_control", {})
            controller = self._create_and_start_controller(laser_cfg)
            previous_laser_state = 1 if controller.current_state else 0

            issue_logger.log(
                "runtime_ready",
                level="INFO",
                camera=camera_info,
                dlc_model=runtime.model_info(),
                laser_mode=laser_cfg.get("mode", "dryrun"),
                fallback_to_dryrun=laser_cfg.get("fallback_to_dryrun", True),
                debounce_frames=self.config.get("roi", {}).get("debounce_frames", 8),
                preview_recording_requested=preview_record_requested,
            )

            metadata.update(
                {
                    "camera": camera_info,
                    "dlc_model": runtime.model_info(),
                    "daq": dict(laser_cfg),
                    "roi": roi.to_dict(),
                    "analysis": self.config.get("analysis", {}),
                }
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

            self.logger.info("Realtime session started")

            while True:
                if self.duration_s is not None:
                    if (time.monotonic() - start_monotonic) >= self.duration_s:
                        self.logger.info("Duration reached: %.2f s", self.duration_s)
                        break

                ok, frame = camera.read()
                if not ok or frame is None:
                    if self._eof_is_normal_stop:
                        self.logger.info("Input video reached end-of-stream")
                        break
                    raise RuntimeError("Camera stream ended or frame read failed")

                t_wall = time.time()

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

                desired_laser_on = self._resolve_laser_target(chamber, last_non_neutral)
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
                        chamber=chamber,
                        laser_state=laser_state,
                        fps_est=fps_est,
                        inference_ms=inference_ms,
                    )

                if preview_record_enabled:
                    frame_to_write = overlay_frame if preview_overlay and overlay_frame is not None else frame
                    if preview_writer is None:
                        h, w = frame_to_write.shape[:2]
                        fps_for_writer = (
                            preview_fps_override
                            if preview_fps_override is not None and preview_fps_override > 0
                            else float(camera_info.get("fps", 0.0))
                        )
                        if fps_for_writer <= 0:
                            fps_cfg = _optional_float(self.config.get("camera", {}).get("fps_target"))
                            fps_for_writer = fps_cfg if fps_cfg is not None and fps_cfg > 0 else 30.0

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
                            self.logger.info(
                                "Preview recording started: %s (codec=%s fps=%.2f, overlay=%s)",
                                preview_video_path,
                                preview_codec,
                                fps_for_writer,
                                preview_overlay,
                            )
                            issue_logger.log(
                                "preview_video_writer_started",
                                level="INFO",
                                path=str(preview_video_path),
                                codec=preview_codec,
                                fps=fps_for_writer,
                                width=w,
                                height=h,
                                overlay=preview_overlay,
                            )
                    if preview_writer is not None:
                        preview_writer.write(frame_to_write)
                        preview_frames_written += 1

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
                    "end_time_utc": utc_now_iso(),
                    "end_wall": end_wall,
                    "duration_s": max(0.0, end_wall - start_wall),
                    "status_code": status_code,
                    "runtime_stats": {
                        "frames_total": processed_frames,
                        "low_confidence_frames": low_confidence_frames,
                        "chamber_transitions": chamber_transition_count,
                        "laser_transitions": laser_transition_count,
                        "warnings": warning_count,
                        "issue_events_file": issue_events_file if issue_enabled else None,
                        "preview_frames_written": preview_frames_written,
                    },
                    "preview_recording_result": {
                        "enabled_requested": preview_record_requested,
                        "enabled_effective": preview_record_enabled or preview_writer_opened,
                        "writer_opened": preview_writer_opened,
                        "resolved_path": str(preview_video_path) if preview_video_path is not None else None,
                        "frames_written": preview_frames_written,
                    },
                    "last_context": last_context,
                }
            )
            save_json(metadata, self.session_dir / "metadata.json")
            self.logger.info("Session metadata written: %s", self.session_dir / "metadata.json")
            if issue_logger is not None:
                issue_logger.log(
                    "session_end",
                    level=("INFO" if status_code == 0 else "ERROR"),
                    status_code=status_code,
                    duration_s=max(0.0, end_wall - start_wall),
                    frames_total=processed_frames,
                    low_confidence_frames=low_confidence_frames,
                    warning_count=warning_count,
                )
                issue_logger.close()

        return status_code

    def _create_camera(self) -> CameraStream:
        cam_cfg = dict(self.config.get("camera", {}))
        if self.camera_source_override is not None:
            cam_cfg["source"] = self.camera_source_override

        source = cam_cfg.get("source", 0)
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        self._eof_is_normal_stop = isinstance(source, str) and Path(source).exists()

        cfg = CameraConfig(
            source=source,
            width=_optional_int(cam_cfg.get("width")),
            height=_optional_int(cam_cfg.get("height")),
            fps_target=_optional_float(cam_cfg.get("fps_target")),
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

    def _resolve_laser_target(self, chamber: str, last_non_neutral: str) -> bool:
        laser_cfg = self.config.get("laser_control", {})
        if not bool(laser_cfg.get("enabled", True)):
            return False

        if chamber == "chamber1":
            return True
        if chamber == "chamber2":
            return False

        if chamber == "neutral":
            strategy = str(self.config.get("roi", {}).get("strategy_on_neutral", "off")).lower().strip()
            if strategy == "hold_last":
                return last_non_neutral == "chamber1"
            if strategy == "unknown":
                return self._resolve_unknown_policy(last_non_neutral)
            return False

        return self._resolve_unknown_policy(last_non_neutral)

    def _resolve_unknown_policy(self, last_non_neutral: str) -> bool:
        unknown_policy = str(self.config.get("laser_control", {}).get("unknown_policy", "off")).lower().strip()
        if unknown_policy == "hold_last":
            return last_non_neutral == "chamber1"
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
        chamber: str,
        laser_state: int,
        fps_est: float,
        inference_ms: float,
    ) -> np.ndarray:
        vis = roi.draw(frame)
        if math.isfinite(x) and math.isfinite(y):
            cv2.circle(vis, (int(x), int(y)), 5, (255, 255, 255), -1)

        cv2.putText(vis, f"chamber: {chamber}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"laser: {laser_state}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"fps: {fps_est:.1f}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"infer_ms: {inference_ms:.1f}", (10, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return vis

    def _resolve_preview_video_path(self, filename: str) -> Path:
        path = Path(str(filename))
        if path.is_absolute():
            return path
        return self.session_dir / path

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
        path = self.session_dir / f"incident_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            save_json(report, path)
            self.logger.error("Incident report written: %s", path)
        except Exception:
            self.logger.exception("Failed to write incident report")


def _optional_int(v: Any) -> Optional[int]:
    return int(v) if v is not None else None


def _optional_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None
