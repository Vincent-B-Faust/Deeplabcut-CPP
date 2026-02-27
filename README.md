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
- `camera`: source and transform options
- `dlc`: model path/backend/bodypart/confidence/smoothing
- `roi`: chamber polygons/rectangles + neutral policy + debounce
- `laser_control`: hardware strategy and channels
- `analysis`: offline metric options
- `preview_recording`: optional save of preview video
- `runtime_logging`: issue/heartbeat/warning settings

## Field reference (practical)

### `project`
- `project.session_id`: fixed id or `auto_timestamp`
- `project.out_dir`: output root; session subdirectory is created automatically

### `camera`
- `camera.source`: camera index (`0`) or video path/URL
- `camera.width`, `camera.height`, `camera.fps_target`
- `camera.flip`, `camera.rotate_deg`

### `dlc`
- `dlc.model_path`: DLCLive model path (typically exported artifact)
- `dlc.backend`: `auto` | `pytorch` | `tensorflow`
- `dlc.bodypart`: tracked bodypart name (must exist in model, unless fallback logic is intentional)
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
- `analysis.cm_per_px`
- `analysis.output_plots`

### `preview_recording`
- `preview_recording.enabled`: save preview video or not
- `preview_recording.filename`: relative path is resolved under session dir
- `preview_recording.codec`: 4-char codec (e.g. `mp4v`)
- `preview_recording.fps`: optional override
- `preview_recording.overlay`: save annotated frame (`true`) or raw frame (`false`)

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

camera:
  source: C:/data/videos/test.avi
  width: 1280
  height: 720
  fps_target: 30
  flip: false
  rotate_deg: 0

dlc:
  model_path: C:/data/models/exported-models-pytorch/your_model.pt
  backend: pytorch
  bodypart: Mouse
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
  cm_per_px: null
  output_plots: true

preview_recording:
  enabled: true
  filename: preview_overlay.mp4
  codec: mp4v
  fps: 30
  overlay: true

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
- `--no_preview` (disable window display)

Notes:
- `preview_recording.enabled=true` can still record video even when `--no_preview` is used.
- On input video EOF, run exits normally.

## 2) `analyze_session`

```bash
cpp-dlc-live analyze_session --session_dir data/session_20260226_120000
```

Options:
- `--cm_per_px 0.05`
- `--no_plots`

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

## 4) `calibrate_roi`

```bash
cpp-dlc-live calibrate_roi --config config/config_example.yaml --camera_source 0
```

Options:
- `--image /path/to/background.png`
- `--save_to /path/to/new_config.yaml`
- `--without_neutral`

Calibrator controls:
- left click: add point
- `u`: undo
- `r`: reset current ROI
- `n`: finish current ROI and move next
- `s`: save
- `q`/`Esc`: cancel

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

- `cpp_realtime_log.csv`: frame-level runtime records
- `metadata.json`: run metadata + runtime stats + config hash + preview recording result
- `config_used.yaml`: exact runtime config copy
- `run.log`: readable runtime log
- `preview_overlay.mp4` (configurable): preview recording output when enabled
- `issue_events.jsonl`: structured issue/event stream
- `incident_report_*.json`: runtime exception report snapshots
- `summary.csv`: offline analysis summary
- `trajectory.png`, `speed_over_time.png`, `occupancy_over_time.png` (if plot output enabled)
- `issue_summary.csv`, `issue_timeline.csv`, `incident_summary.csv` (from `analyze_issues`)

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
