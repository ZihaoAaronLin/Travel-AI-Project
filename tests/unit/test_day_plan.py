"""2b：check_day_plan——把一天的行程丢进去，逐站核验，问题逐条列出、每条带修复建议。

设计（Aaron 2026-10-10 定）：
- 严重级别：BLOCKER 必须改；WARNING 提醒；UNKNOWN 未核验（不算通过）
- 每个问题带编号、站点、fix（机器可读的修法）、suggestion（给模型看的一句话，含具体数值）
  模型逐条修完再调一次，直到没有 BLOCKER / UNKNOWN
- 不算路上时间

假数据（见 conftest）：demo-museum 周二到周日 10–18，17 点最后入场，周一闭馆。
日期速查：10-05 周一，10-06 周二。
"""

from datetime import date, time

import pytest

from travelkb.core.plan import Stop, check_day_plan

MON, TUE = date(2026, 10, 5), date(2026, 10, 6)


@pytest.fixture
def pois(make_poi):
    museum = make_poi()
    twin = make_poi(
        id="demo-twin",
        names={"local": None, "en": "Demo Twin", "zh": "示例分馆"},
        aliases=[],
    )
    park = make_poi(  # 没有官方来源：永远 UNKNOWN
        id="demo-park",
        category="park",
        names={"local": None, "en": "Demo Park", "zh": "示例公园"},
        aliases=[],
        rules=[],
        source_url=None,
        verified_at=None,
    )
    return [museum, twin, park]


def stop(poi_id, arrive, leave=None):
    return Stop(
        poi_id=poi_id, arrive=time.fromisoformat(arrive), leave=leave and time.fromisoformat(leave)
    )


def issue_codes(report):
    return [(i.severity, i.code, i.stop_index) for i in report.issues]


# ---- 通过 ----


def test_clean_plan_passes(pois):
    report = check_day_plan(
        pois, TUE, [stop("demo-museum", "10:30", "12:00"), stop("demo-twin", "13:00", "15:00")]
    )

    assert report.ok is True
    assert report.issues == []
    assert (report.date, report.weekday) == (TUE, "TUE")
    assert [s.status for s in report.stops] == ["OPEN", "OPEN"]
    assert report.stops[0].poi_id == "demo-museum"
    assert (report.stops[0].open, report.stops[0].last_entry) == (time(10), time(17))
    assert report.stops[0].source_url == "https://example.org/demo-museum/hours"


# ---- BLOCKER ----


def test_closed_day_is_a_blocker_with_a_date_to_move_to(pois):
    report = check_day_plan(pois, MON, [stop("demo-museum", "10:30", "12:00")])

    assert report.ok is False
    assert issue_codes(report) == [("BLOCKER", "CLOSED_DAY", 0)]
    issue = report.issues[0]
    assert issue.fix == "CHANGE_DATE"
    assert "2026-10-06" in issue.suggestion  # 下一个能去的日子
    assert "find_open_pois" in issue.suggestion  # 或者换一个当天开放的


def test_arriving_after_last_entry_is_a_blocker(pois):
    report = check_day_plan(pois, TUE, [stop("demo-museum", "17:30", "18:00")])

    assert issue_codes(report) == [("BLOCKER", "AFTER_LAST_ENTRY", 0)]
    assert report.issues[0].fix == "ARRIVE_EARLIER"
    assert "17:00" in report.issues[0].suggestion


def test_overlapping_stops_are_a_blocker(pois):
    report = check_day_plan(
        pois, TUE, [stop("demo-museum", "10:30", "13:30"), stop("demo-twin", "13:00", "15:00")]
    )

    assert issue_codes(report) == [("BLOCKER", "OVERLAP", 1)]
    issue = report.issues[0]
    assert issue.fix == "ARRIVE_LATER"
    assert "13:30" in issue.suggestion  # 要等上一站离开
    assert issue.related_stop_index == 0


def test_stops_out_of_order_count_as_overlap(pois):
    # 第二站比第一站还早到：没写 leave 时按到达时刻算
    report = check_day_plan(pois, TUE, [stop("demo-museum", "14:00"), stop("demo-twin", "11:00")])

    assert issue_codes(report) == [("BLOCKER", "OVERLAP", 1)]


# ---- WARNING：提醒，不算失败 ----


def test_arriving_before_opening_is_a_warning(pois):
    report = check_day_plan(pois, TUE, [stop("demo-museum", "09:30", "12:00")])

    assert report.ok is True
    assert issue_codes(report) == [("WARNING", "BEFORE_OPENING", 0)]
    assert report.issues[0].fix == "ARRIVE_LATER"
    assert "10:00" in report.issues[0].suggestion


def test_leaving_after_closing_is_a_warning(pois):
    report = check_day_plan(pois, TUE, [stop("demo-museum", "16:00", "19:00")])

    assert issue_codes(report) == [("WARNING", "LEAVE_AFTER_CLOSE", 0)]
    assert report.issues[0].fix == "LEAVE_EARLIER"
    assert "18:00" in report.issues[0].suggestion


# ---- UNKNOWN：未核验，不算通过 ----


def test_unverifiable_stop_is_unknown_not_pass(pois):
    report = check_day_plan(pois, TUE, [stop("demo-park", "10:00", "11:00")])

    assert report.ok is False
    assert issue_codes(report) == [("UNKNOWN", "UNVERIFIED", 0)]
    assert report.issues[0].fix == "CHECK_OFFICIAL"
    assert report.stops[0].status == "UNKNOWN"


def test_unknown_moment_is_unknown(pois, poi_dict, make_poi):
    # 官网只给了收费时段：时段外能不能进没写 → 这一站 UNKNOWN，而不是 CLOSED
    rule = {**poi_dict["rules"][0], "outside_hours": "UNKNOWN", "last_entry": None}
    rule = {k: v for k, v in rule.items() if v is not None}
    partial = make_poi(
        id="demo-partial",
        names={"local": None, "en": "P", "zh": "示例收费区"},
        aliases=[],
        rules=[rule],
    )

    report = check_day_plan([partial], TUE, [stop("demo-partial", "20:00", "21:00")])

    assert issue_codes(report) == [("UNKNOWN", "UNVERIFIED", 0)]


# ---- 问题清单的形状：能逐条解决 ----


def test_issues_are_numbered_in_stop_order(pois):
    report = check_day_plan(
        pois,
        TUE,
        [
            stop("demo-museum", "09:30", "12:00"),
            stop("demo-park", "12:30", "13:00"),
            stop("demo-twin", "17:30"),
        ],
    )

    assert [i.id for i in report.issues] == ["I1", "I2", "I3"]
    assert issue_codes(report) == [
        ("WARNING", "BEFORE_OPENING", 0),
        ("UNKNOWN", "UNVERIFIED", 1),
        ("BLOCKER", "AFTER_LAST_ENTRY", 2),
    ]
    assert report.counts == {"BLOCKER": 1, "WARNING": 1, "UNKNOWN": 1}


def test_fixing_the_issues_makes_the_plan_pass(pois):
    # 模型照建议改：10:00 到、把公园换掉、第三站提前到 16:00 → 再验通过
    before = check_day_plan(
        pois, TUE, [stop("demo-museum", "09:30", "12:00"), stop("demo-twin", "17:30")]
    )
    after = check_day_plan(
        pois, TUE, [stop("demo-museum", "10:00", "12:00"), stop("demo-twin", "16:00")]
    )

    assert before.ok is False
    assert after.ok is True and after.issues == []


# ---- 提醒：数据可能过期 ----


def test_stale_data_is_reported_once_per_poi(pois):
    report = check_day_plan(
        pois,
        date(2026, 10, 20),
        [stop("demo-museum", "10:30", "12:00"), stop("demo-museum", "14:00", "15:00")],
        as_of=date(2026, 10, 16),
    )

    assert report.ok is True
    assert [(w.poi_id, w.code) for w in report.warnings] == [("demo-museum", "STALE")]


# ---- 坏输入 ----


def test_unknown_poi_id_is_an_error(pois):
    with pytest.raises(ValueError, match="no-such-poi"):
        check_day_plan(pois, TUE, [stop("no-such-poi", "10:00")])


def test_leave_must_be_after_arrive(pois):
    with pytest.raises(ValueError):
        check_day_plan(pois, TUE, [stop("demo-museum", "12:00", "11:00")])


def test_empty_plan_is_an_error(pois):
    with pytest.raises(ValueError):
        check_day_plan(pois, TUE, [])
