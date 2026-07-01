from __future__ import annotations

import logging

from cpp_dlc_live.realtime.performance import RuntimePriorityManager, normalize_runtime_priority_config


def test_normalize_runtime_priority_config_defaults() -> None:
    cfg = normalize_runtime_priority_config({})
    assert cfg["enabled"] is True
    assert cfg["level"] == "high"
    assert cfg["disable_windows_power_throttling"] is True
    assert cfg["windows_timer_resolution_ms"] == 1


def test_normalize_runtime_priority_config_invalid_level_fallback() -> None:
    cfg = normalize_runtime_priority_config({"level": "ultra"})
    assert cfg["level"] == "high"


def test_runtime_priority_manager_disabled_apply() -> None:
    manager = RuntimePriorityManager({"enabled": False}, logger=logging.getLogger("test"))
    result = manager.apply()
    assert result["enabled"] is False
    assert result["applied"] is False
    assert "disabled" in result["actions"]


def test_runtime_priority_manager_posix_path_with_mocked_nice(monkeypatch) -> None:
    state = {"nice": 0}

    def fake_nice(delta: int) -> int:
        state["nice"] += int(delta)
        return state["nice"]

    import cpp_dlc_live.realtime.performance as perf_mod

    monkeypatch.setattr(perf_mod.sys, "platform", "linux")
    monkeypatch.setattr(perf_mod.os, "nice", fake_nice, raising=False)

    manager = RuntimePriorityManager({"enabled": True, "level": "high"}, logger=logging.getLogger("test"))
    result = manager.apply()
    assert result["enabled"] is True
    assert result["requested_level"] == "high"
    assert result["applied"] is True
