from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

from cpp_dlc_live.realtime.controller_base import LaserControllerBase


class LaserControllerError(RuntimeError):
    pass


def _import_nidaqmx() -> Tuple[Any, Any]:
    try:
        import nidaqmx  # type: ignore
        from nidaqmx.constants import AcquisitionType  # type: ignore
    except Exception as exc:
        raise LaserControllerError("nidaqmx is not installed or NI-DAQmx driver is unavailable") from exc
    return nidaqmx, AcquisitionType


def _set_pulse_terminal(task: Any, pulse_term: Optional[str]) -> None:
    if not pulse_term:
        return
    try:
        task.co_channels.all.co_pulse_term = pulse_term
        return
    except Exception:
        pass
    try:
        task.channels.co_pulse_term = pulse_term
        return
    except Exception as exc:
        raise LaserControllerError(f"Failed to set pulse terminal: {pulse_term}") from exc


class DryRunLaserController(LaserControllerBase):
    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__()
        self.logger = logger or logging.getLogger("cpp_dlc_live")

    def start(self) -> None:
        self.current_state = False
        self.logger.info("DryRunLaserController started (no hardware output)")

    def set_state(self, on: bool) -> None:
        target = bool(on)
        if target != self.current_state:
            self.logger.debug("DryRun laser state -> %s", int(target))
        self.current_state = target

    def stop(self) -> None:
        self.current_state = False
        self.logger.info("DryRunLaserController stopped")


class NILaserControllerGated(LaserControllerBase):
    def __init__(
        self,
        ctr_channel: str,
        pulse_term: str,
        enable_line: str,
        freq_hz: float,
        duty_cycle: float,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__()
        self.ctr_channel = ctr_channel
        self.pulse_term = pulse_term
        self.enable_line = enable_line
        self.freq_hz = float(freq_hz)
        self.duty_cycle = float(duty_cycle)
        self.logger = logger or logging.getLogger("cpp_dlc_live")

        self._nidaqmx = None
        self._counter_task = None
        self._enable_task = None

    def start(self) -> None:
        nidaqmx, AcquisitionType = _import_nidaqmx()
        self._nidaqmx = nidaqmx

        try:
            self._counter_task = nidaqmx.Task("cpp_counter_gated")
            self._counter_task.co_channels.add_co_pulse_chan_freq(
                self.ctr_channel,
                freq=self.freq_hz,
                duty_cycle=self.duty_cycle,
            )
            _set_pulse_terminal(self._counter_task, self.pulse_term)
            self._counter_task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)

            self._enable_task = nidaqmx.Task("cpp_enable_gated")
            self._enable_task.do_channels.add_do_chan(self.enable_line)

            self._counter_task.start()
            self._enable_task.start()
            self._enable_task.write(False)
            self.current_state = False
            self.logger.info("NILaserControllerGated started")
        except Exception as exc:
            self.stop()
            raise LaserControllerError("Failed to start gated NI laser controller") from exc

    def set_state(self, on: bool) -> None:
        if self._enable_task is None:
            raise LaserControllerError("Gated NI controller is not started")
        try:
            self._enable_task.write(bool(on))
            self.current_state = bool(on)
        except Exception as exc:
            raise LaserControllerError("Failed to set gated laser state") from exc

    def stop(self) -> None:
        try:
            if self._enable_task is not None:
                try:
                    self._enable_task.write(False)
                except Exception:
                    pass
                try:
                    self._enable_task.stop()
                except Exception:
                    pass
                try:
                    self._enable_task.close()
                except Exception:
                    pass
        finally:
            self._enable_task = None

        try:
            if self._counter_task is not None:
                try:
                    self._counter_task.stop()
                except Exception:
                    pass
                try:
                    self._counter_task.close()
                except Exception:
                    pass
        finally:
            self._counter_task = None
            self.current_state = False


class NILaserControllerStartStop(LaserControllerBase):
    def __init__(
        self,
        ctr_channel: str,
        pulse_term: str,
        freq_hz: float,
        duty_cycle: float,
        min_on_s: float,
        min_off_s: float,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__()
        self.ctr_channel = ctr_channel
        self.pulse_term = pulse_term
        self.freq_hz = float(freq_hz)
        self.duty_cycle = float(duty_cycle)
        self.min_on_s = float(min_on_s)
        self.min_off_s = float(min_off_s)
        self.logger = logger or logging.getLogger("cpp_dlc_live")

        self._counter_task = None
        self._counter_running = False
        self._last_switch = time.monotonic()

    def start(self) -> None:
        nidaqmx, AcquisitionType = _import_nidaqmx()
        try:
            self._counter_task = nidaqmx.Task("cpp_counter_startstop")
            self._counter_task.co_channels.add_co_pulse_chan_freq(
                self.ctr_channel,
                freq=self.freq_hz,
                duty_cycle=self.duty_cycle,
            )
            _set_pulse_terminal(self._counter_task, self.pulse_term)
            self._counter_task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)
            self._counter_running = False
            self.current_state = False
            self._last_switch = time.monotonic()
            self.logger.info("NILaserControllerStartStop started")
        except Exception as exc:
            self.stop()
            raise LaserControllerError("Failed to start startstop NI laser controller") from exc

    def set_state(self, on: bool) -> None:
        if self._counter_task is None:
            raise LaserControllerError("StartStop NI controller is not started")

        target = bool(on)
        now = time.monotonic()

        try:
            if target and not self._counter_running:
                if (now - self._last_switch) < self.min_off_s:
                    return
                self._counter_task.start()
                self._counter_running = True
                self.current_state = True
                self._last_switch = now
            elif (not target) and self._counter_running:
                if (now - self._last_switch) < self.min_on_s:
                    return
                self._counter_task.stop()
                self._counter_running = False
                self.current_state = False
                self._last_switch = now
        except Exception as exc:
            raise LaserControllerError("Failed to set startstop laser state") from exc

    def stop(self) -> None:
        if self._counter_task is not None:
            try:
                if self._counter_running:
                    self._counter_task.stop()
            except Exception:
                pass
            try:
                self._counter_task.close()
            except Exception:
                pass
        self._counter_task = None
        self._counter_running = False
        self.current_state = False


def create_laser_controller(laser_cfg: Dict[str, Any], logger: Optional[logging.Logger] = None) -> LaserControllerBase:
    logger = logger or logging.getLogger("cpp_dlc_live")
    enabled = bool(laser_cfg.get("enabled", True))
    mode = str(laser_cfg.get("mode", "dryrun")).lower().strip()

    if not enabled or mode == "dryrun":
        return DryRunLaserController(logger=logger)

    freq_hz = float(laser_cfg.get("freq_hz", 20.0))
    duty_cycle = float(laser_cfg.get("duty_cycle", 0.05))
    ctr_channel = str(laser_cfg.get("ctr_channel", ""))
    pulse_term = str(laser_cfg.get("pulse_term", ""))

    if not ctr_channel:
        raise LaserControllerError("laser_control.ctr_channel is required for NI modes")

    if mode == "gated":
        enable_line = str(laser_cfg.get("enable_line", ""))
        if not enable_line:
            raise LaserControllerError("laser_control.enable_line is required for gated mode")
        return NILaserControllerGated(
            ctr_channel=ctr_channel,
            pulse_term=pulse_term,
            enable_line=enable_line,
            freq_hz=freq_hz,
            duty_cycle=duty_cycle,
            logger=logger,
        )

    if mode == "startstop":
        return NILaserControllerStartStop(
            ctr_channel=ctr_channel,
            pulse_term=pulse_term,
            freq_hz=freq_hz,
            duty_cycle=duty_cycle,
            min_on_s=float(laser_cfg.get("min_on_s", 0.2)),
            min_off_s=float(laser_cfg.get("min_off_s", 0.2)),
            logger=logger,
        )

    raise LaserControllerError(f"Unknown laser control mode: {mode}")
