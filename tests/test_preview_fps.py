from cpp_dlc_live.realtime.app import RealtimeApp


def test_resolve_preview_writer_fps_prefers_override() -> None:
    fps, source = RealtimeApp._resolve_preview_writer_fps(
        preview_fps_override=24.0,
        camera_fps=120.0,
        camera_fps_target=30.0,
    )
    assert fps == 24.0
    assert source == "preview_recording.fps"


def test_resolve_preview_writer_fps_prefers_camera_target_over_reported() -> None:
    fps, source = RealtimeApp._resolve_preview_writer_fps(
        preview_fps_override=None,
        camera_fps=300.0,
        camera_fps_target=30.0,
    )
    assert fps == 30.0
    assert source == "camera.fps_target"


def test_resolve_preview_writer_fps_falls_back_default() -> None:
    fps, source = RealtimeApp._resolve_preview_writer_fps(
        preview_fps_override=None,
        camera_fps=0.0,
        camera_fps_target=None,
    )
    assert fps == 30.0
    assert source == "default_30"
