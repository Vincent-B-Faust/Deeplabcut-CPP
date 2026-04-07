from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any, Dict, Optional


_VALID_LEVELS = {"normal", "above_normal", "high", "realtime"}


def normalize_runtime_priority_config(raw_cfg: Any) -> Dict[str, Any]:
    """Normalize runtime priority config into a predictable dict.

    Config keys:
    - enabled: bool, default True
    - level: normal|above_normal|high|realtime, default high
    - disable_windows_power_throttling: bool, default True
    - windows_timer_resolution_ms: optional int, default 1
    """
    cfg = dict(raw_cfg) if isinstance(raw_cfg, dict) else {}
    enabled = bool(cfg.get("enabled", True))
    level_raw = str(cfg.get("level", "high")).strip().lower()
    level = level_raw if level_raw in _VALID_LEVELS else "high"

    timer_raw = cfg.get("windows_timer_resolution_ms", 1)
    timer_ms: Optional[int]
    try:
        timer_ms = int(float(timer_raw))
    except Exception:
        timer_ms = 1
    if timer_ms <= 0:
        timer_ms = None

    return {
        "enabled": enabled,
        "level": level,
        "disable_windows_power_throttling": bool(cfg.get("disable_windows_power_throttling", True)),
        "windows_timer_resolution_ms": timer_ms,
    }


class RuntimePriorityManager:
    """Best-effort process priority tuning for realtime loop stability.

    This manager never raises on failure; it only reports applied/failed actions.
    """

    def __init__(self, raw_cfg: Any, logger):
        self.cfg = normalize_runtime_priority_config(raw_cfg)
        self.logger = logger
        self._timer_period_ms: Optional[int] = None
        self._winmm = None
        self._applied = False
        self._result: Dict[str, Any] = {
            "enabled": bool(self.cfg.get("enabled", True)),
            "platform": sys.platform,
            "requested_level": self.cfg.get("level"),
            "applied": False,
            "actions": [],
            "warnings": [],
        }

    def apply(self) -> Dict[str, Any]:
        if not self.cfg.get("enabled", True):
            self._result["applied"] = False
            self._result["actions"].append("disabled")
            return dict(self._result)

        try:
            if sys.platform.startswith("win"):
                self._apply_windows()
            else:
                self._apply_posix()
        except Exception as exc:
            self._result["warnings"].append(f"unexpected_apply_error:{type(exc).__name__}:{exc}")

        self._result["applied"] = self._applied
        return dict(self._result)

    def restore(self) -> Dict[str, Any]:
        restored_actions: list[str] = []
        warnings: list[str] = []
        if self._timer_period_ms is not None and self._winmm is not None:
            try:
                rc = int(self._winmm.timeEndPeriod(int(self._timer_period_ms)))
                if rc == 0:
                    restored_actions.append(f"timeEndPeriod({self._timer_period_ms})")
                else:
                    warnings.append(f"timeEndPeriod_failed_rc={rc}")
            except Exception as exc:
                warnings.append(f"timeEndPeriod_error:{type(exc).__name__}:{exc}")
        return {
            "restored_actions": restored_actions,
            "warnings": warnings,
        }

    def _apply_posix(self) -> None:
        level = str(self.cfg.get("level", "high"))
        target_nice = {
            "normal": None,
            "above_normal": -5,
            "high": -10,
            "realtime": -15,
        }.get(level, -10)
        if target_nice is None:
            self._result["actions"].append("posix_level_normal")
            self._applied = True
            return

        try:
            current_nice = int(os.nice(0))
        except Exception as exc:
            self._result["warnings"].append(f"get_nice_failed:{type(exc).__name__}:{exc}")
            return

        if target_nice >= current_nice:
            self._result["actions"].append(f"nice_unchanged:{current_nice}")
            self._applied = True
            return

        delta = target_nice - current_nice
        try:
            new_nice = int(os.nice(delta))
            self._result["actions"].append(f"nice:{current_nice}->{new_nice}")
            self._applied = True
        except Exception as exc:
            self._result["warnings"].append(
                f"set_nice_failed:{type(exc).__name__}:{exc} (need higher privileges?)"
            )

    def _apply_windows(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        proc = kernel32.GetCurrentProcess()
        thread = kernel32.GetCurrentThread()

        process_class = {
            "normal": 0x00000020,  # NORMAL_PRIORITY_CLASS
            "above_normal": 0x00008000,  # ABOVE_NORMAL_PRIORITY_CLASS
            "high": 0x00000080,  # HIGH_PRIORITY_CLASS
            "realtime": 0x00000100,  # REALTIME_PRIORITY_CLASS
        }.get(str(self.cfg.get("level", "high")), 0x00000080)

        if kernel32.SetPriorityClass(proc, process_class):
            self._result["actions"].append(f"SetPriorityClass({process_class:#x})")
            self._applied = True
        else:
            self._result["warnings"].append(f"SetPriorityClass_failed_winerr={ctypes.get_last_error()}")

        thread_priority = {
            "normal": 0,  # THREAD_PRIORITY_NORMAL
            "above_normal": 1,  # THREAD_PRIORITY_ABOVE_NORMAL
            "high": 2,  # THREAD_PRIORITY_HIGHEST
            "realtime": 15,  # THREAD_PRIORITY_TIME_CRITICAL
        }.get(str(self.cfg.get("level", "high")), 2)
        if kernel32.SetThreadPriority(thread, thread_priority):
            self._result["actions"].append(f"SetThreadPriority({thread_priority})")
            self._applied = True
        else:
            self._result["warnings"].append(f"SetThreadPriority_failed_winerr={ctypes.get_last_error()}")

        if bool(self.cfg.get("disable_windows_power_throttling", True)):
            self._apply_windows_disable_power_throttling(kernel32, proc)

        timer_ms = self.cfg.get("windows_timer_resolution_ms")
        if timer_ms is not None and int(timer_ms) > 0:
            self._apply_windows_timer_resolution(int(timer_ms))

    def _apply_windows_disable_power_throttling(self, kernel32: Any, proc: Any) -> None:
        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.DWORD),
                ("ControlMask", wintypes.DWORD),
                ("StateMask", wintypes.DWORD),
            ]

        PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
        ProcessPowerThrottling = 4

        state = PROCESS_POWER_THROTTLING_STATE(
            Version=PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            ControlMask=PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            StateMask=0,
        )
        try:
            ok = kernel32.SetProcessInformation(
                proc,
                ProcessPowerThrottling,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
        except Exception as exc:
            self._result["warnings"].append(f"SetProcessInformation_error:{type(exc).__name__}:{exc}")
            return
        if ok:
            self._result["actions"].append("SetProcessInformation(ProcessPowerThrottling=disable)")
            self._applied = True
        else:
            self._result["warnings"].append(
                f"SetProcessInformation_failed_winerr={ctypes.get_last_error()}"
            )

    def _apply_windows_timer_resolution(self, timer_ms: int) -> None:
        timer_ms = max(1, min(16, int(timer_ms)))
        try:
            winmm = ctypes.WinDLL("winmm", use_last_error=True)
            rc = int(winmm.timeBeginPeriod(timer_ms))
        except Exception as exc:
            self._result["warnings"].append(f"timeBeginPeriod_error:{type(exc).__name__}:{exc}")
            return
        if rc == 0:
            self._timer_period_ms = timer_ms
            self._winmm = winmm
            self._result["actions"].append(f"timeBeginPeriod({timer_ms})")
            self._applied = True
        else:
            self._result["warnings"].append(f"timeBeginPeriod_failed_rc={rc}")
