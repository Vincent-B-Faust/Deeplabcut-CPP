from cpp_dlc_live.realtime.debounce import Debouncer


def test_debounce_requires_n_consecutive_frames() -> None:
    d = Debouncer(required_count=3, initial_state="chamber2")

    seq = ["chamber2", "chamber1", "chamber1", "chamber2", "chamber1", "chamber1", "chamber1"]
    out = [d.update(x) for x in seq]

    assert out[:6] == ["chamber2", "chamber2", "chamber2", "chamber2", "chamber2", "chamber2"]
    assert out[6] == "chamber1"


def test_debounce_n1_switches_immediately() -> None:
    d = Debouncer(required_count=1, initial_state="unknown")
    assert d.update("chamber1") == "chamber1"
    assert d.update("chamber2") == "chamber2"
