# 新电脑部署指南（Conda 逐步版）

本文档面向首次部署 `cpp_dlc_live` 的新手用户，按“从零开始”顺序给出完整步骤。

覆盖内容：

1. 从 Conda 创建环境
2. dryrun（视频/摄像头）跑通
3. DLC-live GPU 推理配置
4. NI 硬件模式配置（`gated` / `startstop`）

英文版见：
- [New Computer Setup Guide (EN)](new_computer_setup_en.md)

## 1. 先确定部署目标

请先选一种目标：

1. `dryrun`：无 NI 硬件，仅视频/摄像头联调。
2. `dlc`：启用 DLC-live 推理，不控制 NI。
3. `full`：DLC-live + NI 激光控制。

建议首次部署先做 `dryrun`。

## 2. 安装系统前置软件

新电脑先安装：

1. `Git`
2. `Miniconda` 或 `Anaconda`
3. NVIDIA 驱动（仅 GPU 推理需要）
4. NI-DAQmx + NI MAX（仅 NI 模式需要）

推荐：

1. OS：Windows 10/11（NI 场景优先）
2. Python：3.10

## 3. 克隆仓库

打开终端后执行：

```bash
git clone git@github.com:Vincent-B-Faust/Deeplabcut-CPP.git
cd Deeplabcut-CPP
git checkout main
git pull origin main
```

## 4. 创建 Conda 环境

按系统使用仓库自带的环境文件。

## 4.1 Windows

```bash
# 基础环境（dryrun + 离线分析）
conda env create -f environment.windows.base.yml
conda activate cpp_dlc_live_windows_base

# 或完整环境（DLC + NI + 测试）
# conda env create -f environment.windows.full.yml
# conda activate cpp_dlc_live_windows_full
```

## 4.2 Linux

```bash
conda env create -f environment.linux.base.yml
conda activate cpp_dlc_live_linux_base

# 可选完整环境
# conda env create -f environment.linux.full.yml
# conda activate cpp_dlc_live_linux_full
```

## 4.3 macOS

```bash
conda env create -f environment.macos.base.yml
conda activate cpp_dlc_live_macos_base

# 可选完整环境
# conda env create -f environment.macos.full.yml
# conda activate cpp_dlc_live_macos_full
```

## 5. GPU 推理（DLC 模式关键）

若要启用 GPU，请在当前环境安装 CUDA 版 PyTorch：

```bash
conda install pytorch torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia -y
```

验证：

```bash
python -c "import torch; print('torch=',torch.__version__); print('cuda_available=',torch.cuda.is_available()); print('count=',torch.cuda.device_count()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

应满足：

1. `cuda_available=True`
2. `count>=1`

若仍是 CPU，请先修复 GPU 驱动/环境，再继续 DLC 运行。

## 6. NI 驱动配置（仅硬件模式）

NI 机器上需要：

1. 安装 NI-DAQmx
2. 在 NI MAX 中看到 cDAQ 与模块
3. Python 可导入 `nidaqmx`

```bash
python -c "import nidaqmx; print('nidaqmx ok')"
```

## 7. 环境快速自检

```bash
python -m cpp_dlc_live.cli --help
python -c "import cv2, numpy, pandas, yaml; print('base ok')"
python -c "import dlclive; print('dlclive ok')"   # 需要 DLC 时执行
```

## 8. 准备配置文件

复制模板：

```bash
# Windows
copy config\config_example.yaml config\config_test.yaml

# Linux/macOS
# cp config/config_example.yaml config/config_test.yaml
```

至少修改以下字段：

1. `project.out_dir`
2. `camera.source`
3. `dlc.model_path`（DLC 模式）
4. `dlc.backend: pytorch`
5. `dlc.device: cuda:0`（单 GPU）
6. `laser_control.mode`（先用 `dryrun`）

注意：

1. `model_path` 应指向 DLC-live 可用导出模型，不是训练快照原始目录。
2. 路径请使用当前系统可访问的绝对路径。

## 9. 第一次运行：dryrun 冒烟测试

```bash
python -m cpp_dlc_live.cli run_realtime --config config/config_test.yaml --duration_s 30
```

无界面环境可用：

```bash
python -m cpp_dlc_live.cli run_realtime --config config/config_test.yaml --duration_s 30 --no_preview
```

期望生成：

1. `cpp_realtime_log.csv`
2. `metadata.json`
3. `run.log`
4. `config_used.yaml`

若开启相关功能，还会有：

1. `preview_overlay.mp4`
2. `issue_events.jsonl`

## 10. ROI 标定

正式实验前建议先标定：

```bash
python -m cpp_dlc_live.cli calibrate_roi --config config/config_test.yaml --camera_source 0
```

按键：

1. 鼠标左键：加点
2. `u`：撤销
3. `r`：重置当前 ROI
4. `n`：下一块 ROI
5. `s`：保存
6. `q` 或 `Esc`：退出

## 11. 切换到真实 DLC + NI

dryrun 确认后再切换：

1. 设置真实 `dlc.model_path`
2. 设置 `laser_control.mode`
   - 推荐 `gated`
   - 兼容用 `startstop`
3. 配好 NI 通道
   - `ctr_channel`
   - `pulse_term`
   - `enable_line`（gated 模式）
4. 保持异常安全策略为 OFF

先做短时验证：

```bash
python -m cpp_dlc_live.cli run_realtime --config config/config_test.yaml --duration_s 60
```

## 12. 离线分析与问题回溯

分析 session：

```bash
python -m cpp_dlc_live.cli analyze_session --session_dir <session_dir>
```

分析运行问题：

```bash
python -m cpp_dlc_live.cli analyze_issues --session_dir <session_dir>
```

期望输出：

1. `summary.csv`
2. 可选图表
3. `issue_summary.csv`
4. `issue_timeline.csv`
5. `incident_summary.csv`

## 13. 多 GPU 说明

1. 单 GPU：`dlc.device: cuda:0` 或 `cuda`
2. 多 GPU：可写 `cuda:0`、`cuda:1` 等
3. 必须使用半角冒号 `:`，不要用全角 `：`
4. 若设置了 `CUDA_VISIBLE_DEVICES`，进程内 GPU 编号会重映射

## 14. 另一台电脑拉取更新

```bash
git checkout main
git pull origin main
```

若依赖更新，执行：

```bash
conda env update -f environment.windows.full.yml --prune
```

Linux/macOS 请改用对应 YAML。

## 15. 常见问题速查

1. `dlclive` 回退到 mock：模型路径无效或后端依赖不完整
2. `torch.cuda.is_available() == False`：驱动/CUDA/环境变量问题
3. NI `-200022`：通道被其他任务占用
4. 视频看起来加速：检查 `camera.fps_target` 与运行日志里的实际相机参数
5. chamber 判断不稳：重标 ROI，并调整 `debounce_frames`

完整依赖矩阵与锁定部署方案见：
- [DEPLOYMENT_REQUIREMENTS.md](../DEPLOYMENT_REQUIREMENTS.md)
