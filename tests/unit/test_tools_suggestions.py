"""2a：is_open 工具把建议和提醒交给模型。

- next_open_date：去不了时下一个确定能去的日子（"YYYY-MM-DD"）
- warnings：[{code, message}]，目前只有 STALE
- 判断过期用的「今天」由 server 按景点当地日期算（铁律 3），不是 UTC 日期

假博物馆（见 conftest）：核验日 2026-10-01，周一闭馆。
"""

import datetime as dt

import pytest
from mcp import Client

from travelkb.server import build_server


async def is_open_at(pois, now: dt.datetime, **args) -> dict:
    """用固定时钟 now 起一个 server，调一次 is_open，返回 structured_content。"""
    async with Client(build_server(pois, clock=lambda: now), raise_exceptions=True) as client:
        result = await client.call_tool("is_open", args)
    assert result.is_error is False
    return result.structured_content


@pytest.mark.anyio
async def test_closed_day_comes_with_next_open_date(make_poi):
    now = dt.datetime(2026, 10, 2, 8, 0, tzinfo=dt.UTC)

    content = await is_open_at([make_poi()], now, poi_id="demo-museum", date="2026-10-05")

    assert content["status"] == "CLOSED"
    assert content["next_open_date"] == "2026-10-06"
    assert content["warnings"] == []


@pytest.mark.anyio
async def test_stale_warning_reaches_the_model(make_poi):
    now = dt.datetime(2026, 10, 16, 8, 0, tzinfo=dt.UTC)  # 核验后第 15 天

    content = await is_open_at([make_poi()], now, poi_id="demo-museum", date="2026-10-20")

    assert content["status"] == "OPEN"
    assert [w["code"] for w in content["warnings"]] == ["STALE"]
    assert "2026-10-01" in content["warnings"][0]["message"]


@pytest.mark.anyio
async def test_staleness_is_judged_by_the_pois_local_date(make_poi):
    # 2026-10-15 22:30 UTC：UTC 日期还是 10-15（第 14 天，不算过期），
    # 布达佩斯已是 10-16 00:30（第 15 天，过期）。应按景点当地日期判断
    now = dt.datetime(2026, 10, 15, 22, 30, tzinfo=dt.UTC)

    content = await is_open_at([make_poi()], now, poi_id="demo-museum", date="2026-10-20")

    assert [w["code"] for w in content["warnings"]] == ["STALE"]
