from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import yaml


@dataclass
class PoseResult:
    x: float
    y: float
    p: float
    bodypart: str


class RuntimeBase:
    def infer(self, frame: np.ndarray) -> PoseResult:
        raise NotImplementedError

    def model_info(self) -> Dict[str, Any]:
        raise NotImplementedError


class MockDLCRuntime(RuntimeBase):
    def __init__(self, bodypart: str = "center"):
        self.bodypart = bodypart

    def infer(self, frame: np.ndarray) -> PoseResult:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        m = cv2.moments(mask)
        if m["m00"] > 0:
            x = float(m["m10"] / m["m00"])
            y = float(m["m01"] / m["m00"])
            p = 1.0
        else:
            h, w = gray.shape
            x = float(w / 2)
            y = float(h / 2)
            p = 0.0
        return PoseResult(x=x, y=y, p=p, bodypart=self.bodypart)

    def model_info(self) -> Dict[str, Any]:
        return {
            "runtime": "mock",
            "model_path": None,
            "bodyparts": [self.bodypart],
            "snapshot": None,
            "notes": "Fallback runtime without deeplabcut-live",
        }


class DLCLiveRuntime(RuntimeBase):
    def __init__(self, model_path: str, bodypart: str = "center"):
        self.model_path = str(model_path)
        self.bodypart = bodypart
        self._initialized = False

        try:
            from dlclive import DLCLive, Processor  # type: ignore
        except Exception as exc:
            raise RuntimeError("deeplabcut-live is not available") from exc

        self._model_cfg = _load_model_cfg(model_path)
        self._bodyparts = _extract_bodyparts(self._model_cfg)
        self._snapshot = _extract_snapshot(self._model_cfg)
        self._dlc = DLCLive(model_path, processor=Processor())

    def infer(self, frame: np.ndarray) -> PoseResult:
        if not self._initialized:
            self._dlc.init_inference(frame)
            self._initialized = True

        pose = np.asarray(self._dlc.get_pose(frame))
        if pose.ndim != 2 or pose.shape[1] < 3:
            raise RuntimeError(f"Unexpected pose shape: {pose.shape}")

        x, y, p, resolved = _select_bodypart(pose, self._bodyparts, self.bodypart)
        return PoseResult(x=float(x), y=float(y), p=float(p), bodypart=resolved)

    def model_info(self) -> Dict[str, Any]:
        return {
            "runtime": "dlclive",
            "model_path": self.model_path,
            "bodyparts": self._bodyparts,
            "target_bodypart": self.bodypart,
            "snapshot": self._snapshot,
        }


def build_runtime(dlc_cfg: Dict[str, Any], logger: Optional[logging.Logger] = None) -> RuntimeBase:
    bodypart = str(dlc_cfg.get("bodypart", "center"))
    model_path = str(dlc_cfg.get("model_path", "")).strip()

    if model_path and Path(model_path).exists():
        try:
            runtime = DLCLiveRuntime(model_path=model_path, bodypart=bodypart)
            if logger:
                logger.info("Using DLCLive runtime from %s", model_path)
            return runtime
        except Exception:
            if logger:
                logger.exception("Failed to initialize DLCLive runtime, falling back to mock")

    if logger:
        logger.warning("Using mock DLC runtime (no valid model path or DLCLive unavailable)")
    return MockDLCRuntime(bodypart=bodypart)


def _load_model_cfg(model_path: str) -> Dict[str, Any]:
    candidates = [
        Path(model_path) / "pose_cfg.yaml",
        Path(model_path) / "config.yaml",
        Path(model_path) / "dlc-models" / "pose_cfg.yaml",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            continue
    return {}


def _extract_bodyparts(model_cfg: Dict[str, Any]) -> List[str]:
    names = model_cfg.get("all_joints_names") or model_cfg.get("bodyparts")
    if isinstance(names, list) and names:
        return [str(n) for n in names]
    return []


def _extract_snapshot(model_cfg: Dict[str, Any]) -> Optional[str]:
    for key in ("init_weights", "snapshot_prefix", "snapshot"):
        value = model_cfg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _select_bodypart(pose: np.ndarray, bodyparts: List[str], target: str) -> tuple[float, float, float, str]:
    target = target.strip()

    def pick(idx: int, name: str) -> tuple[float, float, float, str]:
        row = pose[idx]
        return float(row[0]), float(row[1]), float(row[2]), name

    if bodyparts and target in bodyparts:
        return pick(bodyparts.index(target), target)

    if bodyparts and target == "center":
        if "center" in bodyparts:
            return pick(bodyparts.index("center"), "center")
        if "nose" in bodyparts and "tailbase" in bodyparts:
            nose = pose[bodyparts.index("nose")]
            tail = pose[bodyparts.index("tailbase")]
            x = float((nose[0] + tail[0]) / 2.0)
            y = float((nose[1] + tail[1]) / 2.0)
            p = float(min(nose[2], tail[2]))
            return x, y, p, "nose_tailbase_midpoint"

    return pick(0, bodyparts[0] if bodyparts else "index0")
