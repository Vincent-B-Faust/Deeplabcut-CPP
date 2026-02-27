from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_trajectory(df: pd.DataFrame, roi_cfg: Optional[Dict[str, Any]], out_path: Path) -> None:
    x = pd.to_numeric(df.get("x"), errors="coerce")
    y = pd.to_numeric(df.get("y"), errors="coerce")

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(x, y, lw=1.0, alpha=0.8, color="tab:blue")
    ax.set_title("Trajectory")
    ax.set_xlabel("x (px)")
    ax.set_ylabel("y (px)")
    ax.invert_yaxis()

    if roi_cfg:
        _draw_roi(ax, roi_cfg.get("chamber1"), "tab:green", "ch1")
        _draw_roi(ax, roi_cfg.get("chamber2"), "tab:orange", "ch2")
        _draw_roi(ax, roi_cfg.get("neutral"), "tab:gray", "neutral")

    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_speed(speed_df: pd.DataFrame, out_path: Path) -> None:
    t = pd.to_numeric(speed_df.get("t_wall"), errors="coerce")
    t = t - float(np.nanmin(t)) if len(t) else t
    speed = pd.to_numeric(speed_df.get("speed_px_s"), errors="coerce")

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(t, speed, lw=1.0, color="tab:red")
    ax.set_title("Speed over Time")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (px/s)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_occupancy(df: pd.DataFrame, out_path: Path) -> None:
    t = pd.to_numeric(df.get("t_wall"), errors="coerce")
    t = t - float(np.nanmin(t)) if len(t) else t
    chamber = df.get("chamber", pd.Series(["unknown"] * len(df))).astype(str).str.lower()

    mapping = {"unknown": 0, "neutral": 1, "chamber1": 2, "chamber2": 3}
    y = chamber.map(mapping).fillna(0)

    fig, ax = plt.subplots(figsize=(9, 3))
    ax.step(t, y, where="post", lw=1.0)
    ax.set_title("Chamber Occupancy")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("State")
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["unknown", "neutral", "ch1", "ch2"])
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _draw_roi(ax: Any, roi_points: Any, color: str, label: str) -> None:
    if not roi_points:
        return
    arr = np.array(roi_points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        return
    closed = np.vstack([arr, arr[0]])
    ax.plot(closed[:, 0], closed[:, 1], color=color, lw=1.5, label=label)
