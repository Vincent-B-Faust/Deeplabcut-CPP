from __future__ import annotations

import json

import pandas as pd
import pytest

from cpp_dlc_live.analysis.analyze import analyze_session


def _write_log(path) -> pd.DataFrame:
    # Irregular wall-clock spacing to distinguish wall-time vs fixed-fps metrics.
    df = pd.DataFrame(
        {
            "t_wall": [0.0, 0.2, 1.5, 1.7, 3.9],
            "frame_idx": [0, 1, 2, 3, 4],
            "x": [0.0, 1.0, 2.0, 3.0, 4.0],
            "y": [0.0, 0.0, 0.0, 0.0, 0.0],
            "chamber": ["chamber1", "chamber1", "chamber2", "chamber2", "neutral"],
            "laser_state": [1, 1, 0, 0, 0],
        }
    )
    path.write_text(df.to_csv(index=False), encoding="utf-8")
    return df


def test_analyze_session_auto_timebase_prefers_wall_for_realtime(tmp_path) -> None:
    _write_log(tmp_path / "cpp_realtime_log.csv")
    # fixed_fps is configured, but realtime(default auto mode) should still use wall clock.
    (tmp_path / "config_used.yaml").write_text(
        "fixed_fps: 2\nanalysis:\n  output_plots: false\n",
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(json.dumps({"offline_fast": False}), encoding="utf-8")

    summary_path = analyze_session(session_dir=tmp_path, output_plots_override=False)
    summary = pd.read_csv(summary_path).iloc[0]

    # Wall-time result for this trace:
    # dt=[0.2,1.3,0.2,2.2,0.75], dt_state first=0
    # ch1=1.3, ch2=2.4, neutral=0.75, total=4.65
    assert summary["time_ch1_s"] == pytest.approx(1.3, rel=1e-6)
    assert summary["time_ch2_s"] == pytest.approx(2.4, rel=1e-6)
    assert summary["session_duration_s"] == pytest.approx(4.65, rel=1e-6)


def test_analyze_session_auto_timebase_uses_fixed_for_offline_fast(tmp_path) -> None:
    _write_log(tmp_path / "cpp_realtime_log.csv")
    (tmp_path / "config_used.yaml").write_text(
        "fixed_fps: 2\nanalysis:\n  output_plots: false\n",
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(json.dumps({"offline_fast": True}), encoding="utf-8")

    summary_path = analyze_session(session_dir=tmp_path, output_plots_override=False)
    summary = pd.read_csv(summary_path).iloc[0]

    # Fixed-fps=2 result:
    # dt=[0.5]*5, dt_state first=0
    # ch1=0.5, ch2=1.0, neutral=0.5, total=2.5
    assert summary["time_ch1_s"] == pytest.approx(0.5, rel=1e-6)
    assert summary["time_ch2_s"] == pytest.approx(1.0, rel=1e-6)
    assert summary["session_duration_s"] == pytest.approx(2.5, rel=1e-6)

