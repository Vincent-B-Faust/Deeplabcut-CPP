from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


class SessionIssueLogger:
    """Structured runtime issue logger for post-hoc troubleshooting."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = bool(enabled)
        self._file = None
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a", encoding="utf-8")

    def log(self, event: str, level: str = "INFO", **fields: Any) -> None:
        if not self.enabled or self._file is None:
            return
        record: Dict[str, Any] = {
            "t_wall": time.time(),
            "event": str(event),
            "level": str(level).upper(),
        }
        record.update(fields)
        self._file.write(json.dumps(_json_safe(record), ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
