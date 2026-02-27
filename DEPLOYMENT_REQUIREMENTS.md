# Deeplabcut_CPP 多设备部署 Requirements 文档

本文档用于在多台设备上快速部署 `cpp_dlc_live` 项目，覆盖 dryrun、NI 硬件控制、DLC-live 推理三种场景。

## 1. 部署目标与环境分层

- `dryrun`：无 NI 硬件，无 DLC 模型，使用摄像头/视频文件跑通全流程。
- `ni`：在 dryrun 基础上启用 NI cDAQ TTL 输出（gated/startstop）。
- `dlc`：在 dryrun 基础上启用 DeepLabCut-live 模型实时推理。
- `full`：同时启用 NI + DLC。

## 2. 推荐系统与 Python 版本

- 推荐 OS：
  - Windows 10/11（NI 场景优先）
  - Ubuntu 20.04/22.04（dryrun/dlc 常见）
  - macOS 13/14（dryrun/dlc/analysis）
- Python：`3.10`（推荐统一）
- pip：`>=23.2`
- 虚拟环境：`venv` 或 `conda` 均可

说明：
- 为减少跨设备兼容问题，建议所有机器统一 Python 小版本（例如全部 3.10.x）。
- 若使用 GPU 推理，请额外对齐 CUDA/cuDNN 与 TensorFlow 兼容矩阵（依 DLC-live 版本而定）。

## 3. 系统级依赖

### 3.1 通用依赖

- Git
- Python 3.10 + pip
- 能打开 OpenCV 窗口的图形环境（无头服务器可关闭预览 `--no_preview`）

### 3.2 Linux 额外建议依赖

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-venv python3-dev build-essential \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev ffmpeg
```

### 3.3 NI 硬件依赖

- NI-DAQmx 驱动（目标机安装，建议与实验室设备统一版本）
- NI MAX 可识别 `cDAQ1` 与目标模块（如 NI 9402）
- Python `nidaqmx` 包可正常导入
- 一般建议：NI 控制机使用 Windows/Linux；macOS 通常仅做 dryrun/分析

### 3.4 DLC-live 依赖

- 已导出的 DLC-live 模型目录（配置到 `dlc.model_path`）
- `deeplabcut-live` Python 包
- 若使用 GPU：匹配的 CUDA/cuDNN/TensorFlow

## 4. Python 包清单

### 4.1 核心基础包（dryrun 最小集）

- `numpy>=1.23`
- `pandas>=1.5`
- `opencv-python>=4.8`
- `PyYAML>=6.0`
- `matplotlib>=3.7`

### 4.2 可选包

- `nidaqmx>=0.8`（NI 控制）
- `deeplabcut-live>=1.0.0`（DLC-live 推理）
- `pytest>=7.0`（测试）

### 4.3 requirements 文件

仓库已提供：
- `requirements/base.txt`
- `requirements/ni.txt`
- `requirements/dlc.txt`
- `requirements/dev.txt`
- `requirements/full.txt`
- `requirements/full-linux.txt`
- `requirements/full-macos.txt`
- `requirements/full-windows.txt`
- `requirements-lock.txt`（推荐锁定版）
- `requirements-lock-linux.txt`
- `requirements-lock-macos.txt`
- `requirements-lock-windows.txt`
- `environment.base.yml`
- `environment.full.yml`
- `environment.linux.base.yml`
- `environment.linux.full.yml`
- `environment.macos.base.yml`
- `environment.macos.full.yml`
- `environment.windows.base.yml`
- `environment.windows.full.yml`
- `Dockerfile`

## 5. 快速部署流程（推荐）

### 5.1 Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

# 仅 dryrun
pip install -r requirements/base.txt

# 全功能（NI + DLC + 测试）
# pip install -r requirements/full-linux.txt

# 当前项目可编辑安装
pip install -e .
```

### 5.2 macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

# 仅 dryrun
pip install -r requirements/base.txt

# 全功能（DLC + 测试，不含 NI）
# pip install -r requirements/full-macos.txt

pip install -e .
```

### 5.3 Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel

pip install -r requirements\base.txt
# pip install -r requirements\full-windows.txt

pip install -e .
```

### 5.4 Conda（按系统）

```bash
# Linux
conda env create -f environment.linux.base.yml
conda activate cpp_dlc_live_linux_base
# conda env create -f environment.linux.full.yml
# conda activate cpp_dlc_live_linux_full

# macOS
# conda env create -f environment.macos.base.yml
# conda activate cpp_dlc_live_macos_base
# conda env create -f environment.macos.full.yml
# conda activate cpp_dlc_live_macos_full

# Windows
# conda env create -f environment.windows.base.yml
# conda activate cpp_dlc_live_windows_base
# conda env create -f environment.windows.full.yml
# conda activate cpp_dlc_live_windows_full
```

## 6. Docker 部署（可选）

说明：
- Docker 适用于 dryrun/离线分析/CI，不建议用于 NI 直连控制。
- 默认安装 `requirements/base.txt`，可通过 build arg 切换 profile。

```bash
# base 镜像
docker build -t cpp-dlc-live:base --build-arg INSTALL_PROFILE=base .

# full 镜像（包含 ni/dlc/dev 依赖）
# docker build -t cpp-dlc-live:full --build-arg INSTALL_PROFILE=full .

docker run --rm -it cpp-dlc-live:base
```

## 7. 跨设备一致性部署（强烈建议）

### 7.1 在线机器打包 wheelhouse

```bash
mkdir -p wheelhouse
# Linux
pip download -r requirements/full-linux.txt -d wheelhouse
# macOS
# pip download -r requirements/full-macos.txt -d wheelhouse
# Windows
# pip download -r requirements/full-windows.txt -d wheelhouse
```

### 7.2 离线机器安装

```bash
# Linux
pip install --no-index --find-links=wheelhouse -r requirements/full-linux.txt
# macOS
# pip install --no-index --find-links=wheelhouse -r requirements/full-macos.txt
# Windows
# pip install --no-index --find-links=wheelhouse -r requirements/full-windows.txt
pip install -e . --no-deps
```

### 7.3 配置与模型同步

跨设备同步以下目录/文件：
- `config/config_example.yaml`（或你的实验配置）
- DLC 导出模型目录（`dlc.model_path` 指向）
- NI 通道命名约定（`ctr_channel/pulse_term/enable_line`）

## 8. 部署后自检清单

在每台设备执行：

```bash
python -c "import cv2, numpy, pandas, yaml, matplotlib; print('base ok')"
python -c "import nidaqmx; print('ni ok')"      # 仅 NI 机器
python -c "import dlclive; print('dlc ok')"     # 仅 DLC 机器
pytest -q                                        # 开发/验收机器建议执行
python -m cpp_dlc_live.cli --help
```

dryrun 冒烟测试：

```bash
python -m cpp_dlc_live.cli run_realtime \
  --config config/config_example.yaml \
  --camera_source 0 \
  --duration_s 10 \
  --no_preview
```

## 9. 推荐设备角色模板

- 采集机（无 NI 无 DLC）：安装 `base`
- 控制机（NI + 可选 DLC）：安装 `ni` 或 `full`
- 分析机（离线分析）：安装 `base`
- 开发机（代码修改 + 测试）：安装 `full`（已含 `pytest`）

## 10. 常见部署问题

- `nidaqmx import 失败`：确认 NI-DAQmx 驱动已安装，且 Python 环境位数与驱动兼容。
- OpenCV 无法显示窗口：远程/无显示环境使用 `--no_preview`。
- DLC-live 初始化失败：检查 `dlc.model_path` 是否为导出后的 live 模型目录。
- 多设备行为不一致：统一 Python 版本、requirements 文件、配置文件与模型快照。

## 11. 锁定版本更新流程

当你需要升级依赖时，建议按以下流程：

```bash
# 1) 升级 requirements/*.txt 后，更新锁定文件
# 2) 在目标 Python 版本（推荐 3.10）环境中验证
# Linux
pip install -r requirements-lock-linux.txt
# macOS
# pip install -r requirements-lock-macos.txt
# Windows
# pip install -r requirements-lock-windows.txt
pytest -q
python -m cpp_dlc_live.cli --help
```

如果你的设备有平台差异（Windows/Linux、GPU/CPU），建议分别维护锁定文件，例如：
- `requirements-lock-linux.txt`
- `requirements-lock-macos.txt`
- `requirements-lock-windows.txt`
