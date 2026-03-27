from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from cpp_dlc_live.realtime.app import RealtimeApp


def _build_app(laser_cfg: Optional[Dict[str, Any]] = None, roi_cfg: Optional[Dict[str, Any]] = None) -> RealtimeApp:
    config: Dict[str, Any] = {
        "laser_control": dict(laser_cfg or {}),
        "roi": dict(roi_cfg or {}),
    }
    return RealtimeApp(config=config, session_dir=Path("."), preview=False)


def test_laser_on_chambers_default_is_chamber1() -> None:
    app = _build_app({"enabled": True})
    on_chambers = app._resolve_laser_on_chambers({"enabled": True})
    assert on_chambers == {"chamber1"}
    assert app._resolve_laser_target("chamber1", "unknown", on_chambers=on_chambers)
    assert not app._resolve_laser_target("chamber2", "unknown", on_chambers=on_chambers)


def test_laser_on_chambers_can_target_chamber2_only() -> None:
    laser_cfg = {"enabled": True, "on_chambers": ["chamber2"]}
    app = _build_app(laser_cfg)
    on_chambers = app._resolve_laser_on_chambers(laser_cfg)
    assert on_chambers == {"chamber2"}
    assert app._resolve_laser_target("chamber2", "unknown", on_chambers=on_chambers)
    assert not app._resolve_laser_target("chamber1", "unknown", on_chambers=on_chambers)


def test_laser_on_chambers_supports_alias_and_csv_string() -> None:
    laser_cfg = {"enabled": True, "on_chambers": "ch1, ch2"}
    app = _build_app(laser_cfg)
    on_chambers = app._resolve_laser_on_chambers(laser_cfg)
    assert on_chambers == {"chamber1", "chamber2"}


def test_laser_on_chambers_respects_unknown_policy_hold_last() -> None:
    laser_cfg = {"enabled": True, "on_chambers": ["chamber2"], "unknown_policy": "hold_last"}
    app = _build_app(laser_cfg)
    on_chambers = app._resolve_laser_on_chambers(laser_cfg)
    assert app._resolve_laser_target("unknown", "chamber2", on_chambers=on_chambers)
    assert not app._resolve_laser_target("unknown", "chamber1", on_chambers=on_chambers)


def test_laser_on_chambers_can_enable_neutral_when_strategy_off() -> None:
    laser_cfg = {"enabled": True, "on_chambers": ["neutral"]}
    roi_cfg = {"strategy_on_neutral": "off"}
    app = _build_app(laser_cfg, roi_cfg=roi_cfg)
    on_chambers = app._resolve_laser_on_chambers(laser_cfg)
    assert app._resolve_laser_target("neutral", "unknown", on_chambers=on_chambers)


def test_laser_on_chambers_invalid_input_falls_back_to_chamber1() -> None:
    app = _build_app({"enabled": True})
    on_chambers = app._resolve_laser_on_chambers({"on_chambers": ["bad_region"]})
    assert on_chambers == {"chamber1"}


def test_laser_on_chambers_none_disables_all_chamber_triggers() -> None:
    app = _build_app({"enabled": True})
    on_chambers = app._resolve_laser_on_chambers({"on_chambers": "none"})
    assert on_chambers == set()
    assert not app._resolve_laser_target("chamber1", "unknown", on_chambers=on_chambers)
    assert not app._resolve_laser_target("chamber2", "unknown", on_chambers=on_chambers)
    assert not app._resolve_laser_target("neutral", "chamber1", on_chambers=on_chambers)
