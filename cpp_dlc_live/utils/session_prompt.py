from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def collect_session_info(
    default_mouse_id: str = "",
    default_group: str = "",
    default_duration_s: Optional[float] = None,
    history_path: Optional[Path] = None,
) -> Dict[str, Any]:
    history_file = history_path or (Path.home() / ".cpp_dlc_live_session_history.json")
    history = _load_history(history_file)

    default_duration_text = ""
    if default_duration_s is not None:
        default_duration_text = _format_duration(default_duration_s)

    try:
        values = _prompt_with_tk(
            mouse_default=default_mouse_id,
            group_default=default_group,
            duration_default=default_duration_text,
            mouse_history=history.get("mouse_id", []),
            group_history=history.get("group", []),
            duration_history=history.get("experiment_duration_s", []),
        )
    except Exception:
        values = _prompt_in_console(
            mouse_default=default_mouse_id,
            group_default=default_group,
            duration_default=default_duration_text,
        )

    mouse_id = str(values["mouse_id"]).strip()
    group = str(values["group"]).strip()
    duration_s = _parse_positive_float(values["experiment_duration_s"], "实验时长")

    _update_history(history, "mouse_id", mouse_id)
    _update_history(history, "group", group)
    _update_history(history, "experiment_duration_s", _format_duration(duration_s))
    _save_history(history_file, history)

    return {
        "mouse_id": mouse_id,
        "group": group,
        "experiment_duration_s": duration_s,
    }


def _prompt_with_tk(
    mouse_default: str,
    group_default: str,
    duration_default: str,
    mouse_history: List[str],
    group_history: List[str],
    duration_history: List[str],
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
    ttk.Label(frame, text="实验时长(s)").grid(row=2, column=0, sticky="w", pady=(0, 10))

    mouse_values = _merge_history(mouse_default, mouse_history)
    group_values = _merge_history(group_default, group_history)
    duration_values = _merge_history(duration_default, duration_history)

    mouse_var = tk.StringVar(value=mouse_default)
    group_var = tk.StringVar(value=group_default)
    duration_var = tk.StringVar(value=duration_default)

    mouse_box = ttk.Combobox(frame, textvariable=mouse_var, values=mouse_values, width=30)
    group_box = ttk.Combobox(frame, textvariable=group_var, values=group_values, width=30)
    duration_box = ttk.Combobox(frame, textvariable=duration_var, values=duration_values, width=30)
    mouse_box.grid(row=0, column=1, sticky="ew", pady=(0, 6))
    group_box.grid(row=1, column=1, sticky="ew", pady=(0, 6))
    duration_box.grid(row=2, column=1, sticky="ew", pady=(0, 10))

    result: Dict[str, str] = {}
    cancelled = {"value": False}

    def on_ok() -> None:
        mouse_id = mouse_var.get().strip()
        group = group_var.get().strip()
        duration_text = duration_var.get().strip()
        if not mouse_id:
            messagebox.showerror("输入错误", "小鼠编号不能为空")
            return
        if not group:
            messagebox.showerror("输入错误", "实验组别不能为空")
            return
        try:
            _parse_positive_float(duration_text, "实验时长")
        except ValueError as exc:
            messagebox.showerror("输入错误", str(exc))
            return
        result["mouse_id"] = mouse_id
        result["group"] = group
        result["experiment_duration_s"] = duration_text
        root.destroy()

    def on_cancel() -> None:
        cancelled["value"] = True
        root.destroy()

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=3, column=0, columnspan=2, sticky="e")
    ttk.Button(btn_frame, text="取消", command=on_cancel).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(btn_frame, text="开始记录", command=on_ok).grid(row=0, column=1)

    frame.columnconfigure(1, weight=1)
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
) -> Dict[str, str]:
    mouse_prompt = f"小鼠编号 [{mouse_default}]: " if mouse_default else "小鼠编号: "
    group_prompt = f"实验组别 [{group_default}]: " if group_default else "实验组别: "
    duration_prompt = f"实验时长(s) [{duration_default}]: " if duration_default else "实验时长(s): "

    mouse_id = input(mouse_prompt).strip() or mouse_default
    group = input(group_prompt).strip() or group_default
    duration_text = input(duration_prompt).strip() or duration_default

    if not mouse_id:
        raise ValueError("小鼠编号不能为空")
    if not group:
        raise ValueError("实验组别不能为空")
    _parse_positive_float(duration_text, "实验时长")

    return {
        "mouse_id": mouse_id,
        "group": group,
        "experiment_duration_s": duration_text,
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


def _load_history(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        return {"mouse_id": [], "group": [], "experiment_duration_s": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"mouse_id": [], "group": [], "experiment_duration_s": []}
    if not isinstance(raw, dict):
        return {"mouse_id": [], "group": [], "experiment_duration_s": []}
    out: Dict[str, List[str]] = {}
    for key in ("mouse_id", "group", "experiment_duration_s"):
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


def _merge_history(default: str, history: List[str]) -> List[str]:
    merged: List[str] = []
    if default:
        merged.append(default)
    for value in history:
        if value and value not in merged:
            merged.append(value)
    return merged
