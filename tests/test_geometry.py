import pytest
from PySide6.QtCore import QPointF, QRectF, QSizeF

from r2_companion.pet.positioning import clamp, from_normalized, legal_bounds, nearest_index, normalized


@pytest.mark.parametrize("area", [QRectF(0, 0, 1920, 1040), QRectF(-1920, -1080, 1920, 1080),
                                    QRectF(2560, 0, 1280, 680), QRectF(0, 1080, 400, 300)])
@pytest.mark.parametrize("anchor", [(0, 0), (1, 1), (0.5, 0.25), (0.85, 0.9)])
def test_normalized_position_round_trip(area, anchor):
    size = QSizeF(160, 160)
    point = from_normalized(*anchor, area, size)
    assert normalized(point, area, size) == pytest.approx(anchor)
    assert area.contains(QRectF(point, size))


def test_negative_origin_clamp():
    point = clamp(QPointF(-9000, 9000), QRectF(-1920, -1080, 1920, 1080), QSizeF(160, 160))
    assert point == QPointF(-1912, -168)


def test_zero_range_and_oversized_pet_do_not_invert_bounds():
    area, size = QRectF(-100, 50, 100, 100), QSizeF(200, 200)
    assert legal_bounds(area, size) == (-100, -100, 50, 50)
    assert normalized(QPointF(-100, 50), area, size) == (0.5, 0.5)


def test_monitor_gap_is_not_a_valid_screen():
    screens = [QRectF(-1920, 0, 1920, 1080), QRectF(2560, 0, 1280, 720)]
    assert nearest_index(QPointF(100, 100), screens) == 0
    assert nearest_index(QPointF(2400, 100), screens) == 1
    assert nearest_index(QPointF(-10, 50), screens) == 0
    with pytest.raises(ValueError):
        nearest_index(QPointF(), [])
