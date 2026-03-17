from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Dict, Optional, Tuple, Union

import cv2
import numpy as np


@dataclass
class CameraConfig:
    source: Union[int, str] = 0
    width: Optional[int] = None
    height: Optional[int] = None
    fps_target: Optional[float] = None
    enforce_fps: bool = False
    auto_exposure: Optional[bool] = None
    exposure: Optional[float] = None
    gain: Optional[float] = None
    flip: bool = False
    rotate_deg: int = 0


class CameraStream:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self._source_is_file = isinstance(cfg.source, str) and Path(cfg.source).exists()
        self._throttle_period_s: Optional[float] = None
        self._next_frame_deadline: Optional[float] = None
        self._throttle_reason: Optional[str] = None

        if cfg.fps_target is not None and float(cfg.fps_target) > 0 and (self._source_is_file or bool(cfg.enforce_fps)):
            # Throttle to target FPS when reading from file, or when explicitly enforced for camera streams.
            self._throttle_period_s = 1.0 / float(cfg.fps_target)
            self._throttle_reason = "file_source" if self._source_is_file else "enforce_fps"

        self.cap = cv2.VideoCapture(cfg.source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera/video source: {cfg.source}")

        if cfg.width is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.width))
        if cfg.height is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.height))
        if cfg.fps_target is not None:
            self.cap.set(cv2.CAP_PROP_FPS, float(cfg.fps_target))
        self._apply_exposure_settings()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return False, None

        if self.cfg.flip:
            frame = cv2.flip(frame, 1)

        rotate = int(self.cfg.rotate_deg) % 360
        if rotate == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotate == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rotate == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif rotate not in (0,):
            h, w = frame.shape[:2]
            m = cv2.getRotationMatrix2D((w / 2, h / 2), rotate, 1.0)
            frame = cv2.warpAffine(frame, m, (w, h))

        self._apply_realtime_throttle_if_needed()
        return True, frame

    def camera_info(self) -> Dict[str, Any]:
        return {
            "source": self.cfg.source,
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0),
            "fps_target": (float(self.cfg.fps_target) if self.cfg.fps_target is not None else None),
            "enforce_fps": bool(self.cfg.enforce_fps),
            "auto_exposure_requested": self.cfg.auto_exposure,
            "exposure_requested": self.cfg.exposure,
            "gain_requested": self.cfg.gain,
            "auto_exposure": float(self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE) or 0.0),
            "exposure": float(self.cap.get(cv2.CAP_PROP_EXPOSURE) or 0.0),
            "gain": float(self.cap.get(cv2.CAP_PROP_GAIN) or 0.0),
            "source_is_file": self._source_is_file,
            "file_realtime_throttle": bool(self._throttle_period_s is not None),
            "fps_throttle_reason": self._throttle_reason,
            "flip": bool(self.cfg.flip),
            "rotate_deg": int(self.cfg.rotate_deg),
        }

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()

    def set_auto_exposure(self, enabled: bool) -> float:
        # CAP_PROP_AUTO_EXPOSURE is backend-specific:
        # - DirectShow often uses 0.25(manual)/0.75(auto)
        # - V4L2 often uses 1(manual)/3(auto)
        candidates = (0.75, 3.0, 1.0) if bool(enabled) else (0.25, 1.0, 0.0)
        for value in candidates:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, float(value))
        return float(self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE) or 0.0)

    def set_exposure(self, value: float) -> float:
        self.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
        return float(self.cap.get(cv2.CAP_PROP_EXPOSURE) or 0.0)

    def set_gain(self, value: float) -> float:
        self.cap.set(cv2.CAP_PROP_GAIN, float(value))
        return float(self.cap.get(cv2.CAP_PROP_GAIN) or 0.0)

    def _apply_realtime_throttle_if_needed(self) -> None:
        if self._throttle_period_s is None:
            return

        now = time.perf_counter()
        if self._next_frame_deadline is None:
            self._next_frame_deadline = now + self._throttle_period_s
            return

        sleep_s = self._next_frame_deadline - now
        if sleep_s > 0:
            time.sleep(sleep_s)
            now = time.perf_counter()

        next_deadline = self._next_frame_deadline + self._throttle_period_s
        if next_deadline < now:
            next_deadline = now + self._throttle_period_s
        self._next_frame_deadline = next_deadline

    def _apply_exposure_settings(self) -> None:
        if self.cfg.auto_exposure is not None:
            self.set_auto_exposure(bool(self.cfg.auto_exposure))

        if self.cfg.exposure is not None:
            self.set_exposure(float(self.cfg.exposure))

        if self.cfg.gain is not None:
            self.set_gain(float(self.cfg.gain))
