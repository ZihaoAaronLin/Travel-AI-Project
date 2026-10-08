"""is_open 的规则语义（docs/ROADMAP.md 第 7 节），按判定步骤分组。

假博物馆（见 conftest）：2026-10-01 ~ 2026-12-31 有效；
周二到周日 10–18 点，17 点最后入场；周一闭馆。
日期速查：10-05 周一，10-06 周二，10-09 周五，10-11 周日。
"""

from datetime import date, time

import pytest

from travelkb.core.hours import is_open

MON = date(2026, 10, 5)
TUE = date(2026, 10, 6)
FRI = date(2026, 10, 9)
TUE_NOV = date(2026, 11, 3)


def exception(exc_id, day, **fields):
    return {"id": exc_id, "date": day, "reason": "测试用例外", **fields}


# ---- 每个结论都带可追溯的依据（铁律 4）----


def test_open_result_carries_hours_and_provenance(make_poi):
    result = is_open(make_poi(), TUE)

    assert result.status == "OPEN"
    assert result.reason_code == "WEEKLY_RULE"
    assert result.reason  # 给模型看的一句话说明，不能为空
    assert result.poi_id == "demo-museum"
    assert result.date == TUE
    assert result.weekday == "TUE"
    assert result.rule_ids == ["r1"]
    assert (result.open, result.close, result.last_entry) == (time(10), time(18), time(17))
    assert result.source_url == "https://example.org/demo-museum/hours"
    assert result.verified_at == date(2026, 10, 1)


@pytest.mark.parametrize(
    ("day", "weekday"),
    [(date(2026, 10, 5), "MON"), (date(2026, 10, 10), "SAT"), (date(2026, 10, 11), "SUN")],
)
def test_weekday_is_computed_by_code(make_poi, day, weekday):
    # 模型常把星期几算错，所以由代码算好放进结果
    assert is_open(make_poi(), day).weekday == weekday


# ---- 第 0 步：营业状态 ----


def test_permanently_closed_is_closed_on_any_date(make_poi):
    poi = make_poi(status="PERMANENTLY_CLOSED")

    for day in (TUE, date(2030, 1, 1)):  # 有效期外也一样：永久停业不会因为日期变化而恢复
        result = is_open(poi, day)
        assert result.status == "CLOSED"
        assert result.reason_code == "PERMANENTLY_CLOSED"
        assert result.rule_ids == ["status"]


def test_temporarily_closed_without_dates_is_unknown(make_poi):
    # 「暂时关闭」没说哪天恢复：不能答 OPEN，也不能保证那天还关着
    result = is_open(make_poi(status="TEMP_CLOSED"), TUE)

    assert result.status == "UNKNOWN"
    assert result.reason_code == "TEMP_CLOSED"


# ---- 第 1 步：有效期覆盖 ----


@pytest.mark.parametrize("day", [date(2026, 9, 29), date(2027, 1, 5)])
def test_date_outside_every_rule_is_unknown(make_poi, day):
    result = is_open(make_poi(), day)

    assert result.status == "UNKNOWN"
    assert result.reason_code == "NOT_COVERED"
    assert result.rule_ids == []
    assert result.source_url == "https://example.org/demo-museum/hours"  # 让用户知道去哪查


def test_validity_bounds_are_inclusive(make_poi):
    assert is_open(make_poi(), date(2026, 10, 1)).status == "OPEN"  # 周四，有效期第一天
    assert is_open(make_poi(), date(2026, 12, 31)).status == "OPEN"  # 周四，有效期最后一天


def test_poi_without_rules_is_unknown(make_poi):
    poi = make_poi(rules=[], source_url=None, verified_at=None)

    result = is_open(poi, TUE)

    assert result.status == "UNKNOWN"
    assert result.reason_code == "NOT_COVERED"


def test_exception_outside_coverage_does_not_count(make_poi):
    # 有效期是对整份数据的信任窗口：窗口外的例外也不采信，validate_data 会单独报错
    poi = make_poi(exceptions=[exception("e1", date(2027, 1, 5), closed=True)])

    assert is_open(poi, date(2027, 1, 5)).reason_code == "NOT_COVERED"


# ---- 第 2 步：单日例外优先于基础规则 ----


def test_closed_exception_overrides_weekly_rule(make_poi):
    poi = make_poi(exceptions=[exception("e1", TUE, closed=True)])

    result = is_open(poi, TUE)

    assert result.status == "CLOSED"
    assert result.reason_code == "EXCEPTION"
    assert result.rule_ids == ["e1"]
    assert result.reason  # 带上例外的原因


def test_changed_hours_exception_overrides_weekly_rule(make_poi):
    poi = make_poi(
        exceptions=[exception("e1", FRI, open="12:00", close="20:00", last_entry="19:00")]
    )

    result = is_open(poi, FRI)

    assert result.status == "OPEN"
    assert result.rule_ids == ["e1"]
    assert (result.open, result.close, result.last_entry) == (time(12), time(20), time(19))


def test_exception_can_open_a_normally_closed_day(make_poi):
    poi = make_poi(exceptions=[exception("e1", MON, open="10:00", close="16:00")])

    assert is_open(poi, MON).status == "OPEN"


def test_exception_only_affects_its_own_date(make_poi):
    poi = make_poi(exceptions=[exception("e1", TUE, closed=True)])

    assert is_open(poi, date(2026, 10, 7)).status == "OPEN"  # 第二天周三照常


def test_conflicting_exceptions_on_same_date_are_unknown(make_poi):
    poi = make_poi(
        exceptions=[
            exception("e1", TUE, closed=True),
            exception("e2", TUE, open="10:00", close="14:00"),
        ]
    )

    result = is_open(poi, TUE)

    assert result.status == "UNKNOWN"
    assert result.reason_code == "CONFLICT"
    assert result.rule_ids == ["e1", "e2"]


def test_agreeing_exceptions_on_same_date_are_not_a_conflict(make_poi):
    poi = make_poi(
        exceptions=[exception("e1", TUE, closed=True), exception("e2", TUE, closed=True)]
    )

    result = is_open(poi, TUE)

    assert result.status == "CLOSED"
    assert result.rule_ids == ["e1", "e2"]


# ---- 第 3 步：当天星期对应的基础规则 ----


def test_weekly_closed_day_is_closed(make_poi):
    result = is_open(make_poi(), MON)

    assert result.status == "CLOSED"
    assert result.reason_code == "WEEKLY_RULE"
    assert result.rule_ids == ["r2"]
    assert (result.open, result.close, result.last_entry) == (None, None, None)


def test_weekday_without_a_rule_is_unknown_not_closed(poi_dict, make_poi):
    # 官网只列了开放日、没写某个星期：那天不能当成闭馆，更不能当成开放
    rules = [r for r in poi_dict["rules"] if r["id"] != "r2"]  # 去掉周一闭馆规则

    result = is_open(make_poi(rules=rules), MON)

    assert result.status == "UNKNOWN"
    assert result.reason_code == "NO_RULE_FOR_WEEKDAY"


def test_conflicting_weekly_rules_are_unknown(poi_dict, make_poi):
    rules = poi_dict["rules"] + [
        {
            "id": "r3",
            "valid": [date(2026, 10, 1), date(2026, 10, 31)],
            "days": ["TUE"],
            "closed": True,
        }
    ]
    poi = make_poi(rules=rules)

    result = is_open(poi, TUE)
    assert result.status == "UNKNOWN"
    assert result.reason_code == "CONFLICT"
    assert result.rule_ids == ["r1", "r3"]

    # r3 只管 10 月：11 月的周二只剩 r1，不再冲突
    assert is_open(poi, TUE_NOV).status == "OPEN"


def test_agreeing_weekly_rules_are_not_a_conflict(poi_dict, make_poi):
    duplicate = {**poi_dict["rules"][0], "id": "r3", "days": ["TUE"]}

    result = is_open(make_poi(rules=poi_dict["rules"] + [duplicate]), TUE)

    assert result.status == "OPEN"
    assert result.rule_ids == ["r1", "r3"]


# ---- 第 4 步：给了时刻，判断那一刻能不能入场 ----


@pytest.mark.parametrize("at", [time(10, 0), time(13, 30), time(17, 0)])
def test_entry_allowed_from_opening_through_last_entry(make_poi, at):
    result = is_open(make_poi(), TUE, at)

    assert result.status == "OPEN"
    assert result.at == at


def test_before_opening_is_closed_and_says_when_it_opens(make_poi):
    result = is_open(make_poi(), TUE, time(9, 59))

    assert result.status == "CLOSED"
    assert result.reason_code == "BEFORE_OPENING"
    assert result.open == time(10)  # 模型可以据此建议几点到


def test_after_last_entry_is_closed_even_though_building_is_open(make_poi):
    result = is_open(make_poi(), TUE, time(17, 1))

    assert result.status == "CLOSED"
    assert result.reason_code == "AFTER_LAST_ENTRY"
    assert result.last_entry == time(17)


def test_without_last_entry_entry_is_allowed_until_closing(poi_dict, make_poi):
    rule = {k: v for k, v in poi_dict["rules"][0].items() if k != "last_entry"}
    poi = make_poi(rules=[rule, poi_dict["rules"][1]])

    assert is_open(poi, TUE, time(17, 59)).status == "OPEN"
    result = is_open(poi, TUE, time(18, 0))  # 关门那一刻已经不能进
    assert result.status == "CLOSED"
    assert result.reason_code == "AFTER_CLOSING"


def test_outside_hours_unknown_rule_answers_unknown_outside_its_hours(poi_dict, make_poi):
    # 例：官网只给了收费时段，时段外能不能进没写
    rule = {
        "id": "r1",
        "valid": poi_dict["rules"][0]["valid"],
        "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
        "open": "09:00",
        "close": "19:00",
        "outside_hours": "UNKNOWN",
    }
    poi = make_poi(rules=[rule])

    assert is_open(poi, TUE).status == "OPEN"  # 不给时刻：当天至少这段时间能进
    assert is_open(poi, TUE, time(12)).status == "OPEN"
    for at in (time(8, 0), time(20, 0)):
        result = is_open(poi, TUE, at)
        assert result.status == "UNKNOWN"
        assert result.reason_code == "OUTSIDE_KNOWN_HOURS"


def test_time_check_uses_exception_hours(make_poi):
    poi = make_poi(
        exceptions=[exception("e1", FRI, open="12:00", close="20:00", last_entry="19:00")]
    )

    result = is_open(poi, FRI, time(11, 0))  # 平时 11 点能进，这天 12 点才开
    assert result.status == "CLOSED"
    assert result.reason_code == "BEFORE_OPENING"
    assert result.rule_ids == ["e1"]

    assert is_open(poi, FRI, time(18, 30)).status == "OPEN"  # 平时已过最后入场，这天还能进


def test_time_on_a_closed_day_is_closed(make_poi):
    result = is_open(make_poi(), MON, time(12))

    assert result.status == "CLOSED"
    assert result.reason_code == "WEEKLY_RULE"


def test_time_on_an_unknown_day_stays_unknown(make_poi):
    result = is_open(make_poi(), date(2027, 1, 5), time(12))

    assert result.status == "UNKNOWN"
    assert result.reason_code == "NOT_COVERED"
