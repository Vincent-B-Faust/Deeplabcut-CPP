# cpp_dlc_live

End-to-end Python project for **real-time closed-loop 2-chamber CPP experiments** using:
- video/camera acquisition
- DeepLabCut-live inference
- ROI chamber classification + debounce
- NI cDAQ TTL control (`gated` / `startstop`) or `dryrun`
- offline session analysis and issue traceback

`README.md` is the default **English** documentation for GitHub.

Chinese docs:
- [Chinese Documentation Entry](docs/user_guide_zh.md)
- [Operator Guide (中文)](docs/operator_guide_zh.md)
- [Developer Guide (中文)](docs/developer_guide_zh.md)
- [New Computer Setup Guide (中文)](docs/new_computer_setup_zh.md)
- [DeepLabCut GUI 配置教程（中文）](docs/deeplabcut_gui_setup_zh.md)

Beginner setup docs:
- [New Computer Setup Guide (EN)](docs/new_computer_setup_en.md)
- [新电脑部署指南（中文）](docs/new_computer_setup_zh.md)
- [DeepLabCut GUI 配置教程（中文）](docs/deeplabcut_gui_setup_zh.md)

For multi-device deployment details (pip/conda/docker/lock files), see:
- [DEPLOYMENT_REQUIREMENTS.md](DEPLOYMENT_REQUIREMENTS.md)

## Table of Contents

1. [What This Project Solves](#what-this-project-solves)
2. [Core Features](#core-features)
3. [Repository Layout](#repository-layout)
4. [Environment and Installation](#environment-and-installation)
5. [DeepLabCut-live Model Preparation](#deeplabcut-live-model-preparation)
6. [Configuration Guide](#configuration-guide)
7. [CLI Commands](#cli-commands)
8. [Recommended End-to-End Workflow](#recommended-end-to-end-workflow)
9. [Session Outputs and File Meanings](#session-outputs-and-file-meanings)
10. [Performance, Safety, and Failure Behavior](#performance-safety-and-failure-behavior)
11. [Troubleshooting](#troubleshooting)
12. [Development and Tests](#development-and-tests)
13. [Beginner Setup Guides](#beginner-setup-guides)

## What This Project Solves

This project is designed for 2-chamber CPP experiments where behavior state controls stimulation in real time.

Runtime loop:
1. Acquire frame from camera/video.
2. Infer pose with DLC-live.
3. Determine chamber (`chamber1/chamber2/neutral/unknown`) from ROI.
4. Stabilize chamber state with debounce.
5. Control laser output (`ON` in chamber1, `OFF` otherwise by default).
6. Save frame-level logs and metadata.
7. Optionally preview and record annotated overlay video.

After runtime:
1. Analyze `cpp_realtime_log.csv` into summary metrics.
2. Optionally generate plots.
3. Analyze issue events and incident reports for traceback.

## Core Features

- Real-time modules:
  - camera/video stream (`opencv`)
  - DLC-live inference (`dlclive`) with configurable backend (`auto/pytorch/tensorflow`)
  - polygon/rect ROI classification
  - debounce for robust state transitions
  - confidence threshold + hold-last-valid logic
  - OpenCV overlay preview (including runtime timer `HH:MM:SS.mmm`)
- Laser control modes:
  - `gated`: continuous counter pulse + digital enable line
  - `startstop`: on-demand counter start/stop with min on/off dwell
  - `dryrun`: no hardware output, full logic path enabled
- Safety behavior:
  - default output state is OFF
  - on camera/DLC/DAQ/ROI exceptions, force OFF and shutdown cleanly
- Recording and traceability:
  - frame-level CSV log
  - session metadata + config copy + config hash
  - structured issue events (`JSONL`)
  - incident report JSON on runtime failure
- Offline analysis:
  - chamber occupancy time
  - distance and mean speed (px/s and optional cm/s)
  - laser-on duration
  - optional trajectory/speed/occupancy plots
- Test coverage includes ROI, debounce, analysis metrics, and issue analysis parser.

## Repository Layout

```text
cpp_dlc_live/
  README.md
  DEPLOYMENT_REQUIREMENTS.md
  Dockerfile
  pyproject.toml
  requirements/
  environment.*.yml
  config/
    config_example.yaml
  cpp_dlc_live/
    cli.py
    realtime/
    analysis/
    utils/
  tests/
  docs/
```

Key code entry points:
- CLI entry: `cpp_dlc_live/cli.py`
- Realtime app: `cpp_dlc_live/realtime/app.py`
- Offline analysis: `cpp_dlc_live/analysis/analyze.py`
- Issue analysis: `cpp_dlc_live/analysis/issues.py`

## Environment and Installation

If you are deploying on a brand-new machine, follow these first:
- [New Computer Setup Guide (EN)](docs/new_computer_setup_en.md)
- [新电脑部署指南（中文）](docs/new_computer_setup_zh.md)

## Supported OS

- Windows 10/11 (recommended for NI workflows)
- Linux (dryrun/DLC/NI depending on driver setup)
- macOS (typically dryrun + analysis, NI is uncommon)

Recommended Python: `3.10`.

## Option A: pip + requirements (recommended)

1. Create and activate virtual environment.

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
```

2. Upgrade packaging tools.

```bash
python -m pip install --upgrade pip setuptools wheel
```

3. Install profile.

```bash
# Minimal dryrun/analysis
pip install -r requirements/base.txt

# DLC-enabled (no NI)
pip install -r requirements/dlc.txt

# Full profile by OS
# Linux:   pip install -r requirements/full-linux.txt
# macOS:   pip install -r requirements/full-macos.txt
# Windows: pip install -r requirements/full-windows.txt
```

4. Install package in editable mode.

```bash
pip install -e .
```

## Option B: conda

```bash
# Windows base
conda env create -f environment.windows.base.yml
conda activate cpp_dlc_live_windows_base

# Windows full
# conda env create -f environment.windows.full.yml
# conda activate cpp_dlc_live_windows_full

# Linux/macOS variants are also provided:
# environment.linux.*.yml
# environment.macos.*.yml
```

## NI requirement (only NI hardware mode)

- Install NI-DAQmx driver on target machine.
- Confirm NI device visibility in NI MAX.
- Confirm Python package works in your active env:

```bash
python -c "import nidaqmx; print('nidaqmx ok')"
```

## Quick environment sanity checks

```bash
python -m cpp_dlc_live.cli --help
python -c "import cv2, numpy, pandas, yaml; print('base ok')"
python -c "import dlclive; print('dlclive ok')"   # if DLC is needed
```

## Beginner Setup Guides

- English: [New Computer Setup Guide (EN)](docs/new_computer_setup_en.md)
- 中文: [新电脑部署指南（中文）](docs/new_computer_setup_zh.md)
- 中文: [DeepLabCut GUI 配置教程（Windows/Conda/RTX 5070 Ti）](docs/deeplabcut_gui_setup_zh.md)

## DeepLabCut-live Model Preparation

This is the most common source of runtime confusion.

## Important distinction

- `dlc-models-pytorch/.../train/snapshot-*.pt` are **training snapshots**.
- For realtime DLCLive inference, use **exported model artifacts** expected by DLCLive.

If you directly point `model_path` to an incompatible training snapshot, you may see errors like:
- `KeyError: 'config'`
- fallback to mock runtime

## Recommended workflow

1. Train/evaluate in DeepLabCut.
2. Export model for live inference per official docs.
3. Point `dlc.model_path` to exported DLCLive-compatible model path.
4. Set backend explicitly for DLC 3.0 PyTorch projects:
   - `dlc.backend: pytorch`

References:
- DeepLabCut docs: <https://deeplabcut.github.io/DeepLabCut/>
- DeepLabCut-live repo/docs: <https://github.com/DeepLabCut/DeepLabCut-live>

## Configuration Guide

Use `config/config_example.yaml` as a template, then create your local runtime config (for example `config/config_windows_dryrun.yaml`).

Note: always replace any machine-specific paths with your own absolute paths.

## Top-level config sections

- `project`: session naming and output location
- `fixed_fps`: optional global fixed FPS for runtime + recording + analysis
- `session_info`: mouse/group/planned duration metadata (used by naming prompt)
- `camera`: source and transform options
- `dlc`: model path/backend/bodypart/confidence/smoothing
- `roi`: chamber polygons/rectangles + neutral policy + debounce
- `laser_control`: hardware strategy and channels
- `analysis`: offline metric options
- `preview_recording`: optional save of preview video
- `raw_recording`: optional save of raw (unannotated) video
- `runtime_logging`: issue/heartbeat/warning settings

## Field reference (practical)

### `project`
- `project.session_id`: fixed id or `auto_timestamp`
- `project.out_dir`: output root; session subdirectory is created automatically

### `fixed_fps`
- `fixed_fps`: optional global fixed FPS (Hz)
  - When set, it overrides camera realtime cadence and recording writer FPS selection.
  - Offline analysis also uses this fixed timebase unless CLI override is given.

### `session_info`
- `session_info.mouse_id`: mouse identifier
- `session_info.group`: group label
- `session_info.experiment_duration_s`: planned duration in seconds
- `run_realtime` opens a popup before start (with history dropdowns) to confirm/edit these values.

### `camera`
- `camera.source`: camera index (`0`) or video path/URL
- `camera.width`, `camera.height`, `camera.fps_target`
  - For camera devices, `fps_target` is requested via OpenCV capture settings.
  - For video-file sources, `fps_target` is also used to throttle playback to realtime speed.
  - Set `camera.enforce_fps=true` to throttle realtime loop to `fps_target` even on camera input.
- `camera.file_realtime_throttle`: `true` (default) | `false`
  - `true`: when source is a video file, replay is throttled to realtime.
  - `false`: process file as fast as possible (recommended for offline fast replay).
- `camera.auto_exposure`: `true` (auto) | `false` (manual lock) | `null` (leave driver default)
- `camera.exposure`: manual exposure value (`auto_exposure=false` recommended); unit/range is camera-driver specific
- `camera.gain`: optional gain value; unit/range is camera-driver specific
- `camera.flip`, `camera.rotate_deg`

### `dlc`
- `dlc.model_path`: DLCLive model path (typically exported artifact)
- `dlc.backend`: `auto` | `pytorch` | `tensorflow`
- `dlc.device`: `auto` | `cpu` | `cuda` | `cuda:0` (passed to DLCLive when supported)
- `dlc.strict_runtime`: `false` (default) | `true`
  - `true`: fail fast if DLCLive cannot initialize (no fallback to mock runtime).
  - recommended for real experiments to avoid silent incorrect tracking.
- `dlc.bodypart`: control bodypart used for ROI/chamber and laser logic
- `dlc.display_bodyparts`: optional preview overlay bodyparts list, e.g. `["head","tail","center"]` or `["all"]`
  - If omitted/null, preview shows only the control bodypart point.
  - This setting does not change ROI/laser decisions.
- `dlc.p_thresh`: confidence threshold
- `dlc.smoothing.enabled`, `dlc.smoothing.window`

### `roi`
- `roi.type`: `polygon` | `rect`
- `roi.chamber1`, `roi.chamber2`, optional `roi.neutral`
- `roi.strategy_on_neutral`: `off` | `hold_last` | `unknown`
- `roi.debounce_frames`

### `laser_control`
- `laser_control.enabled`
- `laser_control.mode`: `gated` | `startstop` | `dryrun`
- `laser_control.freq_hz`, `laser_control.duty_cycle`
- `laser_control.ctr_channel`, `laser_control.pulse_term`, `laser_control.enable_line`
- `laser_control.min_on_s`, `laser_control.min_off_s` (startstop)
- `laser_control.unknown_policy`: `off` | `hold_last`
- `laser_control.fallback_to_dryrun`

### `analysis`
- `analysis.auto_after_run`: run `analyze_session` automatically right after successful realtime run
- `analysis.cm_per_px`
- `analysis.fixed_fps_hz`: optional fixed timebase for speed/occupancy metrics (ignores frame timestamp jitter)
- `analysis.output_plots`

### `preview_recording`
- `preview_recording.enabled`: save preview video or not
- `preview_recording.filename`: relative path is resolved under session dir
- `preview_recording.codec`: 4-char codec (e.g. `mp4v`)
- `preview_recording.fps`: optional explicit writer FPS override
  - Writer FPS selection order: `preview_recording.fps` -> `camera.fps_target` -> camera reported FPS -> `30`.
- `preview_recording.overlay`: save annotated frame (`true`) or raw frame (`false`)

### `raw_recording`
- `raw_recording.enabled`: save an additional raw stream (no overlays)
- `raw_recording.filename`: relative path is resolved under session dir
- `raw_recording.codec`: 4-char codec (e.g. `mp4v`)
- `raw_recording.fps`: optional explicit writer FPS override
  - Writer FPS selection order: `raw_recording.fps` -> `camera.fps_target` -> camera reported FPS -> `30`.

### `runtime_logging`
- `runtime_logging.enabled`
- `runtime_logging.issue_events_file`
- `runtime_logging.heartbeat_interval_s`
- `runtime_logging.low_conf_warn_every_n`
- `runtime_logging.inference_warn_ms`
- `runtime_logging.fps_warn_below`

## Example: minimal Windows dryrun + DLC

```yaml
project:
  name: cpp_dlc_live
  session_id: auto_timestamp
  out_dir: D:/data/cpp_runs
fixed_fps: null
session_info:
  mouse_id: M001
  group: Control
  experiment_duration_s: 600

camera:
  source: C:/data/videos/test.avi
  width: 1280
  height: 720
  fps_target: 30
  enforce_fps: false
  auto_exposure: null
  exposure: null
  gain: null
  flip: false
  rotate_deg: 0

dlc:
  model_path: C:/data/models/exported-models-pytorch/your_model.pt
  backend: pytorch
  device: cuda
  strict_runtime: true
  bodypart: Mouse
  display_bodyparts: [head, tail, center]
  p_thresh: 0.2
  smoothing:
    enabled: false
    window: 5

roi:
  type: polygon
  chamber1: [[50, 50], [600, 50], [600, 650], [50, 650]]
  chamber2: [[680, 50], [1230, 50], [1230, 650], [680, 650]]
  strategy_on_neutral: off
  debounce_frames: 8

laser_control:
  enabled: true
  mode: dryrun
  freq_hz: 20.0
  duty_cycle: 0.05
  ctr_channel: cDAQ1Mod4/ctr0
  pulse_term: /cDAQ1Mod4/PFI0
  enable_line: cDAQ1Mod4/port0/line0
  min_on_s: 0.2
  min_off_s: 0.2
  unknown_policy: off
  fallback_to_dryrun: true

analysis:
  auto_after_run: true
  cm_per_px: null
  fixed_fps_hz: null
  output_plots: true

preview_recording:
  enabled: true
  filename: preview_overlay.mp4
  codec: mp4v
  fps: 30
  overlay: true

raw_recording:
  enabled: true
  filename: raw_video.mp4
  codec: mp4v
  fps: 30

runtime_logging:
  enabled: true
  issue_events_file: issue_events.jsonl
  heartbeat_interval_s: 5.0
  low_conf_warn_every_n: 30
  inference_warn_ms: 80.0
  fps_warn_below: 10.0
```

## CLI Commands

The project installs a console script `cpp-dlc-live`, and also supports `python -m cpp_dlc_live.cli`.

## 1) `run_realtime`

```bash
cpp-dlc-live run_realtime --config config/config_example.yaml
```

Common options:
- `--out_dir /path/to/output_root`
- `--duration_s 600`
- `--camera_source 0` (or video path/URL)
- `--fixed_fps 30`
- `--no_preview` (disable window display)
- `--mouse_id M001`
- `--group Control`
- `--experiment_duration_s 600`
- `--no_session_prompt` (skip popup and use provided values)
- `--no_auto_analyze` (skip automatic post-run analysis/plots)

Notes:
- `preview_recording.enabled=true` can still record video even when `--no_preview` is used.
- Set both `preview_recording.enabled=true` and `raw_recording.enabled=true` to save both overlay and raw videos simultaneously.
- On input video EOF, run exits normally.
- Session folder name is expanded to include `timestamp + mouse_id + group + duration`.
- Output files are prefixed with resolved session id.
- By default, analysis is auto-run after each successful realtime session and writes Figure1–Figure5 plus summary.

## 2) `analyze_session`

```bash
cpp-dlc-live analyze_session --session_dir data/session_20260226_120000
```

Options:
- `--cm_per_px 0.05`
- `--fixed_fps 30`
- `--fixed_fps_hz 30`
- `--no_plots`
- `--render_overlay_video` (render an offline annotated video from session log + source video)
- `--overlay_video_source /path/to/raw_or_preview.mp4` (optional source override)
- `--overlay_video_filename analysis_overlay.mp4` (optional output filename)

Typical dryrun/offline workflow:

```bash
cpp-dlc-live analyze_session \
  --session_dir data/session_20260226_120000 \
  --render_overlay_video \
  --no_plots
```

## 3) `analyze_issues`

```bash
cpp-dlc-live analyze_issues --session_dir data/session_20260226_120000
```

Options:
- `--issue_file custom_issue_events.jsonl`

Outputs:
- `issue_summary.csv`
- `issue_timeline.csv`
- `incident_summary.csv`

## 4) `analyze_batch`

```bash
cpp-dlc-live analyze_batch --root_dir data --recursive
```

Options:
- `--cm_per_px 0.05`
- `--fixed_fps 30`
- `--fixed_fps_hz 30`
- `--no_plots`
- `--render_overlay_video`
- `--overlay_video_filename analysis_overlay.mp4`
- `--include_issues`
- `--fail_fast`
- `--report_name batch_analysis_report.csv`

Output:
- a report CSV under `root_dir` (default `batch_analysis_report.csv`) with per-session status and generated paths.

## 5) `run_offline` (fast full replay from raw video)

Use this when you already have a raw video and want the full pipeline outputs (`cpp_realtime_log.csv`, preview/raw recording, summary, Figure1-5) without realtime pacing.

```bash
cpp-dlc-live run_offline \
  --config config/config_example.yaml \
  --video path/to/raw_video.mp4
```

Common options:
- `--out_dir /path/to/output_root`
- `--root_dir /path/to/sessions_or_videos --recursive` (batch replay)
- `--duration_s 600` (optional; omit to process until EOF)
- `--fixed_fps 20`
- `--preview` (show window; default is headless for speed)
- `--mouse_id M001 --group Control --experiment_duration_s 600`
- `--no_auto_analyze`
- `--fail_fast` (batch mode: stop on first failure)
- `--batch_report_name offline_batch_report.csv`

Behavior:
- Forces `laser_control.mode=dryrun` for safety.
- Disables file realtime throttle and runs as fast as hardware allows.
- Still uses your current config logic for DLC/ROI/debounce/laser state calculation and output file structure.

Batch example:

```bash
cpp-dlc-live run_offline \
  --config config/config_example.yaml \
  --root_dir D:/Data/LiuZY/Code/DeeplabcutCPP/output \
  --recursive
```

Batch source rule:
- `--root_dir` scans `session_*` folders (or folders containing session metadata/log files).
- In each session folder, only `*_raw_video.*`/`raw_video.*` files are selected.
- `preview/overlay` videos are ignored for batch source selection.

## 6) `calibrate_roi`

```bash
cpp-dlc-live calibrate_roi --config config/config_example.yaml --camera_source 0
```

Options:
- `--image /path/to/background.png`
- `--save_to /path/to/new_config.yaml`
- `--without_neutral`
- `--exposure_step 1.0`
- `--gain_step 1.0`

Calibrator controls:
- left click: add point
- `u`: undo
- `r`: reset current ROI
- `n`: finish current ROI and move next
- `a`: toggle auto exposure
- `[` / `]`: exposure down/up (forces manual mode)
- `,` / `.`: gain down/up
- `s`: save
- `q`/`Esc`: cancel

When using camera input (not `--image`), `calibrate_roi` can now update both ROI and camera exposure fields in config:
- `camera.auto_exposure`
- `camera.exposure`
- `camera.gain`

## Recommended End-to-End Workflow

## First-time bring-up (dryrun)

1. Install environment.
2. Prepare config copy from template.
3. Calibrate ROI (`calibrate_roi`).
4. Run dryrun for 30–60 seconds with a known video.
5. Confirm output files are complete.
6. Run `analyze_session` and `analyze_issues` to validate post-processing.

## DLC validation

1. Ensure `run.log` contains `Using DLCLive runtime ...`.
2. Confirm `metadata.json` shows `dlc_model.runtime = dlclive` (not `mock`).
3. Verify bodypart names match your model metadata.

## NI hardware validation

1. Keep `fallback_to_dryrun=true` during first hardware tests.
2. Validate channels/routes in NI MAX.
3. Start with short sessions and monitor transitions in logs.

## Session Outputs and File Meanings

Each session directory includes (depending on command and options):

- `<session_id>_cpp_realtime_log.csv`: frame-level runtime records
- `<session_id>_metadata.json`: run metadata + runtime stats + config hash + preview recording result
- `<session_id>_config_used.yaml`: exact runtime config copy
- `<session_id>_run.log`: readable runtime log
- `<session_id>_preview_overlay.mp4` (configurable): preview recording output when enabled
- `<session_id>_raw_video.mp4` (configurable): raw recording output when enabled
- `<session_id>_issue_events.jsonl`: structured issue/event stream
- `<session_id>_incident_report_*.json`: runtime exception report snapshots
- `<session_id>_summary.csv`: offline analysis summary
- `<session_id>_figure1_trajectory_speed_heatmap.png`: trajectory with speed-coded color
- `<session_id>_figure2_position_heatmap.png`: position occupancy heatmap
- `<session_id>_figure3_chamber_dwell.png`: chamber1/chamber2 dwell time + percentage bars
- `<session_id>_speed_over_time.png`: Figure 4
- `<session_id>_occupancy_over_time.png`: Figure 5
- `<session_id>_issue_summary.csv`, `<session_id>_issue_timeline.csv`, `<session_id>_incident_summary.csv` (from `analyze_issues`)

## Core columns in `cpp_realtime_log.csv`

- `t_wall`, `frame_idx`
- `x`, `y`, `p`
- `chamber_raw`, `chamber`
- `laser_state`
- `inference_ms`, `fps_est`

## Core columns in `summary.csv`

- `time_ch1_s`, `time_ch2_s`, `time_neutral_s`
- `distance_px`, `distance_cm`
- `mean_speed_px_s`, `mean_speed_cm_s`
- `laser_on_time_s`
- `session_duration_s`, `n_samples`

## Performance, Safety, and Failure Behavior

## Performance targets

- Target FPS: `>= 15` (prefer `>= 30` if hardware allows)
- Target mean inference latency: `< 50 ms` (hardware dependent)
- Chamber switch latency: approximately `debounce_frames / actual_fps`

## Safety strategy

- Default stimulation state is OFF.
- On runtime exceptions (camera/DLC/DAQ/ROI), system attempts to force OFF before exit.
- Laser controller stop is called in cleanup path.

## Failure traceability

- Text log: `run.log`
- Structured events: `issue_events.jsonl`
- Exception snapshot: `incident_report_*.json`

## Troubleshooting

## `No module named tensorflow` while using PyTorch model

Symptom:
- runtime tries TensorFlow runner and falls back to mock.

Actions:
1. Set `dlc.backend: pytorch` in config.
2. Verify effective config in session `config_used.yaml`.
3. Check dlclive signature:

```bash
python -c "import dlclive,inspect; from dlclive import DLCLive; print(dlclive.__version__); print(inspect.signature(DLCLive.__init__))"
```

## `PermissionError` on model path ending with `.../train`

Cause:
- `model_path` points to a **directory**, but loader expects a model file/path format usable by DLCLive.

Action:
- point to exported model artifact expected by DLCLive, not the train folder itself.

## `KeyError: 'config'` when loading `.pt`

Cause:
- `.pt` is a training snapshot, not a DLCLive-exported model artifact.

Action:
- export model for live inference and update `dlc.model_path` accordingly.

## Model appears inaccurate although training looked good

Checks:
1. Ensure runtime is actually `dlclive` (not `mock`).
2. Ensure `dlc.bodypart` exists in model bodypart names.
3. Temporarily reduce `p_thresh` and disable smoothing for debugging.
4. Recalibrate ROI using the exact runtime camera geometry.
5. Set `dlc.strict_runtime: true` so initialization errors fail fast instead of falling back to mock.

## ROI looks shifted

Cause:
- ROI calibrated under different transform/resolution.

Action:
- keep `camera.width/height/flip/rotate_deg` consistent between calibration and runtime.

## Development and Tests

Run test suite:

```bash
pytest -q
```

Useful checks before commit:

```bash
python -m cpp_dlc_live.cli --help
python -m py_compile cpp_dlc_live/realtime/app.py
```

## Related Documents

- [DEPLOYMENT_REQUIREMENTS.md](DEPLOYMENT_REQUIREMENTS.md)
- [Chinese Documentation Entry](docs/user_guide_zh.md)
- [Operator Guide (中文)](docs/operator_guide_zh.md)
- [Developer Guide (中文)](docs/developer_guide_zh.md)
