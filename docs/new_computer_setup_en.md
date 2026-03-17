# New Computer Setup Guide (Conda, Step by Step)

This guide is for first-time users who want to deploy `cpp_dlc_live` on a brand-new machine.

It covers:
- clean setup from Conda
- dryrun with video/camera
- DLC-live GPU inference setup
- NI hardware setup (`gated` / `startstop`)

If you prefer Chinese, see:
- [新电脑部署指南（中文）](new_computer_setup_zh.md)

## 1. Decide Your Deployment Target

Choose one profile before installation:

1. `dryrun`: no NI hardware needed; use video file or webcam.
2. `dlc`: real DLC-live inference, no NI output.
3. `full`: DLC-live + NI output control.

For first deployment, always start with `dryrun`.

## 2. Install System Prerequisites

Install these on the new machine:

1. `Git`
2. `Miniconda` or `Anaconda`
3. NVIDIA driver (if using GPU inference)
4. NI-DAQmx + NI MAX (only for NI hardware mode)

Recommended:
- OS: Windows 10/11 for NI workflows
- Python: 3.10

## 3. Clone the Repository

Open terminal (Windows CMD/PowerShell) and run:

```bash
git clone git@github.com:Vincent-B-Faust/Deeplabcut-CPP.git
cd Deeplabcut-CPP
git checkout main
git pull origin main
```

## 4. Create Conda Environment

Use the provided environment YAML files.

### 4.1 Windows

```bash
# Base (dryrun + analysis)
conda env create -f environment.windows.base.yml
conda activate cpp_dlc_live_windows_base

# OR full profile (DLC + NI + tests)
# conda env create -f environment.windows.full.yml
# conda activate cpp_dlc_live_windows_full
```

### 4.2 Linux

```bash
conda env create -f environment.linux.base.yml
conda activate cpp_dlc_live_linux_base

# Optional full
# conda env create -f environment.linux.full.yml
# conda activate cpp_dlc_live_linux_full
```

### 4.3 macOS

```bash
conda env create -f environment.macos.base.yml
conda activate cpp_dlc_live_macos_base

# Optional full
# conda env create -f environment.macos.full.yml
# conda activate cpp_dlc_live_macos_full
```

## 5. GPU Setup for DLC-live (Important)

If you need GPU inference, install CUDA-enabled PyTorch in the active environment:

```bash
conda install pytorch torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia -y
```

Verify:

```bash
python -c "import torch; print('torch=',torch.__version__); print('cuda_available=',torch.cuda.is_available()); print('count=',torch.cuda.device_count()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

Expected:
- `cuda_available=True`
- `count>=1`

If this shows CPU only, do not continue to DLC runtime yet; fix GPU first.

## 6. NI Driver Setup (Only NI Mode)

On NI hardware machine:

1. Install NI-DAQmx.
2. Open NI MAX and confirm your cDAQ and module are visible.
3. Confirm Python package:

```bash
python -c "import nidaqmx; print('nidaqmx ok')"
```

## 7. Project Sanity Check

Run:

```bash
python -m cpp_dlc_live.cli --help
python -c "import cv2, numpy, pandas, yaml; print('base ok')"
python -c "import dlclive; print('dlclive ok')"   # if DLC is needed
```

## 8. Prepare Config File

Copy template:

```bash
# Windows
copy config\config_example.yaml config\config_test.yaml

# Linux/macOS
# cp config/config_example.yaml config/config_test.yaml
```

Edit at least these fields in `config/config_test.yaml`:

1. `project.out_dir`
2. `camera.source`
3. `dlc.model_path` (for DLC mode)
4. `dlc.backend: pytorch`
5. `dlc.device: cuda:0` (single GPU)
6. `laser_control.mode` (`dryrun` first)

Important:
- Use exported DLC-live model path, not raw training snapshots.
- Path separators must match your OS style.

## 9. First Run: Dryrun Smoke Test

Use dryrun first even if NI and DLC are available:

```bash
python -m cpp_dlc_live.cli run_realtime --config config/config_test.yaml --duration_s 30
```

For headless mode:

```bash
python -m cpp_dlc_live.cli run_realtime --config config/config_test.yaml --duration_s 30 --no_preview
```

Expected output session files:

1. `cpp_realtime_log.csv`
2. `metadata.json`
3. `run.log`
4. `config_used.yaml`

If enabled, also:
- `preview_overlay.mp4`
- `issue_events.jsonl`

## 10. Calibrate ROI

Before real experiments:

```bash
python -m cpp_dlc_live.cli calibrate_roi --config config/config_test.yaml --camera_source 0
```

Controls:

1. Left click: add point
2. `u`: undo
3. `r`: reset current ROI
4. `n`: next ROI
5. `s`: save
6. `q` or `Esc`: quit

## 11. Switch to Real DLC and NI

After dryrun passes:

1. Set real `dlc.model_path`
2. Set `laser_control.mode`:
   - `gated` (recommended)
   - `startstop` (fallback)
3. Set NI channels:
   - `ctr_channel`
   - `pulse_term`
   - `enable_line` (gated)
4. Keep safety policy to OFF on unknown/exception.

Run short validation:

```bash
python -m cpp_dlc_live.cli run_realtime --config config/config_test.yaml --duration_s 60
```

## 12. Offline Analysis and Issue Traceback

Analyze one session:

```bash
python -m cpp_dlc_live.cli analyze_session --session_dir <session_dir>
```

Analyze runtime issues:

```bash
python -m cpp_dlc_live.cli analyze_issues --session_dir <session_dir>
```

Expected outputs:

1. `summary.csv`
2. optional plots
3. `issue_summary.csv`
4. `issue_timeline.csv`
5. `incident_summary.csv`

## 13. Multi-GPU Notes

If machine has one GPU, use:
- `dlc.device: cuda:0` or `cuda`

If machine has multiple GPUs:
- use `cuda:0`, `cuda:1`, etc.
- avoid full-width colon (`：`); use ASCII `:`.

If `CUDA_VISIBLE_DEVICES` is set, GPU indexing inside the process changes.

## 14. Update on Another Machine

To sync latest changes:

```bash
git checkout main
git pull origin main
```

If dependencies changed:

```bash
conda env update -f environment.windows.full.yml --prune
```

Adjust YAML by OS (`linux/macos/windows`).

## 15. Common Problems

1. `dlclive fallback to mock`: model path invalid or backend package missing.
2. `torch.cuda.is_available() == False`: driver/CUDA/env issue.
3. NI `-200022 resource reserved`: line/channel occupied by another task/process.
4. Video appears accelerated: set `camera.fps_target` and verify runtime logs.
5. Wrong ROI/chamber transitions: recalibrate ROI and tune `debounce_frames`.

For full dependency matrix and lock-file deployment:
- [DEPLOYMENT_REQUIREMENTS.md](../DEPLOYMENT_REQUIREMENTS.md)
