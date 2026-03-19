from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from cpp_dlc_live.utils.time_utils import make_session_id

PathLike = Union[str, Path]


def ensure_dir(path: PathLike) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def load_yaml(path: PathLike) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be mapping: {path}")
    return data


def save_yaml(data: Dict[str, Any], path: PathLike) -> None:
    with Path(path).open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def save_json(data: Dict[str, Any], path: PathLike) -> None:
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def file_sha256(path: PathLike) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_session_dir(config: Dict[str, Any], out_dir_override: Optional[str] = None) -> Path:
    project_cfg = config.setdefault("project", {})
    base_dir = out_dir_override or project_cfg.get("out_dir", "./data")
    session_id_raw = str(project_cfg.get("session_id", "auto_timestamp"))
    session_id = session_id_raw
    if session_id_raw in {"auto", "auto_timestamp", ""}:
        session_id = make_session_id("session")

    session_info = config.get("session_info", {})
    suffix = build_session_suffix(session_info if isinstance(session_info, dict) else {})
    if suffix:
        session_id = f"{session_id}_{suffix}"

    project_cfg["resolved_session_id"] = session_id
    project_cfg["resolved_file_prefix"] = session_id
    session_dir = ensure_dir(Path(base_dir) / session_id)
    return session_dir


def ensure_prefixed_filename(filename: str, prefix: str) -> str:
    raw = str(filename).strip()
    path = Path(raw)
    base = path.name
    expected = f"{prefix}_"
    if base.startswith(expected):
        return raw
    renamed = path.with_name(f"{prefix}_{base}")
    return str(renamed)


def build_session_suffix(session_info: Dict[str, Any]) -> str:
    mouse_id = sanitize_name_component(session_info.get("mouse_id"))
    group = sanitize_name_component(session_info.get("group"))
    duration = _format_duration_for_name(session_info.get("experiment_duration_s"))
    laser_mode = _format_laser_mode_for_name(
        session_info.get("laser_mode"),
        session_info.get("pulse_freq_hz"),
    )

    parts = [p for p in [mouse_id, group, duration, laser_mode] if p]
    return "_".join(parts)


def sanitize_name_component(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return ""
    text = text.replace(" ", "-")
    text = re.sub(r"[^\w\-\u4e00-\u9fff]+", "", text, flags=re.UNICODE)
    return text[:64]


def _format_duration_for_name(value: Any) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except Exception:
        return sanitize_name_component(value)
    if v <= 0:
        return ""
    if v.is_integer():
        return f"{int(v)}s"
    text = f"{v:.3f}".rstrip("0").rstrip(".").replace(".", "p")
    return f"{text}s"


def _format_laser_mode_for_name(mode: Any, pulse_freq_hz: Any) -> str:
    if mode is None:
        return ""
    raw = str(mode).strip().lower()
    if not raw:
        return ""
    if raw in {"none", "null"}:
        return ""

    if raw in {"continuous", "continues", "level"}:
        return "continuous"

    if raw in {"pulse", "gated", "startstop"}:
        try:
            freq = float(pulse_freq_hz)
        except Exception:
            return "pulse"
        if freq <= 0:
            return "pulse"
        if float(freq).is_integer():
            return f"pulse{int(freq)}Hz"
        text = f"{freq:.3f}".rstrip("0").rstrip(".").replace(".", "p")
        return f"pulse{text}Hz"

    return sanitize_name_component(raw)


def detect_session_file_prefix(session_dir: PathLike) -> Optional[str]:
    session_path = Path(session_dir)
    prefixed_meta = sorted(session_path.glob("*_metadata.json"))
    if prefixed_meta:
        name = prefixed_meta[0].name
        return name[: -len("_metadata.json")]
    return None


def resolve_session_file(session_dir: PathLike, base_name: str) -> Path:
    session_path = Path(session_dir)
    direct = session_path / base_name
    if direct.exists():
        return direct

    matches = sorted(session_path.glob(f"*_{base_name}"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return max(matches, key=lambda p: p.stat().st_mtime)
    return direct
