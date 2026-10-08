"""MCP 工具层：用内存客户端调 resolve_poi / is_open。

判定逻辑已在 test_is_open / test_resolve 里测过，这里只测「接线」：
参数怎么传、结果怎么序列化、错误怎么告诉模型、不给日期时「今天」怎么按景点时区算。
"""

import datetime as dt

import pytest
from mcp import Client

from travelkb.server import build_server

# 2026-10-11 23:30 UTC 这一刻：布达佩斯（夏令时 UTC+2）已是 10-12 周一 01:30，
# 纽约（夏令时 UTC-4）还是 10-11 周日 19:30。同一时刻，两地的「今天」不是同一天
FIXED_NOW = dt.datetime(2026, 10, 11, 23, 30, tzinfo=dt.UTC)


@pytest.fixture
def pois(make_poi):
    museum = make_poi()  # demo-museum：布达佩斯，周一闭馆，别名「示例馆」
    twin = make_poi(
        id="demo-twin",
        names={"local": None, "en": "Demo Twin", "zh": "示例分馆"},
        aliases=["示例馆"],
    )
    new_york = make_poi(
        id="demo-new-york",
        city="New York",
        country="US",
        tz="America/New_York",
        names={"local": None, "en": "Demo New York", "zh": "纽约示例馆"},
        aliases=[],
    )
    return [museum, twin, new_york]


@pytest.fixture
async def client(pois):
    # clock 注入固定时刻：server 里唯一允许取「现在」的地方，测试里必须可控
    server = build_server(pois, clock=lambda: FIXED_NOW)
    async with Client(server, raise_exceptions=True) as c:
        yield c


async def call(client: Client, tool: str, **args):
    return await client.call_tool(tool, args)


def error_text(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


# ---- 注册 ----


@pytest.mark.anyio
async def test_tools_are_registered_and_read_only(client: Client):
    tools = {t.name: t for t in (await client.list_tools()).tools}

    assert {"ping", "resolve_poi", "is_open"} <= tools.keys()
    for name in ("resolve_poi", "is_open"):
        assert tools[name].annotations.read_only_hint is True


@pytest.mark.anyio
async def test_descriptions_tell_the_model_how_to_use_the_tools(client: Client):
    # 工具描述就是给模型的提示词：先 resolve 再 is_open；AMBIGUOUS 要问用户；UNKNOWN 不能当开放
    tools = {t.name: t for t in (await client.list_tools()).tools}

    assert "AMBIGUOUS" in tools["resolve_poi"].description
    assert "resolve_poi" in tools["is_open"].description
    assert "UNKNOWN" in tools["is_open"].description


# ---- resolve_poi ----


@pytest.mark.anyio
async def test_resolve_poi_lists_every_candidate(client: Client):
    result = await call(client, "resolve_poi", query="示例馆")

    assert result.is_error is False
    content = result.structured_content
    assert content["status"] == "AMBIGUOUS"
    assert [c["poi_id"] for c in content["candidates"]] == ["demo-museum", "demo-twin"]
    assert content["candidates"][0]["name_zh"] == "示例博物馆"


@pytest.mark.anyio
async def test_resolve_poi_accepts_city(client: Client):
    result = await call(client, "resolve_poi", query="纽约示例馆", city="New York")

    assert result.structured_content["status"] == "MATCH"


@pytest.mark.anyio
async def test_blank_query_is_reported_to_the_model(client: Client):
    result = await call(client, "resolve_poi", query="   ")

    assert result.is_error is True
    assert "query" in error_text(result)


# ---- is_open：结果的写法 ----


@pytest.mark.anyio
async def test_is_open_serializes_dates_and_times_for_the_model(client: Client):
    result = await call(client, "is_open", poi_id="demo-museum", date="2026-10-06", time="17:30")

    assert result.is_error is False
    content = result.structured_content
    assert content["status"] == "CLOSED"
    assert content["reason_code"] == "AFTER_LAST_ENTRY"
    assert content["date"] == "2026-10-06"
    assert content["date_source"] == "caller"
    assert content["weekday"] == "TUE"
    assert content["time"] == "17:30"
    # 时刻一律 "HH:MM"，不带秒
    assert (content["open"], content["close"], content["last_entry"]) == ("10:00", "18:00", "17:00")
    assert content["rule_ids"] == ["r1"]
    assert content["source_url"] == "https://example.org/demo-museum/hours"
    assert content["verified_at"] == "2026-10-01"


@pytest.mark.anyio
async def test_is_open_without_time_judges_the_whole_day(client: Client):
    content = (
        await call(client, "is_open", poi_id="demo-museum", date="2026-10-06")
    ).structured_content

    assert content["status"] == "OPEN"
    assert content["time"] is None


# ---- is_open：不给日期时用景点当地的「今天」（铁律 3）----


@pytest.mark.anyio
async def test_missing_date_means_today_in_the_pois_own_timezone(client: Client):
    budapest = (await call(client, "is_open", poi_id="demo-museum")).structured_content
    new_york = (await call(client, "is_open", poi_id="demo-new-york")).structured_content

    assert (budapest["date"], budapest["weekday"]) == ("2026-10-12", "MON")
    assert budapest["status"] == "CLOSED"  # 布达佩斯已经到了周一，闭馆
    assert budapest["date_source"] == "poi_local_today"

    assert (new_york["date"], new_york["weekday"]) == ("2026-10-11", "SUN")
    assert new_york["status"] == "OPEN"  # 纽约还是周日


# ---- is_open：坏参数要以模型能读懂的方式报错 ----


@pytest.mark.anyio
async def test_unknown_poi_id_tells_the_model_to_resolve_first(client: Client):
    result = await call(client, "is_open", poi_id="布达佩斯美术馆", date="2026-10-06")

    assert result.is_error is True
    assert "resolve_poi" in error_text(result)


@pytest.mark.anyio
@pytest.mark.parametrize("bad_date", ["2026/10/06", "10-06", "2026-13-01", "next monday"])
async def test_bad_date_is_an_error(client: Client, bad_date):
    result = await call(client, "is_open", poi_id="demo-museum", date=bad_date)

    assert result.is_error is True
    assert "YYYY-MM-DD" in error_text(result)


@pytest.mark.anyio
@pytest.mark.parametrize("bad_time", ["9:00", "17:30:00", "5pm", "24:00"])
async def test_bad_time_is_an_error(client: Client, bad_time):
    result = await call(client, "is_open", poi_id="demo-museum", date="2026-10-06", time=bad_time)

    assert result.is_error is True
    assert "HH:MM" in error_text(result)


@pytest.mark.anyio
async def test_numeric_time_is_rejected_not_reinterpreted(client: Client):
    # 和 YAML 的坑一样：1730 不能被悄悄当成某个时刻
    result = await call(client, "is_open", poi_id="demo-museum", date="2026-10-06", time=1730)

    assert result.is_error is True
