# cpp_dlc_live

End-to-end Python project for DeepLabCut-live closed-loop 2-chamber CPP experiments with NI cDAQ laser control and offline analysis.

For multi-device deployment (pip/conda/docker/locked requirements), see `DEPLOYMENT_REQUIREMENTS.md`.

## Features

- Real-time video acquisition, DLC-live inference, ROI chamber classification, debounce, and OpenCV overlay preview.
- NI laser control modes:
  - `gated`: continuous 20 Hz counter output + digital enable gating.
  - `startstop`: start/stop counter output on chamber transitions with min on/off dwell.
  - `dryrun`: no hardware output, logic-only simulation.
- Safety-first behavior: any runtime exception forces laser OFF and performs graceful cleanup.
- Session logging:
  - `cpp_realtime_log.csv` frame-level records.
  - `run.log` console/file logging.
  - `metadata.json` full session metadata.
  - `config_used.yaml` copied runtime config.
- Offline analysis from session logs:
  - chamber occupancy time
  - distance and mean speed (px/s and optional cm/s)
  - laser-on duration
  - optional plots

## Repository Structure

```text
cpp_dlc_live/
  README.md
  pyproject.toml
  config/
    config_example.yaml
  cpp_dlc_live/
    __init__.py
    cli.py
    realtime/
      camera.py
      dlc_runtime.py
      roi.py
      debounce.py
      logging_utils.py
      recorder.py
      controller_ni.py
      controller_base.py
      app.py
    analysis/
      analyze.py
      plots.py
      metrics.py
    utils/
      time_utils.py
      io_utils.py
  tests/
    test_roi.py
    test_debounce.py
    test_analysis_metrics.py
```

## Installation

1. Create and activate a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
```

2. Install package with development dependencies.

```bash
pip install -e .[dev]
```

3. Optional dependencies:

```bash
pip install -e .[ni,dlc]
```

4. NI-DAQmx requirement:
- Install NI-DAQmx driver on the target machine.
- Verify that `import nidaqmx` works in the same Python environment.

## Config File

Use `config/config_example.yaml` as template. All runtime parameters are loaded from YAML.

Main sections:
- `project`: project name, session id policy, output root.
- `camera`: source, resolution, target fps, transform.
- `dlc`: model path, bodypart, confidence threshold, optional smoothing.
- `roi`: chamber1/chamber2/neutral polygons or rectangles, neutral strategy, debounce.
- `laser_control`: `enabled`, mode (`gated`/`startstop`/`dryrun`), channels and timing.
- `analysis`: `cm_per_px`, plot output toggle.

Field reference:

- `project.name`: project identifier written into metadata.
- `project.session_id`: fixed session ID or `auto_timestamp` (auto generated at runtime).
- `project.out_dir`: root directory for all session outputs.
- `camera.source`: OpenCV source (`0`, `1`, file path, or stream URL).
- `camera.width` / `camera.height`: requested capture resolution.
- `camera.fps_target`: requested camera FPS.
- `camera.flip`: horizontal flip for preview/inference.
- `camera.rotate_deg`: rotation angle (0/90/180/270 recommended).
- `dlc.model_path`: exported DLC-live model directory.
- `dlc.bodypart`: tracked point (`center` by default, fallback supported).
- `dlc.p_thresh`: confidence threshold.
- `dlc.smoothing.enabled`: enable moving-average smoothing on tracked coordinates.
- `dlc.smoothing.window`: smoothing window size in frames.
- `roi.type`: `polygon` or `rect`.
- `roi.chamber1` / `roi.chamber2` / `roi.neutral`: ROI points in image coordinates.
- `roi.strategy_on_neutral`: `off` | `hold_last` | `unknown`.
- `roi.debounce_frames`: N consecutive frames needed for stable chamber switch.
- `laser_control.enabled`: master laser control switch.
- `laser_control.mode`: `gated` | `startstop` | `dryrun`.
- `laser_control.freq_hz`: pulse frequency (default 20 Hz).
- `laser_control.duty_cycle`: pulse duty cycle (default 0.05).
- `laser_control.ctr_channel`: NI counter output channel (example `cDAQ1Mod4/ctr0`).
- `laser_control.pulse_term`: NI pulse route terminal (example `/cDAQ1Mod4/PFI0`).
- `laser_control.enable_line`: NI digital line for gating mode.
- `laser_control.min_on_s` / `laser_control.min_off_s`: minimum on/off dwell for startstop mode.
- `laser_control.unknown_policy`: unknown-state behavior (`off` | `hold_last`).
- `laser_control.fallback_to_dryrun`: auto-fallback to dryrun when NI init fails.
- `analysis.cm_per_px`: calibration scale for cm metrics (optional).
- `analysis.output_plots`: enable trajectory/speed/occupancy plots.

## DeepLabCut-live Model

This project expects an exported DLC-live model path under `dlc.model_path`.
Export references:

- DeepLabCut docs: `https://deeplabcut.github.io/DeepLabCut/`
- DeepLabCut-live repo/docs: `https://github.com/DeepLabCut/DeepLabCut-live`

Typical workflow:

1. Train/evaluate your DLC model in DeepLabCut.
2. Export the model for live inference (DLCLive format) per official docs.
3. Set `dlc.model_path` in YAML to the exported directory.

## CLI Usage

### 1) Run realtime closed-loop

```bash
cpp-dlc-live run_realtime --config config/config_example.yaml
```

Common options:
- `--out_dir /path/to/output_root`
- `--duration_s 600`
- `--camera_source 0` (or video file/stream URL)
- `--no_preview`

### 2) Analyze a session

```bash
cpp-dlc-live analyze_session --session_dir data/session_20260226_120000
```

Options:
- `--cm_per_px 0.05` (override config)
- `--no_plots`

### 3) Calibrate ROI interactively

```bash
cpp-dlc-live calibrate_roi --config config/config_example.yaml --camera_source 0
```

Options:
- `--image /path/to/background.png` (calibrate on static image)
- `--save_to /path/to/new_config.yaml`
- `--without_neutral`

## Runtime Outputs

Each session directory contains:
- `cpp_realtime_log.csv`
- `metadata.json`
- `config_used.yaml`
- `run.log`
- `summary.csv` and plot files after offline analysis

Notes:

- `metadata.json` includes start/end time, model info, ROI, DAQ config, camera info, and config hash.
- `summary.csv` uses frame-to-frame `dt`; last frame `dt` is estimated by median previous positive `dt`, so occupancy sum is approximately total session duration.

## Performance Targets

- Target FPS: `>= 15` (prefer `>= 30` when hardware allows).
- Target mean inference latency: `< 50 ms`.
- Chamber switch latency: approximately `debounce_frames / actual_fps`.
- Recorded online metrics: `inference_ms`, `fps_est` in `cpp_realtime_log.csv`.

## FAQ

### DAQ routing/channel error
- Verify `ctr_channel`, `pulse_term`, `enable_line` in config.
- Check NI MAX for channel names and route capability.
- Ensure no other process occupies the same task/channel.

### Camera FPS lower than expected
- Reduce frame size.
- Disable preview for benchmarking.
- Verify camera backend and USB bandwidth.

### ROI calibration issues
- Use high-contrast background frame.
- In calibrator: left click add points, `u` undo, `r` reset ROI, `n` next ROI, `s` save.

### Safety behavior
- Default laser state is OFF.
- Any camera/DLC/DAQ/ROI exception attempts to force OFF before exit.
