from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Optional, Tuple

import pandas as pd

from cpp_dlc_live.analysis.metrics import compute_summary
from cpp_dlc_live.utils.io_utils import load_yaml, resolve_session_file


_SESSION_NAME_RE = re.compile(r"^session_\d{8}_\d{6}_(?P<mouse>[^_]+)_(?P<group>[^_]+)(?:_|$)")


def summarize_group_chamber_metrics(
    session_dirs: Iterable[Path],
    output_csv: Path,
    layout: Literal["prism", "wide"] = "prism",
    strict_identity: bool = False,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """Aggregate chamber1/chamber2 metrics by mouse_id + group across sessions.

    Layout modes:
    - `wide` (legacy):
      - first column: `mouse_id`
      - per-group columns:
        - <group>_chamber1_time_s
        - <group>_chamber1_pct
        - <group>_chamber2_time_s
        - <group>_chamber2_pct
    - `prism` (default):
      - first column: `metric`
      - remaining columns: one column per `mouse_id`
      - each row is one metric (transposed from wide), convenient for direct
        copy/paste into GraphPad Prism.

    Percentages are computed against aggregated session duration for that
    mouse/group pair.
    """
    logger = logger or logging.getLogger("cpp_dlc_live")
    output_csv = Path(output_csv)

    grouped: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
    skipped = 0
    processed = 0

    for session_dir in sorted({Path(p).resolve() for p in session_dirs}):
        if not session_dir.is_dir():
            continue

        identity = _resolve_session_identity(session_dir=session_dir, strict_identity=strict_identity, logger=logger)
        if identity is None:
            skipped += 1
            continue
        mouse_id, group = identity

        summary = _load_or_compute_session_summary(session_dir=session_dir, logger=logger)
        if summary is None:
            skipped += 1
            continue

        time_ch1_s = _as_float(summary.get("time_ch1_s"))
        time_ch2_s = _as_float(summary.get("time_ch2_s"))
        session_duration_s = _as_float(summary.get("session_duration_s"))
        if session_duration_s <= 0:
            # Fallback for legacy summaries without session_duration_s.
            session_duration_s = _as_float(summary.get("time_ch1_s")) + _as_float(summary.get("time_ch2_s")) + _as_float(
                summary.get("time_neutral_s")
            )

        slot = grouped.setdefault(mouse_id, {}).setdefault(
            group,
            {
                "time_ch1_s": 0.0,
                "time_ch2_s": 0.0,
                "session_duration_s": 0.0,
                "n_sessions": 0.0,
            },
        )
        slot["time_ch1_s"] += time_ch1_s
        slot["time_ch2_s"] += time_ch2_s
        slot["session_duration_s"] += max(0.0, session_duration_s)
        slot["n_sessions"] += 1.0
        processed += 1

    if layout == "wide":
        rows = _build_wide_rows(grouped)
    elif layout == "prism":
        rows = _build_prism_rows(grouped)
    else:
        raise ValueError(f"Unsupported layout: {layout}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_csv, index=False)
    logger.info(
        "Group chamber summary written: %s (layout=%s processed_sessions=%d skipped_sessions=%d mice=%d)",
        output_csv,
        layout,
        processed,
        skipped,
        len(rows),
    )
    return output_csv


def _build_wide_rows(grouped: Dict[str, Dict[str, Dict[str, float]]]) -> list[Dict[str, Any]]:
    all_groups = sorted({group for groups in grouped.values() for group in groups.keys()})
    rows: list[Dict[str, Any]] = []

    for mouse_id in sorted(grouped.keys()):
        row: Dict[str, Any] = {"mouse_id": mouse_id}
        group_stats = grouped.get(mouse_id, {})
        for group in all_groups:
            stats = group_stats.get(group)
            col_time_ch1 = f"{group}_chamber1_time_s"
            col_pct_ch1 = f"{group}_chamber1_pct"
            col_time_ch2 = f"{group}_chamber2_time_s"
            col_pct_ch2 = f"{group}_chamber2_pct"
            if stats is None:
                row[col_time_ch1] = 0.0
                row[col_pct_ch1] = 0.0
                row[col_time_ch2] = 0.0
                row[col_pct_ch2] = 0.0
                continue

            duration_s = max(0.0, _as_float(stats.get("session_duration_s")))
            time_ch1_s = max(0.0, _as_float(stats.get("time_ch1_s")))
            time_ch2_s = max(0.0, _as_float(stats.get("time_ch2_s")))
            row[col_time_ch1] = time_ch1_s
            row[col_time_ch2] = time_ch2_s
            if duration_s > 0:
                row[col_pct_ch1] = (time_ch1_s / duration_s) * 100.0
                row[col_pct_ch2] = (time_ch2_s / duration_s) * 100.0
            else:
                row[col_pct_ch1] = 0.0
                row[col_pct_ch2] = 0.0
        rows.append(row)
    return rows


def _build_prism_rows(grouped: Dict[str, Dict[str, Dict[str, float]]]) -> list[Dict[str, Any]]:
    """Build transposed table: rows=metric, columns=mouse_id."""
    wide_rows = _build_wide_rows(grouped)
    if not wide_rows:
        return []
    wide_df = pd.DataFrame(wide_rows).sort_values("mouse_id")
    prism_df = wide_df.set_index("mouse_id").T.reset_index().rename(columns={"index": "metric"})
    return prism_df.to_dict(orient="records")


def _resolve_session_identity(
    session_dir: Path,
    strict_identity: bool,
    logger: logging.Logger,
) -> Optional[Tuple[str, str]]:
    session_info = _load_session_info(session_dir=session_dir, logger=logger)
    mouse_id = str(session_info.get("mouse_id", "")).strip()
    group = str(session_info.get("group", "")).strip()
    if mouse_id and group:
        return mouse_id, group

    fallback = _parse_identity_from_session_name(session_dir.name)
    if fallback is not None:
        return fallback

    if strict_identity:
        raise ValueError(f"Cannot resolve mouse_id/group for session: {session_dir}")
    logger.warning("Skip session with unresolved mouse_id/group: %s", session_dir)
    return None


def _load_session_info(session_dir: Path, logger: logging.Logger) -> Dict[str, Any]:
    # 1) metadata.json (or prefixed metadata) keeps full runtime config and is preferred.
    metadata_path = resolve_session_file(session_dir, "metadata.json")
    if metadata_path.exists():
        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                metadata = json.load(f)
            if isinstance(metadata, dict):
                # Newest structure: metadata["config"]["session_info"].
                cfg = metadata.get("config", {})
                if isinstance(cfg, dict):
                    info = cfg.get("session_info", {})
                    if isinstance(info, dict):
                        return info
                # Backward-compatible fallback.
                info = metadata.get("session_info", {})
                if isinstance(info, dict):
                    return info
        except Exception:
            logger.exception("Failed to read metadata for identity parsing: %s", metadata_path)

    # 2) config_used.yaml (or prefixed config copy).
    config_path = resolve_session_file(session_dir, "config_used.yaml")
    if config_path.exists():
        try:
            config = load_yaml(config_path)
            if isinstance(config, dict):
                info = config.get("session_info", {})
                if isinstance(info, dict):
                    return info
        except Exception:
            logger.exception("Failed to read config_used for identity parsing: %s", config_path)

    return {}


def _parse_identity_from_session_name(name: str) -> Optional[Tuple[str, str]]:
    match = _SESSION_NAME_RE.match(str(name))
    if match is not None:
        mouse = str(match.group("mouse")).strip()
        group = str(match.group("group")).strip()
        if mouse and group:
            return mouse, group

    # Fallback: session_<mouse>_<group>_...
    tokens = str(name).split("_")
    if len(tokens) >= 3 and tokens[0].lower() == "session":
        mouse = tokens[1].strip()
        group = tokens[2].strip()
        if mouse and group:
            return mouse, group
    return None


def _load_or_compute_session_summary(session_dir: Path, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    summary_path = resolve_session_file(session_dir, "summary.csv")
    if summary_path.exists():
        try:
            summary_df = pd.read_csv(summary_path)
            if not summary_df.empty:
                return dict(summary_df.iloc[0].to_dict())
        except Exception:
            logger.exception("Failed to read summary.csv, fallback to realtime log: %s", summary_path)

    log_path = resolve_session_file(session_dir, "cpp_realtime_log.csv")
    if not log_path.exists():
        logger.warning("Skip session without summary/log: %s", session_dir)
        return None

    try:
        df = pd.read_csv(log_path)
    except Exception:
        logger.exception("Failed to read realtime log: %s", log_path)
        return None

    fixed_fps_hz: Optional[float] = None
    config_path = resolve_session_file(session_dir, "config_used.yaml")
    if config_path.exists():
        try:
            config = load_yaml(config_path)
            if isinstance(config, dict):
                raw_fixed = config.get("fixed_fps")
                if raw_fixed is not None:
                    parsed = float(raw_fixed)
                    if parsed > 0:
                        fixed_fps_hz = parsed
        except Exception:
            logger.exception("Failed to parse fixed_fps from config: %s", config_path)

    return compute_summary(df, cm_per_px=None, fixed_fps_hz=fixed_fps_hz)


def _as_float(value: Any) -> float:
    try:
        v = float(value)
    except Exception:
        return 0.0
    if pd.isna(v):
        return 0.0
    return v
