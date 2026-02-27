from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

Point = Tuple[float, float]


@dataclass
class ROI:
    def contains(self, x: float, y: float) -> bool:
        raise NotImplementedError

    def as_points(self) -> List[Point]:
        raise NotImplementedError


@dataclass
class RectROI(ROI):
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        self.x1, self.x2 = sorted((float(self.x1), float(self.x2)))
        self.y1, self.y2 = sorted((float(self.y1), float(self.y2)))

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def as_points(self) -> List[Point]:
        return [
            (self.x1, self.y1),
            (self.x2, self.y1),
            (self.x2, self.y2),
            (self.x1, self.y2),
        ]


@dataclass
class PolygonROI(ROI):
    points: List[Point]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("PolygonROI requires at least 3 points")
        self.points = [(float(x), float(y)) for x, y in self.points]

    @staticmethod
    def _point_on_segment(px: float, py: float, a: Point, b: Point, eps: float = 1e-9) -> bool:
        ax, ay = a
        bx, by = b
        cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
        if abs(cross) > eps:
            return False
        dot = (px - ax) * (px - bx) + (py - ay) * (py - by)
        return dot <= eps

    def contains(self, x: float, y: float) -> bool:
        px = float(x)
        py = float(y)

        n = len(self.points)
        for i in range(n):
            a = self.points[i]
            b = self.points[(i + 1) % n]
            if self._point_on_segment(px, py, a, b):
                return True

        inside = False
        for i in range(n):
            x1, y1 = self.points[i]
            x2, y2 = self.points[(i + 1) % n]
            intersects = ((y1 > py) != (y2 > py)) and (
                px < (x2 - x1) * (py - y1) / ((y2 - y1) + 1e-12) + x1
            )
            if intersects:
                inside = not inside
        return inside

    def as_points(self) -> List[Point]:
        return list(self.points)


@dataclass
class ChamberROI:
    chamber1: ROI
    chamber2: ROI
    neutral: Optional[ROI] = None
    strategy_on_neutral: str = "off"
    roi_type: str = "polygon"

    def classify(self, x: float, y: float) -> str:
        if self.neutral is not None and self.neutral.contains(x, y):
            return "neutral"
        if self.chamber1.contains(x, y):
            return "chamber1"
        if self.chamber2.contains(x, y):
            return "chamber2"
        return "unknown"

    def draw(self, frame: np.ndarray) -> np.ndarray:
        out = frame.copy()
        _draw_roi(out, self.chamber1, (0, 255, 0), "ch1")
        _draw_roi(out, self.chamber2, (0, 128, 255), "ch2")
        if self.neutral is not None:
            _draw_roi(out, self.neutral, (255, 255, 0), "neutral")
        return out

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "type": self.roi_type,
            "chamber1": [[float(x), float(y)] for x, y in self.chamber1.as_points()],
            "chamber2": [[float(x), float(y)] for x, y in self.chamber2.as_points()],
            "strategy_on_neutral": self.strategy_on_neutral,
        }
        if self.neutral is not None:
            data["neutral"] = [[float(x), float(y)] for x, y in self.neutral.as_points()]
        return data

    @classmethod
    def from_config(cls, roi_cfg: Dict[str, object]) -> "ChamberROI":
        roi_type = str(roi_cfg.get("type", "polygon")).lower().strip()
        chamber1 = _build_roi(roi_cfg.get("chamber1"), roi_type)
        chamber2 = _build_roi(roi_cfg.get("chamber2"), roi_type)
        neutral_cfg = roi_cfg.get("neutral")
        neutral = _build_roi(neutral_cfg, roi_type) if neutral_cfg else None
        strategy = str(roi_cfg.get("strategy_on_neutral", "off")).lower().strip()
        return cls(
            chamber1=chamber1,
            chamber2=chamber2,
            neutral=neutral,
            strategy_on_neutral=strategy,
            roi_type=roi_type,
        )


def _build_roi(raw_points: object, roi_type: str) -> ROI:
    if raw_points is None:
        raise ValueError("ROI points are required")
    if roi_type == "rect":
        return _build_rect(raw_points)
    points = _as_points(raw_points)
    return PolygonROI(points)


def _build_rect(raw_points: object) -> RectROI:
    if isinstance(raw_points, Sequence) and len(raw_points) == 4 and not isinstance(raw_points[0], Sequence):
        x1, y1, x2, y2 = raw_points  # type: ignore[misc]
        return RectROI(float(x1), float(y1), float(x2), float(y2))

    pts = _as_points(raw_points)
    if len(pts) == 2:
        (x1, y1), (x2, y2) = pts
        return RectROI(x1, y1, x2, y2)
    if len(pts) == 4:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return RectROI(min(xs), min(ys), max(xs), max(ys))
    raise ValueError("Rect ROI expects 2 points, 4 corner points, or [x1,y1,x2,y2]")


def _as_points(raw_points: object) -> List[Point]:
    if not isinstance(raw_points, Sequence):
        raise ValueError("ROI must be a sequence of points")
    points: List[Point] = []
    for p in raw_points:
        if not isinstance(p, Sequence) or len(p) != 2:
            raise ValueError("ROI point must be [x,y]")
        points.append((float(p[0]), float(p[1])))
    return points


def _draw_roi(frame: np.ndarray, roi: ROI, color: Tuple[int, int, int], label: str) -> None:
    pts = np.array(roi.as_points(), dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)
    x0, y0 = pts[0, 0, 0], pts[0, 0, 1]
    cv2.putText(frame, label, (int(x0), int(y0) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def calibrate_roi_with_frame(frame: np.ndarray, with_neutral: bool = True) -> Dict[str, List[List[int]]]:
    names = ["chamber1", "chamber2"] + (["neutral"] if with_neutral else [])
    points_by_roi: Dict[str, List[Tuple[int, int]]] = {}
    current_idx = 0
    current_points: List[Tuple[int, int]] = []

    win = "ROI Calibrator"

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and current_idx < len(names):
            current_points.append((x, y))

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)

    while True:
        canvas = frame.copy()

        for name, pts in points_by_roi.items():
            arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(canvas, [arr], True, (0, 255, 0), 2)
            cv2.putText(canvas, name, (arr[0, 0, 0], arr[0, 0, 1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        if current_idx < len(names):
            if len(current_points) > 1:
                arr = np.array(current_points, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(canvas, [arr], False, (0, 0, 255), 2)
            for x, y in current_points:
                cv2.circle(canvas, (x, y), 3, (0, 0, 255), -1)
            cv2.putText(
                canvas,
                f"ROI: {names[current_idx]} | click:add u:undo r:reset n:next s:save q:quit",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
        else:
            cv2.putText(
                canvas,
                "All ROI done | s:save q:quit",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

        cv2.imshow(win, canvas)
        key = cv2.waitKey(20) & 0xFF

        if key in (ord("q"), 27):
            cv2.destroyWindow(win)
            raise RuntimeError("ROI calibration cancelled by user")

        if key == ord("u") and current_points:
            current_points.pop()
        elif key == ord("r"):
            current_points.clear()
        elif key == ord("n"):
            if current_idx >= len(names):
                continue
            if len(current_points) < 3:
                continue
            points_by_roi[names[current_idx]] = list(current_points)
            current_points.clear()
            current_idx += 1
        elif key == ord("s"):
            if current_idx < len(names):
                if len(current_points) >= 3:
                    points_by_roi[names[current_idx]] = list(current_points)
                    current_points.clear()
                    current_idx += 1
                else:
                    continue
            if all(name in points_by_roi for name in names):
                break

    cv2.destroyWindow(win)
    return {name: [[int(x), int(y)] for x, y in pts] for name, pts in points_by_roi.items()}
