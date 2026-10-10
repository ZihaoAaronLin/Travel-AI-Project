"""2a：validate_data 对区间例外和 rrule 例外的检查。

例外覆盖的每一天都必须落在某条基础规则的有效期内（否则引擎第 1 步不采信，写了等于白写）；
不同写法的例外撞在同一天、结论又不同，就是冲突。
"""

from datetime import date

import pytest

from travelkb.core.validate import validate_pois

VERIFIED = date(2026, 10, 1)
WINDOW = [date(2026, 10, 1), date(2026, 12, 30)]  # 核验日起 90 天
EVERY_DAY = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
LAST_MONDAY = "FREQ=MONTHLY;BYDAY=-1MO"


def exc(exc_id, **fields):
    return {"id": exc_id, "reason": "测试用例外", **fields}


@pytest.fixture
def poi_with(make_poi):
    """已核对、有效期正好 90 天的假景点，只换例外。"""
    rule = {"id": "r1", "valid": WINDOW, "days": EVERY_DAY, "open": "10:00", "close": "18:00"}

    def _make(*exceptions):
        return make_poi(
            review="verified", rules=[rule], verified_at=VERIFIED, exceptions=list(exceptions)
        )

    return _make


def codes(issues):
    return [(i.level, i.code) for i in issues]


def test_range_and_rrule_inside_validity_are_fine(poi_with):
    poi = poi_with(
        exc("e1", dates=[date(2026, 12, 24), date(2026, 12, 26)], closed=True),
        exc("e2", rrule=LAST_MONDAY, valid=WINDOW, closed=True),
    )

    assert validate_pois([poi]) == []


def test_range_reaching_past_validity_is_an_error(poi_with):
    poi = poi_with(exc("e1", dates=[date(2026, 12, 29), date(2027, 1, 2)], closed=True))

    assert codes(validate_pois([poi])) == [("error", "EXCEPTION_NOT_COVERED")]


def test_rrule_occurring_past_validity_is_an_error(poi_with):
    # 规则只到 12-30，rrule 却写到 3 月：1–3 月的最后一个周一都不会被采信
    poi = poi_with(
        exc("e1", rrule=LAST_MONDAY, valid=[date(2026, 10, 1), date(2027, 3, 31)], closed=True)
    )

    assert codes(validate_pois([poi])) == [("error", "EXCEPTION_NOT_COVERED")]


def test_range_and_single_day_with_different_verdicts_conflict(poi_with):
    poi = poi_with(
        exc("e1", dates=[date(2026, 12, 24), date(2026, 12, 26)], closed=True),
        exc("e2", date=date(2026, 12, 25), open="10:00", close="14:00"),
    )

    issues = validate_pois([poi])
    assert codes(issues) == [("error", "EXCEPTION_CONFLICT")]
    assert "2026-12-25" in issues[0].message


def test_range_and_single_day_with_same_verdict_are_fine(poi_with):
    poi = poi_with(
        exc("e1", dates=[date(2026, 12, 24), date(2026, 12, 26)], closed=True),
        exc("e2", date=date(2026, 12, 25), closed=True),
    )

    assert validate_pois([poi]) == []
