from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2
import pandas as pd

from cpp_dlc_live.analysis.analyze import analyze_session
from cpp_dlc_live.analysis.issues import analyze_issues
from cpp_dlc_live.realtime.app import RealtimeApp
from cpp_dlc_live.realtime.camera import CameraConfig, CameraStream
from cpp_dlc_live.realtime.logging_utils import setup_logging
from cpp_dlc_live.realtime.roi import calibrate_roi_with_camera, calibrate_roi_with_frame
from cpp_dlc_live.utils.io_utils import (
    detect_session_file_prefix,
    ensure_prefixed_filename,
    file_sha256,
    load_yaml,
    prepare_session_dir,
    save_yaml,
    sanitize_name_component,
)
from cpp_dlc_live.utils.session_prompt import collect_session_info


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run_realtime":
        _cmd_run_realtime(args)
        return
    if args.command == "run_offline":
        _cmd_run_offline(args)
        return
    if args.command == "analyze_session":
        _cmd_analyze_session(args)
        return
    if args.command == "analyze_issues":
        _cmd_analyze_issues(args)
        return
    if args.command == "analyze_batch":
        _cmd_analyze_batch(args)
        return
    if args.command == "calibrate_roi":
        _cmd_calibrate_roi(args)
        return

    parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cpp-dlc-live", description="DLC-live CPP realtime and analysis CLI")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run_realtime", help="Run realtime closed-loop experiment")
    p_run.add_argument("--config", required=True, help="Path to config YAML")
    p_run.add_argument("--out_dir", default=None, help="Session output root override")
    p_run.add_argument("--duration_s", type=float, default=None, help="Optional run duration in seconds")
    p_run.add_argument("--camera_source", default=None, help="Camera source override (int index or URL/path)")
    p_run.add_argument("--fixed_fps", type=float, default=None, help="Optional global fixed FPS override")
    p_run.add_argument("--no_preview", action="store_true", help="Disable OpenCV preview window")
    p_run.add_argument("--mouse_id", default=None, help="Mouse ID (prefill for session prompt)")
    p_run.add_argument("--group", default=None, help="Group label (prefill for session prompt)")
    p_run.add_argument(
        "--experiment_duration_s",
        type=float,
        default=None,
        help="Planned experiment duration in seconds (prefill for session prompt)",
    )
    p_run.add_argument("--no_session_prompt", action="store_true", help="Disable pre-run popup and use provided values")
    p_run.add_argument(
        "--no_auto_analyze",
        action="store_true",
        help="Skip automatic post-run analysis and plotting",
    )

    p_off = sub.add_parser("run_offline", help="Run fast offline replay from existing video")
    p_off.add_argument("--config", required=True, help="Path to config YAML")
    p_off.add_argument("--out_dir", default=None, help="Session output root override")
    p_off.add_argument("--video", default=None, help="Offline input video path override")
    p_off.add_argument("--camera_source", default=None, help="Alternative source override (same as --video)")
    p_off.add_argument("--root_dir", default=None, help="Batch replay root directory containing raw videos")
    p_off.add_argument("--recursive", action="store_true", help="Recursively scan root_dir for videos")
    p_off.add_argument("--fail_fast", action="store_true", help="Stop batch replay on first failed video")
    p_off.add_argument(
        "--batch_report_name",
        default="offline_batch_report.csv",
        help="Batch report CSV filename under root_dir",
    )
    p_off.add_argument("--duration_s", type=float, default=None, help="Optional processing duration in seconds")
    p_off.add_argument("--fixed_fps", type=float, default=None, help="Optional global fixed FPS override")
    p_off.add_argument("--preview", action="store_true", help="Enable OpenCV preview window during offline replay")
    p_off.add_argument("--mouse_id", default=None, help="Mouse ID for output naming metadata")
    p_off.add_argument("--group", default=None, help="Group label for output naming metadata")
    p_off.add_argument(
        "--experiment_duration_s",
        type=float,
        default=None,
        help="Session naming metadata duration (seconds); does not limit processing unless --duration_s is set",
    )
    p_off.add_argument(
        "--no_auto_analyze",
        action="store_true",
        help="Skip automatic post-run analysis and plotting",
    )

    p_an = sub.add_parser("analyze_session", help="Analyze one session directory")
    p_an.add_argument("--session_dir", required=True, help="Path to session directory")
    p_an.add_argument("--cm_per_px", type=float, default=None, help="Override cm_per_px")
    p_an.add_argument("--fixed_fps", type=float, default=None, help="Use global fixed FPS timebase for metrics")
    p_an.add_argument("--fixed_fps_hz", type=float, default=None, help="Use fixed FPS timebase for metrics")
    p_an.add_argument("--no_plots", action="store_true", help="Disable plot output")
    p_an.add_argument(
        "--render_overlay_video",
        action="store_true",
        help="Render offline overlay video from session log + source video",
    )
    p_an.add_argument(
        "--overlay_video_source",
        default=None,
        help="Optional source video path override for offline overlay rendering",
    )
    p_an.add_argument(
        "--overlay_video_filename",
        default=None,
        help="Optional output filename for offline overlay video (under session_dir if relative)",
    )

    p_issues = sub.add_parser("analyze_issues", help="Analyze issue events and incident reports")
    p_issues.add_argument("--session_dir", required=True, help="Path to session directory")
    p_issues.add_argument(
        "--issue_file",
        default=None,
        help="Optional issue events JSONL path (absolute or relative to session_dir)",
    )

    p_batch = sub.add_parser("analyze_batch", help="Batch analyze all session folders under a root directory")
    p_batch.add_argument("--root_dir", required=True, help="Root directory containing session subfolders")
    p_batch.add_argument("--recursive", action="store_true", help="Recursively scan subdirectories")
    p_batch.add_argument("--cm_per_px", type=float, default=None, help="Override cm_per_px for all sessions")
    p_batch.add_argument("--fixed_fps", type=float, default=None, help="Use fixed FPS timebase for all sessions")
    p_batch.add_argument("--fixed_fps_hz", type=float, default=None, help="Legacy fixed FPS option")
    p_batch.add_argument("--no_plots", action="store_true", help="Disable plot generation for all sessions")
    p_batch.add_argument(
        "--render_overlay_video",
        action="store_true",
        help="Render offline overlay video for each session",
    )
    p_batch.add_argument(
        "--overlay_video_filename",
        default=None,
        help="Optional output filename for offline overlay video in each session",
    )
    p_batch.add_argument("--include_issues", action="store_true", help="Also run analyze_issues for each session")
    p_batch.add_argument("--fail_fast", action="store_true", help="Stop at first failed session")
    p_batch.add_argument(
        "--report_name",
        default="batch_analysis_report.csv",
        help="Output CSV report filename under root_dir",
    )

    p_cal = sub.add_parser("calibrate_roi", help="Interactive ROI calibrator")
    p_cal.add_argument("--config", required=True, help="Config YAML to load/update")
    p_cal.add_argument("--camera_source", default=None, help="Camera source override (int index or URL/path)")
    p_cal.add_argument("--image", default=None, help="Use static image instead of camera")
    p_cal.add_argument("--save_to", default=None, help="Output YAML path (default: overwrite --config)")
    p_cal.add_argument("--without_neutral", action="store_true", help="Calibrate only chamber1/chamber2")
    p_cal.add_argument("--exposure_step", type=float, default=1.0, help="Exposure step for calibration hotkeys")
    p_cal.add_argument("--gain_step", type=float, default=1.0, help="Gain step for calibration hotkeys")

    return parser


def _cmd_run_realtime(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    config = load_yaml(config_path)

    camera_override = _parse_source(args.camera_source) if args.camera_source is not None else None
    if camera_override is not None:
        config.setdefault("camera", {})["source"] = camera_override
    if args.fixed_fps is not None:
        config["fixed_fps"] = float(args.fixed_fps)

    session_info = _resolve_session_info(config, args)
    config["session_info"] = session_info
    args.duration_s = float(session_info["experiment_duration_s"])
    _apply_session_laser_settings(config, session_info)
    _apply_session_acclimation_settings(config, session_info)

    session_dir = prepare_session_dir(config, out_dir_override=args.out_dir)
    file_prefix = str(config.setdefault("project", {}).get("resolved_file_prefix", "session"))
    _apply_prefixed_output_names(config, file_prefix=file_prefix)

    used_cfg_path = session_dir / ensure_prefixed_filename("config_used.yaml", file_prefix)
    save_yaml(config, used_cfg_path)

    logger = setup_logging(session_dir, file_prefix=file_prefix)
    logger.info("Config copied to: %s", used_cfg_path)
    logger.info("Config sha256: %s", file_sha256(used_cfg_path))

    app = RealtimeApp(
        config=config,
        session_dir=session_dir,
        duration_s=args.duration_s,
        camera_source_override=camera_override,
        preview=not bool(args.no_preview),
        file_prefix=file_prefix,
        logger=logger,
    )
    status = app.run()
    if status != 0:
        raise SystemExit(status)

    _run_auto_analysis(config=config, no_auto_analyze=bool(args.no_auto_analyze), session_dir=session_dir, logger=logger)


def _cmd_run_offline(args: argparse.Namespace) -> None:
    if getattr(args, "root_dir", None):
        _cmd_run_offline_batch(args)
        return

    source_raw = args.video if getattr(args, "video", None) is not None else getattr(args, "camera_source", None)
    source_override = _parse_source(source_raw) if source_raw is not None else None
    status, _ = _run_offline_once(args=args, source_override=source_override, session_id_override=None)
    if status != 0:
        raise SystemExit(status)


def _cmd_run_offline_batch(args: argparse.Namespace) -> None:
    root_dir = Path(str(args.root_dir))
    if not root_dir.exists():
        raise FileNotFoundError(f"root_dir not found: {root_dir}")
    if args.video or args.camera_source:
        raise ValueError("--video/--camera_source cannot be used together with --root_dir")

    video_paths = _discover_offline_videos(root_dir=root_dir, recursive=bool(args.recursive))
    if not video_paths:
        raise RuntimeError(f"No candidate offline videos found under: {root_dir}")

    rows: List[Dict[str, Any]] = []
    failed = 0
    for idx, video_path in enumerate(video_paths, start=1):
        session_id_override = f"offline_{idx:04d}_{sanitize_name_component(video_path.stem)[:40]}"
        row = {
            "index": idx,
            "video_path": str(video_path),
            "status": "ok",
            "session_dir": "",
            "error": "",
        }
        try:
            status, session_dir = _run_offline_once(
                args=args,
                source_override=video_path,
                session_id_override=session_id_override,
            )
            row["session_dir"] = str(session_dir)
            if status != 0:
                failed += 1
                row["status"] = "failed"
                row["error"] = f"status_code={status}"
                if bool(args.fail_fast):
                    rows.append(row)
                    break
        except Exception as exc:
            failed += 1
            row["status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
            if bool(args.fail_fast):
                rows.append(row)
                break
        rows.append(row)

    report_path = root_dir / str(args.batch_report_name)
    pd.DataFrame(rows).to_csv(report_path, index=False)
    print(report_path)
    if failed > 0:
        raise SystemExit(2)


def _run_offline_once(
    args: argparse.Namespace,
    source_override: Optional[Union[int, str, Path]],
    session_id_override: Optional[str],
) -> tuple[int, Path]:
    config_path = Path(args.config)
    base_config = load_yaml(config_path)
    config: Dict[str, Any] = copy.deepcopy(base_config)

    source_value: Optional[Union[int, str]] = None
    if source_override is not None:
        source_value = _parse_source(source_override)
        config.setdefault("camera", {})["source"] = source_value
    if args.fixed_fps is not None:
        config["fixed_fps"] = float(args.fixed_fps)

    cam_cfg = config.setdefault("camera", {})
    if isinstance(cam_cfg, dict):
        # Offline replay should run as fast as possible for file inputs.
        cam_cfg["file_realtime_throttle"] = False
        cam_cfg["enforce_fps"] = False

    acclimation_cfg = config.setdefault("acclimation", {})
    if isinstance(acclimation_cfg, dict):
        # Offline replay should not wait for acclimation.
        acclimation_cfg["enabled"] = False
        acclimation_cfg["duration_s"] = 0.0

    laser_cfg = config.setdefault("laser_control", {})
    if isinstance(laser_cfg, dict):
        # Safety: offline replay must not touch NI hardware.
        laser_cfg["mode"] = "dryrun"
        laser_cfg["fallback_to_dryrun"] = True

    session_info = _resolve_offline_session_info(config, args)
    config["session_info"] = session_info
    if session_id_override:
        config.setdefault("project", {})["session_id"] = session_id_override

    session_dir = prepare_session_dir(config, out_dir_override=args.out_dir)
    file_prefix = str(config.setdefault("project", {}).get("resolved_file_prefix", "session"))
    _apply_prefixed_output_names(config, file_prefix=file_prefix)

    used_cfg_path = session_dir / ensure_prefixed_filename("config_used.yaml", file_prefix)
    save_yaml(config, used_cfg_path)

    logger = setup_logging(session_dir, file_prefix=file_prefix)
    logger.info("Config copied to: %s", used_cfg_path)
    logger.info("Config sha256: %s", file_sha256(used_cfg_path))
    logger.info("Offline replay mode: source=%s preview=%s", config.get("camera", {}).get("source"), bool(args.preview))

    app = RealtimeApp(
        config=config,
        session_dir=session_dir,
        duration_s=(float(args.duration_s) if args.duration_s is not None else None),
        camera_source_override=source_value,
        preview=bool(args.preview),
        offline_fast=True,
        file_prefix=file_prefix,
        logger=logger,
    )
    status = app.run()
    if status == 0:
        _run_auto_analysis(
            config=config,
            no_auto_analyze=bool(args.no_auto_analyze),
            session_dir=session_dir,
            logger=logger,
        )
    return status, session_dir


def _cmd_analyze_session(args: argparse.Namespace) -> None:
    session_dir = Path(args.session_dir)
    logger = setup_logging(session_dir, file_prefix=detect_session_file_prefix(session_dir))
    summary_path = analyze_session(
        session_dir=session_dir,
        cm_per_px_override=args.cm_per_px,
        # Keep backward compatibility with --fixed_fps_hz while preferring the new unified --fixed_fps.
        fixed_fps_hz_override=(args.fixed_fps if args.fixed_fps is not None else args.fixed_fps_hz),
        output_plots_override=(False if args.no_plots else None),
        render_overlay_video=bool(args.render_overlay_video),
        overlay_video_source_override=(Path(args.overlay_video_source) if args.overlay_video_source else None),
        overlay_video_filename_override=args.overlay_video_filename,
        logger=logger,
    )
    print(summary_path)


def _run_auto_analysis(
    config: Dict[str, Any],
    no_auto_analyze: bool,
    session_dir: Path,
    logger,
) -> None:
    analysis_cfg = config.get("analysis", {}) if isinstance(config.get("analysis", {}), dict) else {}
    auto_analyze = bool(analysis_cfg.get("auto_after_run", True)) and (not bool(no_auto_analyze))
    logger.info(
        "Auto analysis config: auto_after_run=%s no_auto_analyze=%s output_plots=%s",
        bool(analysis_cfg.get("auto_after_run", True)),
        bool(no_auto_analyze),
        bool(analysis_cfg.get("output_plots", True)),
    )
    if auto_analyze:
        logger.info("Auto analysis started for session: %s", session_dir)
        try:
            summary_path = analyze_session(
                session_dir=session_dir,
                cm_per_px_override=None,
                fixed_fps_hz_override=None,
                output_plots_override=None,
                logger=logger,
            )
            logger.info("Auto analysis finished: %s", summary_path)
        except Exception:
            logger.exception("Auto analysis failed for session: %s", session_dir)


def _cmd_analyze_issues(args: argparse.Namespace) -> None:
    session_dir = Path(args.session_dir)
    logger = setup_logging(session_dir, file_prefix=detect_session_file_prefix(session_dir))
    outputs = analyze_issues(
        session_dir=session_dir,
        issue_file_override=args.issue_file,
        logger=logger,
    )
    print(outputs["issue_summary"])
    print(outputs["issue_timeline"])
    print(outputs["incident_summary"])


def _cmd_analyze_batch(args: argparse.Namespace) -> None:
    root_dir = Path(args.root_dir)
    if not root_dir.exists():
        raise FileNotFoundError(f"Root directory not found: {root_dir}")

    session_dirs = _discover_session_dirs(root_dir=root_dir, recursive=bool(args.recursive))
    if not session_dirs:
        raise RuntimeError(f"No valid session folder found under: {root_dir}")

    rows: List[Dict[str, Any]] = []
    failed = 0

    for session_dir in session_dirs:
        logger = setup_logging(session_dir, file_prefix=detect_session_file_prefix(session_dir))
        logger.info("Batch analyze started: %s", session_dir)
        row: Dict[str, Any] = {
            "session_dir": str(session_dir),
            "status": "ok",
            "summary_path": "",
            "issue_summary_path": "",
            "issue_timeline_path": "",
            "incident_summary_path": "",
            "error": "",
        }
        try:
            summary_path = analyze_session(
                session_dir=session_dir,
                cm_per_px_override=args.cm_per_px,
                fixed_fps_hz_override=(args.fixed_fps if args.fixed_fps is not None else args.fixed_fps_hz),
                output_plots_override=(False if args.no_plots else None),
                render_overlay_video=bool(getattr(args, "render_overlay_video", False)),
                overlay_video_source_override=None,
                overlay_video_filename_override=getattr(args, "overlay_video_filename", None),
                logger=logger,
            )
            row["summary_path"] = str(summary_path)

            if bool(args.include_issues):
                issue_outputs = analyze_issues(session_dir=session_dir, logger=logger)
                row["issue_summary_path"] = str(issue_outputs["issue_summary"])
                row["issue_timeline_path"] = str(issue_outputs["issue_timeline"])
                row["incident_summary_path"] = str(issue_outputs["incident_summary"])

            logger.info("Batch analyze finished: %s", session_dir)
        except Exception as exc:
            failed += 1
            row["status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("Batch analyze failed: %s", session_dir)
            if bool(args.fail_fast):
                rows.append(row)
                report_path = root_dir / str(args.report_name)
                pd.DataFrame(rows).to_csv(report_path, index=False)
                print(report_path)
                raise

        rows.append(row)

    report_path = root_dir / str(args.report_name)
    pd.DataFrame(rows).to_csv(report_path, index=False)
    print(report_path)
    if failed > 0:
        raise SystemExit(2)


def _cmd_calibrate_roi(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    config = load_yaml(config_path)

    with_neutral = not bool(args.without_neutral)
    camera_updates: Optional[Dict[str, object]] = None

    if args.image:
        frame = _load_calibration_image(args.image)
        roi_points = calibrate_roi_with_frame(frame, with_neutral=with_neutral)
    else:
        cam = _open_calibration_camera(config, args.camera_source)
        try:
            roi_points, camera_updates = calibrate_roi_with_camera(
                cam,
                with_neutral=with_neutral,
                exposure_step=float(args.exposure_step),
                gain_step=float(args.gain_step),
            )
        finally:
            cam.release()

    roi_cfg: Dict[str, Any] = config.setdefault("roi", {})
    roi_cfg["type"] = "polygon"
    roi_cfg["chamber1"] = roi_points["chamber1"]
    roi_cfg["chamber2"] = roi_points["chamber2"]
    if with_neutral and "neutral" in roi_points:
        roi_cfg["neutral"] = roi_points["neutral"]
    else:
        roi_cfg.pop("neutral", None)

    if camera_updates:
        cam_cfg: Dict[str, Any] = config.setdefault("camera", {})
        cam_cfg.update(camera_updates)

    save_path = Path(args.save_to) if args.save_to else config_path
    save_yaml(config, save_path)
    print(save_path)


def _load_calibration_image(image_path: str):
    frame = cv2.imread(image_path)
    if frame is None:
        raise RuntimeError(f"Failed to read image: {image_path}")
    return frame


def _open_calibration_camera(config: Dict[str, Any], camera_source: Optional[str]) -> CameraStream:
    cam_cfg = dict(config.get("camera", {}))
    if camera_source is not None:
        cam_cfg["source"] = _parse_source(camera_source)

    cfg = CameraConfig(
        source=cam_cfg.get("source", 0),
        width=cam_cfg.get("width"),
        height=cam_cfg.get("height"),
        fps_target=cam_cfg.get("fps_target"),
        auto_exposure=cam_cfg.get("auto_exposure"),
        exposure=cam_cfg.get("exposure"),
        gain=cam_cfg.get("gain"),
        flip=bool(cam_cfg.get("flip", False)),
        rotate_deg=int(cam_cfg.get("rotate_deg", 0)),
    )
    return CameraStream(cfg)


def _parse_source(raw: Union[str, int, None]) -> Union[str, int]:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    text = str(raw)
    if text.isdigit():
        return int(text)
    return text


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n", ""}:
        return False
    return bool(default)


def _is_session_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    direct = path / "cpp_realtime_log.csv"
    if direct.exists():
        return True
    prefixed = list(path.glob("*_cpp_realtime_log.csv"))
    return len(prefixed) > 0


def _discover_offline_videos(root_dir: Path, recursive: bool) -> List[Path]:
    iterator = root_dir.rglob("*") if recursive else root_dir.iterdir()
    session_dirs = [p for p in iterator if p.is_dir() and _is_session_folder_for_offline(p)]
    if _is_session_folder_for_offline(root_dir):
        session_dirs.append(root_dir)

    selected: List[Path] = []
    seen_dirs: set[Path] = set()
    for session_dir in sorted({p.resolve() for p in session_dirs}):
        sdir = Path(session_dir)
        if sdir in seen_dirs:
            continue
        seen_dirs.add(sdir)
        picked = _find_session_raw_video(sdir)
        if picked is not None:
            selected.append(picked)
    return selected


def _is_session_folder_for_offline(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.name.lower().startswith("session_"):
        return True
    if any(path.glob("*_metadata.json")):
        return True
    if any(path.glob("*_config_used.yaml")):
        return True
    if any(path.glob("*_cpp_realtime_log.csv")):
        return True
    return False


def _find_session_raw_video(session_dir: Path) -> Optional[Path]:
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".mpg", ".mpeg"}
    files = [p for p in session_dir.iterdir() if p.is_file() and p.suffix.lower() in video_exts]
    if not files:
        return None

    def score(p: Path) -> tuple[int, str]:
        name = p.name.lower()
        # Strict preference: any session raw video naming.
        if "_raw_video" in name or name.startswith("raw_video"):
            return (0, name)
        if "raw" in name and "preview" not in name and "overlay" not in name:
            return (1, name)
        # Preview/overlay videos are not valid sources for this batch mode.
        if "preview" in name or "overlay" in name:
            return (9, name)
        return (5, name)

    ranked = sorted(files, key=score)
    best = ranked[0]
    best_score = score(best)[0]
    # Require a raw-like filename in session folders to avoid accidental selection.
    if best_score > 1:
        return None
    return best


def _discover_session_dirs(root_dir: Path, recursive: bool) -> List[Path]:
    candidates: List[Path] = []
    if _is_session_dir(root_dir):
        candidates.append(root_dir)

    iterator = root_dir.rglob("*") if recursive else root_dir.iterdir()
    for path in iterator:
        if path.is_dir() and _is_session_dir(path):
            candidates.append(path)

    # Deduplicate while preserving stable sorted order.
    unique = sorted({p.resolve() for p in candidates})
    return [Path(p) for p in unique]


def _resolve_session_info(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    existing = config.get("session_info", {}) if isinstance(config.get("session_info", {}), dict) else {}
    laser_cfg = config.get("laser_control", {}) if isinstance(config.get("laser_control", {}), dict) else {}
    acclimation_cfg = config.get("acclimation", {}) if isinstance(config.get("acclimation", {}), dict) else {}

    default_mouse = str(args.mouse_id if args.mouse_id is not None else existing.get("mouse_id", "")).strip()
    default_group = str(args.group if args.group is not None else existing.get("group", "")).strip()
    default_laser_mode = str(existing.get("laser_mode", "")).strip() or str(laser_cfg.get("mode", "pulse")).strip()
    default_pulse_freq = existing.get("pulse_freq_hz", laser_cfg.get("freq_hz"))
    pulse_freq_seed = _optional_float(default_pulse_freq)
    default_acclimation_enabled_raw = existing.get("acclimation_enabled", acclimation_cfg.get("enabled", False))
    default_acclimation_enabled = _to_bool(default_acclimation_enabled_raw, default=False)
    default_acclimation_duration = existing.get("acclimation_duration_s", acclimation_cfg.get("duration_s"))
    acclimation_duration_seed = _optional_float(default_acclimation_duration)

    duration_seed = args.experiment_duration_s
    if duration_seed is None:
        duration_seed = args.duration_s
    if duration_seed is None:
        duration_seed = existing.get("experiment_duration_s")

    if bool(args.no_session_prompt):
        mouse_id = sanitize_name_component(default_mouse)
        group = sanitize_name_component(default_group)
        if not mouse_id or not group:
            raise ValueError("mouse_id/group are required when --no_session_prompt is used")
        if duration_seed is None:
            raise ValueError("experiment_duration_s or duration_s is required when --no_session_prompt is used")
        duration_s = float(duration_seed)
        if duration_s <= 0:
            raise ValueError("experiment_duration_s must be > 0")
        laser_mode = _normalize_user_laser_mode(default_laser_mode)
        pulse_freq_hz = (pulse_freq_seed if pulse_freq_seed is not None else 20.0) if laser_mode == "pulse" else None
        if laser_mode == "pulse" and (pulse_freq_hz is None or pulse_freq_hz <= 0):
            raise ValueError("laser pulse_freq_hz must be > 0 when laser_mode=pulse")
        acclimation_enabled = default_acclimation_enabled
        acclimation_duration_s = 0.0
        if acclimation_enabled:
            if acclimation_duration_seed is None or acclimation_duration_seed <= 0:
                raise ValueError("acclimation duration must be > 0 when acclimation_enabled=true")
            acclimation_duration_s = float(acclimation_duration_seed)
        return {
            "mouse_id": mouse_id,
            "group": group,
            "experiment_duration_s": duration_s,
            "laser_mode": laser_mode,
            "pulse_freq_hz": pulse_freq_hz,
            "acclimation_enabled": acclimation_enabled,
            "acclimation_duration_s": acclimation_duration_s,
        }

    info = collect_session_info(
        default_mouse_id=default_mouse,
        default_group=default_group,
        default_duration_s=(float(duration_seed) if duration_seed is not None else None),
        default_laser_mode=_normalize_user_laser_mode(default_laser_mode),
        default_pulse_freq_hz=pulse_freq_seed,
        default_acclimation_enabled=default_acclimation_enabled,
        default_acclimation_duration_s=acclimation_duration_seed,
    )
    info["mouse_id"] = sanitize_name_component(info.get("mouse_id", ""))
    info["group"] = sanitize_name_component(info.get("group", ""))
    if not info["mouse_id"] or not info["group"]:
        raise ValueError("mouse_id/group cannot be empty")
    info["experiment_duration_s"] = float(info.get("experiment_duration_s"))
    info["laser_mode"] = _normalize_user_laser_mode(info.get("laser_mode", default_laser_mode))
    info["pulse_freq_hz"] = _optional_float(info.get("pulse_freq_hz"))
    if info["laser_mode"] == "pulse":
        if info["pulse_freq_hz"] is None or info["pulse_freq_hz"] <= 0:
            raise ValueError("laser pulse_freq_hz must be > 0 when laser_mode=pulse")
    else:
        info["pulse_freq_hz"] = None
    info["acclimation_enabled"] = _to_bool(info.get("acclimation_enabled"), default=False)
    info["acclimation_duration_s"] = _optional_float(info.get("acclimation_duration_s"))
    if info["acclimation_enabled"]:
        if info["acclimation_duration_s"] is None or info["acclimation_duration_s"] <= 0:
            raise ValueError("acclimation duration must be > 0 when acclimation_enabled=true")
    else:
        info["acclimation_duration_s"] = 0.0
    return info


def _resolve_offline_session_info(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    existing = config.get("session_info", {}) if isinstance(config.get("session_info", {}), dict) else {}

    mouse_id = sanitize_name_component(args.mouse_id if args.mouse_id is not None else existing.get("mouse_id", "offline"))
    group = sanitize_name_component(args.group if args.group is not None else existing.get("group", "replay"))

    duration_seed = args.experiment_duration_s
    if duration_seed is None:
        duration_seed = args.duration_s
    if duration_seed is None:
        duration_seed = existing.get("experiment_duration_s")
    if duration_seed is None:
        duration_seed = 1.0

    duration_s = float(duration_seed)
    if duration_s <= 0:
        duration_s = 1.0

    return {
        "mouse_id": (mouse_id or "offline"),
        "group": (group or "replay"),
        "experiment_duration_s": duration_s,
    }


def _normalize_user_laser_mode(mode: Any) -> str:
    text = str(mode).strip().lower()
    if text in {"", "dryrun", "real"}:
        return "pulse"
    if text in {"continuous", "continues", "level"}:
        return "continuous"
    if text in {"pulse", "gated", "startstop"}:
        return "pulse"
    raise ValueError(f"laser mode must be continuous|pulse, got: {mode}")


def _apply_session_laser_settings(config: Dict[str, Any], session_info: Dict[str, Any]) -> None:
    laser_mode = str(session_info.get("laser_mode", "")).strip()
    if not laser_mode:
        return

    laser_cfg = config.setdefault("laser_control", {})
    if not isinstance(laser_cfg, dict):
        return

    normalized = _normalize_user_laser_mode(laser_mode)
    current_mode_raw = str(laser_cfg.get("mode", "dryrun")).strip().lower()

    if normalized == "continuous":
        laser_cfg["mode"] = "continuous"
        return

    # Keep legacy low-level mode (gated/startstop) if config already uses it,
    # otherwise use the pulse alias and existing pulse_mode setting.
    if current_mode_raw not in {"gated", "startstop"}:
        laser_cfg["mode"] = "pulse"

    pulse_freq = _optional_float(session_info.get("pulse_freq_hz"))
    if pulse_freq is not None and pulse_freq > 0:
        laser_cfg["freq_hz"] = float(pulse_freq)


def _apply_session_acclimation_settings(config: Dict[str, Any], session_info: Dict[str, Any]) -> None:
    acclimation_cfg = config.setdefault("acclimation", {})
    if not isinstance(acclimation_cfg, dict):
        return
    enabled = _to_bool(session_info.get("acclimation_enabled"), default=False)
    duration_s = _optional_float(session_info.get("acclimation_duration_s"))
    acclimation_cfg["enabled"] = bool(enabled)
    acclimation_cfg["duration_s"] = float(duration_s) if enabled and duration_s is not None and duration_s > 0 else 0.0


def _apply_prefixed_output_names(config: Dict[str, Any], file_prefix: str) -> None:
    runtime_cfg = config.setdefault("runtime_logging", {})
    if isinstance(runtime_cfg, dict):
        issue_file = str(runtime_cfg.get("issue_events_file", "issue_events.jsonl"))
        runtime_cfg["issue_events_file"] = ensure_prefixed_filename(issue_file, file_prefix)

    preview_cfg = config.setdefault("preview_recording", {})
    if isinstance(preview_cfg, dict):
        preview_filename = str(preview_cfg.get("filename", "preview_overlay.mp4"))
        preview_cfg["filename"] = ensure_prefixed_filename(preview_filename, file_prefix)

    raw_cfg = config.setdefault("raw_recording", {})
    if isinstance(raw_cfg, dict):
        raw_filename = str(raw_cfg.get("filename", "raw_video.mp4"))
        raw_cfg["filename"] = ensure_prefixed_filename(raw_filename, file_prefix)


if __name__ == "__main__":
    main(sys.argv[1:])
