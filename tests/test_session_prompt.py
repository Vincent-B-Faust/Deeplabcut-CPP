from cpp_dlc_live.utils.session_prompt import _ensure_choices


def test_ensure_choices_always_contains_required_options() -> None:
    values = _ensure_choices(values=["on"], required=["on", "off"], preferred="on")
    assert values == ["on", "off"]

    values2 = _ensure_choices(values=["pulse"], required=["continuous", "pulse"], preferred="pulse")
    assert values2 == ["pulse", "continuous"]


def test_ensure_choices_deduplicates_and_preserves_preferred_first() -> None:
    values = _ensure_choices(values=["off", "on", "off"], required=["on", "off"], preferred="on")
    assert values == ["on", "off"]
