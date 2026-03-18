from __future__ import annotations

from pathlib import Path

import yaml

from cpp_dlc_live.realtime.dlc_runtime import _extract_bodyparts, _load_model_cfg


def test_extract_bodyparts_reads_dlc3_metadata_bodyparts() -> None:
    cfg = {
        "metadata": {
            "bodyparts": ["head", "tail", "center"],
        }
    }
    assert _extract_bodyparts(cfg) == ["head", "tail", "center"]


def test_load_model_cfg_reads_pytorch_config_next_to_pt(tmp_path: Path) -> None:
    model_pt = tmp_path / "snapshot-best.pt"
    model_pt.write_bytes(b"dummy")

    pytorch_cfg = {
        "metadata": {
            "bodyparts": ["head", "tail", "center"],
        }
    }
    with (tmp_path / "pytorch_config.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(pytorch_cfg, f, sort_keys=False, allow_unicode=True)

    cfg = _load_model_cfg(str(model_pt))
    assert _extract_bodyparts(cfg) == ["head", "tail", "center"]
