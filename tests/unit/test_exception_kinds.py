"""2a：例外的三种写法——单日 date、连续几天 dates、按规律重复 rrule（配 valid）。

数据模型只认「三选一」；引擎对三种写法一视同仁：例外覆盖了那一天，就优先于基础规则。
日期速查（2026）：每月最后一个周一是 10-26、11-30、12-28；12-24 周四、12-27 周日。
"""

from datetime import date, time

import pytest
from pydantic import ValidationError

from travelkb.core.hours import is_open
from travelkb.core.models import Poi

EVERY_DAY = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
VALID = [date(2026, 10, 1), date(2026, 12, 31)]
LAST_MONDAY = "FREQ=MONTHLY;BYDAY=-1MO"
XMAS_EVE, XMAS, BOXING_DAY = date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 26)


def exc(exc_id, **fields):
    return {"id": exc_id, "reason": "测试用例外", **fields}


@pytest.fixture
def every_day_poi(make_poi):
    """一个天天 10–18 点开的假景点（周一也开，才能测「每月最后一个周一闭」）。"""
    rule = {"id": "r1", "valid": VALID, "days": EVERY_DAY, "open": "10:00", "close": "18:00"}

    def _make(*exceptions):
        return make_poi(rules=[rule], exceptions=list(exceptions))

    return _make


# ---- 数据模型：三选一 ----


def test_date_range_exception_parses(poi_dict):
    poi_dict["exceptions"] = [exc("e1", dates=[XMAS_EVE, BOXING_DAY], closed=True)]

    assert Poi.model_validate(poi_dict).exceptions[0].dates == (XMAS_EVE, BOXING_DAY)


def test_rrule_exception_parses(poi_dict):
    poi_dict["exceptions"] = [exc("e1", rrule=LAST_MONDAY, valid=VALID, closed=True)]

    assert Poi.model_validate(poi_dict).exceptions[0].rrule == LAST_MONDAY


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"date": XMAS, "dates": [XMAS_EVE, BOXING_DAY]},
        {"date": XMAS, "rrule": LAST_MONDAY, "valid": VALID},
        {"dates": [BOXING_DAY, XMAS_EVE]},
        {"rrule": LAST_MONDAY},
        {"rrule": "FREQ=SOMETIMES", "valid": VALID},
        # dateutil 会悄悄接受 DTSTART 并用它覆盖起点：起止只能写在 valid 里
        {"rrule": "DTSTART:20261001\nRRULE:FREQ=MONTHLY;BYDAY=-1MO", "valid": VALID},
        {"date": XMAS, "valid": VALID},
    ],
    ids=[
        "none_of_three",
        "date_and_dates",
        "date_and_rrule",
        "dates_reversed",
        "rrule_without_valid",
        "rrule_unparseable",
        "rrule_with_dtstart",
        "valid_without_rrule",
    ],
)
def test_malformed_exceptions_are_rejected(poi_dict, fields):
    poi_dict["exceptions"] = [exc("e1", closed=True, **fields)]

    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


# ---- 引擎：区间 ----


def test_date_range_covers_every_day_in_it(every_day_poi):
    poi = every_day_poi(exc("e1", dates=[XMAS_EVE, BOXING_DAY], closed=True))

    for day in (XMAS_EVE, XMAS, BOXING_DAY):  # 首尾两天都算在内
        result = is_open(poi, day)
        assert (result.status, result.reason_code, result.rule_ids) == (
            "CLOSED",
            "EXCEPTION",
            ["e1"],
        )
    for day in (date(2026, 12, 23), date(2026, 12, 27)):
        assert is_open(poi, day).status == "OPEN"


def test_date_range_can_change_hours_instead_of_closing(every_day_poi):
    poi = every_day_poi(
        exc("e1", dates=[XMAS_EVE, date(2026, 12, 31)], open="10:00", close="14:00")
    )

    result = is_open(poi, date(2026, 12, 30), time(15, 0))

    assert (result.status, result.reason_code) == ("CLOSED", "AFTER_CLOSING")
    assert result.close == time(14, 0)


# ---- 引擎：rrule ----


def test_rrule_closes_the_last_monday_of_each_month(every_day_poi):
    poi = every_day_poi(exc("e1", rrule=LAST_MONDAY, valid=VALID, closed=True))

    for day in (date(2026, 10, 26), date(2026, 11, 30), date(2026, 12, 28)):
        result = is_open(poi, day)
        assert (result.status, result.rule_ids) == ("CLOSED", ["e1"])
    # 前一周的周一、下个月第一个周一照常开
    for day in (date(2026, 10, 19), date(2026, 11, 2), date(2026, 11, 23), date(2026, 12, 21)):
        assert is_open(poi, day).status == "OPEN"


def test_rrule_only_applies_inside_its_own_valid(every_day_poi):
    october_only = [date(2026, 10, 1), date(2026, 10, 31)]
    poi = every_day_poi(exc("e1", rrule=LAST_MONDAY, valid=october_only, closed=True))

    assert is_open(poi, date(2026, 10, 26)).status == "CLOSED"
    assert is_open(poi, date(2026, 11, 30)).status == "OPEN"


# ---- 引擎：不同写法的例外撞在同一天 ----


def test_overlapping_exceptions_with_different_verdicts_are_unknown(every_day_poi):
    poi = every_day_poi(
        exc("e1", dates=[XMAS_EVE, BOXING_DAY], closed=True),
        exc("e2", date=XMAS, open="10:00", close="14:00"),
    )

    result = is_open(poi, XMAS)
    assert (result.status, result.reason_code, result.rule_ids) == (
        "UNKNOWN",
        "CONFLICT",
        ["e1", "e2"],
    )
    assert is_open(poi, XMAS_EVE).status == "CLOSED"  # 只有 e1 的日子不受影响
