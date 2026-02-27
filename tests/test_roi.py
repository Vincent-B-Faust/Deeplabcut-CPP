from cpp_dlc_live.realtime.roi import ChamberROI, PolygonROI, RectROI


def test_polygon_contains_inside_outside_boundary() -> None:
    roi = PolygonROI(points=[(0, 0), (10, 0), (10, 10), (0, 10)])
    assert roi.contains(5, 5)
    assert not roi.contains(20, 20)
    assert roi.contains(0, 5)
    assert roi.contains(10, 10)


def test_rect_contains() -> None:
    roi = RectROI(1, 2, 5, 6)
    assert roi.contains(1, 2)
    assert roi.contains(3, 4)
    assert roi.contains(5, 6)
    assert not roi.contains(0, 0)


def test_neutral_has_priority() -> None:
    ch1 = PolygonROI(points=[(0, 0), (10, 0), (10, 10), (0, 10)])
    ch2 = PolygonROI(points=[(20, 0), (30, 0), (30, 10), (20, 10)])
    neutral = PolygonROI(points=[(5, 0), (25, 0), (25, 10), (5, 10)])
    chamber = ChamberROI(chamber1=ch1, chamber2=ch2, neutral=neutral)

    assert chamber.classify(7, 5) == "neutral"
    assert chamber.classify(2, 5) == "chamber1"
    assert chamber.classify(27, 5) == "chamber2"
