from __future__ import annotations

from argparse import Namespace

import pandas as pd

from cpp_dlc_live.cli import _cmd_analyze_batch, _discover_session_dirs


def _write_minimal_log(path) -> None:
    df = pd.DataFrame(
        {
            "t_wall": [0.0, 1.0, 2.0],
            "frame_idx": [0, 1, 2],
            "x": [0.0, 1.0, 2.0],
            "y": [0.0, 0.0, 0.0],
            "chamber": ["chamber1", "chamber2", "chamber1"],
            "laser_state": [1, 0, 1],
        }
    )
    path.write_text(df.to_csv(index=False), encoding="utf-8")


def test_discover_session_dirs_supports_prefixed_and_plain_logs(tmp_path) -> None:
    s1 = tmp_path / "session_a"
    s2 = tmp_path / "session_b"
    s1.mkdir()
    s2.mkdir()
    _write_minimal_log(s1 / "cpp_realtime_log.csv")
    _write_minimal_log(s2 / "session_abc_cpp_realtime_log.csv")

    found = _discover_session_dirs(tmp_path, recursive=False)
    found_names = sorted([p.name for p in found])
    assert found_names == ["session_a", "session_b"]


def test_cmd_analyze_batch_writes_report(tmp_path) -> None:
    s1 = tmp_path / "session_a"
    s2 = tmp_path / "session_b"
    s1.mkdir()
    s2.mkdir()
    _write_minimal_log(s1 / "cpp_realtime_log.csv")
    _write_minimal_log(s2 / "session_abc_cpp_realtime_log.csv")

    args = Namespace(
        root_dir=str(tmp_path),
        recursive=False,
        cm_per_px=None,
        fixed_fps=None,
        fixed_fps_hz=None,
        no_plots=True,
        include_issues=False,
        fail_fast=False,
        report_name="batch_analysis_report.csv",
    )
    _cmd_analyze_batch(args)

    report = pd.read_csv(tmp_path / "batch_analysis_report.csv")
    assert len(report) == 2
    assert set(report["status"]) == {"ok"}
