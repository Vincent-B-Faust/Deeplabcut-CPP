from cpp_dlc_live.realtime.app import _format_laser_mode_overlay, _parse_display_bodyparts, _resolve_preview_points


def test_parse_display_bodyparts_normalization() -> None:
    assert _parse_display_bodyparts(None) is None
    assert _parse_display_bodyparts("") is None
    assert _parse_display_bodyparts("head") == ["head"]
    assert _parse_display_bodyparts("all") == ["*"]
    assert _parse_display_bodyparts(["head", "tail"]) == ["head", "tail"]
    assert _parse_display_bodyparts(["all", "tail"]) == ["*"]


def test_resolve_preview_points_default_single_control() -> None:
    points = {"head": (10.0, 20.0, 0.9), "tail": (30.0, 40.0, 0.8)}
    resolved = _resolve_preview_points(
        keypoints=points,
        display_bodyparts=None,
        control_bodypart="head",
        control_point=(10.0, 20.0, 0.9),
    )
    assert resolved == [("head", (10.0, 20.0, 0.9), True)]


def test_resolve_preview_points_selected_names_case_insensitive() -> None:
    points = {"Head": (10.0, 20.0, 0.9), "tail": (30.0, 40.0, 0.8), "center": (20.0, 30.0, 0.95)}
    resolved = _resolve_preview_points(
        keypoints=points,
        display_bodyparts=["head", "CENTER"],
        control_bodypart="center",
        control_point=(20.0, 30.0, 0.95),
    )
    assert resolved == [
        ("Head", (10.0, 20.0, 0.9), False),
        ("center", (20.0, 30.0, 0.95), True),
    ]


def test_resolve_preview_points_fallback_when_no_name_matches() -> None:
    points = {"head": (10.0, 20.0, 0.9)}
    resolved = _resolve_preview_points(
        keypoints=points,
        display_bodyparts=["tail"],
        control_bodypart="center",
        control_point=(5.0, 6.0, 0.7),
    )
    assert resolved == [("center", (5.0, 6.0, 0.7), True)]


def test_format_laser_mode_overlay() -> None:
    assert _format_laser_mode_overlay({"mode": "continuous"}) == "continuous"
    assert _format_laser_mode_overlay({"mode": "pulse", "freq_hz": 20}) == "pulse 20.0Hz"
    assert _format_laser_mode_overlay({"mode": "startstop", "freq_hz": 10}) == "pulse 10.0Hz"
