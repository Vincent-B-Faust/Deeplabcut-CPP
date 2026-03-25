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


def test_compute_summary_fixed_fps_timebase() -> None:
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

    summary = compute_summary(df, cm_per_px=None, fixed_fps_hz=2.0)

    assert summary["time_ch1_s"] == 1.0
    assert summary["time_ch2_s"] == 1.0
    assert summary["time_neutral_s"] == 0.5
    assert summary["session_duration_s"] == 2.5
    assert summary["laser_on_time_s"] == 1.0


def test_compute_summary_maps_unknown_to_neutral() -> None:
    df = pd.DataFrame(
        {
            "t_wall": [0.0, 1.0, 2.0],
            "frame_idx": [0, 1, 2],
            "x": [0.0, 1.0, 2.0],
            "y": [0.0, 0.0, 0.0],
            "chamber": ["unknown", "chamber1", "bad_value"],
            "laser_state": [0, 1, 0],
        }
    )

    summary = compute_summary(df, cm_per_px=None)
    # dt = [1, 1, 1] for this synthetic timeline (last frame uses median dt)
    assert summary["time_ch1_s"] == 1.0
    assert summary["time_ch2_s"] == 0.0
    assert summary["time_neutral_s"] == 2.0
