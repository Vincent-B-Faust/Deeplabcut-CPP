from __future__ import annotations

import json

import cv2
import numpy as np
import pandas as pd
import pytest

from cpp_dlc_live.analysis.analyze import analyze_session


def _write_dummy_video(path, width: int = 96, height: int = 72, frames: int = 12, fps: float = 20.0) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        float(fps),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV video writer is unavailable in test environment")
    for i in range(frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.putText(frame, f"f{i}", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        writer.write(frame)
    writer.release()


def test_analyze_session_can_render_overlay_video_without_realtime(tmp_path) -> None:
    prefix = "session_20260318_120000_M001_G1_120s"
    raw_name = f"{prefix}_raw_video.avi"
    raw_path = tmp_path / raw_name
    _write_dummy_video(raw_path)

    frames = 12
    df = pd.DataFrame(
        {
            "t_wall": [float(i) / 20.0 for i in range(frames)],
            "frame_idx": list(range(frames)),
            "x": [20.0 + i for i in range(frames)],
            "y": [30.0 for _ in range(frames)],
            "p": [0.95 for _ in range(frames)],
            "chamber": ["chamber1" if i < frames // 2 else "chamber2" for i in range(frames)],
            "laser_state": [1 if i < frames // 2 else 0 for i in range(frames)],
        }
    )
    (tmp_path / f"{prefix}_cpp_realtime_log.csv").write_text(df.to_csv(index=False), encoding="utf-8")

    (tmp_path / f"{prefix}_config_used.yaml").write_text(
        (
            "fixed_fps: 20\n"
            "analysis:\n"
            "  output_plots: false\n"
            "raw_recording:\n"
            f"  filename: {raw_name}\n"
            "roi:\n"
            "  type: polygon\n"
            "  chamber1: [[0,0],[40,0],[40,70],[0,70]]\n"
            "  chamber2: [[41,0],[95,0],[95,70],[41,70]]\n"
        ),
        encoding="utf-8",
    )

    metadata = {
        "file_prefix": prefix,
        "raw_recording_result": {
            "resolved_path": str(raw_path),
            "fps_actual": 20.0,
        },
    }
    (tmp_path / f"{prefix}_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    analyze_session(
        session_dir=tmp_path,
        output_plots_override=False,
        render_overlay_video=True,
        overlay_video_filename_override="analysis_overlay.avi",
    )

    out_path = tmp_path / f"{prefix}_analysis_overlay.avi"
    assert out_path.exists()
    assert out_path.stat().st_size > 0

    cap = cv2.VideoCapture(str(out_path))
    try:
        assert cap.isOpened()
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        assert frame_count > 0
    finally:
        cap.release()
