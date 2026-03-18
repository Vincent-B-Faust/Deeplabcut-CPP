from __future__ import annotations

from pathlib import Path

import pytest

from cpp_dlc_live.realtime import dlc_runtime
from cpp_dlc_live.realtime.dlc_runtime import MockDLCRuntime, PoseResult, build_runtime


class _DummyRuntime:
    def infer(self, frame):  # pragma: no cover - not used in these tests
        return PoseResult(x=0.0, y=0.0, p=0.0, bodypart="center", keypoints={})

    def model_info(self):
        return {"runtime": "dlclive"}


def test_build_runtime_strict_missing_model_raises() -> None:
    cfg = {
        "model_path": "Z:/not_exists/model.pt",
        "strict_runtime": True,
    }
    with pytest.raises(RuntimeError, match="model_path is missing or does not exist"):
        build_runtime(cfg)


def test_build_runtime_non_strict_missing_model_falls_back_mock() -> None:
    cfg = {"model_path": "Z:/not_exists/model.pt", "strict_runtime": False}
    runtime = build_runtime(cfg)
    assert isinstance(runtime, MockDLCRuntime)


def test_build_runtime_strict_init_failure_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"dummy")

    def _raise(**kwargs):  # type: ignore[no-redef]
        raise RuntimeError("boom")

    monkeypatch.setattr(dlc_runtime, "DLCLiveRuntime", _raise)

    with pytest.raises(RuntimeError, match="strict_runtime=true"):
        build_runtime({"model_path": str(model_path), "strict_runtime": True})


def test_build_runtime_non_strict_init_failure_falls_back_mock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"dummy")

    def _raise(**kwargs):  # type: ignore[no-redef]
        raise RuntimeError("boom")

    monkeypatch.setattr(dlc_runtime, "DLCLiveRuntime", _raise)
    runtime = build_runtime({"model_path": str(model_path), "strict_runtime": False})
    assert isinstance(runtime, MockDLCRuntime)


def test_build_runtime_strict_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"dummy")

    def _ok(**kwargs):  # type: ignore[no-redef]
        return _DummyRuntime()

    monkeypatch.setattr(dlc_runtime, "DLCLiveRuntime", _ok)
    runtime = build_runtime({"model_path": str(model_path), "strict_runtime": True})
    assert isinstance(runtime, _DummyRuntime)
