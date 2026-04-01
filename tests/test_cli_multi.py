from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from cpp_dlc_live import cli
from cpp_dlc_live.utils.io_utils import save_yaml


def _write_config(path: Path, camera_source, laser_control: dict) -> None:
    save_yaml(
        {
            "project": {"name": "cpp_dlc_live", "session_id": "auto_timestamp", "out_dir": str(path.parent / "out")},
            "camera": {"source": camera_source, "fps_target": 20},
            "session_info": {"mouse_id": "M001", "group": "G", "experiment_duration_s": 60},
            "laser_control": laser_control,
        },
        path,
    )


def test_validate_multi_run_specs_camera_conflict() -> None:
    specs = [
        {"config_path": Path("a.yaml"), "camera_key": "cam_index:0", "laser_resources": []},
        {"config_path": Path("b.yaml"), "camera_key": "cam_index:0", "laser_resources": []},
    ]
    with pytest.raises(ValueError, match="camera source conflict"):
        cli._validate_multi_run_specs(specs=specs, allow_shared_camera=False, allow_shared_ni=False)


def test_validate_multi_run_specs_ni_conflict() -> None:
    specs = [
        {"config_path": Path("a.yaml"), "camera_key": "cam_index:0", "laser_resources": ["ctr:cdaq1mod4/ctr0"]},
        {"config_path": Path("b.yaml"), "camera_key": "cam_index:1", "laser_resources": ["ctr:cdaq1mod4/ctr0"]},
    ]
    with pytest.raises(ValueError, match="NI resource conflict"):
        cli._validate_multi_run_specs(specs=specs, allow_shared_camera=True, allow_shared_ni=False)


def test_build_run_multi_command_contains_required_flags(tmp_path) -> None:
    cfg = tmp_path / "a.yaml"
    cmd = cli._build_run_multi_command(
        config_path=cfg,
        out_dir=str(tmp_path / "exp_01"),
        duration_s=30,
        fixed_fps=20,
        no_preview=True,
        no_auto_analyze=True,
    )
    text = " ".join(cmd)
    assert "run_realtime" in text
    assert "--no_session_prompt" in text
    assert "--no_preview" in text
    assert "--no_auto_analyze" in text
    assert "--duration_s 30.0" in text
    assert "--fixed_fps 20.0" in text


def test_cmd_run_multi_launches_all_configs(tmp_path, monkeypatch) -> None:
    cfg1 = tmp_path / "cfg1.yaml"
    cfg2 = tmp_path / "cfg2.yaml"
    _write_config(cfg1, camera_source=0, laser_control={"enabled": False, "mode": "dryrun"})
    _write_config(cfg2, camera_source=1, laser_control={"enabled": False, "mode": "dryrun"})

    launched: list[list[str]] = []

    class DummyProc:
        _next_pid = 1000

        def __init__(self, cmd: list[str]):
            self.cmd = cmd
            self.pid = DummyProc._next_pid
            DummyProc._next_pid += 1
            self._poll_calls = 0

        def poll(self):
            self._poll_calls += 1
            if self._poll_calls <= 1:
                return None
            return 0

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    def fake_popen(cmd):
        launched.append(list(cmd))
        return DummyProc(list(cmd))

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli.time, "sleep", lambda _x: None)

    args = Namespace(
        configs=[str(cfg1), str(cfg2)],
        out_dir=None,
        duration_s=None,
        fixed_fps=None,
        no_preview=True,
        no_auto_analyze=True,
        fail_fast=False,
        allow_shared_camera=False,
        allow_shared_ni=False,
    )
    cli._cmd_run_multi(args)

    assert len(launched) == 2
    assert all("--no_session_prompt" in cmd for cmd in launched)
