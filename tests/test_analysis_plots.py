from __future__ import annotations

import json

import pandas as pd

from cpp_dlc_live.analysis.analyze import analyze_session
from cpp_dlc_live.analysis.plots import _resolve_spatial_limits


def test_analyze_session_generates_figure1_to_5_with_prefix(tmp_path) -> None:
    prefix = "session_20260317_120000_M001_Control_600s"

    df = pd.DataFrame(
        {
            "t_wall": [0.0, 1.0, 2.0, 3.0, 4.0],
            "frame_idx": [0, 1, 2, 3, 4],
            "x": [10.0, 20.0, 30.0, 30.0, 25.0],
            "y": [10.0, 10.0, 15.0, 25.0, 35.0],
            "chamber": ["chamber1", "chamber1", "chamber2", "chamber2", "chamber1"],
            "laser_state": [1, 1, 0, 0, 1],
        }
    )
    (tmp_path / f"{prefix}_cpp_realtime_log.csv").write_text(df.to_csv(index=False), encoding="utf-8")

    (tmp_path / f"{prefix}_config_used.yaml").write_text(
        "analysis:\n  output_plots: true\nroi:\n  chamber1: [[0,0],[40,0],[40,20],[0,20]]\n  chamber2: [[0,20],[40,20],[40,40],[0,40]]\n",
        encoding="utf-8",
    )
    (tmp_path / f"{prefix}_metadata.json").write_text(json.dumps({"file_prefix": prefix}), encoding="utf-8")

    summary_path = analyze_session(session_dir=tmp_path, output_plots_override=True)
    assert summary_path.name == f"{prefix}_summary.csv"
    assert summary_path.exists()

    expected = [
        f"{prefix}_figure1_trajectory_speed_heatmap.png",
        f"{prefix}_figure2_position_heatmap.png",
        f"{prefix}_figure3_chamber_dwell.png",
        f"{prefix}_speed_over_time.png",
        f"{prefix}_occupancy_over_time.png",
    ]
    for name in expected:
        assert (tmp_path / name).exists(), name


def test_spatial_limits_prioritize_roi_over_frame_shape() -> None:
    roi_cfg = {
        "chamber1": [[100, 100], [300, 100], [300, 400], [100, 400]],
        "chamber2": [[320, 100], [520, 100], [520, 400], [320, 400]],
    }
    x_min, x_max, y_min, y_max = _resolve_spatial_limits(
        frame_shape=(1280, 720),
        x_values=pd.Series([150.0, 500.0]).to_numpy(dtype=float),
        y_values=pd.Series([120.0, 380.0]).to_numpy(dtype=float),
        roi_cfg=roi_cfg,
    )
    assert (x_min, x_max, y_min, y_max) == (100.0, 520.0, 100.0, 400.0)


def test_analyze_session_time_range_outputs_to_subdir(tmp_path) -> None:
    prefix = "session_20260317_120000_M001_Control_600s"
    df = pd.DataFrame(
        {
            "t_wall": [float(i) for i in range(10)],
            "frame_idx": list(range(10)),
            "x": [10.0 + i for i in range(10)],
            "y": [20.0 + i for i in range(10)],
            "chamber": ["chamber1"] * 10,
            "laser_state": [1] * 10,
        }
    )
    (tmp_path / f"{prefix}_cpp_realtime_log.csv").write_text(df.to_csv(index=False), encoding="utf-8")
    (tmp_path / f"{prefix}_config_used.yaml").write_text("analysis:\n  output_plots: true\n", encoding="utf-8")
    (tmp_path / f"{prefix}_metadata.json").write_text(json.dumps({"file_prefix": prefix}), encoding="utf-8")

    summary_path = analyze_session(
        session_dir=tmp_path,
        output_plots_override=True,
        time_start_s=2.0,
        time_end_s=5.0,
    )

    assert summary_path.parent.name == "analysis_range_2s_to_5s"
    assert summary_path.exists()
    assert (summary_path.parent / f"{prefix}_occupancy_over_time.png").exists()
