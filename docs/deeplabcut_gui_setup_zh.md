# DeepLabCut GUI 配置教程（Windows / Conda / RTX 5070 Ti / PyTorch）

> 适用场景：
> - Windows
> - Conda / Miniconda
> - NVIDIA RTX 5070 Ti
> - DeepLabCut 3 GUI（PyTorch 路线）
> - 关键点：`head / tail / center`

---

## 1. 目标

本文记录一套已实际排障验证的 DeepLabCut GUI 配置流程，包括：

- 创建独立 Conda 环境
- 安装 GPU 版 PyTorch
- 安装 DeepLabCut 3 GUI
- 处理 RTX 5070 Ti（`sm_120`）兼容问题
- 处理 Hugging Face 预训练权重下载问题
- 训练、评估、分析视频
- 常见报错排查

---

## 2. 为什么必须用独立环境

不要把 DeepLabCut GUI 装进已有项目环境里。

建议单独创建环境，例如 `dlc3_gui`，避免以下依赖冲突：

- PyTorch / CUDA
- napari / PySide6
- matplotlib
- huggingface_hub
- timm

---

## 3. 删除旧环境（如果装错）

先查看 Conda 环境：

```bash
conda env list
```

删除旧环境示例：

```bash
conda deactivate
conda env remove -n dlc_gui
```

如果之前创建了错误的 `dlc3_gui`，也可删掉重建：

```bash
conda deactivate
conda env remove -n dlc3_gui
```

---

## 4. 创建新的 DeepLabCut GUI 环境

```bash
conda create -n dlc3_gui python=3.10 -y
conda activate dlc3_gui
python -m pip install --upgrade pip
conda install -c conda-forge pytables==3.8.0 -y
```

---

## 5. 安装 GPU 版 PyTorch

### 5.1 先确认显卡驱动正常

```bash
nvidia-smi
```

如果能看到如下信息，说明驱动正常：

- `NVIDIA GeForce RTX 5070 Ti`
- `Driver Version: ...`
- `CUDA Version: ...`

### 5.2 不要装 CPU 版 PyTorch

检查命令：

```bash
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available())"
```

若输出类似：

```text
2.10.0+cpu
None
False
```

说明是 CPU 版，需要重装。

### 5.3 RTX 5070 Ti 关键点

RTX 5070 Ti 架构较新，`cu126` 版本可能出现：

```text
... CUDA capability sm_120 is not compatible ...
```

此时改用 `cu128`。

### 5.4 安装 CUDA 12.8 版 PyTorch

先卸载旧版本：

```bash
pip uninstall -y torch torchvision torchaudio
```

安装支持新架构的版本：

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

验证：

```bash
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')"
```

理想结果：

- `torch.version.cuda` 不是 `None`
- `torch.cuda.is_available()` 为 `True`
- 设备名显示 `NVIDIA GeForce RTX 5070 Ti`

---

## 6. 安装 DeepLabCut 3 GUI

安装：

```bash
pip install --pre "deeplabcut[gui]"
```

验证版本：

```bash
python -c "import deeplabcut as dlc; print(dlc.__version__)"
```

启动 GUI：

```bash
python -m deeplabcut
```

---

## 7. GUI 首次启动后项目流程

在 GUI 中按顺序操作：

1. Create New Project
2. 选择项目名、实验者、视频路径
3. 创建项目
4. 修改 `config.yaml`
5. Extract Frames
6. Label Frames
7. Create Training Dataset
8. Train
9. Evaluate
10. Analyze Videos
11. Create Labeled Video

---

## 8. 配置 bodyparts

在 `config.yaml` 中设置关键点：

```yaml
bodyparts:
  - head
  - tail
  - center
```

单个个体场景也可配置：

```yaml
individuals:
  - animal
```

---

## 9. 查看当前模型可选 bodyparts

### 9.1 看项目配置

```bash
findstr /n "bodyparts" "D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml"
```

### 9.2 看训练模型配置

```bash
python -c "import yaml; p=r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\dlc-models-pytorch\iteration-0\RTCPPMar17-trainset95shuffle1\train\pytorch_config.yaml'; print(yaml.safe_load(open(p,'r',encoding='utf-8'))['metadata']['bodyparts'])"
```

输出示例：

```text
['head', 'tail', 'center']
```

---

## 10. Hugging Face 权重下载问题

训练时可能出现：

```text
Loading pretrained weights from Hugging Face hub
... WinError 10060 ...
```

表示训练需要下载预训练 backbone，但当前网络无法访问 Hugging Face。

### 10.1 先调大超时

```bash
set HF_HUB_ETAG_TIMEOUT=60
set HF_HUB_DOWNLOAD_TIMEOUT=300
```

测试下载：

```bash
python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id='timm/resnet50_gn.a1h_in1k', filename='model.safetensors'))"
```

### 10.2 如果网络不通

可选方案：

- 换网络
- 手动下载模型文件
- 在可联网机器先下载缓存再复制
- 使用可访问 Hugging Face 的网络环境重跑

### 10.3 Hugging Face 缓存位置

默认常见位置：

```text
C:\Users\你的用户名\.cache\huggingface\hub
```

也可查询：

```bash
python -c "from huggingface_hub import constants; print(constants.HF_HUB_CACHE)"
```

---

## 11. 抽帧失败：`Video files must be corrupted`

若报错：

```text
Frame extraction failed. Video files must be corrupted.
failed to extract frames: worker is None
```

通常是视频编码/容器兼容问题。先转码：

```bash
ffmpeg -i "原视频.mp4" -c:v h264 -crf 18 -preset fast "重编码后.mp4"
```

然后：

- 用重编码视频重新建项目；或
- 改 `config.yaml` 的视频路径后重抽帧

---

## 12. 训练成功但 GUI 评估报图像错误

可能看到：

```text
OSError: No supported images were found ...
QThread::wait: Thread tried to wait on itself
Starting a Matplotlib GUI outside of the main thread will likely fail.
```

通常表示：模型训练成功，评估数值可算，GUI 线程绘图失败。

建议命令行评估（不画图）：

```bash
python -c "import deeplabcut; deeplabcut.evaluate_network(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', Shuffles=[1], plotting=False)"
```

---

## 13. Analyze Videos 后没有 `.h5`

若日志显示：

```text
Video ... already analyzed at ..._full.pickle
No .h5 files were created during video analysis.
```

表示旧的不完整结果残留，GUI 误判“已分析”。

先删旧结果：

```bash
del "D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos\session_20260317_143904_O5C0792_pretest_1200s_raw_videoDLC_Resnet50_RTCPPMar17shuffle1_snapshot_best-60*"
```

再命令行重分析：

```bash
python -c "import deeplabcut; deeplabcut.analyze_videos(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', [r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos\session_20260317_143904_O5C0792_pretest_1200s_raw_video.mp4'])"
```

---

## 14. Analyze Videos 结果位置

通常在原视频目录，例如：

```text
D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos
```

常见输出：

- `...DLC_...h5`
- `...DLC_...csv`
- `...DLC_...pickle`
- `...labeled.mp4`

查看目录：

```bash
dir "D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos"
```

---

## 15. 生成带标注视频

```bash
python -c "import deeplabcut; deeplabcut.create_labeled_video(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', [r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos\session_20260317_143904_O5C0792_pretest_1200s_raw_video.mp4'])"
```

---

## 16. 如何导出模型

用于实时推理时，常见关键文件：

- `...\dlc-models-pytorch\...\train\snapshot-best-060.pt`
- `...\dlc-models-pytorch\...\train\pytorch_config.yaml`

也可尝试官方导出接口：

```bash
python -c "import deeplabcut; deeplabcut.export_model(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', shuffle=1, trainingsetindex=0, overwrite=True, make_tar=True)"
```

> 说明：不同 DLC 版本/引擎下导出产物结构可能有差异，实时程序请以你实际 `run.log` 中 `dlc_model.runtime=dlclive` 且关键点识别正确为准。

---

## 17. 只想导出 `center`，不要 `head/tail`

### 17.1 当前 3 点模型不能直接“裁成单点模型”

如果训练定义是：

```yaml
bodyparts:
  - head
  - tail
  - center
```

则该模型输出头就是 3 点，导出时不会自动变成单点模型。

### 17.2 两种可行方案

方案 A：继续用 3 点模型，在下游程序只读取 `center`（最快）。

方案 B：新建只含 `center` 的项目并重训：

```yaml
bodyparts:
  - center
```

然后重新抽帧、标注、建训练集、训练、导出。

---

## 18. 常见问题总结

### 问题 1：`tensorflow` 缺失

若提示：

```text
ModuleNotFoundError: No module named 'tensorflow'
```

通常是环境或安装路线混乱。建议在独立环境中重装：

```bash
pip install --pre "deeplabcut[gui]"
```

### 问题 2：RTX 5070 Ti 不兼容

若报 `sm_120 is not compatible`，换 `cu128` PyTorch。

### 问题 3：GUI 评估报 PNG/plotting 错误

优先改命令行评估：

```bash
python -c "import deeplabcut; deeplabcut.evaluate_network(r'你的config.yaml路径', Shuffles=[1], plotting=False)"
```

### 问题 4：视频分析只留下 `_full.pickle`

删旧结果，重跑分析，确认 `.h5` 生成。

### 问题 5：网页跳转 MSN 或 Google HSTS 报错

通常是网络环境问题（门户认证/HTTPS 拦截/校园网限制），不是 DLC 本身问题。

---

## 19. 推荐最终工作流

1. 创建独立环境
2. 安装 `cu128` 版 PyTorch
3. 安装 `deeplabcut[gui]`
4. 启动 GUI
5. 建项目
6. 配置 bodyparts
7. 抽帧
8. 标注
9. 创建训练集
10. 训练
11. 命令行评估（`plotting=False`）
12. 分析视频
13. 生成 labeled video
14. 导出模型或使用可验证可用的 `snapshot-best-*.pt`

---

## 20. 当前项目关键路径示例

项目根目录：

```text
D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17
```

训练模型目录：

```text
D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\dlc-models-pytorch\iteration-0\RTCPPMar17-trainset95shuffle1\train
```

最佳模型权重：

```text
D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\dlc-models-pytorch\iteration-0\RTCPPMar17-trainset95shuffle1\train\snapshot-best-060.pt
```

模型配置：

```text
D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\dlc-models-pytorch\iteration-0\RTCPPMar17-trainset95shuffle1\train\pytorch_config.yaml
```

视频目录：

```text
D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos
```

---

## 21. 常用命令速查

激活环境：

```bash
conda activate dlc3_gui
```

检查 GPU：

```bash
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')"
```

启动 GUI：

```bash
python -m deeplabcut
```

命令行评估：

```bash
python -c "import deeplabcut; deeplabcut.evaluate_network(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', Shuffles=[1], plotting=False)"
```

分析视频：

```bash
python -c "import deeplabcut; deeplabcut.analyze_videos(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', [r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos\session_20260317_143904_O5C0792_pretest_1200s_raw_video.mp4'])"
```

生成带点视频：

```bash
python -c "import deeplabcut; deeplabcut.create_labeled_video(r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\config.yaml', [r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\videos\session_20260317_143904_O5C0792_pretest_1200s_raw_video.mp4'])"
```

查看 bodyparts：

```bash
python -c "import yaml; p=r'D:\Data\LiuZY\DeeplabcutGUI_data\RTCPP-pretest-2026-03-17\dlc-models-pytorch\iteration-0\RTCPPMar17-trainset95shuffle1\train\pytorch_config.yaml'; print(yaml.safe_load(open(p,'r',encoding='utf-8'))['metadata']['bodyparts'])"
```

---

## 22. 结论

本流程的关键经验：

- 一定使用独立环境
- RTX 5070 Ti 优先 `cu128` PyTorch
- DeepLabCut 3 GUI 推荐 PyTorch 路线
- GUI 某些评估绘图线程问题通常不影响模型可用性
- 真正判断可用性的关键是命令行流程是否跑通：训练、评估、视频分析、导出

如果这些都正常，模型可用于后续实时/离线工作流。
