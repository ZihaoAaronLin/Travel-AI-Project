"""数据模型：坏数据在加载时就报错，而不是等到查询时才答错。"""

from datetime import date, time

import pytest
from pydantic import ValidationError

from travelkb.core.models import Poi


def test_valid_poi_parses(poi_dict):
    poi = Poi.model_validate(poi_dict)

    assert poi.rules[0].open == time(10, 0)
    assert poi.rules[0].last_entry == time(17, 0)
    assert poi.rules[1].closed is True
    assert poi.rules[0].valid == (date(2026, 10, 1), date(2026, 12, 31))


# ---- 时间字段 ----


def test_unquoted_time_is_rejected(poi_dict):
    # YAML 里不加引号的 10:00 会被解析成整数 600；
    # pydantic 默认会把 600 悄悄当成 00:10（UTC），所以必须显式拒绝非字符串
    poi_dict["rules"][0]["open"] = 600
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


@pytest.mark.parametrize("bad", ["9:00", "10:00:00", "10.00", "25:00", "10:60"])
def test_time_must_be_hh_mm(poi_dict, bad):
    poi_dict["rules"][0]["open"] = bad
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


# ---- 规则的形状：要么闭馆，要么给出完整时段 ----


def test_closed_rule_cannot_have_hours(poi_dict):
    poi_dict["rules"][1]["open"] = "10:00"
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_open_rule_needs_both_open_and_close(poi_dict):
    del poi_dict["rules"][0]["close"]
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_rule_needs_either_closed_or_hours(poi_dict):
    poi_dict["rules"][1]["closed"] = False
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_open_must_be_before_close(poi_dict):
    poi_dict["rules"][0].update({"open": "18:00", "close": "10:00", "last_entry": "12:00"})
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


@pytest.mark.parametrize("bad", ["09:30", "18:30"])
def test_last_entry_must_be_within_opening_hours(poi_dict, bad):
    poi_dict["rules"][0]["last_entry"] = bad
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_valid_range_must_be_ordered(poi_dict):
    poi_dict["rules"][0]["valid"] = [date(2026, 12, 31), date(2026, 10, 1)]
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_unknown_weekday_is_rejected(poi_dict):
    poi_dict["rules"][1]["days"] = ["MONDAY"]
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


# ---- outside_hours：官网只给了部分时段（如收费时段）时，时段外答 UNKNOWN 而不是 CLOSED ----


def test_outside_hours_defaults_to_closed(poi_dict):
    poi = Poi.model_validate(poi_dict)
    assert poi.rules[0].outside_hours == "CLOSED"


def test_outside_hours_accepts_unknown(poi_dict):
    poi_dict["rules"][0]["outside_hours"] = "UNKNOWN"
    poi = Poi.model_validate(poi_dict)
    assert poi.rules[0].outside_hours == "UNKNOWN"


def test_outside_hours_cannot_be_open(poi_dict):
    poi_dict["rules"][0]["outside_hours"] = "OPEN"
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


# ---- 例外：第 1 阶段只支持单日例外 ----


def test_single_day_exception_parses(poi_dict):
    poi_dict["exceptions"] = [
        {"id": "e1", "date": date(2026, 10, 6), "closed": True, "reason": "假日闭馆"}
    ]
    poi = Poi.model_validate(poi_dict)
    assert poi.exceptions[0].date == date(2026, 10, 6)


def test_exception_needs_reason(poi_dict):
    poi_dict["exceptions"] = [{"id": "e1", "date": date(2026, 10, 6), "closed": True}]
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_rrule_exception_is_rejected_in_stage_1(poi_dict):
    # 不认识的字段一律报错：否则 rrule 会被静默忽略，那天就会错答成 OPEN
    poi_dict["exceptions"] = [
        {
            "id": "e1",
            "date": date(2026, 10, 6),
            "rrule": "FREQ=MONTHLY;BYDAY=-1MO",
            "closed": True,
            "reason": "每月最后一个周一闭馆",
        }
    ]
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_unknown_top_level_field_is_rejected(poi_dict):
    poi_dict["opening_hours"] = "10-18"
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


# ---- 其他字段 ----


def test_rule_and_exception_ids_must_be_unique(poi_dict):
    # rule_id 是返回给模型的审计线索，同一个景点里不能重名
    poi_dict["exceptions"] = [
        {"id": "r1", "date": date(2026, 10, 6), "closed": True, "reason": "假日闭馆"}
    ]
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


@pytest.mark.parametrize(
    ("field", "bad"),
    [("status", "DRAFT"), ("review", "maybe"), ("tz", "Europe/Budapes")],
)
def test_enumerated_fields_are_checked(poi_dict, field, bad):
    poi_dict[field] = bad
    with pytest.raises(ValidationError):
        Poi.model_validate(poi_dict)


def test_poi_without_rules_or_source_is_allowed(poi_dict):
    # 没有官方来源的部分（如渔人堡免费区域）也要能建记录，好让同名追问把它列出来
    poi_dict.update({"rules": [], "source_url": None, "verified_at": None})
    poi = Poi.model_validate(poi_dict)
    assert poi.rules == []
