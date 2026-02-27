from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

import cv2

from cpp_dlc_live.analysis.analyze import analyze_session
from cpp_dlc_live.realtime.app import RealtimeApp
from cpp_dlc_live.realtime.camera import CameraConfig, CameraStream
from cpp_dlc_live.realtime.logging_utils import setup_logging
from cpp_dlc_live.realtime.roi import calibrate_roi_with_frame
from cpp_dlc_live.utils.io_utils import file_sha256, load_yaml, prepare_session_dir, save_yaml


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run_realtime":
        _cmd_run_realtime(args)
        return
    if args.command == "analyze_session":
        _cmd_analyze_session(args)
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
    p_run.add_argument("--no_preview", action="store_true", help="Disable OpenCV preview window")

    p_an = sub.add_parser("analyze_session", help="Analyze one session directory")
    p_an.add_argument("--session_dir", required=True, help="Path to session directory")
    p_an.add_argument("--cm_per_px", type=float, default=None, help="Override cm_per_px")
    p_an.add_argument("--no_plots", action="store_true", help="Disable plot output")

    p_cal = sub.add_parser("calibrate_roi", help="Interactive ROI calibrator")
    p_cal.add_argument("--config", required=True, help="Config YAML to load/update")
    p_cal.add_argument("--camera_source", default=None, help="Camera source override (int index or URL/path)")
    p_cal.add_argument("--image", default=None, help="Use static image instead of camera")
    p_cal.add_argument("--save_to", default=None, help="Output YAML path (default: overwrite --config)")
    p_cal.add_argument("--without_neutral", action="store_true", help="Calibrate only chamber1/chamber2")

    return parser


def _cmd_run_realtime(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    config = load_yaml(config_path)

    camera_override = _parse_source(args.camera_source) if args.camera_source is not None else None
    if camera_override is not None:
        config.setdefault("camera", {})["source"] = camera_override

    session_dir = prepare_session_dir(config, out_dir_override=args.out_dir)

    used_cfg_path = session_dir / "config_used.yaml"
    save_yaml(config, used_cfg_path)

    logger = setup_logging(session_dir)
    logger.info("Config copied to: %s", used_cfg_path)
    logger.info("Config sha256: %s", file_sha256(used_cfg_path))

    app = RealtimeApp(
        config=config,
        session_dir=session_dir,
        duration_s=args.duration_s,
        camera_source_override=camera_override,
        preview=not bool(args.no_preview),
        logger=logger,
    )
    status = app.run()
    if status != 0:
        raise SystemExit(status)


def _cmd_analyze_session(args: argparse.Namespace) -> None:
    session_dir = Path(args.session_dir)
    logger = setup_logging(session_dir)
    summary_path = analyze_session(
        session_dir=session_dir,
        cm_per_px_override=args.cm_per_px,
        output_plots_override=(False if args.no_plots else None),
        logger=logger,
    )
    print(summary_path)


def _cmd_calibrate_roi(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    config = load_yaml(config_path)

    frame = _load_calibration_frame(config, args.image, args.camera_source)
    with_neutral = not bool(args.without_neutral)

    roi_points = calibrate_roi_with_frame(frame, with_neutral=with_neutral)

    roi_cfg: Dict[str, Any] = config.setdefault("roi", {})
    roi_cfg["type"] = "polygon"
    roi_cfg["chamber1"] = roi_points["chamber1"]
    roi_cfg["chamber2"] = roi_points["chamber2"]
    if with_neutral and "neutral" in roi_points:
        roi_cfg["neutral"] = roi_points["neutral"]
    else:
        roi_cfg.pop("neutral", None)

    save_path = Path(args.save_to) if args.save_to else config_path
    save_yaml(config, save_path)
    print(save_path)


def _load_calibration_frame(config: Dict[str, Any], image_path: Optional[str], camera_source: Optional[str]):
    if image_path:
        frame = cv2.imread(image_path)
        if frame is None:
            raise RuntimeError(f"Failed to read image: {image_path}")
        return frame

    cam_cfg = dict(config.get("camera", {}))
    if camera_source is not None:
        cam_cfg["source"] = _parse_source(camera_source)

    cfg = CameraConfig(
        source=cam_cfg.get("source", 0),
        width=cam_cfg.get("width"),
        height=cam_cfg.get("height"),
        fps_target=cam_cfg.get("fps_target"),
        flip=bool(cam_cfg.get("flip", False)),
        rotate_deg=int(cam_cfg.get("rotate_deg", 0)),
    )
    cam = CameraStream(cfg)
    try:
        ok, frame = cam.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to capture frame for ROI calibration")
        return frame
    finally:
        cam.release()


def _parse_source(raw: Union[str, int, None]) -> Union[str, int]:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    text = str(raw)
    if text.isdigit():
        return int(text)
    return text


if __name__ == "__main__":
    main(sys.argv[1:])
