from __future__ import annotations

import json
from argparse import Namespace

import pandas as pd
import pytest

from cpp_dlc_live.cli import _cmd_analyze_group_summary


def _write_log(path, chambers: list[str]) -> None:
    n = len(chambers)
    df = pd.DataFrame(
        {
            "t_wall": [float(i) for i in range(n)],
            "frame_idx": list(range(n)),
            "x": [float(i) for i in range(n)],
            "y": [0.0 for _ in range(n)],
            "p": [0.99 for _ in range(n)],
            "chamber": chambers,
            "laser_state": [0 for _ in range(n)],
        }
    )
    path.write_text(df.to_csv(index=False), encoding="utf-8")


def _write_metadata_with_identity(path, mouse_id: str, group: str) -> None:
    payload = {
        "config": {
            "session_info": {
                "mouse_id": mouse_id,
                "group": group,
            }
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_cmd_analyze_group_summary_writes_wide_csv(tmp_path) -> None:
    # Session A (identity from metadata): M001 + pretest
    s1 = tmp_path / "session_20260301_120000_M001_pretest_60s"
    s1.mkdir()
    _write_log(s1 / "cpp_realtime_log.csv", ["chamber1", "chamber1", "chamber2"])
    _write_metadata_with_identity(s1 / "metadata.json", mouse_id="M001", group="pretest")

    # Session B (identity from metadata): M001 + test
    s2 = tmp_path / "session_20260301_130000_M001_test_60s"
    s2.mkdir()
    _write_log(s2 / "cpp_realtime_log.csv", ["chamber2", "chamber2", "chamber2", "chamber1"])
    _write_metadata_with_identity(s2 / "metadata.json", mouse_id="M001", group="test")

    # Session C (identity fallback from folder name): M002 + pretest
    s3 = tmp_path / "session_20260301_140000_M002_pretest_60s"
    s3.mkdir()
    _write_log(s3 / "cpp_realtime_log.csv", ["chamber1", "chamber2", "chamber2"])

    args = Namespace(
        root_dir=str(tmp_path),
        recursive=False,
        out_csv="group_chamber_summary.csv",
        strict_identity=False,
        layout="wide",
    )
    _cmd_analyze_group_summary(args)

    out = pd.read_csv(tmp_path / "group_chamber_summary.csv")
    assert list(out.columns)[0] == "mouse_id"
    assert "pretest_chamber1_time_s" in out.columns
    assert "pretest_chamber2_time_s" in out.columns
    assert "pretest_chamber1_pct" in out.columns
    assert "pretest_chamber2_pct" in out.columns
    assert "test_chamber1_time_s" in out.columns
    assert "test_chamber2_time_s" in out.columns

    row_m001 = out.loc[out["mouse_id"] == "M001"].iloc[0]
    assert row_m001["pretest_chamber1_time_s"] == pytest.approx(1.0, rel=1e-6)
    assert row_m001["pretest_chamber2_time_s"] == pytest.approx(1.0, rel=1e-6)
    assert row_m001["pretest_chamber1_pct"] == pytest.approx((1.0 / 3.0) * 100.0, rel=1e-6)
    assert row_m001["pretest_chamber2_pct"] == pytest.approx((1.0 / 3.0) * 100.0, rel=1e-6)
    assert row_m001["test_chamber1_time_s"] == pytest.approx(1.0, rel=1e-6)
    assert row_m001["test_chamber2_time_s"] == pytest.approx(2.0, rel=1e-6)
    assert row_m001["test_chamber1_pct"] == pytest.approx(25.0, rel=1e-6)
    assert row_m001["test_chamber2_pct"] == pytest.approx(50.0, rel=1e-6)

    row_m002 = out.loc[out["mouse_id"] == "M002"].iloc[0]
    assert row_m002["pretest_chamber1_time_s"] == pytest.approx(0.0, rel=1e-6)
    assert row_m002["pretest_chamber2_time_s"] == pytest.approx(2.0, rel=1e-6)
    assert row_m002["pretest_chamber1_pct"] == pytest.approx(0.0, rel=1e-6)
    assert row_m002["pretest_chamber2_pct"] == pytest.approx((2.0 / 3.0) * 100.0, rel=1e-6)


def test_cmd_analyze_group_summary_strict_identity_raises(tmp_path) -> None:
    # Missing metadata/config and folder name not parseable -> strict mode should fail.
    s1 = tmp_path / "random_folder_name"
    s1.mkdir()
    _write_log(s1 / "cpp_realtime_log.csv", ["chamber1", "chamber2"])

    args = Namespace(
        root_dir=str(tmp_path),
        recursive=False,
        out_csv="group_chamber_summary.csv",
        strict_identity=True,
        layout="prism",
    )
    with pytest.raises(ValueError):
        _cmd_analyze_group_summary(args)


def test_cmd_analyze_group_summary_prism_layout(tmp_path) -> None:
    s1 = tmp_path / "session_20260301_120000_M001_pretest_60s"
    s2 = tmp_path / "session_20260301_130000_M002_pretest_60s"
    s1.mkdir()
    s2.mkdir()
    _write_log(s1 / "cpp_realtime_log.csv", ["chamber1", "chamber2", "chamber2"])
    _write_log(s2 / "cpp_realtime_log.csv", ["chamber1", "chamber1", "chamber2"])

    args = Namespace(
        root_dir=str(tmp_path),
        recursive=False,
        out_csv="group_chamber_summary.csv",
        strict_identity=False,
        layout="prism",
    )
    _cmd_analyze_group_summary(args)

    out = pd.read_csv(tmp_path / "group_chamber_summary.csv")
    assert list(out.columns)[0] == "metric"
    assert "M001" in out.columns
    assert "M002" in out.columns
    assert "pretest_chamber1_time_s" in set(out["metric"])
    assert "pretest_chamber2_time_s" in set(out["metric"])


def test_cmd_analyze_group_summary_uses_log_not_stale_summary(tmp_path) -> None:
    s1 = tmp_path / "session_20260301_120000_M001_pretest_60s"
    s1.mkdir()
    _write_metadata_with_identity(s1 / "metadata.json", mouse_id="M001", group="pretest")
    # realtime session with fixed_fps in config; group summary should still use wall-time in auto mode.
    (s1 / "config_used.yaml").write_text("fixed_fps: 2\n", encoding="utf-8")
    df = pd.DataFrame(
        {
            "t_wall": [0.0, 0.5, 1.5],
            "frame_idx": [0, 1, 2],
            "x": [0.0, 1.0, 2.0],
            "y": [0.0, 0.0, 0.0],
            "chamber": ["chamber1", "chamber2", "chamber1"],
            "laser_state": [0, 0, 0],
        }
    )
    (s1 / "cpp_realtime_log.csv").write_text(df.to_csv(index=False), encoding="utf-8")

    # Deliberately wrong legacy summary; implementation should ignore this when log exists.
    stale = pd.DataFrame(
        [
            {
                "time_ch1_s": 999.0,
                "time_ch2_s": 1.0,
                "time_neutral_s": 0.0,
                "session_duration_s": 1000.0,
            }
        ]
    )
    stale.to_csv(s1 / "summary.csv", index=False)

    args = Namespace(
        root_dir=str(tmp_path),
        recursive=False,
        out_csv="group_chamber_summary.csv",
        strict_identity=False,
        layout="wide",
    )
    _cmd_analyze_group_summary(args)

    out = pd.read_csv(tmp_path / "group_chamber_summary.csv")
    row = out.loc[out["mouse_id"] == "M001"].iloc[0]
    # Wall-time dt=[0.5,1.0,0.75], dt_state=[0,1.0,0.75]:
    # ch1=0.75, ch2=1.0, total=2.25
    assert row["pretest_chamber1_time_s"] == pytest.approx(0.75, rel=1e-6)
    assert row["pretest_chamber2_time_s"] == pytest.approx(1.0, rel=1e-6)
    assert row["pretest_chamber1_pct"] == pytest.approx((0.75 / 2.25) * 100.0, rel=1e-6)
    assert row["pretest_chamber2_pct"] == pytest.approx((1.0 / 2.25) * 100.0, rel=1e-6)
