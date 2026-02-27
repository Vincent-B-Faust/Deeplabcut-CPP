from __future__ import annotations

import time
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_session_id(prefix: str = "session") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}"


def monotonic_time_s() -> float:
    return time.monotonic()
