from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

import cv2
import numpy as np


@dataclass
class CameraConfig:
    source: Union[int, str] = 0
    width: Optional[int] = None
    height: Optional[int] = None
    fps_target: Optional[float] = None
    flip: bool = False
    rotate_deg: int = 0


class CameraStream:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.cap = cv2.VideoCapture(cfg.source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera/video source: {cfg.source}")

        if cfg.width is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.width))
        if cfg.height is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.height))
        if cfg.fps_target is not None:
            self.cap.set(cv2.CAP_PROP_FPS, float(cfg.fps_target))

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

        return True, frame

    def camera_info(self) -> Dict[str, Any]:
        return {
            "source": self.cfg.source,
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0),
            "flip": bool(self.cfg.flip),
            "rotate_deg": int(self.cfg.rotate_deg),
        }

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
