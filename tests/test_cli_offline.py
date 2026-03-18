from __future__ import annotations

from argparse import Namespace

from cpp_dlc_live import cli
from cpp_dlc_live.utils.io_utils import load_yaml, save_yaml


def test_cmd_run_offline_forces_fast_replay_and_dryrun(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    save_yaml(
        {
            "project": {"name": "cpp_dlc_live", "session_id": "auto_timestamp", "out_dir": str(tmp_path)},
            "camera": {"source": "input.mp4", "fps_target": 20, "enforce_fps": True},
            "laser_control": {"enabled": True, "mode": "startstop", "fallback_to_dryrun": False},
            "analysis": {"auto_after_run": False, "output_plots": True},
        },
        config_path,
    )

    captured = {}

    class DummyApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self) -> int:
            return 0

    monkeypatch.setattr(cli, "RealtimeApp", DummyApp)

    args = Namespace(
        config=str(config_path),
        out_dir=str(tmp_path),
        video=None,
        camera_source=None,
        duration_s=None,
        fixed_fps=25.0,
        preview=False,
        mouse_id=None,
        group=None,
        experiment_duration_s=None,
        no_auto_analyze=True,
    )
    cli._cmd_run_offline(args)

    assert captured["offline_fast"] is True
    assert captured["preview"] is False
    assert captured["duration_s"] is None
    assert float(captured["config"]["fixed_fps"]) == 25.0
    assert captured["config"]["camera"]["enforce_fps"] is False
    assert captured["config"]["camera"]["file_realtime_throttle"] is False

    session_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert session_dirs
    used_candidates = list(session_dirs[0].glob("*_config_used.yaml"))
    assert used_candidates
    used = load_yaml(used_candidates[0])

    assert float(used["fixed_fps"]) == 25.0
    assert used["camera"]["file_realtime_throttle"] is False
    assert used["camera"]["enforce_fps"] is False
    assert used["laser_control"]["mode"] == "dryrun"
    assert used["laser_control"]["fallback_to_dryrun"] is True
