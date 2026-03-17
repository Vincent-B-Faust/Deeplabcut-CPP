from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize

from cpp_dlc_live.analysis.metrics import compute_dt_seconds


def plot_trajectory(df: pd.DataFrame, roi_cfg: Optional[Dict[str, Any]], out_path: Path) -> None:
    """Legacy plain trajectory plot kept for backward compatibility."""
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


def plot_trajectory_speed_heatmap(
    df: pd.DataFrame,
    speed_df: pd.DataFrame,
    roi_cfg: Optional[Dict[str, Any]],
    out_path: Path,
) -> None:
    """Figure 1: trajectory with segment color mapped to instantaneous speed."""
    x = pd.to_numeric(df.get("x"), errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df.get("y"), errors="coerce").to_numpy(dtype=float)
    speed = pd.to_numeric(speed_df.get("speed_px_s"), errors="coerce").to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(8, 6))
    _draw_speed_colored_trajectory(ax=ax, x=x, y=y, speed=speed)
    ax.set_title("Figure 1: Trajectory Colored by Speed")
    ax.set_xlabel("x (px)")
    ax.set_ylabel("y (px)")
    ax.invert_yaxis()

    if roi_cfg:
        _draw_roi(ax, roi_cfg.get("chamber1"), "tab:green", "ch1")
        _draw_roi(ax, roi_cfg.get("chamber2"), "tab:orange", "ch2")
        _draw_roi(ax, roi_cfg.get("neutral"), "tab:gray", "neutral")
    if ax.has_data():
        ax.legend(loc="best")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_position_heatmap(df: pd.DataFrame, roi_cfg: Optional[Dict[str, Any]], out_path: Path) -> None:
    """Figure 2: 2D occupancy heatmap of positions."""
    x = pd.to_numeric(df.get("x"), errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df.get("y"), errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    xv = x[valid]
    yv = y[valid]

    fig, ax = plt.subplots(figsize=(8, 6))
    if xv.size > 0:
        bins = max(32, min(120, int(np.sqrt(xv.size))))
        h = ax.hist2d(xv, yv, bins=bins, cmap="hot")
        cbar = fig.colorbar(h[3], ax=ax)
        cbar.set_label("Counts")
    else:
        ax.text(0.5, 0.5, "No valid position data", ha="center", va="center", transform=ax.transAxes)

    ax.set_title("Figure 2: Position Heatmap")
    ax.set_xlabel("x (px)")
    ax.set_ylabel("y (px)")
    ax.invert_yaxis()

    if roi_cfg:
        _draw_roi(ax, roi_cfg.get("chamber1"), "tab:green", "ch1")
        _draw_roi(ax, roi_cfg.get("chamber2"), "tab:orange", "ch2")
        _draw_roi(ax, roi_cfg.get("neutral"), "tab:gray", "neutral")
    if ax.has_data():
        ax.legend(loc="best")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_chamber_time_bars(df: pd.DataFrame, out_path: Path, fixed_fps_hz: Optional[float] = None) -> None:
    """Figure 3: chamber1/chamber2 dwell durations and percentages."""
    dt = compute_dt_seconds(df, fixed_fps_hz=fixed_fps_hz)
    chamber = df.get("chamber", pd.Series(["unknown"] * len(df))).astype(str).str.lower().to_numpy(dtype=str)

    labels = ["chamber1", "chamber2"]
    durations = np.array([float(dt[chamber == label].sum()) for label in labels], dtype=float)
    total = float(durations.sum())
    percentages = (durations / total * 100.0) if total > 0 else np.zeros_like(durations)

    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)

    axes[0].bar(labels, durations, color=["tab:green", "tab:orange"])
    axes[0].set_title("Figure 3A: Dwell Time in Chambers")
    axes[0].set_ylabel("Time (s)")
    for i, v in enumerate(durations):
        axes[0].text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)

    axes[1].bar(labels, percentages, color=["tab:green", "tab:orange"])
    axes[1].set_title("Figure 3B: Dwell Percentage in Chambers")
    axes[1].set_ylabel("Percentage (%)")
    axes[1].set_ylim(0, 100)
    for i, v in enumerate(percentages):
        axes[1].text(i, v, f"{v:.2f}%", ha="center", va="bottom", fontsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_speed(speed_df: pd.DataFrame, out_path: Path) -> None:
    t = pd.to_numeric(speed_df.get("t_wall"), errors="coerce")
    t = t - float(np.nanmin(t)) if len(t) else t
    speed = pd.to_numeric(speed_df.get("speed_px_s"), errors="coerce")

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(t, speed, lw=1.0, color="tab:red")
    ax.set_title("Figure 4: Speed over Time")
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
    ax.set_title("Figure 5: Chamber Occupancy")
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


def _draw_speed_colored_trajectory(ax: Any, x: np.ndarray, y: np.ndarray, speed: np.ndarray) -> None:
    if x.size < 2 or y.size < 2:
        ax.text(0.5, 0.5, "No valid trajectory data", ha="center", va="center", transform=ax.transAxes)
        return

    points = np.column_stack([x, y])
    if speed.size != x.size:
        ax.plot(x, y, lw=1.0, color="tab:blue")
        return

    segments = np.stack([points[:-1], points[1:]], axis=1)
    seg_speed = speed[1:]

    valid = (
        np.isfinite(segments[:, 0, 0])
        & np.isfinite(segments[:, 0, 1])
        & np.isfinite(segments[:, 1, 0])
        & np.isfinite(segments[:, 1, 1])
        & np.isfinite(seg_speed)
    )
    if not np.any(valid):
        ax.plot(x, y, lw=1.0, color="tab:blue")
        return

    segments_valid = segments[valid]
    speed_valid = seg_speed[valid]
    vmin = float(np.nanpercentile(speed_valid, 5)) if speed_valid.size else 0.0
    vmax = float(np.nanpercentile(speed_valid, 95)) if speed_valid.size else 1.0
    if not np.isfinite(vmin):
        vmin = 0.0
    if not np.isfinite(vmax) or vmax <= vmin:
        vmax = vmin + 1e-6

    lc = LineCollection(segments_valid, cmap="turbo", norm=Normalize(vmin=vmin, vmax=vmax))
    lc.set_array(speed_valid)
    lc.set_linewidth(1.5)
    ax.add_collection(lc)
    ax.autoscale()

    cbar = plt.colorbar(lc, ax=ax)
    cbar.set_label("Speed (px/s)")
