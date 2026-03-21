from __future__ import annotations

from argparse import Namespace
from pathlib import Path

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


def test_discover_offline_videos_prefers_raw_video_in_session_folders(tmp_path) -> None:
    s1 = tmp_path / "session_a"
    s2 = tmp_path / "session_b"
    not_session = tmp_path / "misc_videos"
    s1.mkdir()
    s2.mkdir()
    not_session.mkdir()
    (s1 / "session_x_raw_video.mp4").write_bytes(b"")
    (s1 / "session_x_preview_overlay.mp4").write_bytes(b"")
    (s2 / "session_y_raw_video.avi").write_bytes(b"")
    (not_session / "some_raw_video.mp4").write_bytes(b"")

    found = cli._discover_offline_videos(tmp_path, recursive=True)
    names = [p.name for p in found]
    assert "session_x_raw_video.mp4" in names
    assert "session_y_raw_video.avi" in names
    assert "session_x_preview_overlay.mp4" not in names
    assert "some_raw_video.mp4" not in names


def test_cmd_run_offline_batch_supports_root_dir(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    save_yaml(
        {
            "project": {"name": "cpp_dlc_live", "session_id": "auto_timestamp", "out_dir": str(tmp_path / "out")},
            "camera": {"source": 0, "fps_target": 20},
            "laser_control": {"enabled": True, "mode": "startstop"},
            "analysis": {"auto_after_run": False},
        },
        cfg,
    )
    root = tmp_path / "videos"
    (root / "session_a").mkdir(parents=True)
    (root / "session_b").mkdir(parents=True)
    (root / "session_a" / "session_a_raw_video.mp4").write_bytes(b"dummy")
    (root / "session_b" / "session_b_raw_video.mp4").write_bytes(b"dummy")

    calls: list[Path] = []

    def fake_run_once(args, source_override, session_id_override):
        calls.append(Path(source_override))
        session_dir = tmp_path / f"session_{len(calls)}"
        session_dir.mkdir(exist_ok=True)
        return 0, session_dir

    monkeypatch.setattr(cli, "_run_offline_once", fake_run_once)

    args = Namespace(
        config=str(cfg),
        out_dir=None,
        video=None,
        camera_source=None,
        root_dir=str(root),
        recursive=True,
        fail_fast=False,
        batch_report_name="offline_batch_report.csv",
        duration_s=None,
        fixed_fps=None,
        preview=False,
        mouse_id=None,
        group=None,
        experiment_duration_s=None,
        no_auto_analyze=True,
    )
    cli._cmd_run_offline(args)

    assert len(calls) == 2
    report = root / "offline_batch_report.csv"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "status" in text and "session_dir" in text


def test_resolve_session_info_no_prompt_includes_laser_mode_and_freq() -> None:
    config = {
        "laser_control": {
            "mode": "startstop",
            "freq_hz": 25.0,
        },
        "acclimation": {
            "enabled": True,
            "duration_s": 30.0,
        },
    }
    args = Namespace(
        mouse_id="M001",
        group="test",
        experiment_duration_s=120.0,
        duration_s=None,
        no_session_prompt=True,
    )

    info = cli._resolve_session_info(config, args)
    assert info["laser_mode"] == "pulse"
    assert float(info["pulse_freq_hz"]) == 25.0
    assert info["acclimation_enabled"] is True
    assert float(info["acclimation_duration_s"]) == 30.0


def test_apply_session_laser_settings_preserves_legacy_pulse_mode() -> None:
    config = {
        "laser_control": {
            "mode": "startstop",
            "freq_hz": 20.0,
        }
    }
    session_info = {
        "laser_mode": "pulse",
        "pulse_freq_hz": 40.0,
    }

    cli._apply_session_laser_settings(config, session_info)
    assert config["laser_control"]["mode"] == "startstop"
    assert float(config["laser_control"]["freq_hz"]) == 40.0


def test_apply_session_laser_settings_switches_to_continuous() -> None:
    config = {
        "laser_control": {
            "mode": "startstop",
            "freq_hz": 20.0,
        }
    }
    session_info = {
        "laser_mode": "continuous",
        "pulse_freq_hz": None,
    }

    cli._apply_session_laser_settings(config, session_info)
    assert config["laser_control"]["mode"] == "continuous"


def test_apply_session_acclimation_settings() -> None:
    config = {"acclimation": {"enabled": False, "duration_s": 0}}
    session_info = {
        "acclimation_enabled": True,
        "acclimation_duration_s": 45.0,
    }
    cli._apply_session_acclimation_settings(config, session_info)
    assert config["acclimation"]["enabled"] is True
    assert float(config["acclimation"]["duration_s"]) == 45.0
