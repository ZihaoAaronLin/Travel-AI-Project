"""2b：find_open_pois——某城某天（某时）确定开放的景点，给模型替换闭馆站点用。

只列结论是 OPEN 的；说不准的单独列在 unverified 里，让模型知道「不是没有，是没法核验」。
假数据（见 conftest）：demo-museum 周二到周日 10–18、17 点最后入场；10-05 周一，10-06 周二。
"""

from datetime import date, time

import pytest

from travelkb.core.plan import find_open_pois

MON, TUE = date(2026, 10, 5), date(2026, 10, 6)


@pytest.fixture
def pois(make_poi):
    return [
        make_poi(),
        make_poi(
            id="demo-twin",
            category="gallery",
            names={"local": None, "en": "Demo Twin", "zh": "示例分馆"},
            aliases=[],
        ),
        make_poi(
            id="demo-park",
            category="park",
            names={"local": None, "en": "Demo Park", "zh": "示例公园"},
            aliases=[],
            rules=[],
            source_url=None,
            verified_at=None,
        ),
        make_poi(
            id="demo-vienna",
            city="Vienna",
            country="AT",
            tz="Europe/Vienna",
            names={"local": None, "en": "Vienna Demo", "zh": "维也纳示例馆"},
            aliases=[],
        ),
    ]


def open_ids(result):
    return [p.poi_id for p in result.open]


def test_lists_only_pois_that_are_open_that_day(pois):
    result = find_open_pois(pois, "Budapest", TUE)

    assert open_ids(result) == ["demo-museum", "demo-twin"]  # 按 id 排序，不暗示优先级
    assert result.unverified == ["demo-park"]
    assert (result.date, result.weekday) == (TUE, "TUE")


def test_closed_day_yields_nothing_but_still_names_the_unverified(pois):
    result = find_open_pois(pois, "Budapest", MON)

    assert open_ids(result) == []
    assert result.unverified == ["demo-park"]


def test_time_filters_by_whether_you_can_still_get_in(pois):
    assert open_ids(find_open_pois(pois, "Budapest", TUE, at=time(16, 0))) == [
        "demo-museum",
        "demo-twin",
    ]
    assert open_ids(find_open_pois(pois, "Budapest", TUE, at=time(17, 30))) == []


def test_category_filter(pois):
    result = find_open_pois(pois, "Budapest", TUE, category="gallery")

    assert open_ids(result) == ["demo-twin"]
    assert result.unverified == []  # 公园不是 gallery，也不列


def test_city_is_matched_loosely_and_required(pois):
    assert open_ids(find_open_pois(pois, "budapest", TUE)) == ["demo-museum", "demo-twin"]
    assert open_ids(find_open_pois(pois, "Vienna", TUE)) == ["demo-vienna"]
    assert open_ids(find_open_pois(pois, "Prague", TUE)) == []
    with pytest.raises(ValueError):
        find_open_pois(pois, "  ", TUE)


def test_each_hit_carries_what_the_model_needs_to_replace_a_stop(pois):
    hit = find_open_pois(pois, "Budapest", TUE).open[0]

    assert hit.poi_id == "demo-museum"
    assert hit.name_zh == "示例博物馆"
    assert hit.category == "museum"
    assert (hit.open, hit.close, hit.last_entry) == (time(10), time(18), time(17))
    assert hit.source_url == "https://example.org/demo-museum/hours"
