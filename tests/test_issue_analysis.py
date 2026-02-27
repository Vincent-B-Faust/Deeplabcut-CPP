import json

import pandas as pd

from cpp_dlc_live.analysis.issues import analyze_issues


def test_analyze_issues_outputs_summary_and_incidents(tmp_path) -> None:
    issue_file = tmp_path / "custom_issue_events.jsonl"
    issue_records = [
        {"t_wall": 1.0, "event": "session_start", "level": "INFO", "frame_idx": 0},
        {"t_wall": 2.0, "event": "fps_warning", "level": "WARNING", "frame_idx": 20, "fps_est": 8.5},
        {"t_wall": 3.0, "event": "fps_warning", "level": "WARNING", "frame_idx": 40, "fps_est": 7.9},
        {
            "t_wall": 4.0,
            "event": "runtime_exception",
            "level": "ERROR",
            "exception_type": "RuntimeError",
            "exception_message": "boom",
            "frame_idx": 44,
        },
    ]
    with issue_file.open("w", encoding="utf-8") as f:
        for record in issue_records:
            f.write(json.dumps(record) + "\n")

    metadata = {
        "runtime_stats": {"issue_events_file": "custom_issue_events.jsonl"},
        "runtime_logging": {"issue_events_file": "issue_events.jsonl"},
    }
    with (tmp_path / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f)

    incident = {
        "time_utc": "2026-02-27T00:00:00Z",
        "exception_type": "RuntimeError",
        "exception_message": "boom",
        "last_context": {"frame_idx": 99, "chamber": "chamber1", "laser_state": 1},
    }
    with (tmp_path / "incident_report_20260227_000000.json").open("w", encoding="utf-8") as f:
        json.dump(incident, f)

    outputs = analyze_issues(session_dir=tmp_path)

    summary_df = pd.read_csv(outputs["issue_summary"])
    assert int(
        summary_df.loc[
            (summary_df["event"] == "fps_warning") & (summary_df["level"] == "WARNING"),
            "count",
        ].iloc[0]
    ) == 2

    timeline_df = pd.read_csv(outputs["issue_timeline"])
    assert len(timeline_df) == 4
    assert "details_json" in timeline_df.columns

    incident_df = pd.read_csv(outputs["incident_summary"])
    assert len(incident_df) == 1
    assert incident_df.loc[0, "exception_type"] == "RuntimeError"
    assert int(incident_df.loc[0, "frame_idx"]) == 99


def test_analyze_issues_handles_missing_issue_file(tmp_path) -> None:
    outputs = analyze_issues(session_dir=tmp_path, issue_file_override="missing_issue_events.jsonl")
    summary_df = pd.read_csv(outputs["issue_summary"])
    timeline_df = pd.read_csv(outputs["issue_timeline"])
    incident_df = pd.read_csv(outputs["incident_summary"])

    assert summary_df.empty
    assert timeline_df.empty
    assert incident_df.empty
