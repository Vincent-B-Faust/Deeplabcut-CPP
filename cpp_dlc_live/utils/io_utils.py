from __future__ import annotations

import hashlib
import json
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
    session_id = str(project_cfg.get("session_id", "auto_timestamp"))
    if session_id in {"auto", "auto_timestamp", ""}:
        session_id = make_session_id("session")
    project_cfg["resolved_session_id"] = session_id
    session_dir = ensure_dir(Path(base_dir) / session_id)
    return session_dir
