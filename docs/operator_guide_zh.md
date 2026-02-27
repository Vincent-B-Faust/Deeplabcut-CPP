# cpp_dlc_live 实验员版使用手册（操作流程）

本文档面向实验执行人员，重点是“怎么配、怎么跑、怎么查结果”。

## 1. 你可以用它做什么

1. 实时读取相机或视频文件。
2. 实时识别小鼠位置并判断 `chamber1/chamber2/neutral`。
3. 在 `chamber1` 触发激光，在 `chamber2` 关闭激光。
4. 自动记录每帧数据与实验元信息。
5. 实验后自动统计停留时间、速度、距离、激光时长。

## 2. 开始前检查

## 2.1 必需软件

1. Python 3.10。
2. 项目依赖安装完成（参考 `DEPLOYMENT_REQUIREMENTS.md`）。
3. 命令可用：

```bash
python -m cpp_dlc_live.cli --help
```

## 2.2 NI 模式额外要求

1. 安装 NI-DAQmx 驱动。
2. 在 NI MAX 里确认设备与通道可见。
3. 配置文件中的 `ctr_channel/pulse_term/enable_line` 与实际一致。

## 2.3 DLC 模式额外要求

1. 已导出 DLC-live 模型目录。
2. 配置 `dlc.model_path` 指向模型目录。

## 3. 配置文件怎么填（最关键）

配置文件模板：`config/config_example.yaml`

## 3.1 `project`

1. `session_id` 建议使用 `auto_timestamp`。
2. `out_dir` 建议按日期组织，比如 `./data`。

## 3.2 `camera`

1. `source=0` 表示默认摄像头。
2. 也可填视频路径用于 dryrun 回放。
3. 建议先用 `1280x720 @30fps`。

## 3.3 `dlc`

1. `model_path`：模型目录。
2. `bodypart`：推荐 `center`。
3. `p_thresh`：推荐 `0.6` 起步。
4. `smoothing.enabled=true` 可减少抖动。

## 3.4 `roi`

1. `type`：`polygon` 或 `rect`。
2. `chamber1/chamber2` 必填。
3. `neutral` 可选。
4. `debounce_frames` 推荐 `8`。
5. `strategy_on_neutral`：
   1. `off`：neutral 时激光关。
   2. `hold_last`：保持上一 chamber 逻辑。
   3. `unknown`：按 unknown 策略处理。

## 3.5 `laser_control`

1. `mode=dryrun`：联调首选。
2. `mode=gated`：硬件推荐模式。
3. `mode=startstop`：兼容模式，需设置 `min_on_s/min_off_s`。
4. `fallback_to_dryrun=true`：NI 异常时自动降级（建议保持开启）。

## 3.6 `runtime_logging`（回溯关键）

1. `enabled=true`：开启结构化问题日志。
2. `issue_events_file`：事件日志文件名（默认 `issue_events.jsonl`）。
3. `heartbeat_interval_s`：心跳记录周期（建议 `5.0` 秒）。
4. `low_conf_warn_every_n`：低置信度周期告警频率。
5. `inference_warn_ms`：推理耗时告警阈值。
6. `fps_warn_below`：低 FPS 告警阈值。

## 3.7 `preview_recording`（可选录制预览视频）

1. `enabled=true`：保存预览视频到 session 目录。
2. `filename`：视频文件名（默认 `preview_overlay.mp4`）。
3. `codec`：OpenCV FourCC（默认 `mp4v`）。
4. `fps`：写出帧率，留空会自动用相机 FPS/目标 FPS。
5. `overlay=true`：保存带 ROI/状态叠加的视频；`false` 保存原始帧。

## 4. 四条命令怎么用

## 4.1 ROI 标定（先做）

```bash
python -m cpp_dlc_live.cli calibrate_roi \
  --config config/config_example.yaml \
  --camera_source 0
```

交互键：
1. 左键加点。
2. `u` 撤销。
3. `r` 重置当前 ROI。
4. `n` 下一块 ROI。
5. `s` 保存。
6. `q`/`Esc` 取消。

## 4.2 实时运行

```bash
python -m cpp_dlc_live.cli run_realtime \
  --config config/config_example.yaml \
  --duration_s 600
```

常用可选参数：
1. `--out_dir`：覆盖输出目录。
2. `--camera_source`：覆盖相机/视频来源。
3. `--no_preview`：无显示环境时关闭窗口。
4. 即使 `--no_preview`，只要 `preview_recording.enabled=true` 仍会保存视频。

结束方式：
1. 预览窗口按 `q` 或 `Esc`。
2. `Ctrl-C`。
3. 到 `duration_s` 自动结束。
4. 视频文件到末尾自动结束。

## 4.3 离线分析

```bash
python -m cpp_dlc_live.cli analyze_session \
  --session_dir data/<session_id>
```

可选：
1. `--cm_per_px 0.05`。
2. `--no_plots` 只要 summary。

## 4.4 问题日志分析（回溯专用）

```bash
python -m cpp_dlc_live.cli analyze_issues \
  --session_dir data/<session_id>
```

可选：
1. `--issue_file issue_events.jsonl`（可传绝对路径，或相对 `session_dir` 的路径）。

输出：
1. `issue_summary.csv`：按事件类型和级别统计计数。
2. `issue_timeline.csv`：按时间展开的标准化事件流。
3. `incident_summary.csv`：异常报告摘要（由 `incident_report_*.json` 汇总）。

## 5. 标准操作流程（SOP）

## 5.1 第一次部署

1. 配好环境。
2. 准备配置文件。
3. 执行 `calibrate_roi`。
4. 先跑 `dryrun` 30 秒。
5. 确认输出文件齐全。

## 5.2 每次实验前

1. 检查相机画面与 ROI。
2. 检查激光策略与模式。
3. NI 模式下检查通道占用。
4. 先做 1 分钟短跑验证。

## 5.3 实验执行

1. 启动 `run_realtime`。
2. 观察窗口叠加信息：`chamber/laser/fps/infer_ms`。
3. 异常时优先停机检查：
   1. `run.log`（人类可读日志）。
   2. `issue_events.jsonl`（结构化事件）。
   3. `incident_report_*.json`（异常快照，若有）。

## 5.4 实验后

1. 执行 `analyze_session`。
2. 需要排障时执行 `analyze_issues`。
3. 归档 session 目录。
4. 记录关键指标并备份。

## 6. 输出文件怎么解读

每个 session 目录至少有：
1. `cpp_realtime_log.csv`：逐帧日志。
2. `metadata.json`：实验元数据。
3. `config_used.yaml`：当次配置快照。
4. `run.log`：运行日志。
5. `preview_overlay.mp4`：预览视频（开启 `preview_recording` 时生成，文件名可配置）。
6. `issue_events.jsonl`：结构化问题日志（事件流）。
7. `incident_report_*.json`：异常报告（发生异常时生成）。
8. `summary.csv`：离线统计结果。
9. `issue_summary.csv`：问题事件计数汇总（执行 `analyze_issues` 后生成）。
10. `issue_timeline.csv`：问题时间线（执行 `analyze_issues` 后生成）。
11. `incident_summary.csv`：异常摘要（执行 `analyze_issues` 后生成）。

## 6.1 `summary.csv` 核心字段

1. `time_ch1_s/time_ch2_s/time_neutral_s`：各区域停留时间。
2. `distance_px/distance_cm`：总位移。
3. `mean_speed_px_s/mean_speed_cm_s`：平均速度。
4. `laser_on_time_s`：激光总开启时长。

## 7. 常见问题

1. 启动即退出：
   1. 检查 `camera.source`。
   2. 若视频输入到 EOF，属于正常结束。
2. 总是 mock 推理：
   1. 检查 `dlc.model_path`。
   2. 检查 DLC 依赖是否安装。
3. NI 报错：
   1. 检查通道/路由。
   2. 检查 NI MAX 是否被占用。
4. 没有图：
   1. 检查是否用了 `--no_plots`。
   2. 检查 `analysis.output_plots=true`。
5. 想回溯“某一时刻为什么激光切换”：
   1. 查 `issue_events.jsonl` 中 `chamber_transition`、`laser_transition` 事件。
   2. 对照同一 `frame_idx` 的 `cpp_realtime_log.csv`。

## 8. 安全注意事项

1. 默认激光 OFF。
2. 任何异常会尝试强制 OFF。
3. 联调时先 `dryrun`，确认流程后再上 NI。
4. NI 模式建议先短时间试跑再正式实验。
