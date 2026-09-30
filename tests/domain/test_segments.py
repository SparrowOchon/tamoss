from __future__ import annotations

from tamoss.domain.segments import missing_timerange_bounds


def test_missing_timerange_bounds_reports_leading_interior_and_trailing_gaps() -> None:
    assert missing_timerange_bounds([(10, 20), (30, 40)], start=0, end=50) == [
        (0, 10),
        (20, 30),
        (40, 50),
    ]
    assert missing_timerange_bounds([], start=10, end=20) == [(10, 20)]


def test_missing_timerange_bounds_merges_touching_and_straddling_segments() -> None:
    assert missing_timerange_bounds(
        [(30, 45), (5, 12), (12, 20), (18, 25)], start=10, end=40
    ) == [(25, 30)]


def test_missing_timerange_bounds_is_empty_when_the_window_is_covered() -> None:
    assert missing_timerange_bounds([(0, 100)], start=10, end=20) == []
    assert missing_timerange_bounds([(10, 15), (15, 20)], start=10, end=20) == []
