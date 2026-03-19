from __future__ import annotations

import pytest

from cpp_dlc_live.realtime.controller_ni import (
    LaserControllerError,
    NILaserControllerContinuous,
    NILaserControllerGated,
    NILaserControllerStartStop,
    create_laser_controller,
)


def test_create_laser_controller_continuous_mode() -> None:
    controller = create_laser_controller(
        {
            "enabled": True,
            "mode": "continuous",
            "continuous_line": "cDAQ1Mod4/port0/line0",
        }
    )
    assert isinstance(controller, NILaserControllerContinuous)


def test_create_laser_controller_continues_alias() -> None:
    controller = create_laser_controller(
        {
            "enabled": True,
            "mode": "continues",
            "continuous_line": "cDAQ1Mod4/port0/line0",
        }
    )
    assert isinstance(controller, NILaserControllerContinuous)


def test_create_laser_controller_continuous_uses_enable_line_fallback() -> None:
    controller = create_laser_controller(
        {
            "enabled": True,
            "mode": "continuous",
            "enable_line": "cDAQ1Mod4/port0/line0",
        }
    )
    assert isinstance(controller, NILaserControllerContinuous)


def test_create_laser_controller_pulse_alias_defaults_to_gated() -> None:
    controller = create_laser_controller(
        {
            "enabled": True,
            "mode": "pulse",
            "ctr_channel": "cDAQ1Mod4/ctr0",
            "pulse_term": "/cDAQ1Mod4/PFI0",
            "enable_line": "cDAQ1Mod4/port0/line0",
            "freq_hz": 20.0,
            "duty_cycle": 0.05,
        }
    )
    assert isinstance(controller, NILaserControllerGated)


def test_create_laser_controller_pulse_alias_supports_startstop() -> None:
    controller = create_laser_controller(
        {
            "enabled": True,
            "mode": "pulse",
            "pulse_mode": "startstop",
            "ctr_channel": "cDAQ1Mod4/ctr0",
            "pulse_term": "/cDAQ1Mod4/PFI0",
            "freq_hz": 20.0,
            "duty_cycle": 0.05,
            "min_on_s": 0.2,
            "min_off_s": 0.2,
        }
    )
    assert isinstance(controller, NILaserControllerStartStop)


def test_create_laser_controller_pulse_mode_validation() -> None:
    with pytest.raises(LaserControllerError):
        create_laser_controller(
            {
                "enabled": True,
                "mode": "pulse",
                "pulse_mode": "bad",
                "ctr_channel": "cDAQ1Mod4/ctr0",
            }
        )
