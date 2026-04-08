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
    )
    with pytest.raises(ValueError):
        _cmd_analyze_group_summary(args)

