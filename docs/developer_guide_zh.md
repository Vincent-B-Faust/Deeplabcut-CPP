# cpp_dlc_live 开发者版手册（架构与二次开发）

本文档面向需要维护代码、扩展功能、接入新硬件或新模型的开发者。

## 1. 架构总览

系统分三层：

1. `CLI` 层：参数解析、配置加载、命令分发。
2. `Realtime` 层：采集、推理、ROI 判定、去抖、激光控制、记录。
3. `Analysis` 层：读取日志、计算指标、输出结果和图。

主入口：`cpp_dlc_live/cli.py`

## 2. 代码结构与职责

## 2.1 `cpp_dlc_live/cli.py`

1. `run_realtime`：准备 session、复制配置、启动 `RealtimeApp`。
2. `analyze_session`：调用离线分析。
3. `analyze_issues`：分析结构化问题事件与异常报告。
4. `calibrate_roi`：执行交互式 ROI 标定并写回配置。

## 2.2 `cpp_dlc_live/realtime/`

1. `app.py`：主循环与状态机。
2. `camera.py`：OpenCV 采集封装。
3. `dlc_runtime.py`：DLC runtime + mock fallback。
4. `roi.py`：ROI 数据结构、点在区域判定、标定。
5. `debounce.py`：稳定状态切换。
6. `controller_base.py`：激光控制接口。
7. `controller_ni.py`：`DryRun/Gated/StartStop` 三实现。
8. `recorder.py`：CSV 缓冲写入。
9. `logging_utils.py`：控制台与文件日志。
10. `issue_logger.py`：结构化事件日志（JSONL）。

## 2.3 `cpp_dlc_live/analysis/`

1. `analyze.py`：分析流程编排。
2. `issues.py`：问题事件和异常报告离线分析。
3. `metrics.py`：时长、距离、速度、激光时长计算。
4. `plots.py`：轨迹/速度/占据图。

## 2.4 `cpp_dlc_live/utils/`

1. `io_utils.py`：YAML/JSON 读写、session 准备、hash。
2. `time_utils.py`：时间工具函数。

## 3. 实时主循环细节（`RealtimeApp.run`）

每帧流程：

1. 读帧。
2. 推理并记录 `inference_ms`。
3. 置信度门限：`p < p_thresh` 走 hold-last-valid。
4. 可选坐标平滑（移动均值）。
5. ROI 分类得到 `chamber_raw`。
6. neutral 策略映射 + debounce 得到稳定 `chamber`。
7. chamber -> desired laser state。
8. 调控制器 `set_state`。
9. 记录日志行 + 问题事件（状态切换/告警/心跳）。
10. 按配置可选写出预览视频（支持叠加层或原始帧）。
11. 预览叠加并处理退出按键。

异常路径：

1. 捕获异常后强制激光 OFF。
2. 写 `incident_report_*.json`（异常类型、traceback、最后上下文）。
3. `finally` 中再次 OFF + 释放相机 + 关闭窗口 + 写 metadata。

## 3.1 运行时问题日志体系

默认会写三类日志：

1. `run.log`：文本日志（便于人工阅读）。
2. `issue_events.jsonl`：结构化事件流（便于检索与机器处理）。
3. `incident_report_*.json`：异常快照（仅异常时生成）。

关键事件类型：

1. `session_start/session_end`
2. `runtime_ready`
3. `low_confidence`
4. `inference_latency_warning`
5. `fps_warning`
6. `chamber_transition`
7. `laser_transition`
8. `runtime_exception`
9. `heartbeat`

`analyze_issues` 会基于这些事件生成：
1. `issue_summary.csv`
2. `issue_timeline.csv`
3. `incident_summary.csv`

## 4. 激光控制器实现与扩展

## 4.1 接口约定

基类：`LaserControllerBase`

1. `start()`：初始化资源。
2. `set_state(on: bool)`：更新输出状态。
3. `stop()`：停止并释放资源。

## 4.2 现有实现

1. `DryRunLaserController`：逻辑模拟，无硬件。
2. `NILaserControllerGated`：持续 counter + DO 使能门控。
3. `NILaserControllerStartStop`：按状态启停 counter，带最小开关时间。

## 4.3 新硬件接入建议

1. 新建 `LaserControllerBase` 子类。
2. 在 `create_laser_controller` 中注册新 `mode`。
3. 保证异常时 `set_state(False)` 和 `stop()` 幂等。
4. 增加 dryrun 回退策略与日志。

## 5. ROI 与状态稳定机制

## 5.1 ROI

1. `PolygonROI`：射线法 + 边界点 inside。
2. `RectROI`：支持 `[x1,y1,x2,y2]`、2点、4点格式。
3. `ChamberROI.classify`：neutral 优先，再 ch1/ch2，最后 unknown。

## 5.2 Debounce

1. 只有候选状态连续 N 帧一致才切换。
2. `required_count=1` 时立即切换。
3. neutral 可通过策略在 debounce 前映射为 `hold_last/unknown`。

## 6. 离线分析算法

## 6.1 时间步长

1. `dt = diff(t_wall)`。
2. 负值/非法值置 0。
3. 最后一帧 `dt` 用前序正 `dt` 中位数估计。

## 6.2 指标

1. 各 chamber 停留时间：按 `chamber` 对 `dt` 求和。
2. 距离：相邻点欧氏距离累加。
3. 平均速度：总距离 / session_duration。
4. 激光时长：`laser_state > 0.5` 对应 `dt` 求和。
5. `cm_per_px` 非空时导出厘米单位。

## 7. 配置驱动原则

1. 运行参数尽量全部来自 YAML。
2. CLI 覆盖项只做局部 override。
3. 运行时必须复制 `config_used.yaml` 到 session。
4. `metadata.json` 必须记录配置 hash 与关键运行参数。
5. `runtime_logging` 控制事件日志频率与告警阈值。
6. `preview_recording` 控制预览视频录制（开关、编码器、fps、是否叠加）。

## 8. 测试策略

现有测试：

1. `tests/test_roi.py`：点在多边形/矩形、neutral 优先。
2. `tests/test_debounce.py`：N 帧切换规则。
3. `tests/test_analysis_metrics.py`：停留时间/速度/激光时长。

建议补充：

1. `run_realtime` dryrun 集成测试（视频输入）。
2. `neutral` 三策略测试。
3. 控制器工厂参数校验测试。

## 9. 二次开发常见任务

## 9.1 新增 CLI 命令

1. 在 `cli.py` 的 subparser 新增命令。
2. 新建 `_cmd_xxx(args)`。
3. 复用 `setup_logging/load_yaml` 等工具。

## 9.2 替换推理后端（例如 DLC 3.0 PyTorch 适配）

1. 在 `dlc_runtime.py` 增加新 runtime 类。
2. 保持返回 `PoseResult(x,y,p,bodypart)`。
3. 在 `build_runtime` 中按配置选择 runtime。
4. 兼容 `p_thresh` 和 fallback 行为。

## 9.3 输出格式扩展（Parquet/数据库）

1. 扩展 `recorder.py`。
2. 保留 CSV 作为兼容默认输出。
3. 更新分析模块的读取入口。

## 10. 开发流程建议

1. 修改后执行：

```bash
pytest -q
python -m cpp_dlc_live.cli --help
```

2. 关键改动优先覆盖单测。
3. 涉及硬件改动先用 `dryrun` 验证行为。

## 11. 已知约束

1. 目前默认依赖 DLCLive SDK；若使用新推理栈需自行扩展 runtime。
2. NI 路由可用性依赖具体机箱/模块/布线。
3. 高 FPS 下建议评估写盘与预览的性能开销。
