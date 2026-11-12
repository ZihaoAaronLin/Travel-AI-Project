"""评测用：把 server 的「今天」钉在某一天（环境变量 TRAVELKB_TODAY）。

为什么要：评测题按「今天是 2026-10-10」出题（数据 10-08 核验），跑评测时真实日期已过一个多月。
server 用真实时钟的话，A3 / A4 每次 is_open 都会带 STALE 提醒，不给日期时还会查成真实的今天，
答错 / 弃答里就混进了「跑评测那天数据已过期」这个和题目无关的因素。

接口：
- TODAY_ENV = "TRAVELKB_TODAY"；run.py 生成 mcp.json 时用同一个常量
- today_from_env(env) -> date | None：没设是 None；设了就必须是 YYYY-MM-DD，否则启动时报错，
  不能悄悄退回真实时钟（那样评测照跑，结果却是错的）
- build_server(pois, clock, today=...)：today 给定时，三个工具的「今天」都是它，
  既当默认日期，也用来判断过期；它就是景点当地的今天，不再按时区换算
"""

import datetime as dt

import pytest
from mcp import Client

from travelkb.server import TODAY_ENV, build_server, today_from_env

# 真实时钟：假博物馆核验（10-01）后第 50 天，不钉的话一定 STALE
REAL_NOW = dt.datetime(2026, 11, 20, 8, 0, tzinfo=dt.UTC)
PINNED = dt.date(2026, 10, 5)  # 周一，假博物馆闭馆；核验后第 4 天，不过期


async def call(pois, tool: str, today: dt.date | None, **args) -> dict:
    server = build_server(pois, clock=lambda: REAL_NOW, today=today)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error is False
    return result.structured_content


# ---- 读环境变量 ----


def test_env_name_is_the_documented_one():
    assert TODAY_ENV == "TRAVELKB_TODAY"


def test_unset_means_real_clock():
    assert today_from_env({}) is None


def test_iso_date_is_parsed():
    assert today_from_env({TODAY_ENV: "2026-10-10"}) == dt.date(2026, 10, 10)


@pytest.mark.parametrize("bad", ["2026-10-1", "10/10/2026", "today", "", "2026-02-30"])
def test_bad_value_fails_loudly(bad):
    with pytest.raises(ValueError, match=TODAY_ENV):
        today_from_env({TODAY_ENV: bad})


# ---- 三个工具都用钉住的今天 ----


@pytest.mark.anyio
async def test_is_open_defaults_to_pinned_today(make_poi):
    content = await call([make_poi()], "is_open", PINNED, poi_id="demo-museum")

    assert content["date"] == "2026-10-05"
    assert content["date_source"] == "poi_local_today"
    assert content["status"] == "CLOSED"


@pytest.mark.anyio
async def test_pinned_today_decides_staleness(make_poi):
    content = await call([make_poi()], "is_open", PINNED, poi_id="demo-museum", date="2026-10-06")

    assert content["status"] == "OPEN"
    assert content["warnings"] == []


@pytest.mark.anyio
async def test_without_pin_the_real_clock_still_decides(make_poi):
    # 对照组：同一个真实时钟、不钉 → 过期提醒还在。证明上一条的「没提醒」来自钉日期，不是碰巧
    content = await call([make_poi()], "is_open", None, poi_id="demo-museum", date="2026-10-06")

    assert [w["code"] for w in content["warnings"]] == ["STALE"]


@pytest.mark.anyio
async def test_check_day_plan_defaults_to_pinned_today(make_poi):
    content = await call(
        [make_poi()], "check_day_plan", PINNED, stops=[{"poi_id": "demo-museum", "arrive": "11:00"}]
    )

    assert content["date"] == "2026-10-05"
    assert content["ok"] is False  # 周一闭馆


@pytest.mark.anyio
async def test_find_open_pois_defaults_to_pinned_today(make_poi):
    content = await call([make_poi()], "find_open_pois", PINNED, city="Budapest")

    assert content["date"] == "2026-10-05"
    assert content["open"] == []


@pytest.mark.anyio
async def test_pinned_today_is_the_same_day_in_every_time_zone(make_poi):
    # 钉的就是景点当地的今天。真实时钟换算的话，奥克兰（UTC+13）和纽约（UTC-5）
    # 可能差一天；钉住之后不该再被时区推前推后
    pois = [
        make_poi(id="demo-auckland", city="Auckland", country="NZ", tz="Pacific/Auckland"),
        make_poi(id="demo-new-york", city="New York", country="US", tz="America/New_York"),
    ]
    for poi_id in ("demo-auckland", "demo-new-york"):
        content = await call(pois, "is_open", PINNED, poi_id=poi_id)
        assert content["date"] == "2026-10-05"
