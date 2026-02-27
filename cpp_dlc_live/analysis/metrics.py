from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def compute_dt_seconds(df: pd.DataFrame) -> np.ndarray:
    if "t_wall" not in df.columns or df.empty:
        return np.array([], dtype=float)

    t = pd.to_numeric(df["t_wall"], errors="coerce").to_numpy(dtype=float)
    n = len(t)
    dt = np.zeros(n, dtype=float)

    if n <= 1:
        return dt

    diffs = np.diff(t)
    diffs = np.where(np.isfinite(diffs), diffs, np.nan)
    diffs = np.where(diffs >= 0, diffs, 0.0)

    dt[:-1] = np.nan_to_num(diffs, nan=0.0, posinf=0.0, neginf=0.0)

    positive = dt[:-1][dt[:-1] > 0]
    dt[-1] = float(np.median(positive)) if positive.size else 0.0
    return dt


def compute_speed_series(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    if n == 0:
        return pd.DataFrame(columns=["t_wall", "speed_px_s"])

    dt = compute_dt_seconds(df)
    x = pd.to_numeric(df.get("x"), errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df.get("y"), errors="coerce").to_numpy(dtype=float)

    speed = np.full(n, np.nan, dtype=float)
    if n > 1:
        dx = np.diff(x)
        dy = np.diff(y)
        dist = np.sqrt(dx * dx + dy * dy)
        step_dt = dt[:-1]
        valid = np.isfinite(dist) & np.isfinite(step_dt) & (step_dt > 0)
        tmp = np.full(n - 1, np.nan, dtype=float)
        tmp[valid] = dist[valid] / step_dt[valid]
        speed[1:] = tmp

    return pd.DataFrame(
        {
            "t_wall": pd.to_numeric(df.get("t_wall"), errors="coerce"),
            "speed_px_s": speed,
        }
    )


def compute_summary(df: pd.DataFrame, cm_per_px: Optional[float] = None) -> Dict[str, Any]:
    if df.empty:
        return {
            "time_ch1_s": 0.0,
            "time_ch2_s": 0.0,
            "time_neutral_s": 0.0,
            "distance_px": 0.0,
            "distance_cm": np.nan,
            "mean_speed_px_s": 0.0,
            "mean_speed_cm_s": np.nan,
            "laser_on_time_s": 0.0,
            "session_duration_s": 0.0,
            "n_samples": 0,
        }

    dt = compute_dt_seconds(df)
    chamber = df.get("chamber", pd.Series(["unknown"] * len(df))).astype(str).str.lower()

    time_ch1_s = float(dt[chamber == "chamber1"].sum())
    time_ch2_s = float(dt[chamber == "chamber2"].sum())
    time_neutral_s = float(dt[chamber == "neutral"].sum())

    x = pd.to_numeric(df.get("x"), errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df.get("y"), errors="coerce").to_numpy(dtype=float)

    distance_px = 0.0
    if len(df) > 1:
        dx = np.diff(x)
        dy = np.diff(y)
        dist = np.sqrt(dx * dx + dy * dy)
        valid = np.isfinite(dist)
        distance_px = float(np.nansum(dist[valid]))

    session_duration_s = float(np.nansum(dt))
    mean_speed_px_s = distance_px / session_duration_s if session_duration_s > 0 else 0.0

    laser = pd.to_numeric(df.get("laser_state", 0), errors="coerce").fillna(0).to_numpy(dtype=float)
    laser_on_time_s = float(dt[laser > 0.5].sum())

    distance_cm = np.nan
    mean_speed_cm_s = np.nan
    if cm_per_px is not None:
        scale = float(cm_per_px)
        distance_cm = distance_px * scale
        mean_speed_cm_s = mean_speed_px_s * scale

    return {
        "time_ch1_s": time_ch1_s,
        "time_ch2_s": time_ch2_s,
        "time_neutral_s": time_neutral_s,
        "distance_px": distance_px,
        "distance_cm": distance_cm,
        "mean_speed_px_s": mean_speed_px_s,
        "mean_speed_cm_s": mean_speed_cm_s,
        "laser_on_time_s": laser_on_time_s,
        "session_duration_s": session_duration_s,
        "n_samples": int(len(df)),
    }
