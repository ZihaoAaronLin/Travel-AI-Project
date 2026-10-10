"""2a：结论之外的建议和提醒。

- next_open_date：去不了的时候，下一个「确定能去」的日子（只在数据有效期内找，跳过 UNKNOWN 的日子）
- warnings：数据可能过期——核验后超过 14 天，结论不变，但提醒临时调整可能没收录（11/13 的教训）

假博物馆（见 conftest）：2026-10-01 ~ 2026-12-31 有效；周二到周日开，周一闭；核验日 2026-10-01。
日期速查：10-05 周一、10-06 周二、10-08 周四；12-26 周六、12-29 周二、12-31 周四。
"""

from datetime import date, time

import pytest

from travelkb.core.hours import is_open

MON, TUE, THU = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 8)


def exc(exc_id, **fields):
    return {"id": exc_id, "reason": "测试用例外", **fields}


# ---- next_open_date ----


def test_closed_day_suggests_the_next_open_day(make_poi):
    result = is_open(make_poi(), MON)

    assert result.status == "CLOSED"
    assert result.next_open_date == TUE


def test_suggestion_skips_consecutive_closed_days(make_poi):
    # 周六、周日例外闭馆，周一本来就闭 → 下一个能去的是周二
    poi = make_poi(
        exceptions=[exc("e1", dates=[date(2026, 12, 26), date(2026, 12, 27)], closed=True)]
    )

    assert is_open(poi, date(2026, 12, 26)).next_open_date == date(2026, 12, 29)


def test_suggestion_never_lands_on_an_unknown_day(poi_dict, make_poi):
    # 去掉周三的规则：周三是 UNKNOWN，不能被当成「能去」推荐出去
    r1 = {**poi_dict["rules"][0], "days": ["TUE", "THU", "FRI", "SAT", "SUN"]}
    poi = make_poi(rules=[r1, poi_dict["rules"][1]], exceptions=[exc("e1", date=TUE, closed=True)])

    assert is_open(poi, TUE).next_open_date == THU


def test_too_late_today_suggests_the_next_open_day(make_poi):
    result = is_open(make_poi(), TUE, time(17, 30))

    assert (result.status, result.reason_code) == ("CLOSED", "AFTER_LAST_ENTRY")
    assert result.next_open_date == date(2026, 10, 7)


@pytest.mark.parametrize(
    ("day", "at"),
    [
        (TUE, None),  # 开着，不需要建议
        (TUE, time(9, 0)),  # 还没开门：当天晚些就能进，看 open 字段就够了
        (date(2027, 1, 5), None),  # UNKNOWN：连今天都说不准，更不敢推荐别的日子
    ],
    ids=["open", "before_opening", "unknown"],
)
def test_no_suggestion_when_it_would_not_help(make_poi, day, at):
    assert is_open(make_poi(), day, at).next_open_date is None


def test_permanently_closed_has_no_next_open_day(make_poi):
    assert is_open(make_poi(status="PERMANENTLY_CLOSED"), TUE).next_open_date is None


def test_no_suggestion_beyond_the_data_window(make_poi):
    # 有效期最后一天闭馆：之后的日子数据没覆盖，不能推荐
    poi = make_poi(exceptions=[exc("e1", date=date(2026, 12, 31), closed=True)])

    result = is_open(poi, date(2026, 12, 31))
    assert result.status == "CLOSED"
    assert result.next_open_date is None


# ---- warnings：STALE ----


def test_no_warning_unless_caller_says_what_today_is(make_poi):
    # core 不调 now()（铁律 3）：不给 as_of 就不判断过期
    assert is_open(make_poi(), TUE).warnings == []


def test_data_checked_14_days_ago_is_still_fresh(make_poi):
    assert is_open(make_poi(), TUE, as_of=date(2026, 10, 15)).warnings == []


def test_data_older_than_14_days_warns_but_keeps_the_verdict(make_poi):
    result = is_open(make_poi(), date(2026, 10, 20), as_of=date(2026, 10, 16))

    assert result.status == "OPEN"  # 结论不变
    assert [w.code for w in result.warnings] == ["STALE"]
    assert "2026-10-01" in result.warnings[0].message  # 告诉用户数据是哪天核验的


def test_record_without_verification_date_gets_no_stale_warning(make_poi):
    poi = make_poi(rules=[], source_url=None, verified_at=None)

    assert is_open(poi, TUE, as_of=date(2027, 6, 1)).warnings == []
