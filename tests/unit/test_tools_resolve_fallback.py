"""resolve_poi 工具把回退的结果交给模型：matched_query 和认出来的城市。

接口：build_server(pois, ..., city_names=...)；正式运行时从 data/cities.yaml 读。
"""

import pytest
from mcp import Client

from travelkb.server import build_server


@pytest.fixture
def pois(make_poi):
    return [
        make_poi(
            id="demo-fine-arts",
            names={"local": None, "en": "A", "zh": "布达佩斯示例馆"},
            aliases=["示例馆"],
        ),
        make_poi(
            id="demo-gallery",
            names={"local": None, "en": "B", "zh": "示例国家馆"},
            aliases=["示例馆"],
        ),
    ]


@pytest.mark.anyio
async def test_tool_reports_how_it_matched(pois):
    server = build_server(pois, city_names={"Budapest": ["布达佩斯"]})
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("resolve_poi", {"query": "布达佩斯的示例馆"})

    content = result.structured_content
    assert content["status"] == "AMBIGUOUS"
    assert content["matched_query"] == "示例馆"
    assert content["city"] == "Budapest"
    assert [c["poi_id"] for c in content["candidates"]] == ["demo-fine-arts", "demo-gallery"]


@pytest.mark.anyio
async def test_description_tells_the_model_about_matched_query(pois):
    # 只认出一部分时，模型要告诉用户「是按哪个说法查到的」，工具描述里必须讲到这个字段
    async with Client(build_server(pois), raise_exceptions=True) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert "matched_query" in tools["resolve_poi"].description
