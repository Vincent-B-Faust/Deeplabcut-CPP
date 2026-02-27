import pandas as pd

from cpp_dlc_live.analysis.metrics import compute_summary


def test_compute_summary_basic() -> None:
    df = pd.DataFrame(
        {
            "t_wall": [0.0, 1.0, 2.0, 3.0, 4.0],
            "frame_idx": [0, 1, 2, 3, 4],
            "x": [0.0, 1.0, 2.0, 2.0, 2.0],
            "y": [0.0, 0.0, 0.0, 1.0, 2.0],
            "chamber": ["chamber1", "chamber1", "chamber2", "chamber2", "neutral"],
            "laser_state": [1, 1, 0, 0, 0],
        }
    )

    summary = compute_summary(df, cm_per_px=0.5)

    assert summary["time_ch1_s"] == 2.0
    assert summary["time_ch2_s"] == 2.0
    assert summary["time_neutral_s"] == 1.0
    assert summary["distance_px"] == 4.0
    assert summary["distance_cm"] == 2.0
    assert summary["laser_on_time_s"] == 2.0
    assert summary["mean_speed_px_s"] == 0.8
    assert summary["mean_speed_cm_s"] == 0.4
