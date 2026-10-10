"""2b：check_day_plan / find_open_pois 两个工具的接线。

判定逻辑在 test_day_plan / test_find_open 里测过，这里只测参数、序列化、报错。
"""

import datetime as dt

import pytest
from mcp import Client

from travelkb.server import build_server

NOW = dt.datetime(2026, 10, 2, 8, 0, tzinfo=dt.UTC)


@pytest.fixture
def pois(make_poi):
    return [
        make_poi(),
        make_poi(
            id="demo-twin",
            names={"local": None, "en": "Demo Twin", "zh": "示例分馆"},
            aliases=[],
        ),
    ]


@pytest.fixture
async def client(pois):
    async with Client(build_server(pois, clock=lambda: NOW), raise_exceptions=True) as c:
        yield c


def error_text(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


@pytest.mark.anyio
async def test_tools_are_registered_read_only_and_described(client: Client):
    tools = {t.name: t for t in (await client.list_tools()).tools}

    for name in ("check_day_plan", "find_open_pois"):
        assert tools[name].annotations.read_only_hint is True
    # 工具描述就是给模型的提示词
    assert "路上" in tools["check_day_plan"].description  # 不算路上时间，要说清楚
    assert "BLOCKER" in tools["check_day_plan"].description
    assert "resolve_poi" in tools["check_day_plan"].description  # 站点要先消歧
    assert "find_open_pois" in tools["check_day_plan"].description  # 闭馆了用它换
    assert "unverified" in tools["find_open_pois"].description


@pytest.mark.anyio
async def test_check_day_plan_serializes_for_the_model(client: Client):
    result = await client.call_tool(
        "check_day_plan",
        {
            "date": "2026-10-06",
            "stops": [
                {"poi_id": "demo-museum", "arrive": "09:30", "leave": "12:00"},
                {"poi_id": "demo-twin", "arrive": "17:30"},
            ],
        },
    )

    assert result.is_error is False
    content = result.structured_content
    assert content["ok"] is False
    assert (content["date"], content["weekday"]) == ("2026-10-06", "TUE")
    assert content["stops"][0]["arrive"] == "09:30"
    assert content["stops"][1]["leave"] is None
    assert content["stops"][0]["open"] == "10:00"
    assert [(i["id"], i["severity"], i["code"], i["stop_index"]) for i in content["issues"]] == [
        ("I1", "WARNING", "BEFORE_OPENING", 0),
        ("I2", "BLOCKER", "AFTER_LAST_ENTRY", 1),
    ]
    assert content["issues"][1]["fix"] == "ARRIVE_EARLIER"
    assert content["counts"] == {"BLOCKER": 1, "WARNING": 1, "UNKNOWN": 0}


@pytest.mark.anyio
async def test_check_day_plan_without_date_uses_poi_local_today(client: Client):
    # NOW 是 10-02 08:00 UTC：布达佩斯 10-02 周五；不给日期就查当天
    content = (
        await client.call_tool(
            "check_day_plan", {"stops": [{"poi_id": "demo-museum", "arrive": "11:00"}]}
        )
    ).structured_content

    assert (content["date"], content["weekday"]) == ("2026-10-02", "FRI")


@pytest.mark.anyio
async def test_unknown_stop_tells_the_model_to_resolve_first(client: Client):
    result = await client.call_tool(
        "check_day_plan",
        {"date": "2026-10-06", "stops": [{"poi_id": "示例博物馆", "arrive": "11:00"}]},
    )

    assert result.is_error is True
    assert "resolve_poi" in error_text(result)


@pytest.mark.anyio
@pytest.mark.parametrize("bad", ["9:30", "11am", "25:00"])
async def test_bad_stop_time_is_an_error(client: Client, bad):
    result = await client.call_tool(
        "check_day_plan",
        {"date": "2026-10-06", "stops": [{"poi_id": "demo-museum", "arrive": bad}]},
    )

    assert result.is_error is True
    assert "HH:MM" in error_text(result)


@pytest.mark.anyio
async def test_find_open_pois_serializes_for_the_model(client: Client):
    result = await client.call_tool(
        "find_open_pois", {"city": "Budapest", "date": "2026-10-06", "time": "16:00"}
    )

    assert result.is_error is False
    content = result.structured_content
    assert [p["poi_id"] for p in content["open"]] == ["demo-museum", "demo-twin"]
    assert content["open"][0]["last_entry"] == "17:00"
    assert content["unverified"] == []
    assert content["weekday"] == "TUE"
