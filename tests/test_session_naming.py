from __future__ import annotations

from cpp_dlc_live.utils.io_utils import (
    build_session_suffix,
    detect_session_file_prefix,
    ensure_prefixed_filename,
    prepare_session_dir,
    resolve_session_file,
)


def test_build_session_suffix_formats_duration() -> None:
    suffix = build_session_suffix(
        {
            "mouse_id": "Mouse 01",
            "group": "CPP-Drug",
            "experiment_duration_s": 600,
        }
    )
    assert suffix == "Mouse-01_CPP-Drug_600s"


def test_build_session_suffix_includes_laser_mode_and_freq_when_present() -> None:
    suffix = build_session_suffix(
        {
            "mouse_id": "M001",
            "group": "pre",
            "experiment_duration_s": 1200,
            "laser_mode": "pulse",
            "pulse_freq_hz": 20.0,
        }
    )
    assert suffix == "M001_pre_1200s_pulse20Hz"


def test_build_session_suffix_includes_laser_on_chambers_when_present() -> None:
    suffix = build_session_suffix(
        {
            "mouse_id": "M001",
            "group": "pre",
            "experiment_duration_s": 1200,
            "laser_mode": "continuous",
            "laser_on_chambers": ["chamber2"],
        }
    )
    assert suffix == "M001_pre_1200s_continuous_onCh2"


def test_ensure_prefixed_filename_preserves_subdir_and_no_double_prefix() -> None:
    out = ensure_prefixed_filename("videos/preview_overlay.mp4", "session_20260317")
    assert out == "videos/session_20260317_preview_overlay.mp4"

    out2 = ensure_prefixed_filename(out, "session_20260317")
    assert out2 == out


def test_prepare_session_dir_appends_session_suffix(tmp_path) -> None:
    cfg = {
        "project": {
            "out_dir": str(tmp_path),
            "session_id": "auto_timestamp",
        },
        "session_info": {
            "mouse_id": "M009",
            "group": "A组",
            "experiment_duration_s": 120,
        },
    }
    session_dir = prepare_session_dir(cfg)

    assert session_dir.exists()
    resolved = cfg["project"]["resolved_session_id"]
    assert resolved.endswith("M009_A组_120s")
    assert cfg["project"]["resolved_file_prefix"] == resolved


def test_resolve_prefixed_session_files(tmp_path) -> None:
    prefix = "session_20260317_113000_M001_CTL_600s"
    prefixed_meta = tmp_path / f"{prefix}_metadata.json"
    prefixed_meta.write_text("{}", encoding="utf-8")
    prefixed_log = tmp_path / f"{prefix}_cpp_realtime_log.csv"
    prefixed_log.write_text("frame_idx\n0\n", encoding="utf-8")

    assert detect_session_file_prefix(tmp_path) == prefix
    assert resolve_session_file(tmp_path, "metadata.json") == prefixed_meta
    assert resolve_session_file(tmp_path, "cpp_realtime_log.csv") == prefixed_log
