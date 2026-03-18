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
    keypoints: Dict[str, tuple[float, float, float]]


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
        return PoseResult(
            x=x,
            y=y,
            p=p,
            bodypart=self.bodypart,
            keypoints={self.bodypart: (x, y, p)},
        )

    def model_info(self) -> Dict[str, Any]:
        return {
            "runtime": "mock",
            "model_path": None,
            "bodyparts": [self.bodypart],
            "snapshot": None,
            "notes": "Fallback runtime without deeplabcut-live",
        }


class DLCLiveRuntime(RuntimeBase):
    def __init__(
        self,
        model_path: str,
        bodypart: str = "center",
        backend: str = "auto",
        device: str = "auto",
    ):
        self.model_path = str(model_path)
        self.bodypart = bodypart
        self.backend = _normalize_backend(backend)
        self.device = _normalize_device(device)
        self._initialized = False
        self._runtime_device: Optional[str] = None

        try:
            from dlclive import DLCLive, Processor  # type: ignore
        except Exception as exc:
            raise RuntimeError("deeplabcut-live is not available") from exc

        self._model_cfg = _load_model_cfg(model_path)
        self._bodyparts = _extract_bodyparts(self._model_cfg)
        self._snapshot = _extract_snapshot(self._model_cfg)
        processor = Processor()

        # Prefer explicit backend selection for DLC 3.0 PyTorch models.
        model_type_value = _resolve_model_type_value(self.backend)
        self._dlc = _build_dlclive_instance(
            DLCLive=DLCLive,
            model_path=model_path,
            processor=processor,
            model_type_value=model_type_value,
            device_value=(None if self.device == "auto" else self.device),
        )

    def infer(self, frame: np.ndarray) -> PoseResult:
        if not self._initialized:
            self._dlc.init_inference(frame)
            self._initialized = True
            self._runtime_device = _resolve_runtime_device(self._dlc)

        pose = np.asarray(self._dlc.get_pose(frame))
        if pose.ndim != 2 or pose.shape[1] < 3:
            raise RuntimeError(f"Unexpected pose shape: {pose.shape}")

        x, y, p, resolved = _select_bodypart(pose, self._bodyparts, self.bodypart)
        keypoints = _extract_keypoints(pose=pose, bodyparts=self._bodyparts)
        if resolved not in keypoints:
            keypoints[resolved] = (float(x), float(y), float(p))
        # Keep a "center" alias when center is synthesized from nose/tailbase midpoint.
        if self.bodypart.strip().lower() == "center" and resolved == "nose_tailbase_midpoint":
            keypoints.setdefault("center", (float(x), float(y), float(p)))
        return PoseResult(
            x=float(x),
            y=float(y),
            p=float(p),
            bodypart=resolved,
            keypoints=keypoints,
        )

    def model_info(self) -> Dict[str, Any]:
        return {
            "runtime": "dlclive",
            "model_path": self.model_path,
            "bodyparts": self._bodyparts,
            "target_bodypart": self.bodypart,
            "backend": self.backend,
            "device_requested": self.device,
            "device_runtime": self._runtime_device,
            "snapshot": self._snapshot,
        }


def build_runtime(dlc_cfg: Dict[str, Any], logger: Optional[logging.Logger] = None) -> RuntimeBase:
    bodypart = str(dlc_cfg.get("bodypart", "center"))
    backend = _normalize_backend(dlc_cfg.get("backend", "auto"))
    device = _normalize_device(dlc_cfg.get("device", "auto"))
    model_path = str(dlc_cfg.get("model_path", "")).strip()

    if model_path and Path(model_path).exists():
        try:
            torch_info = _probe_torch_env()
            if logger:
                if "import_error" in torch_info:
                    logger.warning("PyTorch import failed: %s", torch_info["import_error"])
                else:
                    logger.info(
                        "PyTorch env: version=%s cuda_available=%s cuda_version=%s device_count=%s",
                        torch_info.get("torch_version"),
                        torch_info.get("cuda_available"),
                        torch_info.get("cuda_version"),
                        torch_info.get("cuda_device_count"),
                    )
                    if str(device).startswith("cuda") and not bool(torch_info.get("cuda_available", False)):
                        logger.warning(
                            "dlc.device=%s requested, but torch.cuda.is_available() is False; inference will run on CPU",
                            device,
                        )

            runtime = DLCLiveRuntime(
                model_path=model_path,
                bodypart=bodypart,
                backend=backend,
                device=device,
            )
            if logger:
                logger.info(
                    "Using DLCLive runtime from %s (backend=%s, device=%s)",
                    model_path,
                    backend,
                    device,
                )
            return runtime
        except Exception:
            if logger:
                logger.exception("Failed to initialize DLCLive runtime, falling back to mock")

    if logger:
        logger.warning("Using mock DLC runtime (no valid model path or DLCLive unavailable)")
    return MockDLCRuntime(bodypart=bodypart)


def _load_model_cfg(model_path: str) -> Dict[str, Any]:
    candidates = _candidate_model_cfg_paths(model_path)
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


def _candidate_model_cfg_paths(model_path: str) -> List[Path]:
    path = Path(model_path)
    base_dir = path.parent if path.is_file() else path
    return [
        # DLC 3.0 PyTorch export usually stores bodypart names here (metadata.bodyparts).
        base_dir / "pytorch_config.yaml",
        # Legacy TensorFlow-style configs.
        base_dir / "pose_cfg.yaml",
        base_dir / "config.yaml",
        base_dir / "dlc-models" / "pose_cfg.yaml",
    ]


def _extract_bodyparts(model_cfg: Dict[str, Any]) -> List[str]:
    names = model_cfg.get("all_joints_names") or model_cfg.get("bodyparts")
    parsed = _normalize_bodypart_names(names)
    if parsed:
        return parsed

    metadata = model_cfg.get("metadata", {})
    if isinstance(metadata, dict):
        names = metadata.get("all_joints_names") or metadata.get("bodyparts")
        parsed = _normalize_bodypart_names(names)
        if parsed:
            return parsed

    return []


def _extract_snapshot(model_cfg: Dict[str, Any]) -> Optional[str]:
    for key in ("init_weights", "snapshot_prefix", "snapshot"):
        value = model_cfg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = model_cfg.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ("init_weights", "snapshot_prefix", "snapshot"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_keypoints(pose: np.ndarray, bodyparts: List[str]) -> Dict[str, tuple[float, float, float]]:
    points: Dict[str, tuple[float, float, float]] = {}
    n = int(pose.shape[0]) if pose.ndim >= 2 else 0
    for idx in range(n):
        row = pose[idx]
        name = bodyparts[idx] if idx < len(bodyparts) else f"kp{idx}"
        points[str(name)] = (float(row[0]), float(row[1]), float(row[2]))
    return points


def _normalize_bodypart_names(raw_names: Any) -> List[str]:
    if isinstance(raw_names, list) and raw_names:
        names: List[str] = []
        seen: set[str] = set()
        for n in raw_names:
            label = str(n).strip()
            if not label or label in seen:
                continue
            names.append(label)
            seen.add(label)
        return names
    return []


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


def _normalize_backend(value: Any) -> str:
    text = str(value or "auto").strip().lower()
    if text in {"pytorch", "torch"}:
        return "pytorch"
    if text in {"tensorflow", "tf"}:
        return "tensorflow"
    return "auto"


def _resolve_model_type_value(backend: str) -> Any:
    if backend == "auto":
        return None

    try:
        from dlclive.enums import PoseEstimationModelType  # type: ignore

        enum_name = "PYTORCH" if backend == "pytorch" else "TENSORFLOW"
        if hasattr(PoseEstimationModelType, enum_name):
            return getattr(PoseEstimationModelType, enum_name)
    except Exception:
        pass

    # Fallback for dlclive builds that accept string model type.
    return backend


def _normalize_device(value: Any) -> str:
    text = str(value or "auto").strip().lower()
    if not text:
        return "auto"
    if text in {"auto", "cpu", "cuda"}:
        return text
    if text.startswith("cuda:"):
        suffix = text.split(":", 1)[1].strip()
        if suffix.isdigit():
            return f"cuda:{suffix}"
    return text


def _build_dlclive_instance(
    DLCLive: Any,
    model_path: str,
    processor: Any,
    model_type_value: Any,
    device_value: Optional[str],
) -> Any:
    # Try richer signatures first, then degrade for backward compatibility.
    kwargs_attempts = []
    full_kwargs: Dict[str, Any] = {"processor": processor}
    if model_type_value is not None:
        full_kwargs["model_type"] = model_type_value
    if device_value is not None:
        full_kwargs["device"] = device_value
    kwargs_attempts.append(full_kwargs)

    if "device" in full_kwargs:
        no_device = dict(full_kwargs)
        no_device.pop("device", None)
        kwargs_attempts.append(no_device)

    if "model_type" in full_kwargs:
        no_model_type = dict(full_kwargs)
        no_model_type.pop("model_type", None)
        kwargs_attempts.append(no_model_type)

    kwargs_attempts.append({"processor": processor})

    last_error: Optional[TypeError] = None
    for kwargs in kwargs_attempts:
        try:
            return DLCLive(model_path, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to construct DLCLive runtime")


def _resolve_runtime_device(dlc_obj: Any) -> Optional[str]:
    try:
        runner = getattr(dlc_obj, "runner", None)
        if runner is None:
            return None
        value = getattr(runner, "device", None)
        if value is None:
            return None
        return str(value)
    except Exception:
        return None


def _probe_torch_env() -> Dict[str, Any]:
    try:
        import torch  # type: ignore
    except Exception as exc:
        return {"import_error": str(exc)}

    info: Dict[str, Any] = {
        "torch_version": getattr(torch, "__version__", None),
        "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
    }
    try:
        info["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:
        info["cuda_available"] = False
    try:
        info["cuda_device_count"] = int(torch.cuda.device_count())
    except Exception:
        info["cuda_device_count"] = 0
    return info
