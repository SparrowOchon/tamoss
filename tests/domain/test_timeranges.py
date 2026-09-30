from __future__ import annotations

from tamoss.domain.timeranges import timerange_from_bounds


def test_timerange_from_bounds_renders_half_open_point_and_missing_bounds() -> None:
    assert timerange_from_bounds(0, 10_000_000_000) == "[0:0_10:0)"
    assert timerange_from_bounds(10_000_000_000, 10_000_000_001) == "[10:0_10:1)"
    assert timerange_from_bounds(5_000_000_000, 5_000_000_000) == "[5:0]"
    assert timerange_from_bounds(None, 10_000_000_000) == "()"
    assert timerange_from_bounds(0, None) == "()"
