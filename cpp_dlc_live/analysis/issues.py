from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def analyze_issues(
    session_dir: Path,
    issue_file_override: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Path]:
    """Analyze structured runtime issue logs and incident reports for one session."""
    logger = logger or logging.getLogger("cpp_dlc_live")
    session_dir = Path(session_dir)

    metadata = _load_metadata(session_dir)
    issue_path = _resolve_issue_events_path(
        session_dir=session_dir,
        metadata=metadata,
        issue_file_override=issue_file_override,
    )

    events = _read_issue_events(issue_path, logger=logger)
    timeline_df = _build_timeline(events)
    issue_summary_df = _build_issue_summary(timeline_df)
    incident_summary_df = _build_incident_summary(session_dir, logger=logger)

    timeline_path = session_dir / "issue_timeline.csv"
    issue_summary_path = session_dir / "issue_summary.csv"
    incident_summary_path = session_dir / "incident_summary.csv"

    timeline_df.to_csv(timeline_path, index=False)
    issue_summary_df.to_csv(issue_summary_path, index=False)
    incident_summary_df.to_csv(incident_summary_path, index=False)

    logger.info("Issue timeline written: %s", timeline_path)
    logger.info("Issue summary written: %s", issue_summary_path)
    logger.info("Incident summary written: %s", incident_summary_path)

    return {
        "issue_timeline": timeline_path,
        "issue_summary": issue_summary_path,
        "incident_summary": incident_summary_path,
    }


def _load_metadata(session_dir: Path) -> Dict[str, Any]:
    path = session_dir / "metadata.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_issue_events_path(
    session_dir: Path,
    metadata: Dict[str, Any],
    issue_file_override: Optional[str],
) -> Path:
    if issue_file_override:
        override_path = Path(issue_file_override)
        return override_path if override_path.is_absolute() else session_dir / override_path

    runtime_stats = metadata.get("runtime_stats", {})
    if isinstance(runtime_stats, dict):
        issue_file = runtime_stats.get("issue_events_file")
        if issue_file:
            issue_path = Path(str(issue_file))
            return issue_path if issue_path.is_absolute() else session_dir / issue_path

    runtime_logging = metadata.get("runtime_logging", {})
    if isinstance(runtime_logging, dict):
        issue_file = runtime_logging.get("issue_events_file")
        if issue_file:
            issue_path = Path(str(issue_file))
            return issue_path if issue_path.is_absolute() else session_dir / issue_path

    return session_dir / "issue_events.jsonl"


def _read_issue_events(issue_path: Path, logger: logging.Logger) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not issue_path.exists():
        logger.warning("Issue events file not found: %s", issue_path)
        return events

    with issue_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                logger.warning("Skip invalid issue JSONL line %d: %s", line_no, exc)
                events.append(
                    {
                        "t_wall": None,
                        "event": "jsonl_parse_error",
                        "level": "ERROR",
                        "line_no": line_no,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    }
                )
                continue
            if isinstance(payload, dict):
                events.append(payload)
            else:
                events.append(
                    {
                        "t_wall": None,
                        "event": "jsonl_non_object_record",
                        "level": "ERROR",
                        "line_no": line_no,
                        "record_type": type(payload).__name__,
                    }
                )
    return events


def _build_timeline(events: List[Dict[str, Any]]) -> pd.DataFrame:
    columns = [
        "event_idx",
        "t_wall",
        "t_utc",
        "level",
        "event",
        "frame_idx",
        "chamber",
        "laser_state",
        "exception_type",
        "exception_message",
        "details_json",
    ]
    if not events:
        return pd.DataFrame(columns=columns)

    rows: List[Dict[str, Any]] = []
    for idx, event in enumerate(events):
        t_wall = _to_float(event.get("t_wall"))
        event_name = str(event.get("event", "unknown"))
        level = str(event.get("level", "INFO")).upper()
        frame_idx = _to_int(event.get("frame_idx"))
        chamber = _opt_str(event.get("chamber"))
        if chamber is None:
            chamber = _opt_str(event.get("to_chamber"))
        if chamber is None:
            chamber = _opt_str(event.get("chamber_raw"))
        laser_state = _to_int(event.get("laser_state"))
        if laser_state is None:
            laser_state = _to_int(event.get("to_state"))
        exception_type = _opt_str(event.get("exception_type"))
        exception_message = _opt_str(event.get("exception_message"))

        details = {
            k: v
            for k, v in event.items()
            if k
            not in {
                "t_wall",
                "event",
                "level",
                "frame_idx",
                "chamber",
                "to_chamber",
                "chamber_raw",
                "laser_state",
                "to_state",
                "exception_type",
                "exception_message",
            }
        }
        rows.append(
            {
                "event_idx": idx,
                "t_wall": t_wall,
                "t_utc": _epoch_to_utc(t_wall),
                "level": level,
                "event": event_name,
                "frame_idx": frame_idx,
                "chamber": chamber,
                "laser_state": laser_state,
                "exception_type": exception_type,
                "exception_message": exception_message,
                "details_json": json.dumps(details, ensure_ascii=False, sort_keys=True),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _build_issue_summary(timeline_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "event",
        "level",
        "count",
        "first_t_wall",
        "last_t_wall",
        "first_frame_idx",
        "last_frame_idx",
    ]
    if timeline_df.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        timeline_df.groupby(["event", "level"], dropna=False)
        .agg(
            count=("event_idx", "count"),
            first_t_wall=("t_wall", "min"),
            last_t_wall=("t_wall", "max"),
            first_frame_idx=("frame_idx", "min"),
            last_frame_idx=("frame_idx", "max"),
        )
        .reset_index()
        .sort_values(by=["count", "event", "level"], ascending=[False, True, True])
    )
    return grouped[columns]


def _build_incident_summary(session_dir: Path, logger: logging.Logger) -> pd.DataFrame:
    columns = [
        "file",
        "time_utc",
        "exception_type",
        "exception_message",
        "frame_idx",
        "chamber",
        "laser_state",
    ]
    rows: List[Dict[str, Any]] = []

    for path in sorted(session_dir.glob("incident_report_*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            logger.warning("Skip invalid incident report %s: %s", path, exc)
            rows.append(
                {
                    "file": path.name,
                    "time_utc": None,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "frame_idx": None,
                    "chamber": None,
                    "laser_state": None,
                }
            )
            continue

        if not isinstance(payload, dict):
            rows.append(
                {
                    "file": path.name,
                    "time_utc": None,
                    "exception_type": "InvalidIncidentReport",
                    "exception_message": f"Unexpected root type: {type(payload).__name__}",
                    "frame_idx": None,
                    "chamber": None,
                    "laser_state": None,
                }
            )
            continue

        ctx = payload.get("last_context", {})
        ctx = ctx if isinstance(ctx, dict) else {}
        rows.append(
            {
                "file": path.name,
                "time_utc": _opt_str(payload.get("time_utc")),
                "exception_type": _opt_str(payload.get("exception_type")),
                "exception_message": _opt_str(payload.get("exception_message")),
                "frame_idx": _to_int(ctx.get("frame_idx")),
                "chamber": _opt_str(ctx.get("chamber")),
                "laser_state": _to_int(ctx.get("laser_state")),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _epoch_to_utc(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    if ts < 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None
