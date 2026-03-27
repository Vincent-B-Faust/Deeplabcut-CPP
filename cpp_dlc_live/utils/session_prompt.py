from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_LASER_ON_CHAMBERS_ORDER = ("chamber1", "chamber2", "neutral")
_LASER_ON_CHAMBER_ALIASES = {
    "ch1": "chamber1",
    "1": "chamber1",
    "ch2": "chamber2",
    "2": "chamber2",
    "center": "neutral",
    "centre": "neutral",
    "middle": "neutral",
    "n": "neutral",
    "none": "none",
    "off": "none",
    "disabled": "none",
    "disable": "none",
    "no": "none",
    "0": "none",
}


def collect_session_info(
    default_mouse_id: str = "",
    default_group: str = "",
    default_duration_s: Optional[float] = None,
    default_laser_mode: str = "pulse",
    default_pulse_freq_hz: Optional[float] = None,
    default_laser_on_chambers: Optional[Any] = None,
    default_acclimation_enabled: bool = False,
    default_acclimation_duration_s: Optional[float] = None,
    history_path: Optional[Path] = None,
) -> Dict[str, Any]:
    history_file = history_path or (Path.home() / ".cpp_dlc_live_session_history.json")
    history = _load_history(history_file)

    default_duration_text = ""
    if default_duration_s is not None:
        default_duration_text = _format_duration(default_duration_s)
    default_mode_text = _normalize_laser_mode(default_laser_mode)
    default_pulse_freq_text = ""
    if default_pulse_freq_hz is not None:
        default_pulse_freq_text = _format_duration(default_pulse_freq_hz)
    default_laser_on_chambers_text = _format_laser_on_chambers(default_laser_on_chambers)
    default_acclimation_mode_text = "on" if bool(default_acclimation_enabled) else "off"
    default_acclimation_duration_text = ""
    if default_acclimation_duration_s is not None and float(default_acclimation_duration_s) > 0:
        default_acclimation_duration_text = _format_duration(default_acclimation_duration_s)

    try:
        values = _prompt_with_tk(
            mouse_default=default_mouse_id,
            group_default=default_group,
            duration_default=default_duration_text,
            laser_mode_default=default_mode_text,
            pulse_freq_default=default_pulse_freq_text,
            laser_on_chambers_default=default_laser_on_chambers_text,
            acclimation_mode_default=default_acclimation_mode_text,
            acclimation_duration_default=default_acclimation_duration_text,
            mouse_history=history.get("mouse_id", []),
            group_history=history.get("group", []),
            duration_history=history.get("experiment_duration_s", []),
            laser_mode_history=history.get("laser_mode", []),
            pulse_freq_history=history.get("pulse_freq_hz", []),
            laser_on_chambers_history=history.get("laser_on_chambers", []),
            acclimation_mode_history=history.get("acclimation_enabled", []),
            acclimation_duration_history=history.get("acclimation_duration_s", []),
        )
    except Exception:
        values = _prompt_in_console(
            mouse_default=default_mouse_id,
            group_default=default_group,
            duration_default=default_duration_text,
            laser_mode_default=default_mode_text,
            pulse_freq_default=default_pulse_freq_text,
            laser_on_chambers_default=default_laser_on_chambers_text,
            acclimation_mode_default=default_acclimation_mode_text,
            acclimation_duration_default=default_acclimation_duration_text,
        )

    mouse_id = str(values["mouse_id"]).strip()
    group = str(values["group"]).strip()
    duration_s = _parse_positive_float(values["experiment_duration_s"], "实验时长")
    laser_mode = _normalize_laser_mode(values.get("laser_mode", default_mode_text))
    laser_on_chambers = normalize_laser_on_chambers(values.get("laser_on_chambers", default_laser_on_chambers_text))
    pulse_freq_hz: Optional[float] = None
    if laser_mode == "pulse":
        pulse_freq_hz = _parse_positive_float(values.get("pulse_freq_hz", default_pulse_freq_text), "脉冲频率")
    acclimation_enabled = _parse_toggle(values.get("acclimation_enabled", default_acclimation_mode_text))
    acclimation_duration_s = 0.0
    if acclimation_enabled:
        acclimation_duration_s = _parse_positive_float(
            values.get("acclimation_duration_s", default_acclimation_duration_text),
            "适应时长",
        )

    _update_history(history, "mouse_id", mouse_id)
    _update_history(history, "group", group)
    _update_history(history, "experiment_duration_s", _format_duration(duration_s))
    _update_history(history, "laser_mode", laser_mode)
    _update_history(history, "laser_on_chambers", _format_laser_on_chambers(laser_on_chambers))
    if pulse_freq_hz is not None:
        _update_history(history, "pulse_freq_hz", _format_duration(pulse_freq_hz))
    _update_history(history, "acclimation_enabled", ("on" if acclimation_enabled else "off"))
    if acclimation_enabled and acclimation_duration_s > 0:
        _update_history(history, "acclimation_duration_s", _format_duration(acclimation_duration_s))
    _save_history(history_file, history)

    return {
        "mouse_id": mouse_id,
        "group": group,
        "experiment_duration_s": duration_s,
        "laser_mode": laser_mode,
        "pulse_freq_hz": pulse_freq_hz,
        "laser_on_chambers": laser_on_chambers,
        "acclimation_enabled": acclimation_enabled,
        "acclimation_duration_s": acclimation_duration_s,
    }


def _prompt_with_tk(
    mouse_default: str,
    group_default: str,
    duration_default: str,
    laser_mode_default: str,
    pulse_freq_default: str,
    laser_on_chambers_default: str,
    acclimation_mode_default: str,
    acclimation_duration_default: str,
    mouse_history: List[str],
    group_history: List[str],
    duration_history: List[str],
    laser_mode_history: List[str],
    pulse_freq_history: List[str],
    laser_on_chambers_history: List[str],
    acclimation_mode_history: List[str],
    acclimation_duration_history: List[str],
) -> Dict[str, str]:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("实验信息录入")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frame, text="小鼠编号").grid(row=0, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="实验组别").grid(row=1, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="实验时长(s)").grid(row=2, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="激光模式").grid(row=3, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="激光ON区域").grid(row=4, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="脉冲频率(Hz)").grid(row=5, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="适应期").grid(row=6, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="适应时长(s)").grid(row=7, column=0, sticky="w", pady=(0, 10))

    mouse_values = _merge_history(mouse_default, mouse_history)
    group_values = _merge_history(group_default, group_history)
    duration_values = _merge_history(duration_default, duration_history)
    laser_mode_values = _merge_history(laser_mode_default, laser_mode_history, allowed={"continuous", "pulse"})
    laser_mode_values = _ensure_choices(
        values=laser_mode_values,
        required=["continuous", "pulse"],
        preferred=laser_mode_default,
    )
    laser_on_chambers_values = _merge_history(laser_on_chambers_default, laser_on_chambers_history)
    laser_on_chambers_values = _ensure_choices(
        values=laser_on_chambers_values,
        required=["chamber1", "chamber2", "neutral", "chamber1,chamber2", "all", "none"],
        preferred=laser_on_chambers_default,
    )
    pulse_freq_values = _merge_history(pulse_freq_default, pulse_freq_history)
    acclimation_mode_values = _merge_history(
        acclimation_mode_default,
        acclimation_mode_history,
        allowed={"on", "off"},
    )
    acclimation_mode_values = _ensure_choices(
        values=acclimation_mode_values,
        required=["on", "off"],
        preferred=acclimation_mode_default,
    )
    acclimation_duration_values = _merge_history(acclimation_duration_default, acclimation_duration_history)

    mouse_var = tk.StringVar(value=mouse_default)
    group_var = tk.StringVar(value=group_default)
    duration_var = tk.StringVar(value=duration_default)
    laser_mode_var = tk.StringVar(value=laser_mode_default)
    laser_on_chambers_var = tk.StringVar(value=laser_on_chambers_default)
    pulse_freq_var = tk.StringVar(value=pulse_freq_default)
    acclimation_mode_var = tk.StringVar(value=acclimation_mode_default)
    acclimation_duration_var = tk.StringVar(value=acclimation_duration_default)

    mouse_box = ttk.Combobox(frame, textvariable=mouse_var, values=mouse_values, width=30)
    group_box = ttk.Combobox(frame, textvariable=group_var, values=group_values, width=30)
    duration_box = ttk.Combobox(frame, textvariable=duration_var, values=duration_values, width=30)
    laser_mode_box = ttk.Combobox(frame, textvariable=laser_mode_var, values=laser_mode_values, width=30, state="readonly")
    laser_on_chambers_box = ttk.Combobox(
        frame,
        textvariable=laser_on_chambers_var,
        values=laser_on_chambers_values,
        width=30,
    )
    pulse_freq_box = ttk.Combobox(frame, textvariable=pulse_freq_var, values=pulse_freq_values, width=30)
    acclimation_mode_box = ttk.Combobox(
        frame,
        textvariable=acclimation_mode_var,
        values=acclimation_mode_values,
        width=30,
        state="readonly",
    )
    acclimation_duration_box = ttk.Combobox(
        frame,
        textvariable=acclimation_duration_var,
        values=acclimation_duration_values,
        width=30,
    )
    mouse_box.grid(row=0, column=1, sticky="ew", pady=(0, 6))
    group_box.grid(row=1, column=1, sticky="ew", pady=(0, 6))
    duration_box.grid(row=2, column=1, sticky="ew", pady=(0, 6))
    laser_mode_box.grid(row=3, column=1, sticky="ew", pady=(0, 6))
    laser_on_chambers_box.grid(row=4, column=1, sticky="ew", pady=(0, 6))
    pulse_freq_box.grid(row=5, column=1, sticky="ew", pady=(0, 6))
    acclimation_mode_box.grid(row=6, column=1, sticky="ew", pady=(0, 6))
    acclimation_duration_box.grid(row=7, column=1, sticky="ew", pady=(0, 10))

    result: Dict[str, str] = {}
    cancelled = {"value": False}

    def _on_mode_changed(*_args: Any) -> None:
        mode = _normalize_laser_mode(laser_mode_var.get())
        pulse_freq_box.configure(state=("normal" if mode == "pulse" else "disabled"))

    def _on_acclimation_changed(*_args: Any) -> None:
        try:
            enabled = _parse_toggle(acclimation_mode_var.get())
        except ValueError:
            enabled = False
        acclimation_duration_box.configure(state=("normal" if enabled else "disabled"))

    def on_ok() -> None:
        mouse_id = mouse_var.get().strip()
        group = group_var.get().strip()
        duration_text = duration_var.get().strip()
        laser_mode = _normalize_laser_mode(laser_mode_var.get())
        laser_on_chambers = normalize_laser_on_chambers(laser_on_chambers_var.get())
        pulse_freq_text = pulse_freq_var.get().strip()
        acclimation_enabled = _parse_toggle(acclimation_mode_var.get())
        acclimation_duration_text = acclimation_duration_var.get().strip()
        if not mouse_id:
            messagebox.showerror("输入错误", "小鼠编号不能为空")
            return
        if not group:
            messagebox.showerror("输入错误", "实验组别不能为空")
            return
        try:
            _parse_positive_float(duration_text, "实验时长")
            if laser_mode == "pulse":
                _parse_positive_float(pulse_freq_text, "脉冲频率")
            if acclimation_enabled:
                _parse_positive_float(acclimation_duration_text, "适应时长")
        except ValueError as exc:
            messagebox.showerror("输入错误", str(exc))
            return
        result["mouse_id"] = mouse_id
        result["group"] = group
        result["experiment_duration_s"] = duration_text
        result["laser_mode"] = laser_mode
        result["laser_on_chambers"] = _format_laser_on_chambers(laser_on_chambers)
        result["pulse_freq_hz"] = pulse_freq_text
        result["acclimation_enabled"] = "on" if acclimation_enabled else "off"
        result["acclimation_duration_s"] = acclimation_duration_text if acclimation_enabled else "0"
        root.destroy()

    def on_cancel() -> None:
        cancelled["value"] = True
        root.destroy()

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=8, column=0, columnspan=2, sticky="e")
    ttk.Button(btn_frame, text="取消", command=on_cancel).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(btn_frame, text="开始记录", command=on_ok).grid(row=0, column=1)

    frame.columnconfigure(1, weight=1)
    laser_mode_var.trace_add("write", _on_mode_changed)
    acclimation_mode_var.trace_add("write", _on_acclimation_changed)
    _on_mode_changed()
    _on_acclimation_changed()
    mouse_box.focus_set()
    root.bind("<Return>", lambda _evt: on_ok())
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()

    if cancelled["value"]:
        raise RuntimeError("Session setup cancelled by user")
    if not result:
        raise RuntimeError("Session setup cancelled")
    return result


def _prompt_in_console(
    mouse_default: str,
    group_default: str,
    duration_default: str,
    laser_mode_default: str,
    pulse_freq_default: str,
    laser_on_chambers_default: str,
    acclimation_mode_default: str,
    acclimation_duration_default: str,
) -> Dict[str, str]:
    mouse_prompt = f"小鼠编号 [{mouse_default}]: " if mouse_default else "小鼠编号: "
    group_prompt = f"实验组别 [{group_default}]: " if group_default else "实验组别: "
    duration_prompt = f"实验时长(s) [{duration_default}]: " if duration_default else "实验时长(s): "
    mode_prompt = f"激光模式 continuous|pulse [{laser_mode_default}]: " if laser_mode_default else "激光模式 continuous|pulse: "
    on_region_prompt = (
        f"激光ON区域 chamber1|chamber2|neutral|all|none [{laser_on_chambers_default}]: "
        if laser_on_chambers_default
        else "激光ON区域 chamber1|chamber2|neutral|all|none: "
    )
    pulse_prompt = f"脉冲频率(Hz) [{pulse_freq_default}]: " if pulse_freq_default else "脉冲频率(Hz): "
    acclimation_prompt = (
        f"是否启用适应期 on|off [{acclimation_mode_default}]: "
        if acclimation_mode_default
        else "是否启用适应期 on|off: "
    )
    acclimation_duration_prompt = (
        f"适应时长(s) [{acclimation_duration_default}]: "
        if acclimation_duration_default
        else "适应时长(s): "
    )

    mouse_id = input(mouse_prompt).strip() or mouse_default
    group = input(group_prompt).strip() or group_default
    duration_text = input(duration_prompt).strip() or duration_default
    laser_mode_text = input(mode_prompt).strip() or laser_mode_default
    laser_mode = _normalize_laser_mode(laser_mode_text)
    laser_on_chambers_text = input(on_region_prompt).strip() or laser_on_chambers_default
    laser_on_chambers = normalize_laser_on_chambers(laser_on_chambers_text)
    pulse_freq_text = ""
    if laser_mode == "pulse":
        pulse_freq_text = input(pulse_prompt).strip() or pulse_freq_default
    acclimation_enabled = _parse_toggle(input(acclimation_prompt).strip() or acclimation_mode_default)
    acclimation_duration_text = "0"
    if acclimation_enabled:
        acclimation_duration_text = input(acclimation_duration_prompt).strip() or acclimation_duration_default

    if not mouse_id:
        raise ValueError("小鼠编号不能为空")
    if not group:
        raise ValueError("实验组别不能为空")
    _parse_positive_float(duration_text, "实验时长")
    if laser_mode == "pulse":
        _parse_positive_float(pulse_freq_text, "脉冲频率")
    if acclimation_enabled:
        _parse_positive_float(acclimation_duration_text, "适应时长")

    return {
        "mouse_id": mouse_id,
        "group": group,
        "experiment_duration_s": duration_text,
        "laser_mode": laser_mode,
        "laser_on_chambers": _format_laser_on_chambers(laser_on_chambers),
        "pulse_freq_hz": pulse_freq_text,
        "acclimation_enabled": ("on" if acclimation_enabled else "off"),
        "acclimation_duration_s": acclimation_duration_text,
    }


def _parse_positive_float(value: str, field_name: str) -> float:
    try:
        parsed = float(str(value).strip())
    except Exception as exc:
        raise ValueError(f"{field_name}必须是数字") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name}必须大于0")
    return parsed


def _format_duration(value: float) -> str:
    val = float(value)
    if val.is_integer():
        return str(int(val))
    return f"{val:.3f}".rstrip("0").rstrip(".")


def _normalize_laser_mode(value: str) -> str:
    text = str(value).strip().lower()
    if text in {"continuous", "continues", "level"}:
        return "continuous"
    if text in {"pulse", "gated", "startstop"}:
        return "pulse"
    raise ValueError(f"激光模式必须是 continuous 或 pulse，当前为: {value}")


def normalize_laser_on_chambers(value: Any) -> List[str]:
    if value is None:
        return ["chamber1"]

    tokens: List[str]
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return ["chamber1"]
        for sep in ("|", ";", "+"):
            text = text.replace(sep, ",")
        tokens = [token.strip() for token in text.split(",") if token.strip()]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(token).strip().lower() for token in value if str(token).strip()]
        if not tokens:
            # Explicit empty list means "none": no chamber can turn laser ON.
            return []
    else:
        raise ValueError(f"激光ON区域必须是字符串或列表，当前为: {type(value).__name__}")

    if any(token in {"all", "*"} for token in tokens):
        return list(_LASER_ON_CHAMBERS_ORDER)

    if any(token in {"none", "off", "disabled", "disable", "no", "0"} for token in tokens):
        # Explicit OFF region selection: no chamber can turn laser ON.
        # Mixing none with chamber names is considered invalid to avoid ambiguity.
        chamber_like = {t for t in tokens if t not in {"none", "off", "disabled", "disable", "no", "0"}}
        if chamber_like:
            raise ValueError("激光ON区域不能同时包含 none 和 chamber 名称")
        return []

    normalized: List[str] = []
    invalid: List[str] = []
    for token in tokens:
        mapped = _LASER_ON_CHAMBER_ALIASES.get(token, token)
        if mapped in _LASER_ON_CHAMBERS_ORDER:
            if mapped not in normalized:
                normalized.append(mapped)
        else:
            invalid.append(token)

    if invalid:
        raise ValueError(
            f"激光ON区域包含无效项: {invalid}；有效值: chamber1, chamber2, neutral, all, none"
        )

    if not normalized:
        return ["chamber1"]

    return [name for name in _LASER_ON_CHAMBERS_ORDER if name in normalized]


def _format_laser_on_chambers(value: Any) -> str:
    normalized = normalize_laser_on_chambers(value)
    if not normalized:
        return "none"
    if normalized == list(_LASER_ON_CHAMBERS_ORDER):
        return "all"
    return ",".join(normalized)


def _parse_toggle(value: str) -> bool:
    text = str(value).strip().lower()
    if text in {"on", "true", "1", "yes", "y"}:
        return True
    if text in {"off", "false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"开关值必须是 on 或 off，当前为: {value}")


def _load_history(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        return {
            "mouse_id": [],
            "group": [],
            "experiment_duration_s": [],
            "laser_mode": [],
            "laser_on_chambers": [],
            "pulse_freq_hz": [],
            "acclimation_enabled": [],
            "acclimation_duration_s": [],
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "mouse_id": [],
            "group": [],
            "experiment_duration_s": [],
            "laser_mode": [],
            "laser_on_chambers": [],
            "pulse_freq_hz": [],
            "acclimation_enabled": [],
            "acclimation_duration_s": [],
        }
    if not isinstance(raw, dict):
        return {
            "mouse_id": [],
            "group": [],
            "experiment_duration_s": [],
            "laser_mode": [],
            "laser_on_chambers": [],
            "pulse_freq_hz": [],
            "acclimation_enabled": [],
            "acclimation_duration_s": [],
        }
    out: Dict[str, List[str]] = {}
    for key in (
        "mouse_id",
        "group",
        "experiment_duration_s",
        "laser_mode",
        "laser_on_chambers",
        "pulse_freq_hz",
        "acclimation_enabled",
        "acclimation_duration_s",
    ):
        values = raw.get(key, [])
        if isinstance(values, list):
            out[key] = [str(v).strip() for v in values if str(v).strip()]
        else:
            out[key] = []
    return out


def _save_history(path: Path, history: Dict[str, List[str]]) -> None:
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_history(history: Dict[str, List[str]], key: str, value: str, max_items: int = 20) -> None:
    values = [v for v in history.get(key, []) if v != value]
    values.insert(0, value)
    history[key] = values[:max_items]


def _merge_history(default: str, history: List[str], allowed: Optional[set[str]] = None) -> List[str]:
    merged: List[str] = []
    if default and (allowed is None or default in allowed):
        merged.append(default)
    for value in history:
        if value and (allowed is None or value in allowed) and value not in merged:
            merged.append(value)
    return merged


def _ensure_choices(values: List[str], required: List[str], preferred: Optional[str] = None) -> List[str]:
    out: List[str] = []
    if preferred and preferred in required and preferred not in out:
        out.append(preferred)
    for value in values:
        if value and value not in out:
            out.append(value)
    for value in required:
        if value not in out:
            out.append(value)
    return out
