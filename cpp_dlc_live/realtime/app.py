from __future__ import annotations

import logging
import math
import time
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

        try:
            camera = self._create_camera()
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

            metadata.update(
                {
                    "camera": camera.camera_info(),
                    "dlc_model": runtime.model_info(),
                    "daq": dict(laser_cfg),
                    "roi": roi.to_dict(),
                    "analysis": self.config.get("analysis", {}),
                }
            )

            timestamps: Deque[float] = deque(maxlen=60)
            smooth_window = max(1, int(self.config.get("dlc", {}).get("smoothing", {}).get("window", 5)))
            smooth_enabled = bool(self.config.get("dlc", {}).get("smoothing", {}).get("enabled", False))
            smooth_points: Deque[Tuple[float, float]] = deque(maxlen=smooth_window)
            frame_idx = 0
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

                if pose.p >= p_thresh:
                    x, y = pose.x, pose.y
                    last_valid_xy = (x, y)
                elif last_valid_xy is not None:
                    x, y = last_valid_xy
                else:
                    x, y = float("nan"), float("nan")

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
                if chamber in {"chamber1", "chamber2"}:
                    last_non_neutral = chamber

                desired_laser_on = self._resolve_laser_target(chamber, last_non_neutral)
                controller.set_state(desired_laser_on)
                laser_state = 1 if controller.current_state else 0

                timestamps.append(time.perf_counter())
                fps_est = self._estimate_fps(timestamps)

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

                if self.preview:
                    self._preview_frame(
                        frame=frame,
                        roi=roi,
                        x=x,
                        y=y,
                        chamber=chamber,
                        laser_state=laser_state,
                        fps_est=fps_est,
                        inference_ms=inference_ms,
                    )
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        self.logger.info("Preview exit key pressed")
                        break

                frame_idx += 1

            self.logger.info("Realtime loop ended normally")

        except KeyboardInterrupt:
            status_code = 0
            self.logger.info("Realtime session interrupted by user (Ctrl-C)")
            if controller is not None:
                try:
                    controller.set_state(False)
                except Exception:
                    self.logger.exception("Failed to force laser OFF on KeyboardInterrupt")

        except Exception:
            status_code = 1
            self.logger.exception("Realtime session failed")
            if controller is not None:
                try:
                    controller.set_state(False)
                except Exception:
                    self.logger.exception("Failed to force laser OFF during exception handling")

        finally:
            if recorder is not None:
                recorder.close()

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
                }
            )
            save_json(metadata, self.session_dir / "metadata.json")
            self.logger.info("Session metadata written: %s", self.session_dir / "metadata.json")

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
    def _preview_frame(
        frame: np.ndarray,
        roi: ChamberROI,
        x: float,
        y: float,
        chamber: str,
        laser_state: int,
        fps_est: float,
        inference_ms: float,
    ) -> None:
        vis = roi.draw(frame)
        if math.isfinite(x) and math.isfinite(y):
            cv2.circle(vis, (int(x), int(y)), 5, (255, 255, 255), -1)

        cv2.putText(vis, f"chamber: {chamber}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"laser: {laser_state}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"fps: {fps_est:.1f}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(vis, f"infer_ms: {inference_ms:.1f}", (10, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("cpp_dlc_live", vis)


def _optional_int(v: Any) -> Optional[int]:
    return int(v) if v is not None else None


def _optional_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None
